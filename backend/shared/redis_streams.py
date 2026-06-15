"""
Redis Stream 封装 - 服务间通信的消息总线
提供生产者/消费者 API, 抽象底层 redis-py 细节
"""
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis_async
except ImportError:
    redis_async = None


class RedisStreamClient:
    """Redis Stream 异步客户端封装"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str = "",
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self._client: Optional["redis_async.Redis"] = None

    async def connect(self):
        if redis_async is None:
            raise RuntimeError("redis-py not installed. Run: pip install redis")
        self._client = redis_async.Redis(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password or None,
            decode_responses=True,
        )
        await self._client.ping()
        logger.info("Redis connected: %s:%d", self.host, self.port)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Redis disconnected")

    @property
    def client(self) -> "redis_async.Redis":
        if self._client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client

    # --- 生产者 ---
    async def xadd(self, stream: str, data: Dict[str, Any], max_len: int = 10000):
        """向 Stream 追加一条消息 (自动 JSON 序列化复杂值)"""
        serialized = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                      for k, v in data.items()}
        msg_id = await self.client.xadd(
            stream,
            serialized,
            maxlen=max_len,
            approximate=True,
        )
        return msg_id

    async def xadd_batch(self, stream: str, items: List[Dict[str, Any]], max_len: int = 10000):
        """批量写入 (事务方式)"""
        pipe = self.client.pipeline(transaction=False)
        for item in items:
            serialized = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                          for k, v in item.items()}
            pipe.xadd(stream, serialized, maxlen=max_len, approximate=True)
        results = await pipe.execute()
        return results

    # --- 消费者组 ---
    async def ensure_consumer_group(self, stream: str, group: str):
        """创建消费者组, 已存在则忽略"""
        try:
            await self.client.xgroup_create(stream, group, id="0", mkstream=True)
            logger.info("Consumer group created: %s -> %s", stream, group)
        except Exception as e:
            if "BUSYGROUP" in str(e):
                pass  # 已存在, 正常
            else:
                raise

    async def xread_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> List[tuple]:
        """
        从消费者组读取消息 (XREADGROUP)
        返回: [(msg_id, {field: value}), ...]
        值自动 JSON 反序列化
        """
        result = await self.client.xreadgroup(
            group, consumer,
            {stream: ">"},
            count=count,
            block=block_ms,
        )
        if not result:
            return []

        messages = []
        for stream_name, msgs in result:
            for msg_id, fields in msgs:
                parsed = {}
                for k, v in fields.items():
                    try:
                        parsed[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        parsed[k] = v
                messages.append((msg_id, parsed))
        return messages

    async def xack(self, stream: str, group: str, msg_ids: List[str]):
        """确认消息已处理 (XACK)"""
        if msg_ids:
            await self.client.xack(stream, group, *msg_ids)

    async def xpending_summary(self, stream: str, group: str) -> dict:
        """获取 pending 消息统计"""
        return await self.client.xpending(stream, group)

    # --- 消费循环辅助 ---
    async def consume_loop(
        self,
        stream: str,
        group: str,
        consumer_name: str,
        handler: Callable[[dict], Awaitable[None]],
        batch_size: int = 10,
        block_ms: int = 2000,
    ):
        """
        持续消费循环: 读消息 → 调用 handler → ack
        handler 抛出异常时不 ack, 消息会重新交付
        """
        await self.ensure_consumer_group(stream, group)

        while True:
            try:
                msgs = await self.xread_group(
                    stream, group, consumer_name,
                    count=batch_size, block_ms=block_ms,
                )
                if not msgs:
                    continue

                ack_ids = []
                for msg_id, payload in msgs:
                    try:
                        await handler(payload)
                        ack_ids.append(msg_id)
                    except Exception as e:
                        logger.error(
                            "Handler failed for msg %s: %s", msg_id, e, exc_info=True
                        )
                        # 失败的消息不 ack, 会在 PEL 中等待重新交付

                if ack_ids:
                    await self.xack(stream, group, ack_ids)

            except asyncio.CancelledError:
                logger.info("Consumer loop cancelled")
                raise
            except Exception as e:
                logger.error("Consumer loop error: %s, retrying in 2s", e)
                await asyncio.sleep(2)
