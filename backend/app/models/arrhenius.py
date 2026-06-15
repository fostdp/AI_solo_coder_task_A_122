import numpy as np
from typing import Dict


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
    """

    R = 8.314

    def __init__(self, drug_params: Dict):
        self.Ea = drug_params["Ea"]
        self.A = drug_params["A"]
        self.T_ref = drug_params["T_ref"]
        self.shelf_life_ref_months = drug_params["shelf_life_ref_months"]

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

    def shelf_life_with_aw_correction(self, T_celsius: float, aw: float) -> float:
        base_shelf_life = self.shelf_life_at_temp(T_celsius)
        aw_correction = 1.0
        if aw > 0.5:
            aw_correction = max(0.1, 1.0 - 2.0 * (aw - 0.5) ** 1.5)
        return base_shelf_life * aw_correction

    def quality_retention(self, T_celsius: float, aw: float, storage_days: float) -> float:
        shelf = self.shelf_life_with_aw_correction(T_celsius, aw)
        if shelf <= 0:
            return 0.0
        k_eff = -np.log(0.9) / shelf
        retention = np.exp(-k_eff * storage_days)
        return max(0.0, min(1.0, retention))
