"""
LoRa Sensor Simulator v3 - 敦煌悬泉置汉代医疗帐篷

每座帐篷: 20 传感器 (温湿度/光照/气体) + 10 水分活度检测仪
每 30 分钟 LoRa 上行

[v3 工程化] 新增:
  - CLI 参数: --tents / --interval / --spoil / --target-tents / --start-hour / --duration-hours
  - 异常注入 (--spoil): 高温高湿 + Aw 抬升 + 乙烯/CO2 超标, 触发告警和药品变质
  - 结构化日志 (loguru) + 异常注入摘要
"""
import os
import sys
import time
import math
import json
import random
import argparse
from datetime import datetime, timedelta

import httpx

# ---------- 日志 & 配置 ----------
try:
    from loguru import logger
    _loguru_ok = True
    logger.remove()
    logger.add(
        sys.stdout,
        level=os.getenv("SIM_LOG_LEVEL", "INFO"),
        format="<green>{time:HH:mm:ss}</green> | "
               "<level>{level: <7}</level> | "
               "{message}",
        colorize=True,
    )
except ImportError:
    import logging
    logger = logging.getLogger("lora-sim")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(message)s")
    _loguru_ok = False

API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")
SIM_RUN_ID = f"run-{int(time.time())}"

# ---------- 帐篷/药材基础配置 ----------
TENT_CONFIGS = [
    {"id": 1, "name": "悬泉置·东帐", "drugs": ["当归", "大黄", "甘草"]},
    {"id": 2, "name": "悬泉置·西帐", "drugs": ["黄芪", "白术", "茯苓"]},
    {"id": 3, "name": "悬泉置·南帐", "drugs": ["川芎", "白芍", "熟地"]},
    {"id": 4, "name": "悬泉置·北帐", "drugs": ["桂枝", "麻黄", "细辛"]},
    {"id": 5, "name": "悬泉置·中帐", "drugs": ["人参", "丹参", "五味子"]},
]

SENSOR_TYPES = ["temperature", "humidity", "light", "ethylene", "co2"]
SENSORS_PER_TYPE = 4

BASE_RANGES = {
    "temperature": {"min": 10, "max": 35, "unit": "°C"},
    "humidity":    {"min": 20, "max": 85, "unit": "%RH"},
    "light":       {"min": 0,  "max": 800, "unit": "lux"},
    "ethylene":    {"min": 0,  "max": 3,   "unit": "ppm"},
    "co2":         {"min": 350, "max": 1200, "unit": "ppm"},
}

AW_RANGE = {"min": 0.35, "max": 0.75}

# ---------- LoRa 退避 (CSMA/CA + BEB) ----------
LORA_SF = [7, 8, 9, 10, 11, 12]
BACKOFF_INIT_MS = 200
BACKOFF_MAX_MS = 8000
RETRY_MAX = 3


class LoRaBackoffClient:
    def __init__(self, tent_id: int):
        self.tent_id = tent_id
        self.sf = LORA_SF[(tent_id - 1) % len(LORA_SF)]
        self.backoff_window = BACKOFF_INIT_MS

    def acquire_channel(self, congestion: float = 0.0) -> float:
        window = self.backoff_window * (1 + congestion * 3)
        backoff_ms = random.uniform(0, min(window, BACKOFF_MAX_MS))
        phase = (self.tent_id * 37.0) % 360.0
        jitter = (phase / 360.0) * (BACKOFF_INIT_MS / 2)
        return (backoff_ms + jitter) / 1000.0

    def report_result(self, success: bool):
        if success:
            self.backoff_window = max(BACKOFF_INIT_MS, self.backoff_window * 0.5)
        else:
            self.backoff_window = min(BACKOFF_MAX_MS, self.backoff_window * 2)


_lora_clients: dict = {}

# ============================================================
#  异常注入: --spoil
# ============================================================
class SpoilInjector:
    """
    异常注入器 - 模拟高温高湿导致药品变质

    spoil_level:
      0 = 正常 (无异常)
      1 = 轻度异常: 目标帐篷温度 32~36°C, 湿度 70~85%, Aw 0.58~0.65
      2 = 中度异常: 目标帐篷温度 36~40°C, 湿度 80~92%, Aw 0.65~0.78, 乙烯/CO2 高
      3 = 极端异常: 所有帐篷温度 40~48°C, 湿度 90~98%, Aw 0.75~0.92, 气体全面超标
    """

    def __init__(
        self,
        spoil_level: int = 0,
        target_tents: list = None,
        start_hour: int = 0,
        duration_hours: int = 8,
    ):
        self.spoil_level = spoil_level
        self.target_tents = target_tents or [1, 2]
        self.start_hour = start_hour
        self.duration_hours = duration_hours
        self._reported = set()

        if spoil_level >= 3:
            self.target_tents = [1, 2, 3, 4, 5]

    def is_active(self, sim_hour: int) -> bool:
        """模拟时间是否处于异常窗口内"""
        if self.spoil_level == 0:
            return False
        end = (self.start_hour + self.duration_hours) % 24
        if self.start_hour <= end:
            return self.start_hour <= sim_hour < end
        else:
            return sim_hour >= self.start_hour or sim_hour < end

    def tent_is_target(self, tent_id: int) -> bool:
        return tent_id in self.target_tents

    def spoil_scale(self) -> float:
        """异常强度系数 (0~1 之间平滑过渡)"""
        if self.spoil_level == 0:
            return 0.0
        return {1: 0.4, 2: 0.75, 3: 1.0}.get(self.spoil_level, 0)

    def sensor_offset(self, tent_id: int, sim_hour: int, sensor_type: str) -> float:
        """返回应叠加在正常值上的偏移量"""
        if self.spoil_level == 0 or not self.is_active(sim_hour) or not self.tent_is_target(tent_id):
            return 0.0

        s = self.spoil_scale()
        if sensor_type == "temperature":
            return (10 + self.spoil_level * 6) * s + random.uniform(-1.5, 1.5)
        elif sensor_type == "humidity":
            return (30 + self.spoil_level * 12) * s + random.uniform(-4, 4)
        elif sensor_type == "ethylene":
            return (2 + self.spoil_level * 3) * s + random.uniform(0, 1)
        elif sensor_type == "co2":
            return (600 + self.spoil_level * 500) * s + random.uniform(-80, 80)
        return 0.0

    def aw_boost(self, tent_id: int, sim_hour: int, base_aw: float) -> float:
        """水分活度抬升 (加速霉变)"""
        if self.spoil_level == 0 or not self.is_active(sim_hour) or not self.tent_is_target(tent_id):
            return base_aw

        s = self.spoil_scale()
        boost = 0.18 * s + self.spoil_level * 0.06 * s
        return min(0.95, base_aw + boost + random.uniform(-0.02, 0.03))

    def summary(self) -> dict:
        return {
            "level": self.spoil_level,
            "target_tents": self.target_tents,
            "start_hour": self.start_hour,
            "duration_hours": self.duration_hours,
            "expected_temp_jump_c": round((10 + self.spoil_level * 6) * self.spoil_scale(), 1),
            "expected_humidity_jump_pct": round((30 + self.spoil_level * 12) * self.spoil_scale(), 1),
            "expected_aw_boost": round(0.18 * self.spoil_scale() + self.spoil_level * 0.06 * self.spoil_scale(), 2),
        }


# ============================================================
#  数据生成
# ============================================================
def diurnal_variation(hour: float, sensor_type: str) -> float:
    """日变化曲线"""
    if sensor_type == "temperature":
        return 8 * math.sin((hour - 6) * math.pi / 12)
    elif sensor_type == "humidity":
        return -15 * math.sin((hour - 6) * math.pi / 12)
    elif sensor_type == "light":
        sunrise, sunset = 6, 20
        if sunrise <= hour <= sunset:
            return 600 * math.sin(math.pi * (hour - sunrise) / (sunset - sunrise))
        return 0
    elif sensor_type in ("ethylene", "co2"):
        return 0.8 * math.sin((hour - 12) * math.pi / 24)
    return 0


def generate_sensor_value(tent_id: int, sensor_type: str, sim_hour: float, injector: SpoilInjector) -> float:
    r = BASE_RANGES[sensor_type]
    base = (r["min"] + r["max"]) / 2 + diurnal_variation(sim_hour, sensor_type)
    noise = (r["max"] - r["min"]) * 0.05 * random.uniform(-1, 1)
    val = base + noise + injector.sensor_offset(tent_id, sim_hour, sensor_type)
    return round(max(r["min"] * 0.8, min(r["max"] * 1.3, val)), 3)


def generate_aw_value(tent_id: int, drug: str, sim_hour: float, injector: SpoilInjector) -> float:
    diurnal = 0.04 * math.sin((sim_hour - 14) * math.pi / 12)
    drug_hash = hash(drug) % 100 / 100
    base = AW_RANGE["min"] + drug_hash * (AW_RANGE["max"] - AW_RANGE["min"]) * 0.5 + diurnal
    aw = injector.aw_boost(tent_id, sim_hour, base)
    return round(aw, 4)


def generate_batch(tent_cfg: dict, sim_hour: float, injector: SpoilInjector) -> tuple:
    """生成一座帐篷的一批读数 (传感器 + Aw)"""
    tent_id = tent_cfg["id"]
    ts = datetime.utcnow()

    sensor_readings = []
    for stype in SENSOR_TYPES:
        for s_idx in range(1, SENSORS_PER_TYPE + 1):
            sensor_readings.append({
                "timestamp": ts.isoformat(),
                "tent_id": tent_id,
                "sensor_id": SENSOR_TYPES.index(stype) * SENSORS_PER_TYPE + s_idx,
                "sensor_type": stype,
                "value": generate_sensor_value(tent_id, stype, sim_hour, injector),
            })

    aw_readings = []
    for drug in tent_cfg["drugs"]:
        for m_idx in range(1, 5):
            aw_readings.append({
                "timestamp": ts.isoformat(),
                "tent_id": tent_id,
                "meter_id": (tent_id - 1) * 10 + m_idx,
                "drug_name": drug,
                "water_activity": generate_aw_value(tent_id, drug, sim_hour, injector),
            })

    return sensor_readings, aw_readings


# ============================================================
#  上报 (LoRa 退避 + 重试)
# ============================================================
def send_batch(tent_id: int, sensor_readings: list, aw_readings: list) -> bool:
    client = _lora_clients.setdefault(tent_id, LoRaBackoffClient(tent_id))
    for attempt in range(RETRY_MAX):
        delay = client.acquire_channel(congestion=attempt * 0.2)
        time.sleep(delay)
        try:
            with httpx.Client(timeout=15) as h:
                ok1, ok2 = True, True
                if sensor_readings:
                    r = h.post(
                        f"{API_BASE}/api/sensors/readings",
                        json={"readings": sensor_readings},
                    )
                    ok1 = r.status_code == 200
                if aw_readings:
                    r = h.post(
                        f"{API_BASE}/api/sensors/aw-readings",
                        json={"readings": aw_readings},
                    )
                    ok2 = r.status_code == 200
                success = ok1 and ok2
                client.report_result(success)
                return success
        except Exception as e:
            client.report_result(False)
            if attempt == RETRY_MAX - 1:
                logger.error("Tent {t}: LoRa send failed after {n} retries: {e}",
                             t=tent_id, n=RETRY_MAX, e=e)
    return False


# ============================================================
#  主循环
# ============================================================
def run(tent_count: int, interval_min: int, injector: SpoilInjector, once: bool = False):
    sim_tents = TENT_CONFIGS[:tent_count]
    sim_start = datetime.utcnow()
    tick = 0

    if injector.spoil_level > 0:
        summary = injector.summary()
        logger.warning("=" * 60)
        logger.warning("异常注入已启用 spoil={l}", l=injector.spoil_level)
        logger.warning("  目标帐篷: {t}", t=summary["target_tents"])
        logger.warning("  窗口: {s}:00-{e}:00 (持续 {d}h)",
                       s=injector.start_hour,
                       e=(injector.start_hour + injector.duration_hours) % 24,
                       d=injector.duration_hours)
        logger.warning("  温度抬升约 {v}°C", v=summary["expected_temp_jump_c"])
        logger.warning("  湿度抬升约 {v}%", v=summary["expected_humidity_jump_pct"])
        logger.warning("  水分活度抬升约 Aw+{v}", v=summary["expected_aw_boost"])
        logger.warning("  预期效果: 高温>4h 告警 + Aw>0.6 告警 + 霉变风险上升")
        logger.warning("=" * 60)

    while True:
        ts = datetime.utcnow()
        sim_hour = (ts.hour + ts.minute / 60.0) % 24

        # 每个帐篷独立分包上报 (避免消息碰撞)
        total_sensors = 0
        total_aw = 0
        ok_count = 0
        hot_tents = []

        for tent_cfg in sim_tents:
            sensor_readings, aw_readings = generate_batch(tent_cfg, sim_hour, injector)
            total_sensors += len(sensor_readings)
            total_aw += len(aw_readings)
            ok = send_batch(tent_cfg["id"], sensor_readings, aw_readings)
            if ok:
                ok_count += 1

            # 简易异常检测 (用于日志提示)
            if injector.is_active(sim_hour) and injector.tent_is_target(tent_cfg["id"]):
                max_t = max((r["value"] for r in sensor_readings if r["sensor_type"] == "temperature"), default=0)
                max_aw = max((r["water_activity"] for r in aw_readings), default=0)
                if max_t > 30 or max_aw > 0.58:
                    hot_tents.append((tent_cfg["name"], round(max_t, 1), round(max_aw, 3)))

        tick += 1
        elapsed = (datetime.utcnow() - sim_start).total_seconds()

        log_msg = (
            f"Tick #{tick} | T={sim_hour:5.2f}h | "
            f"OK {ok_count}/{tent_count} | "
            f"Readings: sensor={total_sensors} aw={total_aw} | "
            f"Elapsed {elapsed:6.1f}s"
        )
        if hot_tents and injector.spoil_level > 0:
            log_msg += " | 异常: " + ", ".join(
                f"{name}(T={t}°C, Aw={aw})" for name, t, aw in hot_tents
            )
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        if once:
            break

        time.sleep(max(0.5, interval_min * 60 / 60))  # debug: 加速模式下实际按 1s 上报
        # 实际模拟: time.sleep(interval_min * 60)


# ============================================================
#  CLI
# ============================================================
def parse_args():
    p = argparse.ArgumentParser(
        description="LoRa Sensor Simulator v3 - 敦煌悬泉置医疗帐篷",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 正常模拟, 5 帐篷, 30 分钟间隔
  python lora_simulator.py

  # 异常注入 Level 1: 帐篷 1 高温高湿 (最常用的演示模式)
  python lora_simulator.py --spoil=1

  # 异常注入 Level 2: 帐篷 1,2,3 中度异常, 异常窗口 12:00~20:00
  python lora_simulator.py --spoil=2 --target-tents 1,2,3 --start-hour 12 --duration-hours 8

  # 极端异常: 所有帐篷拉满
  python lora_simulator.py --spoil=3 --tents 5

  # 仅跑一轮然后退出 (CI 用)
  python lora_simulator.py --once
""",
    )
    p.add_argument("--tents", type=int, default=5,
                   help="帐篷数量 (1-5, 默认 5)")
    p.add_argument("--interval", type=int, default=30,
                   help="上报间隔 (分钟, 默认 30)")
    p.add_argument("--api", default=API_BASE,
                   help="后端 API 地址 (或设 env API_BASE)")
    p.add_argument("--seed", type=int, default=42,
                   help="随机种子, 用于可复现")

    # ---- 异常注入 ----
    p.add_argument("--spoil", type=int, default=0,
                   choices=[0, 1, 2, 3],
                   help="异常注入等级: 0=正常 1=轻度 2=中度 3=极端")
    p.add_argument("--target-tents", default="1,2",
                   help="目标帐篷列表 (逗号分隔, 默认 1,2)")
    p.add_argument("--start-hour", type=int, default=0,
                   help="异常窗口起始小时 (0-23, 默认 0)")
    p.add_argument("--duration-hours", type=int, default=8,
                   help="异常持续小时数 (1-24, 默认 8)")

    p.add_argument("--once", action="store_true",
                   help="只跑一轮就退出 (调试/CI 用)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    random.seed(args.seed)
    API_BASE = args.api.rstrip("/")

    tents = min(max(1, args.tents), len(TENT_CONFIGS))
    interval = max(1, args.interval)

    target = [int(x.strip()) for x in args.target_tents.split(",") if x.strip().isdigit()]
    injector = SpoilInjector(
        spoil_level=args.spoil,
        target_tents=target,
        start_hour=args.start_hour,
        duration_hours=args.duration_hours,
    )

    logger.info(
        "LoRa Simulator v3: tents={t}, interval={i}min, "
        "api={a}, run_id={rid}",
        t=tents, i=interval, a=API_BASE, rid=SIM_RUN_ID,
    )

    # 等待后端就绪
    for i in range(20):
        try:
            httpx.get(f"{API_BASE}/healthz", timeout=3)
            logger.success("Backend API is healthy")
            break
        except Exception as e:
            if i < 19:
                logger.info("Waiting for backend... ({i}/20)", i=i + 1)
                time.sleep(3)
            else:
                logger.warning("Backend not reachable, continuing anyway...")

    try:
        run(tents, interval, injector, once=args.once)
    except KeyboardInterrupt:
        logger.info("Simulator stopped by user")
    except Exception as e:
        logger.exception("Fatal error: {e}", e=e)
        sys.exit(1)
