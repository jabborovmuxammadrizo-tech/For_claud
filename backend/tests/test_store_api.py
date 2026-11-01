"""Storage, versions, trash, templates, branding, assets, backups and the HTTP API."""
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ptd import model as M
from ptd import templates as T

TOKEN = "test-token"


@pytest.fixture()
def client(svc):
    from ptd.api import create_app
    app = create_app(svc, TOKEN)
    c = TestClient(app, base_url="http://127.0.0.1")
    c.headers["X-PTD-Token"] = TOKEN
    return c


def _png(w=400, h=200, color=(30, 60, 200, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def test_seeded_templates_and_branding(svc):
    tpls = svc.store.templates()
    assert len(tpls) >= 9
    assert sum(t["is_default"] for t in tpls) == 1
    assert tpls[0]["name"].startswith("Mirzo Ulugbek NTM")
    cats = {t["category"] for t in tpls}
    assert {"beginner", "elementary", "pre_intermediate", "general_english", "certificate", "listening", "reading", "custom"} <= cats
    assert svc.store.branding_profiles()[0]["config"]["org_name"] == "MIRZO ULUGBEK NTM"


def test_template_crud(svc):
    t = svc.store.save_template({"name": "My test", "fonts": {"body": "Roboto"}})
    assert t["config"]["fonts"]["body"] == "Roboto" and t["config"]["page"]["width_mm"] == 210
    d = svc.store.duplicate_template(t["id"])
    assert d["name"] == "My test (copy)"
    svc.store.set_default_template(d["id"])
    with pytest.raises(ValueError):
        svc.store.delete_template(d["id"])
    svc.store.delete_template(t["id"])
    with pytest.raises(ValueError):
        svc.store.save_template({"name": "bad", "page": {"margins_mm": {"top": 1, "bottom": 1, "left": 1, "right": 1}}})


def test_versions_and_trash(svc, fx):
    doc = svc.upload(fx["txt_exam"][0], "beginner.txt")
    m = M.new_document("x", [M.block("paragraph", text="one")])
    svc.store.save_model(doc["id"], m, "v1")
    m["blocks"].append(M.block("paragraph", text="two"))
    svc.store.save_model(doc["id"], m, "v2")
    vs = svc.store.versions(doc["id"])
    assert [v["version"] for v in vs] == [2, 1]
    svc.store.restore_version(doc["id"], vs[1]["id"])
    assert len(svc.store.load_model(doc["id"])["blocks"]) == 1
    svc.store.trash_document(doc["id"])
    assert not svc.store.list_documents()
    assert svc.store.list_documents(trash=True)
    svc.store.restore_document(doc["id"])
    assert svc.store.list_documents()
    with pytest.raises(ValueError):
        svc.store.delete_document_permanently(doc["id"])   # must be in the trash first
    svc.store.trash_document(doc["id"])
    svc.store.delete_document_permanently(doc["id"])
    assert not (svc.paths.sub("Documents") / doc["id"]).exists()


def test_original_is_read_only_copy(svc, fx):
    doc = svc.upload(fx["one_page"][0], "one_page_exam.pdf")
    p = Path(doc["source_path"])
    assert p.read_bytes() == Path(fx["one_page"][0]).read_bytes()
    import os
    assert not os.access(p, os.W_OK) or os.geteuid() == 0   # root ignores permission bits


def test_backup_and_restore(svc, fx):
    doc = svc.upload(fx["txt_exam"][0], "beginner.txt")
    svc.store.save_model(doc["id"], M.new_document("keep", [M.block("paragraph", text="precious")]))
    b = svc.backup("manual")
    assert zipfile.ZipFile(b).testzip() is None
    svc.store.trash_document(doc["id"])
    svc.store.delete_document_permanently(doc["id"])
    assert not svc.store.list_documents()
    safety = svc.restore(b.name)
    assert (svc.paths.sub("Backups") / safety).exists()
    docs = svc.store.list_documents()
    assert [d["id"] for d in docs] == [doc["id"]]
    assert svc.store.load_model(doc["id"])["blocks"][0]["text"] == "precious"


def test_interrupted_jobs_recovered(tmp_path, fx):
    from ptd.config import Paths
    from ptd.service import Service
    s = Service(Paths(tmp_path / "d"))
    doc = s.upload(fx["txt_exam"][0], "a.txt")
    s.db.insert("jobs", {"id": "job_crash", "kind": "generate", "status": "running", "document_id": doc["id"],
                         "template_id": None, "steps": [], "progress": 0.4, "created": 0})
    s.close()
    s2 = Service(Paths(tmp_path / "d"))
    j = s2.job("job_crash")
    assert j["status"] == "failed" and "Interrupted" in j["error"]
    s2.close()


def test_api_auth_and_host(client):
    assert client.get("/api/health").status_code == 200
    r = client.get("/api/info", headers={"X-PTD-Token": "wrong"})
    assert r.status_code == 401
    r = client.get("/api/info", headers={"Host": "attacker.example"})
    assert r.status_code == 403
    assert client.get("/api/info").json()["ocr"]["any"] in (True, False)


def test_api_quick_generate_flow(client, fx):
    with open(fx["one_page"][0], "rb") as f:
        r = client.post("/api/quick-generate", files={"file": ("exam.pdf", f, "application/pdf")})
    assert r.status_code == 200, r.text
    jid = r.json()["job"]["id"]
    import time
    for _ in range(300):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert j["status"] == "succeeded", j
    assert [s["key"] for s in j["steps"]] == ["analyze", "extract", "template", "format", "check", "export"]
    assert all(s["status"] == "done" for s in j["steps"])
    pdf = client.get(f"/api/jobs/{jid}/file/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get(f"/api/jobs/{jid}/thumb/1").headers["content-type"] == "image/png"
    did = r.json()["document"]["id"]
    rec = client.get(f"/api/documents/{did}/recommend").json()
    assert rec and "template_id" in rec[0]
    prev = client.post(f"/api/documents/{did}/preview", json={}).json()
    assert prev["pages"] >= 1 and prev["positions"]
    assert client.get(prev["url"]).content[:4] == b"%PDF"
    assert client.get(f"/api/documents/{did}/original").content[:4] == b"%PDF"
    dash = client.get("/api/dashboard").json()
    assert dash["counts"]["documents"] == 1 and dash["counts"]["generated"] == 1


def test_api_unsupported_upload(client, tmp_path):
    p = tmp_path / "x.exe"
    p.write_bytes(b"MZ....")
    r = client.post("/api/documents", files={"file": ("x.exe", p.read_bytes())})
    assert r.status_code == 400 and "Unsupported" in r.json()["detail"]
    r = client.post("/api/documents", files={"file": ("old.doc", b"\xd0\xcf\x11\xe0")})
    assert r.status_code == 400 and ".docx" in r.json()["detail"]


def test_api_model_edit_and_preview(client, fx):
    with open(fx["txt_exam"][0], "rb") as f:
        r = client.post("/api/documents", files={"file": ("t.txt", f)}).json()
    did, jid = r["document"]["id"], r["job"]["id"]
    import time
    for _ in range(200):
        if client.get(f"/api/jobs/{jid}").json()["status"] == "succeeded":
            break
        time.sleep(0.05)
    m = client.get(f"/api/documents/{did}/model").json()
    m["blocks"][2]["style"] = {"font_size": 14, "bold": True, "color": "#DC2626", "keep_together": False}
    assert client.put(f"/api/documents/{did}/model", json={"model": m, "note": "styled"}).status_code == 200
    bad = client.put(f"/api/documents/{did}/model", json={"model": {"blocks": [{"type": "evil"}]}})
    assert bad.status_code == 400
    prev = client.post(f"/api/documents/{did}/preview", json={"model": m}).json()
    assert m["blocks"][2]["id"] in prev["positions"]


def test_api_template_import_export(client):
    tid = client.get("/api/templates").json()[0]["id"]
    exp = client.get(f"/api/templates/{tid}/export")
    assert exp.status_code == 200
    imp = client.post("/api/templates/import", files={"file": ("t.ptdtemplate.json", exp.content)})
    assert imp.status_code == 200 and imp.json()["name"].endswith("(imported)")
    prev = client.post("/api/templates/preview", json={"config": imp.json()["config"]}).json()
    assert prev["pages"] >= 2 and not prev["errors"]
    # built-in templates are protected
    assert client.put(f"/api/templates/{tid}", json={"name": "x"}).status_code == 400


def test_api_assets_logo_and_edit(client):
    r = client.post("/api/assets", files={"file": ("logo.png", _png(1200, 600))}, data={"kind": "logo"})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    e = client.post(f"/api/assets/{aid}/edit", json={"ops": {"crop": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}, "rotate": 90,
                                                              "flip_h": True, "opacity": 0.5}}).json()
    assert e["width"] == 300 and e["height"] == 600   # cropped 600x300 then rotated
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="100" height="50" fill="#1D4ED8"/></svg>'
    s = client.post("/api/assets", files={"file": ("logo.svg", svg)}, data={"kind": "logo"})
    assert s.status_code == 200
    evil = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert client.post("/api/assets", files={"file": ("x.svg", evil)}).status_code == 400
    # use both logos in a template and render a preview
    cfg = T.normalize({"name": "Logo test"})
    cfg["branding"]["logo_asset"] = aid
    cfg["branding"]["secondary_logo_asset"] = s.json()["id"]
    cfg["branding"]["watermark"] = {"type": "image", "asset": aid, "opacity": 0.08}
    prev = client.post("/api/templates/preview", json={"config": cfg}).json()
    assert prev["pages"] >= 2
    assert not [i for i in prev["issues"] if i["code"] in ("missing_logo", "missing_image")]
    assert client.delete(f"/api/assets/{aid}").status_code == 200   # not used by a saved template


def test_api_font_upload(client):
    from ptd.config import resource_dir
    data = (resource_dir() / "fonts" / "Roboto-Bold.ttf").read_bytes()
    r = client.post("/api/fonts", files={"file": ("MyFont-Bold.ttf", data)}, data={"family": "Teacher Font"})
    assert r.status_code == 200, r.text
    assert r.json()["style"] == "bold"
    fams = [f["family"] for f in client.get("/api/fonts").json()["families"]]
    assert "Teacher Font" in fams
    assert client.post("/api/fonts", files={"file": ("x.ttf", b"not a font")}).status_code == 400


def test_otf_conversion(tmp_path):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})
    pen = T2CharStringPen(600, None)
    pen.moveTo((0, 0)); pen.lineTo((300, 700)); pen.lineTo((600, 0)); pen.closePath()
    cs = pen.getCharString()
    fb.setupCFF("TestCFF", {"FullName": "TestCFF"}, {".notdef": cs, "A": cs}, {})
    fb.setupHorizontalMetrics({".notdef": (600, 0), "A": (600, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "TestCFF", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    p = tmp_path / "t.otf"
    fb.save(str(p))
    from ptd.fontconv import otf_to_ttf_if_needed
    from ptd.layout.fonts import inspect_font_file
    out = otf_to_ttf_if_needed(p)
    assert out.suffix == ".ttf" and inspect_font_file(out)["ok"]
