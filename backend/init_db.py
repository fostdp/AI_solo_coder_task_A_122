from clickhouse_driver import Client
from shared.config_loader import get_clickhouse_config


def init_database():
    cfg = get_clickhouse_config()
    client = Client(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
    )
    db = cfg["database"]

    client.execute(f"CREATE DATABASE IF NOT EXISTS {db}")

    # [v2] 复合分区键 + TTL 保留 2 年 (730 天)
    # - 复合分区: (月, tent_id) → 带 tent_id 查询可分区裁剪 ~20x
    # - 跳数索引: set(0) = bloom-like, minmax 用于时间范围
    # - TTL: sensor_readings / aw_readings 保留 2 年, 风险评估 1 年, 告警 0.5 年

    client.execute(f"""
    CREATE TABLE IF NOT EXISTS {db}.sensor_readings (
        timestamp DateTime64(3),
        tent_id UInt8,
        sensor_id UInt8,
        sensor_type Enum8('temperature' = 1, 'humidity' = 2, 'light' = 3, 'ethylene' = 4, 'co2' = 5),
        value Float32
    ) ENGINE = MergeTree()
    PARTITION BY (toYYYYMM(timestamp), tent_id)
    ORDER BY (tent_id, sensor_type, timestamp)
    INDEX idx_tent_sensor (tent_id, sensor_type) TYPE set(0) GRANULARITY 1
    INDEX idx_ts_minmax timestamp TYPE minmax GRANULARITY 4
    TTL timestamp + INTERVAL 730 DAY
    SETTINGS min_bytes_for_wide_part = 10485760
    """)

    client.execute(f"""
    CREATE TABLE IF NOT EXISTS {db}.aw_readings (
        timestamp DateTime64(3),
        tent_id UInt8,
        meter_id UInt8,
        drug_name String,
        water_activity Float32
    ) ENGINE = MergeTree()
    PARTITION BY (toYYYYMM(timestamp), tent_id)
    ORDER BY (tent_id, drug_name, timestamp)
    INDEX idx_tent_drug (tent_id, drug_name) TYPE set(0) GRANULARITY 1
    TTL timestamp + INTERVAL 730 DAY
    SETTINGS min_bytes_for_wide_part = 10485760
    """)

    client.execute(f"""
    CREATE TABLE IF NOT EXISTS {db}.drug_risk_assessments (
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
    PARTITION BY (toYYYYMM(timestamp), tent_id)
    ORDER BY (tent_id, drug_name, timestamp)
    TTL timestamp + INTERVAL 365 DAY
    SETTINGS min_bytes_for_wide_part = 10485760
    """)

    client.execute(f"""
    CREATE TABLE IF NOT EXISTS {db}.alerts (
        timestamp DateTime64(3),
        tent_id UInt8,
        alert_type Enum8('high_aw' = 1, 'high_temp' = 2, 'combined' = 3, 'mold_risk' = 4),
        severity Enum8('warning' = 1, 'critical' = 2),
        value Float32,
        threshold Float32,
        duration_hours Float32,
        message String,
        notified UInt8
    ) ENGINE = MergeTree()
    PARTITION BY (toYYYYMM(timestamp), tent_id)
    ORDER BY (tent_id, alert_type, timestamp)
    TTL timestamp + INTERVAL 180 DAY
    SETTINGS min_bytes_for_wide_part = 10485760
    """)

    print("Database and tables created (v2: composite partitions + TTL 2 years).")


if __name__ == "__main__":
    init_database()

