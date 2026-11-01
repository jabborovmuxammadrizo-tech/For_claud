"""Format dispatch and upload validation."""
from __future__ import annotations

import zipfile
from pathlib import Path

SUPPORTED = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".png": "image", ".jpg": "image",
             ".jpeg": "image", ".tif": "image", ".tiff": "image", ".bmp": "image", ".webp": "image"}
MAX_BYTES = 300 * 1024 * 1024


class ImportErrorUser(ValueError):
    """An error with a message that can be shown to the user."""


def detect_kind(path: Path, original_name: str) -> str:
    ext = Path(original_name).suffix.lower()
    if ext == ".doc":
        raise ImportErrorUser("Legacy .doc files are not supported. Open the file in Word and save it as .docx.")
    kind = SUPPORTED.get(ext)
    if not kind:
        raise ImportErrorUser(f"Unsupported file type '{ext}'. Supported: PDF, DOCX, TXT, PNG, JPG, TIFF, BMP.")
    size = path.stat().st_size
    if size == 0:
        raise ImportErrorUser("The file is empty.")
    if size > MAX_BYTES:
        raise ImportErrorUser("The file is larger than 300 MB.")
    head = path.read_bytes()[:8]
    if kind == "pdf" and b"%PDF" not in path.read_bytes()[:1024]:
        raise ImportErrorUser("This file does not look like a valid PDF.")
    if kind == "docx":
        if head[:2] != b"PK" or not zipfile.is_zipfile(path):
            raise ImportErrorUser("This file does not look like a valid DOCX document.")
        with zipfile.ZipFile(path) as z:
            if "word/document.xml" not in z.namelist():
                raise ImportErrorUser("This DOCX file has no document body.")
    return kind


def extract(path: Path, kind: str, save_image, progress=None, ocr_enabled: bool = True) -> dict:
    if kind == "pdf":
        from . import pdf_import
        return pdf_import.extract(str(path), save_image, progress, ocr_enabled=ocr_enabled)
    if kind == "docx":
        from . import docx_import
        return docx_import.extract(str(path), save_image, progress)
    if kind == "txt":
        from . import simple_import
        return simple_import.extract_txt(str(path), save_image, progress)
    if kind == "image":
        from . import simple_import
        return simple_import.extract_image(str(path), save_image, progress, ocr_enabled=ocr_enabled)
    raise ImportErrorUser(f"Unsupported kind {kind}")
