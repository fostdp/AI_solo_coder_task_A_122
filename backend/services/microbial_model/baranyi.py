"""
Baranyi-Roberts 微生物生长模型
用于评估药材霉变风险

Baranyi-Roberts 方程:
  dN/dt = mu_max * (q / (1 + q)) * (1 - N / N_max) * N
  dq/dt = mu_max * q

积分形式:
  N(t) = N0 + mu_max * A(t) - ln(1 + (exp(mu_max*A(t)) - 1) / (exp(N_max) - exp(N0)))
  A(t) = t + (1/mu_max) * ln(exp(-mu_max*t) + exp(-h0))

其中:
  N       - 菌量 (log CFU/g)
  mu_max  - 最大比生长速率
  h0      - 延迟期参数
  N0      - 初始菌量
  N_max   - 最大菌量

温度影响 (cardinal model 简化):
  T <= T_min 或 T >= T_max: mu = 0
  T_min < T <= T_opt:  mu = mu_max_base * ((T-T_min)/(T_opt-T_min))^2
  T_opt < T < T_max:   mu = mu_max_base * ((T_max-T)/(T_max-T_opt))^2

水分活度影响:
  aw <= aw_min: mu = 0
  aw >  aw_min: mu *= ((aw - aw_min) / (aw_opt - aw_min))^2
"""
import math
from typing import Tuple, List, Optional

from shared.config_loader import get_microbial_config


class BaranyiRobertsModel:
    """
    Baranyi-Roberts 微生物生长模型

    用于预测不同温湿度/水分活度下的微生物生长曲线, 评估霉变风险
    """

    def __init__(self, config: Optional[dict] = None):
        cfg = config or get_microbial_config()
        self.mu_max_base = cfg.get("mu_max_base", 0.3)      # /h
        self.opt_temp = cfg.get("opt_temp", 25.0)            # °C
        self.min_temp = cfg.get("min_temp", -2.0)            # °C
        self.max_temp = cfg.get("max_temp", 45.0)            # °C
        self.opt_aw = cfg.get("opt_aw", 0.95)
        self.min_aw = cfg.get("min_aw", 0.60)
        self.N0 = cfg.get("N0", 2.0)        # log CFU/g
        self.N_max = cfg.get("N_max", 7.0)  # log CFU/g
        self.h0 = cfg.get("h0", 2.0)

    # ---- 温度因子 ----
    def temperature_factor(self, T_celsius: float) -> float:
        """温度对生长速率的影响 (0~1)"""
        T = T_celsius
        if T <= self.min_temp or T >= self.max_temp:
            return 0.0
        if T <= self.opt_temp:
            return ((T - self.min_temp) / (self.opt_temp - self.min_temp)) ** 2
        else:
            return ((self.max_temp - T) / (self.max_temp - self.opt_temp)) ** 2

    # ---- 水分活度因子 ----
    def aw_factor(self, aw: float) -> float:
        """水分活度对生长速率的影响 (0~1)"""
        if aw <= self.min_aw:
            return 0.0
        if aw >= self.opt_aw:
            return 1.0
        return ((aw - self.min_aw) / (self.opt_aw - self.min_aw)) ** 2

    # ---- 最大生长速率 ----
    def mu_max(self, T_celsius: float, aw: float) -> float:
        """校正后的最大比生长速率 (/h)"""
        gamma_T = self.temperature_factor(T_celsius)
        gamma_aw = self.aw_factor(aw)
        return self.mu_max_base * gamma_T * gamma_aw

    # ---- 延迟期 ----
    def lag_time(self, T_celsius: float, aw: float) -> float:
        """延迟期 (小时)"""
        mu = self.mu_max(T_celsius, aw)
        if mu <= 1e-10:
            return float("inf")
        return self.h0 / mu

    # ---- 生长曲线 ----
    def growth_curve(
        self,
        T_celsius: float,
        aw: float,
        hours: int = 168,
        steps: int = 100,
        N0: Optional[float] = None,
    ) -> Tuple[List[float], List[float]]:
        """
        计算生长曲线

        Args:
            T_celsius: 温度 (°C)
            aw: 水分活度
            hours: 模拟时长 (小时)
            steps: 时间步数
            N0: 初始菌量 (log CFU/g), None 用默认

        Returns:
            (times, N_values): 时间数组 (h), 菌量数组 (log CFU/g)
        """
        mu = self.mu_max(T_celsius, aw)
        n0 = N0 if N0 is not None else self.N0
        n_max = self.N_max

        if mu <= 1e-10:
            times = [i * hours / (steps - 1) for i in range(steps)]
            return times, [n0] * steps

        times = []
        N_values = []
        exp_n0 = math.exp(n0)
        exp_nmax = math.exp(n_max)
        denom_numerator_base = exp_nmax - exp_n0
        h0 = self.h0
        exp_minus_h0 = math.exp(-h0)
        one_plus_exp_minus_h0 = 1.0 + exp_minus_h0

        for i in range(steps):
            t = i * hours / (steps - 1)
            times.append(t)

            if mu <= 1e-10:
                N_values.append(n0)
                continue

            # Baranyi-Roberts 积分形式
            # A(t) = t + (1/mu) * ln((exp(-mu*t) + exp(-h0)) / (1 + exp(-h0)))
            exp_minus_mut = math.exp(-mu * t)
            A = t + (1.0 / mu) * math.log(
                (exp_minus_mut + exp_minus_h0) / one_plus_exp_minus_h0
            )

            # N(t) = N0 + mu*A - ln(1 + (exp(mu*A + N0) - exp(N0)) / (exp(Nmax) - exp(N0)))
            exp_muA_plus_n0 = math.exp(mu * A + n0)
            numerator = exp_muA_plus_n0 - exp_n0
            denom = 1.0 + numerator / denom_numerator_base

            if denom <= 0:
                N_values.append(n_max)
            else:
                N = n0 + mu * A - math.log(denom)
                N_values.append(max(n0, min(n_max, N)))

        return times, N_values

    # ---- 霉变风险评分 ----
    def mold_risk_score(
        self,
        T_celsius: float,
        aw: float,
        exposure_hours: float = 72.0,
        N0: Optional[float] = None,
    ) -> float:
        """
        计算霉变风险评分 (0~1)
        基于暴露时间后的最终菌量与 N0 和 N_max 的相对位置

        Args:
            T_celsius: 温度
            aw: 水分活度
            exposure_hours: 暴露时间 (小时)
            N0: 初始菌量

        Returns:
            risk: 0~1, 越高风险越大
        """
        mu = self.mu_max(T_celsius, aw)
        n0 = N0 if N0 is not None else self.N0
        n_max = self.N_max

        if mu <= 1e-10:
            return 0.0

        # Baranyi-Roberts 单点计算
        exp_minus_h0 = math.exp(-self.h0)
        one_plus_exp_minus_h0 = 1.0 + exp_minus_h0
        exp_minus_mut = math.exp(-mu * exposure_hours)

        A = exposure_hours + (1.0 / mu) * math.log(
            (exp_minus_mut + exp_minus_h0) / one_plus_exp_minus_h0
        )

        exp_n0 = math.exp(n0)
        exp_nmax = math.exp(n_max)
        exp_muA_plus_n0 = math.exp(mu * A + n0)
        numerator = exp_muA_plus_n0 - exp_n0
        denom = 1.0 + numerator / (exp_nmax - exp_n0)

        if denom <= 0:
            final_N = n_max
        else:
            final_N = n0 + mu * A - math.log(denom)
            final_N = max(n0, min(n_max, final_N))

        # 归一化到 0~1
        growth_range = n_max - n0
        if growth_range <= 0:
            return 0.0
        return max(0.0, min(1.0, (final_N - n0) / growth_range))

    def risk_level(self, risk_score: float) -> str:
        """风险等级文字描述"""
        if risk_score < 0.2:
            return "低"
        elif risk_score < 0.5:
            return "中"
        elif risk_score < 0.8:
            return "高"
        else:
            return "极高"
