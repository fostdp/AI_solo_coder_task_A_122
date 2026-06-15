"""
配置加载器测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from shared.config_loader import (
    load_config,
    get_tents,
    get_tent,
    get_drug_params,
    get_drug_list,
    get_clickhouse_config,
    get_alert_config,
    get_lora_config,
    get_microbial_config,
)


class TestConfigLoader:

    def test_load_config_returns_dict(self):
        cfg = load_config()
        assert isinstance(cfg, dict)
        assert "tents" in cfg
        assert "drugs" in cfg
        assert "clickhouse" in cfg
        assert "redis" in cfg
        assert "alerts" in cfg
        assert "microbial" in cfg

    def test_get_tents_returns_list(self):
        tents = get_tents()
        assert isinstance(tents, list)
        assert len(tents) == 5
        for tent in tents:
            assert "id" in tent
            assert "name" in tent
            assert "lat" in tent
            assert "lng" in tent
            assert "drugs" in tent

    def test_get_tent_by_id(self):
        tent = get_tent(1)
        assert tent is not None
        assert tent["id"] == 1
        assert "悬泉置" in tent["name"]

    def test_get_tent_not_found(self):
        tent = get_tent(999)
        assert tent is None

    def test_get_drug_list(self):
        drugs = get_drug_list()
        assert isinstance(drugs, list)
        assert len(drugs) >= 5
        assert "当归" in drugs
        assert "大黄" in drugs

    def test_get_drug_params_structure(self):
        params = get_drug_params("当归")
        assert params is not None
        assert "arrhenius" in params
        assert "aw_critical" in params
        assert "light_degradation" in params
        assert "photosensitive" in params

        arr = params["arrhenius"]
        assert "Ea" in arr
        assert "A" in arr
        assert "T_ref" in arr
        assert "shelf_life_ref_months" in arr

    def test_get_drug_params_not_found(self):
        params = get_drug_params("不存在的药材")
        assert params is None

    def test_clickhouse_config(self):
        cfg = get_clickhouse_config()
        assert "host" in cfg
        assert "port" in cfg
        assert "database" in cfg

    def test_alert_config(self):
        cfg = get_alert_config()
        assert "water_activity_threshold" in cfg
        assert "temperature_threshold" in cfg
        assert "duration_hours" in cfg
        assert cfg["duration_hours"] == 4

    def test_lora_config(self):
        cfg = get_lora_config()
        assert "spreading_factors" in cfg
        assert "backoff_init_ms" in cfg
        assert "dedup_window_seconds" in cfg

    def test_microbial_config(self):
        cfg = get_microbial_config()
        assert "mu_max_base" in cfg
        assert "opt_temp" in cfg
        assert "min_aw" in cfg
        assert "N0" in cfg
        assert "N_max" in cfg
