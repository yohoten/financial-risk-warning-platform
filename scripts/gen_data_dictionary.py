"""从特征注册表生成《数据字典》Markdown，保证文档与代码同源。

用法：python -m scripts.gen_data_dictionary
输出：docs/数据字典与特征口径.md
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from config.feature_registry import (
    FEATURE_GROUP_LABELS,
    FEATURES,
    RADAR_DIMENSIONS,
    TARGET_COLUMN,
    by_group,
)

HEADER = """# 数据字典与特征口径

> 本文件由 `scripts/gen_data_dictionary.py` 自动生成，请勿手工修改。
> 特征元数据的唯一事实来源是 `config/feature_registry.py`。

## 一、总览

| 维度 | 特征数 | 说明 |
|------|-------|------|
"""

FOOTER = """
## 五、标签定义

| 项 | 定义 |
|----|------|
| 标签字段 | `{target}` |
| 正样本 | T 年被实施 ST 或 *ST 的上市公司 |
| 特征时点 | T-{horizon} 年财务与文本数据（避免前视偏差） |
| 训练窗口 | {train_start}-{train_end} 年 |
| 验证窗口 | {valid} 年（时间序列外验证，OOT） |
| 测试窗口 | {test} 年（仅用于最终评估，不参与调优） |
| 行业范围 | 沪深 A 股制造业（证监会 C 类），剔除金融、房地产、综合 |

## 六、缺失值与异常值处理规则

| 环节 | 规则 | 理由 |
|------|------|------|
| 去重 | 按 `stock_code + year` 保留最后一条 | 后写入视为数据更新 |
| 缺失插补 | 公司内线性插值（≤2 期）→ 行业-年度中位数 → 全局中位数 | 保留时间连续性，避免跨公司信息污染 |
| 文本缺失 | 情感极性置 0（中性） | 「未披露」不等于「极度悲观」 |
| 异常值 | 按 1%/99% 分位缩尾 | 抑制极端值对树模型分裂点的影响 |
| 样本剔除 | 关键科目缺失、总资产≤0、覆盖率<70% | 插补可靠性不足的样本不进入建模 |
| 比率计算 | 分母为 0 或缺失时返回 NaN | 避免 inf 污染特征 |

## 七、特征筛选四步法

| 步骤 | 方法 | 阈值 | 作用 |
|------|------|------|------|
| Step 1 | IV 值（Information Value） | IV ≥ 0.02 | 剔除无预测力特征 |
| Step 2 | Pearson 相关 + VIF | \\|r\\| ≤ 0.85，VIF ≤ 10 | 去除共线性冗余 |
| Step 3 | PSI（跨期稳定性） | PSI ≤ 0.25 | 剔除分布不稳定的特征 |
| Step 4 | Boruta / RF 重要性 | 保留重要特征 | 最终确认，输出 35-50 维 |

> 筛选统计量仅在训练窗口内估计，验证集与测试集只做变换，不参与任何选择决策。
"""


def build_markdown() -> str:
    lines = [HEADER]
    for group, label in FEATURE_GROUP_LABELS.items():
        specs = by_group(group)
        radar = "（雷达图维度）" if group in RADAR_DIMENSIONS else ""
        lines.append(f"| {label}{radar} | {len(specs)} | {specs[0].note[:24]}… |\n")

    lines.append(f"\n**合计：{len(FEATURES)} 维特征**\n")
    lines.append("\n## 二、财务维度（偿债 / 盈利 / 营运 / 成长 / 现金流）\n")

    for group in ["solvency", "profitability", "operation", "growth", "cashflow"]:
        lines.append(f"\n### {FEATURE_GROUP_LABELS[group]}\n\n")
        lines.append("| 字段名 | 中文名 | 方向 | 来源 | 计算口径 |\n|--------|--------|------|------|---------|\n")
        for f in by_group(group):
            lines.append(f"| `{f.key}` | {f.cn} | {'正向' if f.higher_better else '逆向'} | {f.source} | {f.note} |\n")

    lines.append("\n## 三、非财务维度（文本 / 治理 / 审计市场司法 / 宏观行业）\n")
    for group in ["text", "governance", "audit_market_legal", "macro_industry"]:
        lines.append(f"\n### {FEATURE_GROUP_LABELS[group]}\n\n")
        lines.append("| 字段名 | 中文名 | 方向 | 来源 | 计算口径 |\n|--------|--------|------|------|---------|\n")
        for f in by_group(group):
            lines.append(f"| `{f.key}` | {f.cn} | {'正向' if f.higher_better else '逆向'} | {f.source} | {f.note} |\n")

    lines.append("\n## 四、数据表结构\n")
    lines.append(
        "\n| 表 | 文件 | 主键 | 关键字段 |\n|----|------|------|---------|\n"
        "| 财务主表 | `data/raw/csmar_financial.csv` | stock_code + year | 30+ 报表科目（金额单位：亿元）|\n"
        "| 治理表 | `data/raw/csmar_governance.csv` | stock_code + year | top1_holding, board_size, independent_directors, duality, big4_audit |\n"
        "| 文本情感 | `data/raw/text_sentiment.csv` | stock_code + year | mdna_positive, mdna_negative, mdna_uncertainty, sentiment_polarity |\n"
        "| 市场特征 | `data/raw/market_features.csv` | stock_code + year | annual_turnover, stock_volatility |\n"
        "| 司法事件 | `data/raw/legal_events.csv` | stock_code + year | litigation_count, penalty_count |\n"
        "| ST 标签 | `data/raw/labels_st.csv` | stock_code + year | is_st |\n"
        "| 宏观指标 | `data/external/macro_industry.csv` | year | gdp_growth, m2_growth, cpi_yoy, ppi_yoy, social_financing_growth, pmi_manufacturing |\n"
    )
    lines.append(
        FOOTER.format(
            target=TARGET_COLUMN,
            horizon=settings.LABEL_HORIZON,
            train_start=settings.TRAIN_YEAR_RANGE[0],
            train_end=settings.TRAIN_YEAR_RANGE[1],
            valid=settings.VALID_YEAR,
            test=settings.TEST_YEAR,
        )
    )
    return "".join(lines)


def main() -> None:
    output = settings.DOCS_DIR / "数据字典与特征口径.md"
    output.write_text(build_markdown(), encoding="utf-8")
    print(f"已生成：{output}")


if __name__ == "__main__":
    main()
