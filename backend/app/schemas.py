from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class SensorReading(BaseModel):
    timestamp: datetime
    tent_id: int
    sensor_id: int
    sensor_type: str
    value: float


class SensorReadingBatch(BaseModel):
    readings: List[SensorReading]


class AwReading(BaseModel):
    timestamp: datetime
    tent_id: int
    meter_id: int
    drug_name: str
    water_activity: float


class AwReadingBatch(BaseModel):
    readings: List[AwReading]


class TentInfo(BaseModel):
    id: int
    name: str
    lat: float
    lng: float
    drugs: List[str]


class DrugRisk(BaseModel):
    tent_id: int
    drug_name: str
    shelf_life_days: float
    mold_risk: float
    priority_score: float
    avg_temperature: float
    avg_humidity: float
    avg_aw: float
    timestamp: Optional[datetime] = None


class AlertRecord(BaseModel):
    timestamp: datetime
    tent_id: int
    alert_type: str
    severity: str
    value: float
    threshold: float
    duration_hours: float
    message: str
    notified: int


class MicroClimateTrend(BaseModel):
    timestamps: List[str]
    temperature: List[float]
    humidity: List[float]
    light: List[float]
    ethylene: List[float]
    co2: List[float]


class PriorityRecommendation(BaseModel):
    tent_id: int
    drug_name: str
    priority_score: float
    priority_level: str
    reason: str


class TentDashboard(BaseModel):
    tent: TentInfo
    current_climate: dict
    drug_risks: List[DrugRisk]
    active_alerts: List[AlertRecord]
    recommendations: List[PriorityRecommendation]
