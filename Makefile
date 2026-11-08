# 财务风险预警平台 · 常用命令
# Windows 用户可直接复制命令执行，或使用 `make`（需安装 GNU Make）

PY ?= python

.PHONY: help install data pipeline train evaluate shap monitor app test lint docker clean

help:  ## 显示所有可用命令
	@grep -E "^[a-zA-Z_-]+:.*?## .*$$" $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## 安装依赖
	$(PY) -m pip install -r requirements.txt

data:  ## 生成演示原始数据
	$(PY) -m data.gen_demo_data

pipeline:  ## 清洗 + 特征工程 + 四步特征筛选
	$(PY) -m etl.run_pipeline

train:  ## 训练五模型 + Optuna 调优
	$(PY) -m models.train --trials 30

evaluate:  ## 生成模型评估报告
	$(PY) -m models.evaluate

shap:  ## 计算并缓存 SHAP 解释
	$(PY) -m models.shap_analysis

monitor:  ## PSI 漂移监控
	$(PY) -m models.monitor

app:  ## 启动 Streamlit 平台
	$(PY) -m streamlit run streamlit_app/app.py

all: data pipeline train evaluate shap  ## 全链路一键复现

test:  ## 运行单元测试
	$(PY) -m pytest -q

smoke:  ## Streamlit 六页面冒烟测试（不启动浏览器）
	$(PY) -m scripts.smoke_streamlit

lint:  ## 代码风格检查
	$(PY) -m ruff check .

docker:  ## 构建并启动容器
	docker compose up -d --build

clean:  ## 清理缓存产物（不删除原始数据）
	rm -rf cache/* reports/* models/artifacts/* data/cleaned/* data/feature_store/*
