"""End-to-end one-click generation on realistic exam documents (spec test cases 1-13)."""
from collections import Counter
from pathlib import Path

import pymupdf
import pytest

from ptd import model as M
from ptd.util import norm_tokens

A4 = (595.28, 841.89)


def generate(svc, path, template_id=None, **opts):
    r = svc.quick_generate(Path(path), Path(path).name, template_id, opts)
    job = svc.wait(r["job"]["id"], 300)
    return r["document"], job


def verify(svc, doc, job, expected, allow_review=False, ocr=False):
    assert job["status"] in (("succeeded", "needs_review") if allow_review else ("succeeded",)), \
        (job["status"], job["error"], [i for i in job["result"]["validation"]["issues"] if i["level"] == "critical"] if job["result"] else None)
    res = job["result"]
    pdf_path = Path(res["outputs"]["pdf"])
    assert pdf_path.exists() and pdf_path.stat().st_size > 1000
    pdf = pymupdf.open(pdf_path)
    # page dimensions: A4 portrait
    for p in pdf:
        assert abs(p.rect.width - A4[0]) < 1 and abs(p.rect.height - A4[1]) < 1
    # searchable, selectable text
    text = " ".join(p.get_text() for p in pdf)
    out = Counter(norm_tokens(text))
    toks = norm_tokens(text)
    hay = " " + " ".join(toks) + " "
    model = svc.store.load_model(doc["id"])
    qs = M.questions(model)
    if not ocr:
        assert len(qs) == len(expected["questions"])
    pos = 0
    for q, e in zip(qs, expected["questions"]):
        if not ocr:
            assert q["text"] == e["text"], "question wording must be preserved exactly"
            assert [o["text"] for o in q["options"]] == e["options"]
        need = Counter(norm_tokens(q["text"]))
        for o in q["options"]:
            need.update(norm_tokens(o["text"]))
        assert not (need - out), f"question {q['number']} content missing from PDF"
        needle = " " + " ".join(norm_tokens(q["text"])[:8]) + " "
        i = hay.find(needle, pos)
        assert i >= 0, f"question {q['number']} out of order"
        pos = i + 1
    # every image placed
    img_count = sum(len(p.get_image_info()) for p in pdf)
    assert img_count >= M.stats(model)["images"]
    # nothing outside page boundaries
    for p in pdf:
        for b in p.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    x0, y0, x1, y1 = sp["bbox"]
                    assert x0 > -1 and y0 > -1 and x1 < p.rect.width + 1 and y1 < p.rect.height + 1
    # fonts embedded
    for p in pdf:
        for f in p.get_fonts():
            if any(sp_font in f[3] for sp_font in ("DejaVu", "Liberation", "Roboto", "OpenSans", "PTD")):
                assert f[1] != "n/a", f"font {f[3]} not embedded"
    # compressed copy & thumbnails
    assert Path(res["outputs"]["compressed"]).exists()
    assert len(res["thumbnails"]) == pdf.page_count == res["pages"]
    # originals untouched
    assert Path(doc["source_path"]).read_bytes() == Path(expected["_src"]).read_bytes()
    pdf.close()
    return res


CASES = ["one_page", "ten_page", "hundred", "large_images", "full_page_map", "complex_tables", "uzbek_english",
         "reading_passages", "multi_column", "docx_exam", "txt_exam"]


@pytest.mark.parametrize("name", CASES)
def test_one_click_generation(shared_svc, fx, name):
    path, expected = fx[name]
    expected = {**expected, "_src": path}
    tpls = shared_svc.store.templates()
    tpl = tpls[CASES.index(name) % len(tpls)]
    doc, job = generate(shared_svc, path, tpl["id"])
    res = verify(shared_svc, doc, job, expected)
    s = res["validation"]["summary"]
    assert s["passed"] and s["critical"] == 0


def test_ten_page_has_many_pages(shared_svc, fx):
    doc, job = generate(shared_svc, fx["ten_page"][0], None)
    assert job["result"]["pages"] >= 6


def test_hundred_questions_numbering(shared_svc, fx):
    doc, job = generate(shared_svc, fx["hundred"][0], None)
    m = shared_svc.store.load_model(doc["id"])
    assert [q["number"] for q in M.questions(m)] == [str(i) for i in range(1, 101)]


def test_uzbek_characters_render(shared_svc, fx):
    doc, job = generate(shared_svc, fx["uzbek_english"][0], None)
    text = " ".join(p.get_text() for p in pymupdf.open(job["result"]["outputs"]["pdf"]))
    for s in ("Oʻquvchi", "“kitob”", "—", "gʻisht", "shaʼnba"):
        assert s in text, s
    assert not [i for i in job["result"]["validation"]["issues"] if i["code"] == "unsupported_characters"]


def test_scanned_pdf_is_flagged_not_claimed_perfect(shared_svc, fx):
    path, expected = fx["scanned"]
    doc, job = generate(shared_svc, path, None)
    assert job["status"] in ("succeeded", "needs_review")
    codes = {i["code"] for i in job["result"]["validation"]["issues"]}
    assert "scanned_source" in codes
    m = shared_svc.store.load_model(doc["id"])
    assert len(M.questions(m)) >= 9   # OCR quality depends on the scan; never silently perfect
    assert m["meta"]["ocr_pages"]


def test_multi_column_reading_order(shared_svc, fx):
    path, expected = fx["multi_column"]
    doc, job = generate(shared_svc, path, None)
    m = shared_svc.store.load_model(doc["id"])
    assert [q["number"] for q in M.questions(m)] == [q["number"] for q in expected["questions"]]
    assert m["meta"]["multi_column_pages"]


def test_docx_word_numbering_reconstructed(shared_svc, fx):
    path, expected = fx["docx_exam"]
    doc, job = generate(shared_svc, path, None)
    m = shared_svc.store.load_model(doc["id"])
    texts = [q["text"] for q in M.questions(m)]
    for t in expected["auto_numbered"]:
        assert t in texts
    assert M.stats(m)["tables"] == 1 and M.stats(m)["images"] == 1


def test_multiple_page_layouts_in_one_document(svc):
    blocks = [M.block("section", title="Listening", layout="listening"),
              M.question("Listen and choose.", "1", [M.option("A", "yes"), M.option("B", "no")], "mcq"),
              M.block("section", title="Reading", layout="reading"),
              M.block("paragraph", text="A short reading passage about the city."),
              M.question("Is the city big?", "2", [M.option("A", "True"), M.option("B", "False")], "true_false"),
              M.block("section", title="Writing", layout="writing"),
              M.question("Write about your family.", "3", qtype="writing", answer_lines=5)]
    m = M.new_document("Layouts", blocks)
    _, cfg = svc.store.effective_template(None)
    from ptd.layout.renderer import render
    r = render(m, cfg, svc.store.asset_path, svc.paths.sub("Temp") / "layouts.pdf", svc.paths.sub("Temp") / "c")
    assert {"cover", "listening", "reading", "writing"} <= set(r.page_layouts.values())


def test_batch_of_ten_documents_and_zip(svc, fx):
    names = ["one_page", "ten_page", "hundred", "large_images", "full_page_map", "complex_tables", "uzbek_english",
             "reading_passages", "multi_column", "txt_exam"]
    files = [(fx[n][0], fx[n][0].name) for n in names]
    b = svc.create_batch(files, None, "Ten exams")
    for j in b["jobs"]:
        svc.wait(j["id"], 300)
    b = svc.batch(b["id"])
    assert b["finished"] and len(b["jobs"]) == 10
    assert b["counts"]["succeeded"] == 10, b["counts"]
    pdfs = {Path(j["result"]["outputs"]["pdf"]) for j in b["jobs"]}
    assert len(pdfs) == 10                       # every document got its own output
    import zipfile
    z = zipfile.ZipFile(svc.batch_zip(b["id"]))
    assert len([n for n in z.namelist() if n.endswith(".pdf")]) == 10


def test_batch_failure_is_isolated(svc, fx, tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4\n%garbage that is not a pdf")
    b = svc.create_batch([(fx["one_page"][0], "a.pdf"), (bad, "broken.pdf"), (fx["txt_exam"][0], "b.txt")], None)
    for j in b["jobs"]:
        svc.wait(j["id"], 300)
    b = svc.batch(b["id"])
    st = sorted(j["status"] for j in b["jobs"])
    assert st == ["failed", "succeeded", "succeeded"], st
    failed = next(j for j in b["jobs"] if j["status"] == "failed")
    assert failed["error"]
    svc.retry_job(failed["id"])
    assert svc.wait(failed["id"])["status"] == "failed"   # still broken, but retry ran cleanly


def test_custom_fonts(svc, fx):
    from ptd.layout import fonts as F
    src = Path(F.resource_dir()) / "fonts"
    dest = svc.paths.sub("Fonts")
    for style, fname in (("regular", "OpenSans-Regular.ttf"), ("bold", "OpenSans-Bold.ttf")):
        p = dest / f"custom-{fname}"
        p.write_bytes((src / fname).read_bytes())
        svc.store.add_font(p, "My School Font", style)
    F.set_custom_fonts(svc.store.fonts())
    rec, cfg = svc.store.effective_template(None)
    cfg["name"] = "Custom font template"
    cfg["fonts"]["body"] = "My School Font"
    cfg["fonts"]["heading"] = "Roboto"
    t = svc.store.save_template(cfg)
    doc, job = generate(svc, fx["one_page"][0], t["id"])
    assert job["status"] == "succeeded"
    fonts = {f[3] for p in pymupdf.open(job["result"]["outputs"]["pdf"]) for f in p.get_fonts()}
    assert any("OpenSans" in f for f in fonts), fonts      # the custom family's file is embedded
    assert any("Roboto" in f for f in fonts), fonts
    assert not any(f in ("Helvetica", "Times-Roman", "Courier") for f in fonts), fonts   # no base-14 fonts


def test_idempotent_and_regenerate(svc, fx):
    doc, job = generate(svc, fx["one_page"][0], None)
    again = svc.create_job("generate", doc["id"], None, {})
    assert again.get("reused") and again["id"] == job["id"]
    forced = svc.create_job("generate", doc["id"], None, {"force": True})
    assert forced["id"] != job["id"]
    j2 = svc.wait(forced["id"])
    assert j2["status"] == "succeeded"
    assert j2["result"]["outputs"]["pdf"] != job["result"]["outputs"]["pdf"]   # never overwritten
    assert Path(job["result"]["outputs"]["pdf"]).exists()


def test_edited_model_is_used_on_regenerate(svc, fx):
    doc, job = generate(svc, fx["one_page"][0], None)
    m = svc.store.load_model(doc["id"])
    m["blocks"].append(M.question("A brand new question added in the editor?", None,
                                  [M.option("A", "first"), M.option("B", "second")], "mcq"))
    svc.store.save_model(doc["id"], m)
    j = svc.wait(svc.create_job("generate", doc["id"], None, {})["id"])
    text = " ".join(p.get_text() for p in pymupdf.open(j["result"]["outputs"]["pdf"]))
    assert "A brand new question added in the editor?" in text


def test_auto_numbering_does_not_touch_content(svc, fx):
    rec, cfg = svc.store.effective_template(None)
    cfg["name"] = "Auto numbering"
    cfg["questions"]["numbering"] = "auto"
    t = svc.store.save_template(cfg)
    doc, job = generate(svc, fx["docx_exam"][0], t["id"])
    assert job["status"] == "succeeded"
    stored = svc.store.load_model(doc["id"])
    nums = [q["number"] for q in M.questions(stored)]
    assert nums == [str(i) for i in range(1, 11)] + [str(i) for i in range(1, 6)]   # source numbering kept in storage
    text = " ".join(p.get_text() for p in pymupdf.open(job["result"]["outputs"]["pdf"]))
    assert "15." in text and "11." in text                                          # output renumbered 1..15


def test_original_page_mode(svc, fx):
    path, _ = fx["ten_page"]
    r = svc.quick_generate(path, path.name, None, {}, import_mode="original")
    j = svc.wait(r["job"]["id"])
    assert j["status"] == "succeeded", j["error"]
    src = pymupdf.open(path)
    out = pymupdf.open(j["result"]["outputs"]["pdf"])
    assert out.page_count == src.page_count
    assert "MIRZO ULUGBEK NTM" in out[0].get_text()           # branding added
    assert Counter(norm_tokens(src[3].get_text())) - Counter(norm_tokens(out[3].get_text())) == Counter()


def test_original_page_mode_reorder_rotate_exclude(svc, fx):
    path, _ = fx["ten_page"]
    r = svc.quick_generate(path, path.name, None, {}, import_mode="original")
    svc.wait(r["job"]["id"])
    m = svc.store.load_model(r["document"]["id"])
    pages = m["original_pages"]
    pages[0]["include"] = False
    pages[1]["rotation"] = 90
    pages[2], pages[3] = pages[3], pages[2]
    svc.store.save_model(r["document"]["id"], m)
    j = svc.wait(svc.create_job("generate", r["document"]["id"], None, {})["id"])
    out = pymupdf.open(j["result"]["outputs"]["pdf"])
    assert out.page_count == len(pages) - 1


def test_custom_exports(svc, fx):
    doc, job = generate(svc, fx["ten_page"][0], None)
    m = svc.store.load_model(doc["id"])
    sec = [b["id"] for b in m["blocks"] if b["type"] == "section"][1]
    g = svc.export(doc["id"], None, "pdf", "print", grayscale=True)[0]
    assert Path(g["path"]).exists()
    pg = svc.export(doc["id"], None, "pdf", "print", pages=[2, 3])[0]
    assert pymupdf.open(pg["path"]).page_count == 2
    s = svc.export(doc["id"], None, "pdf", "print", sections=[sec])[0]
    assert 0 < pymupdf.open(s["path"]).page_count < job["result"]["pages"]
    png = svc.export(doc["id"], None, "png", pages=[1, 2])[0]
    import zipfile
    assert len(zipfile.ZipFile(png["path"]).namelist()) == 2
    js = svc.export(doc["id"], None, "json")[0]
    assert Path(js["path"]).read_text(encoding="utf-8").startswith("{")
    comp = svc.export(doc["id"], None, "pdf", "compressed")[0]
    assert Path(comp["path"]).stat().st_size < Path(job["result"]["outputs"]["pdf"]).stat().st_size * 1.05
