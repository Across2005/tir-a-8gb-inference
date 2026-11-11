#!/usr/bin/env python3
"""Build paper.docx from paper.md using python-docx.

Supported markdown subset:
  # / ## / ### headings, paragraphs, - bullets, 1. lists, > quotes,
  ``` fenced code ```, | pipe tables |, ![alt](path) images,
  **bold**, `code`, --- rules, <!-- comments -->.

Word-specific: A4, Chinese fonts, TOC field, page numbers, figure captions.
Run: python build_docx.py [input.md] [output.docx]
"""
import os
import re
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = os.path.dirname(os.path.abspath(__file__))
BODY_FONT = "宋体"
HEAD_FONT = "黑体"
CODE_FONT = "Consolas"


def set_run_font(run, name, size=None, bold=None, color=None):
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)


def shade(paragraph, hex_fill="F2F2F2"):
    ppr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_fill)
    ppr.append(shd)


def add_field(paragraph, instr, placeholder=""):
    r = paragraph.add_run()
    fld = OxmlElement("w:fldChar")
    fld.set(qn("w:fldCharType"), "begin")
    r._r.append(fld)
    r2 = paragraph.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    r2._r.append(it)
    r3 = paragraph.add_run()
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    r3._r.append(sep)
    if placeholder:
        paragraph.add_run(placeholder)
    r4 = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    r4._r.append(end)


def prefer_update_fields(doc):
    settings = doc.settings.element
    upd = settings.find(qn("w:updateFields"))
    if upd is None:
        upd = OxmlElement("w:updateFields")
        settings.append(upd)
    upd.set(qn("w:val"), "true")


INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def add_inline(paragraph, text, size=10.5, font=BODY_FONT):
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            inner = part[2:-2]
            for sub in re.split(r"(`[^`]+`)", inner):
                if not sub:
                    continue
                if sub.startswith("`") and sub.endswith("`") and len(sub) > 2:
                    run = paragraph.add_run(sub[1:-1])
                    set_run_font(run, CODE_FONT, size - 0.5, bold=True)
                else:
                    run = paragraph.add_run(sub)
                    set_run_font(run, font, size, bold=True)
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            set_run_font(run, CODE_FONT, size - 0.5)
        else:
            run = paragraph.add_run(part)
            set_run_font(run, font, size)


def body_paragraph(doc, text, indent=True, size=10.5):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing = 1.5
    pf.space_after = Pt(3)
    if indent:
        pf.first_line_indent = Pt(size * 2)
    add_inline(p, text, size)
    return p


def heading(doc, level, text):
    sizes = {1: 18, 2: 14, 3: 12}
    p = doc.add_paragraph(style=f"Heading {level}")
    pf = p.paragraph_format
    if level == 1:
        pf.page_break_before = True
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf.space_before = Pt(6)
        pf.space_after = Pt(18)
    elif level == 2:
        pf.space_before = Pt(14)
        pf.space_after = Pt(8)
    else:
        pf.space_before = Pt(10)
        pf.space_after = Pt(6)
    run = p.add_run(text)
    set_run_font(run, HEAD_FONT, sizes[level], bold=True, color=(0x1F, 0x23, 0x28))
    return p


def add_table(doc, rows):
    if not rows:
        return
    ncol = max(len(r) for r in rows)
    table = doc.add_table(rows=0, cols=ncol)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    total = 15.4
    if ncol >= 7:
        widths = [2.0, 4.2] + [(total - 6.2) / (ncol - 2)] * (ncol - 2)
        fsize = 8
    elif ncol == 6:
        widths = [2.4, 3.6] + [(total - 6.0) / 4] * 4
        fsize = 8.5
    else:
        widths = [total / ncol] * ncol
        fsize = 9
    for i, row in enumerate(rows):
        cells = table.add_row().cells
        for j in range(ncol):
            txt = row[j] if j < len(row) else ""
            cells[j].width = Cm(widths[j])
            p = cells[j].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            add_inline(p, txt, fsize)
            if i == 0:
                for r in p.runs:
                    r.font.bold = True
                tcpr = cells[j]._tc.get_or_add_tcPr()
                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:fill"), "E8EEF4")
                tcpr.append(shd)
    if table.rows:
        trpr = table.rows[0]._tr.get_or_add_trPr()
        trpr.append(OxmlElement("w:tblHeader"))
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_image(doc, path, caption):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    run = p.add_run()
    run.add_picture(path, width=Cm(15.5))
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_after = Pt(10)
    r = cap.add_run(caption)
    set_run_font(r, BODY_FONT, 9, color=(0x5B, 0x65, 0x72))


def parse_table(lines, i):
    rows = []
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw = lines[i].strip().strip("|")
        cells = [c.strip() for c in raw.split("|")]
        if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            rows.append(cells)
        i += 1
    return rows, i


def setup_document(title):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    sec.left_margin = sec.right_margin = Cm(2.8)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    sec.different_first_page_header_footer = True

    # header
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hr = hp.add_run(title)
    set_run_font(hr, BODY_FONT, 9, color=(0x5B, 0x65, 0x72))

    # footer page number
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_field(fp, "PAGE", "1")
    for r in fp.runs:
        set_run_font(r, BODY_FONT, 9)

    prefer_update_fields(doc)
    return doc


def build(md_path, out_path):
    with open(md_path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    title = "TIR-A 阶段性技术研究论文"
    subtitle = ""
    for ln in lines:
        if ln.startswith("# "):
            title = ln[2:].strip()
            break

    doc = setup_document(title)

    main_title = title
    subtitle = "在 8 GiB 笔记本上把 llama.cpp 做成可用的 C ABI 引擎"
    if "：" in title:
        main_title, rest = title.split("：", 1)
        if rest.strip():
            subtitle = rest.strip()

    # title page
    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(main_title)
    set_run_font(r, HEAD_FONT, 22, bold=True)
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run(subtitle)
    set_run_font(r2, HEAD_FONT, 14, color=(0x2F, 0x6F, 0x9F))
    for _ in range(8):
        doc.add_paragraph()
    for txt in ("TIR-A 技术报告：8 GiB 笔记本上的 llama.cpp 引擎实践", "2026-11-11"):
        pp = doc.add_paragraph()
        pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rr = pp.add_run(txt)
        set_run_font(rr, BODY_FONT, 12)
    doc.add_page_break()

    i = 0
    in_code = False
    code_buf = []
    first_h1 = True
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            if not in_code:
                in_code = True
                code_buf = []
            else:
                in_code = False
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.5)
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(6)
                shade(p)
                run = p.add_run("\n".join(code_buf))
                set_run_font(run, CODE_FONT, 9)
            i += 1
            continue
        if in_code:
            code_buf.append(raw)
            i += 1
            continue

        if not stripped or stripped.startswith("<!--"):
            i += 1
            continue
        if stripped == "---":
            i += 1
            continue

        m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1 and first_h1:
                first_h1 = False
                i += 1
                continue
            if level == 1:
                doc.add_page_break()
            heading(doc, level, text)
            i += 1
            continue

        if stripped == "[TOC]":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_field(p, 'TOC \\o "1-3" \\h \\z \\u', "右键更新目录")
            for r in p.runs:
                set_run_font(r, BODY_FONT, 10.5)
            i += 1
            continue

        if stripped.startswith("|"):
            rows, i = parse_table(lines, i)
            add_table(doc, rows)
            continue

        mi = re.match(r"^!\[(.*?)\]\((.*?)\)$", stripped)
        if mi:
            caption, path = mi.group(1), mi.group(2)
            full = path if os.path.isabs(path) else os.path.join(HERE, path)
            if os.path.exists(full):
                add_image(doc, full, caption)
            else:
                body_paragraph(doc, f"[缺图: {path}]")
            i += 1
            continue

        if stripped.startswith(">"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.8)
            add_inline(p, stripped.lstrip("> "), 10)
            for r in p.runs:
                r.font.italic = True
                r.font.color.rgb = RGBColor(0x5B, 0x65, 0x72)
            i += 1
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.line_spacing = 1.5
            p.paragraph_format.space_after = Pt(2)
            add_inline(p, stripped[2:], 10.5)
            i += 1
            continue

        mo = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if mo:
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.line_spacing = 1.5
            pf.space_after = Pt(2)
            pf.left_indent = Cm(0.75)
            pf.first_line_indent = Cm(-0.75)
            add_inline(p, stripped, 10.5)
            i += 1
            continue

        body_paragraph(doc, stripped)
        i += 1

    doc.save(out_path)
    print("wrote", out_path, os.path.getsize(out_path))
    print("paragraphs", len(doc.paragraphs), "tables", len(doc.tables),
          "inline_shapes", len(doc.inline_shapes))


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "paper.md")
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "paper.docx")
    build(src, dst)
