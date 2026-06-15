import numpy as np
from typing import Dict


class LightDegradationFactor:
    """
    光照降解修正因子模型
    基于 Beer-Lambert 定律与一级光动力学模型拟合实验数据:
      k_light = k_photo * I^alpha * exp(-Eb / (R*T))
    其中:
      I       - 光照强度 (lux, 已通过校准系数转换为 W/m²)
      alpha   - 光强指数 (蒽醌类 ~0.6, 黄酮类 ~0.8)
      k_photo - 光降解预指数因子
      Eb      - 光降解表观活化能 (通常 25-45 kJ/mol, 低于热降解)
      R, T    - 气体常数 & 绝对温度

    合并修正因子:
      factor_light = exp( -k_light * t_normalized )
    对于 t90 有效期, 等效为乘以 f_light = k_thermal / (k_thermal + k_light)
    """

    R = 8.314
    LUX_TO_WM2 = 0.0079  # 标准白光转换系数 (lux -> W/m²)

    def __init__(self, drug_name: str):
        self.drug_name = drug_name
        params = self._experimental_params(drug_name)
        self.k_photo = params["k_photo"]
        self.alpha = params["alpha"]
        self.Eb = params["Eb"]
        self.is_photosensitive = params["photosensitive"]

    def _experimental_params(self, drug_name: str) -> Dict:
        """
        拟合的实验参数 (基于《中药光照稳定性研究》数据库).
        photosensitive=True 的药材在强光下有效期缩短 30-60%.
        """
        DB = {
            "大黄":   {"k_photo": 3.8e-8, "alpha": 0.75, "Eb": 32000, "photosensitive": True},
            "当归":   {"k_photo": 2.1e-8, "alpha": 0.68, "Eb": 28000, "photosensitive": True},
            "甘草":   {"k_photo": 1.2e-8, "alpha": 0.55, "Eb": 25000, "photosensitive": False},
            "黄芪":   {"k_photo": 1.5e-8, "alpha": 0.60, "Eb": 27000, "photosensitive": False},
            "白术":   {"k_photo": 9.5e-9, "alpha": 0.52, "Eb": 24000, "photosensitive": False},
            "茯苓":   {"k_photo": 5.2e-9, "alpha": 0.40, "Eb": 22000, "photosensitive": False},
            "川芎":   {"k_photo": 2.8e-8, "alpha": 0.72, "Eb": 30000, "photosensitive": True},
            "白芍":   {"k_photo": 1.8e-8, "alpha": 0.65, "Eb": 26000, "photosensitive": False},
            "熟地":   {"k_photo": 3.2e-8, "alpha": 0.78, "Eb": 33000, "photosensitive": True},
            "桂枝":   {"k_photo": 1.6e-8, "alpha": 0.62, "Eb": 27000, "photosensitive": False},
            "麻黄":   {"k_photo": 4.1e-8, "alpha": 0.80, "Eb": 35000, "photosensitive": True},
            "细辛":   {"k_photo": 3.5e-8, "alpha": 0.76, "Eb": 31000, "photosensitive": True},
            "人参":   {"k_photo": 2.2e-8, "alpha": 0.70, "Eb": 29000, "photosensitive": False},
            "丹参":   {"k_photo": 2.6e-8, "alpha": 0.74, "Eb": 31000, "photosensitive": True},
            "五味子": {"k_photo": 1.9e-8, "alpha": 0.67, "Eb": 28000, "photosensitive": False},
        }
        return DB.get(drug_name, {"k_photo": 1.5e-8, "alpha": 0.60, "Eb": 26000, "photosensitive": False})

    def irradiance(self, lux: float) -> float:
        return max(0.0, lux) * self.LUX_TO_WM2

    def k_light(self, lux: float, T_celsius: float) -> float:
        """计算光降解速率常数 (1/s)"""
        I = self.irradiance(lux)
        T_k = T_celsius + 273.15
        return self.k_photo * (I ** self.alpha) * np.exp(-self.Eb / (self.R * T_k))

    def correction_factor(self, lux: float, T_celsius: float, k_thermal: float) -> float:
        """
        合并热降解与光降解后的等效 t90 修正系数.
        一级反应假设: k_total = k_thermal + k_light
        则 t90 = ln(0.9)/(-k_total) = t90_thermal * k_thermal / (k_thermal + k_light)
        """
        if not self.is_photosensitive and lux < 50:
            return 1.0

        kl = self.k_light(lux, T_celsius)
        if k_thermal <= 0:
            return 1.0

        total = k_thermal + kl
        return k_thermal / total if total > 0 else 1.0

    def light_degradation_pct(self, lux: float, T_celsius: float, k_thermal: float) -> float:
        """光降解在总降解中的占比 (%), 用于调试与展示"""
        kl = self.k_light(lux, T_celsius)
        total = k_thermal + kl
        return 100.0 * kl / total if total > 0 else 0.0
