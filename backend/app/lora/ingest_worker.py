"""
SensorIngestWorker - 后台线程持续从队列取出数据, 批量写入 ClickHouse
- 每 2s 或积累 500 条刷盘
- 队列满时只丢弃低优先级 (light/ethylene), 保留温湿度/CO2/Aw 数据
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Any

from ..database import get_client
from ..config import CLICKHOUSE_DB
from .backoff import SensorIngestQueue

logger = logging.getLogger(__name__)

_ingest_queue: SensorIngestQueue | None = None


def _clickhouse_write(table: str, rows: List[Any]):
    """同步写入 ClickHouse (在 worker thread 调用)"""
    client = get_client()
    if table == "sensor_readings":
        data = [
            (r["timestamp"], r["tent_id"], r["sensor_id"], r["sensor_type"], r["value"])
            for r in rows
        ]
        client.execute(
            f"""
            INSERT INTO {CLICKHOUSE_DB}.sensor_readings
            (timestamp, tent_id, sensor_id, sensor_type, value)
            VALUES
            """,
            data,
        )
    elif table == "aw_readings":
        data = [
            (r["timestamp"], r["tent_id"], r["meter_id"], r["drug_name"], r["water_activity"])
            for r in rows
        ]
        client.execute(
            f"""
            INSERT INTO {CLICKHOUSE_DB}.aw_readings
            (timestamp, tent_id, meter_id, drug_name, water_activity)
            VALUES
            """,
            data,
        )


def get_ingest_queue() -> SensorIngestQueue:
    global _ingest_queue
    if _ingest_queue is None:
        _ingest_queue = SensorIngestQueue(
            max_size=8000, flush_interval=2.0, flush_size=500
        )
    return _ingest_queue


async def start_ingest_worker():
    """在 FastAPI lifespan 启动时调用"""
    q = get_ingest_queue()
    await q.start(_clickhouse_write)
    logger.info("Sensor ingest worker started (queue + batch write v1.1)")


async def stop_ingest_worker():
    q = get_ingest_queue()
    await q.stop()
    logger.info("Sensor ingest worker stopped")


async def ingest_sensors_async(readings: List[dict]):
    """生产者接口: 把 readings 入队, 不阻塞"""
    q = get_ingest_queue()
    await q.enqueue_sensor(readings)


async def ingest_aw_async(readings: List[dict]):
    q = get_ingest_queue()
    await q.enqueue_aw(readings)


def ingest_stats() -> dict:
    return get_ingest_queue().stats()
