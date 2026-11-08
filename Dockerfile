# 财务风险智能预警平台 · 生产镜像
# 构建：docker build -t risk-warning-platform:1.0 .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 仅安装运行时必需的系统库（xgboost/lightgbm 依赖 libgomp）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 首次启动若缺少数据/模型，自动完成"生成演示数据 → 训练 → 评估 → SHAP"全流程
RUN chmod +x docker/entrypoint.sh

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
