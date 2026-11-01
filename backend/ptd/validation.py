"""Quality control: compares source -> extracted model -> generated PDF.

Two independent integrity checks:
  1. extraction integrity: every word of the original file is present in the document model
  2. render integrity:     every word of every block is present in the generated PDF, in order

plus layout checks (overflow, page boundaries, blank pages, orphaned headings, split questions,
broken tables, page numbers, fonts, images). Each issue: {level, code, message, block?, page?}.
Levels: critical | warning | info. A report only passes when there are no critical issues.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf

from . import model as M
from .util import norm_tokens

LEVELS = ("critical", "warning", "info")


def source_tokens(path: Path, kind: str) -> list[str] | None:
    """Raw word tokens of the original file, or None when not text-extractable (scans, images)."""
    try:
        if kind == "pdf":
            d = pymupdf.open(path)
            toks = []
            for p in d:
                toks += norm_tokens(p.get_text("text"))
            d.close()
            return toks or None
        if kind == "docx":
            import docx
            doc = docx.Document(str(path))
            toks = []
            for p in doc.paragraphs:
                toks += norm_tokens(p.text)
            for t in doc.tables:
                seen = set()
                for r in t.rows:
                    for c in r.cells:
                        if id(c._tc) in seen:
                            continue
                        seen.add(id(c._tc))
                        toks += norm_tokens(c.text)
            return toks
        if kind == "txt":
            from .importers.simple_import import _decode
            return norm_tokens(_decode(Path(path).read_bytes()))
    except Exception:
        return None
    return None


def check_extraction(doc_model: dict, src_tokens: list[str] | None) -> list[dict]:
    issues = []
    meta = doc_model.get("meta", {})
    if meta.get("scanned_pages"):
        conf = (meta.get("extraction") or {}).get("ocr_confidence")
        issues.append({"level": "warning", "code": "scanned_source",
                       "message": f"The source contains scanned page(s) {meta['scanned_pages'][:10]}. "
                                  + (f"OCR confidence {conf:.0%}. " if conf else "")
                                  + "Text from scans cannot be guaranteed to be perfect - please proofread."})
    if not src_tokens:
        return issues
    have = Counter(M.content_tokens(doc_model))
    for b in doc_model.get("blocks", []):
        for im in ([b] if b["type"] == "image" else b.get("images") or []):
            have.update(norm_tokens(im.get("embedded_text") or ""))
    for r in (meta.get("extraction") or {}).get("removed_furniture") or []:
        have.update(norm_tokens(r["text"]))
    for b in doc_model.get("blocks", []):
        # numbers and option labels are kept as structure (re-rendered by the template)
        if b["type"] == "question":
            have.update(norm_tokens(str(b.get("number") or "")))
            for o in b.get("options") or []:
                have.update(norm_tokens(o.get("label", "")))
        for row in b.get("repeated_header_dropped") or []:
            for cell in row:
                have.update(norm_tokens(cell))
    src = Counter(src_tokens)
    missing = src - have
    n_missing = sum(missing.values())
    total = sum(src.values()) or 1
    if n_missing:
        sample = ", ".join(f"'{w}'" for w, _ in missing.most_common(8))
        ratio = n_missing / total
        level = "critical" if ratio > 0.01 else "warning"
        issues.append({"level": level, "code": "extraction_incomplete",
                       "message": f"{n_missing} of {total} words of the original ({ratio:.1%}) were not found in the extracted content "
                                  f"(e.g. {sample}). Please compare with the original before printing."})
    return issues


def _pdf_text_tokens(pdf: pymupdf.Document) -> tuple[list[str], list[list[str]]]:
    all_t, per_page = [], []
    for p in pdf:
        t = norm_tokens(p.get_text("text"))
        per_page.append(t)
        all_t += t
    return all_t, per_page


def check_render(doc_model: dict, render, template: dict, include: set | None = None) -> tuple[list[dict], list[dict]]:
    """Returns (issues, suggested_repairs[{block, repair}])."""
    issues: list[dict] = []
    repairs: list[dict] = []
    pdf = pymupdf.open(render.path)
    W, H = render.page_size
    out_tokens, per_page = _pdf_text_tokens(pdf)
    out = Counter(out_tokens)
    blocks = [b for b in doc_model.get("blocks", []) if include is None or b["id"] in include]

    # ---- 1. missing content (per block, so the user can navigate to it)
    missing_blocks = 0
    for b in blocks:
        need = Counter()
        for s in M.block_texts(b):
            need.update(norm_tokens(s))
        miss = need - out
        if miss:
            missing_blocks += 1
            label = f"Question {b.get('number')}" if b["type"] == "question" else b["type"].capitalize()
            issues.append({"level": "critical", "code": "missing_content", "block": b["id"],
                           "message": f"{label}: {sum(miss.values())} word(s) missing from the PDF "
                                      f"({', '.join(list(miss)[:5])})."})
        if b["type"] == "question":
            for o in b.get("options") or []:
                if Counter(norm_tokens(o.get("text", ""))) - out:
                    issues.append({"level": "critical", "code": "missing_option", "block": b["id"],
                                   "message": f"Question {b.get('number')}: option {o.get('label')} is missing from the PDF."})

    # ---- 2. question order
    hay = " " + " ".join(out_tokens) + " "
    pos = 0
    for q in [b for b in blocks if b["type"] == "question"]:
        toks = norm_tokens(q.get("text", ""))[:10]
        if len(toks) < 2:
            continue
        needle = " " + " ".join(toks) + " "
        i = hay.find(needle, pos)
        if i < 0:
            if hay.find(needle) >= 0:
                issues.append({"level": "critical", "code": "question_order", "block": q["id"],
                               "message": f"Question {q.get('number')} appears out of order in the PDF."})
            continue
        pos = i + 1

    # ---- 3. numbering
    qs = [b for b in blocks if b["type"] == "question"]
    nums = [q.get("number") for q in qs]
    if template["questions"]["numbering"] == "auto":
        expect = [str(i + 1) for i in range(len(qs))]
        if nums != expect:
            issues.append({"level": "critical", "code": "numbering", "message": "Automatic numbering is not sequential."})
    else:
        src = (doc_model.get("meta", {}).get("extraction") or {}).get("source_numbers")
        manual = [q.get("number") for q in qs if q.get("number_mode") == "manual"]
        if src and include is None and len(src) == len(manual) and manual != src:
            issues.append({"level": "warning", "code": "numbering_changed",
                           "message": "Question numbers differ from the original document (they were edited)."})
    if any(not n for n in nums):
        issues.append({"level": "warning", "code": "numbering_missing",
                       "message": f"{sum(1 for n in nums if not n)} question(s) have no number. Use automatic numbering to fill them."})

    # ---- 4. images
    for b in blocks:
        expected = (1 if b["type"] == "image" else 0) + len(b.get("images") or [])
        if expected and render.images_drawn.get(b["id"], 0) < expected:
            issues.append({"level": "critical", "code": "missing_image", "block": b["id"],
                           "message": f"{expected - render.images_drawn.get(b['id'], 0)} image(s) of this block were not placed in the PDF."})

    # ---- 5. geometry: content outside the page / printable area
    mg = template["page"]["margins_mm"]
    k = 72 / 25.4
    left, right, top, bottom = mg["left"] * k, W - mg["right"] * k, mg["top"] * k, H - mg["bottom"] * k
    for bid, rects in render.positions.items():
        for r in rects:
            if r["x0"] < -0.5 or r["y0"] < -0.5 or r["x1"] > W + 0.5 or r["y1"] > H + 0.5:
                issues.append({"level": "critical", "code": "outside_page", "block": bid, "page": r["page"],
                               "message": f"Content extends beyond the edge of page {r['page']}."})
            elif not bid.startswith("ov:") and (r["x1"] > right + 1.5 or r["x0"] < left - 1.5 or r["y1"] > bottom + 1.5 or r["y0"] < top - 1.5):
                issues.append({"level": "critical", "code": "page_overflow", "block": bid, "page": r["page"],
                               "message": f"Content overflows the printable margins on page {r['page']}."})
    for pno, page in enumerate(pdf, start=1):
        for blk in page.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                if abs(ln["dir"][0] - 1) > 0.01:   # rotated text (watermark) is checked by its own bounds
                    continue
                for sp in ln["spans"]:
                    x0, y0, x1, y1 = sp["bbox"]
                    if sp["text"].strip() and (x1 > W + 1 or x0 < -1 or y1 > H + 1):
                        issues.append({"level": "critical", "code": "text_outside_page", "page": pno,
                                       "message": f"Text '{sp['text'][:30]}' is outside page {pno}."})
                    elif sp["text"].strip() and top < y0 < bottom and x1 > right + 3:
                        issues.append({"level": "warning", "code": "text_overflow", "page": pno,
                                       "message": f"Text runs into the right margin on page {pno}: '{sp['text'][:30]}'."})

    # ---- 6. blank pages / orphaned headings / split questions
    used = {p: [] for p in range(1, render.pages + 1)}
    for bid, rects in render.positions.items():
        for r in rects:
            used.setdefault(r["page"], []).append((r["y0"], bid))
    for p in range(render.cover_pages + 1, render.pages + 1):
        if not used.get(p):
            issues.append({"level": "warning", "code": "blank_page", "page": p,
                           "message": f"Page {p} has no content."})
    by_id = {b["id"]: b for b in blocks}
    order = [b["id"] for b in blocks]
    for i, b in enumerate(blocks):
        rects = render.positions.get(b["id"]) or []
        if b["type"] in ("heading", "section") and rects and i + 1 < len(order):
            hp = rects[-1]["page"]
            nxt = render.positions.get(order[i + 1]) or []
            if nxt and nxt[0]["page"] > hp:
                issues.append({"level": "warning", "code": "orphan_heading", "block": b["id"], "page": hp,
                               "message": f"Heading '{(b.get('text') or b.get('title') or '')[:40]}' is alone at the bottom of page {hp}."})
                repairs.append({"block": b["id"], "repair": "page_break_before"})
        if b["type"] == "question" and len({r["page"] for r in rects}) > 1:
            keep = template["questions"]["keep_together"]
            issues.append({"level": "info" if not keep else "warning", "code": "question_split", "block": b["id"],
                           "page": rects[0]["page"],
                           "message": f"Question {b.get('number')} continues onto the next page"
                                      + (" (it is taller than the space available)." if keep else ".")})
        if b["type"] == "table" and len({r["page"] for r in rects}) > 1:
            first = [r for r in rects if r["page"] == rects[0]["page"]]
            fh = max(r["y1"] for r in first) - min(r["y0"] for r in first)
            fs = (b.get("style") or {}).get("font_size") or template["tables"]["font_size"]
            row_h = fs * 1.25 + 6
            hdr = int(b.get("header_rows", 1) or 0)
            if fh < row_h * (hdr + 2.2):
                issues.append({"level": "warning", "code": "table_orphan_rows", "block": b["id"], "page": rects[0]["page"],
                               "message": f"Only one table row is left at the bottom of page {rects[0]['page']}."})
                repairs.append({"block": b["id"], "repair": "cond_break"})

    # ---- 7. page numbers
    f = template["footer"]
    if f["enabled"] and f["show_page_numbers"]:
        off = 0 if f["number_cover"] else render.cover_pages
        total = render.pages - off
        for p in range(off + 1, render.pages + 1):
            s = f["page_number_format"].replace("{page}", str(p - off)).replace("{total}", str(total))
            if s.strip() and not pdf[p - 1].search_for(s):
                issues.append({"level": "warning", "code": "page_number_missing", "page": p,
                               "message": f"Page number '{s}' not found on page {p}."})
                break

    # ---- 8. fonts embedded
    not_embedded = set()
    for p in pdf:
        for fnt in p.get_fonts():
            ext, name = fnt[1], fnt[3]
            if ext == "n/a" and name not in ("ZapfDingbats", "Symbol"):
                not_embedded.add(name)
    used_ne = {n for n in not_embedded if any(n in sp_font for sp_font in _span_fonts(pdf))}
    if used_ne:
        issues.append({"level": "warning", "code": "font_not_embedded",
                       "message": f"Font(s) not embedded: {', '.join(sorted(used_ne))}."})
    pdf.close()
    issues.extend(render.issues)
    for r in render.repairs:
        issues.append({"level": "info", "code": "auto_repair", "block": r["block"],
                       "message": f"Layout automatically adjusted ({r['repair'].replace('_', ' ')}) so the block fits."})
    return _dedupe(issues), repairs


def _span_fonts(pdf):
    fonts = set()
    for p in pdf:
        for blk in p.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                for sp in ln["spans"]:
                    if sp["text"].strip():
                        fonts.add(sp["font"])
    return fonts


def _dedupe(issues: list[dict]) -> list[dict]:
    seen, out = set(), []
    for i in issues:
        key = (i["level"], i["code"], i.get("block"), i.get("page"), i["message"])
        if key not in seen:
            seen.add(key)
            out.append(i)
    rank = {l: n for n, l in enumerate(LEVELS)}
    out.sort(key=lambda i: rank.get(i["level"], 9))
    return out


def summarize(issues: list[dict]) -> dict:
    c = Counter(i["level"] for i in issues)
    return {"critical": c.get("critical", 0), "warning": c.get("warning", 0), "info": c.get("info", 0),
            "passed": c.get("critical", 0) == 0}


def compare_counts(doc_model: dict, render) -> dict:
    st = M.stats(doc_model)
    pdf = pymupdf.open(render.path)
    text = " ".join(p.get_text() for p in pdf)
    pdf.close()
    return {"questions": st["questions"], "options": st["options"], "images": st["images"], "tables": st["tables"],
            "pages": render.pages, "words_source": st["words"], "words_output": len(norm_tokens(text))}
