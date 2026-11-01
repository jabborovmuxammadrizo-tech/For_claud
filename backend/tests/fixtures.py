"""Generates realistic source examination documents for tests and CI smoke tests.

Each fixture returns (path, expected) where expected lists the questions/options that the
import must preserve verbatim.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import docx
import pymupdf
from docx.shared import Pt, Inches
from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle, Frame, PageTemplate, BaseDocTemplate, FrameBreak)

FONT_DIR = Path(__file__).resolve().parent.parent / "resources" / "fonts"
_reg = False


def _fonts():
    global _reg
    if _reg:
        return
    pdfmetrics.registerFont(TTFont("FxSans", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("FxSans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("FxSerif", str(FONT_DIR / "LiberationSans-Regular.ttf")))
    _reg = True


def _styles():
    _fonts()
    return {
        "h1": ParagraphStyle("h1", fontName="FxSans-Bold", fontSize=16, leading=20, spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName="FxSans-Bold", fontSize=13, leading=17, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("b", fontName="FxSans", fontSize=10.5, leading=14),
        "instr": ParagraphStyle("i", fontName="FxSans", fontSize=10.5, leading=14, spaceAfter=4),
        "q": ParagraphStyle("q", fontName="FxSans", fontSize=10.5, leading=14, spaceBefore=6),
        "opt": ParagraphStyle("o", fontName="FxSans", fontSize=10.5, leading=14, leftIndent=14),
    }


WORDS = ("school student teacher river mountain library window garden morning evening family "
         "village city market history science lesson holiday friend country weather journey").split()
VERBS = "goes reads writes plays visits watches likes studies opens finds".split()


def _sentence(rng, n=8):
    w = [rng.choice(WORDS) for _ in range(n)]
    w[0] = w[0].capitalize()
    w.insert(2, rng.choice(VERBS))
    return " ".join(w) + "."


def make_questions(n, seed=1, start=1, uzbek=False):
    rng = random.Random(seed)
    qs = []
    for i in range(n):
        if uzbek and i % 2 == 0:
            text = f"Oʻquvchi “kitob” soʻzini qanday tarjima qiladi — {rng.choice(WORDS)}?"
            opts = ["gʻisht", "oʻqituvchi", "kitob — book", "shaʼnba"]
        else:
            text = f"{_sentence(rng, 6)} She ___ to the {rng.choice(WORDS)} every day?"
            opts = [rng.choice(VERBS) + " " + rng.choice(WORDS) for _ in range(4)]
        qs.append({"number": str(start + i), "text": text, "options": opts})
    return qs


def _q_flow(q, st, inline=False):
    if inline:
        line = f"{q['number']}. {_esc(q['text'])}<br/>" + "&nbsp;&nbsp;&nbsp;".join(
            f"{'ABCD'[k]}) {_esc(o)}" for k, o in enumerate(q["options"]))
        return [Paragraph(line, st["q"])]
    out = [Paragraph(f"{q['number']}. {_esc(q['text'])}", st["q"])]
    out += [Paragraph(f"{'ABCD'[k]}) {_esc(o)}", st["opt"]) for k, o in enumerate(q["options"])]
    return out


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _page_no(c, d):
    c.saveState()
    c.setFont("FxSans", 8)
    c.drawCentredString(A4[0] / 2, 12 * mm, f"Page {d.page}")
    c.drawString(20 * mm, A4[1] - 12 * mm, "Old School Header - English Department")
    c.restoreState()


def _build(path, flow, footer=True):
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=22 * mm, bottomMargin=22 * mm, title="Source exam")
    if footer:
        doc.build(flow, onFirstPage=_page_no, onLaterPages=_page_no)
    else:
        doc.build(flow)


def one_page(d: Path):
    st = _styles()
    qs = make_questions(10, seed=11)
    flow = [Paragraph("ENGLISH TEST", st["h1"]),
            Paragraph("Choose the correct answer for each question.", st["instr"])]
    for q in qs:
        flow += _q_flow(q, st)
    p = d / "one_page_exam.pdf"
    _build(p, flow, footer=False)
    return p, {"questions": qs}


def ten_page(d: Path):
    st = _styles()
    rng = random.Random(5)
    qs = make_questions(60, seed=21)
    flow = [Paragraph("General English Examination", st["h1"])]
    for s in range(4):
        flow.append(Paragraph(f"Part {s + 1}. Grammar and Vocabulary", st["h2"]))
        flow.append(Paragraph("Read the sentences and choose the best option A, B, C or D.", st["instr"]))
        flow.append(Paragraph(" ".join(_sentence(rng, 10) for _ in range(12)), st["body"]))
        for q in qs[s * 15:(s + 1) * 15]:
            flow += _q_flow(q, st, inline=(s % 2 == 1))
    p = d / "ten_page_exam.pdf"
    _build(p, flow)
    return p, {"questions": qs}


def hundred(d: Path):
    st = _styles()
    qs = make_questions(100, seed=31)
    flow = [Paragraph("FINAL TEST - 100 QUESTIONS", st["h1"]),
            Paragraph("Answer all questions. Choose one answer.", st["instr"])]
    for q in qs:
        flow += _q_flow(q, st)
    p = d / "hundred_questions.pdf"
    _build(p, flow)
    return p, {"questions": qs}


def _photo(path: Path, w=2400, h=1600, seed=3):
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), (180, 210, 240))
    dr = ImageDraw.Draw(img)
    for y in range(h):
        dr.line([(0, y), (w, y)], fill=(int(120 + 100 * y / h), int(170 + 50 * y / h), 230))
    for _ in range(60):
        x, y, r = rng.randint(0, w), rng.randint(0, h), rng.randint(20, 160)
        dr.ellipse([x - r, y - r, x + r, y + r], fill=(rng.randint(30, 200), rng.randint(80, 200), rng.randint(30, 120)))
    img.save(path, quality=92)
    return path


def _map(path: Path, w=2000, h=2600):
    img = Image.new("RGB", (w, h), (236, 242, 230))
    dr = ImageDraw.Draw(img)
    for i in range(0, w, 100):
        dr.line([(i, 0), (i, h)], fill=(210, 220, 210), width=2)
    for j in range(0, h, 100):
        dr.line([(0, j), (w, j)], fill=(210, 220, 210), width=2)
    pts = [(w * 0.5 + w * 0.35 * math.cos(t / 10) + 40 * math.sin(t), h * 0.5 + h * 0.35 * math.sin(t / 10)) for t in range(63)]
    dr.polygon(pts, outline=(40, 80, 160), fill=(200, 225, 200))
    dr.line([(100, h - 300), (w - 100, 300)], fill=(30, 90, 200), width=18)
    for k, (x, y) in enumerate([(600, 700), (1300, 1200), (900, 1800), (1500, 2100)]):
        dr.rectangle([x - 40, y - 40, x + 40, y + 40], fill=(200, 40, 40))
    img.save(path)
    return path


def large_images(d: Path):
    st = _styles()
    qs = make_questions(6, seed=41)
    ph = _photo(d / "_photo.jpg")
    flow = [Paragraph("Picture Description Test", st["h1"]),
            Paragraph("Look at the picture and answer the questions.", st["instr"]),
            RLImage(str(ph), width=170 * mm, height=113 * mm)]
    for q in qs[:3]:
        flow += _q_flow(q, st)
    flow.append(RLImage(str(_photo(d / "_photo2.jpg", 3000, 2000, 9)), width=170 * mm, height=113 * mm))
    for q in qs[3:]:
        flow += _q_flow(q, st)
    p = d / "large_images.pdf"
    _build(p, flow)
    return p, {"questions": qs, "images": 2}


def full_page_map(d: Path):
    st = _styles()
    qs = make_questions(5, seed=51)
    m = _map(d / "_map.png")
    flow = [Paragraph("Map Reading", st["h1"]), Paragraph("Look at the map of the town.", st["instr"]),
            RLImage(str(m), width=160 * mm, height=208 * mm), PageBreak()]
    for q in qs:
        flow += _q_flow(q, st)
    p = d / "full_page_map.pdf"
    _build(p, flow)
    return p, {"questions": qs, "images": 1}


def complex_tables(d: Path):
    st = _styles()
    qs = make_questions(4, seed=61)
    rows = [["No", "Word", "Translation", "Part of speech", "Example"]]
    rng = random.Random(7)
    for i in range(1, 70):
        rows.append([str(i), rng.choice(WORDS), rng.choice(WORDS) + "lar", rng.choice(["noun", "verb", "adj"]),
                     _sentence(rng, 5)])
    t = Table(rows, repeatRows=1, colWidths=[12 * mm, 28 * mm, 30 * mm, 28 * mm, 72 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONT", (0, 0), (-1, -1), "FxSans", 8.5),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
    flow = [Paragraph("Vocabulary Table Test", st["h1"]), Paragraph("Study the table and answer the questions.", st["instr"]), t]
    for q in qs:
        flow += _q_flow(q, st)
    p = d / "complex_tables.pdf"
    _build(p, flow)
    return p, {"questions": qs, "table_rows": len(rows)}


def uzbek_english(d: Path):
    st = _styles()
    qs = make_questions(12, seed=71, uzbek=True)
    flow = [Paragraph("Ingliz tili fanidan test — “Oʻzbekiston” mavzusi", st["h1"]),
            Paragraph("Toʻgʻri javobni tanlang. Choose the correct answer — only one is right.", st["instr"])]
    for q in qs:
        flow += _q_flow(q, st)
    p = d / "uzbek_english.pdf"
    _build(p, flow, footer=False)
    return p, {"questions": qs}


def reading_passages(d: Path):
    st = _styles()
    rng = random.Random(81)
    qs = make_questions(10, seed=82)
    flow = [Paragraph("Reading Comprehension", st["h1"])]
    for k in range(2):
        flow.append(Paragraph(f"Reading Text {k + 1}", st["h2"]))
        flow.append(Paragraph("Read the text and answer the questions below.", st["instr"]))
        for _ in range(5):
            flow.append(Paragraph(" ".join(_sentence(rng, 12) for _ in range(9)), st["body"]))
            flow.append(Spacer(1, 6))
        for q in qs[k * 5:(k + 1) * 5]:
            flow += _q_flow(q, st)
    p = d / "reading_passages.pdf"
    _build(p, flow)
    return p, {"questions": qs}


def scanned(d: Path):
    src, exp = one_page(d)
    s = pymupdf.open(src)
    out = pymupdf.open()
    for page in s:
        pix = page.get_pixmap(dpi=200)
        np_ = out.new_page(width=page.rect.width, height=page.rect.height)
        np_.insert_image(np_.rect, stream=pix.tobytes("png"))
    p = d / "scanned_exam.pdf"
    out.save(p)
    return p, exp


def multi_column(d: Path):
    st = _styles()
    qs = make_questions(24, seed=91)
    p = d / "multi_column.pdf"
    doc = BaseDocTemplate(str(p), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=20 * mm, bottomMargin=20 * mm)
    w = (A4[0] - 30 * mm - 8 * mm) / 2
    frames = [Frame(15 * mm, 20 * mm, w, A4[1] - 40 * mm, id="l"), Frame(15 * mm + w + 8 * mm, 20 * mm, w, A4[1] - 40 * mm, id="r")]
    doc.addPageTemplates([PageTemplate(frames=frames)])
    flow = [Paragraph("Two Column Test", st["h1"]), Paragraph("Choose the correct answer.", st["instr"])]
    for q in qs:
        flow += _q_flow(q, st)
    doc.build(flow)
    return p, {"questions": qs}


def docx_exam(d: Path):
    qs = make_questions(15, seed=101, uzbek=True)
    document = docx.Document()
    document.add_heading("Elementary English Test", level=1)
    document.add_paragraph("Choose the correct answer.")
    for q in qs[:10]:
        document.add_paragraph(f"{q['number']}. {q['text']}")
        for k, o in enumerate(q["options"]):
            document.add_paragraph(f"{'ABCD'[k]}) {o}")
    document.add_heading("Part 2. Vocabulary", level=2)
    document.add_paragraph("Complete the table.")
    t = document.add_table(rows=4, cols=3)
    t.style = "Table Grid"
    for r in range(4):
        for c in range(3):
            t.cell(r, c).text = ["Word", "Meaning", "Example"][c] if r == 0 else f"w{r}{c} cell"
    ph = _photo(d / "_docx_photo.jpg", 800, 500, 4)
    document.add_picture(str(ph), width=Inches(4))
    # Word automatic numbering (List Number style): numbers are NOT part of the text
    for q in qs[10:]:
        document.add_paragraph(q["text"], style="List Number")
    p = d / "docx_exam.docx"
    document.save(p)
    auto = [{"number": str(i + 1), "text": q["text"], "options": []} for i, q in enumerate(qs[10:])]
    return p, {"questions": qs[:10] + auto, "auto_numbered": [q["text"] for q in qs[10:]]}


def txt_exam(d: Path):
    qs = make_questions(8, seed=111)
    lines = ["BEGINNER TEST", "", "Choose the correct answer.", ""]
    for q in qs:
        lines.append(f"{q['number']}. {q['text']}")
        lines.append("   ".join(f"{'ABCD'[k]}) {o}" for k, o in enumerate(q["options"])))
        lines.append("")
    p = d / "beginner.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p, {"questions": qs}


ALL = {"one_page": one_page, "ten_page": ten_page, "hundred": hundred, "large_images": large_images,
       "full_page_map": full_page_map, "complex_tables": complex_tables, "uzbek_english": uzbek_english,
       "reading_passages": reading_passages, "scanned": scanned, "multi_column": multi_column,
       "docx_exam": docx_exam, "txt_exam": txt_exam}


def build_all(d: Path) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    return {k: f(d) for k, f in ALL.items()}


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures_out")
    for k, (p, e) in build_all(out).items():
        print(k, p, len(e.get("questions", [])))
