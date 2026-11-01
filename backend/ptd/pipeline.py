"""One-click generation pipeline. Each step reports real progress to the job record."""
from __future__ import annotations

import json
import re
import shutil
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

import pymupdf

from . import __version__
from . import exports as X
from . import importers
from . import model as M
from . import validation as V
from .layout import fonts as F
from .layout.original_pages import render_original
from .layout.renderer import RenderError, render
from .mupdf import LOCK as MU
from .mupdf import locked
from .util import now, safe_filename, sha256_json, unique_path, write_json_atomic

if TYPE_CHECKING:
    from .service import Service

ENGINE_VERSION = f"{__version__}-layout3"
STEPS = [
    ("analyze", "Analyzing document"),
    ("extract", "Extracting text and images"),
    ("template", "Applying saved template"),
    ("format", "Formatting pages"),
    ("check", "Checking document integrity"),
    ("export", "Generating final PDF"),
]
WEIGHTS = {"analyze": 0.05, "extract": 0.30, "template": 0.05, "format": 0.30, "check": 0.15, "export": 0.15}
JUNK_TITLES = re.compile(r"^(untitled|anonymous|\(anonymous\)|microsoft word.*|document\d*|none|.{0,2})$", re.I)


class UserError(Exception):
    """Failure with a message meant for the user."""


class Cancelled(Exception):
    pass


def initial_steps() -> list[dict]:
    return [{"key": k, "label": l, "status": "pending", "progress": 0.0, "detail": "", "started": None, "finished": None}
            for k, l in STEPS]


class JobRun:
    def __init__(self, svc: "Service", job: dict):
        self.svc = svc
        self.job = job
        self.id = job["id"]
        self.steps = initial_steps()
        self._last_flush = 0.0
        self.current: str | None = None

    def log(self, msg: str, level: str = "info"):
        self.svc.db.execute("INSERT INTO job_log (job_id, ts, level, message) VALUES (?,?,?,?)", (self.id, now(), level, msg))

    def _step(self, key):
        return next(s for s in self.steps if s["key"] == key)

    def overall(self) -> float:
        tot = 0.0
        wsum = sum(WEIGHTS[s["key"]] for s in self.steps) or 1
        for s in self.steps:
            w = WEIGHTS[s["key"]]
            tot += w * (1.0 if s["status"] in ("done", "skipped") else s["progress"] if s["status"] == "running" else 0)
        return round(min(tot / wsum, 1.0), 4)

    def flush(self, force=False):
        t = time.time()
        if force or t - self._last_flush > 0.2:
            self._last_flush = t
            self.svc.db.update("jobs", self.id, {"steps": self.steps, "progress": self.overall()})

    def start(self, key):
        if self.id in self.svc.cancel_requests:
            raise Cancelled()
        s = self._step(key)
        s.update(status="running", started=now(), progress=0.0)
        self.current = key
        self.log(f"▶ {s['label']}")
        self.flush(True)

    def progress(self, key):
        def cb(frac: float, msg: str = ""):
            s = self._step(key)
            s["progress"] = max(0.0, min(1.0, float(frac)))
            if msg:
                s["detail"] = msg
            self.flush()
        return cb

    def done(self, key, detail: str = "", status: str = "done"):
        s = self._step(key)
        s.update(status=status, progress=1.0, finished=now())
        if detail:
            s["detail"] = detail
        self.log(f"✓ {s['label']}: {detail}" if detail else f"✓ {s['label']}")
        self.flush(True)

    def fail_current(self, msg):
        if self.current:
            s = self._step(self.current)
            s.update(status="failed", detail=msg, finished=now())
        self.flush(True)


def _title_for(doc_rec: dict, m: dict) -> str:
    t = (m.get("title") or "").strip()
    if t and not JUNK_TITLES.match(t):
        return t
    return doc_rec["title"]


def ensure_model(svc: "Service", run: JobRun | None, doc: dict, reextract: bool = False) -> tuple[dict, bool]:
    """Return (model, reused). Extracts when the document has no model yet."""
    m = svc.store.load_model(doc["id"])
    if m is not None and not reextract:
        return m, True
    src = Path(doc["source_path"])
    kind = doc["kind"]
    cb = run.progress("extract") if run else (lambda f, msg="": None)
    ocr_on = bool(svc.db.get_setting("ocr_enabled", True))
    m = importers.extract(src, kind, svc.store.importer_saver(doc["id"]), cb, ocr_enabled=ocr_on)
    if doc["import_mode"] == "original":
        if kind == "pdf":
            m["original_pages"] = [{"index": i, "rotation": 0, "include": True} for i in range(m["meta"].get("source_pages", 0))]
        elif kind == "image":
            work = _images_to_pdf(src, Path(doc["source_path"]).parent.parent / "work" / "original.pdf")
            m["meta"]["work_pdf"] = str(work)
            with MU:
                pd = pymupdf.open(work)
                m["original_pages"] = [{"index": i, "rotation": 0, "include": True} for i in range(pd.page_count)]
                pd.close()
        else:
            m["meta"]["warnings"].append({"level": "warning", "code": "original_mode_unavailable",
                                          "message": "Original-page mode needs a PDF or image. This DOCX was imported as editable content instead."})
    m["title"] = _title_for(doc, m)
    svc.store.save_model(doc["id"], m, note="Imported from original", status="imported")
    svc.store.update_document(doc["id"], title=m["title"] if doc["title"] == Path(doc["source_name"]).stem else doc["title"])
    if run:
        run.log(f"Extracted {M.stats(m)['questions']} questions, {M.stats(m)['images']} images, {M.stats(m)['tables']} tables.")
    return m, False


@locked
def _images_to_pdf(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = pymupdf.open(src)
    pdf = pymupdf.open("pdf", img.convert_to_pdf())
    pdf.save(dest)
    return dest


def render_any(svc: "Service", doc: dict, m: dict, cfg: dict, out: Path, options: dict, progress=None):
    cache = svc.paths.sub("Temp") / "render-cache"
    if doc["import_mode"] == "original" and m.get("original_pages"):
        src = Path(m["meta"].get("work_pdf") or doc["source_path"])
        return render_original(m, cfg, svc.store.asset_path, src, out, cache, options, progress)
    return render(m, cfg, svc.store.asset_path, out, cache, options, progress)


def working_model(m: dict, cfg: dict) -> dict:
    """The model used for layout: automatic numbering is applied to a copy, never to stored content."""
    w = M.clone(m)
    if cfg["questions"]["numbering"] == "auto":
        for q in M.questions(w):
            q["number_mode"] = "auto"
        M.renumber(w)
    return w


def run_generate(svc: "Service", job: dict) -> None:
    run = JobRun(svc, job)
    opts = job.get("options") or {}
    try:
        # ---------------- 1. analyze
        run.start("analyze")
        doc = svc.store.document(job["document_id"])
        src = Path(doc["source_path"])
        if not src.exists():
            raise UserError("The original file is missing from the document folder.")
        detail = f"{doc['kind'].upper()} file, {src.stat().st_size / 1024:.0f} KB"
        if doc["kind"] == "pdf":
            with MU:
                pd = pymupdf.open(src)
                empty = sum(1 for p in pd if len(p.get_text().strip()) < 15)
                detail += f", {pd.page_count} page(s)"
                if empty:
                    detail += f", {empty} without a text layer (OCR needed)"
                pd.close()
        run.done("analyze", detail)

        # ---------------- 2. extract
        run.start("extract")
        m, reused = ensure_model(svc, run, doc, reextract=bool(opts.get("reextract")))
        if job.get("idem_key"):
            # key now reflects the extracted content, so an identical request is recognised later
            _, cfg0 = svc.store.effective_template(job["template_id"])
            svc.db.update("jobs", job["id"], {"idem_key": idem_key(svc, doc, cfg0, opts)})
        st = M.stats(m)
        run.done("extract", ("Using saved document content (edited or previously extracted). " if reused else "")
                 + f"{st['questions']} questions, {st['options']} options, {st['images']} images, {st['tables']} tables")
        if not m.get("blocks") and not m.get("original_pages"):
            raise UserError("No content could be extracted from this document.")

        # ---------------- 3. template
        run.start("template")
        rec, cfg = svc.store.effective_template(job["template_id"])
        F.set_custom_fonts(svc.store.fonts())
        notes = []
        for fam in {cfg["fonts"]["body"], cfg["fonts"]["heading"]}:
            _, note = F.register(fam)
            if note:
                notes.append(note)
        wm = working_model(m, cfg)
        run.done("template", f"“{rec['name']}” — {cfg['fonts']['body']} {cfg['fonts']['body_size']}pt, "
                             f"{cfg['pagination']['density']} density" + (f". {' '.join(notes)}" if notes else ""))

        # ---------------- 4. format
        run.start("format")
        jdir = svc.paths.sub("Temp") / "jobs" / job["id"]
        if jdir.exists():
            shutil.rmtree(jdir, ignore_errors=True)
        jdir.mkdir(parents=True, exist_ok=True)
        pdf_path = jdir / "document.pdf"
        quality = cfg["export"]["quality"]
        r = render_any(svc, doc, wm, cfg, pdf_path, {"quality": quality, "grayscale": cfg["export"]["grayscale"]},
                       run.progress("format"))
        run.done("format", f"{r.pages} page(s) laid out" + (f", {len(r.repairs)} automatic layout repair(s)" if r.repairs else ""))

        # ---------------- 5. check
        run.start("check")
        cbk = run.progress("check")
        cbk(0.1, "Comparing the original with the extracted content")
        issues = V.check_extraction(m, V.source_tokens(src, doc["kind"]))
        cbk(0.4, "Checking the generated PDF")
        if doc["import_mode"] == "original" and m.get("original_pages"):
            r_issues, suggested = list(r.issues), []
        else:
            r_issues, suggested = V.check_render(wm, r, cfg)
        rounds = 0
        seeded: dict[str, list] = {}
        while suggested and rounds < 2:
            rounds += 1
            for s in suggested:
                seeded.setdefault(s["block"], []).append(s["repair"])
            run.log(f"Auto-repair round {rounds}: {', '.join(s['repair'] + '@' + s['block'] for s in suggested)}")
            cbk(0.5 + rounds * 0.15, f"Regenerating pages with {len(suggested)} layout fix(es)")
            r = render_any(svc, doc, wm, cfg, pdf_path, {"quality": quality, "grayscale": cfg["export"]["grayscale"],
                                                        "repairs": seeded})
            r_issues, suggested = V.check_render(wm, r, cfg)
            for s in seeded:
                r_issues.append({"level": "info", "code": "auto_repair", "block": s,
                                 "message": f"Layout regenerated: {', '.join(seeded[s]).replace('_', ' ')}."})
        issues += r_issues
        issues += [w for w in m.get("meta", {}).get("warnings", []) if w.get("level") in ("critical", "warning", "info")
                   and not any(w.get("code") == i.get("code") for i in issues)]
        summary = V.summarize(issues)
        counts = V.compare_counts(wm, r) if not (doc["import_mode"] == "original" and m.get("original_pages")) else {"pages": r.pages}
        run.done("check", ("Passed" if summary["passed"] else "Needs review") +
                 f": {summary['critical']} critical, {summary['warning']} warnings, {summary['info']} notes")

        # ---------------- 6. export
        run.start("export")
        cbx = run.progress("export")
        title = safe_filename(wm.get("title") or doc["title"], default="document")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        edir = svc.paths.sub("Exports") / f"{title} ({doc['id'][-6:]})" / stamp
        while edir.exists():
            stamp += "-1"
            edir = edir.parent / stamp
        edir.mkdir(parents=True)
        final = edir / f"{title}.pdf"
        X.optimize_in_place(pdf_path)
        shutil.copy2(pdf_path, final)
        outputs = {"pdf": str(final)}
        cbx(0.3, "Print-ready PDF written")
        if cfg["export"]["compressed_copy"]:
            comp_src = jdir / "compressed-src.pdf"
            render_any(svc, doc, wm, cfg, comp_src, {"quality": "compressed", "grayscale": cfg["export"]["grayscale"],
                                                     "repairs": seeded})
            comp = X.compress_pdf(comp_src, edir / f"{title} (compressed).pdf")
            outputs["compressed"] = str(comp)
        cbx(0.6, "Creating page previews")
        thumbs = X.thumbnails(final, jdir / "thumbs")
        if cfg["export"].get("page_images"):
            X.page_images(final, edir / "pages", "png", 150)
        X.write_structure(m, edir / "structure.json")
        report = {"summary": summary, "issues": issues, "counts": counts, "template": rec["name"],
                  "engine": ENGINE_VERSION, "generated": now()}
        write_json_atomic(edir / "validation.json", report)
        # verify the files really exist and open before reporting success
        with MU:
            chk = pymupdf.open(final)
            ok_pages = chk.page_count
            chk.close()
        if ok_pages != r.pages or ok_pages == 0:
            raise UserError("The generated PDF could not be verified.")
        for kind_, p in outputs.items():
            svc.db.insert("exports", {"id": f"ex_{job['id'][-10:]}_{kind_}", "document_id": doc["id"], "job_id": job["id"],
                                      "kind": kind_, "path": p, "size": Path(p).stat().st_size, "created": now()})
        log_lines = [f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(l['ts']))} [{l['level']}] {l['message']}"
                     for l in svc.db.all("SELECT * FROM job_log WHERE job_id=? ORDER BY id", (job["id"],))]
        (edir / "processing-log.txt").write_text("\n".join(log_lines), encoding="utf-8")
        delivered = None
        if opts.get("deliver_dir"):
            from . import shell as SH
            delivered = str(SH.deliver(svc, final, Path(opts["deliver_dir"]),
                                       SH.output_name(svc, opts.get("deliver_stem") or title, rec["name"])))
            outputs["delivered"] = delivered
        run.done("export", f"Saved to {Path(delivered).name if delivered else edir.name}")
        status = "succeeded" if summary["passed"] else "needs_review"
        result = {"outputs": outputs, "export_dir": str(edir), "pages": r.pages, "thumbnails": [str(t) for t in thumbs],
                  "validation": {"summary": summary, "issues": issues[:300]}, "counts": counts,
                  "template_name": rec["name"], "positions_available": True, "title": wm.get("title") or doc["title"]}
        svc.db.update("jobs", job["id"], {"status": status, "result": result, "progress": 1.0, "finished": now(),
                                          "steps": run.steps, "error": None})
        svc.store.update_document(doc["id"], status="generated" if status == "succeeded" else "needs_review",
                                  template_id=rec["id"])
        svc.db.update("documents", doc["id"], {"page_count": r.pages})
        run.log(f"Finished: {status}")
    except Cancelled:
        _fail(svc, run, "Cancelled by the user.", status="cancelled")
    except UserError as e:
        _fail(svc, run, str(e))
    except RenderError as e:
        _fail(svc, run, f"Layout failed: {e}")
    except importers.ImportErrorUser as e:
        _fail(svc, run, str(e))
    except Exception as e:  # noqa: BLE001 - every failure must be recorded, never swallowed
        run.log(traceback.format_exc(), "error")
        _fail(svc, run, f"Unexpected error: {e.__class__.__name__}: {e}")


def _fail(svc: "Service", run: JobRun, msg: str, status: str = "failed"):
    run.fail_current(msg)
    run.log(msg, "error" if status == "failed" else "warning")
    svc.db.update("jobs", run.id, {"status": status, "error": msg, "finished": now(), "steps": run.steps})
    svc.cancel_requests.discard(run.id)


def idem_key(svc: "Service", doc: dict, template_cfg: dict, options: dict) -> str:
    m = svc.store.load_model(doc["id"])
    return sha256_json({"src": doc["source_hash"], "model": sha256_json(m) if m else None, "tpl": template_cfg,
                        "opt": {k: v for k, v in options.items() if k != "force"}, "engine": ENGINE_VERSION})


def run_extract(svc: "Service", job: dict) -> None:
    """Import only (PDF Import screen): extraction with progress, no layout."""
    run = JobRun(svc, job)
    run.steps = [s for s in run.steps if s["key"] in ("analyze", "extract")]
    try:
        run.start("analyze")
        doc = svc.store.document(job["document_id"])
        run.done("analyze", f"{doc['kind'].upper()} file")
        run.start("extract")
        m, _ = ensure_model(svc, run, doc, reextract=True)
        st = M.stats(m)
        run.done("extract", f"{st['questions']} questions, {st['images']} images, {st['tables']} tables")
        svc.db.update("jobs", job["id"], {"status": "succeeded", "progress": 1.0, "finished": now(), "steps": run.steps,
                                          "result": {"stats": st, "warnings": m["meta"].get("warnings", [])}})
    except importers.ImportErrorUser as e:
        _fail(svc, run, str(e))
    except Exception as e:  # noqa: BLE001
        run.log(traceback.format_exc(), "error")
        _fail(svc, run, f"Extraction failed: {e}")
