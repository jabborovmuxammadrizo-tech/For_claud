"""SQLite storage. One connection guarded by a lock (writes are small and fast)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .util import now

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS folders (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT, created REAL);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, folder_id TEXT, kind TEXT,
  import_mode TEXT, source_name TEXT, source_path TEXT, source_hash TEXT,
  model_path TEXT, page_count INTEGER, question_count INTEGER,
  status TEXT, warnings TEXT, template_id TEXT,
  created REAL, updated REAL, deleted_at REAL);
CREATE TABLE IF NOT EXISTS document_versions (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version INTEGER NOT NULL,
  model_path TEXT NOT NULL, note TEXT, created REAL);
CREATE TABLE IF NOT EXISTS templates (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT, description TEXT,
  config TEXT NOT NULL, is_default INTEGER DEFAULT 0, builtin INTEGER DEFAULT 0,
  created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS branding_profiles (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL,
  is_default INTEGER DEFAULT 0, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT, path TEXT NOT NULL,
  width INTEGER, height INTEGER, dpi INTEGER, size INTEGER, meta TEXT,
  document_id TEXT, created REAL);
CREATE TABLE IF NOT EXISTS fonts (
  id TEXT PRIMARY KEY, family TEXT NOT NULL, style TEXT NOT NULL, path TEXT NOT NULL,
  builtin INTEGER DEFAULT 0, embeddable INTEGER DEFAULT 1, created REAL);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, document_id TEXT,
  template_id TEXT, batch_id TEXT, idem_key TEXT, options TEXT, steps TEXT,
  progress REAL DEFAULT 0, result TEXT, error TEXT, attempts INTEGER DEFAULT 0,
  created REAL, started REAL, finished REAL);
CREATE INDEX IF NOT EXISTS jobs_idem ON jobs(idem_key);
CREATE TABLE IF NOT EXISTS job_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, ts REAL, level TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY, name TEXT, template_id TEXT, job_ids TEXT, created REAL);
CREATE TABLE IF NOT EXISTS exports (
  id TEXT PRIMARY KEY, document_id TEXT, job_id TEXT, kind TEXT, path TEXT,
  size INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, entity TEXT, entity_id TEXT,
  action TEXT, detail TEXT);
"""

JSON_COLS = {"warnings", "config", "meta", "options", "steps", "result", "job_ids"}


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for k in JSON_COLS & d.keys():
            if isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        return d

    @staticmethod
    def _encode(values: dict) -> dict:
        return {k: (json.dumps(v, ensure_ascii=False) if k in JSON_COLS and v is not None and not isinstance(v, str) else v)
                for k, v in values.items()}

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self.lock:
            return self._decode(self.conn.execute(sql, tuple(params)).fetchone())

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.lock:
            return [self._decode(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def insert(self, table: str, values: dict) -> None:
        values = self._encode(values)
        cols = ",".join(values)
        qs = ",".join("?" * len(values))
        self.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", values.values())

    def update(self, table: str, id_: str, values: dict) -> None:
        if not values:
            return
        values = self._encode(values)
        sets = ",".join(f"{k}=?" for k in values)
        self.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*values.values(), id_])

    def get(self, table: str, id_: str) -> dict | None:
        return self.one(f"SELECT * FROM {table} WHERE id=?", (id_,))

    def audit(self, entity: str, entity_id: str, action: str, detail: Any = None) -> None:
        self.execute("INSERT INTO audit (ts, entity, entity_id, action, detail) VALUES (?,?,?,?,?)",
                     (now(), entity, entity_id, action, json.dumps(detail, ensure_ascii=False) if detail is not None else None))

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except ValueError:
            return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value, ensure_ascii=False)))

    def checkpoint(self) -> None:
        with self.lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def backup_to(self, dest: Path) -> None:
        with self.lock:
            target = sqlite3.connect(str(dest))
            try:
                self.conn.backup(target)
            finally:
                target.close()
