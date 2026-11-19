# 财务风险预警平台 · 常用命令
# Windows 用户可直接复制命令执行，或使用 `make`（需安装 GNU Make）

PY ?= python

.PHONY: help install data sync sync-write readiness depreciation debt-fix annual-market pipeline validate train evaluate shap monitor app api web-build desktop-backend desktop-dist test lint docker clean

help:  ## 显示所有可用命令
	@grep -E "^[a-zA-Z_-]+:.*?## .*$$" $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## 安装依赖
	$(PY) -m pip install -r requirements.txt

data:  ## 生成演示原始数据（data/raw 已有真实数据时会拒绝覆盖；确需覆盖用 --force）
	$(PY) -m data.gen_demo_data

pipeline:  ## 清洗 + 特征工程 + 四步特征筛选
	$(PY) -m etl.run_pipeline

sync:  ## 预演：DATA_RAW_Download → data/incoming/csmar 规范化
	$(PY) -m scripts.sync_raw_download

sync-write:  ## 执行规范化（硬链接/流式拼接 + manifest）
	$(PY) -m scripts.sync_raw_download --write

readiness:  ## 数据与训练就绪度体检（G0–G5）
	$(PY) -m scripts.check_data_readiness

depreciation:  ## G-03：用 FS_Comscfi 官方折旧替换回填值并写回
	$(PY) -m scripts.import_comscfi_official --write

debt-fix:  ## G-04：按 CSMAR 带息债务口径重建有息负债
	$(PY) -m scripts.fix_interest_debt --write

annual-market:  ## TRD_Year → 年度市场候选特征（仅消融）
	$(PY) -m scripts.build_annual_market_features --write

validate:  ## 原始数据质量校验（进入 ETL 前）
	$(PY) -m scripts.validate_raw_data

train:  ## 训练五模型 + Optuna 调优
	$(PY) -m models.train --trials 30

evaluate:  ## 生成模型评估报告
	$(PY) -m models.evaluate

shap:  ## 计算并缓存 SHAP 解释
	$(PY) -m models.shap_analysis

monitor:  ## PSI 漂移监控
	$(PY) -m models.monitor

app:  ## 启动 Streamlit 平台
	$(PY) -m streamlit run streamlit_app/streamlit_app.py

api:  ## 启动 FastAPI 服务层（Vue 大屏后端）
	$(PY) -m uvicorn api.main:app --host 127.0.0.1 --port 8000

web-build:  ## 构建 Vue 前端（web/dist）
	cd web && npm install && npm run build

desktop-backend:  ## 用 PyInstaller 打包后端（desktop/resources/backend）
	$(PY) scripts/build_backend.py

desktop-dist: web-build desktop-backend  ## 打包 Windows 桌面端（nsis + portable）
	cd desktop && npm install && npm run dist

all: data pipeline train evaluate shap  ## 空目录全链路演示（已有真实数据请只跑 make pipeline）

test:  ## 运行单元测试
	$(PY) -m pytest -q

smoke:  ## Streamlit 六页面冒烟测试（不启动浏览器）
	$(PY) -m scripts.smoke_streamlit

lint:  ## 代码风格检查
	$(PY) -m ruff check .

docker:  ## 构建并启动容器
	docker compose up -d --build

clean:  ## 清理冗余产物（构建/缓存/备份，不删除原始数据与模型权重）
	$(PY) -m scripts.clean_project --write

clean-dry:  ## 预演清理（仅列出将删除项，不真正删除）
	$(PY) -m scripts.clean_project
