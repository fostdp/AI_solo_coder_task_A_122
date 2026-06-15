"""
Microbial Model Service - 微生物生长/霉变风险评估服务

消费 Redis Stream (sensor_raw / aw), 输出霉变风险到 drug_risk stream
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from shared.config_loader import get_redis_config, get_tents, get_drug_params
from shared.redis_streams import RedisStreamClient
from .baranyi import BaranyiRobertsModel

logger = logging.getLogger(__name__)


class MicrobialService:
    """微生物生长模型服务"""

    def __init__(self, redis_client: Optional[RedisStreamClient] = None):
        self._model = None
        self._redis = redis_client
        self._running = False
        self._consumer_task = None

        rc = get_redis_config()
        self._stream_in = rc["streams"]["sensor_raw"]
        self._stream_out = rc["streams"]["drug_risk"]
        self._consumer_group = rc["consumer_groups"]["microbial_workers"]
        self._consumer_name = f"microbial-{id(self)}"

    # ---- 生命周期 ----
    async def start(self, consume_stream: bool = False):
        self._model = BaranyiRobertsModel()

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
            logger.info("MicrobialService started (stream consumer)")
        else:
            logger.info("MicrobialService started (library mode)")

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
        logger.info("MicrobialService stopped")

    # ---- 对外 API ----
    def assess_risk(
        self,
        T_celsius: float,
        aw: float,
        exposure_hours: float = 72.0,
    ) -> dict:
        """单条件霉变风险评估"""
        risk = self._model.mold_risk_score(T_celsius, aw, exposure_hours)
        mu = self._model.mu_max(T_celsius, aw)
        lag = self._model.lag_time(T_celsius, aw)
        return {
            "mold_risk": round(risk, 4),
            "risk_level": self._model.risk_level(risk),
            "mu_max_per_hour": round(mu, 6),
            "lag_hours": round(lag, 2) if lag != float("inf") else None,
            "temperature_factor": round(self._model.temperature_factor(T_celsius), 4),
            "aw_factor": round(self._model.aw_factor(aw), 4),
        }

    def assess_tent_drugs(
        self,
        tent_id: int,
        avg_temp: float,
        aw_data: Dict[str, float],
        exposure_hours: float = 72.0,
    ) -> List[dict]:
        """评估某帐篷所有药材的霉变风险"""
        tent = _get_tent(tent_id)
        if not tent:
            return []

        results = []
        for drug_name in tent["drugs"]:
            aw = aw_data.get(drug_name, 0.5)
            result = self.assess_risk(avg_temp, aw, exposure_hours)
            results.append({
                "tent_id": tent_id,
                "drug_name": drug_name,
                "mold_risk": result["mold_risk"],
                "risk_level": result["risk_level"],
                "avg_temperature": avg_temp,
                "avg_aw": aw,
                "exposure_hours": exposure_hours,
            })
        return results

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
        """处理 climate_summary 消息, 输出霉变风险"""
        if payload.get("type") == "climate_summary":
            tent_id = int(payload["tent_id"])
            avg_temp = float(payload.get("avg_temp", 25))
            aw_data = payload.get("aw_data", {})
            if isinstance(aw_data, str):
                import json
                aw_data = json.loads(aw_data)

            risks = self.assess_tent_drugs(tent_id, avg_temp, aw_data)
            for r in risks:
                await self._redis.xadd(self._stream_out, {
                    "source": "microbial",
                    "tent_id": r["tent_id"],
                    "drug_name": r["drug_name"],
                    "mold_risk": r["mold_risk"],
                    "risk_level": r["risk_level"],
                    "avg_temperature": r["avg_temperature"],
                    "avg_aw": r["avg_aw"],
                    "timestamp": datetime.utcnow().isoformat(),
                })


def _get_tent(tent_id: int):
    from shared.config_loader import get_tent
    return get_tent(tent_id)
