"""Mode B - original page import: each source page is embedded unchanged (vector, searchable)
inside the template's content area; branding, header/footer, watermark and user overlays are added
around/over it. Page order, rotation and exclusion come from doc_model['original_pages']."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Callable

import pymupdf
from reportlab.pdfgen import canvas as rl_canvas

from ..util import norm_tokens
from .renderer import Ctx, Furniture, RenderResult, _overlays
from ..mupdf import locked


@locked
def render_original(doc_model: dict, template: dict, resolve_asset: Callable, source_pdf: Path, out_path: Path,
                    cache_dir: Path, options: dict | None = None, progress=None) -> RenderResult:
    options = options or {}
    progress = progress or (lambda f, m: None)
    src = pymupdf.open(source_pdf)
    pages = doc_model.get("original_pages") or [{"index": i, "rotation": 0, "include": True} for i in range(src.page_count)]
    pages = [p for p in pages if p.get("include", True) and 0 <= int(p["index"]) < src.page_count]
    if options.get("pages"):
        sel = set(options["pages"])
        pages = [p for i, p in enumerate(pages, start=1) if i in sel]
    ctx = Ctx(doc_model, template, resolve_asset, cache_dir, options, {})
    ctx.cover_pages = 0
    furn = Furniture(ctx)
    n = len(pages)
    under_p = out_path.with_suffix(".under.pdf")
    over_p = out_path.with_suffix(".over.pdf")

    class _D:
        page = 0
    ctx.doc = _D()
    cu = rl_canvas.Canvas(str(under_p), pagesize=(ctx.W, ctx.H), initialFontName=ctx.body["regular"])
    co = rl_canvas.Canvas(str(over_p), pagesize=(ctx.W, ctx.H), initialFontName=ctx.body["regular"])
    for i in range(1, n + 1):
        ctx.doc.page = i
        furn.background(cu, None)
        cu.showPage()
        wm = ctx.t["branding"]["watermark"] or {}
        furn.watermark(co) if wm.get("layer", "under") in ("under", "over") else None
        furn.header(co, "standard")
        furn.footer_static(co)
        furn.page_number(co, i, n)
        _overlays(ctx, co, i)
        co.showPage()
    cu.save()
    co.save()
    under, over = pymupdf.open(under_p), pymupdf.open(over_p)
    out = pymupdf.open()
    content = pymupdf.Rect(ctx.ml, ctx.mt, ctx.W - ctx.mr, ctx.H - ctx.mb)
    positions = {}
    for i, p in enumerate(pages):
        progress(i / max(n, 1), f"Placing original page {i + 1} of {n}")
        page = out.new_page(width=ctx.W, height=ctx.H)
        page.show_pdf_page(page.rect, under, i)
        rot = int(p.get("rotation", 0)) % 360
        page.show_pdf_page(content, src, int(p["index"]), rotate=rot, keep_proportion=True)
        page.show_pdf_page(page.rect, over, i)
        positions[f"page:{p['index']}"] = [{"page": i + 1, "x0": content.x0, "y0": content.y0, "x1": content.x1, "y1": content.y1}]
    meta = {"title": doc_model.get("title") or "", "author": ctx.t["branding"].get("org_name", ""),
            "creator": "PDF Test Designer", "producer": "PDF Test Designer (PyMuPDF)"}
    out.set_metadata(meta)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, garbage=3, deflate=True)
    issues = list(ctx.issues)
    # integrity: every word of the included source pages must be in the output
    need = Counter()
    for p in pages:
        need.update(norm_tokens(src[int(p["index"])].get_text()))
    got = Counter()
    for pg in out:
        got.update(norm_tokens(pg.get_text()))
    miss = need - got
    if miss:
        issues.append({"level": "critical", "code": "missing_content",
                       "message": f"{sum(miss.values())} word(s) of the original pages are not present in the output."})
    if not need:
        issues.append({"level": "warning", "code": "scanned_source",
                       "message": "The original pages contain no extractable text (scanned). They were placed as images; text is not searchable."})
    for d in (under, over, src):
        d.close()
    out.close()
    under_p.unlink(missing_ok=True)
    over_p.unlink(missing_ok=True)
    positions.update({k: v for k, v in ctx.positions.items()})
    return RenderResult(path=out_path, pages=n, positions=positions, page_size=(ctx.W, ctx.H), issues=issues,
                        fonts={"body": ctx.t["fonts"]["body"]}, cover_pages=0)
