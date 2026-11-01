"""Domain storage: documents (+versions), assets, templates, branding profiles, fonts."""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from . import model as M
from . import templates as T
from .config import Paths
from .db import DB
from .images import probe
from .util import new_id, now, read_json, safe_filename, sha256_file, sha256_json, unique_path, write_json_atomic

ASSET_DIRS = {"image": "Images", "logo": "Logos", "watermark": "Logos", "background": "Images", "extracted": "Images"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg", ".jpx", ".jp2"}


class NotFound(KeyError):
    pass


class Store:
    def __init__(self, db: DB, paths: Paths):
        self.db = db
        self.paths = paths

    # ------------------------------------------------------------------ assets
    def save_asset_bytes(self, data: bytes, ext: str, kind: str = "image", name: str | None = None,
                         document_id: str | None = None, meta: dict | None = None) -> dict:
        ext = "." + ext.lower().lstrip(".")
        if ext == ".jpeg":
            ext = ".jpg"
        aid = new_id("as_")
        sub = ASSET_DIRS.get(kind, "Images")
        folder = self.paths.sub(sub) / (document_id or "library")
        path = unique_path(folder, safe_filename(f"{name or aid}{ext}", default=aid + ext))
        path.write_bytes(data)
        try:
            info = probe(path)
        except Exception as e:
            path.unlink(missing_ok=True)
            raise ValueError(f"Not a readable image: {e}") from e
        self.db.insert("assets", {"id": aid, "kind": kind, "name": name or path.name, "path": str(path),
                                  "width": info["width"], "height": info["height"], "dpi": info["dpi"],
                                  "size": path.stat().st_size, "meta": meta or {}, "document_id": document_id,
                                  "created": now()})
        return {"asset": aid, "width": info["width"], "height": info["height"]}

    def importer_saver(self, document_id: str):
        def save(data: bytes, ext: str, meta: dict) -> dict:
            return self.save_asset_bytes(data, ext, "extracted", None, document_id, meta)
        return save

    def asset(self, aid: str) -> dict:
        a = self.db.get("assets", aid)
        if not a:
            raise NotFound(aid)
        return a

    def asset_path(self, aid: str | None) -> Path | None:
        if not aid:
            return None
        a = self.db.get("assets", aid)
        return Path(a["path"]) if a else None

    def list_assets(self, kind: str | None = None, document_id: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM assets WHERE 1=1", []
        if kind:
            kinds = kind.split(",")
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        if document_id:
            sql += " AND document_id=?"
            args.append(document_id)
        return self.db.all(sql + " ORDER BY created DESC", args)

    def delete_asset(self, aid: str) -> None:
        a = self.asset(aid)
        used = self.asset_usage(aid)
        if used:
            raise ValueError(f"The image is used by: {', '.join(used[:5])}")
        Path(a["path"]).unlink(missing_ok=True)
        self.db.execute("DELETE FROM assets WHERE id=?", (aid,))

    def asset_usage(self, aid: str) -> list[str]:
        out = []
        for t in self.db.all("SELECT id, name, config FROM templates"):
            if aid in str(t["config"]):
                out.append(f"template '{t['name']}'")
        for b in self.db.all("SELECT id, name, config FROM branding_profiles"):
            if aid in str(b["config"]):
                out.append(f"branding '{b['name']}'")
        return out

    # ------------------------------------------------------------------ documents
    def create_document(self, upload: Path, original_name: str, kind: str, import_mode: str = "editable",
                        folder_id: str | None = None, title: str | None = None) -> dict:
        did = new_id("doc_")
        ddir = self.paths.sub("Documents") / did
        odir = ddir / "original"
        odir.mkdir(parents=True, exist_ok=True)
        dest = odir / safe_filename(original_name, default="original" + Path(original_name).suffix.lower())
        shutil.copy2(upload, dest)
        # the original upload is never modified: make it read-only
        os.chmod(dest, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        rec = {"id": did, "title": title or Path(original_name).stem, "folder_id": folder_id, "kind": kind,
               "import_mode": import_mode, "source_name": original_name, "source_path": str(dest),
               "source_hash": sha256_file(dest), "model_path": None, "page_count": None, "question_count": None,
               "status": "uploaded", "warnings": [], "template_id": None, "created": now(), "updated": now(),
               "deleted_at": None}
        self.db.insert("documents", rec)
        self.db.audit("document", did, "created", {"source": original_name})
        return self.document(did)

    def document(self, did: str, include_deleted: bool = True) -> dict:
        d = self.db.get("documents", did)
        if not d or (d["deleted_at"] and not include_deleted):
            raise NotFound(did)
        return d

    def list_documents(self, q: str | None = None, folder_id: str | None = None, sort: str = "updated",
                       trash: bool = False, limit: int = 500) -> list[dict]:
        sql = "SELECT * FROM documents WHERE " + ("deleted_at IS NOT NULL" if trash else "deleted_at IS NULL")
        args: list = []
        if q:
            sql += " AND (title LIKE ? OR source_name LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        if folder_id:
            sql += " AND folder_id=?"
            args.append(folder_id)
        order = {"updated": "updated DESC", "created": "created DESC", "title": "title COLLATE NOCASE ASC",
                 "questions": "question_count DESC"}.get(sort, "updated DESC")
        return self.db.all(f"{sql} ORDER BY {order} LIMIT ?", [*args, limit])

    def model_path(self, did: str) -> Path:
        return self.paths.sub("Documents") / did / "model.json"

    def load_model(self, did: str) -> dict | None:
        return read_json(self.model_path(did))

    def save_model(self, did: str, doc_model: dict, note: str | None = None, version: bool = True,
                   status: str | None = None) -> dict:
        self.document(did)
        doc_model.setdefault("meta", {})
        p = self.model_path(did)
        write_json_atomic(p, doc_model)
        st = M.stats(doc_model)
        upd = {"model_path": str(p), "question_count": st["questions"], "updated": now(),
               "warnings": doc_model["meta"].get("warnings", [])}
        if status:
            upd["status"] = status
        self.db.update("documents", did, upd)
        if version:
            self._add_version(did, doc_model, note)
        return self.document(did)

    def _add_version(self, did: str, doc_model: dict, note: str | None):
        last = self.db.one("SELECT * FROM document_versions WHERE document_id=? ORDER BY version DESC LIMIT 1", (did,))
        if last and read_json(Path(last["model_path"])) == doc_model:
            return
        v = (last["version"] + 1) if last else 1
        vp = self.paths.sub("Documents") / did / "versions" / f"v{v:04d}.json"
        write_json_atomic(vp, doc_model)
        self.db.insert("document_versions", {"id": new_id("ver_"), "document_id": did, "version": v,
                                             "model_path": str(vp), "note": note or "", "created": now()})
        old = self.db.all("SELECT * FROM document_versions WHERE document_id=? ORDER BY version DESC LIMIT -1 OFFSET 50", (did,))
        for o in old:
            Path(o["model_path"]).unlink(missing_ok=True)
            self.db.execute("DELETE FROM document_versions WHERE id=?", (o["id"],))

    def versions(self, did: str) -> list[dict]:
        return self.db.all("SELECT id, version, note, created FROM document_versions WHERE document_id=? ORDER BY version DESC", (did,))

    def restore_version(self, did: str, vid: str) -> dict:
        v = self.db.one("SELECT * FROM document_versions WHERE id=? AND document_id=?", (vid, did))
        if not v:
            raise NotFound(vid)
        m = read_json(Path(v["model_path"]))
        return self.save_model(did, m, note=f"Restored version {v['version']}")

    def update_document(self, did: str, **fields) -> dict:
        allowed = {k: v for k, v in fields.items() if k in ("title", "folder_id", "template_id", "status")}
        allowed["updated"] = now()
        self.db.update("documents", did, allowed)
        return self.document(did)

    def trash_document(self, did: str) -> None:
        self.document(did)
        self.db.update("documents", did, {"deleted_at": now()})
        self.db.audit("document", did, "trashed")

    def restore_document(self, did: str) -> dict:
        self.db.update("documents", did, {"deleted_at": None, "updated": now()})
        self.db.audit("document", did, "restored")
        return self.document(did)

    def delete_document_permanently(self, did: str) -> None:
        d = self.document(did)
        if not d["deleted_at"]:
            raise ValueError("Move the document to the trash before deleting it permanently.")
        ddir = self.paths.sub("Documents") / did
        if ddir.exists() and self.paths.is_inside(ddir):
            for p in ddir.rglob("*"):
                if p.is_file():
                    os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            shutil.rmtree(ddir, ignore_errors=True)
        for a in self.list_assets(document_id=did):
            Path(a["path"]).unlink(missing_ok=True)
        self.db.execute("DELETE FROM assets WHERE document_id=?", (did,))
        self.db.execute("DELETE FROM document_versions WHERE document_id=?", (did,))
        self.db.execute("DELETE FROM documents WHERE id=?", (did,))
        self.db.audit("document", did, "deleted")

    def duplicate_document(self, did: str) -> dict:
        d = self.document(did)
        nd = self.create_document(Path(d["source_path"]), d["source_name"], d["kind"], d["import_mode"],
                                  d["folder_id"], title=f"{d['title']} (copy)")
        m = self.load_model(did)
        if m:
            self.save_model(nd["id"], m, note="Duplicated", status=d["status"])
        return self.document(nd["id"])

    # ------------------------------------------------------------------ folders
    def folders(self) -> list[dict]:
        rows = self.db.all("SELECT * FROM folders ORDER BY name COLLATE NOCASE")
        counts = {r["folder_id"]: r["n"] for r in self.db.all(
            "SELECT folder_id, COUNT(*) n FROM documents WHERE deleted_at IS NULL GROUP BY folder_id")}
        for r in rows:
            r["count"] = counts.get(r["id"], 0)
        return rows

    def create_folder(self, name: str, parent_id: str | None = None) -> dict:
        fid = new_id("fld_")
        self.db.insert("folders", {"id": fid, "name": name.strip()[:80] or "Folder", "parent_id": parent_id, "created": now()})
        return self.db.get("folders", fid)

    def rename_folder(self, fid: str, name: str) -> dict:
        self.db.update("folders", fid, {"name": name.strip()[:80]})
        return self.db.get("folders", fid)

    def delete_folder(self, fid: str) -> None:
        self.db.execute("UPDATE documents SET folder_id=NULL WHERE folder_id=?", (fid,))
        self.db.execute("DELETE FROM folders WHERE id=?", (fid,))

    # ------------------------------------------------------------------ branding
    def branding_profiles(self) -> list[dict]:
        return self.db.all("SELECT * FROM branding_profiles ORDER BY is_default DESC, name COLLATE NOCASE")

    def branding(self, bid: str) -> dict:
        b = self.db.get("branding_profiles", bid)
        if not b:
            raise NotFound(bid)
        return b

    def save_branding(self, name: str, config: dict, bid: str | None = None) -> dict:
        cfg = T.deep_merge(T.DEFAULT_BRANDING, config or {})
        if bid:
            self.branding(bid)
            self.db.update("branding_profiles", bid, {"name": name, "config": cfg, "updated": now()})
        else:
            bid = new_id("br_")
            first = not self.db.one("SELECT id FROM branding_profiles LIMIT 1")
            self.db.insert("branding_profiles", {"id": bid, "name": name, "config": cfg, "is_default": 1 if first else 0,
                                                 "created": now(), "updated": now()})
        return self.branding(bid)

    def delete_branding(self, bid: str) -> None:
        users = [t["name"] for t in self.db.all("SELECT name, config FROM templates") if (t["config"] or {}).get("branding_profile_id") == bid]
        if users:
            raise ValueError(f"This branding profile is used by templates: {', '.join(users[:5])}")
        self.db.execute("DELETE FROM branding_profiles WHERE id=?", (bid,))

    def set_default_branding(self, bid: str) -> None:
        self.branding(bid)
        self.db.execute("UPDATE branding_profiles SET is_default=0")
        self.db.update("branding_profiles", bid, {"is_default": 1})

    # ------------------------------------------------------------------ templates
    def templates(self) -> list[dict]:
        return self.db.all("SELECT * FROM templates ORDER BY is_default DESC, builtin DESC, name COLLATE NOCASE")

    def template(self, tid: str) -> dict:
        t = self.db.get("templates", tid)
        if not t:
            raise NotFound(tid)
        return t

    def default_template(self) -> dict | None:
        return self.db.one("SELECT * FROM templates ORDER BY is_default DESC, builtin DESC, created ASC LIMIT 1")

    def save_template(self, config: dict, tid: str | None = None) -> dict:
        cfg = T.normalize(config)
        errs = T.validate(cfg)
        if errs:
            raise ValueError(" ".join(errs))
        name = (cfg.get("name") or "Untitled template").strip()[:120]
        cfg["name"] = name
        if tid:
            self.template(tid)
            self.db.update("templates", tid, {"name": name, "category": cfg.get("category"),
                                              "description": cfg.get("description", ""), "config": cfg, "updated": now()})
        else:
            tid = new_id("tpl_")
            self.db.insert("templates", {"id": tid, "name": name, "category": cfg.get("category"),
                                         "description": cfg.get("description", ""), "config": cfg, "is_default": 0,
                                         "builtin": 0, "created": now(), "updated": now()})
        write_json_atomic(self.paths.sub("Templates") / f"{tid}.json", cfg)
        self.db.audit("template", tid, "saved", {"name": name})
        return self.template(tid)

    def duplicate_template(self, tid: str, name: str | None = None) -> dict:
        t = self.template(tid)
        cfg = dict(t["config"])
        cfg["name"] = name or f"{t['name']} (copy)"
        return self.save_template(cfg)

    def delete_template(self, tid: str) -> None:
        t = self.template(tid)
        if t["is_default"]:
            raise ValueError("The default template cannot be deleted. Set another template as default first.")
        self.db.execute("DELETE FROM templates WHERE id=?", (tid,))
        (self.paths.sub("Templates") / f"{tid}.json").unlink(missing_ok=True)
        self.db.audit("template", tid, "deleted", {"name": t["name"]})

    def set_default_template(self, tid: str) -> None:
        self.template(tid)
        self.db.execute("UPDATE templates SET is_default=0")
        self.db.update("templates", tid, {"is_default": 1})

    def effective_template(self, tid: str | None) -> tuple[dict, dict]:
        """Template config with its branding profile merged in. Returns (record, config)."""
        rec = self.template(tid) if tid else self.default_template()
        if rec is None:
            raise NotFound("template")
        cfg = T.normalize(rec["config"])
        bp = cfg.get("branding_profile_id")
        if bp:
            prof = self.db.get("branding_profiles", bp)
            if prof:
                cfg["branding"] = T.deep_merge(prof["config"], {k: v for k, v in (rec["config"].get("branding_overrides") or {}).items()})
        return rec, cfg

    def template_hash(self, cfg: dict) -> str:
        return sha256_json(cfg)

    # ------------------------------------------------------------------ fonts
    def fonts(self) -> list[dict]:
        return self.db.all("SELECT * FROM fonts ORDER BY family, style")

    def add_font(self, path: Path, family: str, style: str) -> dict:
        fid = new_id("fnt_")
        self.db.insert("fonts", {"id": fid, "family": family, "style": style, "path": str(path), "builtin": 0,
                                 "embeddable": 1, "created": now()})
        return self.db.get("fonts", fid)

    def delete_font(self, fid: str) -> None:
        f = self.db.get("fonts", fid)
        if not f:
            raise NotFound(fid)
        Path(f["path"]).unlink(missing_ok=True)
        self.db.execute("DELETE FROM fonts WHERE id=?", (fid,))

    # ------------------------------------------------------------------ seed
    def seed(self) -> None:
        if not self.db.one("SELECT id FROM branding_profiles LIMIT 1"):
            self.save_branding("Mirzo Ulugbek NTM (demo)", T.DEFAULT_BRANDING)
        if not self.db.one("SELECT id FROM templates WHERE builtin=1 LIMIT 1"):
            for i, spec in enumerate(T.BUILTIN):
                spec = dict(spec)
                is_def = spec.pop("is_default", False)
                cfg = T.normalize(spec)
                tid = f"tpl_builtin_{i + 1:02d}"
                self.db.insert("templates", {"id": tid, "name": cfg["name"], "category": cfg["category"],
                                             "description": cfg.get("description", ""), "config": cfg,
                                             "is_default": 1 if is_def else 0, "builtin": 1,
                                             "created": now() + i * 1e-3, "updated": now()})
                write_json_atomic(self.paths.sub("Templates") / f"{tid}.json", cfg)
