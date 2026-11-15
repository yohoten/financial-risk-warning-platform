"""论文 DOCX 后处理：按《毕业设计模板及格式要求》定制版式。

规格（参照 docs/附件3：毕业设计模板/毕业设计模板及格式要求.docx）：
- 页面：A4；页边距 上/下 2.5cm、左 3.0cm、右 2.5cm
- 正文：宋体 + Times New Roman 小四（12pt），1.5 倍行距，两端对齐
- 一级标题：黑体三号（16pt）居中；二级/三级标题：黑体小四（12pt）
- 标题均黑色、不加粗（黑体本身已足够醒目）
- 表格：三线表（顶线/底线 1.5pt，表头下栏目线 0.75pt，无竖线、无内横线）

用法：python scripts/postprocess_docx.py docs/论文_全文.docx
在 pandoc 生成 docx 之后调用；幂等，原地覆盖。
"""

from __future__ import annotations

import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.text.paragraph import Paragraph


def _set_style_font(style, latin: str, east: str, size_pt: float | None = None,
                    bold: bool | None = None, color_hex: str | None = None) -> None:
    style.font.name = latin
    if size_pt is not None:
        style.font.size = Pt(size_pt)
    if bold is not None:
        style.font.bold = bold
    if color_hex is not None:
        style.font.color.rgb = RGBColor.from_string(color_hex)

    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), east)


def _set_style_para(style, line_spacing: float | None = None,
                    align: WD_ALIGN_PARAGRAPH | None = None,
                    before_pt: float | None = None, after_pt: float | None = None) -> None:
    pf = style.paragraph_format
    if line_spacing is not None:
        pf.line_spacing = line_spacing
    if align is not None:
        pf.alignment = align
    if before_pt is not None:
        pf.space_before = Pt(before_pt)
    if after_pt is not None:
        pf.space_after = Pt(after_pt)


# ---------------------------------------------------------------------------
# 三线表：顶线/底线（1.5pt）+ 表头下栏目线（0.75pt），无竖线、无内横线
# ---------------------------------------------------------------------------
def _set_border(el, edge: str, val: str = "single", sz: int = 8) -> None:
    tag = qn("w:" + edge)
    b = el.find(tag)
    if b is None:
        b = OxmlElement("w:" + edge)
        el.append(b)
    b.set(qn("w:val"), val)
    if val == "none":
        for attr in ("w:sz", "w:color", "w:space"):
            b.attrib.pop(qn(attr), None)
    else:
        b.set(qn("w:sz"), str(sz))
        b.set(qn("w:color"), "000000")
        b.set(qn("w:space"), "0")


def _insert_tblpr_child(tblPr, element) -> None:
    after = {"w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook",
             "w:tblCaption", "w:tblDescription"}
    for child in tblPr:
        if child.tag in after:
            child.addprevious(element)
            return
    tblPr.append(element)


def _insert_tcpr_child(tcPr, element) -> None:
    after = {"w:shd", "w:noWrap", "w:tcMar", "w:textDirection",
             "w:tcFitText", "w:vAlign", "w:hideMark"}
    for child in tcPr:
        if child.tag in after:
            child.addprevious(element)
            return
    tcPr.append(element)


def _three_line_table(table) -> None:
    tblPr = table._tbl.tblPr

    borders = tblPr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        _insert_tblpr_child(tblPr, borders)
    for child in list(borders):
        borders.remove(child)

    _set_border(borders, "top", "single", 12)
    _set_border(borders, "bottom", "single", 12)
    for edge in ("left", "right", "insideH", "insideV"):
        _set_border(borders, edge, "none")

    if table.rows:
        for cell in table.rows[0].cells:
            tcPr = cell._tc.get_or_add_tcPr()
            tcB = tcPr.find(qn("w:tcBorders"))
            if tcB is None:
                tcB = OxmlElement("w:tcBorders")
                _insert_tcpr_child(tcPr, tcB)
            _set_border(tcB, "bottom", "single", 6)


def _fix_toc_heading(doc: Document) -> None:
    """把 pandoc 生成的英文 TOC 标题改为中文「目　录」并居中。

    pandoc 将目录包裹在 w:sdt 结构化块里，普通 doc.paragraphs 遍历不到，
    需直接遍历 body 下的 w:sdt；同时清掉标题中重复的文本 run。
    """
    body = doc.element.body
    for sdt in body.findall(qn("w:sdt")):
        for p in sdt.iter(qn("w:p")):
            ppr = p.find(qn("w:pPr"))
            style_el = ppr.find(qn("w:pStyle")) if ppr is not None else None
            if style_el is None or style_el.get(qn("w:val")) != "TOCHeading":
                continue

            runs = p.findall(qn("w:r"))
            text_nodes = [t for r in runs for t in r.findall(qn("w:t"))]
            if text_nodes:
                text_nodes[0].text = "目　录"
                text_nodes[0].set(qn("xml:space"), "preserve")
                for t in text_nodes[1:]:
                    t.text = ""
            # 标题字体：黑体三号
            if runs:
                rpr = runs[0].find(qn("w:rPr"))
                if rpr is None:
                    rpr = OxmlElement("w:rPr")
                    runs[0].insert(0, rpr)
                rfonts = rpr.find(qn("w:rFonts"))
                if rfonts is None:
                    rfonts = OxmlElement("w:rFonts")
                    rpr.append(rfonts)
                rfonts.set(qn("w:eastAsia"), "黑体")
                sz = rpr.find(qn("w:sz"))
                if sz is None:
                    sz = OxmlElement("w:sz")
                    rpr.append(sz)
                sz.set(qn("w:val"), "32")  # 16pt

            para = Paragraph(p, None)
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER


def main(path: str) -> None:
    doc = Document(path)

    for section in doc.sections:
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(3.0)
        section.right_margin = Cm(2.5)

    styles = doc.styles
    # 正文
    _set_style_font(styles["Normal"], "Times New Roman", "宋体", size_pt=12)
    _set_style_para(styles["Normal"], line_spacing=1.5,
                    align=WD_ALIGN_PARAGRAPH.JUSTIFY, before_pt=0, after_pt=0)
    # 论文标题
    _set_style_font(styles["Title"], "Times New Roman", "黑体", size_pt=18, bold=True, color_hex="000000")
    _set_style_para(styles["Title"], line_spacing=1.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    # 一级标题（章）：黑体三号居中
    _set_style_font(styles["Heading 1"], "Times New Roman", "黑体", size_pt=16, bold=False, color_hex="000000")
    _set_style_para(styles["Heading 1"], line_spacing=1.5, align=WD_ALIGN_PARAGRAPH.CENTER,
                    before_pt=12, after_pt=12)
    # 二级标题（节）：黑体小四
    _set_style_font(styles["Heading 2"], "Times New Roman", "黑体", size_pt=12, bold=False, color_hex="000000")
    _set_style_para(styles["Heading 2"], line_spacing=1.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                    before_pt=6, after_pt=6)
    # 三级标题：黑体小四
    _set_style_font(styles["Heading 3"], "Times New Roman", "黑体", size_pt=12, bold=False, color_hex="000000")
    _set_style_para(styles["Heading 3"], line_spacing=1.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                    before_pt=6, after_pt=6)
    _set_style_font(styles["Heading 4"], "Times New Roman", "黑体", size_pt=12, bold=False, color_hex="000000")
    _set_style_para(styles["Heading 4"], line_spacing=1.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    _fix_toc_heading(doc)

    # 正文（第 1 章）从新页开始，与目录分离
    for p in doc.paragraphs:
        if p.style.name == "Heading 1":
            p.paragraph_format.page_break_before = True
            break

    for table in doc.tables:
        _three_line_table(table)

    doc.save(path)
    print(f"OK 已按模板后处理：{path}（三线表 {len(doc.tables)} 个）")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python scripts/postprocess_docx.py <docx路径>")
    main(sys.argv[1])
