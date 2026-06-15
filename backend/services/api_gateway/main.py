"""
API Gateway - 主服务入口
整合所有微服务, 提供 REST API 和前端静态文件

服务间通信:
  - 同步调用: 直接 import 各服务的 service 类 (单进程模式)
  - 异步消息: 通过 Redis Stream (多进程/多节点模式)

架构:
  lora_ingest   ->  sensor_raw stream  -> arrhenius_predictor
                    \                    -> microbial_model
                     \                    \
                      -> drug_risk stream  -> alert_broker
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from shared.config_loader import get_tents, get_tent
from shared.redis_streams import RedisStreamClient

from services.lora_ingest.service import LoraIngestService
from services.arrhenius_predictor.service import ArrheniusService
from services.microbial_model.service import MicrobialService
from services.alert_broker.service import AlertBrokerService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


# 单例服务实例
_services: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时: 初始化所有服务
    redis_client = RedisStreamClient()
    try:
        await redis_client.connect()
    except Exception as e:
        logger.warning("Redis not available, running in library-only mode: %s", e)
        redis_client = None

    # 初始化各服务 (库模式, 不消费 stream)
    lora_svc = LoraIngestService(redis_client=redis_client)
    await lora_svc.start()
    _services["lora"] = lora_svc

    arrhenius_svc = ArrheniusService(redis_client=redis_client)
    await arrhenius_svc.start(consume_stream=False)
    _services["arrhenius"] = arrhenius_svc

    microbial_svc = MicrobialService(redis_client=redis_client)
    await microbial_svc.start(consume_stream=False)
    _services["microbial"] = microbial_svc

    alert_svc = AlertBrokerService(redis_client=redis_client)
    await alert_svc.start(with_scheduler=False)
    _services["alert"] = alert_svc

    logger.info("API Gateway started with all services")
    yield

    # 关闭时: 停止所有服务
    for name, svc in reversed(list(_services.items())):
        try:
            await svc.stop()
            logger.info("Service stopped: %s", name)
        except Exception as e:
            logger.error("Error stopping service %s: %s", name, e)
    _services.clear()


app = FastAPI(
    title="丝绸之路医疗帐篷微气候与药品变质预测系统",
    description="敦煌悬泉置汉代医疗帐篷 - 微气候监测与药品变质风险预测 API",
    version="2.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": "2.0.0"}


# --- Tents ---
@app.get("/api/tents/")
def list_tents():
    return get_tents()


@app.get("/api/tents/{tent_id}")
def get_tent_info(tent_id: int):
    tent = get_tent(tent_id)
    if not tent:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tent not found")
    return tent


# --- Sensors / LoRa Ingest ---
@app.post("/api/sensors/readings")
async def ingest_sensor_readings(batch: dict):
    """批量接收传感器数据 (LoRa 上行)"""
    svc: LoraIngestService = _services["lora"]
    readings = batch.get("readings", [])
    result = await svc.ingest_sensors(readings)
    return result


@app.post("/api/sensors/aw-readings")
async def ingest_aw_readings(batch: dict):
    """批量接收水分活度数据"""
    svc: LoraIngestService = _services["lora"]
    readings = batch.get("readings", [])
    result = await svc.ingest_aw(readings)
    return result


@app.get("/api/sensors/trend/{tent_id}")
def get_sensor_trend(tent_id: int, hours: int = Query(default=72, le=168)):
    """获取微气候趋势数据"""
    from shared.clickhouse_client import get_client
    from shared.config_loader import get_clickhouse_config
    from datetime import datetime, timedelta

    ch_cfg = get_clickhouse_config()
    client = get_client(
        host=ch_cfg["host"], port=ch_cfg["port"],
        user=ch_cfg["user"], password=ch_cfg["password"],
        database=ch_cfg["database"],
    )
    since = datetime.utcnow() - timedelta(hours=hours)

    rows = client.execute(
        f"""
        SELECT toStartOfInterval(timestamp, INTERVAL 30 MINUTE) as t, sensor_type, avg(value)
        FROM {ch_cfg['database']}.sensor_readings
        WHERE tent_id = %(tid)s AND timestamp >= %(since)s
        GROUP BY t, sensor_type
        ORDER BY t
        """,
        {"tid": tent_id, "since": since},
    )

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


# --- Drugs / Predictions ---
@app.get("/api/drugs/risks/{tent_id}")
def get_drug_risks(tent_id: int):
    """获取某帐篷所有药材的风险评估 (有效期 + 霉变)"""
    tent = get_tent(tent_id)
    if not tent:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tent not found")

    # 简化: 模拟 climate 和 aw 数据
    # 实际生产环境应从 ClickHouse 查询 24h 均值
    climate = {"temperature": 25, "humidity": 50, "light": 300,
               "co2": 400, "ethylene": 0.5}
    aw_data = {drug: 0.5 for drug in tent["drugs"]}

    arr: ArrheniusService = _services["arrhenius"]
    arr_results = arr.predict_tent_drugs(tent_id, climate, aw_data)

    mic: MicrobialService = _services["microbial"]
    mic_results = mic.assess_tent_drugs(tent_id, climate["temperature"], aw_data)

    # 合并结果
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


@app.get("/api/drugs/priorities/{tent_id}")
def get_drug_priorities(tent_id: int):
    """获取药品调配优先级建议"""
    risks = get_drug_risks(tent_id)

    # 简化版优先级评分 (实际应使用随机森林模型)
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


@app.get("/api/drugs/heatmap/{tent_id}")
def get_drug_heatmap(tent_id: int):
    """获取药品变质风险热力图数据"""
    tent = get_tent(tent_id)
    if not tent:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tent not found")

    # 简化: 10 个检测位的模拟数据
    # 实际生产环境应从 Aw readings 聚合
    from datetime import datetime
    risks = get_drug_risks(tent_id)
    heatmap = []
    meter_id = 1

    for r in risks:
        for i in range(3):  # 每种药材 3 个检测位
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

    # 补足到 10 个
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


# --- Alerts ---
@app.get("/api/alerts/")
def list_alerts(tent_id: int = None, hours: int = Query(default=24, le=168)):
    """获取告警列表"""
    from shared.clickhouse_client import get_client
    from shared.config_loader import get_clickhouse_config
    from datetime import datetime, timedelta

    ch_cfg = get_clickhouse_config()
    client = get_client(
        host=ch_cfg["host"], port=ch_cfg["port"],
        user=ch_cfg["user"], password=ch_cfg["password"],
        database=ch_cfg["database"],
    )
    since = datetime.utcnow() - timedelta(hours=hours)

    if tent_id:
        sql = f"""
            SELECT timestamp, tent_id, alert_type, severity, value, threshold,
                   duration_hours, message, notified
            FROM {ch_cfg['database']}.alerts
            WHERE tent_id = %(tid)s AND timestamp >= %(since)s
            ORDER BY timestamp DESC
        """
        params = {"tid": tent_id, "since": since}
    else:
        sql = f"""
            SELECT timestamp, tent_id, alert_type, severity, value, threshold,
                   duration_hours, message, notified
            FROM {ch_cfg['database']}.alerts
            WHERE timestamp >= %(since)s
            ORDER BY timestamp DESC LIMIT 100
        """
        params = {"since": since}

    rows = client.execute(sql, params)
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


@app.post("/api/alerts/check")
async def trigger_alerts_check():
    """手动触发告警检查"""
    svc: AlertBrokerService = _services["alert"]
    results = await svc.run_alerts_check()
    return {"status": "ok", "alerts_count": len(results), "alerts": results}


# --- Lora stats ---
@app.get("/api/lora/stats")
def get_lora_stats():
    """LoRa 采集服务状态"""
    svc: LoraIngestService = _services["lora"]
    return svc.stats
