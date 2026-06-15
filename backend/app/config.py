import os

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", 9000))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "silkroad_medical")

ALERT_WATER_ACTIVITY_THRESHOLD = 0.6
ALERT_TEMPERATURE_THRESHOLD = 30.0
ALERT_DURATION_HOURS = 4
ALERT_CHECK_INTERVAL_MINUTES = 30

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.example.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "archaeologist@example.com")

SATELLITE_API_URL = os.getenv("SATELLITE_API_URL", "http://satellite-gateway:8080/api/send")
SATELLITE_ENABLED = os.getenv("SATELLITE_ENABLED", "false").lower() == "true"

TENT_COUNT = 5
SENSORS_PER_TENT = 20
AW_METERS_PER_TENT = 10
REPORT_INTERVAL_MINUTES = 30

DUNHUANG_LAT = 40.1420
DUNHUANG_LNG = 94.6619

TENT_CONFIGS = [
    {"id": 1, "name": "悬泉置·东帐", "lat": 40.1435, "lng": 94.6635, "drugs": ["当归", "大黄", "甘草"]},
    {"id": 2, "name": "悬泉置·西帐", "lat": 40.1415, "lng": 94.6600, "drugs": ["黄芪", "白术", "茯苓"]},
    {"id": 3, "name": "悬泉置·南帐", "lat": 40.1405, "lng": 94.6625, "drugs": ["川芎", "白芍", "熟地"]},
    {"id": 4, "name": "悬泉置·北帐", "lat": 40.1445, "lng": 94.6610, "drugs": ["桂枝", "麻黄", "细辛"]},
    {"id": 5, "name": "悬泉置·中帐", "lat": 40.1420, "lng": 94.6619, "drugs": ["人参", "丹参", "五味子"]},
]

DRUG_PARAMS = {
    "当归": {"Ea": 85000, "A": 1.2e12, "T_ref": 298.15, "aw_critical": 0.65, "shelf_life_ref_months": 24},
    "大黄": {"Ea": 78000, "A": 8.5e11, "T_ref": 298.15, "aw_critical": 0.60, "shelf_life_ref_months": 18},
    "甘草": {"Ea": 72000, "A": 6.3e11, "T_ref": 298.15, "aw_critical": 0.62, "shelf_life_ref_months": 30},
    "黄芪": {"Ea": 80000, "A": 9.1e11, "T_ref": 298.15, "aw_critical": 0.63, "shelf_life_ref_months": 24},
    "白术": {"Ea": 76000, "A": 7.8e11, "T_ref": 298.15, "aw_critical": 0.58, "shelf_life_ref_months": 20},
    "茯苓": {"Ea": 68000, "A": 5.2e11, "T_ref": 298.15, "aw_critical": 0.66, "shelf_life_ref_months": 36},
    "川芎": {"Ea": 82000, "A": 1.0e12, "T_ref": 298.15, "aw_critical": 0.60, "shelf_life_ref_months": 22},
    "白芍": {"Ea": 75000, "A": 7.2e11, "T_ref": 298.15, "aw_critical": 0.61, "shelf_life_ref_months": 26},
    "熟地": {"Ea": 88000, "A": 1.4e12, "T_ref": 298.15, "aw_critical": 0.59, "shelf_life_ref_months": 16},
    "桂枝": {"Ea": 70000, "A": 5.8e11, "T_ref": 298.15, "aw_critical": 0.64, "shelf_life_ref_months": 28},
    "麻黄": {"Ea": 73000, "A": 6.5e11, "T_ref": 298.15, "aw_critical": 0.57, "shelf_life_ref_months": 15},
    "细辛": {"Ea": 79000, "A": 8.9e11, "T_ref": 298.15, "aw_critical": 0.55, "shelf_life_ref_months": 12},
    "人参": {"Ea": 90000, "A": 1.5e12, "T_ref": 298.15, "aw_critical": 0.56, "shelf_life_ref_months": 36},
    "丹参": {"Ea": 83000, "A": 1.1e12, "T_ref": 298.15, "aw_critical": 0.62, "shelf_life_ref_months": 20},
    "五味子": {"Ea": 77000, "A": 7.5e11, "T_ref": 298.15, "aw_critical": 0.58, "shelf_life_ref_months": 18},
}
