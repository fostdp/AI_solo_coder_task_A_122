"""
LoRa Ingest Service - 采集服务
负责:
  1. 接收 LoRa 上行数据 (HTTP API 入口)
  2. CSMA/CA 退避 + 去重
  3. 批量写入 ClickHouse (异步队列)
  4. 发布到 Redis Stream (sensor_raw) 供下游服务消费
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any

from shared.config_loader import get_redis_config, get_lora_config
from shared.redis_streams import RedisStreamClient
from shared.clickhouse_client import get_client, insert_rows
from .backoff import LoRaBackoff
from .deduplicator import MessageDeduplicator

logger = logging.getLogger(__name__)


class LoraIngestService:
    """
    LoRa 数据采集服务

    架构:
    HTTP POST /readings
        -> de-dup (去重)
        -> queue (异步队列)
        -> batch flush (ClickHouse)
        -> redis stream xadd (广播给下游服务)
    """

    def __init__(self, redis_client: RedisStreamClient | None = None):
        self._deduplicator = MessageDeduplicator()
        self._backoffs: Dict[int, LoRaBackoff] = {}
        self._redis = redis_client

        cfg = get_lora_config()
        self._stream_name = get_redis_config()["streams"]["sensor_raw"]
        self._flush_interval = 2.0  # 秒
        self._flush_size = 500
        self._max_queue = 8000

        self._sensor_queue: asyncio.Queue | None = None
        self._aw_queue: asyncio.Queue | None = None
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self._ch_client = None
        self._db_name = None

    # === 生命周期 ===
    async def start(self, loop=None):
        if self._running:
            return

        if self._redis is None:
            rc = get_redis_config()
            self._redis = RedisStreamClient(
                host=rc["host"], port=rc["port"], db=rc["db"],
                password=rc.get("password", ""),
            )
            await self._redis.connect()

        ch_cfg = __import__("shared.config_loader", fromlist=["get_clickhouse_config"]).get_clickhouse_config()
        self._ch_client = get_client(
            host=ch_cfg["host"], port=ch_cfg["port"],
            user=ch_cfg["user"], password=ch_cfg["password"],
            database=ch_cfg["database"],
        )
        self._db_name = ch_cfg["database"]

        self._sensor_queue = asyncio.Queue(maxsize=self._max_queue)
        self._aw_queue = asyncio.Queue(maxsize=self._max_queue)
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("LoraIngestService started")

    async def stop(self):
        self._running = False
        if self._flush_task:
            await self._flush_task
        if self._sensor_queue and self._sensor_queue.qsize() > 0:
            await self._flush_queue(self._sensor_queue, "sensor_readings", force=True)
        if self._aw_queue and self._aw_queue.qsize() > 0:
            await self._flush_queue(self._aw_queue, "aw_readings", force=True)
        if self._redis:
            await self._redis.close()
        logger.info("LoraIngestService stopped")

    # === 对外 API ===
    async def ingest_sensors(self, readings: List[Dict[str, Any]]) -> dict:
        """接收传感器数据, 去重后入队"""
        new_items = []
        for r in readings:
            ts = r["timestamp"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            ts_float = ts.timestamp() if hasattr(ts, "timestamp") else ts

            if self._deduplicator.is_duplicate(
                tent_id=r["tent_id"],
                sensor_type=r["sensor_type"],
                sensor_id=r["sensor_id"],
                timestamp=ts_float,
            ):
                continue

            new_items.append(r)
            try:
                self._sensor_queue.put_nowait(r)
            except asyncio.QueueFull:
                # 队列满: 低优先级丢弃
                if r.get("sensor_type") in ("light", "ethylene"):
                    logger.debug("Dropped low-priority reading (queue full)")
                else:
                    # 尝试丢一个队头低优先级的
                    try:
                        self._sensor_queue.get_nowait()
                        self._sensor_queue.put_nowait(r)
                    except Exception:
                        pass

        # 发布到 Redis Stream (批量)
        if new_items and self._redis:
            try:
                for item in new_items:
                    await self._redis.xadd(
                        self._stream_name,
                        {
                            "type": "sensor",
                            "tent_id": item["tent_id"],
                            "sensor_type": item["sensor_type"],
                            "sensor_id": item["sensor_id"],
                            "value": item["value"],
                            "timestamp": str(item["timestamp"]),
                        },
                    )
            except Exception as e:
                logger.error("Failed to publish to Redis stream: %s", e)

        return {
            "received": len(readings),
            "accepted": len(new_items),
            "duplicates": len(readings) - len(new_items),
            "queue_size": self._sensor_queue.qsize(),
        }

    async def ingest_aw(self, readings: List[Dict[str, Any]]) -> dict:
        """接收水分活度数据, 去重后入队"""
        new_items = []
        for r in readings:
            ts = r["timestamp"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            ts_float = ts.timestamp() if hasattr(ts, "timestamp") else ts

            if self._deduplicator.is_aw_duplicate(
                tent_id=r["tent_id"],
                drug_name=r["drug_name"],
                meter_id=r["meter_id"],
                timestamp=ts_float,
            ):
                continue

            new_items.append(r)
            try:
                self._aw_queue.put_nowait(r)
            except asyncio.QueueFull:
                pass

        if new_items and self._redis:
            try:
                for item in new_items:
                    await self._redis.xadd(
                        self._stream_name,
                        {
                            "type": "aw",
                            "tent_id": item["tent_id"],
                            "drug_name": item["drug_name"],
                            "meter_id": item["meter_id"],
                            "water_activity": item["water_activity"],
                            "timestamp": str(item["timestamp"]),
                        },
                    )
            except Exception as e:
                logger.error("Failed to publish AW to Redis stream: %s", e)

        return {
            "received": len(readings),
            "accepted": len(new_items),
            "duplicates": len(readings) - len(new_items),
            "queue_size": self._aw_queue.qsize(),
        }

    def get_backoff(self, tent_id: int) -> LoRaBackoff:
        """获取指定帐篷的退避管理器"""
        if tent_id not in self._backoffs:
            self._backoffs[tent_id] = LoRaBackoff(node_id=tent_id)
        return self._backoffs[tent_id]

    # === 内部 ===
    async def _flush_loop(self):
        while self._running:
            await asyncio.sleep(self._flush_interval)
            try:
                await self._flush_queue(self._sensor_queue, "sensor_readings")
                await self._flush_queue(self._aw_queue, "aw_readings")
            except Exception as e:
                logger.error("Flush error: %s", e, exc_info=True)

    async def _flush_queue(self, queue: asyncio.Queue, table: str, force: bool = False):
        if queue.empty():
            return
        if not force and queue.qsize() < self._flush_size // 2:
            return

        batch = []
        while len(batch) < self._flush_size and not queue.empty():
            try:
                batch.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not batch:
            return

        try:
            await asyncio.to_thread(self._do_insert, table, batch)
            logger.debug("Flushed %d rows to %s", len(batch), table)
        except Exception as e:
            logger.error("Insert failed for %s (%d rows): %s", table, len(batch), e)
            # 失败: 塞回队列头部 (倒序塞回保持原顺序)
            for item in reversed(batch):
                try:
                    queue.put_nowait(item)
                except asyncio.QueueFull:
                    break

    def _do_insert(self, table: str, batch: List[dict]):
        """同步写入 ClickHouse (在 worker thread 中调用)"""
        if not self._ch_client:
            return

        if table == "sensor_readings":
            rows = [
                (
                    r["timestamp"] if isinstance(r["timestamp"], datetime)
                    else datetime.fromisoformat(str(r["timestamp"])),
                    r["tent_id"],
                    r["sensor_id"],
                    r["sensor_type"],
                    float(r["value"]),
                )
                for r in batch
            ]
            insert_rows(
                self._ch_client,
                f"{self._db_name}.{table}",
                ["timestamp", "tent_id", "sensor_id", "sensor_type", "value"],
                rows,
            )
        elif table == "aw_readings":
            rows = [
                (
                    r["timestamp"] if isinstance(r["timestamp"], datetime)
                    else datetime.fromisoformat(str(r["timestamp"])),
                    r["tent_id"],
                    r["meter_id"],
                    r["drug_name"],
                    float(r["water_activity"]),
                )
                for r in batch
            ]
            insert_rows(
                self._ch_client,
                f"{self._db_name}.{table}",
                ["timestamp", "tent_id", "meter_id", "drug_name", "water_activity"],
                rows,
            )

    @property
    def stats(self) -> dict:
        return {
            "dedup": self._deduplicator.stats,
            "sensor_queue_size": self._sensor_queue.qsize() if self._sensor_queue else 0,
            "aw_queue_size": self._aw_queue.qsize() if self._aw_queue else 0,
            "backoff_count": len(self._backoffs),
        }
