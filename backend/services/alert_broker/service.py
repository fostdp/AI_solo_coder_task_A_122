"""
Alert Broker Service - 告警代理服务

职责:
  1. 消费 Redis Stream (drug_risk) 或定时查询 ClickHouse
  2. 检测超标条件:
     - Aw > 0.6 持续 4h
     - 温度 > 30℃ 持续 4h
  3. 生成告警事件, 发布到 alerts stream
  4. 通过邮件 + 卫星通信推送通知
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from shared.config_loader import (
    get_alert_config,
    get_redis_config,
    get_tents,
)
from shared.redis_streams import RedisStreamClient
from .detector import AlertDetector

logger = logging.getLogger(__name__)


class AlertNotifier:
    """告警通知发送器 - 邮件 + 卫星通信"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or get_alert_config()
        self.smtp_host = cfg["email"]["smtp_host"]
        self.smtp_port = cfg["email"]["smtp_port"]
        self.smtp_user = cfg["email"]["smtp_user"]
        self.smtp_password = cfg["email"]["smtp_password"]
        self.email_to = cfg["email"]["to"]
        self.satellite_url = cfg["satellite"]["api_url"]
        self.satellite_enabled = cfg["satellite"]["enabled"]
        self._cooldown: Dict[str, datetime] = {}  # 同类告警冷却时间 2h
        self.cooldown_seconds = 7200

    def should_notify(self, key: str) -> bool:
        """冷却检查: 同类告警 2h 内不重复发送"""
        now = datetime.utcnow()
        last = self._cooldown.get(key)
        if last and (now - last).total_seconds() < self.cooldown_seconds:
            return False
        self._cooldown[key] = now
        return True

    async def send_email(self, subject: str, body: str) -> bool:
        """发送邮件通知"""
        try:
            import aiosmtplib
            from email.mime.text import MIMEText

            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = self.smtp_user
            msg["To"] = self.email_to

            if not self.smtp_user or not self.smtp_password:
                logger.info("(dry-run) Email would be sent: %s", subject)
                return True

            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                use_tls=True,
            )
            logger.info("Alert email sent: %s", subject)
            return True
        except Exception as e:
            logger.error("Failed to send alert email: %s", e)
            return False

    async def send_satellite(self, message: str) -> bool:
        """发送卫星通信通知"""
        if not self.satellite_enabled:
            logger.info("(dry-run) Satellite alert would be sent")
            return True
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    self.satellite_url,
                    json={"message": message, "priority": "high"},
                    timeout=10,
                )
                return r.status_code < 300
        except Exception as e:
            logger.error("Satellite notification failed: %s", e)
            return False

    async def notify(self, alert: dict) -> bool:
        """发送告警通知 (邮件 + 卫星)"""
        key = f"{alert['tent_id']}:{alert['alert_type']}"
        if not self.should_notify(key):
            return False

        tent_name = alert.get("tent_name") or f"帐篷{alert['tent_id']}"
        subject = f"丝绸之路医疗帐篷告警 - {tent_name}"
        body = alert.get("message", "")

        email_ok = await self.send_email(subject, body)
        sat_ok = await self.send_satellite(body)
        return email_ok or sat_ok


class AlertBrokerService:
    """告警代理服务主类"""

    def __init__(self, redis_client: Optional[RedisStreamClient] = None):
        self._detector = AlertDetector()
        self._notifier = AlertNotifier()
        self._redis = redis_client
        self._ch_client = None
        self._db_name = None
        self._running = False
        self._scheduler_task = None

        rc = get_redis_config()
        self._stream_in = rc["streams"]["drug_risk"]
        self._stream_out = rc["streams"]["alerts"]
        self._consumer_group = rc["consumer_groups"]["alert_workers"]
        self._consumer_name = f"alert-{id(self)}"
        self._check_interval = 1800  # 30 min

    async def start(self, with_scheduler: bool = True):
        from shared.clickhouse_client import get_client, insert_rows, query_rows
        from shared.config_loader import get_clickhouse_config
        ch_cfg = get_clickhouse_config()
        self._ch_client = get_client(
            host=ch_cfg["host"], port=ch_cfg["port"],
            user=ch_cfg["user"], password=ch_cfg["password"],
            database=ch_cfg["database"],
        )
        self._ch_insert = insert_rows
        self._ch_query = query_rows
        self._db_name = ch_cfg["database"]

        if self._redis is None:
            rc = get_redis_config()
            self._redis = RedisStreamClient(
                host=rc["host"], port=rc["port"], db=rc["db"],
                password=rc.get("password", ""),
            )
            await self._redis.connect()

        if with_scheduler:
            self._running = True
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            logger.info("AlertBrokerService started")

    async def stop(self):
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        if self._redis:
            await self._redis.close()
        logger.info("AlertBrokerService stopped")

    async def _scheduler_loop(self):
        while self._running:
            try:
                await self.run_alerts_check()
            except Exception as e:
                logger.error("Alert check failed: %s", e, exc_info=True)
            await asyncio.sleep(self._check_interval)

    async def run_alerts_check(self):
        """运行全量告警检测"""
        results = []
        for tent in get_tents():
            tent_id = tent["id"]
            tent_name = tent["name"]

            temp_readings = self._get_temp_history(tent_id)
            temp_result = self._detector.check_high_temperature(temp_readings)
            if temp_result:
                alert = {
                    "tent_id": tent_id,
                    "tent_name": tent_name,
                    "alert_type": "high_temp",
                    "severity": temp_result["severity"],
                    "value": temp_result["value"],
                    "threshold": self._detector.temp_threshold,
                    "duration_hours": temp_result["duration_hours"],
                    "message": self._detector.build_alert_message(
                        tent_name, "high_temp", temp_result
                    ),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                results.append(alert)

            aw_results = self._check_tent_aw_alerts(tent_id, tent_name)
            results.extend(aw_results)

        # 保存 + 发布 + 通知
        for alert in results:
            await self._persist_alert(alert)
            if self._redis:
                await self._redis.xadd(self._stream_out, alert)
            await self._notifier.notify(alert)

        return results

    def _get_temp_history(self, tent_id: int) -> List[tuple]:
        """从 ClickHouse 获取温度历史"""
        hours = self._detector.duration_hours + 1
        since = datetime.utcnow() - timedelta(hours=hours)
        sql = f"""
            SELECT toStartOfInterval(timestamp, INTERVAL 30 MINUTE) as t, avg(value)
            FROM {self._db_name}.sensor_readings
            WHERE tent_id = %(tid)s AND sensor_type = 'temperature' AND timestamp >= %(since)s
            GROUP BY t ORDER BY t
        """
        rows = self._ch_query(self._ch_client, sql, {"tid": tent_id, "since": since})
        return [(r[0], float(r[1])) for r in rows]

    def _check_tent_aw_alerts(self, tent_id: int, tent_name: str) -> List[dict]:
        """检查某帐篷所有药材的 Aw 告警"""
        hours = self._detector.duration_hours + 1
        since = datetime.utcnow() - timedelta(hours=hours)
        sql = f"""
            SELECT drug_name, toStartOfInterval(timestamp, INTERVAL 30 MINUTE) as t, avg(water_activity)
            FROM {self._db_name}.aw_readings
            WHERE tent_id = %(tid)s AND timestamp >= %(since)s
            GROUP BY drug_name, t
            ORDER BY drug_name, t
        """
        rows = self._ch_query(self._ch_client, sql, {"tid": tent_id, "since": since})

        drug_readings: Dict[str, List[tuple]] = {}
        for drug_name, ts, aw in rows:
            drug_readings.setdefault(drug_name, []).append((ts, float(aw)))

        alerts = []
        for drug_name, readings in drug_readings.items():
            result = self._detector.check_high_aw(readings)
            if result:
                alerts.append({
                    "tent_id": tent_id,
                    "tent_name": tent_name,
                    "drug_name": drug_name,
                    "alert_type": "high_aw",
                    "severity": result["severity"],
                    "value": result["value"],
                    "threshold": self._detector.aw_threshold,
                    "duration_hours": result["duration_hours"],
                    "message": self._detector.build_alert_message(
                        f"{tent_name}·{drug_name}", "high_aw", result
                    ),
                    "timestamp": datetime.utcnow().isoformat(),
                })
        return alerts

    async def _persist_alert(self, alert: dict):
        """保存告警到 ClickHouse"""
        if not self._ch_client:
            return
        ts = alert["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        self._ch_insert(
            self._ch_client,
            f"{self._db_name}.alerts",
            ["timestamp", "tent_id", "alert_type", "severity", "value",
             "threshold", "duration_hours", "message", "notified"],
            [(
                ts, alert["tent_id"], alert["alert_type"], alert["severity"],
                alert["value"], alert["threshold"], alert["duration_hours"],
                alert["message"], 1 if await self._notifier.notify(alert) else 0,
            )],
        )
