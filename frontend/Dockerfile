# =============================================================================
#  前端镜像: Nginx + Gzip + CDN 回源
# =============================================================================
FROM nginx:1.25-alpine AS runtime

ENV TZ=Asia/Shanghai

# 时区设置
RUN apk add --no-cache tzdata curl \
    && ln -sf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/cache/apk/*

# 复制站点文件
COPY index.html      /usr/share/nginx/html/index.html
COPY css/            /usr/share/nginx/html/css/
COPY js/             /usr/share/nginx/html/js/

# Nginx 配置 (Gzip + CDN + 缓存)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Health Check
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD curl -fsS http://localhost:80/ || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
