"""Local backups (database, templates, settings, documents) and restore."""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import time
import zipfile
from pathlib import Path

from .config import Paths
from .db import DB

INCLUDE_DIRS = ("Documents", "Templates", "Logos", "Images", "Fonts", "Settings")
KEEP_AUTO = 10


def create_backup(db: DB, paths: Paths, reason: str = "manual") -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = paths.sub("Backups") / f"backup-{stamp}-{reason}.zip"
    i = 2
    while dest.exists():
        dest = paths.sub("Backups") / f"backup-{stamp}-{reason}-{i}.zip"
        i += 1
    with tempfile.TemporaryDirectory(dir=paths.sub("Temp")) as td:
        snap = Path(td) / "ptd.sqlite3"
        db.backup_to(snap)
        tmp = dest.with_suffix(".partial")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.write(snap, "Settings/ptd.sqlite3")
            for d in INCLUDE_DIRS:
                base = paths.sub(d)
                for p in base.rglob("*"):
                    if p.is_file() and not p.name.startswith("ptd.sqlite3") and not p.suffix == ".tmp":
                        z.write(p, p.relative_to(paths.root).as_posix())
        tmp.replace(dest)
    if reason != "manual":
        autos = sorted([p for p in paths.sub("Backups").glob("backup-*.zip") if not p.stem.endswith("manual")],
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for old in autos[KEEP_AUTO:]:
            old.unlink(missing_ok=True)
    db.audit("backup", dest.name, "created", {"reason": reason})
    return dest


def list_backups(paths: Paths) -> list[dict]:
    out = []
    for p in sorted(paths.sub("Backups").glob("backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        out.append({"name": p.name, "size": p.stat().st_size, "created": p.stat().st_mtime})
    return out


def needs_daily_backup(paths: Paths) -> bool:
    b = list_backups(paths)
    return not b or time.time() - b[0]["created"] > 24 * 3600


def restore_backup(db: DB, paths: Paths, name: str) -> Path:
    """Restore into place. A safety backup of the current state is created first.
    The caller must reopen the database afterwards."""
    src = paths.sub("Backups") / Path(name).name
    if not src.exists():
        raise FileNotFoundError(name)
    with zipfile.ZipFile(src) as z:
        bad = z.testzip()
        if bad:
            raise ValueError(f"Backup is damaged ({bad}).")
        names = z.namelist()
        if "Settings/ptd.sqlite3" not in names:
            raise ValueError("This is not a PDF Test Designer backup.")
        for n in names:
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError("Backup contains unsafe paths.")
    safety = create_backup(db, paths, "pre-restore")
    db.close()
    for d in ("Documents", "Templates"):
        target = paths.sub(d)
        for p in target.rglob("*"):
            if p.is_file():
                os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(paths.db) + suffix).unlink(missing_ok=True)
    with zipfile.ZipFile(src) as z:
        z.extractall(paths.root)
    return safety
