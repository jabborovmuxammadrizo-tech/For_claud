"""TXT and image (PNG/JPG/TIFF/BMP) importers."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from .. import model
from . import ocr, structure


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1251", "cp1252"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def extract_txt(path: str, save_image=None, progress=None) -> dict:
    text = _decode(Path(path).read_bytes()).replace("\r\n", "\n").replace("\r", "\n")
    items = []
    prev_blank = True
    for line in text.split("\n"):
        if not line.strip():
            prev_blank = True
            continue
        caps = line.strip().upper() == line.strip() and sum(c.isalpha() for c in line) >= 3 and len(line) < 70
        items.append({"kind": "line", "text": line.replace("\t", "   "), "size": 13 if caps else 11,
                      "bold": caps, "page": None, "bbox": None, "new_para": prev_blank})
        prev_blank = False
    blocks, info = structure.detect(items)
    return model.new_document(title="", blocks=blocks,
                              warnings=structure.numbering_report(info["source_numbers"]),
                              extraction={"raw_tokens": len(text.split()), "body_size": 11,
                                          "source_numbers": info["source_numbers"], "removed_furniture": []})


def extract_image(path: str, save_image, progress=None, ocr_enabled: bool = True) -> dict:
    progress = progress or (lambda f, m: None)
    img = Image.open(path)
    frames = getattr(img, "n_frames", 1)
    items = []
    warnings = []
    confs = []
    for fi in range(frames):
        img.seek(fi)
        frame = img.convert("RGB")
        progress(fi / frames, f"Processing image page {fi + 1} of {frames}")
        lines = []
        if ocr_enabled and ocr.available()["any"]:
            try:
                buf = BytesIO()
                frame.save(buf, "PNG")
                lines = ocr.ocr_image(buf.getvalue())
            except Exception as e:
                warnings.append({"level": "critical", "code": "ocr_failed", "message": f"OCR failed: {e}"})
        if lines:
            prev = None
            for ln in lines:
                gap = (ln["bbox"][1] - prev) if prev is not None else 99
                items.append({"kind": "line", "text": ln["text"], "size": round(ln["height"] * 0.75 * 72 / 200, 1) or 11,
                              "bold": False, "page": fi + 1, "bbox": ln["bbox"], "new_para": gap > ln["height"] * 0.6,
                              "ocr": True, "confidence": ln["confidence"]})
                confs.append(ln["confidence"])
                prev = ln["bbox"][3]
        else:
            buf = BytesIO()
            frame.save(buf, "PNG")
            a = save_image(buf.getvalue(), "png", {"source": "image-import"})
            items.append({"kind": "image", "page": fi + 1, "bbox": None, "area_ratio": 1.0, **a})
            warnings.append({"level": "critical", "code": "scanned_not_extracted",
                             "message": f"Image page {fi+1}: no text could be recognised; the image was kept as-is."})
    blocks, info = structure.detect(items)
    if confs:
        warnings.append({"level": "warning", "code": "ocr_used",
                         "message": f"Text was recognised with OCR (average confidence {sum(confs)/len(confs):.0%}). Please proofread the result."})
    return model.new_document(title=Path(path).stem, blocks=blocks, warnings=warnings,
                              scanned_pages=list(range(1, frames + 1)), ocr_pages=list(range(1, frames + 1)) if confs else [],
                              extraction={"raw_tokens": sum(len(i.get("text", "").split()) for i in items),
                                          "body_size": info["body_size"], "source_numbers": info["source_numbers"],
                                          "ocr_confidence": sum(confs) / len(confs) if confs else None, "removed_furniture": []})
