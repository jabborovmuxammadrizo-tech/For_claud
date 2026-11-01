"""Windows Explorer right-click engine (Part 25), tested through the same entry point Explorer uses."""
import shutil
import zipfile
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from ptd import shell as SH


def wait_task(svc, res):
    b = svc.batch(res["task_id"])
    for j in b["jobs"]:
        svc.wait(j["id"], 300)
    return svc.batch(res["task_id"])


@pytest.fixture()
def out(svc, tmp_path):
    d = tmp_path / "Mening imtihonlarim (output)"
    svc.db.set_setting("output_dir", str(d))
    return d


def test_generate_default_unicode_and_spaces(svc, fx, tmp_path, out):
    src = tmp_path / "Oʻquvchilar uchun test — 1-chorak.pdf"
    shutil.copy(fx["one_page"][0], src)
    before = src.read_bytes()
    res = SH.run(svc, "generate-default", [str(src)])
    b = wait_task(svc, res)
    j = b["jobs"][0]
    assert j["status"] == "succeeded", j["error"]
    delivered = Path(j["result"]["outputs"]["delivered"])
    assert delivered.parent == out and delivered.name == "Oʻquvchilar uchun test — 1-chorak_Formatted.pdf"
    assert pymupdf.open(delivered).page_count >= 1
    assert src.read_bytes() == before                     # original untouched
    # second run never overwrites
    b2 = wait_task(svc, SH.run(svc, "generate-default", [str(src)]))
    d2 = Path(b2["jobs"][0]["result"]["outputs"]["delivered"])
    assert d2.name == "Oʻquvchilar uchun test — 1-chorak_Formatted (2).pdf" and delivered.exists()


def test_very_long_filename(svc, fx, tmp_path, out):
    src = tmp_path / ("Juda uzun nomli imtihon fayli " * 6 + ".pdf")
    shutil.copy(fx["one_page"][0], src)
    b = wait_task(svc, SH.run(svc, "generate-default", [str(src)]))
    assert b["jobs"][0]["status"] == "succeeded"
    assert len(Path(b["jobs"][0]["result"]["outputs"]["delivered"]).name) <= 160


def test_mixed_multi_select_batch_with_template_and_zip(svc, fx, out):
    tpl = [t for t in svc.store.templates() if t["category"] == "certificate"][0]
    paths = [str(fx["one_page"][0]), str(fx["docx_exam"][0]), str(fx["txt_exam"][0])]
    res = SH.run(svc, "batch-generate", paths, tpl["id"])
    b = wait_task(svc, res)
    assert b["template_id"] == tpl["id"] and b["counts"]["succeeded"] == 3
    names = sorted(Path(j["result"]["outputs"]["delivered"]).name for j in b["jobs"])
    assert names == ["beginner_Formatted.pdf", "docx_exam_Formatted.pdf", "one_page_exam_Formatted.pdf"]
    assert all(Path(j["result"]["outputs"]["delivered"]).parent.parent == out for j in b["jobs"])
    z = svc.batch_zip(b["id"])
    assert len(zipfile.ZipFile(z).namelist()) == 3


def test_folder_with_and_without_subfolders(svc, fx, tmp_path, out):
    root = tmp_path / "Exams folder"
    (root / "sub").mkdir(parents=True)
    shutil.copy(fx["one_page"][0], root / "a.pdf")
    shutil.copy(fx["txt_exam"][0], root / "b.txt")
    shutil.copy(fx["docx_exam"][0], root / "sub" / "c.docx")
    (root / "notes.xlsx").write_bytes(b"x")
    (root / "~$lock.docx").write_bytes(b"x")
    b = wait_task(svc, SH.run(svc, "batch-generate", [str(root)]))
    assert len(b["jobs"]) == 2
    b2 = wait_task(svc, SH.run(svc, "batch-generate", [str(root)], options={"include_subfolders": True}))
    assert len(b2["jobs"]) == 3 and b2["counts"]["succeeded"] == 3
    assert (root / "a.pdf").read_bytes() == Path(fx["one_page"][0]).read_bytes()


def test_batch_failure_does_not_stop_others(svc, fx, tmp_path, out):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4 not really")
    b = wait_task(svc, SH.run(svc, "batch-generate", [str(fx["one_page"][0]), str(bad), str(fx["txt_exam"][0])]))
    assert sorted(j["status"] for j in b["jobs"]) == ["failed", "succeeded", "succeeded"]


def test_pdf_operations(svc, fx, out):
    src = str(fx["large_images"][0])
    comp = wait_task(svc, SH.run(svc, "compress", [src]))["jobs"][0]
    assert comp["status"] == "succeeded", comp["error"]
    cp = Path(comp["result"]["delivered"][0])
    assert cp.name == "large_images_Compressed.pdf" and cp.stat().st_size <= Path(src).stat().st_size
    gray = wait_task(svc, SH.run(svc, "grayscale", [src]))["jobs"][0]
    gp = Path(gray["result"]["delivered"][0])
    pix = pymupdf.open(gp)[0].get_pixmap(dpi=30)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    assert all(abs(r - g) < 6 and abs(g - b) < 6 for r, g, b in im.getdata())       # truly grayscale
    assert "Picture Description Test" in pymupdf.open(gp)[0].get_text()             # text still searchable
    info = wait_task(svc, SH.run(svc, "info", [src]))["jobs"][0]["result"]["info"]
    assert info["pages"] >= 1 and info["images"] >= 2 and not info["scanned"]
    ex = wait_task(svc, SH.run(svc, "extract", [src]))["jobs"][0]
    folder = Path(ex["result"]["delivered"][0])
    assert (folder / "large_images.txt").read_text(encoding="utf-8").count("She ___") == 6
    assert len(list((folder / "images").iterdir())) == 2


def test_convert_operations(svc, fx, out):
    ed = wait_task(svc, SH.run(svc, "convert-editable", [str(fx["one_page"][0])]))["jobs"][0]
    assert ed["status"] == "succeeded", ed["error"]
    import docx
    d = docx.Document(ed["result"]["delivered"][0])
    text = "\n".join(p.text for p in d.paragraphs)
    assert text.count("A) ") == 10 and "ENGLISH TEST" in text
    pdf = wait_task(svc, SH.run(svc, "convert-pdf", [str(fx["docx_exam"][0])]))["jobs"][0]
    assert pdf["status"] == "succeeded", pdf["error"]
    t = " ".join(p.get_text() for p in pymupdf.open(pdf["result"]["delivered"][0]))
    assert "Elementary English Test" in t and "MIRZO ULUGBEK" not in t              # faithful, unbranded


def test_image_actions(svc, tmp_path, fx, out):
    img = tmp_path / "Maktab gerbi.png"
    Image.new("RGB", (900, 600), (20, 80, 200)).save(img)
    r = SH.run(svc, "image-library", [str(img)])
    assert r["kind"] == "immediate" and svc.store.asset(r["assets"][0])["kind"] == "image"
    pdf = wait_task(svc, SH.run(svc, "image-pdf", [str(img)]))["jobs"][0]
    assert pymupdf.open(pdf["result"]["delivered"][0]).page_count == 1
    SH.run(svc, "image-watermark", [str(img)])
    SH.run(svc, "image-background", [str(img)])
    _, cfg = svc.store.effective_template(None)
    assert cfg["branding"]["watermark"]["type"] == "image" and cfg["branding"]["background_asset"]
    b = wait_task(svc, SH.run(svc, "generate-default", [str(fx["one_page"][0])]))
    assert b["jobs"][0]["status"] == "succeeded"


def test_errors_are_clear(svc, tmp_path, out):
    p = tmp_path / "table.xlsx"
    p.write_bytes(b"x")
    with pytest.raises(SH.ShellError, match="Unsupported file format"):
        SH.run(svc, "generate-default", [str(p)])
    with pytest.raises(SH.ShellError, match="not found"):
        SH.run(svc, "generate-default", [str(tmp_path / "missing.pdf")])
    svc.db.set_setting("shell_default_template", "tpl_does_not_exist")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(SH.ShellError, match="Template not found"):
        SH.run(svc, "generate-default", [str(pdf)])


def test_output_folder_unavailable(svc, fx, tmp_path):
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x")
    svc.db.set_setting("output_dir", str(blocker / "sub"))
    with pytest.raises(SH.ShellError, match="Output folder unavailable"):
        SH.run(svc, "generate-default", [str(fx["one_page"][0])])


def test_naming_patterns(svc, fx, out):
    svc.db.set_setting("output_naming", "exam")
    b = wait_task(svc, SH.run(svc, "generate-default", [str(fx["txt_exam"][0])]))
    assert Path(b["jobs"][0]["result"]["outputs"]["delivered"]).name == "beginner_Exam.pdf"
    svc.db.set_setting("output_naming", "custom")
    svc.db.set_setting("output_pattern", "{name} - {template}")
    b = wait_task(svc, SH.run(svc, "generate-default", [str(fx["txt_exam"][0])]))
    assert Path(b["jobs"][0]["result"]["outputs"]["delivered"]).name.startswith("beginner - Mirzo Ulugbek NTM")
    assert SH.windows_safe('a<b>:c"d|e?*') == "a_b__c_d_e__"


def test_cancel_batch(svc, fx, out):
    paths = [str(fx[n][0]) for n in ("hundred", "ten_page", "reading_passages", "complex_tables", "uzbek_english", "one_page")]
    res = SH.run(svc, "batch-generate", paths)
    svc.cancel_batch(res["task_id"])
    b = wait_task(svc, res)
    assert b["counts"]["cancelled"] >= 1
    assert all(j["status"] in ("succeeded", "cancelled") for j in b["jobs"])


def test_api_shell_endpoint(svc, fx, out):
    from fastapi.testclient import TestClient
    from ptd.api import create_app
    c = TestClient(create_app(svc, "t"), base_url="http://127.0.0.1")
    c.headers["X-PTD-Token"] = "t"
    r = c.post("/api/shell/run", json={"command": "generate-default", "paths": [str(fx["one_page"][0])]})
    assert r.status_code == 200, r.text
    assert c.post("/api/shell/run", json={"command": "rm -rf", "paths": ["x"]}).status_code == 400
    assert c.post("/api/shell/run", json={"command": "info", "paths": "C:/x"}).status_code == 400
    st = c.put("/api/settings", json={"shell_menu_folder": False, "output_naming": "exam"}).json()
    assert st["shell_menu_folder"] is False and st["output_naming"] == "exam"
    assert c.put("/api/settings", json={"output_naming": "custom", "output_pattern": "no-name"}).status_code == 400
