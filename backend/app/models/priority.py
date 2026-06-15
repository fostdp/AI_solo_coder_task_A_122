import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
import joblib
import os
from typing import List, Dict, Tuple


class PriorityModel:
    """
    Random Forest model that fuses microclimate parameters to produce
    drug dispatch priority scores. Higher score = more urgent need to
    relocate or replace the drug.

    Features: [avg_temp, avg_humidity, avg_aw, avg_co2, avg_ethylene,
               shelf_life_days, mold_risk, aw_critical_delta]
    Target: priority_score (0-100)
    """

    FEATURE_NAMES = [
        "avg_temp",
        "avg_humidity",
        "avg_aw",
        "avg_co2",
        "avg_ethylene",
        "shelf_life_days",
        "mold_risk",
        "aw_critical_delta",
    ]

    def __init__(self):
        self.model = RandomForestRegressor(
            n_estimators=200,
            max_depth=10,
            min_samples_split=5,
            random_state=42,
        )
        self.scaler = StandardScaler()
        self._trained = False
        self._model_path = os.path.join(os.path.dirname(__file__), "priority_model.pkl")

    def _generate_training_data(self, n_samples: int = 2000) -> Tuple[np.ndarray, np.ndarray]:
        rng = np.random.RandomState(42)

        temps = rng.uniform(5, 42, n_samples)
        humidities = rng.uniform(20, 95, n_samples)
        aws = rng.uniform(0.3, 0.85, n_samples)
        co2s = rng.uniform(300, 2000, n_samples)
        ethylenes = rng.uniform(0, 5, n_samples)
        shelf_lives = rng.uniform(5, 800, n_samples)
        mold_risks = rng.uniform(0, 1, n_samples)
        aw_critical_deltas = rng.uniform(-0.15, 0.2, n_samples)

        X = np.column_stack([
            temps, humidities, aws, co2s, ethylenes,
            shelf_lives, mold_risks, aw_critical_deltas,
        ])

        y = (
            (temps > 30).astype(float) * 25
            + (aws > 0.6).astype(float) * 20
            + mold_risks * 25
            + np.clip(1 - shelf_lives / 800, 0, 1) * 15
            + np.clip(aw_critical_deltas / 0.2, 0, 1) * 10
            + (humidities > 70).astype(float) * 5
        )
        y = np.clip(y + rng.normal(0, 3, n_samples), 0, 100)

        return X, y

    def train(self):
        X, y = self._generate_training_data()
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self._trained = True
        self.save()

    def predict(
        self,
        avg_temp: float,
        avg_humidity: float,
        avg_aw: float,
        avg_co2: float,
        avg_ethylene: float,
        shelf_life_days: float,
        mold_risk: float,
        aw_critical: float,
    ) -> Tuple[float, str]:
        if not self._trained:
            if os.path.exists(self._model_path):
                self.load()
            else:
                self.train()

        aw_critical_delta = avg_aw - aw_critical
        features = np.array([[
            avg_temp, avg_humidity, avg_aw, avg_co2, avg_ethylene,
            shelf_life_days, mold_risk, aw_critical_delta,
        ]])
        features_scaled = self.scaler.transform(features)
        score = float(self.model.predict(features_scaled)[0])
        score = max(0.0, min(100.0, score))

        if score >= 75:
            level = "紧急"
        elif score >= 50:
            level = "高"
        elif score >= 25:
            level = "中"
        else:
            level = "低"

        return score, level

    def batch_predict(self, drug_features: List[Dict]) -> List[Dict]:
        results = []
        for feat in drug_features:
            score, level = self.predict(
                avg_temp=feat["avg_temperature"],
                avg_humidity=feat["avg_humidity"],
                avg_aw=feat["avg_aw"],
                avg_co2=feat.get("avg_co2", 400),
                avg_ethylene=feat.get("avg_ethylene", 0.5),
                shelf_life_days=feat["shelf_life_days"],
                mold_risk=feat["mold_risk"],
                aw_critical=feat["aw_critical"],
            )
            results.append({
                "tent_id": feat["tent_id"],
                "drug_name": feat["drug_name"],
                "priority_score": round(score, 2),
                "priority_level": level,
            })
        return results

    def save(self):
        joblib.dump({"model": self.model, "scaler": self.scaler}, self._model_path)

    def load(self):
        data = joblib.load(self._model_path)
        self.model = data["model"]
        self.scaler = data["scaler"]
        self._trained = True


_priority_model = None


def get_priority_model() -> PriorityModel:
    global _priority_model
    if _priority_model is None:
        _priority_model = PriorityModel()
    return _priority_model
