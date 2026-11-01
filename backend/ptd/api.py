"""Local HTTP API used by the Electron renderer.

Security: binds to 127.0.0.1 only; every /api request must carry the per-launch secret token
(header X-PTD-Token, or ?t= for <img>/<a> URLs); Host header must be a loopback name.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__, APP_NAME
from . import backup as B
from . import images as IM
from . import importers
from . import model as M
from . import templates as T
from .importers import ocr
from .layout import fonts as F
from .service import Service
from .store import NotFound
from .util import new_id, safe_filename, unique_path

log = logging.getLogger("ptd.api")
LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}


def create_app(svc: Service, token: str, allowed_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title=APP_NAME, version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.svc = svc
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins or ["app://ptd", "http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in LOOPBACK:
            return JSONResponse({"detail": "Forbidden host"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/health" and request.method != "OPTIONS":
            supplied = request.headers.get("x-ptd-token") or request.query_params.get("t")
            if supplied != token:
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(NotFound)
    async def nf(_req, exc):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.exception_handler(ValueError)
    async def ve(_req, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def S() -> Service:
        return app.state.svc

    def file_response(path: str | Path, download: bool = False, name: str | None = None):
        p = Path(path)
        if not p.exists() or not S().paths.is_inside(p):
            raise HTTPException(404, "File not found")
        mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        headers = {"Cache-Control": "no-store"}
        if download:
            return FileResponse(p, media_type=mt, filename=name or p.name, headers=headers)
        return FileResponse(p, media_type=mt, headers=headers)

    async def save_upload(up: UploadFile) -> Path:
        tmpdir = Path(tempfile.mkdtemp(dir=S().paths.sub("Temp")))
        dest = tmpdir / safe_filename(up.filename or "upload", "upload")
        size = 0
        with open(dest, "wb") as f:
            while chunk := await up.read(1 << 20):
                size += len(chunk)
                if size > importers.MAX_BYTES:
                    raise HTTPException(413, "File is larger than 300 MB.")
                f.write(chunk)
        return dest

    def cleanup(p: Path):
        shutil.rmtree(p.parent, ignore_errors=True)

    # ------------------------------------------------------------------ system
    @app.get("/api/health")
    def health():
        return {"ok": True, "app": APP_NAME, "version": __version__}

    @app.get("/api/info")
    def info():
        return {"version": __version__, "data_dir": str(S().paths.root), "ocr": ocr.available(),
                "fonts": F.available_families(), "supported": sorted(importers.SUPPORTED)}

    @app.get("/api/dashboard")
    def dashboard():
        return S().dashboard()

    @app.get("/api/history")
    def history(limit: int = 200):
        return S().history(limit)

    @app.get("/api/audit")
    def audit(limit: int = 200):
        return S().db.all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))

    @app.get("/api/settings")
    def get_settings():
        db = S().db
        return {"ocr_enabled": db.get_setting("ocr_enabled", True), "autosave_seconds": db.get_setting("autosave_seconds", 20),
                "default_import_mode": db.get_setting("default_import_mode", "editable"),
                "daily_backup": db.get_setting("daily_backup", True), "language": db.get_setting("language", "en"),
                "update_url": db.get_setting("update_url", ""), "check_updates": db.get_setting("check_updates", False),
                "data_dir": str(S().paths.root)}

    @app.put("/api/settings")
    def put_settings(body: dict = Body(...)):
        allowed = {"ocr_enabled", "autosave_seconds", "default_import_mode", "daily_backup", "language", "update_url", "check_updates"}
        for k, v in body.items():
            if k in allowed:
                S().db.set_setting(k, v)
        return get_settings()

    # ------------------------------------------------------------------ folders
    @app.get("/api/folders")
    def folders():
        return S().store.folders()

    @app.post("/api/folders")
    def create_folder(body: dict = Body(...)):
        return S().store.create_folder(body.get("name", "Folder"), body.get("parent_id"))

    @app.patch("/api/folders/{fid}")
    def rename_folder(fid: str, body: dict = Body(...)):
        return S().store.rename_folder(fid, body.get("name", ""))

    @app.delete("/api/folders/{fid}")
    def delete_folder(fid: str):
        S().store.delete_folder(fid)
        return {"ok": True}

    # ------------------------------------------------------------------ documents
    @app.get("/api/documents")
    def documents(q: str | None = None, folder_id: str | None = None, sort: str = "updated", trash: bool = False):
        return S().store.list_documents(q, folder_id, sort, trash)

    @app.post("/api/documents")
    async def upload(file: UploadFile = File(...), import_mode: str = Form("editable"), folder_id: str | None = Form(None),
                     extract: bool = Form(True)):
        tmp = await save_upload(file)
        try:
            doc = S().upload(tmp, file.filename or tmp.name, import_mode, folder_id)
        finally:
            cleanup(tmp)
        job = S().create_job("extract", doc["id"]) if extract else None
        return {"document": doc, "job": job}

    @app.get("/api/documents/{did}")
    def document(did: str):
        d = S().store.document(did)
        d["stats"] = M.stats(S().store.load_model(did) or {"blocks": []})
        d["jobs"] = S().db.all("SELECT id, kind, status, progress, created, finished, error FROM jobs WHERE document_id=? ORDER BY created DESC LIMIT 20", (did,))
        d["exports"] = S().db.all("SELECT * FROM exports WHERE document_id=? ORDER BY created DESC LIMIT 50", (did,))
        return d

    @app.patch("/api/documents/{did}")
    def update_document(did: str, body: dict = Body(...)):
        return S().store.update_document(did, **body)

    @app.delete("/api/documents/{did}")
    def delete_document(did: str, permanent: bool = False):
        if permanent:
            S().store.delete_document_permanently(did)
        else:
            S().store.trash_document(did)
        return {"ok": True}

    @app.post("/api/documents/{did}/restore")
    def restore_document(did: str):
        return S().store.restore_document(did)

    @app.post("/api/documents/{did}/duplicate")
    def duplicate_document(did: str):
        return S().store.duplicate_document(did)

    @app.post("/api/documents/{did}/extract")
    def extract(did: str):
        return S().create_job("extract", did)

    @app.get("/api/documents/{did}/model")
    def get_model(did: str):
        m = S().store.load_model(did)
        if m is None:
            raise HTTPException(404, "Not extracted yet")
        return m

    @app.put("/api/documents/{did}/model")
    def put_model(did: str, body: dict = Body(...)):
        m = body.get("model")
        if not isinstance(m, dict) or not isinstance(m.get("blocks"), list):
            raise HTTPException(400, "Invalid document model")
        for b in m["blocks"]:
            if b.get("type") not in M.BLOCK_TYPES or not b.get("id"):
                raise HTTPException(400, f"Invalid block: {str(b)[:80]}")
        autosave = bool(body.get("autosave"))
        d = S().store.save_model(did, m, note=body.get("note") or ("Autosave" if autosave else "Saved"), version=not autosave,
                                 status="edited")
        return {"ok": True, "document": d, "saved": time.time()}

    @app.get("/api/documents/{did}/versions")
    def versions(did: str):
        return S().store.versions(did)

    @app.post("/api/documents/{did}/versions/{vid}/restore")
    def restore_version(did: str, vid: str):
        S().store.restore_version(did, vid)
        return S().store.load_model(did)

    @app.get("/api/documents/{did}/original")
    def original(did: str, download: bool = False):
        d = S().store.document(did)
        return file_response(d["source_path"], download, d["source_name"])

    @app.get("/api/documents/{did}/original/pages/{n}.png")
    def original_page(did: str, n: int, dpi: int = 60):
        import pymupdf
        d = S().store.document(did)
        m = S().store.load_model(did) or {}
        src = (m.get("meta") or {}).get("work_pdf") or d["source_path"]
        if d["kind"] not in ("pdf", "image"):
            raise HTTPException(400, "Page previews are available for PDF and image files")
        pdf = pymupdf.open(src)
        if not 1 <= n <= pdf.page_count:
            raise HTTPException(404, "No such page")
        png = pdf[n - 1].get_pixmap(dpi=max(20, min(dpi, 200))).tobytes("png")
        pdf.close()
        return Response(png, media_type="image/png")

    @app.post("/api/documents/{did}/preview")
    def preview(did: str, body: dict = Body(default={})):
        r = S().preview(did, body.get("template_id"), body.get("model"))
        r["url"] = f"/api/files/preview/{r['file']}"
        return r

    @app.get("/api/files/preview/{name}")
    def preview_file(name: str):
        return file_response(S().paths.sub("Temp") / "preview" / Path(name).name)

    @app.get("/api/documents/{did}/recommend")
    def recommend(did: str):
        return S().recommend(did)

    @app.post("/api/documents/{did}/export")
    def export(did: str, body: dict = Body(default={})):
        recs = S().export(did, body.get("template_id"), body.get("kind", "pdf"), body.get("quality", "print"),
                          bool(body.get("grayscale")), body.get("pages"), body.get("sections"), int(body.get("dpi", 150)))
        return recs

    # ------------------------------------------------------------------ generation
    @app.post("/api/generate")
    def generate(body: dict = Body(...)):
        return S().create_job("generate", body["document_id"], body.get("template_id"), body.get("options") or {})

    @app.post("/api/quick-generate")
    async def quick_generate(file: UploadFile = File(...), template_id: str | None = Form(None),
                             import_mode: str = Form("editable"), options: str = Form("{}")):
        tmp = await save_upload(file)
        try:
            return S().quick_generate(tmp, file.filename or tmp.name, template_id, json.loads(options or "{}"), import_mode)
        finally:
            cleanup(tmp)

    @app.get("/api/jobs")
    def jobs(status: str | None = None, limit: int = 50):
        sql, args = "SELECT id, kind, status, progress, document_id, template_id, batch_id, created, finished, error FROM jobs", []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        return S().db.all(sql + " ORDER BY created DESC LIMIT ?", [*args, limit])

    @app.get("/api/jobs/{jid}")
    def job(jid: str):
        return S().job(jid)

    @app.get("/api/jobs/{jid}/log")
    def job_log(jid: str):
        return S().db.all("SELECT ts, level, message FROM job_log WHERE job_id=? ORDER BY id", (jid,))

    @app.post("/api/jobs/{jid}/retry")
    def retry(jid: str):
        return S().retry_job(jid)

    @app.get("/api/jobs/{jid}/thumb/{n}")
    def job_thumb(jid: str, n: int):
        j = S().job(jid)
        th = ((j.get("result") or {}).get("thumbnails") or [])
        if not 1 <= n <= len(th):
            raise HTTPException(404, "No thumbnail")
        return file_response(th[n - 1])

    @app.get("/api/jobs/{jid}/file/{kind}")
    def job_file(jid: str, kind: str, download: bool = False):
        j = S().job(jid)
        p = ((j.get("result") or {}).get("outputs") or {}).get(kind)
        if not p:
            raise HTTPException(404, "No such output")
        return file_response(p, download)

    # ------------------------------------------------------------------ batches
    @app.post("/api/batches")
    async def create_batch(files: list[UploadFile] = File(...), template_id: str | None = Form(None), name: str | None = Form(None)):
        saved = []
        try:
            for f in files:
                saved.append((await save_upload(f), f.filename or "upload"))
            return S().create_batch(saved, template_id, name)
        finally:
            for p, _ in saved:
                cleanup(p)

    @app.get("/api/batches")
    def batches():
        return S().batches()

    @app.get("/api/batches/{bid}")
    def batch(bid: str):
        return S().batch(bid)

    @app.post("/api/batches/{bid}/retry-failed")
    def batch_retry(bid: str):
        return S().retry_batch_failed(bid)

    @app.get("/api/batches/{bid}/zip")
    def batch_zip(bid: str):
        p = S().batch_zip(bid)
        return file_response(p, True)

    # ------------------------------------------------------------------ exports
    @app.get("/api/exports")
    def exports(document_id: str | None = None, limit: int = 100):
        if document_id:
            return S().db.all("SELECT * FROM exports WHERE document_id=? ORDER BY created DESC LIMIT ?", (document_id, limit))
        return S().db.all("SELECT e.*, d.title FROM exports e LEFT JOIN documents d ON d.id=e.document_id ORDER BY e.created DESC LIMIT ?", (limit,))

    @app.get("/api/exports/{eid}/file")
    def export_file(eid: str, download: bool = False):
        e = S().db.get("exports", eid)
        if not e:
            raise HTTPException(404, "Not found")
        return file_response(e["path"], download)

    # ------------------------------------------------------------------ templates
    @app.get("/api/templates")
    def templates():
        return S().store.templates()

    @app.get("/api/templates/defaults")
    def template_defaults():
        return {"template": T.DEFAULT_TEMPLATE, "branding": T.DEFAULT_BRANDING, "layouts": list(M.PAGE_LAYOUTS)}

    @app.post("/api/templates")
    def create_template(body: dict = Body(...)):
        return S().store.save_template(body)

    @app.get("/api/templates/{tid}")
    def template(tid: str):
        return S().store.template(tid)

    @app.put("/api/templates/{tid}")
    def update_template(tid: str, body: dict = Body(...)):
        t = S().store.template(tid)
        if t["builtin"]:
            raise HTTPException(400, "Built-in templates cannot be changed. Duplicate it to make your own version.")
        return S().store.save_template(body, tid)

    @app.delete("/api/templates/{tid}")
    def delete_template(tid: str):
        S().store.delete_template(tid)
        return {"ok": True}

    @app.post("/api/templates/{tid}/duplicate")
    def duplicate_template(tid: str, body: dict = Body(default={})):
        return S().store.duplicate_template(tid, body.get("name"))

    @app.post("/api/templates/{tid}/default")
    def default_template(tid: str):
        S().store.set_default_template(tid)
        return {"ok": True}

    @app.get("/api/templates/{tid}/export")
    def export_template(tid: str):
        t = S().store.template(tid)
        data = json.dumps({"ptd_template": 1, "config": t["config"]}, ensure_ascii=False, indent=1)
        name = safe_filename(t["name"], "template") + ".ptdtemplate.json"
        return Response(data, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/templates/import")
    async def import_template(file: UploadFile = File(...)):
        raw = await file.read()
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except ValueError:
            raise HTTPException(400, "Not a valid template file")
        cfg = data.get("config") if isinstance(data, dict) and "config" in data else data
        if not isinstance(cfg, dict):
            raise HTTPException(400, "Not a valid template file")
        cfg["name"] = (cfg.get("name") or Path(file.filename or "Imported").stem) + " (imported)"
        # asset references from another computer do not exist here
        for k in ("logo_asset", "secondary_logo_asset"):
            if cfg.get("branding", {}).get(k) and not S().store.asset_path(cfg["branding"][k]):
                cfg["branding"][k] = None
        return S().store.save_template(cfg)

    @app.post("/api/templates/preview")
    def template_preview(body: dict = Body(...)):
        """Render a sample exam with an (unsaved) template config, for the template editor."""
        from .sample import sample_document
        cfg = T.normalize(body.get("config") or {})
        out = S().paths.sub("Temp") / "preview" / f"tpl-{new_id()}.pdf"
        from .layout.renderer import render
        r = render(sample_document(), cfg, S().store.asset_path, out, S().paths.sub("Temp") / "render-cache", {"quality": "standard"})
        for old in out.parent.glob("tpl-*.pdf"):
            if old != out and time.time() - old.stat().st_mtime > 60:
                old.unlink(missing_ok=True)
        return {"url": f"/api/files/preview/{out.name}", "pages": r.pages, "issues": r.issues, "errors": T.validate(cfg)}

    # ------------------------------------------------------------------ branding
    @app.get("/api/branding")
    def branding():
        return S().store.branding_profiles()

    @app.post("/api/branding")
    def create_branding(body: dict = Body(...)):
        return S().store.save_branding(body.get("name", "Branding"), body.get("config") or {})

    @app.put("/api/branding/{bid}")
    def update_branding(bid: str, body: dict = Body(...)):
        return S().store.save_branding(body.get("name", "Branding"), body.get("config") or {}, bid)

    @app.delete("/api/branding/{bid}")
    def delete_branding(bid: str):
        S().store.delete_branding(bid)
        return {"ok": True}

    @app.post("/api/branding/{bid}/default")
    def default_branding(bid: str):
        S().store.set_default_branding(bid)
        return {"ok": True}

    # ------------------------------------------------------------------ assets
    @app.get("/api/assets")
    def assets(kind: str | None = None, document_id: str | None = None):
        return S().store.list_assets(kind, document_id)

    @app.post("/api/assets")
    async def upload_asset(file: UploadFile = File(...), kind: str = Form("image"), name: str | None = Form(None)):
        ext = Path(file.filename or "").suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".svg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}:
            raise HTTPException(400, "Unsupported image type. Use PNG, JPG, SVG, GIF, BMP, TIFF or WEBP.")
        data = await file.read()
        if len(data) > 60 * 1024 * 1024:
            raise HTTPException(413, "Image larger than 60 MB")
        if ext == ".svg":
            _check_svg(data)
        a = S().store.save_asset_bytes(data, ext, kind if kind in ("image", "logo", "watermark", "background") else "image",
                                       name or Path(file.filename or "image").stem)
        return S().store.asset(a["asset"])

    @app.get("/api/assets/{aid}")
    def asset(aid: str):
        a = S().store.asset(aid)
        a["used_by"] = S().store.asset_usage(aid)
        return a

    @app.get("/api/assets/{aid}/file")
    def asset_file(aid: str):
        return file_response(S().store.asset(aid)["path"])

    @app.get("/api/assets/{aid}/thumb")
    def asset_thumb(aid: str, size: int = 320):
        p = Path(S().store.asset(aid)["path"])
        data = IM.thumbnail(p, max(32, min(size, 1200)))
        return Response(data, media_type="image/svg+xml" if p.suffix.lower() == ".svg" else "image/png",
                        headers={"Cache-Control": "max-age=3600"})

    @app.post("/api/assets/{aid}/edit")
    def edit_asset(aid: str, body: dict = Body(...)):
        a = S().store.asset(aid)
        if Path(a["path"]).suffix.lower() == ".svg":
            raise HTTPException(400, "SVG images cannot be edited; they are scaled without quality loss.")
        data = IM.edit(Path(a["path"]), body.get("ops") or {})
        name = body.get("name") or f"{Path(a['name']).stem} (edited)"
        n = S().store.save_asset_bytes(data, "png", body.get("kind") or a["kind"] if a["kind"] != "extracted" else "image",
                                       name, a["document_id"] if body.get("keep_document") else None, {"edited_from": aid, "ops": body.get("ops")})
        return S().store.asset(n["asset"])

    @app.patch("/api/assets/{aid}")
    def rename_asset(aid: str, body: dict = Body(...)):
        S().store.asset(aid)
        S().db.update("assets", aid, {k: v for k, v in body.items() if k in ("name", "kind")})
        return S().store.asset(aid)

    @app.delete("/api/assets/{aid}")
    def delete_asset(aid: str):
        S().store.delete_asset(aid)
        return {"ok": True}

    # ------------------------------------------------------------------ fonts
    @app.get("/api/fonts")
    def fonts():
        return {"families": F.available_families(), "installed": S().store.fonts()}

    @app.post("/api/fonts")
    async def upload_font(file: UploadFile = File(...), family: str | None = Form(None), style: str | None = Form(None)):
        ext = Path(file.filename or "").suffix.lower()
        if ext not in (".ttf", ".otf"):
            raise HTTPException(400, "Only TTF and OTF fonts are supported.")
        data = await file.read()
        if len(data) > 40 * 1024 * 1024:
            raise HTTPException(413, "Font file too large")
        dest = unique_path(S().paths.sub("Fonts"), safe_filename(file.filename or "font.ttf", "font.ttf"))
        dest.write_bytes(data)
        if ext == ".otf":
            from .fontconv import otf_to_ttf_if_needed
            try:
                dest = otf_to_ttf_if_needed(dest)
            except Exception as e:
                dest.unlink(missing_ok=True)
                raise HTTPException(400, f"This OTF font could not be converted: {e}")
        info = F.inspect_font_file(dest)
        if not info.get("ok"):
            dest.unlink(missing_ok=True)
            raise HTTPException(400, f"The font cannot be used in PDFs: {info.get('error')}")
        rec = S().store.add_font(dest, (family or info["family"]).strip()[:60], style if style in F.STYLES else info["style"])
        F.set_custom_fonts(S().store.fonts())
        return rec

    @app.delete("/api/fonts/{fid}")
    def delete_font(fid: str):
        S().store.delete_font(fid)
        F.set_custom_fonts(S().store.fonts())
        return {"ok": True}

    @app.get("/api/fonts/file")
    def font_file(family: str, style: str = "regular"):
        files, _ = F.family_files(family)
        p = files.get(style) or files.get("regular")
        if not p or not Path(p).exists():
            raise HTTPException(404, "Font not found")
        return FileResponse(p, media_type="font/ttf", headers={"Cache-Control": "max-age=86400"})

    # ------------------------------------------------------------------ backups
    @app.get("/api/backups")
    def backups():
        return B.list_backups(S().paths)

    @app.post("/api/backups")
    def make_backup():
        p = S().backup("manual")
        return {"name": p.name, "size": p.stat().st_size}

    @app.post("/api/backups/{name}/restore")
    def restore_backup(name: str):
        safety = S().restore(name)
        return {"ok": True, "safety_backup": safety}

    return app


def _check_svg(data: bytes) -> None:
    head = data[:4096].lower()
    if b"<svg" not in data[:200000].lower():
        raise HTTPException(400, "Not a valid SVG file")
    if b"<script" in data.lower() or b"javascript:" in data.lower() or b"<!entity" in head:
        raise HTTPException(400, "SVG files with scripts or entities are not allowed.")
