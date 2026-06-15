"""
Alert Detector 告警检测器测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timedelta
from services.alert_broker.detector import AlertDetector


def _make_readings(values, start_ts=None, interval_min=30):
    """生成 (timestamp, value) 列表用于测试"""
    if start_ts is None:
        start_ts = datetime(2025, 1, 1, 0, 0)
    readings = []
    for i, v in enumerate(values):
        ts = start_ts + timedelta(minutes=i * interval_min)
        readings.append((ts, v))
    return readings


class TestAlertDetector:

    def test_init(self, alert_config):
        detector = AlertDetector(alert_config)
        assert detector.aw_threshold == 0.6
        assert detector.temp_threshold == 30.0
        assert detector.duration_hours == 4

    def test_no_readings_no_alert(self, alert_config):
        detector = AlertDetector(alert_config)
        result = detector.check_high_temperature([])
        assert result is None

    def test_temperature_normal_no_alert(self, alert_config):
        """温度一直正常, 不触发告警"""
        detector = AlertDetector(alert_config)
        readings = _make_readings([22, 23, 24, 25, 24, 23, 22, 22, 23, 24])
        result = detector.check_high_temperature(readings)
        assert result is None

    def test_temperature_below_threshold_duration_no_alert(self, alert_config):
        """温度超标但持续时间不够, 不触发"""
        detector = AlertDetector(alert_config)
        # 超标 2 小时 (4 个 30min 间隔)
        readings = _make_readings([25, 31, 32, 33, 28, 25])
        result = detector.check_high_temperature(readings)
        # 2 小时 < 4 小时阈值
        assert result is None

    def test_temperature_above_threshold_duration_triggers_alert(self, alert_config):
        """温度超标持续超过 4 小时, 触发告警"""
        detector = AlertDetector(alert_config)
        # 持续 5 小时超标 (10 个 30min)
        readings = _make_readings([31, 32, 33, 34, 35, 34, 33, 32, 31, 32])
        result = detector.check_high_temperature(readings)

        assert result is not None
        assert result["value"] >= 30.0
        assert result["duration_hours"] >= 4.0
        assert result["severity"] in ("warning", "critical")
        assert result["first_violation"] is not None

    def test_temperature_severity_warning_below_35(self, alert_config):
        """最高温 30~35 度, warning"""
        detector = AlertDetector(alert_config)
        readings = _make_readings([31, 32, 32, 33, 33, 32, 32, 31, 32, 33])
        result = detector.check_high_temperature(readings)
        assert result is not None
        assert result["severity"] == "warning"

    def test_temperature_severity_critical_above_35(self, alert_config):
        """最高温 >35 度, critical"""
        detector = AlertDetector(alert_config)
        readings = _make_readings([35, 36, 37, 38, 37, 36, 35, 36, 37, 36])
        result = detector.check_high_temperature(readings)
        assert result is not None
        assert result["severity"] == "critical"

    def test_aw_normal_no_alert(self, alert_config):
        """Aw 正常, 不告警"""
        detector = AlertDetector(alert_config)
        readings = _make_readings([0.45, 0.48, 0.5, 0.52, 0.5])
        result = detector.check_high_aw(readings)
        assert result is None

    def test_aw_above_threshold_duration_triggers_alert(self, alert_config):
        """Aw 超标持续 4 小时以上, 触发告警"""
        detector = AlertDetector(alert_config)
        # 10 个 30min 点 = 4.5 小时
        readings = _make_readings([0.61, 0.62, 0.63, 0.64, 0.65, 0.64, 0.63, 0.62, 0.61, 0.63])
        result = detector.check_high_aw(readings)

        assert result is not None
        assert result["value"] > 0.6
        assert result["duration_hours"] >= 4.0

    def test_aw_severity_critical_above_075(self, alert_config):
        """Aw > 0.75, critical"""
        detector = AlertDetector(alert_config)
        readings = _make_readings([0.76, 0.77, 0.78, 0.77, 0.76, 0.77, 0.78, 0.77, 0.76, 0.77])
        result = detector.check_high_aw(readings)
        assert result is not None
        assert result["severity"] == "critical"

    def test_intermittent_spikes_no_alert(self, alert_config):
        """间歇性超标, 持续时间不够, 不告警"""
        detector = AlertDetector(alert_config)
        readings = _make_readings([31, 25, 32, 25, 31, 25, 32, 25, 31, 25])
        result = detector.check_high_temperature(readings)
        assert result is None

    def test_multiple_violation_periods_longest(self, alert_config):
        """多个超标段, 取最长的那个"""
        detector = AlertDetector(alert_config)
        # 第一段: 超标 1h (2 点), 第二段: 超标 5h (10 点)
        values = (
            [31, 32]  # 第一段 (1h)
            + [25, 24, 23]  # 恢复
            + [31, 32, 33, 34, 33, 32, 31, 32, 33, 34]  # 第二段 (5h)
        )
        readings = _make_readings(values)
        result = detector.check_high_temperature(readings)

        assert result is not None
        # 最长持续 5 小时
        assert result["duration_hours"] >= 4.0
        assert 33 <= result["value"] <= 34

    def test_build_alert_message(self, alert_config):
        """告警消息格式正确"""
        detector = AlertDetector(alert_config)
        result = {
            "value": 35.5,
            "duration_hours": 5.0,
            "severity": "critical",
        }
        msg = detector.build_alert_message("测试帐篷", "high_temp", result)

        assert "CRITICAL" in msg
        assert "测试帐篷" in msg
        assert "30.0" in msg  # 阈值
        assert "35.5" in msg  # 最大值
        assert "5.0" in msg  # 持续时间

    def test_custom_interval(self, alert_config):
        """支持自定义时间间隔"""
        detector = AlertDetector(alert_config)
        # 10 分钟间隔, 25 个点 = 250 分钟 ≈ 4.17 小时
        values = [32] * 25
        readings = _make_readings(values, interval_min=10)
        result = detector.check_high_temperature(readings, interval_minutes=10)

        assert result is not None
        assert result["duration_hours"] >= 4.0
