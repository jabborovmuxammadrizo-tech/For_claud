"""Windows Explorer right-click processing engine.

Explorer invokes `PDF Test Designer.exe --shell=<command> <paths…>`; the Electron main process
collects the selection and calls POST /api/shell/run. Every action becomes jobs inside one task
(batch) so progress, notifications, retry and cancellation work the same way as in the app.
Originals are only ever read; results go to the configured output folder with non-conflicting names.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

import pymupdf

from . import importers
from . import model as M
from .importers import ImportErrorUser
from .util import new_id, now

if TYPE_CHECKING:
    from .service import Service

DOC_EXT = {".pdf", ".docx", ".txt"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
SUPPORTED = DOC_EXT | IMG_EXT
COMMANDS = {
    "generate-default", "generate-template", "batch-generate", "open", "edit", "extract", "convert-editable",
    "convert-pdf", "compress", "grayscale", "info", "image-library", "image-pdf", "image-editor",
    "image-background", "image-watermark", "open-folder",
}
SHELL_DEFAULTS = {
    "shell_menu_pdf": True, "shell_menu_docx": True, "shell_menu_folder": True, "shell_menu_image": True,
    "shell_batch": True, "shell_default_action": True, "shell_background": True, "shell_notifications": True,
    "shell_default_template": "", "shell_include_subfolders": False, "output_dir": "",
    "output_naming": "formatted", "output_pattern": "{name}_Formatted", "output_zip": False,
}
NAMING = {"formatted": "{name}_Formatted", "exam": "{name}_Exam"}
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def long_path(p: Path) -> Path:
    """Windows: use the \\\\?\\ prefix for paths longer than MAX_PATH."""
    s = str(p)
    if sys.platform == "win32" and len(s) > 240 and not s.startswith("\\\\?\\"):
        s = "\\\\?\\" + os.path.abspath(s)
    return Path(s)


def settings(svc: "Service") -> dict:
    return {k: svc.db.get_setting(k, v) for k, v in SHELL_DEFAULTS.items()}


def output_dir(svc: "Service") -> Path:
    custom = settings(svc)["output_dir"]
    d = Path(custom) if custom else svc.paths.sub("Exports")
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / f".ptd-write-test-{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        raise ShellError(f"Output folder unavailable: {d} ({e.strerror or e}). Choose another folder in Settings → Windows Integration.")
    return d


def windows_safe(name: str, max_len: int = 150) -> str:
    """Keeps Unicode (Uzbek letters) but removes characters Windows forbids in file names."""
    name = _INVALID.sub("_", name).strip(" .")
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return (name or "document")[:max_len]


def output_name(svc: "Service", src_stem: str, template_name: str = "", ext: str = ".pdf", suffix: str | None = None) -> str:
    st = settings(svc)
    pattern = st["output_pattern"] if st["output_naming"] == "custom" else NAMING.get(st["output_naming"], "{name}_Formatted")
    if suffix is not None:
        pattern = "{name}_" + suffix
    base = (pattern.replace("{name}", src_stem).replace("{template}", template_name)
            .replace("{date}", time.strftime("%Y-%m-%d")).replace("{time}", time.strftime("%H%M")))
    return windows_safe(base) + ext


def unique(directory: Path, filename: str) -> Path:
    p = directory / filename
    stem, ext = Path(filename).stem, Path(filename).suffix
    i = 2
    while p.exists():
        p = directory / f"{stem} ({i}){ext}"
        i += 1
    return p


def deliver(svc: "Service", src: Path, directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    dest = unique(directory, filename)
    shutil.copy2(src, long_path(dest))
    return dest


class ShellError(Exception):
    pass


def collect(paths: list[str], include_subfolders: bool, allowed: set[str] = SUPPORTED) -> tuple[list[Path], list[dict]]:
    files, skipped, seen = [], [], set()
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            skipped.append({"path": raw, "reason": "File not found"})
            continue
        if p.is_dir():
            it = p.rglob("*") if include_subfolders else p.iterdir()
            for f in sorted(it, key=lambda x: str(x).lower()):
                if f.is_file() and f.suffix.lower() in allowed and not f.name.startswith("~$"):
                    key = str(f.resolve()).lower()
                    if key not in seen:
                        seen.add(key)
                        files.append(f)
            continue
        if p.suffix.lower() not in allowed:
            skipped.append({"path": raw, "reason": f"Unsupported file format ({p.suffix or 'no extension'})"})
            continue
        key = str(p.resolve()).lower()
        if key not in seen:
            seen.add(key)
            files.append(p)
    return files, skipped


def _import(svc: "Service", f: Path, mode: str = "editable") -> dict:
    try:
        return svc.upload(long_path(f), f.name, mode)
    except PermissionError:
        raise ShellError(f"“{f.name}” is open or locked by another program. Close it and try again.")


def run(svc: "Service", command: str, paths: list[str], template_id: str | None = None, options: dict | None = None) -> dict:
    """Start a right-click task. Returns {task_id (batch), kind, immediate?, skipped, open?}."""
    if command not in COMMANDS:
        raise ShellError(f"Unknown command '{command}'.")
    st = settings(svc)
    options = options or {}
    include_sub = bool(options.get("include_subfolders", st["shell_include_subfolders"]))
    img_cmd = command.startswith("image-")
    files, skipped = collect(paths, include_sub, IMG_EXT if img_cmd else SUPPORTED)
    if not files:
        reason = skipped[0]["reason"] if skipped else "No supported documents were found."
        raise ShellError(reason)

    # ---- quick, synchronous actions
    if command in ("open", "edit", "open-folder"):
        docs = [_import(svc, f) for f in files[:50]]
        jobs = [svc.create_job("extract", d["id"]) for d in docs]
        return {"kind": "open", "documents": [d["id"] for d in docs], "jobs": [j["id"] for j in jobs], "skipped": skipped}
    if img_cmd and command != "image-pdf":
        return _image_action(svc, command, files, skipped)

    # ---- everything else runs as jobs in one task
    name = _task_name(command, paths, files)
    bid = new_id("bat_")
    tpl_id = None
    if command in ("generate-default", "generate-template", "batch-generate", "convert-pdf"):
        if command == "generate-template" or (command == "batch-generate" and template_id):
            rec, _ = svc.store.effective_template(template_id)
        else:
            default = st["shell_default_template"]
            try:
                rec, _ = svc.store.effective_template(default or None)
            except KeyError:
                raise ShellError("Template not found. Choose a default template in Settings → Windows Integration.")
        tpl_id = rec["id"]
    svc.db.insert("batches", {"id": bid, "name": name, "template_id": tpl_id or (svc.store.default_template() or {}).get("id"),
                              "job_ids": [], "created": now()})
    deliver_dir = str(output_dir(svc) / windows_safe(name)) if len(files) > 1 else str(output_dir(svc))
    job_ids = []
    for f in files:
        try:
            if command in ("generate-default", "generate-template", "batch-generate"):
                doc = _import(svc, f)
                j = svc.create_job("generate", doc["id"], tpl_id, {"force": True, "deliver_dir": deliver_dir,
                                                                    "deliver_stem": f.stem}, batch_id=bid)
            else:
                j = svc.create_op_job(command, f, bid, {"deliver_dir": deliver_dir, "template_id": tpl_id})
            job_ids.append(j["id"])
        except (ShellError, ImportErrorUser, ValueError) as e:
            skipped.append({"path": str(f), "reason": str(e)})
    svc.db.update("batches", bid, {"job_ids": job_ids})
    if not job_ids:
        raise ShellError(skipped[0]["reason"] if skipped else "Nothing to process.")
    return {"kind": "task", "task_id": bid, "skipped": skipped, "output_dir": deliver_dir, "count": len(job_ids)}


def _task_name(command: str, paths: list[str], files: list[Path]) -> str:
    label = {"generate-default": "Generated", "generate-template": "Generated", "batch-generate": "Generated",
             "extract": "Extracted", "convert-editable": "Editable", "convert-pdf": "Converted", "compress": "Compressed",
             "grayscale": "Grayscale", "info": "Information", "image-pdf": "PDF from images"}.get(command, command)
    if len(paths) == 1 and Path(paths[0]).is_dir():
        return f"{Path(paths[0]).name} - {label} {time.strftime('%Y-%m-%d %H%M')}"
    if len(files) == 1:
        return f"{files[0].stem} - {label}"
    return f"{label} {len(files)} documents {time.strftime('%Y-%m-%d %H%M')}"


def _image_action(svc: "Service", command: str, files: list[Path], skipped: list) -> dict:
    assets = []
    for f in files:
        kind = {"image-background": "background", "image-watermark": "watermark"}.get(command, "image")
        a = svc.store.save_asset_bytes(long_path(f).read_bytes(), f.suffix, kind, f.stem)
        assets.append(a["asset"])
    msg = f"{len(assets)} image(s) added to the Image Library."
    if command in ("image-background", "image-watermark"):
        prof = svc.db.one("SELECT * FROM branding_profiles ORDER BY is_default DESC, created ASC LIMIT 1")
        if prof:
            cfg = prof["config"]
            if command == "image-background":
                cfg["background_asset"] = assets[0]
                msg = f"“{files[0].name}” is now the page background of the branding profile “{prof['name']}”."
            else:
                cfg["watermark"] = {**(cfg.get("watermark") or {}), "type": "image", "asset": assets[0],
                                    "opacity": (cfg.get("watermark") or {}).get("opacity", 0.08)}
                msg = f"“{files[0].name}” is now the watermark of the branding profile “{prof['name']}”."
            svc.store.save_branding(prof["name"], cfg, prof["id"])
    return {"kind": "immediate", "message": msg, "assets": assets, "skipped": skipped}


# ====================================================================== operation jobs
OP_STEPS = [("prepare", "Reading document"), ("process", "Processing"), ("save", "Saving result")]


def run_op(svc: "Service", job: dict) -> None:
    from .pipeline import JobRun, WEIGHTS
    for k, _ in OP_STEPS:
        WEIGHTS.setdefault(k, 1 / 3)
    run = JobRun(svc, job)
    run.steps = [{"key": k, "label": l, "status": "pending", "progress": 0.0, "detail": "", "started": None, "finished": None}
                 for k, l in OP_STEPS]
    opts = job.get("options") or {}
    op, src = opts["op"], Path(opts["path"])
    out_dir = Path(opts["deliver_dir"])
    try:
        run.start("prepare")
        if not long_path(src).exists():
            raise ShellError(f"“{src.name}” no longer exists.")
        work = svc.paths.sub("Temp") / "jobs" / job["id"]
        work.mkdir(parents=True, exist_ok=True)
        local = work / ("source" + src.suffix.lower())
        try:
            shutil.copy2(long_path(src), local)
        except PermissionError:
            raise ShellError(f"“{src.name}” is open or locked by another program.")
        run.done("prepare", f"{src.name} ({local.stat().st_size // 1024} KB)")
        run.start("process")
        result: dict = {"source": str(src)}
        delivered: list[str] = []
        if op in ("compress", "grayscale", "info") and src.suffix.lower() != ".pdf":
            raise ShellError(f"{op.capitalize()} works with PDF files only.")
        if op == "compress":
            d = pymupdf.open(local)
            d.rewrite_images(dpi_threshold=160, dpi_target=130, quality=72)
            tmp = work / "compressed.pdf"
            d.save(tmp, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)
            d.close()
            before, after = local.stat().st_size, tmp.stat().st_size
            if after >= before:
                shutil.copy2(local, tmp)
                result["note"] = "The PDF was already optimised; size unchanged."
            run.done("process", f"{before // 1024} KB → {min(after, before) // 1024} KB")
            run.start("save")
            delivered.append(str(deliver(svc, tmp, out_dir, output_name(svc, src.stem, suffix="Compressed"))))
        elif op == "grayscale":
            d = pymupdf.open(local)
            d.recolor(1)
            tmp = work / "gray.pdf"
            d.save(tmp, garbage=3, deflate=True)
            d.close()
            run.done("process", "Colours converted to grayscale (text stays searchable)")
            run.start("save")
            delivered.append(str(deliver(svc, tmp, out_dir, output_name(svc, src.stem, suffix="Grayscale"))))
        elif op == "info":
            result["info"] = document_info(local, src)
            run.done("process", f"{result['info'].get('pages', '?')} pages")
            run.start("save")
        elif op in ("extract", "convert-editable", "convert-pdf", "image-pdf"):
            if op == "image-pdf":
                img = pymupdf.open(local)
                pdf = pymupdf.open("pdf", img.convert_to_pdf())
                tmp = work / "image.pdf"
                pdf.save(tmp)
                run.done("process", f"{pdf.page_count} page(s)")
                run.start("save")
                delivered.append(str(deliver(svc, tmp, out_dir, output_name(svc, src.stem, suffix="Image"))))
            else:
                kind = importers.detect_kind(local, src.name)
                saved: list[tuple[bytes, str]] = []

                def save_image(data, ext, meta):
                    saved.append((data, ext))
                    return {"asset": f"img{len(saved)}", "width": None, "height": None}
                ocr_on = bool(svc.db.get_setting("ocr_enabled", True))
                m = importers.extract(local, kind, save_image, run.progress("process"), ocr_enabled=ocr_on)
                st = M.stats(m)
                result["stats"] = st
                result["warnings"] = m["meta"].get("warnings", [])
                run.done("process", f"{st['questions']} questions, {st['images']} images, {st['tables']} tables")
                run.start("save")
                if op == "extract":
                    folder = unique(out_dir, windows_safe(f"{src.stem}_Extracted"))
                    (folder / "images").mkdir(parents=True)
                    lines = []
                    for b in m["blocks"]:
                        for t in M.block_texts(b):
                            lines.append(((b.get("number") + ". ") if b["type"] == "question" and b.get("number") and t == b.get("text") else "") + t)
                    (folder / f"{windows_safe(src.stem)}.txt").write_text("\n".join(lines), encoding="utf-8")
                    for i, (data, ext) in enumerate(saved, start=1):
                        (folder / "images" / f"image-{i:03d}.{ext}").write_bytes(data)
                    import json
                    (folder / "structure.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
                    delivered.append(str(folder))
                elif op == "convert-editable":
                    from .docx_export import export_docx
                    imgdir = work / "img"
                    imgdir.mkdir(exist_ok=True)
                    paths = {}
                    for i, (data, ext) in enumerate(saved, start=1):
                        p = imgdir / f"img{i}.{ext}"
                        p.write_bytes(data)
                        paths[f"img{i}"] = p
                    out = work / "editable.docx"
                    export_docx(m, out, lambda a: paths.get(a))
                    delivered.append(str(deliver(svc, out, out_dir, output_name(svc, src.stem, ext=".docx", suffix="Editable"))))
                else:  # convert-pdf: faithful, unbranded conversion
                    from .layout.renderer import render
                    from .templates import normalize
                    imgdir = work / "img"
                    imgdir.mkdir(exist_ok=True)
                    paths = {}
                    for i, (data, ext) in enumerate(saved, start=1):
                        p = imgdir / f"img{i}.{ext}"
                        p.write_bytes(data)
                        paths[f"img{i}"] = p
                    plain = normalize({"cover": {"enabled": False}, "header": {"enabled": False},
                                       "branding": {"watermark": {"type": "none"}, "footer_text": ""},
                                       "sections": {"style": "plain", "uppercase": False}, "instructions": {"style": "plain"},
                                       "fonts": {"body": "Liberation Sans", "heading": "Liberation Sans"}})
                    out = work / "converted.pdf"
                    render(m, plain, lambda a: paths.get(a), out, svc.paths.sub("Temp") / "render-cache")
                    delivered.append(str(deliver(svc, out, out_dir, output_name(svc, src.stem, suffix="Converted"))))
        else:
            raise ShellError(f"Unknown operation {op}")
        result["delivered"] = delivered
        result["outputs"] = {"delivered": delivered[0]} if delivered else {}
        run.done("save", Path(delivered[0]).name if delivered else "Done")
        svc.db.update("jobs", job["id"], {"status": "succeeded", "result": result, "progress": 1.0, "finished": now(), "steps": run.steps})
    except Exception as e:  # noqa: BLE001 - recorded and reported, never silent
        from .pipeline import Cancelled, _fail
        if isinstance(e, Cancelled):
            _fail(svc, run, "Cancelled by the user.", status="cancelled")
            return
        if not isinstance(e, (ShellError, ImportErrorUser)):
            run.log(traceback.format_exc(), "error")
        _fail(svc, run, str(e))


def document_info(local: Path, original: Path) -> dict:
    d = pymupdf.open(local)
    pages = d.page_count
    no_text = sum(1 for p in d if len(p.get_text().strip()) < 15)
    images = sum(len(p.get_images()) for p in d)
    fonts = sorted({f[3].split("+")[-1] for p in d for f in p.get_fonts()})
    sizes = sorted({f"{round(p.rect.width / 72 * 25.4)}×{round(p.rect.height / 72 * 25.4)} mm" for p in d})
    meta = {k: v for k, v in (d.metadata or {}).items() if v}
    info = {"file": original.name, "path": str(original), "size": original.stat().st_size if original.exists() else local.stat().st_size,
            "pages": pages, "page_sizes": sizes, "pages_without_text": no_text, "images": images, "fonts": fonts[:40],
            "encrypted": d.is_encrypted, "pdf_version": d.metadata.get("format") if d.metadata else None, "metadata": meta,
            "scanned": no_text > 0 and no_text >= pages * 0.5}
    d.close()
    return info
