"""Font registry: bundled families, Windows system Arial, and user-installed fonts.

Fonts are always embedded (TrueType subsets). Built-in PDF base-14 fonts are never used for
content, so Uzbek Latin (oʻ, gʻ), curly quotes and dashes render correctly.
"""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont

from ..config import resource_dir

STYLES = ("regular", "bold", "italic", "bolditalic")
FALLBACK_FAMILY = "DejaVu Sans"

BUNDLED = {
    "DejaVu Sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
    "Liberation Sans": ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
    "Roboto": ("Roboto-Regular.ttf", "Roboto-Bold.ttf", "Roboto-Italic.ttf", "Roboto-BoldItalic.ttf"),
    "Open Sans": ("OpenSans-Regular.ttf", "OpenSans-Bold.ttf", "OpenSans-Italic.ttf", "OpenSans-BoldItalic.ttf"),
}
WINDOWS_ARIAL = ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")

_lock = threading.RLock()
_registered: dict[str, dict[str, str]] = {}
_custom: dict[str, dict[str, str]] = {}
_problems: dict[str, str] = {}


def _key(family: str) -> str:
    return "PTD_" + re.sub(r"[^A-Za-z0-9]", "", family)


def windows_fonts_dir() -> Path | None:
    if sys.platform == "win32":
        return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    return None


def family_files(family: str) -> tuple[dict[str, Path], str | None]:
    """Resolve files for a family. Returns (files, substitution_note)."""
    if family in _custom:
        return {k: Path(v) for k, v in _custom[family].items()}, None
    if family in BUNDLED:
        base = resource_dir() / "fonts"
        return {s: base / f for s, f in zip(STYLES, BUNDLED[family])}, None
    if family == "Arial":
        wd = windows_fonts_dir()
        if wd and (wd / "arial.ttf").exists():
            files = {s: wd / f for s, f in zip(STYLES, WINDOWS_ARIAL) if (wd / f).exists()}
            return files, None
        f, _ = family_files("Liberation Sans")
        return f, "Arial is not installed on this computer; the metric-compatible Liberation Sans was used."
    f, _ = family_files(FALLBACK_FAMILY)
    return f, f"Font '{family}' is not installed; {FALLBACK_FAMILY} was used."


def set_custom_fonts(fonts: list[dict]) -> None:
    """fonts: [{family, style, path}] from the database."""
    with _lock:
        _custom.clear()
        for f in fonts:
            _custom.setdefault(f["family"], {})[f["style"]] = f["path"]
        for fam, files in _custom.items():
            if "regular" not in files and files:
                files["regular"] = next(iter(files.values()))
        for fam in list(_registered):
            if fam in _custom:
                _registered.pop(fam)


def register(family: str) -> tuple[dict[str, str], str | None]:
    """Register a family with ReportLab; returns ({style: rl_font_name}, note)."""
    with _lock:
        if family in _registered:
            return _registered[family], _problems.get(family)
        files, note = family_files(family)
        key = _key(family)
        names: dict[str, str] = {}
        for style in STYLES:
            path = files.get(style) or files.get("regular")
            if path is None:
                continue
            name = f"{key}-{style}"
            try:
                if name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(name, str(path)))
                names[style] = name
            except (TTFError, OSError) as e:
                msg = f"Font '{family}' ({style}) cannot be embedded: {e}."
                note = (note + " " if note else "") + msg
        if "regular" not in names:
            if family == FALLBACK_FAMILY:
                raise RuntimeError("The bundled fallback font is missing or damaged.")
            fb, _ = register(FALLBACK_FAMILY)
            _registered[family] = fb
            _problems[family] = (note or "") + f" {FALLBACK_FAMILY} was used instead."
            return fb, _problems[family]
        for s in STYLES:
            names.setdefault(s, names["bold"] if s == "bolditalic" and "bold" in names else names["regular"])
        addMapping(key, 0, 0, names["regular"])
        addMapping(key, 1, 0, names["bold"])
        addMapping(key, 0, 1, names["italic"])
        addMapping(key, 1, 1, names["bolditalic"])
        names["family"] = key
        _registered[family] = names
        if note:
            _problems[family] = note
        return names, note


def has_glyph(rl_font_name: str, ch: str) -> bool:
    f = pdfmetrics.getFont(rl_font_name)
    face = getattr(f, "face", None)
    if face is None:
        return True
    return ord(ch) in face.charToGlyph


def available_families() -> list[dict]:
    out = []
    for fam in BUNDLED:
        out.append({"family": fam, "source": "bundled", "embeddable": True})
    wd = windows_fonts_dir()
    arial = bool(wd and (wd / "arial.ttf").exists())
    out.append({"family": "Arial", "source": "system" if arial else "substituted (Liberation Sans)", "embeddable": True})
    for fam in _custom:
        out.append({"family": fam, "source": "custom", "embeddable": fam not in _problems})
    return out


def inspect_font_file(path: Path) -> dict:
    """Read family/style names and embedding permission from a TTF/OTF file."""
    try:
        f = TTFont("PTD_inspect_" + re.sub(r"\W", "", path.stem), str(path))
    except TTFError as e:
        return {"ok": False, "error": str(e)}
    face = f.face
    name = getattr(face, "familyName", None) or path.stem
    if isinstance(name, bytes):
        name = name.decode("utf-8", "ignore")
    style = getattr(face, "styleName", b"Regular")
    if isinstance(style, bytes):
        style = style.decode("utf-8", "ignore")
    s = style.lower().replace(" ", "")
    norm = "bolditalic" if ("bold" in s and ("italic" in s or "oblique" in s)) else \
        "bold" if "bold" in s else "italic" if ("italic" in s or "oblique" in s) else "regular"
    return {"ok": True, "family": str(name).strip(), "style": norm, "glyphs": len(face.charToGlyph)}
