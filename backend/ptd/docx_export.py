"""Write a document model to an editable DOCX (Convert to Editable Document)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt

from . import model as M


def export_docx(doc_model: dict, out: Path, resolve_asset: Callable[[str], Path | None]) -> Path:
    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Mm(18))
    sec.top_margin, sec.bottom_margin = Mm(18), Mm(18)
    normal = d.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)
    width_mm = 174
    if doc_model.get("title"):
        d.add_heading(doc_model["title"], level=0)

    def picture(spec: dict, max_mm: float = width_mm):
        p = resolve_asset(spec.get("asset")) if spec.get("asset") else None
        if p and Path(p).exists() and Path(p).suffix.lower() != ".svg":
            w = spec.get("width") or 800
            d.add_picture(str(p), width=Mm(min(max_mm, max(30, w / 300 * 25.4 * 2))))
            d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    for b in M.iter_blocks(doc_model):
        t = b["type"]
        if t == "section":
            d.add_heading(b.get("title", ""), level=1)
        elif t == "heading":
            d.add_heading(b.get("text", ""), level=min(3, max(1, int(b.get("level") or 2))))
        elif t == "instruction":
            p = d.add_paragraph()
            p.add_run(b.get("text", "")).italic = True
        elif t == "paragraph":
            d.add_paragraph(b.get("text", ""))
        elif t == "question":
            p = d.add_paragraph()
            if b.get("number"):
                p.add_run(f"{b['number']}. ").bold = True
            p.add_run(b.get("text", ""))
            for o in b.get("options") or []:
                op = d.add_paragraph(f"{o.get('label', '')}) {o.get('text', '')}")
                op.paragraph_format.left_indent = Mm(8)
            for im in b.get("images") or []:
                picture(im, 120)
            for _ in range(int(b.get("answer_lines") or 0)):
                d.add_paragraph("_" * 80)
        elif t == "table":
            rows = b.get("rows") or []
            if rows:
                ncol = max(len(r) for r in rows)
                tb = d.add_table(rows=len(rows), cols=ncol)
                tb.style = "Table Grid"
                for i, r in enumerate(rows):
                    for j in range(ncol):
                        cell = tb.cell(i, j)
                        cell.text = str(r[j]) if j < len(r) else ""
                        if i < int(b.get("header_rows", 1) or 0):
                            for run in cell.paragraphs[0].runs:
                                run.bold = True
                d.add_paragraph()
        elif t == "image":
            picture(b)
            if b.get("caption"):
                c = d.add_paragraph(b["caption"])
                c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif t == "answer_space":
            for _ in range(int(b.get("lines") or 3)):
                d.add_paragraph("_" * 80)
        elif t == "page_break":
            d.add_page_break()
    d.core_properties.title = doc_model.get("title") or ""
    d.save(str(out))
    return out
