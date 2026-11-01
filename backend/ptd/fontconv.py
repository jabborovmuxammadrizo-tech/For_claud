"""Convert CFF-flavoured OpenType fonts to TrueType outlines (ReportLab embeds TrueType only)."""
from __future__ import annotations

from pathlib import Path


def otf_to_ttf_if_needed(path: Path) -> Path:
    from fontTools.ttLib import TTFont, newTable
    font = TTFont(str(path))
    if "glyf" in font:
        return path
    if "CFF " not in font:
        raise ValueError("unsupported outline format")
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    glyph_order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    glyf = newTable("glyf")
    glyf.glyphOrder = glyph_order
    glyf.glyphs = {}
    for name in glyph_order:
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, max_err=1.0, reverse_direction=True))
        glyf[name] = pen.glyph()
    font["glyf"] = glyf
    font["loca"] = newTable("loca")
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    maxp = font["maxp"]
    maxp.tableVersion = 0x00010000
    for attr in ("maxZones", "maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs",
                 "maxStackElements", "maxSizeOfInstructions", "maxComponentElements"):
        setattr(maxp, attr, 0)
    maxp.maxZones = 1
    maxp.maxComponentDepth = 0
    font["head"].indexToLocFormat = 0
    font["post"].formatType = 2.0
    font["post"].extraNames = []
    font["post"].mapping = {}
    font["post"].glyphOrder = glyph_order
    font.sfntVersion = "\x00\x01\x00\x00"
    out = path.with_suffix(".ttf")
    i = 2
    while out.exists():
        out = path.with_name(f"{path.stem} ({i}).ttf")
        i += 1
    font.save(str(out))
    path.unlink(missing_ok=True)
    return out
