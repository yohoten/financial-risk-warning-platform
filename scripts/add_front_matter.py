"""给论文 docx 添加封面、原创性声明、中英文摘要页（参照《毕业设计模板及格式要求》）。

用法：python scripts/add_front_matter.py docs/论文_全文.docx
在 postprocess_docx.py 之后调用；幂等（若已有封面则跳过），原地覆盖。
"""

from __future__ import annotations

import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

COVER_TITLE = "基于 XGBoost 与 TreeSHAP 的上市公司财务风险预警系统"
DECLARATION_1 = ("本人郑重声明：所呈交的毕业设计是本人在导师的指导下独立进行的研究工作及取得的"
                 "研究成果。除文中已经注明引用的内容外，本设计不包含其他个人或集体已经发表或"
                 "撰写过的研究成果。对本文的研究做出贡献的个人和集体，均已在文中作了明确的说明"
                 "并表示谢意。")
DECLARATION_2 = "如本人的毕业设计涉及抄袭或剽窃等行为，本人愿承担由此造成的一切责任及后果。"

ABSTRACT_ZH = ("财务风险的及时识别与预警对资本市场风险防控具有重要意义。针对传统预警模型可解释性不足、"
              "多源信息融合不充分等问题，本文以沪深 A 股制造业上市公司为研究对象，构建覆盖偿债能力、"
              "盈利能力、营运能力、成长能力、现金流、文本情感、公司治理、审计市场司法、宏观行业与"
              "数字化转型十个维度共 80 维候选特征，经信息价值、相关性/多重共线性、群体稳定性与特征"
              "重要性四步筛选得到 36 维建模特征。以 XGBoost 为主模型，采用按年分组扩展窗口交叉验证"
              "进行超参数搜索与概率校准，并按成本敏感原则确定预警阈值，以 Logistic 回归、随机森林、"
              "LightGBM 与 CatBoost 为对照。主模型在 2023 年留出测试集上 AUC 为 0.8962、PR-AUC 为 "
              "0.3986、Recall@Top10% 为 66.93%、校准后 ECE 为 0.0126。基于 TreeSHAP 的解释分析可从"
              "全局重要性、个体归因、依赖效应与交互效应四个维度揭示风险来源。最后，本文设计并实现了"
              "Streamlit 与 Vue 3 双前端、FastAPI 服务层的交互式预警平台，验证了方法的工程化可行性。")
KEYWORDS_ZH = "财务风险预警；XGBoost；TreeSHAP；特征工程；上市公司"

ABSTRACT_EN = ("Timely identification and early warning of financial risk are of great significance to capital "
               "market risk prevention and control. Targeting the insufficient interpretability and inadequate "
               "fusion of multi-source information in traditional warning models, this thesis takes listed "
               "manufacturing companies in China's A-share market as research objects and constructs 80 candidate "
               "features across ten dimensions, including solvency, profitability, operation, growth, cash flow, "
               "textual sentiment, corporate governance, audit/market/legal, macro/industry and digital "
               "transformation. After a four-step selection based on information value, correlation and "
               "multicollinearity, population stability and feature importance, 36 features are retained for "
               "modeling. XGBoost is adopted as the primary model, with hyperparameter search and probability "
               "calibration performed via grouped expanding-window cross-validation, and the warning threshold "
               "determined by a cost-sensitive criterion; logistic regression, random forest, LightGBM and CatBoost "
               "serve as baselines. The primary model achieves an AUC of 0.8962, PR-AUC of 0.3986, Recall@Top10% "
               "of 66.93% and a calibrated ECE of 0.0126 on the 2023 hold-out test set. TreeSHAP-based analysis "
               "reveals risk sources from global importance, individual attribution, dependence and interaction "
               "effects. Finally, an interactive early-warning platform with dual frontends (Streamlit and Vue 3) "
               "and a FastAPI service layer is designed and implemented, demonstrating the feasibility of "
               "engineering deployment.")
KEYWORDS_EN = "financial risk early warning; XGBoost; TreeSHAP; feature engineering; listed companies"

INFO_LINES = [
    ("学　　院：", "＿＿＿＿＿＿＿＿＿＿"),
    ("专业班级：", "＿＿＿＿＿＿＿＿＿＿"),
    ("层　　次：", "本　　科"),
    ("学生姓名：", "＿＿＿＿＿＿＿＿＿＿"),
    ("学生学号：", "＿＿＿＿＿＿＿＿＿＿"),
    ("指导教师：", "＿＿＿＿＿＿＿＿＿＿"),
    ("企业导师：", "＿＿＿＿＿＿＿＿＿＿"),
    ("完成时间：", "＿＿＿＿年＿＿月"),
]


def _style_run(run, text: str, east: str = "宋体", size: float = 12,
               bold: bool = False, underline: bool = False) -> None:
    run.text = text
    run.font.name = "Times New Roman"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.underline = underline
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), east)


def _new_para(anchor, style=None, align=WD_ALIGN_PARAGRAPH.LEFT, line: float = 1.5,
              before: float = 0, after: float = 0, left_indent_cm: float | None = None,
              first_indent_pt: float | None = None):
    p = anchor.insert_paragraph_before(style=style)
    p.alignment = align
    p.paragraph_format.line_spacing = line
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    if left_indent_cm is not None:
        p.paragraph_format.left_indent = Cm(left_indent_cm)
    if first_indent_pt is not None:
        p.paragraph_format.first_line_indent = Pt(first_indent_pt)
    return p


def main(path: str) -> None:
    doc = Document(path)
    body = doc.element.body

    # 幂等：已存在"毕 业 设 计"则跳过
    for p in doc.paragraphs:
        if "毕 业 设 计" in p.text:
            print("已存在封面，跳过。")
            return

    first = doc.paragraphs[0]  # pandoc 生成的标题段落，将由封面标题取代

    # 注意：insert_paragraph_before 每次插到 anchor 之前，逆序插入才能保持正序
    specs = []

    def spec(align=WD_ALIGN_PARAGRAPH.LEFT, line=1.5, before=0, after=0,
             left_indent_cm=None, first_indent_pt=None, runs=None, page_break=False,
             style=None):
        specs.append(dict(align=align, line=line, before=before, after=after,
                          left_indent_cm=left_indent_cm, first_indent_pt=first_indent_pt,
                          runs=runs or [], page_break=page_break, style=style))

    # ---------- 封面 ----------
    for _ in range(5):
        spec(runs=[])
    spec(align=WD_ALIGN_PARAGRAPH.CENTER, after=24,
         runs=[("毕 业 设 计", dict(east="黑体", size=36))])
    spec(align=WD_ALIGN_PARAGRAPH.CENTER, after=60,
         runs=[(COVER_TITLE, dict(east="黑体", size=22))])
    for _ in range(2):
        spec(runs=[])
    for label, value in INFO_LINES:
        spec(align=WD_ALIGN_PARAGRAPH.LEFT, line=2.0, left_indent_cm=5.0,
             runs=[(label, dict(size=14)),
                   (value, dict(size=14, underline=True))])
    for _ in range(2):
        spec(runs=[])
    spec(runs=[], page_break=True)

    # ---------- 原创性声明 ----------
    spec(align=WD_ALIGN_PARAGRAPH.CENTER, after=12,
         runs=[("毕业设计原创性声明", dict(east="黑体", size=16))])
    spec(runs=[])
    spec(align=WD_ALIGN_PARAGRAPH.JUSTIFY, line=1.5, first_indent_pt=24,
         runs=[(DECLARATION_1, dict(size=12))])
    spec(align=WD_ALIGN_PARAGRAPH.JUSTIFY, line=1.5, first_indent_pt=24,
         runs=[(DECLARATION_2, dict(size=12))])
    spec(runs=[])
    spec(align=WD_ALIGN_PARAGRAPH.LEFT, line=1.5, before=24,
         runs=[("毕业设计作者签名：", dict(size=12)),
               ("＿＿＿＿＿＿＿＿", dict(size=12, underline=True)),
               ("　　日期：", dict(size=12)),
               ("＿＿＿＿年＿＿月＿＿日", dict(size=12, underline=True))])
    spec(runs=[], page_break=True)

    # ---------- 摘 要 ----------
    spec(style="Heading 1", align=WD_ALIGN_PARAGRAPH.CENTER, after=12,
         runs=[("摘　要", None)])
    spec(runs=[])
    spec(align=WD_ALIGN_PARAGRAPH.JUSTIFY, line=1.5, first_indent_pt=24,
         runs=[(ABSTRACT_ZH, dict(size=12))])
    spec(runs=[])
    spec(align=WD_ALIGN_PARAGRAPH.JUSTIFY, line=1.5,
         runs=[("关键词：", dict(size=12, bold=True)),
               (KEYWORDS_ZH, dict(size=12))])
    spec(runs=[], page_break=True)

    # ---------- Abstract ----------
    spec(style="Heading 1", align=WD_ALIGN_PARAGRAPH.CENTER, after=12,
         runs=[("Abstract", None)])
    spec(runs=[])
    spec(align=WD_ALIGN_PARAGRAPH.JUSTIFY, line=1.5, first_indent_pt=24,
         runs=[(ABSTRACT_EN, dict(size=12))])
    spec(runs=[])
    spec(align=WD_ALIGN_PARAGRAPH.JUSTIFY, line=1.5,
         runs=[("Key words: ", dict(size=12, bold=True)),
               (KEYWORDS_EN, dict(size=12))])
    spec(runs=[], page_break=True)

    anchor = first
    for s in reversed(specs):
        p = _new_para(anchor, style=s["style"], align=s["align"], line=s["line"],
                      before=s["before"], after=s["after"],
                      left_indent_cm=s["left_indent_cm"],
                      first_indent_pt=s["first_indent_pt"])
        anchor = p
        for text, fmt in s["runs"]:
            run = p.add_run(text)
            if fmt:
                _style_run(run, text, **fmt)
        if s["page_break"]:
            br_run = p.add_run()
            br_run.add_break(WD_BREAK.PAGE)

    # 删除原 pandoc 标题段落（封面已承载标题）
    first._element.getparent().remove(first._element)

    doc.save(path)
    print(f"OK 已添加封面、声明与摘要：{path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python scripts/add_front_matter.py <docx路径>")
    main(sys.argv[1])
