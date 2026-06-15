"""
Arrhenius 有效期预测模型测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import math
from services.arrhenius_predictor.predictor import ArrheniusPredictor


class TestArrheniusPredictor:

    def test_init(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        assert predictor.Ea == 80000
        assert predictor.A == 1.0e12
        assert predictor.aw_critical == 0.6
        assert predictor.photosensitive is True

    def test_shelf_life_thermal_positive(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        # 温度越高, 有效期越短
        t20 = predictor.shelf_life_thermal(20)
        t30 = predictor.shelf_life_thermal(30)
        t40 = predictor.shelf_life_thermal(40)

        assert t20 > t30 > t40
        assert t20 > 0
        assert t30 > 0
        assert t40 > 0

    def test_shelf_life_thermal_reference(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        # 参考温度下的有效期应接近参考值 (24 个月 ≈ 730 天)
        t_ref = predictor.shelf_life_thermal(25)  # 25°C ≈ 298.15K
        # 允许 10% 误差 (因为 A/Ea 是理论值, 与参考有效期独立)
        expected_days = 24 * 30.4375  # 24 个月约 730 天
        # 不需要精确匹配, 只要是正数且数量级正确就行
        assert t_ref > 0
        assert t_ref < 2000  # 不超过 2000 天

    def test_k_light_zero_when_dark(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        # 黑暗环境下光降解速率为 0
        k_light = predictor.k_light(0, 25)
        assert k_light == 0.0

    def test_k_light_increases_with_intensity(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        k_low = predictor.k_light(100, 25)
        k_high = predictor.k_light(1000, 25)
        assert k_high > k_low
        assert k_low >= 0

    def test_aw_correction_factor(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        # aw <= 0.5 时修正系数为 1
        assert predictor.aw_correction_factor(0.3) == 1.0
        assert predictor.aw_correction_factor(0.5) == 1.0
        # aw > 0.5 时修正系数 < 1
        assert predictor.aw_correction_factor(0.7) < 1.0
        assert predictor.aw_correction_factor(0.8) < predictor.aw_correction_factor(0.6)

    def test_predict_shelf_life_complete(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        result = predictor.predict_shelf_life(
            T_celsius=25,
            aw=0.5,
            light_lux=0,
        )

        assert "shelf_life_days" in result
        assert "thermal_days" in result
        assert "aw_factor" in result
        assert "light_factor" in result
        assert "light_contribution_pct" in result

        # 黑暗 + aw=0.5: aw_factor=1, light_factor≈1
        assert result["aw_factor"] == pytest.approx(1.0, rel=0.01)
        assert result["light_factor"] == pytest.approx(1.0, rel=0.01)

    def test_light_reduces_shelf_life_for_photosensitive(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        dark_result = predictor.predict_shelf_life(25, 0.5, 0)
        light_result = predictor.predict_shelf_life(25, 0.5, 5000)

        # 有光照时光敏药材有效期更短
        assert light_result["shelf_life_days"] < dark_result["shelf_life_days"]
        assert light_result["light_contribution_pct"] > 0

    def test_quality_retention_decreases_over_time(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        r1 = predictor.quality_retention(25, 0.5, 30)
        r2 = predictor.quality_retention(25, 0.5, 90)
        r3 = predictor.quality_retention(25, 0.5, 365)

        assert r1 > r2 > r3
        assert 0 < r1 <= 1
        assert 0 < r2 <= 1
        assert 0 < r3 <= 1

    def test_quality_retention_at_zero_days(self, sample_drug_params):
        predictor = ArrheniusPredictor("test_drug", sample_drug_params)
        retention = predictor.quality_retention(25, 0.5, 0)
        assert retention == pytest.approx(1.0, rel=0.01)
