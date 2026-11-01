"""Export variants: compressed copies, page images, selected pages, structure JSON."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pymupdf


def compress_pdf(src: Path, dest: Path) -> Path:
    d = pymupdf.open(src)
    d.save(dest, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)
    d.close()
    return dest


def optimize_in_place(path: Path) -> None:
    d = pymupdf.open(path)
    tmp = path.with_suffix(".opt.pdf")
    d.save(tmp, garbage=3, deflate=True)
    d.close()
    tmp.replace(path)


def select_pages(src: Path, dest: Path, pages: list[int]) -> Path:
    d = pymupdf.open(src)
    valid = [p - 1 for p in pages if 1 <= p <= d.page_count]
    if not valid:
        d.close()
        raise ValueError("No valid pages selected.")
    d.select(valid)
    d.save(dest, garbage=3, deflate=True)
    d.close()
    return dest


def page_images(src: Path, out_dir: Path, fmt: str = "png", dpi: int = 150, pages: list[int] | None = None,
                prefix: str = "page") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    d = pymupdf.open(src)
    out = []
    for i, page in enumerate(d, start=1):
        if pages and i not in pages:
            continue
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        p = out_dir / f"{prefix}-{i:03d}.{'jpg' if fmt in ('jpg', 'jpeg') else 'png'}"
        if fmt in ("jpg", "jpeg"):
            pix.save(p, jpg_quality=90)
        else:
            pix.save(p)
        out.append(p)
    d.close()
    return out


def thumbnails(src: Path, out_dir: Path, width_px: int = 220) -> list[Path]:
    d = pymupdf.open(src)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i, page in enumerate(d, start=1):
        zoom = width_px / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        p = out_dir / f"thumb-{i:03d}.png"
        pix.save(p)
        out.append(p)
    d.close()
    return out


def write_structure(doc_model: dict, dest: Path) -> Path:
    dest.write_text(json.dumps(doc_model, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest


def zip_files(files: list[tuple[Path, str]], dest: Path) -> Path:
    tmp = dest.with_suffix(".partial")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        used = set()
        for p, arc in files:
            name = arc
            i = 2
            while name in used:
                stem, dot, ext = arc.rpartition(".")
                name = f"{stem} ({i}).{ext}" if dot else f"{arc} ({i})"
                i += 1
            used.add(name)
            z.write(p, name)
    tmp.replace(dest)
    return dest
