"""Document model: an ordered list of typed content blocks plus optional page overlays.

Block types
  heading      {level, text}
  section      {title, layout}             starts a section; layout = standard|listening|reading|writing|instructions|answer_sheet|results
  instruction  {text}
  paragraph    {text}                       passages, free text
  question     {number, number_mode, qtype, text, options[], images[], points, difficulty, correct, answer_lines}
  table        {rows[[str]], header_rows}
  image        {asset, width, height, layout, caption, kind}   kind = image|map|diagram
  answer_space {lines}
  page_break   {}

Every block may carry `style` overrides and `source` provenance ({page, bbox, ocr, confidence}).
"""
from __future__ import annotations

import copy
import re
from typing import Iterator

from .util import new_id, norm_tokens

BLOCK_TYPES = {"heading", "section", "instruction", "paragraph", "question", "table",
               "image", "answer_space", "page_break"}
QTYPES = {"mcq", "true_false", "matching", "gap_fill", "transformation", "translation",
          "reading", "listening", "writing", "speaking", "open"}
PAGE_LAYOUTS = ("standard", "listening", "reading", "writing", "instructions", "answer_sheet", "results", "cover")


def block(type_: str, **fields) -> dict:
    assert type_ in BLOCK_TYPES, type_
    b = {"id": new_id("b_"), "type": type_}
    b.update(fields)
    return b


def question(text: str, number: str | None = None, options: list[dict] | None = None, qtype: str = "open", **kw) -> dict:
    return block("question", number=number, number_mode="manual" if number else "auto", qtype=qtype,
                 text=text, options=options or [], images=kw.pop("images", []), **kw)


def option(label: str, text: str) -> dict:
    return {"label": label, "text": text}


def new_document(title: str, blocks: list[dict] | None = None, **meta) -> dict:
    return {
        "version": 1,
        "title": title,
        "meta": {"orientation": "portrait", "page_size": [595.28, 841.89], "scanned_pages": [],
                 "warnings": [], "extraction": {}, **meta},
        "blocks": blocks or [],
        "overlays": [],
        "original_pages": None,
    }


def iter_blocks(doc: dict) -> Iterator[dict]:
    yield from doc.get("blocks", [])


def questions(doc: dict) -> list[dict]:
    return [b for b in iter_blocks(doc) if b["type"] == "question"]


def block_texts(b: dict) -> list[str]:
    """All user-content strings of a block (what must be preserved)."""
    t = b["type"]
    out: list[str] = []
    if t in ("heading", "instruction", "paragraph"):
        out.append(b.get("text", ""))
    elif t == "section":
        out.append(b.get("title", ""))
    elif t == "question":
        out.append(b.get("text", ""))
        out.extend(o.get("text", "") for o in b.get("options", []))
    elif t == "table":
        for row in b.get("rows", []):
            out.extend(str(c or "") for c in row)
    elif t == "image":
        if b.get("caption"):
            out.append(b["caption"])
    return out


def content_tokens(doc: dict) -> list[str]:
    toks: list[str] = []
    for b in iter_blocks(doc):
        for s in block_texts(b):
            toks.extend(norm_tokens(s))
    return toks


_NUM = re.compile(r"^(\d+)(.*)$")


def renumber(doc: dict, start: int = 1) -> dict:
    """Recompute numbers for questions in 'auto' mode. Manual numbers are left untouched.
    Question content is never modified."""
    n = start
    for b in iter_blocks(doc):
        if b["type"] == "section" and b.get("restart_numbering"):
            n = start
        if b["type"] != "question":
            continue
        if b.get("number_mode", "auto") == "auto":
            b["number"] = str(n)
            n += 1
        else:
            m = _NUM.match(str(b.get("number") or ""))
            n = int(m.group(1)) + 1 if m else n + 1
    return doc


def clone(doc: dict) -> dict:
    return copy.deepcopy(doc)


def stats(doc: dict) -> dict:
    bl = doc.get("blocks", [])
    qs = [b for b in bl if b["type"] == "question"]
    return {
        "blocks": len(bl),
        "questions": len(qs),
        "options": sum(len(q.get("options", [])) for q in qs),
        "mcq": sum(1 for q in qs if q.get("qtype") == "mcq"),
        "tables": sum(1 for b in bl if b["type"] == "table"),
        "images": sum(1 for b in bl if b["type"] == "image") + sum(len(q.get("images", [])) for q in qs),
        "maps": sum(1 for b in bl if b["type"] == "image" and b.get("kind") in ("map", "diagram")),
        "headings": sum(1 for b in bl if b["type"] in ("heading", "section")),
        "paragraphs": sum(1 for b in bl if b["type"] == "paragraph"),
        "words": len(content_tokens(doc)),
    }
