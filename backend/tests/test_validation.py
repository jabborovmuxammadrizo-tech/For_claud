"""The validator must catch real problems (it is tested by sabotaging outputs)."""
from pathlib import Path

import pymupdf

from ptd import model as M
from ptd import validation as V
from ptd.layout.renderer import render
from ptd.templates import normalize


def _doc(n=12):
    blocks = [M.block("section", title="Grammar", layout="standard"),
              M.block("instruction", text="Choose the correct answer.")]
    for i in range(1, n + 1):
        blocks.append(M.question(f"Question number {i} asks about zebra{i} words?", str(i),
                                 [M.option(L, f"answer{i}{L}") for L in "ABCD"], "mcq"))
    return M.new_document("Validation", blocks)


def _render(tmp_path, m, cfg=None, **opts):
    cfg = normalize(cfg or {})
    return render(m, cfg, lambda a: None, tmp_path / "o.pdf", tmp_path / "c", opts), cfg


def test_clean_document_passes(tmp_path):
    m = _doc()
    r, cfg = _render(tmp_path, m)
    issues, _ = V.check_render(m, r, cfg)
    assert V.summarize(issues)["passed"], [i for i in issues if i["level"] == "critical"]


def test_missing_question_detected(tmp_path):
    m = _doc()
    r, cfg = _render(tmp_path, {**m, "blocks": [b for b in m["blocks"] if b.get("number") != "5"]})
    issues, _ = V.check_render(m, r, cfg)       # validate against the full model
    crit = [i for i in issues if i["level"] == "critical"]
    assert any(i["code"] == "missing_content" and "Question 5" in i["message"] for i in crit)
    assert any(i["code"] == "missing_option" for i in crit)


def test_missing_option_detected(tmp_path):
    m = _doc()
    broken = M.clone(m)
    q = next(b for b in broken["blocks"] if b.get("number") == "7")
    q["options"] = q["options"][:2]
    r, cfg = _render(tmp_path, broken)
    issues, _ = V.check_render(m, r, cfg)
    assert any(i["code"] == "missing_option" and "Question 7" in i["message"] for i in issues)


def test_question_order_detected(tmp_path):
    m = _doc()
    swapped = M.clone(m)
    bl = swapped["blocks"]
    i3 = next(i for i, b in enumerate(bl) if b.get("number") == "3")
    i9 = next(i for i, b in enumerate(bl) if b.get("number") == "9")
    bl[i3], bl[i9] = bl[i9], bl[i3]
    r, cfg = _render(tmp_path, swapped)
    issues, _ = V.check_render(m, r, cfg)
    assert any(i["code"] == "question_order" for i in issues)


def test_missing_image_detected(tmp_path):
    m = _doc(3)
    m["blocks"].append(M.block("image", asset="as_missing", kind="image"))
    r, cfg = _render(tmp_path, m)
    issues, _ = V.check_render(m, r, cfg)
    assert any(i["code"] == "missing_image" and i["level"] == "critical" for i in issues)


def test_unsupported_characters_reported(tmp_path):
    m = _doc(2)
    m["blocks"].append(M.block("paragraph", text="Klingon: \U000F8D00 and emoji \U0001F600"))
    r, cfg = _render(tmp_path, m)
    issues, _ = V.check_render(m, r, cfg)
    assert any(i["code"] == "unsupported_characters" for i in issues)


def test_extraction_incomplete_detected():
    m = _doc(3)
    src = M.content_tokens(m) + ["photosynthesis", "chlorophyll"]
    issues = V.check_extraction(m, src)
    assert any(i["code"] == "extraction_incomplete" for i in issues)
    assert not V.check_extraction(m, M.content_tokens(m))


def test_page_numbers_present(tmp_path):
    m = _doc(60)
    r, cfg = _render(tmp_path, m)
    pdf = pymupdf.open(r.path)
    total = r.pages - r.cover_pages
    assert pdf[-1].search_for(f"Page {total} of {total}")
    issues, _ = V.check_render(m, r, cfg)
    assert not any(i["code"] == "page_number_missing" for i in issues)


def test_no_blank_pages_and_no_orphan_headings(tmp_path):
    blocks = []
    for s in range(6):
        blocks.append(M.block("section", title=f"Section {s}", layout="standard"))
        blocks.append(M.block("paragraph", text="Read carefully. " * 40))
        for i in range(8):
            blocks.append(M.question(f"S{s} question {i} text that is long enough to wrap onto a second line in the frame?",
                                     str(s * 8 + i + 1), [M.option(L, "option " + L * 12) for L in "ABCD"], "mcq"))
    m = M.new_document("Pagination", blocks)
    r, cfg = _render(tmp_path, m)
    issues, _ = V.check_render(m, r, cfg)
    assert not any(i["code"] == "blank_page" for i in issues)
    assert not any(i["code"] == "orphan_heading" for i in issues)
    # keep-together: no question is split across pages
    assert not any(i["code"] == "question_split" for i in issues)


def test_keep_together_released_for_oversized_question(tmp_path):
    long_q = M.question("Very long question " * 600, "1", [M.option("A", "x"), M.option("B", "y")], "mcq")
    m = M.new_document("Big", [long_q])
    r, cfg = _render(tmp_path, m)
    issues, _ = V.check_render(m, r, cfg)
    assert V.summarize(issues)["passed"]
    assert any(i["code"] == "question_split" for i in issues)   # reported, never dropped


def test_huge_table_fits_width(tmp_path):
    rows = [["Col %d" % c for c in range(9)]] + [[f"cell{r}x{c} with words" for c in range(9)] for r in range(120)]
    m = M.new_document("Table", [M.block("table", rows=rows, header_rows=1)])
    r, cfg = _render(tmp_path, m)
    issues, _ = V.check_render(m, r, cfg)
    assert V.summarize(issues)["passed"], [i for i in issues if i["level"] == "critical"]
    pdf = pymupdf.open(r.path)
    assert pdf.page_count > 3
    # header row repeated on continuation pages
    assert all("Col 0" in pdf[p].get_text() for p in range(r.cover_pages, pdf.page_count))
