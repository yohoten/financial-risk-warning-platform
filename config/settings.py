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

# 运行时资源根目录：桌面端打包形态下，代码被冻结成 exe、数据资产放在同级
# runtime/ 目录，通过 RISK_RUNTIME_DIR 指向；开发态为空，走项目目录。
_RUNTIME_DIR = os.getenv("RISK_RUNTIME_DIR", "").strip()
RUNTIME_DIR = Path(_RUNTIME_DIR) if _RUNTIME_DIR else None


def rt(rel: str) -> Path:
    """运行时资源路径：优先 runtime/ 目录，其次项目目录。"""
    if RUNTIME_DIR is not None:
        cand = RUNTIME_DIR / rel
        if cand.exists():
            return cand
    return PROJECT_ROOT / rel


DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEANED_DIR = DATA_DIR / "cleaned"
FEATURE_STORE_DIR = DATA_DIR / "feature_store"
EXTERNAL_DIR = DATA_DIR / "external"

# 数据落地区与暂存区：下载原包只读，暂存区做规范化命名后再进入契约层。
INCOMING_DIR = DATA_DIR / "incoming"
STAGING_DIR = INCOMING_DIR / "csmar"
# 用户下载的 CSMAR 原始包目录（体积大、不入库）；可用环境变量指向别处。
RAW_DOWNLOAD_DIR = Path(
    os.getenv("RISK_RAW_DOWNLOAD_DIR", str(PROJECT_ROOT / "DATA_RAW_Download"))
)

CRAWLER_DIR = PROJECT_ROOT / "crawlers"
ETL_DIR = PROJECT_ROOT / "etl"
MODEL_DIR = PROJECT_ROOT / "models"
ARTIFACT_DIR = MODEL_DIR / "artifacts"
CACHE_DIR = PROJECT_ROOT / "cache"

# 桌面端打包形态：可写数据目录（alerts.db、市值快照、报告输出）可被重定向到
# 用户数据目录，避免往只读的安装目录里写。
_DATA_DIR_ENV = os.getenv("RISK_DATA_DIR", "").strip()
WRITABLE_DIR = Path(_DATA_DIR_ENV) if _DATA_DIR_ENV else PROJECT_ROOT
CACHE_DIR = WRITABLE_DIR / "cache"
REPORT_DIR = WRITABLE_DIR / "reports"

# 桌面端打包形态：只读资产（模型产物、缓存快照）从 runtime/ 读取；
# 可写资产（alerts.db、market_cap 快照、报告输出）仍落到用户可写目录。
ARTIFACT_READ_DIR = rt("models/artifacts")
CACHE_READ_DIR = rt("cache")
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
RAW_DIGITAL = RAW_DIR / "digital_features.csv"           # 数字化转型词频
RAW_MARKET = RAW_DIR / "market_features_trd.csv"         # 市场交易特征（TRD 小数口径）
RAW_LABELS = RAW_DIR / "labels_st.csv"                   # ST 标签
RAW_MACRO = EXTERNAL_DIR / "macro_industry.csv"          # 宏观与行业指标

CLEANED_PANEL = rt("data/cleaned/panel_clean.parquet")
FEATURE_PANEL = rt("data/feature_store/panel_features.parquet")
FEATURE_MATRIX = rt("data/feature_store/panel_model_input.parquet")
FEATURE_LIST = rt("data/feature_store/selected_features.json")
FEATURE_REPORT = rt("data/feature_store/feature_selection_report.csv")

# 覆盖标记：不进入特征筛选，但随面板/建模输入保留，供评估、监控和前端区分
# “真实缺失”与“业务上的 0 值”。
AVAILABILITY_COLUMNS = [
    "text_available",
    "legal_available",
    "digital_available",
    "market_available",
]

MODEL_PATH = ARTIFACT_READ_DIR / "xgboost_final.json"
MODEL_ALL_PATH = ARTIFACT_READ_DIR / "all_models.pkl"
MODEL_META = ARTIFACT_READ_DIR / "model_meta.json"
METRICS_PATH = ARTIFACT_READ_DIR / "metrics.json"
EVAL_REPORT = ARTIFACT_READ_DIR / "evaluation_report.md"
SHAP_VALUES = CACHE_READ_DIR / "shap_values.pkl"
SHAP_EXPLAINER = CACHE_READ_DIR / "shap_explainer.pkl"
PREDICTION_PATH = CACHE_READ_DIR / "predictions.parquet"
# 总市值快照（AkShare 东财刷新时落盘，供 Altman Z 的 X4 使用）——可写目录
MARKET_CAP_PATH = CACHE_DIR / "market_cap.parquet"
MONITOR_REPORT = ARTIFACT_READ_DIR / "monitor_report.json"

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
CALIBRATOR_PATH = ARTIFACT_READ_DIR / "calibrator.pkl"

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
# 配色与前端 web/src/lib/theme.ts 的 C 常量保持一致（避免三端配色漂移）
RISK_COLORS = {"高风险": "#dc2626", "中风险": "#ea580c", "低风险": "#16a34a"}

# 全站语义色（对应前端 C 常量）
COLOR_PRIMARY = "#2563eb"
COLOR_ACCENT = "#06b6d4"
COLOR_OK = "#16a34a"
COLOR_WARN = "#d97706"
COLOR_DANGER = "#dc2626"
COLOR_GRAY = "#94a3b8"
COLOR_VIOLET = "#7c3aed"

IV_MIN = 0.02
CORR_MAX = 0.85
VIF_MAX = 10.0
PSI_WARN = 0.10
PSI_BLOCK = 0.25
MIN_FEATURES = 25

# 特征缩尾：只用训练窗口估计分位点，再应用到验证/测试，避免测试集信息泄露。
WINSOR_LOWER = 0.01
WINSOR_UPPER = 0.99

# ---------------------------------------------------------------------------
# 样本范围
# ---------------------------------------------------------------------------
MANUFACTURING_PREFIX = "C"

# 仅用于演示数据生成；真实数据按证监会门类前缀 C（制造业）整体过滤。
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
# 论文主样本：沪深 A 股制造业（证监会 C 门类）。原始财务表保留全 A，
# 仅在清洗面板阶段过滤，便于后续开展全 A 稳健性对照。
SAMPLE_INDUSTRY_PREFIXES = ("C",)

# ---------------------------------------------------------------------------
# 运行环境
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"

# FastAPI 服务层：设置后前端数据访问走 HTTP，否则本地直连领域层。
# 例：RISK_API_URL=http://localhost:8000
RISK_API_URL = os.getenv("RISK_API_URL", "").rstrip("/")
RISK_API_TIMEOUT = float(os.getenv("RISK_API_TIMEOUT", "10"))

# ---------------------------------------------------------------------------
# LLM 研判（OpenAI 兼容端点；base_url + model 未配置时研判退化为纯规则）
# ---------------------------------------------------------------------------
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_ANALYSIS_MAX_TOKENS = int(os.getenv("LLM_ANALYSIS_MAX_TOKENS", "4096"))
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "60"))

# ---------------------------------------------------------------------------
# LLM Agent / 上下文压缩 / 预热（移植自旧项目 server/app/core/config.py，
# 供设置面板 DB 覆盖热生效；仅 Agent 对话与多模态路径使用，不影响研判降级）
# ---------------------------------------------------------------------------
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))
LLM_DISABLE_THINKING = os.getenv("LLM_DISABLE_THINKING", "0") == "1"
LLM_MAX_TURNS = int(os.getenv("LLM_MAX_TURNS", "8"))
LLM_SHORT_TERM_WINDOW = int(os.getenv("LLM_SHORT_TERM_WINDOW", "3"))

AGENT_REQUIRE_APPROVAL = os.getenv("AGENT_REQUIRE_APPROVAL", "1") == "1"
AGENT_APPROVAL_TIMEOUT = int(os.getenv("AGENT_APPROVAL_TIMEOUT", "300"))

LLM_CONTEXT_WINDOW = int(os.getenv("LLM_CONTEXT_WINDOW", "128000"))
COMPACTION_ENABLED = os.getenv("COMPACTION_ENABLED", "1") == "1"
COMPACTION_THRESHOLD_RATIO = float(os.getenv("COMPACTION_THRESHOLD_RATIO", "0.8"))
COMPACTION_RETAIN_RATIO = float(os.getenv("COMPACTION_RETAIN_RATIO", "0.16"))
COMPACTION_SUMMARY_MAX_TOKENS = int(os.getenv("COMPACTION_SUMMARY_MAX_TOKENS", "1024"))

PREHEAT_ENABLED = os.getenv("PREHEAT_ENABLED", "1") == "1"
PREHEAT_ON_STARTUP = os.getenv("PREHEAT_ON_STARTUP", "1") == "1"
PREHEAT_TTL_SECONDS = int(os.getenv("PREHEAT_TTL_SECONDS", "600"))


# ---------------------------------------------------------------------------
# 认证与权限（P1）
# ---------------------------------------------------------------------------
# RISK_AUTH_MODE:
#   full  —— 强制登录（Web / 生产形态，默认）
#   local —— 桌面端 / 单机演示：自动以 local-admin（全部权限）放行，不出登录页
#   off   —— 仅供离线批处理脚本，视同 local 且不写审计
AUTH_MODES = ("full", "local", "off")


def auth_mode() -> str:
    """当前认证模式（动态读取，便于测试与桌面端在运行期切换）。

    默认值：源码运行 / Web 形态 = full（强制登录）；
    被 PyInstaller 冻结（Electron 桌面端）时 = local（免登录，单机单用户）。
    """
    mode = os.getenv("RISK_AUTH_MODE", "").strip().lower()
    if not mode:
        import sys as _sys

        mode = "local" if getattr(_sys, "frozen", False) else "full"
    return mode if mode in AUTH_MODES else "full"


def auth_enabled() -> bool:
    """是否强制校验身份（local/off 模式下业务接口不校验）。"""
    return auth_mode() == "full"


def audit_enabled() -> bool:
    """local/off 免登录形态下仍可关掉审计写入。"""
    return auth_mode() != "off"


ACCESS_TOKEN_MINUTES = int(os.getenv("RISK_ACCESS_TOKEN_MINUTES", "30"))
ACCESS_TOKEN_EXPIRE_MINUTES = ACCESS_TOKEN_MINUTES  # 别名，与 ZNCBZS 命名对齐
REFRESH_TOKEN_DAYS = int(os.getenv("RISK_REFRESH_TOKEN_DAYS", "7"))

# 初始管理员：RISK_ADMIN_PASSWORD 未设置时用演示弱口令并强制改密（启动日志告警）。
INITIAL_ADMIN_USERNAME = os.getenv("RISK_ADMIN_USERNAME", "admin").strip() or "admin"
INITIAL_ADMIN_PASSWORD = os.getenv("RISK_ADMIN_PASSWORD", "").strip()
INITIAL_ADMIN_EMAIL = os.getenv("RISK_ADMIN_EMAIL", "admin@example.com").strip()
DEMO_ADMIN_PASSWORD = "admin12345"

LOGIN_MAX_ATTEMPTS = int(os.getenv("RISK_LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCK_MINUTES = int(os.getenv("RISK_LOGIN_LOCK_MINUTES", "15"))
LOGIN_RATE_LIMIT = int(os.getenv("RISK_LOGIN_RATE_LIMIT", "10"))  # 每分钟/IP
PASSWORD_MIN_LENGTH = int(os.getenv("RISK_PASSWORD_MIN_LENGTH", "8"))

_auth_secret_cache: str | None = None


def auth_secret() -> str:
    """JWT 签名密钥：优先环境变量，其次持久化到可写目录（重启不失效）。

    未配置时随机生成并落盘 cache/.auth_secret，绝不回退到硬编码常量。
    """
    global _auth_secret_cache
    if _auth_secret_cache:
        return _auth_secret_cache
    env = os.getenv("RISK_AUTH_SECRET", "").strip() or os.getenv("JWT_SECRET_KEY", "").strip()
    if env:
        _auth_secret_cache = env
        return env
    import secrets as _secrets

    path = CACHE_DIR / ".auth_secret"
    try:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                _auth_secret_cache = value
                return value
        value = _secrets.token_urlsafe(48)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        try:  # 尽量收紧权限（POSIX；Windows 上静默忽略）
            path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        value = _secrets.token_urlsafe(48)
    _auth_secret_cache = value
    return value


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
