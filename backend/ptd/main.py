"""Backend entry point (packaged as ptd-backend.exe with PyInstaller).

Started by the Electron main process with:
  ptd-backend --port <free port> --parent-pid <electron pid> [--data-dir <path>]
and the per-launch secret in the PTD_TOKEN environment variable (not on the command line,
so other users cannot read it from the process list). Prints 'PTD_READY <port>' when serving.
"""
from __future__ import annotations

import argparse
import logging
import os
import secrets
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _parent_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT -> still running
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _watch_parent(pid: int, on_exit):
    def loop():
        while True:
            time.sleep(2)
            if not _parent_alive(pid):
                logging.getLogger("ptd").warning("Parent process %s is gone - shutting down backend", pid)
                on_exit()
                os._exit(0)
    threading.Thread(target=loop, daemon=True, name="parent-watch").start()


class InstanceLock:
    """Prevents two backends from using the same data folder at once."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self) -> bool:
        self.fh = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fh.seek(0)
            self.fh.truncate()
            self.fh.write(str(os.getpid()))
            self.fh.flush()
            return True
        except OSError:
            return False


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ptd-backend")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--parent-pid", type=int, default=0)
    ap.add_argument("--dev", action="store_true", help="development: print the token and allow the Vite origin")
    ap.add_argument("--self-test", default=None, help="generate a PDF from the given file and exit (used by CI)")
    args = ap.parse_args(argv)

    if args.data_dir:
        os.environ["PTD_DATA_DIR"] = args.data_dir
    from .config import get_paths
    paths = get_paths()

    log_file = paths.sub("Logs") / "backend.log"
    handlers = [RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    log = logging.getLogger("ptd")

    lock = InstanceLock(paths.sub("Settings") / "backend.lock")
    if not lock.acquire():
        print("PTD_ERROR another instance is already running for this data folder", flush=True)
        log.error("Another backend instance holds the lock - exiting")
        return 3

    from .service import Service
    svc = Service(paths)

    if args.self_test:
        return _self_test(svc, Path(args.self_test))

    try:
        from . import backup as B
        if svc.db.get_setting("daily_backup", True) and B.needs_daily_backup(paths):
            threading.Thread(target=lambda: svc.backup("auto"), daemon=True).start()
    except Exception:
        log.exception("Automatic backup failed")

    token = os.environ.get("PTD_TOKEN") or secrets.token_urlsafe(32)
    port = args.port or free_port()
    from .api import create_app
    origins = ["app://ptd"] + (["http://localhost:5173", "http://127.0.0.1:5173"] if args.dev else [])
    app = create_app(svc, token, origins)
    if args.parent_pid:
        _watch_parent(args.parent_pid, svc.close)

    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False, log_config=None)
    server = uvicorn.Server(config)

    def announce():
        while not server.started:
            time.sleep(0.05)
        print(f"PTD_READY {port}", flush=True)
        if args.dev:
            print(f"PTD_TOKEN {token}", flush=True)
        log.info("Backend ready on 127.0.0.1:%s (data: %s)", port, paths.root)
    threading.Thread(target=announce, daemon=True).start()
    try:
        server.run()
    finally:
        svc.close()
    return 0


def _self_test(svc, path: Path) -> int:
    """End-to-end check used by CI on the packaged executable."""
    from .service import Service  # noqa: F401
    r = svc.quick_generate(path, path.name, None)
    j = svc.wait(r["job"]["id"], 600)
    res = j.get("result") or {}
    print(f"SELFTEST status={j['status']} pages={res.get('pages')} pdf={res.get('outputs', {}).get('pdf')} error={j.get('error')}", flush=True)
    for i in (res.get("validation") or {}).get("issues", [])[:20]:
        print(f"  {i['level']}: {i['message']}", flush=True)
    svc.close()
    return 0 if j["status"] in ("succeeded", "needs_review") and res.get("pages") else 1


if __name__ == "__main__":
    sys.exit(main())
