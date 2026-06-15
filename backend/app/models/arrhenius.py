import numpy as np
from typing import Dict, Optional
from .light_factor import LightDegradationFactor


class ArrheniusPredictor:
    """
    Arrhenius equation based drug shelf life prediction.
    k = A * exp(-Ea / (R * T))
    where:
      k  - degradation rate constant
      A  - pre-exponential factor (1/s)
      Ea - activation energy (J/mol)
      R  - gas constant = 8.314 J/(mol·K)
      T  - absolute temperature (K)

    Shelf life is the time for drug potency to drop to 90% (t90).
    Assuming first-order kinetics: t90 = ln(0.9) / (-k)

    [FIX v1.1] 增加光照修正:
      k_total = k_thermal + k_light,  k_light 通过 LightDegradationFactor 拟合
      对于光敏药材(大黄/麻黄/丹参等),强光下有效期缩短 30-60%
    """

    R = 8.314

    def __init__(self, drug_params: Dict, drug_name: Optional[str] = None):
        self.Ea = drug_params["Ea"]
        self.A = drug_params["A"]
        self.T_ref = drug_params["T_ref"]
        self.shelf_life_ref_months = drug_params["shelf_life_ref_months"]
        self.drug_name = drug_name
        self.light_model = LightDegradationFactor(drug_name) if drug_name else None

    def rate_constant(self, T_kelvin: float) -> float:
        return self.A * np.exp(-self.Ea / (self.R * T_kelvin))

    def k_ref(self) -> float:
        k = -np.log(0.9) / (self.shelf_life_ref_months * 30 * 24 * 3600)
        return k

    def shelf_life_at_temp(self, T_celsius: float) -> float:
        T_k = T_celsius + 273.15
        k_ref = self.k_ref()
        k_T = k_ref * np.exp(-self.Ea / (self.R * T_k)) / np.exp(-self.Ea / (self.R * self.T_ref))
        if k_T <= 0:
            return float("inf")
        t90_seconds = -np.log(0.9) / k_T
        t90_days = t90_seconds / (24 * 3600)
        return t90_days

    def shelf_life_with_aw_correction(
        self,
        T_celsius: float,
        aw: float,
        light_lux: float = 0.0,
    ) -> float:
        base_shelf_life = self.shelf_life_at_temp(T_celsius)

        aw_correction = 1.0
        if aw > 0.5:
            aw_correction = max(0.1, 1.0 - 2.0 * (aw - 0.5) ** 1.5)

        light_correction = 1.0
        if self.light_model is not None and light_lux > 0:
            t90_seconds = base_shelf_life * 24 * 3600
            k_thermal = -np.log(0.9) / t90_seconds if t90_seconds > 0 else 1e-12
            light_correction = self.light_model.correction_factor(light_lux, T_celsius, k_thermal)

        return base_shelf_life * aw_correction * light_correction

    def quality_retention(
        self,
        T_celsius: float,
        aw: float,
        storage_days: float,
        light_lux: float = 0.0,
    ) -> float:
        shelf = self.shelf_life_with_aw_correction(T_celsius, aw, light_lux)
        if shelf <= 0:
            return 0.0
        k_eff = -np.log(0.9) / shelf
        retention = np.exp(-k_eff * storage_days)
        return max(0.0, min(1.0, retention))

    def light_contribution_pct(self, T_celsius: float, light_lux: float) -> float:
        """返回光降解在总降解中的占比 (%), 供调试展示"""
        if self.light_model is None or light_lux <= 0:
            return 0.0
        base = self.shelf_life_at_temp(T_celsius)
        t90_seconds = base * 24 * 3600
        k_thermal = -np.log(0.9) / t90_seconds if t90_seconds > 0 else 1e-12
        return self.light_model.light_degradation_pct(light_lux, T_celsius, k_thermal)
