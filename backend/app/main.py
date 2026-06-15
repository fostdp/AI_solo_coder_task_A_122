import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.background import BackgroundScheduler

from .routers import tents, sensors, drugs, alerts
from .services.alert import get_alert_service
from .config import ALERT_CHECK_INTERVAL_MINUTES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

scheduler = BackgroundScheduler()


def scheduled_alert_check():
    try:
        svc = get_alert_service()
        svc.check_alerts()
        logger.info("Scheduled alert check completed")
    except Exception as e:
        logger.error(f"Scheduled alert check failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        scheduled_alert_check,
        "interval",
        minutes=ALERT_CHECK_INTERVAL_MINUTES,
        id="alert_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started, alert check interval: %d minutes", ALERT_CHECK_INTERVAL_MINUTES)
    yield
    scheduler.shutdown()
    logger.info("Scheduler shutdown")


app = FastAPI(
    title="丝绸之路医疗帐篷微气候与药品变质预测系统",
    description="古代丝绸之路商队医疗帐篷微气候监测与药品变质风险预测",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(tents.router)
app.include_router(sensors.router)
app.include_router(drugs.router)
app.include_router(alerts.router)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "silkroad-medical-tent"}
