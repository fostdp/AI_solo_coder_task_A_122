"""
API Gateway - 主服务入口
整合所有微服务, 提供 REST API 和前端静态文件

[v3 工程化] 增加:
  - loguru 结构化日志 (JSON, 可配置文件输出)
  - Prometheus 指标: http 请求量/延迟、LoRa 采集、模型预测耗时
  - /healthz 健康检查、/metrics 指标端点
"""
import os
import sys
import time
import socket
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

# ------------------------------------------------------------
#  loguru 初始化 (必须在 import logging 相关之前)
# ------------------------------------------------------------
try:
    from loguru import logger
except ImportError:
    logger = __import__("logging").getLogger("silkroad")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "")

def _setup_logger():
    """配置 loguru: 控制台 + 可选文件 (JSON Lines 格式)"""
    logger.remove()

    fmt_color = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    logger.add(
        sys.stdout,
        level=LOG_LEVEL,
        format=fmt_color,
        colorize=True,
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )

    if LOG_FILE:
        logger.add(
            LOG_FILE,
            level=LOG_LEVEL,
            rotation="100 MB",
            retention="14 days",
            compression="gz",
            serialize=True,
            enqueue=True,
            encoding="utf-8",
        )

    # 把标准 logging 转发到 loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

_setup_logger()

# ------------------------------------------------------------
#  Prometheus 指标
# ------------------------------------------------------------
try:
    from prometheus_client import (
        Counter, Histogram, Gauge,
        CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
    )

    METRIC_REGISTRY = CollectorRegistry()

    HTTP_REQUESTS = Counter(
        "silkroad_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status_code"],
        registry=METRIC_REGISTRY,
    )
    HTTP_DURATION = Histogram(
        "silkroad_http_request_duration_seconds",
        "HTTP request duration",
        ["method", "path"],
        buckets=(0.01, 0.05, 0.1, 0.3, 0.5, 1.0, 3.0, 5.0, 10.0, 30.0),
        registry=METRIC_REGISTRY,
    )
    LORA_INGEST = Counter(
        "silkroad_lora_ingest_total",
        "LoRa ingest counts",
        ["type", "result"],
        registry=METRIC_REGISTRY,
    )
    PREDICT_DURATION = Histogram(
        "silkroad_model_predict_duration_seconds",
        "Model prediction duration",
        ["service", "action"],
        buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
        registry=METRIC_REGISTRY,
    )
    ALERTS_TOTAL = Counter(
        "silkroad_alerts_total",
        "Alert count",
        ["type", "severity"],
        registry=METRIC_REGISTRY,
    )
    SERVICE_STATUS = Gauge(
        "silkroad_service_status",
        "Up/Down status of each internal service",
        ["service"],
        registry=METRIC_REGISTRY,
    )
    PROM_ENABLED = True
    logger.info("Prometheus metrics enabled")
except Exception as e:
    logger.warning("Prometheus disabled: {0}", e)
    PROM_ENABLED = False

# ------------------------------------------------------------
#  FastAPI + 服务
# ------------------------------------------------------------
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shared.config_loader import get_tents, get_tent
from shared.redis_streams import RedisStreamClient

from services.lora_ingest.service import LoraIngestService
from services.arrhenius_predictor.service import ArrheniusService
from services.microbial_model.service import MicrobialService
from services.alert_broker.service import AlertBrokerService

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

_services: dict = {}


# ------------------------------------------------------------
#  中间件: Prometheus HTTP 指标
# ------------------------------------------------------------
class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        if PROM_ENABLED and not request.url.path.startswith("/metrics"):
            path = _normalize_path(request.url.path)
            HTTP_REQUESTS.labels(
                method=request.method, path=path,
                status_code=str(response.status_code),
            ).inc()
            HTTP_DURATION.labels(method=request.method, path=path).observe(duration)
        return response


def _normalize_path(p: str) -> str:
    parts = p.rstrip("/").split("/")
    out = []
    for part in parts:
        if part.isdigit():
            out.append("{id}")
        else:
            out.append(part)
    return "/".join(out) or "/"


# ------------------------------------------------------------
#  Lifespan
# ------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting API Gateway v2 on host={host}", host=socket.gethostname())

    redis_client = RedisStreamClient()
    try:
        await redis_client.connect()
        logger.success("Redis Stream connected")
    except Exception as e:
        logger.warning("Redis not available, library-only mode: {e}", e=e)
        redis_client = None

    for name, cls, kwargs in [
        ("lora",      LoraIngestService,      {}),
        ("arrhenius", ArrheniusService,       {"consume_stream": False}),
        ("microbial", MicrobialService,       {"consume_stream": False}),
        ("alert",     AlertBrokerService,     {"with_scheduler": False}),
    ]:
        try:
            t0 = time.perf_counter()
            svc = cls(redis_client=redis_client)
            await svc.start(**kwargs)
            _services[name] = svc
            if PROM_ENABLED:
                SERVICE_STATUS.labels(service=name).set(1)
            logger.success("Service started: {n} ({t:.2f}ms)",
                           n=name, t=(time.perf_counter() - t0) * 1000)
        except Exception as e:
            logger.error("Failed to start service {n}: {e}", n=name, e=e)
            if PROM_ENABLED:
                SERVICE_STATUS.labels(service=name).set(0)

    yield

    for name, svc in reversed(list(_services.items())):
        try:
            await svc.stop()
            logger.info("Service stopped: {n}", n=name)
        except Exception as e:
            logger.error("Error stopping {n}: {e}", n=name, e=e)
    _services.clear()
    logger.info("API Gateway shutdown complete")


app = FastAPI(
    title="丝绸之路医疗帐篷微气候与药品变质预测系统",
    description="敦煌悬泉置汉代医疗帐篷 - 微气候监测与药品变质风险预测 API",
    version="2.1.0",
    lifespan=lifespan,
)
app.add_middleware(PrometheusMiddleware)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ============================================================
#  核心端点: /healthz /metrics
# ============================================================
@app.get("/healthz", tags=["system"])
async def healthz():
    """Kubernetes / Docker 健康检查端点"""
    unhealthy = []
    for n, svc in _services.items():
        try:
            ok = getattr(svc, "healthy", True)
            if not ok:
                unhealthy.append(n)
        except Exception:
            pass
    status = "healthy" if not unhealthy else "degraded"
    return {
        "status": status,
        "version": "2.1.0",
        "services": list(_services.keys()),
        "unhealthy": unhealthy,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/metrics", tags=["system"])
async def prometheus_metrics():
    """Prometheus 抓取端点"""
    if not PROM_ENABLED:
        return PlainTextResponse("# Prometheus metrics disabled\n", status_code=501)
    from fastapi.responses import Response
    data = generate_latest(METRIC_REGISTRY)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def serve_frontend():
    if FRONTEND_DIR.exists():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
    return {"message": "Silk Road Medical Tent API v2.1", "docs": "/docs"}


# ============================================================
#  Tents
# ============================================================
@app.get("/api/tents/", tags=["tents"])
def list_tents():
    return get_tents()


@app.get("/api/tents/{tent_id}", tags=["tents"])
def get_tent_info(tent_id: int):
    tent = get_tent(tent_id)
    if not tent:
        raise HTTPException(status_code=404, detail="Tent not found")
    return tent


# ============================================================
#  Sensors / LoRa Ingest
# ============================================================
@app.post("/api/sensors/readings", tags=["sensors"])
async def ingest_sensor_readings(batch: dict):
    svc: LoraIngestService = _services["lora"]
    readings = batch.get("readings", [])
    t0 = time.perf_counter()
    result = await svc.ingest_sensors(readings)
    dur = time.perf_counter() - t0

    if PROM_ENABLED:
        rtype = "sensor"
        LORA_INGEST.labels(type=rtype, result="ok").inc(result.get("ingested", 0))
        LORA_INGEST.labels(type=rtype, result="dup").inc(result.get("duplicates", 0))
        PREDICT_DURATION.labels(service="lora", action="ingest").observe(dur)

    logger.info("LoRa ingest: {n} readings, {d} duplicates in {t:.1f}ms",
                n=result.get("ingested", 0), d=result.get("duplicates", 0),
                t=dur * 1000)
    return result


@app.post("/api/sensors/aw-readings", tags=["sensors"])
async def ingest_aw_readings(batch: dict):
    svc: LoraIngestService = _services["lora"]
    readings = batch.get("readings", [])
    t0 = time.perf_counter()
    result = await svc.ingest_aw(readings)
    dur = time.perf_counter() - t0

    if PROM_ENABLED:
        LORA_INGEST.labels(type="aw", result="ok").inc(result.get("ingested", 0))
        LORA_INGEST.labels(type="aw", result="dup").inc(result.get("duplicates", 0))
        PREDICT_DURATION.labels(service="lora", action="ingest_aw").observe(dur)

    return result


@app.get("/api/sensors/trend/{tent_id}", tags=["sensors"])
def get_sensor_trend(tent_id: int, hours: int = Query(default=72, le=168)):
    from shared.clickhouse_client import get_client, query_rows
    from shared.config_loader import get_clickhouse_config

    ch_cfg = get_clickhouse_config()
    client = get_client(
        host=ch_cfg["host"], port=ch_cfg["port"],
        user=ch_cfg["user"], password=ch_cfg["password"],
        database=ch_cfg["database"],
    )
    since = datetime.utcnow() - timedelta(hours=hours)

    sql = f"""
        SELECT toStartOfInterval(timestamp, INTERVAL 30 MINUTE) as t, sensor_type, avg(value)
        FROM {ch_cfg['database']}.sensor_readings
        WHERE tent_id = %(tid)s AND timestamp >= %(since)s
        GROUP BY t, sensor_type
        ORDER BY t
    """
    rows = query_rows(client, sql, {"tid": tent_id, "since": since})

    trend = {"timestamps": [], "temperature": [], "humidity": [],
             "light": [], "ethylene": [], "co2": []}
    time_map = {}
    for ts, stype, val in rows:
        ts_str = ts.strftime("%Y-%m-%d %H:%M")
        time_map.setdefault(ts_str, {})[stype] = float(val)

    for ts_str in sorted(time_map.keys()):
        trend["timestamps"].append(ts_str)
        trend["temperature"].append(time_map[ts_str].get("temperature", 0))
        trend["humidity"].append(time_map[ts_str].get("humidity", 0))
        trend["light"].append(time_map[ts_str].get("light", 0))
        trend["ethylene"].append(time_map[ts_str].get("ethylene", 0))
        trend["co2"].append(time_map[ts_str].get("co2", 0))

    return trend


# ============================================================
#  Drugs / Predictions
# ============================================================
@app.get("/api/drugs/risks/{tent_id}", tags=["drugs"])
def get_drug_risks(tent_id: int):
    tent = get_tent(tent_id)
    if not tent:
        raise HTTPException(status_code=404, detail="Tent not found")

    climate = {"temperature": 25, "humidity": 50, "light": 300,
               "co2": 400, "ethylene": 0.5}
    aw_data = {drug: 0.5 for drug in tent["drugs"]}

    t0 = time.perf_counter()
    arr: ArrheniusService = _services["arrhenius"]
    arr_results = arr.predict_tent_drugs(tent_id, climate, aw_data)
    if PROM_ENABLED:
        PREDICT_DURATION.labels(service="arrhenius", action="predict").observe(
            time.perf_counter() - t0
        )

    t1 = time.perf_counter()
    mic: MicrobialService = _services["microbial"]
    mic_results = mic.assess_tent_drugs(tent_id, climate["temperature"], aw_data)
    if PROM_ENABLED:
        PREDICT_DURATION.labels(service="microbial", action="assess").observe(
            time.perf_counter() - t1
        )

    mic_dict = {r["drug_name"]: r for r in mic_results}
    combined = []
    for a in arr_results:
        drug = a["drug_name"]
        m = mic_dict.get(drug, {})
        combined.append({
            **a,
            "mold_risk": m.get("mold_risk", 0),
            "risk_level": m.get("risk_level", "低"),
        })
    return combined


@app.get("/api/drugs/priorities/{tent_id}", tags=["drugs"])
def get_drug_priorities(tent_id: int):
    risks = get_drug_risks(tent_id)
    priorities = []
    for r in risks:
        score = 0.0
        reasons = []

        temp_factor = max(0, (r["avg_temperature"] - 25) / 15)
        score += temp_factor * 30
        if temp_factor > 0.3:
            reasons.append(f"温度偏高({r['avg_temperature']}°C)")

        aw_factor = max(0, (r["avg_aw"] - 0.5) / 0.25)
        score += aw_factor * 30
        if aw_factor > 0.4:
            reasons.append(f"水分活度高(Aw={r['avg_aw']})")

        score += r["mold_risk"] * 25
        if r["mold_risk"] > 0.5:
            reasons.append(f"霉变风险高({r['mold_risk']:.0%})")

        if r["shelf_life_days"] < 365:
            shelf_factor = max(0, 1 - r["shelf_life_days"] / 365)
            score += shelf_factor * 15
            if shelf_factor > 0.5:
                reasons.append(f"有效期不足({r['shelf_life_days']:.0f}天)")

        score = min(100, max(0, score))
        if score >= 75:
            level = "紧急"
        elif score >= 50:
            level = "高"
        elif score >= 25:
            level = "中"
        else:
            level = "低"

        priorities.append({
            "tent_id": tent_id,
            "drug_name": r["drug_name"],
            "priority_score": round(score, 1),
            "priority_level": level,
            "reason": "；".join(reasons) if reasons else "当前状态良好",
        })

    return sorted(priorities, key=lambda x: -x["priority_score"])


@app.get("/api/drugs/heatmap/{tent_id}", tags=["drugs"])
def get_drug_heatmap(tent_id: int):
    tent = get_tent(tent_id)
    if not tent:
        raise HTTPException(status_code=404, detail="Tent not found")

    risks = get_drug_risks(tent_id)
    heatmap = []
    meter_id = 1
    for r in risks:
        for i in range(3):
            risk_score = r["mold_risk"] * 0.6 + 0.4 * max(0, (r["avg_aw"] - 0.5) / 0.3)
            risk_score = min(1.0, risk_score)
            heatmap.append({
                "meter_id": meter_id,
                "drug_name": r["drug_name"],
                "avg_aw": round(r["avg_aw"] + 0.02 * (i - 1), 4),
                "risk_score": round(min(1.0, risk_score + 0.05 * (i - 1)), 4),
                "mold_risk": round(max(0, min(1.0, r["mold_risk"] + 0.03 * (i - 1))), 4),
                "shelf_life_days": round(r["shelf_life_days"] * (1 - 0.05 * i), 1),
                "x": (meter_id - 1) % 5,
                "y": (meter_id - 1) // 5,
            })
            meter_id += 1
            if meter_id > 10:
                break
        if meter_id > 10:
            break

    while len(heatmap) < 10 and len(risks) > 0:
        r = risks[-1]
        risk_score = r["mold_risk"] * 0.5 + 0.3
        heatmap.append({
            "meter_id": meter_id,
            "drug_name": r["drug_name"] + " (对照)",
            "avg_aw": round(r["avg_aw"] + 0.03, 4),
            "risk_score": round(min(1.0, risk_score), 4),
            "mold_risk": round(min(1.0, r["mold_risk"] + 0.05), 4),
            "shelf_life_days": round(r["shelf_life_days"] * 0.9, 1),
            "x": (meter_id - 1) % 5,
            "y": (meter_id - 1) // 5,
        })
        meter_id += 1

    return heatmap


# ============================================================
#  Alerts
# ============================================================
@app.get("/api/alerts/", tags=["alerts"])
def list_alerts(tent_id: Optional[int] = None, hours: int = Query(default=24, le=168)):
    from shared.clickhouse_client import get_client, query_rows
    from shared.config_loader import get_clickhouse_config

    ch_cfg = get_clickhouse_config()
    client = get_client(
        host=ch_cfg["host"], port=ch_cfg["port"],
        user=ch_cfg["user"], password=ch_cfg["password"],
        database=ch_cfg["database"],
    )
    since = datetime.utcnow() - timedelta(hours=hours)

    base = """
        SELECT timestamp, tent_id, alert_type, severity, value, threshold,
               duration_hours, message, notified
        FROM {db}.alerts
    """.format(db=ch_cfg['database'])

    if tent_id:
        sql = base + " WHERE tent_id = %(tid)s AND timestamp >= %(since)s ORDER BY timestamp DESC"
        params = {"tid": tent_id, "since": since}
    else:
        sql = base + " WHERE timestamp >= %(since)s ORDER BY timestamp DESC LIMIT 100"
        params = {"since": since}

    rows = query_rows(client, sql, params)
    alerts = []
    for ts, tid, atype, sev, val, thr, dur, msg, notif in rows:
        alerts.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "tent_id": tid,
            "alert_type": atype,
            "severity": sev,
            "value": round(float(val), 3),
            "threshold": round(float(thr), 3),
            "duration_hours": round(float(dur), 2),
            "message": msg,
            "notified": notif,
        })
    return alerts


@app.post("/api/alerts/check", tags=["alerts"])
async def trigger_alerts_check():
    svc: AlertBrokerService = _services["alert"]
    results = await svc.run_alerts_check()

    if PROM_ENABLED:
        for a in results:
            ALERTS_TOTAL.labels(
                type=a.get("alert_type", "unknown"),
                severity=a.get("severity", "warning"),
            ).inc()

    logger.warning("Alert check produced {n} alerts", n=len(results))
    return {"status": "ok", "alerts_count": len(results), "alerts": results}


# ============================================================
#  LoRa stats
# ============================================================
@app.get("/api/lora/stats", tags=["lora"])
def get_lora_stats():
    svc: LoraIngestService = _services["lora"]
    return svc.stats
