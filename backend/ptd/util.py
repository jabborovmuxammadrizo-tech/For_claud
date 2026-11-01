from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"[^A-Za-z0-9._\- ]+")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def now() -> float:
    return time.time()


def safe_filename(name: str, default: str = "file", max_len: int = 80) -> str:
    """ASCII-only, Windows-safe file name. Keeps the extension."""
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    name = _SAFE.sub("_", name).strip(" ._")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if not name or name.split(".")[0].upper() in reserved:
        name = default
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: max_len - len(ext) - 1] + "." + ext) if dot and len(ext) < 8 else name[:max_len]
    return name


def unique_path(directory: Path, filename: str) -> Path:
    """Never overwrite: append (2), (3)... when a file exists."""
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / filename
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    i = 2
    while True:
        cand = directory / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


_WORD = re.compile(r"\w+", re.UNICODE)


def norm_tokens(text: str) -> list[str]:
    """Tokens used for content-preservation comparison (case-folded word characters)."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("­", "")
    return [t.casefold() for t in _WORD.findall(text)]
