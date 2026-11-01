"""Offline OCR. Uses the bundled RapidOCR (ONNX) engine; falls back to Tesseract if installed.

OCR output is always marked as uncertain: callers must surface a warning to the user.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from io import BytesIO

from PIL import Image

_engine = None
_lock = threading.Lock()


def _rapid():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
    return _engine


def available() -> dict:
    info = {"rapidocr": False, "tesseract": bool(shutil.which("tesseract"))}
    try:
        import rapidocr_onnxruntime  # noqa: F401
        info["rapidocr"] = True
    except Exception:
        pass
    info["any"] = info["rapidocr"] or info["tesseract"]
    return info


def ocr_image(png_bytes: bytes, scale: float = 1.0) -> list[dict]:
    """Return text lines: {text, bbox (in source units = pixels/scale), confidence, height}."""
    try:
        eng = _rapid()
        result, _ = eng(png_bytes)
        lines = []
        for box, text, conf in result or []:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            bbox = [min(xs) / scale, min(ys) / scale, max(xs) / scale, max(ys) / scale]
            lines.append({"text": text, "bbox": bbox, "confidence": float(conf), "height": bbox[3] - bbox[1]})
        return lines
    except ImportError:
        pass
    if shutil.which("tesseract"):
        return _tesseract(png_bytes, scale)
    raise RuntimeError("No OCR engine available")


def _tesseract(png_bytes: bytes, scale: float) -> list[dict]:
    proc = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng", "tsv"], input=png_bytes,
                          capture_output=True, timeout=300)
    rows = proc.stdout.decode("utf-8", "replace").splitlines()[1:]
    groups: dict[tuple, dict] = {}
    for r in rows:
        parts = r.split("\t")
        if len(parts) < 12 or not parts[11].strip():
            continue
        key = (parts[2], parts[3], parts[4])
        x, y, w, h, conf = int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9]), float(parts[10])
        g = groups.setdefault(key, {"words": [], "bbox": [x, y, x + w, y + h], "conf": []})
        g["words"].append(parts[11])
        g["conf"].append(conf)
        b = g["bbox"]
        g["bbox"] = [min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)]
    out = []
    for g in groups.values():
        b = [v / scale for v in g["bbox"]]
        out.append({"text": " ".join(g["words"]), "bbox": b, "confidence": sum(g["conf"]) / len(g["conf"]) / 100,
                    "height": b[3] - b[1]})
    out.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
    return out


def ocr_pil(img: Image.Image) -> list[dict]:
    buf = BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return ocr_image(buf.getvalue())
