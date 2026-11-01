"""DOCX extraction with python-docx: paragraphs, Word list numbering, tables, inline images."""
from __future__ import annotations

from typing import Callable

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .. import model
from . import structure

Progress = Callable[[float, str], None]


def _roman(n: int) -> str:
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
            (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def _fmt(n: int, fmt: str) -> str:
    if fmt == "upperLetter":
        return chr(64 + ((n - 1) % 26) + 1)
    if fmt == "lowerLetter":
        return chr(96 + ((n - 1) % 26) + 1)
    if fmt == "upperRoman":
        return _roman(n).upper()
    if fmt == "lowerRoman":
        return _roman(n)
    return str(n)


class Numbering:
    """Resolve Word automatic numbering so '1.' / 'A)' labels that Word renders are not lost."""

    def __init__(self, document):
        self.levels: dict[str, dict[int, dict]] = {}
        self.counters: dict[str, list[int]] = {}
        try:
            root = document.part.numbering_part.element
        except Exception:
            return
        abstract = {}
        for an in root.findall(qn("w:abstractNum")):
            lv = {}
            for l in an.findall(qn("w:lvl")):
                il = int(l.get(qn("w:ilvl")))
                fmt = l.find(qn("w:numFmt"))
                txt = l.find(qn("w:lvlText"))
                start = l.find(qn("w:start"))
                lv[il] = {"fmt": fmt.get(qn("w:val")) if fmt is not None else "decimal",
                          "text": txt.get(qn("w:val")) if txt is not None else "%1.",
                          "start": int(start.get(qn("w:val"))) if start is not None else 1}
            abstract[an.get(qn("w:abstractNumId"))] = lv
        for num in root.findall(qn("w:num")):
            aid = num.find(qn("w:abstractNumId"))
            if aid is not None:
                self.levels[num.get(qn("w:numId"))] = abstract.get(aid.get(qn("w:val")), {})

    def label(self, num_id: str, ilvl: int) -> str | None:
        lv = self.levels.get(num_id)
        if not lv or ilvl not in lv:
            return None
        spec = lv[ilvl]
        if spec["fmt"] == "bullet":
            return "•"
        if spec["fmt"] == "none":
            return None
        c = self.counters.setdefault(num_id, [0] * 9)
        if c[ilvl] == 0:
            c[ilvl] = spec["start"] - 1
        c[ilvl] += 1
        for deeper in range(ilvl + 1, 9):
            c[deeper] = 0
        text = spec["text"]
        for k in range(9):
            if f"%{k+1}" in text:
                kspec = lv.get(k, {"fmt": "decimal", "start": 1})
                val = c[k] if c[k] else kspec.get("start", 1)
                text = text.replace(f"%{k+1}", _fmt(val, kspec["fmt"]))
        return text


def _num_pr(p: Paragraph):
    pPr = p._p.pPr
    numPr = pPr.numPr if pPr is not None else None
    if numPr is None:
        try:
            st = p.style
            while st is not None and numPr is None:
                spPr = st.element.pPr
                numPr = spPr.numPr if spPr is not None else None
                st = st.base_style
        except Exception:
            numPr = None
    if numPr is None or numPr.numId is None:
        return None
    ilvl = numPr.ilvl.val if numPr.ilvl is not None else 0
    return str(numPr.numId.val), int(ilvl)


def _para_props(p: Paragraph, default_size: float):
    runs = [r for r in p.runs if r.text.strip()]
    size = None
    for r in runs:
        if r.font.size:
            size = r.font.size.pt
            break
    st = p.style
    while size is None and st is not None:
        if st.font is not None and st.font.size:
            size = st.font.size.pt
        st = st.base_style
    style_bold = False
    st = p.style
    while st is not None:
        if st.font is not None and st.font.bold is not None:
            style_bold = bool(st.font.bold)
            break
        st = st.base_style
    bold = bool(runs) and all((r.bold if r.bold is not None else style_bold) for r in runs)
    italic = bool(runs) and all(bool(r.italic) for r in runs)
    return size or default_size, bold, italic


def _images_in(element, document, save_image, page):
    out = []
    for blip in element.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        if not rid:
            continue
        part = document.part.related_parts.get(rid)
        if part is None:
            continue
        ext = part.partname.ext.lower()
        if ext in ("emf", "wmf"):
            continue  # vector metafiles: cannot be rendered offline; reported by caller
        a = save_image(part.blob, ext, {"source": "docx"})
        out.append({"kind": "image", "page": page, "bbox": None, "area_ratio": 0.2, **a})
    return out


def extract(path: str, save_image, progress: Progress | None = None) -> dict:
    progress = progress or (lambda f, m: None)
    document = docx.Document(path)
    numbering = Numbering(document)
    default_size = 11.0
    try:
        sz = document.styles["Normal"].font.size
        if sz:
            default_size = sz.pt
    except KeyError:
        pass
    body = list(document.element.body.iterchildren())
    items: list[dict] = []
    warnings: list[dict] = []
    skipped_vector = 0
    numbered_labels = 0
    for i, child in enumerate(body):
        if i % 20 == 0:
            progress(i / max(len(body), 1), f"Reading element {i + 1} of {len(body)}")
        if child.tag == qn("w:p"):
            p = Paragraph(child, document)
            text = p.text.replace("\t", "   ")
            size, bold, italic = _para_props(p, default_size)
            npr = _num_pr(p)
            label = numbering.label(*npr) if npr else None
            if text.strip() and label and label != "•":
                text = f"{label} {text}"
                numbered_labels += 1
            elif text.strip() and label == "•":
                text = f"• {text}"
            parts = text.split("\n")
            for j, part in enumerate(parts):
                if part.strip():
                    items.append({"kind": "line", "text": part, "size": size, "bold": bold, "italic": italic,
                                  "page": None, "bbox": None, "new_para": j == 0, "style": p.style.name if p.style else ""})
            imgs = _images_in(child, document, save_image, None)
            items.extend(imgs)
            if any(b.get(qn("r:embed")) for b in child.iter(qn("a:blip"))) and not imgs:
                skipped_vector += 1
            if child.find(".//" + qn("w:br")) is not None:
                for br in child.iter(qn("w:br")):
                    if br.get(qn("w:type")) == "page":
                        items.append({"kind": "page_break", "page": None})
        elif child.tag == qn("w:tbl"):
            t = Table(child, document)
            rows = []
            for r in t.rows:
                seen = set()
                row = []
                for c in r.cells:
                    key = id(c._tc)
                    row.append("" if key in seen else c.text.strip())
                    seen.add(key)
                rows.append(row)
                for c in r.cells:
                    items.extend(_images_in(c._tc, document, save_image, None))
            if rows:
                if max(len(r) for r in rows) == 1 and len(rows) == 1:
                    items.append({"kind": "line", "text": rows[0][0], "size": default_size, "bold": False,
                                  "page": None, "bbox": None, "new_para": True})
                else:
                    items.append({"kind": "table", "rows": rows, "header_rows": 1, "page": None, "bbox": None})
    progress(1.0, "Detecting document structure")
    blocks, info = structure.detect(items)
    if skipped_vector:
        warnings.append({"level": "warning", "code": "vector_image_skipped",
                         "message": f"{skipped_vector} EMF/WMF vector image(s) could not be converted offline. Re-save them as PNG in Word and re-import."})
    if numbered_labels:
        warnings.append({"level": "info", "code": "word_numbering",
                         "message": f"{numbered_labels} automatic Word list number(s) were reconstructed from the document's numbering definitions."})
    warnings.extend(structure.numbering_report(info["source_numbers"]))
    title = (document.core_properties.title or "").strip()
    raw_tokens = sum(len(it.get("text", "").split()) for it in items if it["kind"] == "line")
    raw_tokens += sum(len(" ".join(" ".join(r) for r in it["rows"]).split()) for it in items if it["kind"] == "table")
    section = document.sections[0] if document.sections else None
    orientation = "portrait"
    page_size = [595.28, 841.89]
    if section is not None and section.page_width and section.page_height:
        w, h = section.page_width.pt, section.page_height.pt
        page_size = [w, h]
        orientation = "landscape" if w > h else "portrait"
    return model.new_document(title=title, blocks=blocks, orientation=orientation, page_size=page_size,
                              warnings=warnings,
                              extraction={"raw_tokens": raw_tokens, "body_size": info["body_size"],
                                          "source_numbers": info["source_numbers"], "removed_furniture": []})
