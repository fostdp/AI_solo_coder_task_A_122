"""
Arrhenius 药品有效期预测模型
基于 Arrhenius 方程: k = A * exp(-Ea / (R * T))

考虑水分活度修正 + 光照降解修正
"""
import math
from typing import Optional

from shared.config_loader import get_drug_params


class ArrheniusPredictor:
    """
    Arrhenius equation based drug shelf life prediction.

    核心公式:
    - k_thermal = A * exp(-Ea/(R*T))  [热降解速率]
    - k_light   = k_photo * I^α * exp(-Eb/(R*T))  [光降解速率]
    - k_total = k_thermal + k_light

    一级动力学: t90 = -ln(0.9) / k_total  (90% 保留时间)

    水分活度修正: aw > 0.5 时加速降解, 修正因子 = max(0.1, 1 - 2*(aw-0.5)^1.5)
    """

    R = 8.314  # 气体常数 J/(mol·K)
    LUX_TO_WM2 = 0.0079  # lux -> W/m² 转换系数

    def __init__(self, drug_name: str, params: Optional[dict] = None):
        self.drug_name = drug_name

        if params is None:
            params = get_drug_params(drug_name)
            if params is None:
                raise ValueError(f"Unknown drug: {drug_name}")

        arr = params["arrhenius"]
        self.Ea = arr["Ea"]
        self.A = arr["A"]
        self.T_ref = arr["T_ref"]
        self.shelf_life_ref_months = arr["shelf_life_ref_months"]
        self.aw_critical = params["aw_critical"]
        self.photosensitive = params.get("photosensitive", False)

        ld = params.get("light_degradation", {})
        self.k_photo = ld.get("k_photo", 1.5e-8)
        self.alpha = ld.get("alpha", 0.6)
        self.Eb = ld.get("Eb", 28000)

    # ---- 热降解 ----

    def k_thermal(self, T_celsius: float) -> float:
        """热降解速率常数 (1/s)"""
        T_k = T_celsius + 273.15
        return self.A * math.exp(-self.Ea / (self.R * T_k))

    def k_ref(self) -> float:
        """参考温度下的降解速率 (由参考有效期反推, 更准确)"""
        t90_ref_seconds = self.shelf_life_ref_months * (365.25 / 12) * 24 * 3600
        return -math.log(0.9) / t90_ref_seconds

    def shelf_life_thermal(self, T_celsius: float) -> float:
        """纯热降解有效期 (天)"""
        T_k = T_celsius + 273.15
        k0 = self.k_ref()
        k_T = k0 * math.exp(-self.Ea / (self.R * T_k)) / math.exp(-self.Ea / (self.R * self.T_ref))
        if k_T <= 0:
            return float("inf")
        t90_seconds = -math.log(0.9) / k_T
        return t90_seconds / (24 * 3600)

    # ---- 光降解 ----

    def irradiance(self, lux: float) -> float:
        """lux -> W/m²"""
        return max(0.0, lux) * self.LUX_TO_WM2

    def k_light(self, lux: float, T_celsius: float) -> float:
        """光降解速率常数 (1/s)"""
        if not self.photosensitive and lux < 50:
            return 0.0
        I = self.irradiance(lux)
        T_k = T_celsius + 273.15
        return self.k_photo * (I ** self.alpha) * math.exp(-self.Eb / (self.R * T_k))

    def light_contribution_pct(self, T_celsius: float, lux: float) -> float:
        """光降解在总降解中的占比 (%)"""
        kt = self.k_thermal(T_celsius)
        kl = self.k_light(lux, T_celsius)
        total = kt + kl
        return 100.0 * kl / total if total > 0 else 0.0

    # ---- 水分活度修正 ----

    def aw_correction_factor(self, aw: float) -> float:
        """水分活度修正系数 (0~1)"""
        if aw <= 0.5:
            return 1.0
        return max(0.1, 1.0 - 2.0 * (aw - 0.5) ** 1.5)

    # ---- 综合有效期预测 ----

    def predict_shelf_life(
        self,
        T_celsius: float,
        aw: float = 0.5,
        light_lux: float = 0.0,
    ) -> dict:
        """
        综合预测有效期

        Returns:
            dict: {
                shelf_life_days, thermal_days, aw_factor, light_factor, light_pct
            }
        """
        thermal_days = self.shelf_life_thermal(T_celsius)

        aw_factor = self.aw_correction_factor(aw)

        # 光降解修正: 用和 thermal_days 一致的 k 基准
        if self.photosensitive or light_lux > 50:
            k_thermal_eff = -math.log(0.9) / (thermal_days * 24 * 3600)
            kl = self.k_light(light_lux, T_celsius)
            total_k = k_thermal_eff + kl
            light_factor = k_thermal_eff / total_k if total_k > 0 else 1.0
            light_pct = 100.0 * kl / total_k if total_k > 0 else 0.0
        else:
            light_factor = 1.0
            light_pct = 0.0

        total_days = thermal_days * aw_factor * light_factor

        return {
            "shelf_life_days": round(total_days, 2),
            "thermal_days": round(thermal_days, 2),
            "aw_factor": round(aw_factor, 4),
            "light_factor": round(light_factor, 4),
            "light_contribution_pct": round(light_pct, 1),
        }

    def quality_retention(
        self,
        T_celsius: float,
        aw: float,
        storage_days: float,
        light_lux: float = 0.0,
    ) -> float:
        """预测储存 storage_days 后的有效成分保留率 (0~1)"""
        result = self.predict_shelf_life(T_celsius, aw, light_lux)
        shelf = result["shelf_life_days"]
        if shelf <= 0:
            return 0.0
        k_eff = -math.log(0.9) / shelf
        retention = math.exp(-k_eff * storage_days)
        return max(0.0, min(1.0, retention))
