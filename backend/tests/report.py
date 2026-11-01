"""Generates the evidence section of docs/TEST_REPORT.md.

Runs every realistic fixture through the real one-click pipeline and records, per document:
source vs output question/option counts, question order, page count, A4 dimensions, searchable
text, images placed, overflow, validation summary and timing; plus page contact sheets for
visual inspection.

  python tests/report.py ../docs/test-report
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

import fixtures  # noqa: E402
from ptd import model as M  # noqa: E402
from ptd.config import Paths  # noqa: E402
from ptd.service import Service  # noqa: E402
from ptd.util import norm_tokens  # noqa: E402

CASES = [
    ("1. One-page examination", "one_page"), ("2. Ten-page examination", "ten_page"), ("3. One hundred questions", "hundred"),
    ("4. Large embedded images", "large_images"), ("5. Full-page map", "full_page_map"), ("6. Complex tables", "complex_tables"),
    ("7. Uzbek and English text", "uzbek_english"), ("9. Long reading passages", "reading_passages"), ("10. Scanned PDF (OCR)", "scanned"),
    ("11. Multi-column PDF", "multi_column"), ("DOCX with Word numbering, table, image", "docx_exam"), ("TXT examination", "txt_exam"),
]


def contact_sheet(pdf: Path, out: Path, max_pages: int = 4):
    d = pymupdf.open(pdf)
    ims = []
    for i in range(min(max_pages, d.page_count)):
        pix = d[i].get_pixmap(dpi=40)
        ims.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    w = sum(i.width for i in ims) + 8 * (len(ims) + 1)
    h = max(i.height for i in ims) + 16
    sheet = Image.new("RGB", (w, h), (226, 232, 240))
    x = 8
    for im in ims:
        sheet.paste(im, (x, 8))
        x += im.width + 8
    sheet.save(out, optimize=True)


def main(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp())
    fx = fixtures.build_all(work / "fx")
    svc = Service(Paths(work / "data"))
    tpls = svc.store.templates()
    rows = []
    for i, (label, key) in enumerate(CASES):
        path, expected = fx[key]
        tpl = tpls[i % len(tpls)]
        t0 = time.time()
        r = svc.quick_generate(path, path.name, tpl["id"])
        job = svc.wait(r["job"]["id"], 600)
        dt = time.time() - t0
        res = job["result"] or {}
        m = svc.store.load_model(r["document"]["id"])
        qs = M.questions(m)
        pdf = pymupdf.open(res["outputs"]["pdf"])
        text = " ".join(p.get_text() for p in pdf)
        toks = norm_tokens(text)
        out = Counter(toks)
        hay = " " + " ".join(toks) + " "
        exp_q = expected["questions"]
        exact = sum(1 for q, e in zip(qs, exp_q) if q["text"] == e["text"] and [o["text"] for o in q["options"]] == e["options"])
        present = sum(1 for q in qs if not (Counter(norm_tokens(q["text"] + " " + " ".join(o["text"] for o in q["options"]))) - out))
        pos, ordered = 0, True
        for q in qs:
            nd = " " + " ".join(norm_tokens(q["text"])[:8]) + " "
            j = hay.find(nd, pos)
            if j < 0:
                ordered = False
                break
            pos = j + 1
        a4 = all(abs(p.rect.width - 595.28) < 1 and abs(p.rect.height - 841.89) < 1 for p in pdf)
        overflow = sum(1 for p in pdf for b in p.get_text("dict")["blocks"] for ln in b.get("lines", []) for s in ln["spans"]
                       if s["bbox"][2] > p.rect.width + 1 or s["bbox"][3] > p.rect.height + 1)
        imgs_expected = M.stats(m)["images"]
        imgs_placed = sum(len(p.get_image_info()) for p in pdf)
        sheet = out_dir / f"{key}.png"
        contact_sheet(Path(res["outputs"]["pdf"]), sheet)
        s = res["validation"]["summary"]
        rows.append({"case": label, "file": path.name, "template": tpl["name"], "status": job["status"], "pages": res["pages"],
                     "q_expected": len(exp_q), "q_extracted": len(qs), "q_exact": exact, "q_in_pdf": present,
                     "options": M.stats(m)["options"], "ordered": ordered, "a4": a4, "overflow": overflow,
                     "images": f"{imgs_placed}/{imgs_expected}", "critical": s["critical"], "warnings": s["warning"],
                     "seconds": round(dt, 1), "sheet": sheet.name,
                     "notes": "; ".join(i["code"] for i in res["validation"]["issues"] if i["level"] != "info")})
        print(f"{label:42} {job['status']:12} q {len(qs)}/{len(exp_q)} exact {exact} order {ordered} pages {res['pages']} {dt:.1f}s")
    # batch of ten
    names = ["one_page", "ten_page", "hundred", "large_images", "full_page_map", "complex_tables", "uzbek_english",
             "reading_passages", "multi_column", "txt_exam"]
    t0 = time.time()
    b = svc.create_batch([(fx[n][0], fx[n][0].name) for n in names], None, "Ten exams")
    for j in b["jobs"]:
        svc.wait(j["id"], 600)
    b = svc.batch(b["id"])
    batch = {"documents": len(b["jobs"]), "succeeded": b["counts"]["succeeded"], "seconds": round(time.time() - t0, 1)}
    svc.close()
    (out_dir / "results.json").write_text(json.dumps({"cases": rows, "batch": batch}, indent=1, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print("batch", batch)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "test-report"))
