"""Application service: wires storage, the job runner, previews, exports, batches and backups."""
from __future__ import annotations

import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import backup as B
from . import exports as X
from . import model as M
from . import pipeline as P
from . import recommend as R
from . import validation as V
from .config import Paths
from .db import DB
from .layout import fonts as F
from .store import NotFound, Store
from .util import new_id, now, safe_filename, sha256_json, unique_path

log = logging.getLogger("ptd")


class Service:
    def __init__(self, paths: Paths, workers: int = 2):
        self.paths = paths
        self.db = DB(paths.db)
        self.store = Store(self.db, paths)
        self._backup_before_upgrade()
        self.store.seed()
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ptd-job")
        self._preview_lock = threading.Lock()
        self.cancel_requests: set[str] = set()
        F.set_custom_fonts(self.store.fonts())
        self._recover_interrupted()

    def _backup_before_upgrade(self):
        """A new application version backs up the user's data before touching it."""
        from . import __version__
        prev = self.db.get_setting("app_version")
        if prev and prev != __version__:
            try:
                B.create_backup(self.db, self.paths, f"before-upgrade-{prev}")
            except Exception:
                log.exception("Pre-upgrade backup failed")
        self.db.set_setting("app_version", __version__)

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.db.checkpoint()
        self.db.close()

    def reopen_db(self):
        self.db = DB(self.paths.db)
        self.store = Store(self.db, self.paths)
        F.set_custom_fonts(self.store.fonts())

    def _recover_interrupted(self):
        for j in self.db.all("SELECT id FROM jobs WHERE status IN ('queued','running')"):
            self.db.update("jobs", j["id"], {"status": "failed", "finished": now(),
                                             "error": "Interrupted because the application was closed. Click Retry to run it again."})
            self.db.execute("INSERT INTO job_log (job_id, ts, level, message) VALUES (?,?,?,?)",
                            (j["id"], now(), "warning", "Recovered after unexpected shutdown; marked as interrupted."))

    # ------------------------------------------------------------------ jobs
    def _submit(self, job_id: str):
        job = self.db.get("jobs", job_id)
        from . import shell as SH
        fn = {"generate": P.run_generate, "extract": P.run_extract, "op": SH.run_op}[job["kind"]]

        def runner():
            j = self.db.get("jobs", job_id)
            if j["status"] != "queued":
                return
            self.db.update("jobs", job_id, {"status": "running", "started": now(), "attempts": (j["attempts"] or 0) + 1})
            fn(self, self.db.get("jobs", job_id))
        self.pool.submit(runner)

    def create_job(self, kind: str, document_id: str, template_id: str | None = None, options: dict | None = None,
                   batch_id: str | None = None) -> dict:
        options = options or {}
        doc = self.store.document(document_id)
        key = None
        if kind == "generate":
            rec, cfg = self.store.effective_template(template_id)
            template_id = rec["id"]
            key = P.idem_key(self, doc, cfg, options)
            if not options.get("force"):
                prev = self.db.one("SELECT * FROM jobs WHERE idem_key=? AND status IN ('succeeded','needs_review','queued','running') "
                                   "ORDER BY created DESC LIMIT 1", (key,))
                if prev and (prev["status"] in ("queued", "running") or Path((prev["result"] or {}).get("outputs", {}).get("pdf", "")).exists()):
                    return {**prev, "reused": True}
        jid = new_id("job_")
        steps = P.initial_steps() if kind == "generate" else [s for s in P.initial_steps() if s["key"] in ("analyze", "extract")]
        self.db.insert("jobs", {"id": jid, "kind": kind, "status": "queued", "document_id": document_id,
                                "template_id": template_id, "batch_id": batch_id, "idem_key": key, "options": options,
                                "steps": steps, "progress": 0, "attempts": 0, "created": now()})
        self._submit(jid)
        return self.db.get("jobs", jid)

    def create_op_job(self, op: str, path: Path, batch_id: str | None, options: dict | None = None) -> dict:
        jid = new_id("job_")
        self.db.insert("jobs", {"id": jid, "kind": "op", "status": "queued", "document_id": None, "template_id": None,
                                "batch_id": batch_id, "idem_key": None,
                                "options": {**(options or {}), "op": op, "path": str(path), "name": path.name},
                                "steps": [], "progress": 0, "attempts": 0, "created": now()})
        self._submit(jid)
        return self.db.get("jobs", jid)

    def cancel_batch(self, bid: str) -> dict:
        b = self.batch(bid)
        for j in b["jobs"]:
            if j["status"] == "queued":
                self.db.update("jobs", j["id"], {"status": "cancelled", "error": "Cancelled by the user.", "finished": now()})
            elif j["status"] == "running":
                self.cancel_requests.add(j["id"])
        return self.batch(bid)

    def retry_job(self, job_id: str) -> dict:
        j = self.db.get("jobs", job_id)
        if not j:
            raise NotFound(job_id)
        if j["status"] in ("queued", "running"):
            return j
        steps = P.initial_steps() if j["kind"] == "generate" else [] if j["kind"] == "op" else \
            [s for s in P.initial_steps() if s["key"] in ("analyze", "extract")]
        self.db.update("jobs", job_id, {"status": "queued", "steps": steps, "progress": 0, "error": None, "result": None,
                                        "started": None, "finished": None})
        self.db.execute("INSERT INTO job_log (job_id, ts, level, message) VALUES (?,?,?,?)", (job_id, now(), "info", "Retry requested"))
        self._submit(job_id)
        return self.db.get("jobs", job_id)

    def job(self, job_id: str, log_tail: int = 40) -> dict:
        j = self.db.get("jobs", job_id)
        if not j:
            raise NotFound(job_id)
        j["log"] = list(reversed(self.db.all("SELECT ts, level, message FROM job_log WHERE job_id=? ORDER BY id DESC LIMIT ?",
                                             (job_id, log_tail))))
        return j

    def wait(self, job_id: str, timeout: float = 600) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout:
            j = self.db.get("jobs", job_id)
            if j["status"] not in ("queued", "running"):
                return j
            time.sleep(0.1)
        raise TimeoutError(job_id)

    # ------------------------------------------------------------------ upload + quick generate
    def upload(self, tmp: Path, original_name: str, import_mode: str = "editable", folder_id: str | None = None) -> dict:
        from . import importers
        kind = importers.detect_kind(tmp, original_name)
        if import_mode not in ("editable", "original"):
            import_mode = "editable"
        return self.store.create_document(tmp, original_name, kind, import_mode, folder_id)

    def quick_generate(self, tmp: Path, original_name: str, template_id: str | None, options: dict | None = None,
                       import_mode: str = "editable") -> dict:
        doc = self.upload(tmp, original_name, import_mode)
        job = self.create_job("generate", doc["id"], template_id, options or {})
        return {"document": doc, "job": job}

    # ------------------------------------------------------------------ batches
    def create_batch(self, files: list[tuple[Path, str]], template_id: str | None, name: str | None = None,
                     options: dict | None = None) -> dict:
        rec, _ = self.store.effective_template(template_id)
        bid = new_id("bat_")
        self.db.insert("batches", {"id": bid, "name": name or time.strftime("Batch %Y-%m-%d %H:%M"),
                                   "template_id": rec["id"], "job_ids": [], "created": now()})
        job_ids, errors = [], []
        for tmp, original in files:
            try:
                doc = self.upload(tmp, original)
                job = self.create_job("generate", doc["id"], rec["id"], {**(options or {}), "force": True}, batch_id=bid)
                job_ids.append(job["id"])
            except Exception as e:  # noqa: BLE001 - one bad file must not stop the batch
                errors.append({"file": original, "error": str(e)})
        self.db.update("batches", bid, {"job_ids": job_ids})
        b = self.batch(bid)
        b["upload_errors"] = errors
        return b

    def batch(self, bid: str) -> dict:
        b = self.db.get("batches", bid)
        if not b:
            raise NotFound(bid)
        jobs = []
        for jid in b["job_ids"] or []:
            j = self.db.get("jobs", jid)
            if j:
                d = self.db.get("documents", j["document_id"]) if j["document_id"] else None
                name = d["source_name"] if d else (j["options"] or {}).get("name", "")
                jobs.append({"id": j["id"], "kind": j["kind"], "status": j["status"], "progress": j["progress"], "error": j["error"],
                             "document_id": j["document_id"], "title": d["title"] if d else Path(name).stem, "source_name": name,
                             "steps": j["steps"], "result": j["result"]})
        b["jobs"] = jobs
        done = [j for j in jobs if j["status"] not in ("queued", "running")]
        b["progress"] = round(sum(1 if j["status"] not in ("queued", "running") else j["progress"] for j in jobs) / max(1, len(jobs)), 4)
        b["counts"] = {s: sum(1 for j in jobs if j["status"] == s) for s in ("queued", "running", "succeeded", "needs_review", "failed", "cancelled")}
        b["finished"] = len(done) == len(jobs)
        tpl = self.db.get("templates", b["template_id"])
        b["template_name"] = tpl["name"] if tpl else ""
        return b

    def batches(self, limit: int = 30) -> list[dict]:
        return [self.batch(b["id"]) for b in self.db.all("SELECT id FROM batches ORDER BY created DESC LIMIT ?", (limit,))]

    def retry_batch_failed(self, bid: str) -> dict:
        for j in self.batch(bid)["jobs"]:
            if j["status"] == "failed":
                self.retry_job(j["id"])
        return self.batch(bid)

    def batch_zip(self, bid: str) -> Path:
        b = self.batch(bid)
        files = []
        for j in b["jobs"]:
            outs = (j.get("result") or {}).get("outputs") or {}
            pdf = outs.get("pdf") or (outs.get("delivered") if str(outs.get("delivered", "")).lower().endswith(".pdf") else None)
            if pdf and Path(pdf).exists():
                files.append((Path(pdf), Path(pdf).name))
        if not files:
            raise ValueError("No finished documents in this batch yet.")
        dest = unique_path(self.paths.sub("Exports") / "Batches", safe_filename(f"{b['name']}.zip", "batch.zip"))
        return X.zip_files(files, dest)

    # ------------------------------------------------------------------ preview (editor)
    def preview(self, did: str, template_id: str | None, model_override: dict | None = None) -> dict:
        doc = self.store.document(did)
        m = model_override or self.store.load_model(did)
        if m is None:
            raise ValueError("The document has not been extracted yet.")
        rec, cfg = self.store.effective_template(template_id or doc.get("template_id"))
        wm = P.working_model(m, cfg)
        key = sha256_json({"m": wm, "t": cfg, "e": P.ENGINE_VERSION})[:20]
        out = self.paths.sub("Temp") / "preview" / f"{did}-{key}.pdf"
        with self._preview_lock:
            r = P.render_any(self, doc, wm, cfg, out, {"quality": "standard"})
            if doc["import_mode"] == "original" and wm.get("original_pages"):
                issues = r.issues
            else:
                issues, _ = V.check_render(wm, r, cfg)
            for old in out.parent.glob(f"{did}-*.pdf"):
                if old != out and time.time() - old.stat().st_mtime > 30:
                    old.unlink(missing_ok=True)
        return {"pdf": str(out), "file": out.name, "pages": r.pages, "positions": r.positions, "page_size": r.page_size,
                "issues": issues, "summary": V.summarize(issues), "template_id": rec["id"], "numbers": {q["id"]: q.get("number") for q in M.questions(wm)},
                "cover_pages": r.cover_pages, "page_layouts": r.page_layouts}

    # ------------------------------------------------------------------ custom export
    def export(self, did: str, template_id: str | None, kind: str = "pdf", quality: str = "print", grayscale: bool = False,
               pages: list[int] | None = None, sections: list[str] | None = None, dpi: int = 150) -> list[dict]:
        doc = self.store.document(did)
        m = self.store.load_model(did)
        if m is None:
            raise ValueError("The document has not been extracted yet.")
        rec, cfg = self.store.effective_template(template_id or doc.get("template_id"))
        wm = P.working_model(m, cfg)
        title = safe_filename(wm.get("title") or doc["title"], "document")
        edir = self.paths.sub("Exports") / f"{title} ({did[-6:]})" / ("custom-" + time.strftime("%Y%m%d-%H%M%S"))
        edir.mkdir(parents=True, exist_ok=True)
        opts: dict = {"quality": quality, "grayscale": grayscale}
        include = None
        if sections:
            include = _section_blocks(wm, sections)
            opts["include_blocks"] = sorted(include)
        if kind == "json":
            out = X.write_structure(m, edir / f"{title}.structure.json")
            return [self._record_export(did, "json", out)]
        if kind == "template":
            import json
            out = edir / f"{safe_filename(rec['name'], 'template')}.ptdtemplate.json"
            out.write_text(json.dumps(rec["config"], ensure_ascii=False, indent=1), encoding="utf-8")
            return [self._record_export(did, "template", out)]
        suffix = (" (grayscale)" if grayscale else "") + (" (compressed)" if quality == "compressed" else "") + \
                 (" (sections)" if sections else "")
        pdf = edir / f"{title}{suffix}.pdf"
        r = P.render_any(self, doc, wm, cfg, pdf, opts)
        if quality == "compressed":
            X.compress_pdf(pdf, pdf.with_suffix(".c.pdf"))
            pdf.with_suffix(".c.pdf").replace(pdf)
        else:
            X.optimize_in_place(pdf)
        if pages:
            sel = edir / f"{title}{suffix} (pages {pages[0]}-{pages[-1]}).pdf"
            X.select_pages(pdf, sel, pages)
            pdf.unlink()
            pdf = sel
        if kind in ("png", "jpeg", "jpg"):
            imgs = X.page_images(pdf, edir / "pages", kind, dpi, prefix=title[:40])
            zipf = X.zip_files([(p, p.name) for p in imgs], edir / f"{title} pages ({kind}).zip")
            return [self._record_export(did, f"pages-{kind}", zipf)]
        return [self._record_export(did, "pdf-custom", pdf)]

    def _record_export(self, did: str, kind: str, path: Path) -> dict:
        eid = new_id("ex_")
        self.db.insert("exports", {"id": eid, "document_id": did, "job_id": None, "kind": kind, "path": str(path),
                                   "size": path.stat().st_size, "created": now()})
        return self.db.get("exports", eid)

    # ------------------------------------------------------------------ misc
    def recommend(self, did: str) -> list[dict]:
        m = self.store.load_model(did)
        if m is None:
            return []
        return R.recommend(m, self.store.templates())

    def dashboard(self) -> dict:
        one = lambda sql, a=(): (self.db.one(sql, a) or {}).get("n", 0)  # noqa: E731
        recent_docs = self.store.list_documents(sort="updated", limit=8)
        recent_exports = self.db.all("SELECT e.*, d.title FROM exports e LEFT JOIN documents d ON d.id=e.document_id "
                                     "ORDER BY e.created DESC LIMIT 8")
        history = self.db.all("SELECT j.id, j.kind, j.status, j.progress, j.created, j.finished, j.error, d.title "
                              "FROM jobs j LEFT JOIN documents d ON d.id=j.document_id ORDER BY j.created DESC LIMIT 12")
        usage = {}
        for sub in ("Documents", "Exports", "Images", "Logos", "Fonts", "Backups", "Temp"):
            usage[sub] = sum(p.stat().st_size for p in self.paths.sub(sub).rglob("*") if p.is_file())
        try:
            free = shutil.disk_usage(self.paths.root).free
        except OSError:
            free = None
        return {
            "counts": {"documents": one("SELECT COUNT(*) n FROM documents WHERE deleted_at IS NULL"),
                       "generated": one("SELECT COUNT(*) n FROM jobs WHERE kind='generate' AND status IN ('succeeded','needs_review')"),
                       "templates": one("SELECT COUNT(*) n FROM templates"),
                       "exports": one("SELECT COUNT(*) n FROM exports"),
                       "failed": one("SELECT COUNT(*) n FROM jobs WHERE status='failed'"),
                       "trash": one("SELECT COUNT(*) n FROM documents WHERE deleted_at IS NOT NULL")},
            "recent_documents": recent_docs, "recent_exports": recent_exports, "history": history,
            "storage": {"by_folder": usage, "total": sum(usage.values()), "free": free, "root": str(self.paths.root)},
        }

    def history(self, limit: int = 200) -> list[dict]:
        return self.db.all("SELECT j.id, j.kind, j.status, j.progress, j.created, j.started, j.finished, j.error, j.attempts, "
                           "j.batch_id, j.template_id, d.title, d.source_name FROM jobs j LEFT JOIN documents d ON d.id=j.document_id "
                           "ORDER BY j.created DESC LIMIT ?", (limit,))

    def backup(self, reason: str = "manual") -> Path:
        self.db.checkpoint()
        return B.create_backup(self.db, self.paths, reason)

    def restore(self, name: str) -> str:
        self.pool.shutdown(wait=True)
        safety = B.restore_backup(self.db, self.paths, name)
        self.reopen_db()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ptd-job")
        self._recover_interrupted()
        return safety.name


def _section_blocks(m: dict, section_ids: list[str]) -> set:
    """Block ids belonging to the given sections (a section runs until the next section)."""
    sel = set(section_ids)
    out, cur = set(), None
    for b in m.get("blocks", []):
        if b["type"] == "section":
            cur = b["id"]
        if cur in sel:
            out.add(b["id"])
    return out
