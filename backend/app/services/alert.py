import logging
from datetime import datetime, timedelta
from typing import List, Dict
from ..database import get_client
from ..config import (
    CLICKHOUSE_DB,
    ALERT_WATER_ACTIVITY_THRESHOLD,
    ALERT_TEMPERATURE_THRESHOLD,
    ALERT_DURATION_HOURS,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    ALERT_EMAIL_TO,
    SATELLITE_API_URL,
    SATELLITE_ENABLED,
    TENT_CONFIGS,
)

logger = logging.getLogger(__name__)


class AlertService:
    def check_alerts(self):
        for tent in TENT_CONFIGS:
            tent_id = tent["id"]
            self._check_temperature_alert(tent_id)
            self._check_aw_alert(tent_id)

    def _check_temperature_alert(self, tent_id: int):
        client = get_client()
        since = datetime.utcnow() - timedelta(hours=ALERT_DURATION_HOURS + 1)

        rows = client.execute(
            f"""
            SELECT
                toStartOfInterval(timestamp, INTERVAL 30 MINUTE) as t,
                avg(value) as avg_temp
            FROM {CLICKHOUSE_DB}.sensor_readings
            WHERE tent_id = %(tent_id)s
              AND sensor_type = 'temperature'
              AND timestamp >= %(since)s
            GROUP BY t
            ORDER BY t
            """,
            {"tent_id": tent_id, "since": since},
        )

        consecutive_count = 0
        first_violation = None
        max_temp = 0.0
        for ts, avg_temp in rows:
            if float(avg_temp) > ALERT_TEMPERATURE_THRESHOLD:
                consecutive_count += 1
                max_temp = max(max_temp, float(avg_temp))
                if first_violation is None:
                    first_violation = ts
            else:
                consecutive_count = 0
                first_violation = None

        duration_hours = consecutive_count * 0.5
        if duration_hours >= ALERT_DURATION_HOURS:
            severity = "critical" if max_temp > 35 else "warning"
            tent_name = next((t["name"] for t in TENT_CONFIGS if t["id"] == tent_id), f"帐篷{tent_id}")
            message = (
                f"[{severity.upper()}] {tent_name}温度持续{duration_hours:.1f}小时超过{ALERT_TEMPERATURE_THRESHOLD}°C，"
                f"最高温度{max_temp:.1f}°C，请立即采取降温措施！"
            )
            self._record_and_notify(
                tent_id=tent_id,
                alert_type="high_temp",
                severity=severity,
                value=max_temp,
                threshold=ALERT_TEMPERATURE_THRESHOLD,
                duration_hours=duration_hours,
                message=message,
            )

    def _check_aw_alert(self, tent_id: int):
        client = get_client()
        since = datetime.utcnow() - timedelta(hours=ALERT_DURATION_HOURS + 1)

        rows = client.execute(
            f"""
            SELECT
                drug_name,
                toStartOfInterval(timestamp, INTERVAL 30 MINUTE) as t,
                avg(water_activity) as avg_aw
            FROM {CLICKHOUSE_DB}.aw_readings
            WHERE tent_id = %(tent_id)s AND timestamp >= %(since)s
            GROUP BY drug_name, t
            ORDER BY drug_name, t
            """,
            {"tent_id": tent_id, "since": since},
        )

        drug_data: Dict[str, List] = {}
        for drug_name, ts, avg_aw in rows:
            if drug_name not in drug_data:
                drug_data[drug_name] = []
            drug_data[drug_name].append((ts, float(avg_aw)))

        tent_name = next((t["name"] for t in TENT_CONFIGS if t["id"] == tent_id), f"帐篷{tent_id}")

        for drug_name, readings in drug_data.items():
            consecutive_count = 0
            max_aw = 0.0
            for ts, avg_aw in readings:
                if avg_aw > ALERT_WATER_ACTIVITY_THRESHOLD:
                    consecutive_count += 1
                    max_aw = max(max_aw, avg_aw)
                else:
                    consecutive_count = 0

            duration_hours = consecutive_count * 0.5
            if duration_hours >= ALERT_DURATION_HOURS:
                severity = "critical" if max_aw > 0.75 else "warning"
                message = (
                    f"[{severity.upper()}] {tent_name}药材「{drug_name}」水分活度持续{duration_hours:.1f}小时"
                    f"超过{ALERT_WATER_ACTIVITY_THRESHOLD}，当前最高Aw={max_aw:.3f}，"
                    f"存在霉变风险，请立即检查药材储存条件！"
                )
                self._record_and_notify(
                    tent_id=tent_id,
                    alert_type="high_aw",
                    severity=severity,
                    value=max_aw,
                    threshold=ALERT_WATER_ACTIVITY_THRESHOLD,
                    duration_hours=duration_hours,
                    message=message,
                )

    def _record_and_notify(
        self,
        tent_id: int,
        alert_type: str,
        severity: str,
        value: float,
        threshold: float,
        duration_hours: float,
        message: str,
    ):
        client = get_client()
        now = datetime.utcnow()

        recent = client.execute(
            f"""
            SELECT count() FROM {CLICKHOUSE_DB}.alerts
            WHERE tent_id = %(tent_id)s
              AND alert_type = %(alert_type)s
              AND timestamp >= %(since)s
            """,
            {
                "tent_id": tent_id,
                "alert_type": alert_type,
                "since": now - timedelta(hours=2),
            },
        )

        if recent[0][0] > 0:
            return

        client.execute(
            f"""
            INSERT INTO {CLICKHOUSE_DB}.alerts
            (timestamp, tent_id, alert_type, severity, value, threshold, duration_hours, message, notified)
            VALUES
            """,
            [(now, tent_id, alert_type, severity, value, threshold, duration_hours, message, 0)],
        )

        notified = 0
        try:
            self._send_email(message)
            notified = 1
        except Exception as e:
            logger.error(f"Email notification failed: {e}")

        if SATELLITE_ENABLED:
            try:
                self._send_satellite(message)
                notified = 2
            except Exception as e:
                logger.error(f"Satellite notification failed: {e}")

        client.execute(
            f"""
            ALTER TABLE {CLICKHOUSE_DB}.alerts
            UPDATE notified = %(notified)s
            WHERE tent_id = %(tent_id)s
              AND alert_type = %(alert_type)s
              AND timestamp = %(ts)s
            """,
            {"notified": notified, "tent_id": tent_id, "alert_type": alert_type, "ts": now},
        )

    def _send_email(self, message: str):
        import aiosmtplib
        from email.mime.text import MIMEText
        import asyncio

        msg = MIMEText(message, "plain", "utf-8")
        msg["Subject"] = "丝绸之路医疗帐篷告警"
        msg["From"] = SMTP_USER
        msg["To"] = ALERT_EMAIL_TO

        async def _send():
            await aiosmtplib.send(
                msg,
                hostname=SMTP_HOST,
                port=SMTP_PORT,
                username=SMTP_USER,
                password=SMTP_PASSWORD,
                use_tls=True,
            )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_send())
            else:
                loop.run_until_complete(_send())
        except RuntimeError:
            asyncio.run(_send())

    def _send_satellite(self, message: str):
        import httpx

        try:
            httpx.post(
                SATELLITE_API_URL,
                json={"message": message, "priority": "high"},
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Satellite API error: {e}")

    def get_active_alerts(self, tent_id: int = None, hours: int = 24) -> List[Dict]:
        client = get_client()
        since = datetime.utcnow() - timedelta(hours=hours)

        if tent_id:
            rows = client.execute(
                f"""
                SELECT timestamp, tent_id, alert_type, severity, value, threshold,
                       duration_hours, message, notified
                FROM {CLICKHOUSE_DB}.alerts
                WHERE tent_id = %(tent_id)s AND timestamp >= %(since)s
                ORDER BY timestamp DESC
                """,
                {"tent_id": tent_id, "since": since},
            )
        else:
            rows = client.execute(
                f"""
                SELECT timestamp, tent_id, alert_type, severity, value, threshold,
                       duration_hours, message, notified
                FROM {CLICKHOUSE_DB}.alerts
                WHERE timestamp >= %(since)s
                ORDER BY timestamp DESC
                LIMIT 100
                """,
                {"since": since},
            )

        alerts = []
        for ts, tid, atype, sev, val, thr, dur, msg, notif in rows:
            alerts.append({
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "tent_id": tid,
                "alert_type": atype,
                "severity": sev,
                "value": round(float(val), 3),
                "threshold": round(float(thr), 3),
                "duration_hours": round(float(dur), 2),
                "message": msg,
                "notified": notif,
            })
        return alerts


_alert_service = None


def get_alert_service() -> AlertService:
    global _alert_service
    if _alert_service is None:
        _alert_service = AlertService()
    return _alert_service
