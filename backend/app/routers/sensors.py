from fastapi import APIRouter, Query
from datetime import datetime
from typing import List
from ..database import get_client
from ..config import CLICKHOUSE_DB
from ..schemas import SensorReading, AwReading, SensorReadingBatch, AwReadingBatch, MicroClimateTrend
from ..lora.ingest_worker import ingest_sensors_async, ingest_aw_async, ingest_stats

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


@router.post("/readings")
async def ingest_sensor_readings(batch: SensorReadingBatch):
    """[FIX v1.1] 入队异步批量写入, 避免高频 LoRa 上报阻塞 worker"""
    data = [
        {
            "timestamp": r.timestamp,
            "tent_id": r.tent_id,
            "sensor_id": r.sensor_id,
            "sensor_type": r.sensor_type,
            "value": r.value,
        }
        for r in batch.readings
    ]
    await ingest_sensors_async(data)
    return {"status": "queued", "count": len(data), **ingest_stats()}


@router.post("/aw-readings")
async def ingest_aw_readings(batch: AwReadingBatch):
    """[FIX v1.1] 入队异步批量写入"""
    data = [
        {
            "timestamp": r.timestamp,
            "tent_id": r.tent_id,
            "meter_id": r.meter_id,
            "drug_name": r.drug_name,
            "water_activity": r.water_activity,
        }
        for r in batch.readings
    ]
    await ingest_aw_async(data)
    return {"status": "queued", "count": len(data), **ingest_stats()}


@router.get("/latest/{tent_id}")
def get_latest_readings(tent_id: int, limit: int = Query(default=100, le=500)):
    client = get_client()

    sensor_rows = client.execute(
        f"""
        SELECT timestamp, sensor_id, sensor_type, value
        FROM {CLICKHOUSE_DB}.sensor_readings
        WHERE tent_id = %(tent_id)s
        ORDER BY timestamp DESC
        LIMIT %(limit)s
        """,
        {"tent_id": tent_id, "limit": limit},
    )

    aw_rows = client.execute(
        f"""
        SELECT timestamp, meter_id, drug_name, water_activity
        FROM {CLICKHOUSE_DB}.aw_readings
        WHERE tent_id = %(tent_id)s
        ORDER BY timestamp DESC
        LIMIT %(limit)s
        """,
        {"tent_id": tent_id, "limit": limit},
    )

    return {
        "sensor_readings": [
            {
                "timestamp": r[0].strftime("%Y-%m-%d %H:%M:%S"),
                "sensor_id": r[1],
                "sensor_type": r[2],
                "value": round(float(r[3]), 3),
            }
            for r in sensor_rows
        ],
        "aw_readings": [
            {
                "timestamp": r[0].strftime("%Y-%m-%d %H:%M:%S"),
                "meter_id": r[1],
                "drug_name": r[2],
                "water_activity": round(float(r[3]), 4),
            }
            for r in aw_rows
        ],
    }


@router.get("/trend/{tent_id}", response_model=MicroClimateTrend)
def get_trend(tent_id: int, hours: int = Query(default=72, le=168)):
    from ..services.prediction import get_prediction_service
    svc = get_prediction_service()
    return svc.get_microclimate_trend(tent_id, hours)
