from clickhouse_driver import Client
from app.config import CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DB


def init_database():
    client = Client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
    )

    client.execute(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DB}")

    client.execute(f"""
    CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.sensor_readings (
        timestamp DateTime64(3),
        tent_id UInt8,
        sensor_id UInt8,
        sensor_type Enum8('temperature' = 1, 'humidity' = 2, 'light' = 3, 'ethylene' = 4, 'co2' = 5),
        value Float32
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (tent_id, sensor_type, timestamp)
    TTL timestamp + INTERVAL 365 DAY
    """)

    client.execute(f"""
    CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.aw_readings (
        timestamp DateTime64(3),
        tent_id UInt8,
        meter_id UInt8,
        drug_name String,
        water_activity Float32
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (tent_id, drug_name, timestamp)
    TTL timestamp + INTERVAL 365 DAY
    """)

    client.execute(f"""
    CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.drug_risk_assessments (
        timestamp DateTime64(3),
        tent_id UInt8,
        drug_name String,
        shelf_life_days Float32,
        mold_risk Float32,
        priority_score Float32,
        avg_temperature Float32,
        avg_humidity Float32,
        avg_aw Float32
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (tent_id, drug_name, timestamp)
    TTL timestamp + INTERVAL 180 DAY
    """)

    client.execute(f"""
    CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.alerts (
        timestamp DateTime64(3),
        tent_id UInt8,
        alert_type Enum8('high_aw' = 1, 'high_temp' = 2, 'combined' = 3),
        severity Enum8('warning' = 1, 'critical' = 2),
        value Float32,
        threshold Float32,
        duration_hours Float32,
        message String,
        notified UInt8
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (tent_id, alert_type, timestamp)
    TTL timestamp + INTERVAL 90 DAY
    """)

    client.execute(f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {CLICKHOUSE_DB}.sensor_30min_avg
    TO {CLICKHOUSE_DB}.sensor_readings
    AS SELECT
        toStartOfThirtyMinutes(timestamp) AS timestamp,
        tent_id,
        sensor_id,
        sensor_type,
        avg(value) AS value
    FROM {CLICKHOUSE_DB}.sensor_readings
    GROUP BY timestamp, tent_id, sensor_id, sensor_type
    """)

    print("Database and tables created successfully.")


if __name__ == "__main__":
    init_database()
