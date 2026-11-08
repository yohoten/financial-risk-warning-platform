"""特征注册表：70+ 维特征的唯一事实来源（Single Source of Truth）。

ETL、模型、前端（雷达图/数据字典）均从此处读取特征元数据，
避免"文档写一套、代码写一套"的口径漂移。

字段说明
--------
key            : 英文列名（数据框列名）
cn             : 中文名称（前端展示）
group          : 所属维度，见 FEATURE_GROUP_LABELS
higher_better  : True 表示数值越高财务越健康（正向指标），False 为逆向指标
source         : 数据来源 csmar / derived / text / crawl / macro
note           : 业务含义与计算口径
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    cn: str
    group: str
    higher_better: bool
    source: str
    note: str


FEATURE_GROUP_LABELS = {
    "solvency": "偿债能力",
    "profitability": "盈利能力",
    "operation": "营运能力",
    "growth": "成长能力",
    "cashflow": "现金流",
    "text": "文本情感",
    "governance": "公司治理",
    "audit_market_legal": "审计/市场/司法",
    "macro_industry": "宏观/行业",
}

# 六维雷达图使用的维度（与业务汇报口径一致）
RADAR_DIMENSIONS = ["solvency", "profitability", "operation", "growth", "cashflow", "governance"]

TARGET_COLUMN = "is_st"
ID_COLUMNS = ["stock_code", "year", "company_name", "industry"]

# ---------------------------------------------------------------------------
# 特征定义：(key, 中文名, 维度, 越高越好, 来源, 口径说明)
# ---------------------------------------------------------------------------
_RAW: list[tuple[str, str, str, bool, str, str]] = [
    # ---------------- 偿债能力 (10) ----------------
    ("current_ratio", "流动比率", "solvency", True, "derived", "流动资产/流动负债，短期偿付能力的核心指标"),
    ("quick_ratio", "速动比率", "solvency", True, "derived", "(流动资产-存货)/流动负债，剔除存货变现能力差的影响"),
    ("cash_ratio", "现金比率", "solvency", True, "derived", "货币资金/流动负债，最严格的短期偿债口径"),
    ("debt_to_asset", "资产负债率", "solvency", False, "derived", "总负债/总资产，Altman Z-Score 核心变量"),
    ("equity_multiplier", "产权比率", "solvency", False, "derived", "总负债/所有者权益，衡量财务杠杆"),
    ("interest_coverage", "利息保障倍数", "solvency", True, "derived", "EBIT/利息费用，低于1提示偿付危机"),
    ("lt_debt_to_ebitda", "长期债务/EBITDA", "solvency", False, "derived", "长期偿债压力的国际通用口径"),
    ("short_debt_ratio", "短期借款占比", "solvency", False, "derived", "短期借款/总负债，短债长投的流动性风险"),
    ("interest_debt_ratio", "有息负债率", "solvency", False, "derived", "有息负债/总资产，剔除经营性负债的杠杆"),
    ("ocf_to_debt", "经营现金流/总负债", "solvency", True, "derived", "以现金流口径衡量的偿债覆盖能力"),
    # ---------------- 盈利能力 (10) ----------------
    ("roa", "总资产报酬率", "profitability", True, "derived", "净利润/平均总资产，Ohlson O-Score 变量"),
    ("roe", "净资产收益率", "profitability", True, "derived", "净利润/平均净资产"),
    ("gross_margin", "毛利率", "profitability", True, "derived", "(营业收入-营业成本)/营业收入"),
    ("net_margin", "净利率", "profitability", True, "derived", "净利润/营业收入"),
    ("ebitda_margin", "EBITDA利润率", "profitability", True, "derived", "EBITDA/营业收入，剔除折旧摊销与资本结构影响"),
    ("cost_profit_ratio", "成本费用利润率", "profitability", True, "derived", "利润总额/成本费用总额"),
    ("operating_margin", "营业利润率", "profitability", True, "derived", "营业利润/营业收入"),
    ("deducted_profit_ratio", "扣非净利润占比", "profitability", True, "derived", "扣非净利润/净利润，识别依赖非经常性损益的企业"),
    ("roe_change", "ROE同比变化", "profitability", True, "derived", "本期ROE-上期ROE，盈利能力的边际恶化更早预警"),
    ("eps", "每股收益", "profitability", True, "csmar", "归母净利润/总股本"),
    # ---------------- 营运能力 (10) ----------------
    ("ar_turnover", "应收账款周转率", "operation", True, "derived", "营业收入/平均应收账款，回款效率"),
    ("inventory_turnover", "存货周转率", "operation", True, "derived", "营业成本/平均存货，存货积压的直接信号"),
    ("asset_turnover", "总资产周转率", "operation", True, "derived", "营业收入/平均总资产"),
    ("fixed_asset_turnover", "固定资产周转率", "operation", True, "derived", "营业收入/平均固定资产"),
    ("working_capital_turnover", "营运资金周转率", "operation", True, "derived", "营业收入/平均营运资金"),
    ("cash_conversion_cycle", "现金转换周期", "operation", False, "derived", "存货周转天数+应收周转天数-应付周转天数"),
    ("ar_to_revenue", "应收账款/营业收入", "operation", False, "derived", "收入质量，激增往往伴随放宽信用政策"),
    ("inventory_to_assets", "存货/总资产", "operation", False, "derived", "存货占比，反映资产流动性与减值风险"),
    ("payable_days", "应付账款周转天数", "operation", True, "derived", "对上游的占款能力，过度延长是资金链紧张的信号"),
    ("ocf_to_revenue", "经营现金流/营业收入", "operation", True, "derived", "收入含金量，长期低于0.05需警惕"),
    # ---------------- 成长能力 (8) ----------------
    ("revenue_growth", "营业收入增长率", "growth", True, "derived", "(本期营收-上期营收)/上期营收"),
    ("profit_growth", "净利润增长率", "growth", True, "derived", "(本期净利润-上期净利润)/|上期净利润|"),
    ("asset_growth", "总资产增长率", "growth", True, "derived", "资产扩张速度，过快扩张伴随财务风险"),
    ("equity_growth", "净资产增长率", "growth", True, "derived", "内生积累能力"),
    ("ocf_growth", "经营现金流增长率", "growth", True, "derived", "造血能力的边际变化"),
    ("rd_growth", "研发费用增长率", "growth", True, "derived", "研发投入的持续性"),
    ("capex_to_depreciation", "资本支出/折旧", "growth", True, "derived", "低于1意味着产能收缩、维持性投入不足"),
    ("revenue_cagr_3y", "营收3年复合增速", "growth", True, "derived", "剔除单年波动后的中期成长性"),
    # ---------------- 现金流 (7) ----------------
    ("ocf_to_net_profit", "经营现金流/净利润", "cashflow", True, "derived", "利润的现金含量，持续低于0.5可能是盈余操纵前兆"),
    ("fcf_to_assets", "自由现金流/总资产", "cashflow", True, "derived", "(经营现金流-资本支出)/总资产"),
    ("icf_to_assets", "投资现金流/总资产", "cashflow", True, "derived", "投资活动净流量/总资产"),
    ("financing_to_assets", "筹资现金流/总资产", "cashflow", False, "derived", "高度依赖外部融资是风险累积的信号"),
    ("cash_to_assets", "现金及等价物/总资产", "cashflow", True, "derived", "现金储备厚度"),
    ("ocf_volatility", "经营现金流波动率", "cashflow", False, "derived", "近3年经营现金流标准差/均值绝对值"),
    ("fcf_negative_years", "自由现金流连续为负年数", "cashflow", False, "derived", "连续为负的时间越长，资金链压力越大"),
    # ---------------- 文本情感 (6) ----------------
    ("mdna_positive", "MD&A正面情感得分", "text", True, "text", "FinBERT 对管理层讨论与分析的正向概率均值"),
    ("mdna_negative", "MD&A负面情感得分", "text", False, "text", "FinBERT 负面概率均值，风险披露的领先指标"),
    ("mdna_uncertainty", "MD&A不确定性得分", "text", False, "text", "不确定性词典+模型打分，高不确定性预示业绩波动"),
    ("sentiment_polarity", "情感极性", "text", True, "text", "正面得分-负面得分"),
    ("sentiment_volatility", "情感波动率", "text", False, "text", "段落级情感得分标准差，语境矛盾度的代理变量"),
    ("forward_looking_ratio", "前瞻性词汇占比", "text", False, "text", "战略/计划类词汇占比，过度乐观表述的识别"),
    # ---------------- 公司治理 (6) ----------------
    ("top1_holding", "第一大股东持股比例", "governance", True, "csmar", "股权集中度，适度集中有利于监督"),
    ("equity_balance", "股权制衡度(Z指数)", "governance", True, "derived", "第二至五大股东持股/第一大股东持股"),
    ("board_size", "董事会规模", "governance", True, "csmar", "董事会人数，过大降低决策效率"),
    ("independent_ratio", "独立董事比例", "governance", True, "derived", "独立董事人数/董事会人数"),
    ("management_holding", "管理层持股比例", "governance", True, "csmar", "利益一致性，过低易产生代理问题"),
    ("duality", "两职合一", "governance", False, "csmar", "董事长兼任总经理=1，权力过度集中"),
    # ---------------- 审计/市场/司法 (8) ----------------
    ("audit_opinion", "审计意见类型", "audit_market_legal", False, "csmar", "非标准无保留意见=1，强预警信号"),
    ("big4_audit", "是否四大审计", "audit_market_legal", True, "csmar", "国际四大=1，审计质量代理变量"),
    ("audit_fee_ratio", "审计费用/总资产", "audit_market_legal", False, "derived", "异常审计费用关联审计意见购买"),
    ("annual_turnover", "年换手率", "audit_market_legal", True, "derived", "年均换手率，流动性/关注度的代理"),
    ("stock_volatility", "股价年化波动率", "audit_market_legal", False, "derived", "日收益率标准差×√252"),
    ("institutional_holding", "机构持股比例", "audit_market_legal", True, "csmar", "机构投资者的信息优势与监督效应"),
    ("litigation_count", "当年涉诉次数", "audit_market_legal", False, "crawl", "企查查/裁判文书网抓取"),
    ("penalty_count", "行政处罚次数", "audit_market_legal", False, "crawl", "环保/税务/交易所处罚合计"),
    # ---------------- 宏观/行业 (8) ----------------
    ("gdp_growth", "GDP同比增速", "macro_industry", True, "macro", "国家统计局季度同比"),
    ("m2_growth", "M2同比增速", "macro_industry", True, "macro", "货币供应量增速，衡量市场流动性环境"),
    ("cpi_yoy", "CPI同比", "macro_industry", False, "macro", "通胀压力，抬升成本端"),
    ("ppi_yoy", "PPI同比", "macro_industry", True, "macro", "工业品价格，制造业景气度"),
    ("social_financing_growth", "社融存量增速", "macro_industry", True, "macro", "社会融资规模存量增速，反映实体信贷可得性"),
    ("pmi_manufacturing", "制造业PMI", "macro_industry", True, "macro", "荣枯线50，领先于企业盈利"),
    ("industry_roa_gap", "行业ROA偏离度", "macro_industry", True, "derived", "企业ROA-行业中位数ROA"),
    ("industry_debt_gap", "行业杠杆偏离度", "macro_industry", False, "derived", "企业资产负债率-行业中位数"),
]

FEATURES: list[FeatureSpec] = [FeatureSpec(*row) for row in _RAW]
FEATURE_MAP: dict[str, FeatureSpec] = {f.key: f for f in FEATURES}
FEATURE_KEYS: list[str] = [f.key for f in FEATURES]


def by_group(group: str) -> list[FeatureSpec]:
    """返回某个维度下的全部特征。"""
    return [f for f in FEATURES if f.group == group]


def cn_names(keys: Iterable[str]) -> dict[str, str]:
    """英文列名 -> 中文名映射，用于图表坐标轴。"""
    return {k: FEATURE_MAP[k].cn if k in FEATURE_MAP else k for k in keys}


def group_of(keys: Iterable[str]) -> dict[str, str]:
    """英文列名 -> 所属维度，用于分组聚合。"""
    return {k: FEATURE_MAP[k].group if k in FEATURE_MAP else "other" for k in keys}


def direction_of(keys: Iterable[str]) -> dict[str, int]:
    """英文列名 -> 方向系数，+1 表示越高越健康。"""
    return {k: (1 if FEATURE_MAP[k].higher_better else -1) if k in FEATURE_MAP else 1 for k in keys}


def to_records() -> list[dict]:
    """导出为字典列表，供数据字典页面/文档渲染。"""
    return [
        {
            "字段名": f.key,
            "中文名": f.cn,
            "维度": FEATURE_GROUP_LABELS.get(f.group, f.group),
            "方向": "正向" if f.higher_better else "逆向",
            "来源": f.source,
            "口径说明": f.note,
        }
        for f in FEATURES
    ]


if __name__ == "__main__":
    print(f"特征总数: {len(FEATURES)}")
    for g, label in FEATURE_GROUP_LABELS.items():
        print(f"  {label:<12} {len(by_group(g)):>2} 维")
