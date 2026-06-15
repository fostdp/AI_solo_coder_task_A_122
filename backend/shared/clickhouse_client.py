"""
ClickHouse 共享客户端 - 所有服务共用
同步客户端 (clickhouse-driver) 封装
"""
from typing import Any, List, Dict, Iterable
import logging

logger = logging.getLogger(__name__)

_client = None  # type: ignore


def _get_client_class():
    from clickhouse_driver import Client
    return Client


def get_client(
    host: str = "localhost",
    port: int = 9000,
    user: str = "default",
    password: str = "",
    database: str = "silkroad_medical",
    force_new: bool = False,
):
    """
    获取 ClickHouse 客户端 (单例)
    注意: clickhouse-driver 是同步的, 异步代码中需配合 asyncio.to_thread 使用
    """
    global _client
    if force_new or _client is None:
        Client = _get_client_class()
        _client = Client(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
        )
        logger.info("ClickHouse client created: %s:%s/%s", host, port, database)
    return _client


def insert_rows(client, table: str, columns: List[str], rows: Iterable[tuple]) -> int:
    """批量插入数据, 返回插入行数"""
    if not rows:
        return 0
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES"
    client.execute(sql, list(rows))
    return len(list(rows))


def query_rows(client, sql: str, params: Dict[str, Any] | None = None) -> list:
    """执行查询返回行列表"""
    return client.execute(sql, params or {})
