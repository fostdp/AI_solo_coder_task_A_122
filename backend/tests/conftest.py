"""
pytest 共享 fixture 配置
"""
import os
import sys
import pytest

# 把 backend 目录加入 sys.path, 方便 import shared / services
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# mock 环境变量
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")
os.environ.setdefault("CLICKHOUSE_PORT", "9000")


@pytest.fixture
def sample_drug_params():
    """示例药材参数"""
    return {
        "arrhenius": {
            "Ea": 80000,
            "A": 1.0e12,
            "T_ref": 298.15,
            "shelf_life_ref_months": 24,
        },
        "aw_critical": 0.6,
        "photosensitive": True,
        "light_degradation": {
            "k_photo": 2.5e-8,
            "alpha": 0.7,
            "Eb": 30000,
        },
    }


@pytest.fixture
def alert_config():
    """告警配置"""
    return {
        "water_activity_threshold": 0.6,
        "temperature_threshold": 30.0,
        "duration_hours": 4,
        "check_interval_minutes": 30,
    }
