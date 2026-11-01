"""Filesystem layout and runtime configuration."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

SUBFOLDERS = ("Documents", "Templates", "Images", "Logos", "Fonts", "Exports",
              "Backups", "Settings", "Logs", "Uploads", "Temp")


def resource_dir() -> Path:
    """Bundled read-only resources (fonts, sample templates). Works under PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


def default_data_dir() -> Path:
    env = os.environ.get("PTD_DATA_DIR")
    if env:
        return Path(env)
    home = Path.home()
    if sys.platform == "win32":
        # Respect a redirected "Documents" folder (OneDrive etc.) when available.
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL
            if buf.value:
                return Path(buf.value) / "PDF Test Designer"
        except Exception:
            pass
    return home / "Documents" / "PDF Test Designer"


@dataclass
class Paths:
    root: Path

    def __post_init__(self):
        self.root = Path(self.root)
        for name in SUBFOLDERS:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def sub(self, name: str) -> Path:
        return self.root / name

    @property
    def db(self) -> Path:
        return self.root / "Settings" / "ptd.sqlite3"

    def is_inside(self, p: Path) -> bool:
        try:
            Path(p).resolve().relative_to(self.root.resolve())
            return True
        except ValueError:
            return False


_paths: Paths | None = None


def get_paths() -> Paths:
    global _paths
    if _paths is None:
        _paths = Paths(default_data_dir())
    return _paths


def set_paths(root: Path) -> Paths:
    global _paths
    _paths = Paths(root)
    return _paths
