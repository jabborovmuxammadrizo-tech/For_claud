"""PDF extraction with PyMuPDF (text, layout, images, tables, vector diagrams, OCR for scans)."""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable

import pymupdf

from .. import model
from . import ocr, structure

SaveImage = Callable[[bytes, str, dict], dict]  # (bytes, ext, meta) -> {"asset", "width", "height"}
Progress = Callable[[float, str], None]

PAGE_NUM_RE = re.compile(r"^\s*(?:page|bet|sahifa)?\s*\d{1,4}\s*(?:/|of|dan)?\s*\d{0,4}\s*$|^\s*[-–]\s*\d{1,4}\s*[-–]\s*$", re.I)
MIN_IMG_PX = 16


def _span_flags(spans):
    txt = [s for s in spans if s["text"].strip()]
    if not txt:
        return False, False, 0.0
    bold = all((s["flags"] & 16) or "bold" in s["font"].lower() or "black" in s["font"].lower() for s in txt)
    italic = all((s["flags"] & 2) or "italic" in s["font"].lower() or "oblique" in s["font"].lower() for s in txt)
    weight = sum(len(s["text"]) for s in txt)
    size = sum(s["size"] * len(s["text"]) for s in txt) / max(weight, 1)
    return bold, italic, size


def _inside(b, r, tol=1.0):
    return b[0] >= r[0] - tol and b[1] >= r[1] - tol and b[2] <= r[2] + tol and b[3] <= r[3] + tol


def _overlap_ratio(b, r):
    x0, y0, x1, y1 = max(b[0], r[0]), max(b[1], r[1]), min(b[2], r[2]), min(b[3], r[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    area = (b[2] - b[0]) * (b[3] - b[1]) or 1
    return (x1 - x0) * (y1 - y0) / area


def _row_sort(regs):
    """Top-to-bottom, and left-to-right within a visual row."""
    regs = sorted(regs, key=lambda r: (r["bbox"][1], r["bbox"][0]))
    out, row = [], []
    for r in regs:
        if row:
            a = row[0]["bbox"]
            b = r["bbox"]
            h = min(a[3] - a[1], b[3] - b[1]) or 1
            if r["kind"] == "line" and row[0]["kind"] == "line" and min(a[3], b[3]) - max(a[1], b[1]) > 0.6 * h:
                row.append(r)
                continue
            out += sorted(row, key=lambda x: x["bbox"][0])
        row = [r]
    out += sorted(row, key=lambda x: x["bbox"][0])
    return out


def _order_regions(regions, page_w):
    """Reading order with multi-column detection. regions: dicts with bbox."""
    mid = page_w / 2
    left = [r for r in regions if r["bbox"][2] <= mid + 12 and r["bbox"][2] - r["bbox"][0] < page_w * 0.55]
    right = [r for r in regions if r["bbox"][0] >= mid - 12 and r["bbox"][2] - r["bbox"][0] < page_w * 0.55]
    # two real columns: both sides carry substantial text and the right column starts near the middle
    multi = len(left) >= 3 and len(right) >= 3 and \
        sum(len(r.get("text", "")) for r in right) > 120 and sum(len(r.get("text", "")) for r in left) > 120 and \
        sum(1 for r in right if r["kind"] == "line" and not structure.OPT_RE.match(r["text"])) > 2
    if not multi:
        return _row_sort(regions), False
    side = {id(r) for r in left} | {id(r) for r in right}
    full = sorted([r for r in regions if id(r) not in side], key=lambda r: r["bbox"][1])
    out = []
    lo = -1e9
    bands = [*(f["bbox"][1] for f in full), 1e9]
    fi = 0
    for hi in bands:
        band_l = _row_sort([r for r in left if lo <= r["bbox"][1] < hi])
        band_r = _row_sort([r for r in right if lo <= r["bbox"][1] < hi])
        out += band_l + band_r
        if fi < len(full):
            out.append(full[fi])
            lo = full[fi]["bbox"][1]
            fi += 1
    return out, True


def _merge_rows(lines):
    """Join lines that sit on the same visual row (e.g. 'A) cat     B) dog') left-to-right."""
    out = []
    for ln in lines:
        if out:
            p = out[-1]
            pb, b = p["bbox"], ln["bbox"]
            h = min(pb[3] - pb[1], b[3] - b[1]) or 1
            vert_overlap = min(pb[3], b[3]) - max(pb[1], b[1])
            if vert_overlap > 0.6 * h and b[0] >= pb[2] - 2 and p["page"] == ln["page"]:
                p["text"] = p["text"] + "   " + ln["text"]
                p["bbox"] = [pb[0], min(pb[1], b[1]), b[2], max(pb[3], b[3])]
                p["bold"] = p["bold"] and ln["bold"]
                continue
        out.append(ln)
    return out


def _plumber_tables(path: str, pno: int) -> list[dict]:
    """Fallback table detector (pdfplumber) used when PyMuPDF's detector fails on a page."""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            page = pdf.pages[pno]
            out = []
            for t in page.find_tables():
                rows = [[(c or "").strip() for c in r] for r in t.extract()]
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2:
                    out.append({"bbox": list(t.bbox), "rows": rows, "header_rows": 1})
            return out
    except Exception:
        return []


def _cell_text(words, rect) -> str:
    """Rebuild a table cell from word boxes so inter-word spaces are kept exactly."""
    x0, y0, x1, y1 = rect
    ws = [w for w in words if x0 - 1 <= (w[0] + w[2]) / 2 <= x1 + 1 and y0 - 1 <= (w[1] + w[3]) / 2 <= y1 + 1]
    ws.sort(key=lambda w: (w[5], w[6], w[7]))
    lines: list[list[str]] = []
    last = None
    for w in ws:
        key = (w[5], w[6])
        if key != last:
            lines.append([])
            last = key
        lines[-1].append(w[4])
    return " ".join(" ".join(l) for l in lines).strip()


def _furniture(pages_lines, page_heights):
    """Find repeated running headers/footers and page numbers in the source document."""
    counter = Counter()
    n = len(pages_lines)
    for lines, h in zip(pages_lines, page_heights):
        seen = set()
        for ln in lines:
            y0, y1 = ln["bbox"][1], ln["bbox"][3]
            if y1 < h * 0.08 or y0 > h * 0.92:
                key = re.sub(r"\d+", "#", ln["text"].strip().lower())
                if key not in seen:
                    counter[key] += 1
                    seen.add(key)
    repeated = {k for k, c in counter.items()
                if (n >= 3 and c >= max(2, int(n * 0.6))) or (n == 2 and c == 2)}
    return repeated


def extract(path: str, save_image: SaveImage, progress: Progress | None = None, ocr_enabled: bool = True) -> dict:
    progress = progress or (lambda f, m: None)
    doc = pymupdf.open(path)
    if doc.needs_pass:
        raise ValueError("The PDF is password protected and cannot be read.")
    n = doc.page_count
    warnings: list[dict] = []
    scanned_pages: list[int] = []
    ocr_pages: list[int] = []
    pages_lines: list[list[dict]] = []
    page_items: list[list[dict]] = []
    page_heights = []
    multi_col_pages = []
    raw_tokens_total = 0
    orientation = Counter()
    skipped_tiny = 0
    ocr_conf: list[float] = []
    ocr_info = ocr.available()

    for pno in range(n):
        page = doc[pno]
        progress(pno / max(n, 1), f"Reading page {pno + 1} of {n}")
        W, H = page.rect.width, page.rect.height
        page_heights.append(H)
        orientation["landscape" if W > H else "portrait"] += 1
        raw_text = page.get_text("text")
        raw_tokens_total += len(raw_text.split())
        regions: list[dict] = []
        lines: list[dict] = []

        # ---- tables
        tables = []
        try:
            words = None
            for t in page.find_tables().tables:
                if words is None:
                    words = page.get_text("words")
                rows = []
                for row in t.rows:
                    rows.append([_cell_text(words, c) if c else "" for c in row.cells])
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                    tables.append({"bbox": list(t.bbox), "rows": rows, "header_rows": 1 if t.header and t.header.external is False else 1})
        except Exception as e:  # pragma: no cover - library edge cases
            tables = _plumber_tables(path, pno)
            if not tables:
                warnings.append({"level": "info", "code": "table_detect_failed", "message": f"Page {pno+1}: table detection skipped ({e})."})
        for t in tables:
            regions.append({"kind": "table", "bbox": t["bbox"], "rows": t["rows"], "header_rows": t["header_rows"], "page": pno + 1})

        # ---- images
        img_rects = []
        page_area = W * H
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            if not rects:
                continue
            try:
                info = doc.extract_image(xref)
            except Exception:
                continue
            if not info or info["width"] < MIN_IMG_PX or info["height"] < MIN_IMG_PX:
                skipped_tiny += 1
                continue
            smask = img[1]
            data, ext = info["image"], info["ext"]
            if smask or ext not in ("png", "jpeg", "jpg"):
                # normalise (CMYK / JBIG2 / alpha masks) to PNG
                pix = pymupdf.Pixmap(doc, xref)
                if smask:
                    try:
                        pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, smask))
                    except Exception:
                        pass
                if pix.n - pix.alpha >= 4:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                data, ext = pix.tobytes("png"), "png"
            for r in rects:
                rb = [r.x0, r.y0, r.x1, r.y1]
                ratio = (r.width * r.height) / page_area
                if ratio < 0.002:
                    skipped_tiny += 1
                    continue
                if any(_overlap_ratio(rb, t["bbox"]) > 0.8 for t in tables):
                    continue
                img_rects.append((rb, ratio, data, ext, info))
        # scanned page: almost no text, an image covering most of the page
        is_scanned = len(raw_text.strip()) < 15 and any(ratio > 0.5 for _, ratio, *_ in img_rects)
        if is_scanned:
            scanned_pages.append(pno + 1)

        if not is_scanned:
            for rb, ratio, data, ext, info in img_rects:
                a = save_image(data, ext, {"page": pno + 1, "source": "pdf"})
                regions.append({"kind": "image", "bbox": rb, "page": pno + 1, "area_ratio": ratio, **a})

            # ---- vector diagrams / maps (clusters of drawings that are not table rules)
            try:
                drawings = page.get_drawings()
            except Exception:
                drawings = []
            shapes = [d["rect"] for d in drawings if d["rect"].width > 2 and d["rect"].height > 2
                      and not (d["rect"].height < 3 or d["rect"].width < 3)]
            if len(shapes) >= 6:
                cluster = pymupdf.Rect(shapes[0])
                for r in shapes[1:]:
                    cluster |= r
                cb = [cluster.x0, cluster.y0, cluster.x1, cluster.y1]
                area_ratio = cluster.width * cluster.height / page_area
                in_table = any(_overlap_ratio(cb, t["bbox"]) > 0.5 for t in tables)
                is_frame = cluster.width > W * 0.9 and cluster.height > H * 0.9  # page border
                if area_ratio > 0.04 and not in_table and not is_frame:
                    clip = cluster + (-4, -4, 4, 4)
                    pix = page.get_pixmap(clip=clip, dpi=200)
                    a = save_image(pix.tobytes("png"), "png", {"page": pno + 1, "source": "pdf-vector"})
                    embedded = page.get_textbox(clip).strip()
                    regions.append({"kind": "image", "bbox": [clip.x0, clip.y0, clip.x1, clip.y1], "page": pno + 1,
                                    "area_ratio": area_ratio, "embedded_text": embedded, "vector": True, **a})

        # ---- text
        if is_scanned:
            if ocr_enabled and ocr_info["any"]:
                progress(pno / max(n, 1), f"Running OCR on scanned page {pno + 1}")
                pix = page.get_pixmap(dpi=200)
                scale = 200 / 72
                try:
                    olines = ocr.ocr_image(pix.tobytes("png"), scale=scale)
                except Exception as e:
                    olines = []
                    warnings.append({"level": "critical", "code": "ocr_failed", "message": f"Page {pno+1}: OCR failed ({e})."})
                if olines:
                    ocr_pages.append(pno + 1)
                    prev_y1 = None
                    for ol in olines:
                        b = ol["bbox"]
                        gap = (b[1] - prev_y1) if prev_y1 is not None else 99
                        lines.append({"kind": "line", "text": ol["text"], "size": round(ol["height"] * 0.75, 1),
                                      "bold": False, "italic": False, "page": pno + 1, "bbox": b,
                                      "new_para": gap > ol["height"] * 0.6, "ocr": True,
                                      "confidence": round(ol["confidence"], 3)})
                        ocr_conf.append(ol["confidence"])
                        prev_y1 = b[3]
            if not lines:
                # preserve visually: include the whole page as an image block
                pix = page.get_pixmap(dpi=200)
                a = save_image(pix.tobytes("png"), "png", {"page": pno + 1, "source": "scan"})
                regions.append({"kind": "image", "bbox": [0, 0, W, H], "page": pno + 1, "area_ratio": 1.0, **a})
                warnings.append({"level": "critical", "code": "scanned_not_extracted",
                                 "message": f"Page {pno+1} is scanned and its text could not be extracted. It was kept as an image; please check it manually."})
        else:
            d = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
            excl = [t["bbox"] for t in tables] + [r["bbox"] for r in regions if r.get("vector")]
            for blk in d["blocks"]:
                if blk.get("type") != 0:
                    continue
                prev = None
                for ln in blk["lines"]:
                    text = "".join(s["text"] for s in ln["spans"])
                    if not text.strip():
                        continue
                    bbox = list(ln["bbox"])
                    if any(_overlap_ratio(bbox, e) > 0.6 for e in excl):
                        continue
                    if abs(ln["dir"][1]) > 0.5:  # vertical text (margin labels): keep but flag
                        warnings.append({"level": "info", "code": "rotated_text", "message": f"Page {pno+1}: rotated text '{text[:40]}' placed inline."})
                    bold, italic, size = _span_flags(ln["spans"])
                    lh = bbox[3] - bbox[1]
                    new_para = prev is None or (bbox[1] - prev[3]) > 0.55 * lh or bbox[0] - prev[0] > 18
                    lines.append({"kind": "line", "text": text, "size": round(size, 1), "bold": bold, "italic": italic,
                                  "page": pno + 1, "bbox": bbox, "new_para": new_para})
                    prev = bbox
        pages_lines.append(lines)
        page_items.append(regions)

    # remove source running headers/footers/page numbers (reported, never silent)
    repeated = _furniture(pages_lines, page_heights)
    removed = []
    for pi, lines in enumerate(pages_lines):
        H = page_heights[pi]
        keep = []
        for ln in lines:
            edge = ln["bbox"][3] < H * 0.08 or ln["bbox"][1] > H * 0.92
            key = re.sub(r"\d+", "#", ln["text"].strip().lower())
            if edge and (key in repeated or PAGE_NUM_RE.match(ln["text"])):
                removed.append({"page": pi + 1, "text": ln["text"].strip()})
                continue
            keep.append(ln)
        pages_lines[pi] = keep

    items: list[dict] = []
    for pi in range(n):
        W = doc[pi].rect.width
        regions = page_items[pi] + [{**ln, "kind": "line"} for ln in pages_lines[pi]]
        # lines are ordered as groups by their block; we order individual regions
        ordered, multi = _order_regions(regions, W)
        if multi:
            multi_col_pages.append(pi + 1)
        line_buf: list[dict] = []
        for r in ordered:
            if r["kind"] == "line":
                line_buf.append(r)
                continue
            items.extend(_merge_rows(line_buf))
            line_buf = []
            items.append(r)
        items.extend(_merge_rows(line_buf))
        items.append({"kind": "page_break", "page": pi + 1})

    progress(1.0, "Detecting document structure")
    blocks, info = structure.detect(items)
    # carry vector-diagram embedded text into the image blocks for validation
    if scanned_pages:
        msg = (f"{len(scanned_pages)} scanned page(s) detected ({_fmt_pages(scanned_pages)}). ")
        if ocr_pages:
            avg = sum(ocr_conf) / len(ocr_conf) if ocr_conf else 0
            msg += f"Text was recognised with OCR (average confidence {avg:.0%}). OCR can misread characters - please proofread these pages."
            warnings.append({"level": "warning", "code": "ocr_used", "message": msg})
    if multi_col_pages:
        warnings.append({"level": "info", "code": "multi_column",
                         "message": f"Multi-column layout detected on page(s) {_fmt_pages(multi_col_pages)}; reading order was reconstructed column by column."})
    if removed:
        uniq = sorted({r["text"] for r in removed})[:6]
        warnings.append({"level": "info", "code": "source_furniture_removed",
                         "message": f"Removed {len(removed)} repeated header/footer/page-number line(s) from the original (replaced by the template's own header/footer): "
                                    + "; ".join(f"'{u}'" for u in uniq)})
    if skipped_tiny:
        warnings.append({"level": "info", "code": "tiny_images_skipped",
                         "message": f"Skipped {skipped_tiny} tiny decorative image(s) (bullets/lines smaller than {MIN_IMG_PX}px)."})
    warnings.extend(structure.numbering_report(info["source_numbers"]))

    title = (doc.metadata or {}).get("title") or ""
    first = doc[0].rect if n else pymupdf.Rect(0, 0, 595, 842)
    result = model.new_document(
        title=title.strip(),
        blocks=blocks,
        orientation=orientation.most_common(1)[0][0] if orientation else "portrait",
        page_size=[first.width, first.height],
        source_pages=n,
        scanned_pages=scanned_pages,
        ocr_pages=ocr_pages,
        multi_column_pages=multi_col_pages,
        warnings=warnings,
        extraction={"raw_tokens": raw_tokens_total, "removed_furniture": removed,
                    "body_size": info["body_size"], "source_numbers": info["source_numbers"],
                    "ocr_confidence": (sum(ocr_conf) / len(ocr_conf)) if ocr_conf else None},
    )
    doc.close()
    return result


def _fmt_pages(pages):
    return ", ".join(map(str, pages[:12])) + ("…" if len(pages) > 12 else "")


def original_pages(path: str) -> list[dict]:
    doc = pymupdf.open(path)
    out = [{"index": i, "width": p.rect.width, "height": p.rect.height, "rotation": p.rotation}
           for i, p in enumerate(doc)]
    doc.close()
    return out
