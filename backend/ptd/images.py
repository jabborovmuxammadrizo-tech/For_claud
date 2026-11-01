"""Image processing: render-time preparation and Image Library edits."""
from __future__ import annotations

import hashlib
import os
import threading
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps
from .mupdf import locked

Image.MAX_IMAGE_PIXELS = 200_000_000

QUALITY = {
    "print": {"dpi": 300, "jpeg": 93},
    "standard": {"dpi": 200, "jpeg": 86},
    "compressed": {"dpi": 120, "jpeg": 68},
}


def _publish(tmp: Path, out: Path) -> None:
    """Move a finished cache file into place. On Windows the target may be open in another job
    (renaming over an open file is refused); the cached content is identical, so keep the existing one."""
    try:
        os.replace(tmp, out)
    except OSError:
        if not out.exists():
            raise
        tmp.unlink(missing_ok=True)


@locked
def probe(path: Path) -> dict:
    if path.suffix.lower() == ".svg":
        try:
            r = pymupdf.open(path)[0].rect
            return {"width": int(r.width), "height": int(r.height), "format": "SVG", "mode": "vector", "dpi": None}
        except Exception as e:
            raise ValueError(f"unreadable SVG ({e})") from e
    with Image.open(path) as im:
        dpi = im.info.get("dpi", (None, None))[0]
        return {"width": im.width, "height": im.height, "format": im.format, "mode": im.mode,
                "dpi": int(dpi) if dpi else None}


def prepare_for_pdf(src: Path, cache_dir: Path, display_w_pt: float, display_h_pt: float,
                    quality: str = "print", grayscale: bool = False) -> tuple[Path, dict]:
    """Downsample to the target DPI for the displayed size (never upsample), convert colour space."""
    q = QUALITY.get(quality, QUALITY["print"])
    if src.suffix.lower() == ".svg":
        src = svg_to_png(src, cache_dir, display_w_pt, display_h_pt)
    key = hashlib.sha1(f"{src}:{src.stat().st_mtime_ns}:{display_w_pt:.1f}:{display_h_pt:.1f}:{quality}:{grayscale}".encode()).hexdigest()
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
        target_w = max(1, int(display_w_pt / 72 * q["dpi"]))
        target_h = max(1, int(display_h_pt / 72 * q["dpi"]))
        info = {"src_w": im.width, "src_h": im.height,
                "effective_dpi": round(im.width / max(display_w_pt / 72, 1e-6))}
        is_jpeg = (im.format or "").upper() == "JPEG"
        ext = ".png" if has_alpha or (not is_jpeg and quality != "compressed") else ".jpg"
        out = cache_dir / f"{key}{ext}"
        if out.exists():
            return out, info
        cache_dir.mkdir(parents=True, exist_ok=True)
        work = im
        if work.mode not in ("RGB", "RGBA", "L", "LA"):
            work = work.convert("RGBA" if has_alpha else "RGB")
        if grayscale:
            work = work.convert("LA" if has_alpha else "L")
        if work.width > target_w * 1.1 or work.height > target_h * 1.1:
            work = work.copy()
            work.thumbnail((target_w, target_h), Image.LANCZOS)
        if ext == ".jpg":
            if work.mode in ("RGBA", "LA"):
                work = work.convert("RGB" if not grayscale else "L")
            tmp = out.with_name(f"{out.stem}.{threading.get_ident()}.tmp")
            work.save(tmp, "JPEG", quality=q["jpeg"], optimize=True, dpi=(q["dpi"], q["dpi"]))
            _publish(tmp, out)
        else:
            tmp = out.with_name(f"{out.stem}.{threading.get_ident()}.tmp")
            work.save(tmp, "PNG", optimize=quality == "compressed")
            _publish(tmp, out)
        return out, info


@locked
def svg_to_png(src: Path, cache_dir: Path, w_pt: float, h_pt: float, dpi: int = 600) -> Path:
    """Rasterise an SVG with MuPDF at print resolution (keeps transparency)."""
    key = hashlib.sha1(f"svg:{src}:{src.stat().st_mtime_ns}:{w_pt:.1f}:{h_pt:.1f}:{dpi}".encode()).hexdigest()
    out = cache_dir / f"{key}.png"
    if out.exists():
        return out
    cache_dir.mkdir(parents=True, exist_ok=True)
    page = pymupdf.open("pdf", pymupdf.open(src).convert_to_pdf())[0]
    zoom = max(w_pt / page.rect.width, h_pt / page.rect.height) * dpi / 72
    # write-then-rename: concurrent jobs share this cache and must never read a half-written file
    tmp = out.with_name(f"{out.stem}.{threading.get_ident()}.tmp.png")
    page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True).save(tmp)
    _publish(tmp, out)
    return out


def edit(src: Path, ops: dict) -> bytes:
    """Apply Image Library edits. ops: crop {x,y,w,h in 0..1}, rotate deg, flip_h, flip_v,
    resize {width,height}, opacity 0..1, background '#rrggbb'. Returns PNG bytes (lossless)."""
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGBA")
        c = ops.get("crop")
        if c:
            x0 = int(max(0, min(1, c["x"])) * im.width)
            y0 = int(max(0, min(1, c["y"])) * im.height)
            x1 = int(max(0, min(1, c["x"] + c["w"])) * im.width)
            y1 = int(max(0, min(1, c["y"] + c["h"])) * im.height)
            if x1 - x0 >= 2 and y1 - y0 >= 2:
                im = im.crop((x0, y0, x1, y1))
        rot = ops.get("rotate") or 0
        if rot:
            im = im.rotate(-float(rot), expand=True, resample=Image.BICUBIC)
        if ops.get("flip_h"):
            im = ImageOps.mirror(im)
        if ops.get("flip_v"):
            im = ImageOps.flip(im)
        r = ops.get("resize")
        if r and r.get("width"):
            w = int(r["width"])
            h = int(r.get("height") or round(im.height * w / im.width))
            im = im.resize((max(1, w), max(1, h)), Image.LANCZOS)
        bg = ops.get("background")
        if bg:
            base = Image.new("RGBA", im.size, bg)
            base.alpha_composite(im)
            im = base
        op = ops.get("opacity")
        if op is not None and float(op) < 1:
            a = im.getchannel("A").point(lambda v: int(v * float(op)))
            im.putalpha(a)
        buf = BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()


def thumbnail(src: Path, size: int = 320) -> bytes:
    if src.suffix.lower() == ".svg":
        return src.read_bytes()
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((size, size))
        buf = BytesIO()
        im.convert("RGBA").save(buf, "PNG")
        return buf.getvalue()
