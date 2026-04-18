"""SQLite 持久化层：Pitch Job（Phase 6.4 Task 1）。

替代纯内存的 pitch_job_store.py，支持 FastAPI BackgroundTasks 多线程写入。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from cangjie_fos.core import paths as fos_paths

_write_lock = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS pitch_jobs (
    job_id        TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    REAL NOT NULL,
    original_report  TEXT,
    edited_report    TEXT,
    words_json    TEXT,
    audio_path    TEXT,
    committed_at  REAL,
    exp_delta     INTEGER DEFAULT 0,
    exp_reason    TEXT DEFAULT '',
    error_summary TEXT,
    error_detail  TEXT,
    error_code    TEXT,
    html_report_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_pitch_jobs_tenant ON pitch_jobs(tenant_id, created_at DESC);
"""

# Columns that store JSON-serialized Python objects.
_JSON_COLS = {"original_report", "edited_report", "words_json"}

# All writable columns (excludes job_id and created_at which are set at insert time).
_WRITABLE_COLS = {
    "status",
    "original_report",
    "edited_report",
    "words_json",
    "audio_path",
    "committed_at",
    "exp_delta",
    "exp_reason",
    "error_summary",
    "error_detail",
    "error_code",
    "html_report_path",
}


def _db_path() -> str:
    p = fos_paths.get_backend_root() / "data" / "pitch_jobs.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _init_db(conn: sqlite3.Connection) -> None:
    """Initialize schema and run migrations on an open connection."""
    conn.executescript(_DDL)
    conn.commit()
    # Migration: add html_report_path if this is an older DB
    try:
        conn.execute("ALTER TABLE pitch_jobs ADD COLUMN html_report_path TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists


def _connect() -> sqlite3.Connection:
    """Open (or create) the DB and ensure schema exists. WAL mode for concurrent access."""
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_db(conn)
    return conn


def _serialize(col: str, value: Any) -> Any:
    """JSON-serialize a value if it belongs to a JSON column and is a dict/list."""
    if col in _JSON_COLS and isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict, deserializing JSON columns."""
    d: dict[str, Any] = dict(row)
    for col in _JSON_COLS:
        raw = d.get(col)
        if isinstance(raw, str):
            try:
                d[col] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass  # leave as string if unparsable
    # Backward-compatibility alias: report = edited_report ?? original_report
    d["report"] = d["edited_report"] if d.get("edited_report") is not None else d.get("original_report")
    return d


# ---------------------------------------------------------------------------
# Public API (mirrors pitch_job_store.py signatures)
# ---------------------------------------------------------------------------


def db_job_create(job_id: str, tenant_id: str, **extra: Any) -> None:
    """Insert a new job row. *extra* may contain: status, exp_delta, exp_reason."""
    now = time.time()
    status = extra.pop("status", "pending")
    exp_delta = extra.pop("exp_delta", 0)
    exp_reason = extra.pop("exp_reason", "")

    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO pitch_jobs
                    (job_id, tenant_id, status, created_at, exp_delta, exp_reason)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (job_id, tenant_id, str(status), now, exp_delta, exp_reason),
            )
            conn.commit()
        finally:
            conn.close()


def db_job_update(job_id: str, **kwargs: Any) -> None:
    """Update any writable fields on the job row.

    Accepted kwargs: status, original_report (JSON string or dict),
    edited_report (JSON string or dict), words_json (JSON string or list),
    audio_path, html_report_path, committed_at, exp_delta, exp_reason,
    error_summary, error_detail, error_code.

    If a value is a dict or list, it is JSON-serialized automatically.
    """
    updates = {k: _serialize(k, v) for k, v in kwargs.items() if k in _WRITABLE_COLS}
    if not updates:
        return

    set_clause = ", ".join(f"{col} = ?" for col in updates)
    values = list(updates.values()) + [job_id]

    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE pitch_jobs SET {set_clause} WHERE job_id = ?",  # noqa: S608
                values,
            )
            conn.commit()
        finally:
            conn.close()


def db_job_get(job_id: str) -> dict[str, Any] | None:
    """Return the job as a dict, or None if not found.

    original_report, edited_report, and words_json are returned as
    already-deserialized Python objects (not raw JSON strings).
    A 'report' key is added as an alias: edited_report if set, else original_report.
    """
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM pitch_jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return _row_to_dict(row)


def db_job_list_for_tenant(
    tenant_id: str, *, limit: int = 50
) -> list[tuple[str, dict[str, Any]]]:
    """Return list of (job_id, row_dict) sorted by created_at DESC."""
    lim = max(1, min(int(limit), 200))
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM pitch_jobs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant_id, lim),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return [(row["job_id"], _row_to_dict(row)) for row in rows]
