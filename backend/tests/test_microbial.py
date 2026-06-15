"""
Baranyi-Roberts 微生物生长模型测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.microbial_model.baranyi import BaranyiRobertsModel


class TestBaranyiRobertsModel:

    def test_init_defaults(self):
        model = BaranyiRobertsModel()
        assert model.mu_max_base > 0
        assert model.opt_temp == 25.0
        assert model.min_aw == 0.60
        assert model.N0 == 2.0
        assert model.N_max == 7.0

    def test_temperature_factor_optimal(self):
        model = BaranyiRobertsModel()
        # 最适温度下因子 = 1
        assert model.temperature_factor(model.opt_temp) == pytest.approx(1.0, rel=0.01)

    def test_temperature_factor_below_min(self):
        model = BaranyiRobertsModel()
        assert model.temperature_factor(-10) == 0.0

    def test_temperature_factor_above_max(self):
        model = BaranyiRobertsModel()
        assert model.temperature_factor(50) == 0.0

    def test_temperature_factor_positive_in_range(self):
        model = BaranyiRobertsModel()
        # 在适宜范围内温度因子 > 0
        assert model.temperature_factor(15) > 0
        assert model.temperature_factor(30) > 0
        # 偏离最适温度因子 < 1
        assert model.temperature_factor(15) < 1.0

    def test_aw_factor_below_min(self):
        model = BaranyiRobertsModel()
        assert model.aw_factor(0.3) == 0.0
        assert model.aw_factor(model.min_aw) == 0.0

    def test_aw_factor_above_opt(self):
        model = BaranyiRobertsModel()
        assert model.aw_factor(0.99) == pytest.approx(1.0, rel=0.01)

    def test_aw_factor_increases_with_aw(self):
        model = BaranyiRobertsModel()
        f_low = model.aw_factor(0.65)
        f_mid = model.aw_factor(0.75)
        f_high = model.aw_factor(0.9)
        assert f_low < f_mid < f_high

    def test_mu_max_zero_when_too_cold_dry(self):
        model = BaranyiRobertsModel()
        # 温度太低 + Aw 太低, 生长速率为 0
        mu = model.mu_max(-5, 0.3)
        assert mu == 0.0

    def test_mu_max_positive_in_good_conditions(self):
        model = BaranyiRobertsModel()
        mu = model.mu_max(25, 0.85)
        assert mu > 0
        assert mu <= model.mu_max_base

    def test_lag_time_increases_with_harsh_conditions(self):
        model = BaranyiRobertsModel()
        # 适宜条件延迟期短
        lag_opt = model.lag_time(25, 0.85)
        # 差条件延迟期长
        lag_bad = model.lag_time(10, 0.65)

        assert lag_bad > lag_opt
        assert lag_opt > 0

    def test_growth_curve_increases(self):
        model = BaranyiRobertsModel()
        times, N_values = model.growth_curve(25, 0.85, hours=72, steps=10)

        assert len(times) == len(N_values) == 10
        assert times[0] == pytest.approx(0.0)
        assert times[-1] == pytest.approx(72.0)
        # 菌量随时间增加
        assert N_values[-1] > N_values[0]
        # 不超过最大菌量
        assert N_values[-1] <= model.N_max
        assert N_values[0] >= model.N0

    def test_growth_curve_no_growth_when_too_cold(self):
        model = BaranyiRobertsModel()
        _, N_values = model.growth_curve(-5, 0.5, hours=72, steps=10)
        # 低温下菌量不变
        assert N_values[-1] == pytest.approx(model.N0, rel=0.01)

    def test_mold_risk_score_in_range(self):
        model = BaranyiRobertsModel()
        risk = model.mold_risk_score(25, 0.85, exposure_hours=72)
        assert 0 <= risk <= 1

    def test_mold_risk_increases_with_temperature(self):
        model = BaranyiRobertsModel()
        r_low = model.mold_risk_score(10, 0.8, 48)
        r_mid = model.mold_risk_score(25, 0.8, 48)

        assert r_mid > r_low

    def test_mold_risk_increases_with_aw(self):
        model = BaranyiRobertsModel()
        r_low = model.mold_risk_score(25, 0.55, 48)
        r_high = model.mold_risk_score(25, 0.85, 48)

        assert r_high > r_low

    def test_mold_risk_zero_below_min_conditions(self):
        model = BaranyiRobertsModel()
        # 低温 + 低 Aw: 风险为 0
        risk = model.mold_risk_score(0, 0.4, 100)
        assert risk == 0.0

    def test_mold_risk_increases_with_time(self):
        model = BaranyiRobertsModel()
        r_short = model.mold_risk_score(25, 0.8, 24)
        r_long = model.mold_risk_score(25, 0.8, 168)
        assert r_long >= r_short

    def test_risk_level_classification(self):
        model = BaranyiRobertsModel()
        assert model.risk_level(0.1) == "低"
        assert model.risk_level(0.3) == "中"
        assert model.risk_level(0.6) == "高"
        assert model.risk_level(0.9) == "极高"

    def test_growth_curve_n0_parameter(self):
        model = BaranyiRobertsModel()
        _, N1 = model.growth_curve(25, 0.85, hours=0, steps=2, N0=3.0)
        assert N1[0] == pytest.approx(3.0)
