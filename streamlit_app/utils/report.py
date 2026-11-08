"""报告导出：单企业 PDF 诊断报告 + 批量 Excel 预警清单。

设计取舍
--------
PDF 使用 ReportLab 内置的 `STSong-Light` CID 字体，**无需携带字体文件**即可
正确渲染中文，保证容器化部署与答辩现场不出现方块字。
图表不内嵌位图（避免 kaleido/wkhtmltopdf 等重型依赖），改用结构化表格呈现，
保证任何环境都能一键导出。
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pandas as pd

from config import settings


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _pdf_styles():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font = "STSong-Light"
    except Exception:
        font = "Helvetica"

    return {
        "title": ParagraphStyle("title", fontName=font, fontSize=20, leading=28, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName=font, fontSize=13, leading=20, spaceBefore=12, spaceAfter=6),
        "body": ParagraphStyle("body", fontName=font, fontSize=9.5, leading=16),
        "small": ParagraphStyle("small", fontName=font, fontSize=8, leading=12, textColor="#666666"),
    }, font


def risk_report_pdf(
    company: dict,
    scores: pd.DataFrame,
    contributions: pd.DataFrame,
    history: pd.DataFrame,
) -> bytes:
    """生成单企业风险诊断 PDF，返回字节流。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles, font = _pdf_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
        title=f"{company.get('company_name', '')} 财务风险诊断报告",
    )

    def table(data, col_widths=None, header_bg="#1f77b4"):
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d7de")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return t

    level = company.get("risk_level", "-")
    story = [
        Paragraph("上市公司财务风险诊断报告", styles["title"]),
        Paragraph(
            f"{company.get('company_name', '')}（{company.get('stock_code', '')}） · "
            f"{company.get('industry', '')} · 数据年度 {company.get('year', '')}",
            styles["body"],
        ),
        Paragraph(f"报告生成时间：{time.strftime('%Y-%m-%d %H:%M')}", styles["small"]),
        Spacer(1, 8),
        Paragraph("一、风险概览", styles["h2"]),
        table(
            [
                ["指标", "取值", "说明"],
                ["风险等级", level, "基于 ST 概率分级（高≥50%，中≥25%）"],
                ["ST 概率", f"{company.get('st_prob', 0):.2%}", "模型预测未来 ST 的可能性"],
                ["样本分位", f"{company.get('risk_percentile', 0):.1%}", "在全样本中的风险排名分位"],
                ["同行业排名", f"{company.get('peer_rank', '-')}/{company.get('peer_count', '-')}", "同行业同期企业中的风险位次"],
                ["行业平均概率", f"{company.get('peer_avg_prob', 0):.2%}", "用于横向对标"],
            ],
            col_widths=[32 * mm, 32 * mm, 96 * mm],
        ),
        Paragraph("二、六维健康度（0-100，越高越健康）", styles["h2"]),
        table(
            [["维度", "健康度"]] + [[r["维度"], f"{r['健康度']:.1f}"] for _, r in scores.iterrows()],
            col_widths=[60 * mm, 40 * mm],
        ),
        Paragraph("三、关键风险因子归因（SHAP）", styles["h2"]),
        table(
            [["因子", "取值", "SHAP 贡献", "方向"]]
            + [
                [r["中文名"], f"{r['取值']:.3f}", f"{r['SHAP值']:+.4f}", r["方向"]]
                for _, r in contributions.head(10).iterrows()
            ],
            col_widths=[56 * mm, 28 * mm, 30 * mm, 26 * mm],
        ),
        Paragraph("四、历史风险轨迹", styles["h2"]),
        table(
            [["年度", "ST 概率", "风险等级"]]
            + [[int(r["year"]), f"{r['st_prob']:.2%}", r["risk_level"]] for _, r in history.tail(8).iterrows()],
            col_widths=[30 * mm, 40 * mm, 36 * mm],
        ),
        Spacer(1, 10),
        Paragraph("五、方法论与免责声明", styles["h2"]),
        Paragraph(
            "模型：XGBoost 二分类，标签为 T 年被实施 ST/*ST，特征取自 T-2 年以避免前视偏差；"
            "可解释性：TreeSHAP，贡献值单位为 log-odds，正值表示推高风险。"
            "本报告由学术研究平台自动生成，不构成投资建议或信用评级意见。",
            styles["body"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def batch_excel(df: pd.DataFrame, sheet_name: str = "批量预警清单") -> bytes:
    """导出 Excel；openpyxl 缺失时降级为 CSV（UTF-8-SIG，Excel 可直接打开）。"""
    export = df.copy()
    buffer = io.BytesIO()
    try:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            export.to_excel(writer, index=False, sheet_name=sheet_name[:31])
            if {"risk_level", "st_prob"}.issubset(export.columns):
                agg = {"企业数": ("risk_level", "size"), "平均概率": ("st_prob", "mean")}
                summary = export.groupby("risk_level").agg(**agg).reset_index()
                summary.to_excel(writer, index=False, sheet_name="汇总")
        return buffer.getvalue()
    except Exception:
        return export.to_csv(index=False).encode("utf-8-sig")


def save_report(content: bytes, filename: str) -> Path:
    """把导出内容保存到 reports/ 并返回路径（供下载后留档）。"""
    settings.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.REPORT_DIR / filename
    path.write_bytes(content)
    return path


def evaluation_markdown() -> str:
    """读取已生成的评估报告 Markdown。"""
    if settings.EVAL_REPORT.exists():
        return settings.EVAL_REPORT.read_text(encoding="utf-8")
    return "评估报告尚未生成，请先运行 `python -m models.evaluate`。"
