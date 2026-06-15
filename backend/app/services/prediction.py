from datetime import datetime, timedelta
from typing import List, Dict, Optional
from ..database import get_client
from ..models.arrhenius import ArrheniusPredictor
from ..models.baranyi import BaranyiRobertsModel
from ..models.priority import get_priority_model
from ..config import DRUG_PARAMS, CLICKHOUSE_DB


class PredictionService:
    def __init__(self):
        self.baranyi = BaranyiRobertsModel()

    def _get_tent_sensor_stats(
        self, tent_id: int, hours: int = 24
    ) -> Dict[str, float]:
        client = get_client()
        since = datetime.utcnow() - timedelta(hours=hours)

        rows = client.execute(
            f"""
            SELECT sensor_type, avg(value) as avg_val
            FROM {CLICKHOUSE_DB}.sensor_readings
            WHERE tent_id = %(tent_id)s AND timestamp >= %(since)s
            GROUP BY sensor_type
            """,
            {"tent_id": tent_id, "since": since},
        )

        stats = {"temperature": 25.0, "humidity": 50.0, "light": 300.0, "ethylene": 0.5, "co2": 400.0}
        for sensor_type, avg_val in rows:
            stats[sensor_type] = float(avg_val)
        return stats

    def _get_tent_aw_stats(self, tent_id: int, hours: int = 24) -> Dict[str, float]:
        client = get_client()
        since = datetime.utcnow() - timedelta(hours=hours)

        rows = client.execute(
            f"""
            SELECT drug_name, avg(water_activity) as avg_aw
            FROM {CLICKHOUSE_DB}.aw_readings
            WHERE tent_id = %(tent_id)s AND timestamp >= %(since)s
            GROUP BY drug_name
            """,
            {"tent_id": tent_id, "since": since},
        )

        result = {}
        for drug_name, avg_aw in rows:
            result[drug_name] = float(avg_aw)
        return result

    def assess_drug_risks(self, tent_id: int, drug_names: List[str]) -> List[Dict]:
        climate = self._get_tent_sensor_stats(tent_id)
        aw_data = self._get_tent_aw_stats(tent_id)

        results = []
        for drug_name in drug_names:
            params = DRUG_PARAMS.get(drug_name)
            if not params:
                continue

            predictor = ArrheniusPredictor(params)
            aw = aw_data.get(drug_name, 0.5)

            shelf_life = predictor.shelf_life_with_aw_correction(climate["temperature"], aw)
            mold_risk = self.baranyi.mold_risk_score(climate["temperature"], aw)

            results.append({
                "tent_id": tent_id,
                "drug_name": drug_name,
                "shelf_life_days": round(shelf_life, 2),
                "mold_risk": round(mold_risk, 4),
                "avg_temperature": round(climate["temperature"], 2),
                "avg_humidity": round(climate["humidity"], 2),
                "avg_aw": round(aw, 4),
                "avg_co2": round(climate.get("co2", 400), 1),
                "avg_ethylene": round(climate.get("ethylene", 0.5), 3),
                "aw_critical": params["aw_critical"],
            })

        return results

    def get_priority_recommendations(self, tent_id: int, drug_names: List[str]) -> List[Dict]:
        risks = self.assess_drug_risks(tent_id, drug_names)
        if not risks:
            return []

        priority_model = get_priority_model()
        predictions = priority_model.batch_predict(risks)

        recommendations = []
        for pred, risk in zip(predictions, risks):
            reasons = []
            if risk["avg_temperature"] > 30:
                reasons.append(f"温度过高({risk['avg_temperature']}°C)")
            if risk["avg_aw"] > 0.6:
                reasons.append(f"水分活度超标(Aw={risk['avg_aw']})")
            if risk["mold_risk"] > 0.5:
                reasons.append(f"霉变风险高({risk['mold_risk']:.0%})")
            if risk["shelf_life_days"] < 30:
                reasons.append(f"有效期不足({risk['shelf_life_days']:.0f}天)")

            recommendations.append({
                "tent_id": tent_id,
                "drug_name": pred["drug_name"],
                "priority_score": pred["priority_score"],
                "priority_level": pred["priority_level"],
                "reason": "；".join(reasons) if reasons else "当前状态良好",
            })

        return recommendations

    def get_microclimate_trend(
        self, tent_id: int, hours: int = 72
    ) -> Dict[str, List]:
        client = get_client()
        since = datetime.utcnow() - timedelta(hours=hours)

        rows = client.execute(
            f"""
            SELECT
                toStartOfInterval(timestamp, INTERVAL 30 MINUTE) as t,
                sensor_type,
                avg(value) as avg_val
            FROM {CLICKHOUSE_DB}.sensor_readings
            WHERE tent_id = %(tent_id)s AND timestamp >= %(since)s
            GROUP BY t, sensor_type
            ORDER BY t
            """,
            {"tent_id": tent_id, "since": since},
        )

        trend = {
            "timestamps": [],
            "temperature": [],
            "humidity": [],
            "light": [],
            "ethylene": [],
            "co2": [],
        }

        time_map: Dict[str, Dict[str, float]] = {}
        for ts, sensor_type, avg_val in rows:
            ts_str = ts.strftime("%Y-%m-%d %H:%M")
            if ts_str not in time_map:
                time_map[ts_str] = {}
            time_map[ts_str][sensor_type] = float(avg_val)

        for ts_str in sorted(time_map.keys()):
            trend["timestamps"].append(ts_str)
            trend["temperature"].append(time_map[ts_str].get("temperature", 0))
            trend["humidity"].append(time_map[ts_str].get("humidity", 0))
            trend["light"].append(time_map[ts_str].get("light", 0))
            trend["ethylene"].append(time_map[ts_str].get("ethylene", 0))
            trend["co2"].append(time_map[ts_str].get("co2", 0))

        return trend

    def get_heatmap_data(self, tent_id: int) -> List[Dict]:
        client = get_client()
        since = datetime.utcnow() - timedelta(hours=24)

        aw_rows = client.execute(
            f"""
            SELECT meter_id, drug_name, avg(water_activity) as avg_aw
            FROM {CLICKHOUSE_DB}.aw_readings
            WHERE tent_id = %(tent_id)s AND timestamp >= %(since)s
            GROUP BY meter_id, drug_name
            ORDER BY meter_id
            """,
            {"tent_id": tent_id, "since": since},
        )

        sensor_rows = client.execute(
            f"""
            SELECT sensor_id, sensor_type, avg(value) as avg_val
            FROM {CLICKHOUSE_DB}.sensor_readings
            WHERE tent_id = %(tent_id)s AND timestamp >= %(since)s
            GROUP BY sensor_id, sensor_type
            ORDER BY sensor_id
            """,
            {"tent_id": tent_id, "since": since},
        )

        heatmap = []
        climate = self._get_tent_sensor_stats(tent_id)

        for meter_id, drug_name, avg_aw in aw_rows:
            params = DRUG_PARAMS.get(drug_name, {})
            predictor = ArrheniusPredictor(params) if params else None
            mold = self.baranyi.mold_risk_score(climate["temperature"], avg_aw)
            shelf = predictor.shelf_life_with_aw_correction(climate["temperature"], avg_aw) if predictor else 999

            risk_score = mold * 60 + max(0, (avg_aw - 0.5) / 0.3) * 20 + max(0, (climate["temperature"] - 20) / 20) * 20

            heatmap.append({
                "meter_id": meter_id,
                "drug_name": drug_name,
                "avg_aw": round(float(avg_aw), 4),
                "risk_score": round(min(1.0, risk_score), 4),
                "mold_risk": round(mold, 4),
                "shelf_life_days": round(shelf, 1),
                "x": (meter_id - 1) % 5,
                "y": (meter_id - 1) // 5,
            })

        return heatmap

    def store_risk_assessments(self, risks: List[Dict]):
        client = get_client()
        now = datetime.utcnow()
        data = [
            (
                now,
                r["tent_id"],
                r["drug_name"],
                r["shelf_life_days"],
                r["mold_risk"],
                r.get("priority_score", 0),
                r["avg_temperature"],
                r["avg_humidity"],
                r["avg_aw"],
            )
            for r in risks
        ]
        client.execute(
            f"""
            INSERT INTO {CLICKHOUSE_DB}.drug_risk_assessments
            (timestamp, tent_id, drug_name, shelf_life_days, mold_risk, priority_score,
             avg_temperature, avg_humidity, avg_aw)
            VALUES
            """,
            data,
        )


_prediction_service = None


def get_prediction_service() -> PredictionService:
    global _prediction_service
    if _prediction_service is None:
        _prediction_service = PredictionService()
    return _prediction_service
