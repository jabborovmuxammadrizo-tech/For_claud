"""Image processing: render-time preparation and Image Library edits."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 200_000_000

QUALITY = {
    "print": {"dpi": 300, "jpeg": 93},
    "standard": {"dpi": 200, "jpeg": 86},
    "compressed": {"dpi": 120, "jpeg": 68},
}


def probe(path: Path) -> dict:
    if path.suffix.lower() == ".svg":
        try:
            from svglib.svglib import svg2rlg
            d = svg2rlg(str(path))
            return {"width": int(d.width), "height": int(d.height), "format": "SVG", "mode": "vector", "dpi": None}
        except Exception:
            return {"width": 0, "height": 0, "format": "SVG", "mode": "vector", "dpi": None}
    with Image.open(path) as im:
        dpi = im.info.get("dpi", (None, None))[0]
        return {"width": im.width, "height": im.height, "format": im.format, "mode": im.mode,
                "dpi": int(dpi) if dpi else None}


def prepare_for_pdf(src: Path, cache_dir: Path, display_w_pt: float, display_h_pt: float,
                    quality: str = "print", grayscale: bool = False) -> tuple[Path, dict]:
    """Downsample to the target DPI for the displayed size (never upsample), convert colour space."""
    q = QUALITY.get(quality, QUALITY["print"])
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
            work.save(out, "JPEG", quality=q["jpeg"], optimize=True, dpi=(q["dpi"], q["dpi"]))
        else:
            work.save(out, "PNG", optimize=quality == "compressed")
        return out, info


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
