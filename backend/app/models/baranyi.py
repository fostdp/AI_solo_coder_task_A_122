import numpy as np
from typing import Tuple


class BaranyiRobertsModel:
    """
    Baranyi-Roberts microbial growth model for mold risk assessment.
    N(t) = N_max + ln(exp(-v_m * h0) + exp(-N_max * mu_max * t / ln(10)) * ... )

    Simplified form:
    N(t) = N0 + mu_max * A(t) - ln(1 + (exp(mu_max * A(t) - 1)) / (N_max - N0))

    where A(t) = t + (1/mu_max) * ln(exp(-mu_max * t) + exp(-h0))

    Parameters influenced by temperature and water activity:
    - mu_max (maximum growth rate): modified by temperature (cardinal model) and aw
    - lag (lag time): influenced by temperature and aw
    """

    OPT_TEMP = 25.0
    MIN_TEMP = -2.0
    MAX_TEMP = 45.0
    OPT_AW = 0.95
    MIN_AW = 0.60

    def mu_max_base(self) -> float:
        return 0.3

    def temperature_factor(self, T_celsius: float) -> float:
        T = T_celsius
        T_min = self.MIN_TEMP
        T_opt = self.OPT_TEMP
        T_max = self.MAX_TEMP
        if T <= T_min or T >= T_max:
            return 0.0
        if T <= T_opt:
            return ((T - T_min) / (T_opt - T_min)) ** 2
        else:
            return ((T_max - T) / (T_max - T_opt)) ** 2

    def aw_factor(self, aw: float) -> float:
        if aw <= self.MIN_AW:
            return 0.0
        if aw >= self.OPT_AW:
            return 1.0
        return ((aw - self.MIN_AW) / (self.OPT_AW - self.MIN_AW)) ** 2

    def adjusted_mu_max(self, T_celsius: float, aw: float) -> float:
        gamma_T = self.temperature_factor(T_celsius)
        gamma_aw = self.aw_factor(aw)
        return self.mu_max_base() * gamma_T * gamma_aw

    def lag_time(self, T_celsius: float, aw: float) -> float:
        mu = self.adjusted_mu_max(T_celsius, aw)
        if mu <= 0:
            return float("inf")
        h0 = 2.0
        return h0 / mu

    def growth_curve(
        self,
        T_celsius: float,
        aw: float,
        N0: float = 2.0,
        N_max: float = 7.0,
        hours: int = 168,
        steps: int = 100,
    ) -> Tuple[np.ndarray, np.ndarray]:
        mu = self.adjusted_mu_max(T_celsius, aw)
        h0 = 2.0

        t = np.linspace(0, hours, steps)
        if mu <= 1e-10:
            return t, np.full_like(t, N0)

        A = t + (1.0 / mu) * np.log(np.exp(-mu * t) + np.exp(-h0))
        exponent = mu * A - N0
        N = N0 + mu * A - np.log1p(np.exp(exponent) / (np.exp(N_max) - np.exp(N0)))
        N = np.clip(N, N0, N_max)

        return t, N

    def mold_risk_score(self, T_celsius: float, aw: float, exposure_hours: float = 72.0) -> float:
        t, N = self.growth_curve(T_celsius, aw, hours=int(exposure_hours), steps=50)
        final_N = N[-1]
        N0 = 2.0
        N_max = 7.0
        growth = (final_N - N0) / (N_max - N0)
        return max(0.0, min(1.0, growth))
