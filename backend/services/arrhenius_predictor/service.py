"""
Arrhenius Predictor Service - 药品有效期预测服务

两种运行模式:
  1. 库模式: 直接 import 调用 predict()
  2. 服务模式: 消费 Redis Stream (sensor_raw), 输出 drug_risk stream

与 microbial_model 服务的结果合并后, 进入 alert_broker
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from shared.config_loader import (
    get_redis_config,
    get_drug_params,
    get_tents,
)
from shared.redis_streams import RedisStreamClient
from shared.clickhouse_client import get_client
from .predictor import ArrheniusPredictor

logger = logging.getLogger(__name__)


class ArrheniusService:
    """Arrhenius 有效期预测服务"""

    def __init__(self, redis_client: Optional[RedisStreamClient] = None):
        self._redis = redis_client
        self._predictors: Dict[str, ArrheniusPredictor] = {}
        self._ch_client = None
        self._db_name = None
        self._running = False
        self._consumer_task = None

        rc = get_redis_config()
        self._stream_in = rc["streams"]["sensor_raw"]
        self._stream_out = rc["streams"]["drug_risk"]
        self._consumer_group = rc["consumer_groups"]["arrhenius_workers"]
        self._consumer_name = f"arrhenius-{id(self)}"

    # ---- 生命周期 ----
    async def start(self, consume_stream: bool = False):
        for drug_name in get_drug_params.__wrapped__() if False else _get_all_drugs():
            try:
                self._predictors[drug_name] = ArrheniusPredictor(drug_name)
            except ValueError:
                continue

        ch_cfg = __import__("shared.config_loader", fromlist=["get_clickhouse_config"]).get_clickhouse_config()
        self._ch_client = get_client(
            host=ch_cfg["host"], port=ch_cfg["port"],
            user=ch_cfg["user"], password=ch_cfg["password"],
            database=ch_cfg["database"],
        )
        self._db_name = ch_cfg["database"]

        if self._redis is None:
            rc = get_redis_config()
            self._redis = RedisStreamClient(
                host=rc["host"], port=rc["port"], db=rc["db"],
                password=rc.get("password", ""),
            )
            await self._redis.connect()

        if consume_stream:
            self._running = True
            self._consumer_task = asyncio.create_task(self._consume_loop())
            logger.info("ArrheniusService started (stream consumer)")
        else:
            logger.info("ArrheniusService started (library mode)")

    async def stop(self):
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        if self._redis:
            await self._redis.close()
        logger.info("ArrheniusService stopped")

    # ---- 对外 API (同步风格, 实际快速计算) ----
    def predict(self, drug_name: str, T_celsius: float, aw: float = 0.5, light_lux: float = 0.0) -> dict:
        """单药材有效期预测"""
        predictor = self._get_predictor(drug_name)
        return predictor.predict_shelf_life(T_celsius, aw, light_lux)

    def predict_tent_drugs(self, tent_id: int, climate: dict, aw_data: dict) -> List[dict]:
        """预测某帐篷所有药材的有效期"""
        tent = _get_tent(tent_id)
        if not tent:
            return []

        results = []
        for drug_name in tent["drugs"]:
            aw = aw_data.get(drug_name, 0.5)
            result = self.predict(
                drug_name,
                T_celsius=climate.get("temperature", 25),
                aw=aw,
                light_lux=climate.get("light", 0),
            )
            results.append({
                "tent_id": tent_id,
                "drug_name": drug_name,
                "shelf_life_days": result["shelf_life_days"],
                "avg_temperature": climate.get("temperature", 25),
                "avg_aw": aw,
                "avg_light": climate.get("light", 0),
                "light_contribution_pct": result["light_contribution_pct"],
                "aw_critical": self._get_predictor(drug_name).aw_critical,
            })
        return results

    def _get_predictor(self, drug_name: str) -> ArrheniusPredictor:
        if drug_name not in self._predictors:
            self._predictors[drug_name] = ArrheniusPredictor(drug_name)
        return self._predictors[drug_name]

    # ---- Stream 消费 ----
    async def _consume_loop(self):
        if not self._redis:
            return
        await self._redis.consume_loop(
            stream=self._stream_in,
            group=self._consumer_group,
            consumer_name=self._consumer_name,
            handler=self._handle_message,
            batch_size=20,
            block_ms=2000,
        )

    async def _handle_message(self, payload: dict):
        """处理单条 sensor 消息 -> 计算并输出风险评估"""
        # 这里是每个 sensor 消息, 实际风险评估需要聚合 24h 数据
        # 简化: 接收聚合后的 climate_summary 消息, 输出 drug_risk
        if payload.get("type") == "climate_summary":
            tent_id = int(payload["tent_id"])
            climate = {
                "temperature": float(payload.get("avg_temp", 25)),
                "humidity": float(payload.get("avg_humidity", 50)),
                "light": float(payload.get("avg_light", 0)),
                "co2": float(payload.get("avg_co2", 400)),
                "ethylene": float(payload.get("avg_ethylene", 0.5)),
            }
            aw_data = payload.get("aw_data", {})
            if isinstance(aw_data, str):
                import json
                aw_data = json.loads(aw_data)

            risks = self.predict_tent_drugs(tent_id, climate, aw_data)
            for r in risks:
                await self._redis.xadd(self._stream_out, {
                    "source": "arrhenius",
                    "tent_id": r["tent_id"],
                    "drug_name": r["drug_name"],
                    "shelf_life_days": r["shelf_life_days"],
                    "avg_temperature": r["avg_temperature"],
                    "avg_aw": r["avg_aw"],
                    "aw_critical": r["aw_critical"],
                    "light_contribution_pct": r["light_contribution_pct"],
                    "timestamp": datetime.utcnow().isoformat(),
                })


def _get_all_drugs() -> List[str]:
    from shared.config_loader import get_drug_list
    return get_drug_list()


def _get_tent(tent_id: int):
    from shared.config_loader import get_tent
    return get_tent(tent_id)
