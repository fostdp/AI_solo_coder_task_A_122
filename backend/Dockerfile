# =============================================================================
#  Stage 1: Builder - 安装依赖, 编译 C 扩展 (numpy/scipy/scikit-learn)
# =============================================================================
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100

WORKDIR /build

# 安装编译依赖 (numpy/scipy/scikit-learn 需要 gcc, gfortran, openblas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    gfortran \
    libopenblas-dev \
    liblapack-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 复制 requirements 并安装到 /install 目录
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install --no-warn-script-location -r requirements.txt

# =============================================================================
#  Stage 2: Runtime - 精简运行镜像
# =============================================================================
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app \
    TZ=Asia/Shanghai \
    PROMETHEUS_PORT=9090

WORKDIR $APP_HOME

# 安装运行时最小依赖 (openblas 供 scipy 使用)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0 \
    libgfortran5 \
    libquadmath0 \
    tzdata \
    curl \
    && ln -sf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r silkroad && useradd -r -g silkroad silkroad

# 从 builder 复制 site-packages
COPY --from=builder /install /usr/local

# 复制应用代码
COPY . .

# 创建日志目录并授权
RUN mkdir -p /app/logs /app/data && chown -R silkroad:silkroad /app

USER silkroad

# Health Check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

EXPOSE 8000 9090

CMD ["uvicorn", "services.api_gateway.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "info"]
