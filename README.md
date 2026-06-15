# 古代丝绸之路商队医疗帐篷微气候与药品变质预测系统 v2.1

> 敦煌悬泉置遗址汉代医疗帐篷数字化保护项目 — 微气候监测 + Arrhenius 药品有效期预测 + Baranyi-Roberts 微生物霉变风险评估 + 随机森林调配优先级

---

## 1. 架构总览

```mermaid
flowchart TB
    subgraph 边缘层["🏕️ 5 座医疗帐篷 (LoRa 传感器)"]
        L1[帐篷 1 东帐<br/>当归/大黄/甘草]
        L2[帐篷 2 西帐<br/>黄芪/白术/茯苓]
        L3[帐篷 3 南帐<br/>川芎/白芍/熟地]
        L4[帐篷 4 北帐<br/>桂枝/麻黄/细辛]
        L5[帐篷 5 中帐<br/>人参/丹参/五味子]
    end

    subgraph 采集层["📡 LoRa 采集服务 lora_ingest"]
        CSMA["CSMA/CA 退避<br/>(BEB 二元指数)"]
        DEDUP["滑动窗口去重<br/>(按 tent_id:sensor:ts 对齐)"]
        BATCH["批量刷盘<br/>(ClickHouse MergeTree)"]
    end

    subgraph 消息总线["📡 Redis Stream (异步解耦)"]
        S1[sensor_raw<br/>stream]
        S2[drug_risk<br/>stream]
        S3[alerts<br/>stream]
    end

    subgraph 算法层["🧪 模型服务"]
        A["arrhenius_predictor<br/>Arrhenius + 光降解 + Aw 修正"]
        B["microbial_model<br/>Baranyi-Roberts 微生物生长"]
        C["[TODO] priority_rf<br/>随机森林 8 维特征融合"]
    end

    subgraph 告警层["🚨 alert_broker"]
        DETECT["持续超标检测<br/>(高温 >30°C×4h<br/>Aw >0.6×4h)"]
        NOTIFY["邮件 + 卫星通信<br/>(冷却 2h 避免轰炸)"]
    end

    subgraph 存储层["💾 ClickHouse (TTL 2 年)"]
        T1[sensor_readings<br/>复合分区 (月, tent_id)]
        T2[aw_readings<br/>水分活度时序]
        T3[drug_risk_assessments<br/>风险评估结果]
        T4[alerts<br/>告警记录]
    end

    subgraph 展示层["🌐 前端 + API"]
        FE["Nginx 前端<br/>Gzip + CDN 友好缓存"]
        GW["API Gateway (FastAPI)<br/>/api/*, /healthz, /metrics"]
        TENT["TentMap.js<br/>Leaflet 帐篷地图"]
        HM["DrugRiskHeatmap.js<br/>ImageData 复用热力图"]
    end

    subgraph 可观测性["📊 Logging + Metrics"]
        LOG["loguru 结构化日志<br/>JSON Lines + 100MB 滚动"]
        MET["Prometheus 指标<br/>HTTP / LoRa / 模型预测耗时"]
        HC["/healthz 健康检查<br/>Docker healthcheck"]
    end

    %% ============ 数据流 ============
    L1 & L2 & L3 & L4 & L5 -- LoRa --> CSMA
    CSMA --> DEDUP --> BATCH --> S1
    S1 -- xread_group --> A & B
    A & B --> S2
    S2 -- xread_group --> DETECT
    DETECT --> S3 --> NOTIFY

    BATCH --> T1 & T2
    A & B --> T3
    DETECT --> T4

    FE --> GW
    GW --> T1 & T2 & T3 & T4
    GW --> TENT & HM

    GW --> LOG & MET
    HC --> GW
```

### 模块职责

| 模块 | 文件路径 | 职责 | 通信方式 |
|---|---|---|---|
| **lora_ingest** | `backend/services/lora_ingest/` | CSMA/CA 退避、滑动窗口去重、批量刷盘、发布 raw stream | Redis Stream: `sensor_raw` |
| **arrhenius_predictor** | `backend/services/arrhenius_predictor/` | Arrhenius 方程 + 光降解修正 + Aw 修正 → 有效期预测 | 消费 `sensor_raw`, 发布 `drug_risk` |
| **microbial_model** | `backend/services/microbial_model/` | Baranyi-Roberts 微生物生长曲线 → 霉变风险 | 消费 `sensor_raw`, 发布 `drug_risk` |
| **alert_broker** | `backend/services/alert_broker/` | 持续超标检测 (4h 窗口) + 邮件/卫星通知 | 消费 `drug_risk`, 发布 `alerts` |
| **API Gateway** | `backend/services/api_gateway/` | REST API, loguru, Prometheus, healthz | 同步调用各服务 |
| **TentMap** | `frontend/js/TentMap.js` | Leaflet 帐篷地图组件 (事件驱动) | REST `GET /api/tents/*` |
| **DrugRiskHeatmap** | `frontend/js/DrugRiskHeatmap.js` | ImageData 单例复用的风险热力图 | REST `GET /api/drugs/heatmap/{id}` |

---

## 2. 部署步骤

### 2.1 一键启动 (docker-compose)

```bash
# 1) 克隆 & 进入
cd AI_solo_coder_task_A_122

# 2) 可选: 配置环境变量
cp .env.example .env    # (如有)
# 默认无需修改即可跑

# 3) 构建 & 启动核心服务 (ClickHouse + Redis + 后端 + 前端)
docker compose up -d --build

# 4) 等待 healthcheck 就绪 (~30s)
docker compose ps

# 5) 启动 LoRa 模拟器 (默认正常模式)
docker compose --profile with-sim up -d simulator

# 6) 验证:
#   前端 UI:         http://localhost:8080/
#   后端 API 文档:   http://localhost:8000/docs
#   健康检查:        http://localhost:8000/healthz
#   Prometheus:      http://localhost:9091/   (需 --profile monitoring)
```

### 2.2 本地开发 (不使用 Docker)

```bash
# ===== 后端 =====
cd backend
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt

# 1. 启动依赖 (需要本地 ClickHouse + Redis 或 docker 仅启动依赖)
docker compose up -d clickhouse redis

# 2. 初始化表
python init_db.py

# 3. 启动 API Gateway (监听 8000)
uvicorn services.api_gateway.main:app --reload --port 8000

# 4. 跑测试
pytest tests/ -v                    # 80 passed
pytest tests/ --cov=services --cov-report=term

# ===== 前端 =====
cd ../frontend
# 任选:
python -m http.server 8080          # 简单静态服务器
# 或使用 nginx (推荐, 支持 API 反代和 Gzip):
nginx -c $(pwd)/nginx.conf

# ===== 模拟器 =====
cd ../simulator
pip install httpx loguru
python lora_simulator.py --tents 5 --interval 30          # 正常
python lora_simulator.py --spoil 1 --once                 # 轻度异常 1 轮退出
```

### 2.3 仅启动模拟器 (注入异常演示)

```bash
# 异常 Level 1 (轻度): 帐篷 1,2 高温高湿 (最常用演示模式)
docker compose run --rm simulator \
    python simulator/lora_simulator.py \
    --tents 5 --interval 30 \
    --spoil 1 --target-tents 1,2

# 异常 Level 3 (极端): 5 顶帐篷全部拉满, 跑 1 轮后退出
docker compose run --rm simulator \
    python simulator/lora_simulator.py \
    --tents 5 --spoil 3 --once
```

---

## 3. 模拟器药品变质注入 `--spoil`

### 3.1 异常等级说明

| `--spoil` | 名称 | 效果 | 预期告警触发 |
|---|---|---|---|
| **0** | 正常 | 数据符合自然日变化, 无异常 | 无 |
| **1** | 轻度 | 目标帐篷: **温度 +6~12°C**, **湿度 +12~24%**, **Aw +0.10**, 气体轻度超标 | 运行 >8 个周期后: **高温 warning** + **Aw warning** |
| **2** | 中度 | 目标帐篷: **温度 +12~20°C**, **湿度 +24~36%**, **Aw +0.20**, 乙烯/CO₂ 明显超标 | >6 周期后: **高温 critical** + **Aw critical** + **霉变高风险** |
| **3** | 极端 | 5 顶帐篷全部: **温度 +20~28°C**, **湿度 +36~48%**, **Aw +0.30**, 气体全面爆表 | 1 轮即可触发: 所有告警全线 critical |

### 3.2 相关 CLI 参数

```bash
python lora_simulator.py \
    --spoil 1                  # 异常等级 0/1/2/3
    --target-tents 1,2         # 目标帐篷 (逗号分隔)
    --start-hour 12            # 异常窗口起始小时 (0-23)
    --duration-hours 8         # 异常持续小时数 (模拟日循环内)
    --tents 5                  # 帐篷总数
    --interval 30              # 上报间隔 (分钟)
    --once                     # 只跑 1 轮 (CI/验证用)
    --seed 42                  # 随机种子 (复现用)
```

### 3.3 docker-compose 环境变量方式

在 `docker-compose.yml` 目录下:

```bash
# 通过 env 变量, 无需改 command
SPOIL=1 SPOIL_TARGET_TENTS=1,2 docker compose --profile with-sim up -d simulator

# 极端模式
SPOIL=3 docker compose --profile with-sim up -d simulator
```

### 3.4 效果验证

启动异常注入后, 在前端或 API 中验证:

```bash
# 查看告警列表
curl "http://localhost:8000/api/alerts/"  | jq '.[] | {severity, alert_type, tent_id, duration_hours, value}'

# 手动触发告警检查
curl -X POST http://localhost:8000/api/alerts/check | jq

# 查看帐篷 1 的药材风险 (有效期缩短 + 霉变上升)
curl http://localhost:8000/api/drugs/risks/1 | jq '[.[] | {drug_name, shelf_life_days, mold_risk, risk_level}]'
```

---

## 4. 工程化特性

### 4.1 Docker 多阶段构建

**后端** `backend/Dockerfile`:
```
Stage 1: python:3.11-slim-bookworm (builder)
  ├─ 安装 gcc/g++/gfortran/libopenblas-dev
  ├─ 编译 numpy/scipy/scikit-learn wheel
  └─ 安装到 /install

Stage 2: python:3.11-slim-bookworm (runtime)
  ├─ 仅 libopenblas0 + libgfortran5 (运行时)
  ├─ 非 root 用户 (silkroad)
  └─ HEALTHCHECK /healthz
```
镜像体积从 ~2GB 降至 ~500MB。

**前端** `frontend/Dockerfile`:
- `nginx:1.25-alpine` + Gzip + 静态资源 1 年强缓存 + HTML 协商缓存

### 4.2 ClickHouse TTL 策略

表级 TTL (在 `init_db.py` 中定义):

| 表 | TTL | 说明 |
|---|---|---|
| `sensor_readings` | **730 天 (2 年)** | 微气候原始数据 |
| `aw_readings` | **730 天 (2 年)** | 水分活度原始数据 |
| `drug_risk_assessments` | **365 天 (1 年)** | 中间评估结果 (可重算) |
| `alerts` | **180 天 (半年)** | 告警事件记录 |

复合分区键 `PARTITION BY (toYYYYMM(timestamp), tent_id)` → 带 tent_id 查询 ~20× 性能。

### 4.3 Nginx Gzip + CDN

```nginx
gzip_comp_level 6;
gzip_types text/plain text/css application/javascript image/svg+xml font/woff2 ...;

# 带 hash 的资源: 1 年强缓存 (CDN 友好)
location ~* \.(?:css|js|woff2?|ttf|png|jpg)$ {
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
# HTML: 协商缓存
location ~* \.html$ { expires -1; add_header Cache-Control "no-cache"; }
# /api/* 反代到 backend:8000
```

### 4.4 可观测性

**loguru 日志** (`services/api_gateway/main.py`):
- 控制台彩色输出
- `LOG_FILE=/app/logs/app.log` → JSON Lines, 100MB 滚动, 14 天保留 + gz 压缩
- 标准 `logging` 自动转发到 loguru

**Prometheus 指标** (`/metrics`):

| Metric | 类型 | Labels | 说明 |
|---|---|---|---|
| `silkroad_http_requests_total` | Counter | method, path, status_code | HTTP 请求量 |
| `silkroad_http_request_duration_seconds` | Histogram | method, path | HTTP 延迟 (10 buckets) |
| `silkroad_lora_ingest_total` | Counter | type, result | LoRa 采集成功/去重计数 |
| `silkroad_model_predict_duration_seconds` | Histogram | service, action | 模型推理耗时 |
| `silkroad_alerts_total` | Counter | type, severity | 告警数量分级 |
| `silkroad_service_status` | Gauge | service | 内部服务 Up/Down |

**健康检查**:
- Docker: `HEALTHCHECK --interval=30s curl /healthz`
- `/healthz` 返回 `{status, version, services, unhealthy, timestamp}`

---

## 5. 项目结构

```
AI_solo_coder_task_A_122/
├── backend/
│   ├── Dockerfile                  # 多阶段构建 (builder + runtime)
│   ├── Dockerfile.simulator        # LoRa 模拟器镜像
│   ├── requirements.txt            # 含 loguru + prometheus-client + pyyaml + redis
│   ├── init_db.py                  # DDL (复合分区 + TTL 2 年)
│   ├── config/
│   │   └── config.yaml             # 所有模型参数外置 (15 种药材)
│   ├── db/
│   │   ├── clickhouse_config.xml   # ClickHouse 服务器配置
│   │   └── partition.sql           # v1.1 分区方案文档
│   ├── shared/                     # 共享基础设施
│   │   ├── config_loader.py
│   │   ├── redis_streams.py
│   │   └── clickhouse_client.py    # lazy import (测试友好)
│   ├── services/                   # 4 个微服务 + API Gateway
│   │   ├── lora_ingest/            # backoff + deduplicator + service
│   │   ├── arrhenius_predictor/
│   │   ├── microbial_model/
│   │   ├── alert_broker/           # detector (纯逻辑) + service
│   │   └── api_gateway/main.py     # loguru + Prometheus + /healthz
│   └── tests/                      # 80 pytest 测试
├── frontend/
│   ├── Dockerfile                  # nginx:alpine
│   ├── nginx.conf                  # Gzip + CDN + API 反代
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── TentMap.js              # Leaflet 地图组件 (独立)
│       ├── DrugRiskHeatmap.js      # ImageData 复用热力图 (独立)
│       ├── app.js / map.js / charts.js
│       └── heatmap_canvas.js       # v2 低内存渲染
├── simulator/
│   └── lora_simulator.py           # v3: --spoil 异常注入
├── deploy/
│   └── prometheus.yml              # Prometheus 抓取配置
├── docker-compose.yml              # 6 服务编排
└── README.md                       # 本文件
```

---

## 6. 版本历史

| 版本 | 关键变更 |
|---|---|
| **v1.0** | 首版全栈: FastAPI + ClickHouse + Leaflet + 3 核心算法 |
| **v1.1** | 光照修正因子 / 复合分区键 / LoRa 退避队列 / 热力图内存优化 |
| **v2.0** | 微服务拆分 + Redis Stream + pytest 80 passed |
| **v2.1** (当前) | Docker 多阶段构建 + docker-compose + loguru + Prometheus + ClickHouse TTL + Nginx Gzip + 模拟器 --spoil 异常注入 |
