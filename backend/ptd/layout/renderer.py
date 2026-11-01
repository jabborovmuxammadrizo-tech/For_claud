"""PDF layout engine (ReportLab platypus).

The same engine produces the editor preview and the final export, so what the user sees is what
gets printed. Every content block is tracked to its drawn position (page + bbox) for click-to-select
in the editor and for overflow/blank-page validation.

Repairs: when a block cannot be laid out (LayoutError) the engine applies the least invasive fix
for that block only - release keep-together, remove decorative box, allow table rows to split,
shrink an image to fit - and re-runs. Content is never dropped to make a layout fit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, Image as RLImage, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.doctemplate import LayoutError

from .. import model as M
from .. import images as imgs
from ..templates import DENSITY, normalize
from . import fonts as F

ALIGN = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY}
MAX_ATTEMPTS = 10


class RenderError(Exception):
    pass


@dataclass
class RenderResult:
    path: Path
    pages: int
    positions: dict = field(default_factory=dict)       # block_id -> [{page,x0,y0,x1,y1}] (pt, top-left origin)
    page_size: tuple = (595.28, 841.89)
    frames: dict = field(default_factory=dict)          # page -> [x0,y0,x1,y1] printable content area
    issues: list = field(default_factory=list)
    repairs: list = field(default_factory=list)
    fonts: dict = field(default_factory=dict)
    cover_pages: int = 0
    answer_sheet_pages: list = field(default_factory=list)
    images_drawn: dict = field(default_factory=dict)    # block_id -> count
    page_layouts: dict = field(default_factory=dict)


def hex_color(h: str | None, gray: bool = False, default: str = "#000000"):
    h = (h or default).strip()
    if not re.fullmatch(r"#?[0-9A-Fa-f]{6}", h):
        h = default
    c = colors.HexColor(h if h.startswith("#") else "#" + h)
    if gray:
        y = 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue
        return colors.Color(y, y, y)
    return c


def _with_alpha(c, a: float):
    return colors.Color(c.red, c.green, c.blue, alpha=max(0.0, min(1.0, a)))


def lighten(c, f: float):
    return colors.Color(c.red + (1 - c.red) * f, c.green + (1 - c.green) * f, c.blue + (1 - c.blue) * f)


class Ctx:
    def __init__(self, doc_model: dict, template: dict, resolve_asset: Callable[[str], Path | None],
                 cache_dir: Path, options: dict, repairs: dict):
        self.m = doc_model
        self.t = normalize(template)
        self.resolve = resolve_asset
        self.cache = cache_dir
        self.opt = options
        self.gray = bool(options.get("grayscale", self.t["export"]["grayscale"]))
        self.quality = options.get("quality") or self.t["export"]["quality"]
        self.repairs = repairs           # bid -> set(flags)
        self.positions: dict[str, list] = {}
        self.images_drawn: dict[str, int] = {}
        self.issues: list[dict] = []
        self.last_bid: str | None = None
        self.doc: BaseDocTemplate | None = None
        b = self.t["branding"]
        c = b["colors"]
        self.c_primary = hex_color(c["primary"], self.gray)
        self.c_secondary = hex_color(c["secondary"], self.gray)
        self.c_accent = hex_color(c["accent"], self.gray)
        self.c_text = hex_color(c["text"], self.gray)
        self.c_muted = hex_color(c["muted"], self.gray, "#64748B")
        p = self.t["page"]
        self.W, self.H = p["width_mm"] * mm, p["height_mm"] * mm
        mg = p["margins_mm"]
        self.ml, self.mr, self.mt, self.mb = mg["left"] * mm, mg["right"] * mm, mg["top"] * mm, mg["bottom"] * mm
        self.dens = DENSITY[self.t["pagination"]["density"]]
        fz = self.t["fonts"]
        self.body, n1 = F.register(fz["body"])
        self.head, n2 = F.register(fz["heading"])
        self.fb, _ = F.register(F.FALLBACK_FAMILY)
        self.font_notes = [n for n in (n1, n2) if n]
        self.missing_glyphs: dict[str, int] = {}
        self._glyph_cache: dict[tuple, bool] = {}
        self.cover_pages = 1 if self.t["cover"]["enabled"] else 0
        self.page_layout: dict[int, str] = {}
        self.answer_pages: list[int] = []
        self.styles = self._styles()

    # ---------- text
    def glyph(self, font: str, ch: str) -> bool:
        k = (font, ch)
        if k not in self._glyph_cache:
            self._glyph_cache[k] = F.has_glyph(font, ch)
        return self._glyph_cache[k]

    def mk(self, text: str, font: str | None = None) -> str:
        """Escape text for Paragraph markup and route characters missing from the font to the fallback."""
        font = font or self.body["regular"]
        out = []
        buf = []
        fb_on = False
        for ch in text or "":
            if ch == "\n":
                buf.append("\x00BR\x00")
                continue
            need_fb = ch not in " \t" and not self.glyph(font, ch)
            if need_fb and not self.glyph(self.fb["regular"], ch):
                self.missing_glyphs[ch] = self.missing_glyphs.get(ch, 0) + 1
            if need_fb != fb_on:
                out.append(escape("".join(buf)))
                buf = []
                out.append(f'<font name="{self.fb["regular"]}">' if need_fb else "</font>")
                fb_on = need_fb
            buf.append(ch)
        out.append(escape("".join(buf)))
        if fb_on:
            out.append("</font>")
        s = "".join(out).replace("\x00BR\x00", "<br/>")
        return re.sub(r"  ", " &nbsp;", s)

    def _styles(self) -> dict:
        fz = self.t["fonts"]
        lead = max(self.dens["leading"], fz.get("line_spacing", 1.3) * self.dens["leading"] / 1.3)
        sp = self.dens["space"]
        bs = fz["body_size"]
        hs = fz["heading_sizes"] + [11, 11, 11]
        widow = self.t["pagination"]["widow_orphan_control"]
        kwn = 1 if self.t["pagination"]["avoid_orphan_headings"] else 0
        base = dict(fontName=self.body["regular"], textColor=self.c_text, allowWidows=0 if widow else 1,
                    allowOrphans=0 if widow else 1)
        S = {
            "body": ParagraphStyle("body", fontSize=bs, leading=bs * lead, spaceAfter=4 * sp, alignment=TA_JUSTIFY, **base),
            "h1": ParagraphStyle("h1", fontSize=hs[0], leading=hs[0] * 1.25, spaceBefore=8 * sp, spaceAfter=6 * sp,
                                 keepWithNext=kwn, **{**base, "fontName": self.head["bold"], "textColor": self.c_secondary}),
            "h2": ParagraphStyle("h2", fontSize=hs[1], leading=hs[1] * 1.25, spaceBefore=7 * sp, spaceAfter=4 * sp,
                                 keepWithNext=kwn, **{**base, "fontName": self.head["bold"], "textColor": self.c_primary}),
            "h3": ParagraphStyle("h3", fontSize=hs[2], leading=hs[2] * 1.25, spaceBefore=5 * sp, spaceAfter=3 * sp,
                                 keepWithNext=kwn, **{**base, "fontName": self.head["bold"]}),
            "section": ParagraphStyle("section", fontSize=hs[1], leading=hs[1] * 1.3, keepWithNext=kwn,
                                      **{**base, "fontName": self.head["bold"], "textColor": colors.white}),
            "instr": ParagraphStyle("instr", fontSize=bs, leading=bs * lead, spaceAfter=4 * sp, keepWithNext=kwn,
                                    **{**base, "fontName": self.body["italic" if self.t["instructions"]["italic"] else "regular"]}),
            "q": ParagraphStyle("q", fontSize=fz["question_size"], leading=fz["question_size"] * lead,
                                leftIndent=fz["question_size"] * 2.3, bulletIndent=0,
                                bulletFontName=self.body["bold" if self.t["questions"]["bold_number"] else "regular"],
                                bulletFontSize=fz["question_size"],
                                bulletColor=hex_color(self.t["questions"]["number_color"], self.gray, self.t["branding"]["colors"]["primary"]),
                                spaceBefore=self.t["questions"]["space_between_mm"] * mm * sp, spaceAfter=2 * sp, **base),
            "opt": ParagraphStyle("opt", fontSize=fz["option_size"], leading=fz["option_size"] * lead,
                                  leftIndent=fz["question_size"] * 2.3 + fz["option_size"] * 2.0,
                                  bulletIndent=fz["question_size"] * 2.3, bulletFontName=self.body["bold"],
                                  bulletFontSize=fz["option_size"], spaceAfter=1 * sp, **base),
            "optcell": ParagraphStyle("optcell", fontSize=fz["option_size"], leading=fz["option_size"] * lead, **base),
            "cell": ParagraphStyle("cell", fontSize=self.t["tables"]["font_size"], leading=self.t["tables"]["font_size"] * 1.25, **base),
            "caption": ParagraphStyle("caption", fontSize=bs * 0.85, leading=bs * 1.1, alignment=TA_CENTER,
                                      textColor=self.c_muted, fontName=self.body["italic"]),
            "small": ParagraphStyle("small", fontSize=8, leading=10, textColor=self.c_muted, fontName=self.body["regular"]),
        }
        S["cellh"] = ParagraphStyle("cellh", parent=S["cell"], fontName=self.body["bold"],
                                    textColor=hex_color(self.t["tables"]["header_color"], self.gray, "#FFFFFF"))
        return S

    def styled(self, base: ParagraphStyle, st: dict | None, name: str) -> ParagraphStyle:
        if not st:
            return base
        kw = {}
        if st.get("font_size"):
            fs = float(st["font_size"])
            kw.update(fontSize=fs, leading=fs * (base.leading / max(base.fontSize, 1)))
        fam = None
        if st.get("font_family"):
            fam, note = F.register(st["font_family"])
            if note:
                self.font_notes.append(note)
        fam = fam or (self.head if base.name in ("h1", "h2", "h3", "section") else self.body)
        b, i = st.get("bold"), st.get("italic")
        if b is not None or i is not None or st.get("font_family"):
            bold = b if b is not None else "bold" in base.fontName.lower()
            ital = i if i is not None else "italic" in base.fontName.lower()
            kw["fontName"] = fam["bolditalic" if bold and ital else "bold" if bold else "italic" if ital else "regular"]
        if st.get("align") in ALIGN:
            kw["alignment"] = ALIGN[st["align"]]
        if st.get("color"):
            kw["textColor"] = hex_color(st["color"], self.gray)
        if st.get("space_before") is not None:
            kw["spaceBefore"] = float(st["space_before"]) * mm
        if st.get("space_after") is not None:
            kw["spaceAfter"] = float(st["space_after"]) * mm
        if st.get("bg"):
            kw["backColor"] = hex_color(st["bg"], self.gray)
        if st.get("padding") is not None:
            kw["borderPadding"] = float(st["padding"]) * mm
        if st.get("border"):
            kw["borderWidth"] = float(st.get("border_width", 0.8))
            kw["borderColor"] = hex_color(st.get("border"), self.gray)
        if st.get("indent") is not None:
            kw["leftIndent"] = base.leftIndent + float(st["indent"]) * mm
        return ParagraphStyle(name, parent=base, **kw) if kw else base

    # ---------- tracking
    def track(self, fl: Flowable, bid: str) -> Flowable:
        ctx = self
        orig_wrap, orig_draw = fl.wrap, fl.drawOn
        orig_split = getattr(fl, "split", None)

        def wrap(aW, aH):
            ctx.last_bid = bid
            w, h = orig_wrap(aW, aH)
            fl._ptd_wh = (w, h)
            return w, h

        def drawOn(canv, x, y, _sW=0):
            w, h = getattr(fl, "_ptd_wh", (0, 0))
            if isinstance(fl, Paragraph):
                w = fl.width
            page = ctx.doc.page if ctx.doc else 1
            ctx.positions.setdefault(bid, []).append(
                {"page": page, "x0": round(x, 2), "y0": round(ctx.H - (y + h), 2),
                 "x1": round(x + w, 2), "y1": round(ctx.H - y, 2)})
            if getattr(fl, "_ptd_image", False):
                ctx.images_drawn[bid] = ctx.images_drawn.get(bid, 0) + 1
            return orig_draw(canv, x, y, _sW)

        fl.wrap = wrap
        fl.drawOn = drawOn
        if orig_split is not None:
            def split(aW, aH):
                parts = orig_split(aW, aH)
                for p in parts:
                    if p is not fl:
                        ctx.track(p, bid)
                return parts
            fl.split = split
        return fl

    def frame_width(self, layout: str) -> float:
        cols = self.columns(layout)
        gap = self.t["page"]["column_gap_mm"] * mm
        return (self.W - self.ml - self.mr - gap * (cols - 1)) / cols

    def frame_height(self) -> float:
        return self.H - self.mt - self.mb

    def columns(self, layout: str) -> int:
        lay = self.t["layouts"].get(layout) or {}
        c = lay.get("columns") or self.t["page"]["columns"] or 1
        return max(1, min(3, int(c)))


# ====================================================================== flowables
class Lines(Flowable):
    """Ruled answer lines."""

    def __init__(self, n: int, color, gap: float = 8 * mm, indent: float = 0):
        super().__init__()
        self.n, self.color, self.gap, self.indent = n, color, gap, indent

    def wrap(self, aW, aH):
        self.width = aW
        return aW, self.n * self.gap + 2

    def draw(self):
        c = self.canv
        c.setStrokeColor(self.color)
        c.setLineWidth(0.5)
        for i in range(self.n):
            y = (self.n - i - 1) * self.gap + 2
            c.line(self.indent, y, self.width, y)


class SectionBar(Flowable):
    def __init__(self, para: Paragraph, color, style: str, badge_color):
        super().__init__()
        self.p, self.color, self.style, self.badge = para, color, style, badge_color
        self.keepWithNext = 1

    def wrap(self, aW, aH):
        self.width = aW
        _, h = self.p.wrap(aW - 16, aH)
        self.ph = h
        self.height = h + (10 if self.style == "bar" else 6)
        return aW, self.height + 8

    def draw(self):
        c = self.canv
        if self.style == "bar":
            c.setFillColor(self.color)
            c.roundRect(0, 0, self.width, self.height, 3, stroke=0, fill=1)
            c.setFillColor(self.badge)
            c.rect(0, 0, 4, self.height, stroke=0, fill=1)
            self.p.drawOn(c, 10, 5)
        else:
            self.p.drawOn(c, 0, 6)
            c.setStrokeColor(self.color)
            c.setLineWidth(1.6 if self.style == "underline" else 0)
            if self.style == "underline":
                c.line(0, 2, self.width, 2)


class BubbleRow(Flowable):
    def __init__(self, number: str, n: int, font: str, color, width: float):
        super().__init__()
        self.number, self.n, self.font, self.color, self.w = number, n, font, color, width

    def wrap(self, aW, aH):
        return self.w, 7.2 * mm

    def draw(self):
        c = self.canv
        c.setFont(self.font, 8.5)
        c.setFillColor(colors.black)
        c.drawRightString(8 * mm, 2.2 * mm, f"{self.number}.")
        for i in range(self.n):
            x = 12 * mm + i * 8 * mm
            c.setStrokeColor(self.color)
            c.setLineWidth(0.7)
            c.circle(x, 3.2 * mm, 2.6 * mm, stroke=1, fill=0)
            c.setFont(self.font, 7)
            c.drawCentredString(x, 2.25 * mm, chr(65 + i))


class OpacityImage(RLImage):
    """Image with opacity that may shrink (down to `min_frac`) to use the space left on a page,
    so a large map stays with its heading instead of leaving a near-empty page behind."""

    def __init__(self, *a, opacity: float = 1.0, min_frac: float = 1.0, **kw):
        super().__init__(*a, **kw)
        self.opacity = opacity
        self._ptd_image = True
        self.min_frac = min_frac
        self._full = (self.drawWidth, self.drawHeight)

    def wrap(self, aW, aH):
        w, h = self._full
        if self.min_frac < 1:
            if aH > 1e6:   # measured inside KeepTogether: report the smallest acceptable size
                w, h = w * self.min_frac, h * self.min_frac
            elif h > aH >= h * self.min_frac:
                w, h = w * aH / h, aH
        self.drawWidth, self.drawHeight = w, h
        return w, h

    def draw(self):
        if self.opacity < 1:
            self.canv.saveState()
            self.canv.setFillAlpha(self.opacity)
            super().draw()
            self.canv.restoreState()
        else:
            super().draw()


class SvgFlowable(Flowable):
    def __init__(self, drawing, w, h, align="CENTER"):
        super().__init__()
        self.d, self.w, self.h = drawing, w, h
        self.hAlign = align
        self._ptd_image = True

    def wrap(self, aW, aH):
        return self.w, self.h

    def draw(self):
        from reportlab.graphics import renderPDF
        sx = self.w / max(self.d.width, 1)
        sy = self.h / max(self.d.height, 1)
        self.canv.saveState()
        self.canv.scale(sx, sy)
        renderPDF.draw(self.d, self.canv, 0, 0)
        self.canv.restoreState()


# ====================================================================== builders
class Builder:
    def __init__(self, ctx: Ctx):
        self.c = ctx
        self.t = ctx.t
        self.layout = "standard"

    # ---- images
    def image_flowable(self, spec: dict, bid: str, max_w: float, max_h: float, layout: str = "center",
                       st: dict | None = None, min_frac: float = 1.0):
        c = self.c
        path = c.resolve(spec.get("asset")) if spec.get("asset") else None
        if not path or not Path(path).exists():
            c.issues.append({"level": "critical", "code": "missing_image", "block": bid,
                             "message": "An image file referenced by the document is missing."})
            return None
        path = Path(path)
        st = st or {}
        flags = c.repairs.get(bid, set())
        shrink = 0.8 ** sum(1 for f in flags if f == "shrink_image") if "shrink_image" in flags else 1.0
        if path.suffix.lower() == ".svg":
            from svglib.svglib import svg2rlg
            d = svg2rlg(str(path))
            iw, ih = d.width or 100, d.height or 100
        else:
            info = imgs.probe(path)
            iw, ih = info["width"] or 1, info["height"] or 1
        aspect = iw / ih
        if st.get("width_mm"):
            w = float(st["width_mm"]) * mm
        elif layout == "full":
            w = max_w
        elif layout == "inline":
            w = min(max_w, iw / 150 * 72)
        else:
            w = max_w * (float(st.get("width_pct") or self.t["images"]["max_width_pct"]) / 100)
            w = min(w, iw / 96 * 72 * 1.6) if iw < 600 else w  # don't blow up small pictures
        w = min(w, max_w) * shrink
        h = w / aspect
        if h > max_h * shrink:
            h = max_h * shrink
            w = h * aspect
        align = (st.get("align") or self.t["images"]["align"]).upper()
        if path.suffix.lower() == ".svg":
            fl = SvgFlowable(d, w, h, align)
        else:
            prepared, pinfo = imgs.prepare_for_pdf(path, c.cache, w, h, c.quality, c.gray)
            fl = OpacityImage(str(prepared), width=w, height=h, opacity=float(st.get("opacity", 1) or 1),
                              min_frac=1.0 if st.get("width_mm") else min_frac)
            fl.hAlign = align
            if pinfo["effective_dpi"] < 110 and w > 60 * mm:
                c.issues.append({"level": "warning", "code": "low_resolution_image", "block": bid,
                                 "message": f"Image resolution is low ({pinfo['effective_dpi']} dpi at printed size); it may look blurry."})
        return fl

    # ---- blocks
    def heading(self, b):
        lvl = int(b.get("level") or 2)
        st = self.c.styled(self.c.styles["h1" if lvl <= 1 else "h2" if lvl == 2 else "h3"], b.get("style"), "h_" + b["id"])
        return [Paragraph(self.c.mk(b.get("text", ""), st.fontName), st)]

    def section(self, b):
        sc = self.t["sections"]
        title = b.get("title", "")
        st_base = self.c.styles["section"] if sc["style"] == "bar" else ParagraphStyle(
            "secp", parent=self.c.styles["h2"], textColor=hex_color(sc.get("color"), self.c.gray, self.t["branding"]["colors"]["primary"]))
        st = self.c.styled(st_base, b.get("style"), "s_" + b["id"])
        text = self.c.mk(title, st.fontName)
        if sc["uppercase"]:
            # display-only transform: the stored title is untouched
            text = self.c.mk(title.upper(), st.fontName)
        color = hex_color(sc.get("color"), self.c.gray, self.t["branding"]["colors"]["primary"])
        return [Spacer(1, 4 * self.c.dens["space"]), SectionBar(Paragraph(text, st), color, sc["style"], self.c.c_accent)]

    def instruction(self, b):
        st = self.c.styled(self.c.styles["instr"], b.get("style"), "i_" + b["id"])
        p = Paragraph(self.c.mk(b.get("text", ""), st.fontName), st)
        if self.t["instructions"]["style"] == "box" and "no_box" not in self.c.repairs.get(b["id"], set()):
            tb = Table([[p]], colWidths=[None])
            tb.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), self.c.body["regular"]), ("BACKGROUND", (0, 0), (-1, -1), lighten(self.c.c_primary, 0.92)),
                                    ("LINEBEFORE", (0, 0), (0, -1), 2.5, self.c.c_primary),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            tb.keepWithNext = 1
            return [tb, Spacer(1, 4)]
        return [p]

    def paragraph(self, b):
        st = self.c.styled(self.c.styles["body"], b.get("style"), "p_" + b["id"])
        return [Paragraph(self.c.mk(b.get("text", ""), st.fontName), st)]

    def option_label(self, label: str) -> str:
        q = self.t["questions"]
        case = q["option_label_case"]
        L = label.upper() if case == "upper" else label.lower() if case == "lower" else label
        return q["option_label_format"].replace("{L}", L)

    def question(self, b, fw):
        c = self.c
        q = self.t["questions"]
        bid = b["id"]
        st = c.styled(c.styles["q"], b.get("style"), "q_" + bid)
        num = q["number_format"].replace("{n}", str(b.get("number") or "")) if b.get("number") else None
        text = b.get("text", "")
        body = c.mk(text, st.fontName)
        if q["show_points"] and b.get("points"):
            body += f' <font color="#64748B" size="{st.fontSize * 0.85:.1f}">({escape(str(b["points"]))} pt)</font>'
        parts: list[Flowable] = [Paragraph(body or "&nbsp;", st, bulletText=num)]
        opts = b.get("options") or []
        indent = st.leftIndent
        if opts:
            parts += self.options(opts, fw, indent, b)
        for im in b.get("images") or []:
            fl = self.image_flowable(im, bid, fw - indent, c.frame_height() * self.t["images"]["max_height_pct"] / 100,
                                     im.get("layout", "center"), im.get("style"), min_frac=0.8)
            if fl is not None:
                parts.append(Spacer(1, 3))
                parts.append(fl)
        lines = int(b.get("answer_lines") or (q["answer_lines"] if b.get("qtype") in ("open", "writing", "translation", "transformation") else 0))
        if lines:
            parts.append(Lines(lines, lighten(c.c_muted, 0.4), indent=indent))
        flags = c.repairs.get(bid, set())
        if q["box"] and "no_box" not in flags:
            box = Table([[parts]], colWidths=[fw])
            box.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), self.c.body["regular"]), ("BACKGROUND", (0, 0), (-1, -1), hex_color(q["box_color"], c.gray)),
                                     ("BOX", (0, 0), (-1, -1), 0.6, lighten(c.c_primary, 0.6)),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                                     ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            parts = [Spacer(1, 3 * c.dens["space"]), box]
        keep = q["keep_together"] and self.t["pagination"]["keep_options_with_question"]
        st_keep = (b.get("style") or {}).get("keep_together")
        if st_keep is not None:
            keep = bool(st_keep)
        if keep and "no_keep" not in flags:
            return [KeepTogether(parts)]
        return parts

    def options(self, opts, fw, indent, b):
        c = self.c
        q = self.t["questions"]
        mode = (b.get("style") or {}).get("option_layout") or q["option_layout"]
        so = c.styles["opt"]
        fs = so.fontSize
        labels = [self.option_label(o.get("label", "")) for o in opts]
        if mode == "auto":
            widths = [stringWidth(l + " ", c.body["bold"], fs) + stringWidth(o.get("text", ""), so.fontName, fs) + 14
                      for l, o in zip(labels, opts)]
            avail = fw - indent
            longest = max(widths) if widths else 0
            if len(opts) >= 3 and longest <= avail / 4 and len(opts) <= 4:
                mode = "grid4"
            elif len(opts) >= 2 and longest <= avail / 2:
                mode = "two_column"
            else:
                mode = "vertical"
        if mode == "vertical":
            return [Paragraph(c.mk(o.get("text", "") or " ", so.fontName), so, bulletText=l) for l, o in zip(labels, opts)]
        ncol = 4 if mode in ("grid", "grid4") else 2
        cells = [Paragraph(f'<font name="{c.body["bold"]}">{escape(l)}</font> {c.mk(o.get("text", ""), so.fontName)}', c.styles["optcell"])
                 for l, o in zip(labels, opts)]
        rows = [cells[i:i + ncol] for i in range(0, len(cells), ncol)]
        rows[-1] += [""] * (ncol - len(rows[-1]))
        cw = (fw - indent) / ncol
        tb = Table(rows, colWidths=[cw] * ncol, hAlign="LEFT")
        tb.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), self.c.body["regular"]), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                                ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                                ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        holder = Table([["", tb]], colWidths=[indent, fw - indent], hAlign="LEFT")
        holder.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), self.c.body["regular"]), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return [holder]

    def table(self, b, fw):
        c = self.c
        tc = self.t["tables"]
        bid = b["id"]
        rows = [list(map(lambda v: "" if v is None else str(v), r)) for r in (b.get("rows") or [])]
        if not rows:
            return []
        ncol = max(len(r) for r in rows)
        rows = [r + [""] * (ncol - len(r)) for r in rows]
        hdr = int(b.get("header_rows", 1) or 0)
        flags = c.repairs.get(bid, set())
        fs = float((b.get("style") or {}).get("font_size") or tc["font_size"])
        pad = 8
        while True:
            body_font = c.body["regular"]
            nat, mins = [], []
            for j in range(ncol):
                col = [r[j] for r in rows]
                nat.append(min(fw, max(stringWidth(v, body_font, fs) for v in col) + pad))
                mins.append(max(max((stringWidth(w, c.body["bold"], fs) for v in col for w in v.split()), default=10) + pad, 14))
            if sum(mins) <= fw or fs <= tc["min_font_size"]:
                break
            fs -= 0.5
        if sum(mins) > fw:
            c.issues.append({"level": "warning", "code": "table_too_wide", "block": bid,
                             "message": "A table has very long words and is wider than the page even at the minimum font size; some cell text may be tight."})
            widths = [fw / ncol] * ncol
        elif sum(nat) <= fw:
            widths = [n * fw / sum(nat) for n in nat]
        else:
            extra = fw - sum(mins)
            want = [max(n - m, 0) for n, m in zip(nat, mins)]
            tw = sum(want) or 1
            widths = [m + extra * w / tw for m, w in zip(mins, want)]
        if fs < tc["font_size"]:
            c.issues.append({"level": "info", "code": "table_font_reduced", "block": bid,
                             "message": f"Table font reduced to {fs:.1f} pt so all columns fit the page width."})
        cs = ParagraphStyle("cell_" + bid, parent=c.styles["cell"], fontSize=fs, leading=fs * 1.25)
        ch = ParagraphStyle("cellh_" + bid, parent=c.styles["cellh"], fontSize=fs, leading=fs * 1.25)
        data = [[Paragraph(c.mk(v, (ch if i < hdr else cs).fontName), ch if i < hdr else cs) for v in r]
                for i, r in enumerate(rows)]
        tb = Table(data, colWidths=widths, repeatRows=hdr if (tc["repeat_header"] and hdr and len(rows) > hdr) else 0,
                   splitByRow=1, splitInRow=1 if "split_rows" in flags else 0, hAlign="LEFT")
        border = hex_color(tc["border_color"], c.gray)
        hbg = hex_color(tc["header_bg"], c.gray, self.t["branding"]["colors"]["primary"])
        style = [("FONTNAME", (0, 0), (-1, -1), c.body["regular"]),
                 ("GRID", (0, 0), (-1, -1), 0.5, border), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                 ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if hdr:
            style.append(("BACKGROUND", (0, 0), (-1, hdr - 1), hbg))
        if tc["stripe"]:
            style.append(("ROWBACKGROUNDS", (0, hdr), (-1, -1), [colors.white, hex_color(tc["stripe_color"], c.gray)]))
        tb.setStyle(TableStyle(style))
        out: list[Flowable] = [Spacer(1, 4), tb, Spacer(1, 6)]
        if "cond_break" in flags:
            out.insert(0, CondPageBreak((fs * 1.25 + 6) * (hdr + 3)))
        if len(rows) <= 6 and "no_keep" not in flags:
            return [KeepTogether(out)]   # small tables never split
        return out

    def image_block(self, b, fw):
        c = self.c
        kind = b.get("kind", "image")
        layout = b.get("layout") or "center"
        st = b.get("style") or {}
        max_h = c.frame_height() * (0.92 if (kind in ("map", "diagram") and self.t["images"]["full_width_maps"]) or layout == "full"
                                    else self.t["images"]["max_height_pct"] / 100)
        if kind in ("map", "diagram") and self.t["images"]["full_width_maps"] and not st.get("width_mm") and not st.get("width_pct"):
            layout = "full"
        fl = self.image_flowable(b, b["id"], fw, max_h - (14 if b.get("caption") else 0), layout, st, min_frac=0.6)
        if fl is None:
            return []
        out = [Spacer(1, 4), fl]
        if b.get("caption"):
            out.append(Paragraph(c.mk(b["caption"], c.styles["caption"].fontName), c.styles["caption"]))
        out.append(Spacer(1, 6))
        return [KeepTogether(out)]

    def answer_space(self, b, fw):
        return [Lines(int(b.get("lines") or 3), lighten(self.c.c_muted, 0.4))]

    def answer_sheet(self, qs: list[dict], fw: float):
        c = self.c
        nopt = max([len(q.get("options") or []) for q in qs] + [self.t["answer_sheet"]["options"]])
        nopt = min(nopt, 8)
        colw = 14 * mm + nopt * 8 * mm
        ncols = max(1, int(fw // (colw + 6 * mm)))
        cells = [BubbleRow(str(q.get("number") or i + 1), max(len(q.get("options") or []), 2), c.body["bold"], c.c_primary, colw)
                 for i, q in enumerate(qs)]
        per_col = -(-len(cells) // ncols)
        cols = [cells[i * per_col:(i + 1) * per_col] for i in range(ncols)]
        rows = [[col[r] if r < len(col) else "" for col in cols] for r in range(per_col)]
        tb = Table(rows, colWidths=[fw / ncols] * ncols, hAlign="LEFT", repeatRows=0)
        tb.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), self.c.body["regular"]), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        res = Table([[Paragraph("<b>Score</b>", c.styles["cell"]), Paragraph("<b>Grade</b>", c.styles["cell"]),
                      Paragraph("<b>Examiner</b>", c.styles["cell"]), Paragraph("<b>Signature</b>", c.styles["cell"])],
                     ["", "", "", ""]], colWidths=[fw / 4] * 4, rowHeights=[None, 12 * mm])
        res.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), self.c.body["regular"]), ("GRID", (0, 0), (-1, -1), 0.6, c.c_primary),
                                 ("BACKGROUND", (0, 0), (-1, 0), lighten(c.c_primary, 0.88))]))
        title = ParagraphStyle("as_t", parent=c.styles["h2"])
        return [Paragraph("Answer Sheet", title),
                Paragraph(c.mk("Fill in one circle for each question."), c.styles["instr"]), Spacer(1, 4), tb,
                Spacer(1, 10), KeepTogether([Paragraph("Results", c.styles["h3"]), res])]


# ====================================================================== page furniture
class Furniture:
    def __init__(self, ctx: Ctx):
        self.c = ctx
        self.t = ctx.t

    def _logo(self, canv, asset, x, y, max_w, max_h, anchor="left", badge=False):
        """Draw a logo fitted into max_w x max_h. On dark bands (badge=True) it sits on a white badge
        so dark-on-white logos stay legible."""
        if not asset:
            return 0
        p = self.c.resolve(asset)
        if not p or not Path(p).exists():
            self.c.issues.append({"level": "warning", "code": "missing_logo", "message": "The template logo file is missing."})
            return 0
        p = Path(p)
        pad = 0.12 if badge else 0.0
        inner_w, inner_h = max_w * (1 - 2 * pad), max_h * (1 - 2 * pad)
        if p.suffix.lower() == ".svg":
            from svglib.svglib import svg2rlg
            d = svg2rlg(str(p))
            iw, ih = max(d.width, 1), max(d.height, 1)
        else:
            info = imgs.probe(p)
            iw, ih = max(info["width"], 1), max(info["height"], 1)
        s = min(inner_w / iw, inner_h / ih)
        w, h = iw * s, ih * s
        bw, bh = (w / (1 - 2 * pad), h / (1 - 2 * pad)) if badge else (w, h)
        bx = x - bw if anchor == "right" else x - bw / 2 if anchor == "center" else x
        by = y + (max_h - bh) / 2
        if badge:
            canv.saveState()
            canv.setFillColor(colors.white)
            if abs(iw - ih) / max(iw, ih) < 0.15:
                r = max(bw, bh) / 2
                canv.circle(bx + bw / 2, by + bh / 2, r, stroke=0, fill=1)
            else:
                canv.roundRect(bx, by, bw, bh, min(bw, bh) * 0.18, stroke=0, fill=1)
            canv.restoreState()
        lx, ly = bx + (bw - w) / 2, by + (bh - h) / 2
        if p.suffix.lower() == ".svg":
            from reportlab.graphics import renderPDF
            canv.saveState()
            canv.translate(lx, ly)
            canv.scale(s, s)
            renderPDF.draw(d, canv, 0, 0)
            canv.restoreState()
            return bw
        prepared, pinfo = imgs.prepare_for_pdf(p, self.c.cache, w, h, self.c.quality, self.c.gray)
        if pinfo["effective_dpi"] < 150 and not any(i["code"] == "low_resolution_logo" for i in self.c.issues):
            self.c.issues.append({"level": "warning", "code": "low_resolution_logo",
                                  "message": f"The logo is low resolution ({pinfo['effective_dpi']} dpi at printed size). Upload a larger PNG or an SVG for sharp printing."})
        canv.drawImage(str(prepared), lx, ly, w, h, mask="auto")
        return bw

    def background(self, canv, doc):
        c = self.c
        pg = self.t["page"]["background"]
        if pg.get("color"):
            canv.setFillColor(hex_color(pg["color"], c.gray))
            canv.rect(0, 0, c.W, c.H, stroke=0, fill=1)
        if pg.get("image_asset"):
            p = c.resolve(pg["image_asset"])
            if p and Path(p).exists():
                prepared, _ = imgs.prepare_for_pdf(Path(p), c.cache, c.W, c.H, c.quality, c.gray)
                canv.saveState()
                canv.setFillAlpha(float(pg.get("image_opacity", 0.15)))
                canv.drawImage(str(prepared), 0, 0, c.W, c.H, preserveAspectRatio=False, mask="auto")
                canv.restoreState()
        if self.t["page"]["content_panel"]:
            canv.setFillColor(hex_color(self.t["branding"]["colors"]["panel_bg"], c.gray, "#FFFFFF"))
            canv.setStrokeColor(lighten(c.c_primary, 0.8))
            canv.roundRect(c.ml - 4 * mm, c.mb - 3 * mm, c.W - c.ml - c.mr + 8 * mm, c.H - c.mt - c.mb + 6 * mm, 6, stroke=1, fill=1)

    def watermark(self, canv):
        c = self.c
        wm = self.t["branding"]["watermark"]
        if not wm or wm.get("type") in (None, "none"):
            return
        canv.saveState()
        canv.setFillAlpha(float(wm.get("opacity", 0.06)))
        canv.translate(c.W / 2, c.H / 2)
        canv.rotate(float(wm.get("angle", 45)))
        if wm.get("type") == "image" and wm.get("asset"):
            p = c.resolve(wm["asset"])
            if p and Path(p).exists():
                info = imgs.probe(Path(p)) if Path(p).suffix.lower() != ".svg" else {"width": 1, "height": 1}
                size = min(c.W, c.H) * 0.6
                s = size / max(info["width"], info["height"], 1)
                w, h = info["width"] * s, info["height"] * s
                if Path(p).suffix.lower() != ".svg":
                    prepared, _ = imgs.prepare_for_pdf(Path(p), c.cache, w, h, "standard", c.gray)
                    canv.drawImage(str(prepared), -w / 2, -h / 2, w, h, mask="auto")
        else:
            text = wm.get("text") or self.t["branding"]["org_name"]
            size = float(wm.get("size", 54))
            font = c.head["bold"]
            while stringWidth(text, font, size) > max(c.W, c.H) * 0.9 and size > 12:
                size -= 2
            canv.setFont(font, size)
            p = c.c_primary
            # colour first, alpha second: setFillColor() would reset the alpha
            canv.setFillColor(colors.Color(p.red, p.green, p.blue))
            canv.setFillAlpha(float(wm.get("opacity", 0.06)))
            canv.drawCentredString(0, -size / 3, text)
        canv.restoreState()

    def header(self, canv, layout: str):
        c = self.c
        h = self.t["header"]
        if not h["enabled"]:
            return
        b = self.t["branding"]
        title = h.get("text") or b.get("header_text") or b.get("exam_title") or c.m.get("title") or ""
        hh = h["height_mm"] * mm
        top = c.H - (c.mt - hh) / 2 - 2 * mm
        y0 = top - hh
        badge = (self.t["layouts"].get(layout) or {}).get("badge")
        if h["style"] == "band":
            canv.setFillColor(c.c_secondary)
            canv.rect(0, y0 - 2 * mm, c.W, c.H - y0 + 2 * mm, stroke=0, fill=1)
            canv.setFillColor(c.c_accent)
            canv.rect(0, y0 - 3.2 * mm, c.W, 1.2 * mm, stroke=0, fill=1)
            tc = colors.white
        else:
            tc = c.c_secondary
        x = c.ml
        if h["show_logo"] and b.get("logo_asset"):
            x += self._logo(canv, b["logo_asset"], x, y0, 30 * mm, hh, badge=h["style"] == "band") + 3 * mm
        canv.setFillColor(tc)
        if h["show_org"]:
            canv.setFont(c.head["bold"], 11.5)
            canv.drawString(x, y0 + hh * 0.55, self._fit(b.get("org_name", ""), c.head["bold"], 11.5, c.W * 0.45))
            if b.get("teacher_name") or b.get("contact"):
                canv.setFont(c.body["regular"], 7.5)
                canv.drawString(x, y0 + hh * 0.18, self._fit(" · ".join(v for v in (b.get("teacher_name"), b.get("contact")) if v),
                                                            c.body["regular"], 7.5, c.W * 0.45))
        right = c.W - c.mr
        if b.get("secondary_logo_asset"):
            right -= self._logo(canv, b["secondary_logo_asset"], right, y0, 24 * mm, hh, "right", badge=h["style"] == "band") + 3 * mm
        if h["show_title"] and title:
            canv.setFont(c.body["bold"], 9.5)
            canv.drawRightString(right, y0 + hh * 0.55, self._fit(title, c.body["bold"], 9.5, c.W * 0.4))
        if badge:
            canv.setFont(c.body["bold"], 7.5)
            bw = stringWidth(badge, c.body["bold"], 7.5) + 10
            canv.setFillColor(c.c_accent)
            canv.roundRect(right - bw, y0 + hh * 0.12, bw, 11, 3, stroke=0, fill=1)
            canv.setFillColor(colors.white)
            canv.drawCentredString(right - bw / 2, y0 + hh * 0.12 + 3.2, badge)
        if h["style"] == "line":
            canv.setStrokeColor(c.c_primary)
            canv.setLineWidth(1.2)
            canv.line(c.ml, y0 - 1.5 * mm, c.W - c.mr, y0 - 1.5 * mm)
            canv.setStrokeColor(c.c_accent)
            canv.setLineWidth(2.2)
            canv.line(c.ml, y0 - 1.5 * mm, c.ml + 18 * mm, y0 - 1.5 * mm)

    def _fit(self, s: str, font: str, size: float, maxw: float) -> str:
        if stringWidth(s, font, size) <= maxw:
            return s
        while s and stringWidth(s + "…", font, size) > maxw:
            s = s[:-1]
        return s + "…"

    def footer_static(self, canv):
        c = self.c
        f = self.t["footer"]
        if not f["enabled"]:
            return
        text = f.get("text") if f.get("text") is not None else self.t["branding"].get("footer_text", "")
        y = c.mb / 2 - 2
        canv.setStrokeColor(lighten(c.c_primary, 0.7))
        canv.setLineWidth(0.6)
        canv.line(c.ml, c.mb - 5 * mm, c.W - c.mr, c.mb - 5 * mm)
        if text:
            canv.setFont(c.body["regular"], 7.5)
            canv.setFillColor(c.c_muted)
            pos = f["align"]
            maxw = (c.W - c.ml - c.mr) * (0.62 if f["show_page_numbers"] else 1)
            s = self._fit(text, c.body["regular"], 7.5, maxw)
            if f["show_page_numbers"] and pos in ("center", "right"):
                canv.drawString(c.ml, y, s)
            elif pos == "center":
                canv.drawCentredString(c.W / 2, y, s)
            else:
                canv.drawString(c.ml, y, s)

    def page_number(self, canv, page: int, total: int):
        c = self.c
        f = self.t["footer"]
        if not (f["enabled"] and f["show_page_numbers"]):
            return
        offset = 0 if f["number_cover"] else c.cover_pages
        if page <= offset:
            return
        s = f["page_number_format"].replace("{page}", str(page - offset)).replace("{total}", str(total - offset))
        canv.setFont(c.body["bold"], 8)
        canv.setFillColor(c.c_secondary)
        y = c.mb / 2 - 2
        if f["align"] == "center" and not (f.get("text") or self.t["branding"].get("footer_text")):
            canv.drawCentredString(c.W / 2, y, s)
        else:
            canv.drawRightString(c.W - c.mr, y, s)

    def cover(self, canv, doc):
        c = self.c
        cv = self.t["cover"]
        b = self.t["branding"]
        W, H = c.W, c.H
        title = cv.get("title") or b.get("exam_title") or c.m.get("title") or "Examination"
        style = cv.get("style", "classic")
        if style == "band":
            canv.setFillColor(c.c_secondary)
            canv.rect(0, H * 0.62, W, H * 0.38, stroke=0, fill=1)
            canv.setFillColor(c.c_accent)
            canv.rect(0, H * 0.62 - 2.2 * mm, W, 2.2 * mm, stroke=0, fill=1)
            canv.setFillColor(c.c_primary)
            canv.rect(0, 0, W, 9 * mm, stroke=0, fill=1)
            tcol = colors.white
            logo_y = H * 0.82
        else:
            canv.setStrokeColor(c.c_primary)
            canv.setLineWidth(2)
            canv.rect(12 * mm, 12 * mm, W - 24 * mm, H - 24 * mm, stroke=1, fill=0)
            canv.setStrokeColor(c.c_accent)
            canv.setLineWidth(0.8)
            canv.rect(14.5 * mm, 14.5 * mm, W - 29 * mm, H - 29 * mm, stroke=1, fill=0)
            tcol = c.c_secondary
            logo_y = H * 0.78
        if cv["show_logo"] and b.get("logo_asset"):
            self._logo(canv, b["logo_asset"], W / 2, logo_y, 46 * mm, 30 * mm, "center", badge=style == "band")
        canv.setFillColor(tcol)
        size = 20
        org = b.get("org_name", "")
        while stringWidth(org, c.head["bold"], size) > W - 50 * mm and size > 10:
            size -= 1
        canv.setFont(c.head["bold"], size)
        canv.drawCentredString(W / 2, logo_y - 10 * mm, org)
        # title (wrapped)
        ts = ParagraphStyle("cv_t", fontName=c.head["bold"], fontSize=26, leading=31, alignment=TA_CENTER,
                            textColor=tcol if style == "band" else c.c_primary)
        tp = Paragraph(c.mk(title, c.head["bold"]), ts)
        _, th = tp.wrap(W - 50 * mm, H)
        ty = logo_y - 22 * mm - th
        tp.drawOn(canv, 25 * mm, ty)
        sub = cv.get("subtitle") or ""
        y = ty - 10 * mm
        if style == "band":
            y = H * 0.55
        if sub:
            sp = Paragraph(c.mk(sub), ParagraphStyle("cv_s", fontName=c.body["regular"], fontSize=13, leading=17,
                                                     alignment=TA_CENTER, textColor=c.c_muted))
            _, sh = sp.wrap(W - 50 * mm, H)
            sp.drawOn(canv, 25 * mm, y - sh)
            y -= sh + 8 * mm
        if cv.get("show_stats"):
            st = M.stats(c.m)
            line = f"Questions: {st['questions']}"
            if b.get("teacher_name"):
                line += f"   ·   Teacher: {b['teacher_name']}"
            canv.setFont(c.body["regular"], 10.5)
            canv.setFillColor(c.c_muted)
            canv.drawCentredString(W / 2, y, line)
            y -= 14 * mm
        # candidate fields
        fields = cv.get("fields") or []
        fx0, fx1 = 32 * mm, W - 32 * mm
        y = min(y, H * 0.42)
        for fname in fields:
            canv.setFont(c.body["bold"], 10.5)
            canv.setFillColor(c.c_secondary)
            canv.drawString(fx0, y, f"{fname}:")
            lw = stringWidth(f"{fname}:", c.body["bold"], 10.5) + 4
            canv.setStrokeColor(c.c_muted)
            canv.setLineWidth(0.6)
            canv.line(fx0 + lw, y - 1.5, fx1, y - 1.5)
            y -= 11 * mm
        if cv.get("instructions"):
            ip = Paragraph(c.mk(cv["instructions"]), ParagraphStyle("cv_i", fontName=c.body["regular"], fontSize=9.5,
                                                                     leading=13, textColor=c.c_text))
            _, ih = ip.wrap(fx1 - fx0, H)
            ip.drawOn(canv, fx0, max(22 * mm, y - ih))
        if b.get("contact"):
            canv.setFont(c.body["regular"], 8)
            canv.setFillColor(colors.white if style == "band" else c.c_muted)
            canv.drawCentredString(W / 2, 3.5 * mm if style == "band" else 18 * mm, b["contact"])


def _make_canvas(ctx: Ctx, furn: Furniture):
    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *a, **kw):
            # embedded body font as the initial font, so no non-embedded Helvetica reference is written
            if not kw.get("initialFontName"):
                kw["initialFontName"] = ctx.body["regular"]
            super().__init__(*a, **kw)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for i, state in enumerate(self._saved):
                self.__dict__.update(state)
                furn.page_number(self, i + 1, total)
                rl_canvas.Canvas.showPage(self)
            rl_canvas.Canvas.save(self)
    return NumberedCanvas


def _overlays(ctx: Ctx, canv, page: int):
    for ov in ctx.m.get("overlays") or []:
        if int(ov.get("page", 0)) != page:
            continue
        x, y = float(ov.get("x_mm", 20)) * mm, float(ov.get("y_mm", 20)) * mm
        w, h = float(ov.get("w_mm", 40)) * mm, float(ov.get("h_mm", 20)) * mm
        canv.saveState()
        canv.setFillAlpha(float(ov.get("opacity", 1)))
        ry = ctx.H - y - h
        if ov.get("rotation"):
            canv.translate(x + w / 2, ry + h / 2)
            canv.rotate(-float(ov["rotation"]))
            canv.translate(-(x + w / 2), -(ry + h / 2))
        if ov.get("type") == "image" and ov.get("asset"):
            p = ctx.resolve(ov["asset"])
            if p and Path(p).exists() and Path(p).suffix.lower() != ".svg":
                prepared, _ = imgs.prepare_for_pdf(Path(p), ctx.cache, w, h, ctx.quality, ctx.gray)
                canv.drawImage(str(prepared), x, ry, w, h, preserveAspectRatio=True, anchor="c", mask="auto")
            else:
                ctx.issues.append({"level": "critical", "code": "missing_image", "block": "ov:" + str(ov.get("id")),
                                   "message": "An overlay image is missing."})
        else:
            st = ParagraphStyle("ov", fontName=ctx.body["bold" if ov.get("bold") else "regular"],
                                fontSize=float(ov.get("font_size", 11)), leading=float(ov.get("font_size", 11)) * 1.25,
                                textColor=_with_alpha(hex_color(ov.get("color"), ctx.gray, "#111827"), float(ov.get("opacity", 1))),
                                alignment=ALIGN.get(ov.get("align", "left"), TA_LEFT),
                                backColor=hex_color(ov["bg"], ctx.gray) if ov.get("bg") else None)
            p = Paragraph(ctx.mk(ov.get("text", "")), st)
            _, ph = p.wrap(w, h * 4)
            if ph > h + 1:
                ctx.issues.append({"level": "warning", "code": "text_overflow", "block": "ov:" + str(ov.get("id")),
                                   "message": f"Text box on page {page} is too small for its text."})
            p.drawOn(canv, x, ry + h - ph)
        canv.restoreState()
        ctx.positions.setdefault("ov:" + str(ov.get("id")), []).append(
            {"page": page, "x0": round(x, 2), "y0": round(y, 2), "x1": round(x + w, 2), "y1": round(y + h, 2)})


def _story(ctx: Ctx, include: set | None):
    """Build story, honouring keep_with_prev by grouping with the previous block."""
    t = ctx.t
    bld = Builder(ctx)
    items: list[tuple[str, list]] = []   # (bid, flowables) or ("__ctl__", [...])
    if ctx.cover_pages:
        items.append(("__ctl__", [Spacer(1, 1), NextPageTemplate("standard"), PageBreak()]))
    layout = "standard"
    last_src_page = None
    blocks = [b for b in ctx.m.get("blocks", []) if include is None or b["id"] in include]
    has_content = False
    for b in blocks:
        typ, bid = b["type"], b["id"]
        st = b.get("style") or {}
        pre: list[Flowable] = []
        if t["pagination"]["preserve_source_page_breaks"]:
            sp = (b.get("source") or {}).get("page")
            if sp and last_src_page and sp != last_src_page and has_content:
                pre.append(PageBreak())
            last_src_page = sp or last_src_page
        if typ == "section":
            new_layout = b.get("layout") or "standard"
            if new_layout not in t["layouts"]:
                new_layout = "standard"
            differs = (ctx.columns(new_layout) != ctx.columns(layout) or
                       (t["layouts"].get(new_layout) or {}).get("badge") != (t["layouts"].get(layout) or {}).get("badge"))
            if new_layout != layout and differs and t["pagination"]["section_layout_page_breaks"]:
                if has_content:
                    pre += [NextPageTemplate(new_layout), PageBreak()]
                elif ctx.cover_pages:
                    items[0] = ("__ctl__", [Spacer(1, 1), NextPageTemplate(new_layout), PageBreak()])
                else:
                    ctx.first_layout = new_layout
                layout = new_layout
            elif t["sections"]["page_break_before"] and has_content:
                pre.append(PageBreak())
        if (st.get("page_break_before") or "page_break_before" in ctx.repairs.get(bid, set())) and has_content:
            pre.append(PageBreak())
        fw = ctx.frame_width(layout)
        fl = {"heading": lambda: bld.heading(b), "section": lambda: bld.section(b),
              "instruction": lambda: bld.instruction(b), "paragraph": lambda: bld.paragraph(b),
              "question": lambda: bld.question(b, fw), "table": lambda: bld.table(b, fw),
              "image": lambda: bld.image_block(b, fw), "answer_space": lambda: bld.answer_space(b, fw),
              "page_break": lambda: [PageBreak()]}.get(typ, lambda: [])()
        fl = [f if isinstance(f, (PageBreak, NextPageTemplate, CondPageBreak)) else ctx.track(f, bid) for f in fl]
        if pre:
            items.append(("__ctl__", pre))
        if b.get("keep_with_prev") and items and items[-1][0] != "__ctl__" and "no_keep" not in ctx.repairs.get(bid, set()):
            pbid, pfl = items[-1]
            items[-1] = (pbid, [KeepTogether(pfl + fl)])
        else:
            items.append((bid, fl))
        if typ != "page_break":
            has_content = True
    story = [f for _, fl in items for f in fl]
    if t["answer_sheet"]["enabled"] and include is None:
        qs = [b for b in blocks if b["type"] == "question" and b.get("options")]
        if qs:
            story += [NextPageTemplate("answer_sheet"), PageBreak()]
            story += [ctx.track(f, "__answer_sheet__") for f in bld.answer_sheet(qs, ctx.frame_width("answer_sheet"))]
    return story


def _doc_template(ctx: Ctx, out: Path, furn: Furniture):
    t = ctx.t
    gap = t["page"]["column_gap_mm"] * mm

    def frames(layout, pid):
        cols = ctx.columns(layout)
        fw = ctx.frame_width(layout)
        return [Frame(ctx.ml + i * (fw + gap), ctx.mb, fw, ctx.frame_height(), id=f"{pid}_c{i}",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0) for i in range(cols)]

    def on_page(layout):
        def fn(canv, doc):
            ctx.page_layout[doc.page] = layout
            if layout == "answer_sheet":
                ctx.answer_pages.append(doc.page)
            furn.background(canv, doc)
            if (t["branding"]["watermark"] or {}).get("layer", "under") == "under":
                furn.watermark(canv)
            furn.header(canv, layout)
            furn.footer_static(canv)
        return fn

    def on_page_end(canv, doc):
        if (t["branding"]["watermark"] or {}).get("layer") == "over":
            furn.watermark(canv)
        _overlays(ctx, canv, doc.page)

    def cover_page(canv, doc):
        ctx.page_layout[doc.page] = "cover"
        furn.background(canv, doc)
        furn.cover(canv, doc)

    templates = []
    first = getattr(ctx, "first_layout", "standard")
    if ctx.cover_pages:
        templates.append(PageTemplate("cover", frames=[Frame(ctx.ml, ctx.mb, ctx.W - ctx.ml - ctx.mr, 20 * mm, id="cover")],
                                      onPage=cover_page, onPageEnd=on_page_end, pagesize=(ctx.W, ctx.H)))
    order = [first] + [l for l in t["layouts"] if l != first]
    for lay in order:
        templates.append(PageTemplate(lay, frames=frames(lay, lay), onPage=on_page(lay), onPageEnd=on_page_end,
                                      pagesize=(ctx.W, ctx.H)))
    b = t["branding"]
    doc = BaseDocTemplate(str(out), pagesize=(ctx.W, ctx.H), leftMargin=ctx.ml, rightMargin=ctx.mr,
                          topMargin=ctx.mt, bottomMargin=ctx.mb, title=ctx.m.get("title") or b.get("exam_title") or "Examination",
                          author=b.get("org_name") or "", subject=b.get("exam_title") or "", creator="PDF Test Designer",
                          producer="PDF Test Designer (ReportLab)", allowSplitting=1, pageTemplates=templates)
    return doc


def render(doc_model: dict, template: dict, resolve_asset: Callable[[str], Path | None], out_path: Path,
           cache_dir: Path, options: dict | None = None, progress: Callable[[float, str], None] | None = None) -> RenderResult:
    """Render a document model to PDF, repairing per-block layout failures automatically."""
    options = options or {}
    progress = progress or (lambda f, m: None)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    include = set(options["include_blocks"]) if options.get("include_blocks") else None
    repairs: dict[str, set] = {k: set(v) for k, v in (options.get("repairs") or {}).items()}
    repair_log: list[dict] = []
    tmp = out_path.with_suffix(".partial.pdf")
    n_blocks = max(1, len(doc_model.get("blocks", [])))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ctx = Ctx(doc_model, template, resolve_asset, cache_dir, options, repairs)
        furn = Furniture(ctx)
        story = _story(ctx, include)
        doc = _doc_template(ctx, tmp, furn)
        ctx.doc = doc
        seen: set[str] = set()

        def after(fl, _seen=seen, _ctx=ctx):
            if _ctx.last_bid and _ctx.last_bid not in _seen:
                _seen.add(_ctx.last_bid)
                if len(_seen) % 10 == 0:
                    progress(min(0.99, len(_seen) / n_blocks), f"Placed {len(_seen)} of {n_blocks} blocks (page {doc.page})")
        doc.afterFlowable = after
        try:
            doc.build(story, canvasmaker=_make_canvas(ctx, furn))
            break
        except LayoutError as e:
            bid = ctx.last_bid
            fix = _choose_repair(doc_model, bid, repairs.get(bid, set()))
            if bid is None or fix is None:
                tmp.unlink(missing_ok=True)
                raise RenderError(f"Layout failed and could not be repaired automatically: {e}") from e
            repairs.setdefault(bid, set()).add(fix)
            if fix == "shrink_image":
                repairs[bid] = repairs[bid] | {"shrink_image"}
            repair_log.append({"attempt": attempt, "block": bid, "repair": fix, "reason": str(e)[:200]})
            progress(0.5, f"Repairing layout (attempt {attempt}): {fix} on block {bid}")
    else:
        tmp.unlink(missing_ok=True)
        raise RenderError("Layout could not be completed after automatic repairs.")
    tmp.replace(out_path)
    issues = ctx.issues
    if ctx.missing_glyphs:
        chars = ", ".join(f"'{ch}' (U+{ord(ch):04X})" for ch in list(ctx.missing_glyphs)[:8])
        issues.append({"level": "critical", "code": "unsupported_characters",
                       "message": f"Characters not available in any installed font: {chars}. They will print as boxes."})
    for n in dict.fromkeys(ctx.font_notes):
        issues.append({"level": "warning", "code": "font_substituted", "message": n})
    frames = {}
    for p in range(1, doc.page + 1):
        frames[p] = [ctx.ml, ctx.mt, ctx.W - ctx.mr, ctx.H - ctx.mb]
    return RenderResult(path=out_path, pages=doc.page, positions=ctx.positions, page_size=(ctx.W, ctx.H),
                        frames=frames, issues=issues, repairs=repair_log,
                        fonts={"body": ctx.t["fonts"]["body"], "heading": ctx.t["fonts"]["heading"]},
                        cover_pages=ctx.cover_pages, answer_sheet_pages=ctx.answer_pages,
                        images_drawn=ctx.images_drawn, page_layouts=dict(ctx.page_layout))


def _choose_repair(doc_model: dict, bid: str | None, have: set) -> str | None:
    if bid is None:
        return None
    if bid == "__answer_sheet__":
        return None
    b = next((x for x in doc_model.get("blocks", []) if x["id"] == bid), None)
    if b is None:
        return None
    order = []
    if b["type"] in ("question", "table", "image") or b.get("keep_with_prev"):
        order.append("no_keep")
    if b["type"] in ("question", "instruction"):
        order.append("no_box")
    if b["type"] == "table":
        order.append("split_rows")
    if b["type"] == "image" or (b["type"] == "question" and b.get("images")):
        order.append("shrink_image")
    for f in order:
        if f not in have:
            return f
    return None
