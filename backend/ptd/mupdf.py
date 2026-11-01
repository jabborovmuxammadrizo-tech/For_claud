"""MuPDF (PyMuPDF) is not thread-safe: every call into it is serialised through this lock.
ReportLab layout work stays parallel; only PDF reading/writing with PyMuPDF waits."""
from __future__ import annotations

import functools
import threading

LOCK = threading.RLock()


def locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with LOCK:
            return fn(*args, **kwargs)
    return wrapper
