"""
Alert Detector - 告警检测器 (纯逻辑, 无外部依赖)
便于单元测试, 与存储/通知解耦
"""
from typing import List, Optional, Tuple, Dict
from datetime import datetime


class AlertDetector:
    """告警检测器 - 纯计算逻辑"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {
            "water_activity_threshold": 0.6,
            "temperature_threshold": 30.0,
            "duration_hours": 4,
        }
        self.aw_threshold = cfg.get("water_activity_threshold", 0.6)
        self.temp_threshold = cfg.get("temperature_threshold", 30.0)
        self.duration_hours = cfg.get("duration_hours", 4)

    def _find_longest_violation(
        self,
        readings: List[Tuple[any, float]],
        threshold: float,
        interval_minutes: int = 30,
    ) -> Optional[dict]:
        """
        找出最长的超标连续段

        Args:
            readings: [(timestamp, value), ...] 按时间升序
            threshold: 超标阈值
            interval_minutes: 读数间隔 (分钟)

        Returns:
            None 或 {value, duration_hours, severity, first_violation}
        """
        if not readings:
            return None

        max_duration = 0.0
        current_streak = 0
        max_value = 0.0
        max_first_violation = None
        current_first = None

        for ts, val in readings:
            if val > threshold:
                current_streak += 1
                if current_first is None:
                    current_first = ts
                if val > max_value:
                    max_value = val
            else:
                duration = current_streak * interval_minutes / 60.0
                if duration > max_duration:
                    max_duration = duration
                    max_first_violation = current_first
                current_streak = 0
                current_first = None

        # 检查最后一段
        if current_streak > 0:
            duration = current_streak * interval_minutes / 60.0
            if duration > max_duration:
                max_duration = duration
                max_first_violation = current_first

        if max_duration >= self.duration_hours:
            return {
                "value": max_value,
                "duration_hours": max_duration,
                "first_violation": max_first_violation,
            }
        return None

    def check_high_temperature(
        self,
        readings: List[tuple],
        interval_minutes: int = 30,
    ) -> Optional[dict]:
        """
        检查温度是否持续超标

        Returns:
            None 或 {value, duration_hours, severity, first_violation}
        """
        result = self._find_longest_violation(
            readings, self.temp_threshold, interval_minutes
        )
        if result is None:
            return None

        result["severity"] = "critical" if result["value"] > 35 else "warning"
        return result

    def check_high_aw(
        self,
        readings: List[tuple],
        interval_minutes: int = 30,
    ) -> Optional[dict]:
        """检查水分活度是否持续超标"""
        result = self._find_longest_violation(
            readings, self.aw_threshold, interval_minutes
        )
        if result is None:
            return None

        result["severity"] = "critical" if result["value"] > 0.75 else "warning"
        return result

    def build_alert_message(
        self,
        tent_name: str,
        alert_type: str,
        result: dict,
    ) -> str:
        """生成告警消息文本"""
        val = result["value"]
        dur = result["duration_hours"]
        sev = result["severity"].upper()

        if alert_type == "high_temp":
            return (
                f"[{sev}] {tent_name}温度持续{dur:.1f}小时超过{self.temp_threshold}°C，"
                f"最高{val:.1f}°C，请立即采取降温措施！"
            )
        elif alert_type == "high_aw":
            return (
                f"[{sev}] {tent_name}药材水分活度持续{dur:.1f}小时"
                f"超过{self.aw_threshold}，当前最高Aw={val:.3f}，"
                f"存在霉变风险，请立即检查药材储存条件！"
            )
        else:
            return f"[{sev}] {tent_name}告警: {alert_type}"
