"""全局路径、常量与实验参数。

所有模块统一从此处读取路径，避免硬编码；任何目录调整只需修改本文件。
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEANED_DIR = DATA_DIR / "cleaned"
FEATURE_STORE_DIR = DATA_DIR / "feature_store"
EXTERNAL_DIR = DATA_DIR / "external"

CRAWLER_DIR = PROJECT_ROOT / "crawlers"
ETL_DIR = PROJECT_ROOT / "etl"
MODEL_DIR = PROJECT_ROOT / "models"
ARTIFACT_DIR = MODEL_DIR / "artifacts"
CACHE_DIR = PROJECT_ROOT / "cache"
REPORT_DIR = PROJECT_ROOT / "reports"
DOCS_DIR = PROJECT_ROOT / "docs"
DESIGN_DIR = DOCS_DIR / "desgin"
NOTEBOOK_DIR = PROJECT_ROOT / "notebooks"

# ---------------------------------------------------------------------------
# 数据文件
# ---------------------------------------------------------------------------
RAW_FINANCIAL = RAW_DIR / "csmar_financial.csv"          # 财务报表主表
RAW_GOVERNANCE = RAW_DIR / "csmar_governance.csv"        # 公司治理
RAW_TEXT_SENTIMENT = RAW_DIR / "text_sentiment.csv"      # 年报 MD&A 情感
RAW_LEGAL = RAW_DIR / "legal_events.csv"                 # 司法/合规事件
RAW_MARKET = RAW_DIR / "market_features.csv"             # 市场交易特征
RAW_LABELS = RAW_DIR / "labels_st.csv"                   # ST 标签
RAW_MACRO = EXTERNAL_DIR / "macro_industry.csv"          # 宏观与行业指标

CLEANED_PANEL = CLEANED_DIR / "panel_clean.parquet"
FEATURE_PANEL = FEATURE_STORE_DIR / "panel_features.parquet"
FEATURE_MATRIX = FEATURE_STORE_DIR / "panel_model_input.parquet"
FEATURE_LIST = FEATURE_STORE_DIR / "selected_features.json"
FEATURE_REPORT = FEATURE_STORE_DIR / "feature_selection_report.csv"

MODEL_PATH = ARTIFACT_DIR / "xgboost_final.json"
MODEL_ALL_PATH = ARTIFACT_DIR / "all_models.pkl"
MODEL_META = ARTIFACT_DIR / "model_meta.json"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"
EVAL_REPORT = ARTIFACT_DIR / "evaluation_report.md"
SHAP_VALUES = CACHE_DIR / "shap_values.pkl"
SHAP_EXPLAINER = CACHE_DIR / "shap_explainer.pkl"
PREDICTION_PATH = CACHE_DIR / "predictions.parquet"
MONITOR_REPORT = ARTIFACT_DIR / "monitor_report.json"

# ---------------------------------------------------------------------------
# 实验参数
# ---------------------------------------------------------------------------
RANDOM_SEED = 42
CV_SPLITS = 5
TRAIN_YEAR_RANGE = (2015, 2021)
VALID_YEAR = 2022
TEST_YEAR = 2023
# 锁箱年份：待 2026 官方 ST 标签披露后再评估，不调参、不重选阈值（见中期报告 §4.4）
LOCKBOX_YEAR = 2024
PANEL_YEARS = tuple(range(TRAIN_YEAR_RANGE[0], TEST_YEAR + 1))

# 领域先验：二值 IV 修复后，审计意见必须进入候选/最终模型。
# 该特征在 IV 步通过后强制保留，避免 RF 重要性分位把它误删。
FORCE_FEATURES = ("audit_opinion",)

# 概率校准：在验证集拟合，测试集只应用；默认等渗回归（小样本可用 Platt 回退）。
CALIBRATION_METHOD = "isotonic"
CALIBRATOR_PATH = ARTIFACT_DIR / "calibrator.pkl"

# 成本敏感阈值：漏报一个 ST 的成本 / 误报一个正常企业的成本。
# 10:1 是中期默认值，论文中应做 5:1、10:1、20:1 敏感性。
COST_FN = 10.0
COST_FP = 1.0

# Top-k 复核容量：按分数排序取前 5%/10% 作为人工复核名单。
TOP_K_FRACTIONS = (0.05, 0.10)
TOP_K_PRIMARY = 0.10

# 标签定义：使用 T-2 年财务数据预测 T 年 ST 状态，规避前视偏差
LABEL_HORIZON = 2

# ---------------------------------------------------------------------------
# 业务阈值（风险分级与特征筛选）
# ---------------------------------------------------------------------------
# 兜底值：仅在缺少 model_meta.json 时使用。训练完成后，分级阈值由
# model_meta.json 的 threshold 块提供（验证集冻结），评估、监控与前端同源读取。
RISK_THRESHOLDS = {
    "high": 0.50,     # P(ST) >= 0.50 → 高风险
    "medium": 0.25,   # 0.25 <= P(ST) < 0.50 → 中风险
}                     # 其余为低风险

# 中风险观察带 = 高风险（预警）阈值 × 该比例
RISK_MEDIUM_RATIO = 0.5

RISK_LEVELS = ["高风险", "中风险", "低风险"]
RISK_COLORS = {"高风险": "#d62728", "中风险": "#ff9f1c", "低风险": "#2ca02c"}

IV_MIN = 0.02
CORR_MAX = 0.85
VIF_MAX = 10.0
PSI_WARN = 0.10
PSI_BLOCK = 0.25
MIN_FEATURES = 25

# ---------------------------------------------------------------------------
# 样本范围
# ---------------------------------------------------------------------------
INDUSTRIES = {
    "C13": "农副食品加工业",
    "C26": "化学原料和化学制品制造业",
    "C27": "医药制造业",
    "C34": "通用设备制造业",
    "C35": "专用设备制造业",
    "C36": "汽车制造业",
    "C38": "电气机械和器材制造业",
    "C39": "计算机、通信和其他电子设备制造业",
}

EXCLUDED_INDUSTRIES = {"J": "金融业", "K": "房地产业", "S": "综合"}

# ---------------------------------------------------------------------------
# 运行环境
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"


def ensure_dirs() -> None:
    """创建运行期必需目录（幂等）。"""
    for path in (
        RAW_DIR, CLEANED_DIR, FEATURE_STORE_DIR, EXTERNAL_DIR,
        ARTIFACT_DIR, CACHE_DIR, REPORT_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def rel(path: Path) -> str:
    """返回相对项目根目录的可读路径，用于日志和前端展示。"""
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)
