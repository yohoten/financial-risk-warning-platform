#!/usr/bin/env bash
# 容器入口：数据/模型缺失时自动补齐，随后执行传入命令（默认 Streamlit）。
# api 服务传 uvicorn、worker 传 python -m api.worker、演示传 streamlit run ...
set -euo pipefail

MODEL_PATH="models/artifacts/xgboost_final.json"
PANEL_PATH="data/feature_store/panel_model_input.parquet"

if [ ! -f "$PANEL_PATH" ] && [ ! -f "data/feature_store/panel_model_input.csv" ]; then
  echo "[entrypoint] 未检测到特征数据，运行数据流水线..."
  python -m etl.run_pipeline
fi

if [ ! -f "$MODEL_PATH" ]; then
  echo "[entrypoint] 未检测到模型，开始训练（快速模式，跳过 Optuna 长搜索）..."
  python -m models.train --trials 10 --no-cv
  python -m models.evaluate
  python -m models.shap_analysis
fi

echo "[entrypoint] 执行: $*"
exec "$@"
