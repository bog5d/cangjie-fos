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
    html_report_path TEXT,
    warnings         TEXT,
    substatus        TEXT
);
CREATE INDEX IF NOT EXISTS idx_pitch_jobs_tenant ON pitch_jobs(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS review_diffs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    committed_at    REAL NOT NULL,
    original_report TEXT,
    edited_report   TEXT,
    diff_summary    TEXT,
    pref_extracted  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_review_diffs_tenant ON review_diffs(tenant_id, committed_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_diffs_pending ON review_diffs(pref_extracted) WHERE pref_extracted = 0;

CREATE TABLE IF NOT EXISTS investor_prefs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id      TEXT NOT NULL,
    created_at     REAL NOT NULL,
    pref_type      TEXT NOT NULL,
    pref_key       TEXT NOT NULL,
    pref_value     TEXT,
    source_job_id  TEXT,
    source_diff_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_investor_prefs_tenant ON investor_prefs(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS executive_memories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id    TEXT NOT NULL,
    tag           TEXT NOT NULL,
    uuid          TEXT NOT NULL,
    raw_text      TEXT NOT NULL,
    refined_text  TEXT,
    weight        REAL NOT NULL DEFAULT 1.0,
    created_at    REAL NOT NULL,
    source_job_id TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_exec_mem_uuid ON executive_memories(uuid);
CREATE INDEX IF NOT EXISTS idx_exec_mem_company ON executive_memories(company_id, tag, created_at DESC);

CREATE TABLE IF NOT EXISTS material_contributions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_filename     TEXT NOT NULL,
    relative_path      TEXT NOT NULL,
    contribution_score REAL NOT NULL DEFAULT 0.0,
    usage_count        INTEGER NOT NULL DEFAULT 0,
    last_used_at       REAL,
    tags               TEXT,
    updated_at         REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mat_contrib_path ON material_contributions(relative_path);

CREATE TABLE IF NOT EXISTS contribution_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contributor TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 0.0,
    job_count   INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_contrib_scores_contributor ON contribution_scores(contributor);

CREATE TABLE IF NOT EXISTS material_match_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL,
    asset_filename TEXT NOT NULL,
    relative_path  TEXT NOT NULL,
    matched_at     REAL NOT NULL,
    score          REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_mat_match_inst ON material_match_history(institution_id, matched_at DESC);
"""

# Columns that store JSON-serialized Python objects.
_JSON_COLS = {"original_report", "edited_report", "words_json", "warnings"}

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
    "interviewee",
    "warnings",
    "substatus",
}


def _db_path() -> str:
    p = fos_paths.get_backend_root() / "data" / "pitch_jobs.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _init_db(conn: sqlite3.Connection) -> None:
    """Initialize schema and run migrations on an open connection."""
    conn.executescript(_DDL)
    conn.commit()
    # Migrations: add columns added after initial release
    for migration in (
        "ALTER TABLE pitch_jobs ADD COLUMN html_report_path TEXT",
        "ALTER TABLE pitch_jobs ADD COLUMN interviewee TEXT",
        "ALTER TABLE pitch_jobs ADD COLUMN warnings TEXT",
        "ALTER TABLE pitch_jobs ADD COLUMN substatus TEXT",
    ):
        try:
            conn.execute(migration)
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
    """Insert a new job row. *extra* may contain: status, exp_delta, exp_reason, interviewee."""
    now = time.time()
    status = extra.pop("status", "pending")
    exp_delta = extra.pop("exp_delta", 0)
    exp_reason = extra.pop("exp_reason", "")
    interviewee = extra.pop("interviewee", None)
    if interviewee is not None:
        interviewee = str(interviewee).strip() or None

    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO pitch_jobs
                    (job_id, tenant_id, status, created_at, exp_delta, exp_reason, interviewee)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (job_id, tenant_id, str(status), now, exp_delta, exp_reason, interviewee),
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


# ---------------------------------------------------------------------------
# review_diffs — 进化飞轮：捕获 original vs edited diff
# ---------------------------------------------------------------------------

def db_diff_insert(
    *,
    job_id: str,
    tenant_id: str,
    committed_at: float,
    original_report: dict | None,
    edited_report: dict,
    diff_summary: dict,
) -> int:
    """Insert a review diff record and return its id."""
    with _write_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """INSERT INTO review_diffs
                    (job_id, tenant_id, committed_at, original_report, edited_report, diff_summary)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    tenant_id,
                    committed_at,
                    json.dumps(original_report, ensure_ascii=False) if original_report else None,
                    json.dumps(edited_report, ensure_ascii=False),
                    json.dumps(diff_summary, ensure_ascii=False),
                ),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        finally:
            conn.close()


def db_diff_list_pending(*, limit: int = 50) -> list[dict[str, Any]]:
    """Return review_diffs rows where pref_extracted = 0."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM review_diffs WHERE pref_extracted = 0 ORDER BY committed_at ASC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for col in ("original_report", "edited_report", "diff_summary"):
            if isinstance(d.get(col), str):
                try:
                    d[col] = json.loads(d[col])
                except Exception:
                    pass
        result.append(d)
    return result


def db_diff_mark_extracted(diff_id: int) -> None:
    """Mark a review_diff row as processed."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE review_diffs SET pref_extracted = 1 WHERE id = ?", (diff_id,)
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# investor_prefs — 结构化投资人偏好
# ---------------------------------------------------------------------------

def db_pref_insert(
    *,
    tenant_id: str,
    pref_type: str,
    pref_key: str,
    pref_value: Any,
    source_job_id: str | None = None,
    source_diff_id: int | None = None,
) -> None:
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO investor_prefs
                    (tenant_id, created_at, pref_type, pref_key, pref_value, source_job_id, source_diff_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    tenant_id,
                    time.time(),
                    pref_type,
                    pref_key,
                    json.dumps(pref_value, ensure_ascii=False) if not isinstance(pref_value, str) else pref_value,
                    source_job_id,
                    source_diff_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def db_job_list_recent_errors(*, limit: int = 5) -> list[dict[str, Any]]:
    """Return recent failed jobs for system diagnostic context injection."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT job_id, tenant_id, created_at, error_summary, error_code "
            "FROM pitch_jobs WHERE status = 'failed' ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 20)),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def db_pref_list_for_tenant(tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM investor_prefs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant_id, limit),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if isinstance(d.get("pref_value"), str):
            try:
                d["pref_value"] = json.loads(d["pref_value"])
            except Exception:
                pass
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# executive_memories — Phase 2: 高管错题本 SQLite 化
# ---------------------------------------------------------------------------


def db_exec_memory_insert(
    *,
    company_id: str,
    tag: str,
    uuid: str,
    raw_text: str,
    refined_text: str | None = None,
    weight: float = 1.0,
    source_job_id: str | None = None,
) -> None:
    """Insert an executive memory entry (idempotent: ignore duplicate uuid)."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO executive_memories
                    (company_id, tag, uuid, raw_text, refined_text, weight, created_at, source_job_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (company_id, tag, uuid, raw_text, refined_text, weight, time.time(), source_job_id),
            )
            conn.commit()
        finally:
            conn.close()


def db_exec_memory_list(
    company_id: str, *, tag: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Return executive memories for a company, optionally filtered by tag."""
    conn = _connect()
    try:
        if tag:
            cur = conn.execute(
                "SELECT * FROM executive_memories WHERE company_id = ? AND tag = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (company_id, tag, max(1, min(int(limit), 500))),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM executive_memories WHERE company_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (company_id, max(1, min(int(limit), 500))),
            )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def db_exec_memory_delete(uuid: str) -> None:
    """Delete an executive memory entry by uuid."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM executive_memories WHERE uuid = ?", (uuid,))
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# material_contributions — Phase 2: 素材贡献度
# ---------------------------------------------------------------------------


def db_material_contribution_upsert(
    asset_filename: str,
    relative_path: str,
    *,
    tags: list[str] | None = None,
    contribution_score_delta: float = 0.0,
    usage_count_delta: int = 0,
) -> None:
    """Upsert a material contribution record (insert or accumulate counts)."""
    now = time.time()
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO material_contributions
                    (asset_filename, relative_path, contribution_score, usage_count, last_used_at, tags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(relative_path) DO UPDATE SET
                    contribution_score = contribution_score + excluded.contribution_score,
                    usage_count = usage_count + excluded.usage_count,
                    last_used_at = excluded.last_used_at,
                    tags = COALESCE(excluded.tags, tags),
                    updated_at = excluded.updated_at""",
                (asset_filename, relative_path, contribution_score_delta, usage_count_delta, now, tags_json, now),
            )
            conn.commit()
        finally:
            conn.close()


def db_material_contributions_list(*, limit: int = 200) -> list[dict[str, Any]]:
    """Return all material contributions sorted by usage_count DESC."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM material_contributions ORDER BY usage_count DESC, contribution_score DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except Exception:
                d["tags"] = []
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# material_match_history — Phase 2: 素材-机构匹配历史
# ---------------------------------------------------------------------------


def db_material_match_insert(
    institution_id: str,
    asset_filename: str,
    relative_path: str,
    *,
    score: float = 0.0,
) -> None:
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO material_match_history
                    (institution_id, asset_filename, relative_path, matched_at, score)
                VALUES (?, ?, ?, ?, ?)""",
                (institution_id, asset_filename, relative_path, time.time(), score),
            )
            conn.commit()
        finally:
            conn.close()


def db_material_matches_list(institution_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM material_match_history WHERE institution_id = ? "
            "ORDER BY matched_at DESC LIMIT ?",
            (institution_id, max(1, min(int(limit), 200))),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# contribution_scores — Phase 2: 贡献度汇总
# ---------------------------------------------------------------------------


def db_contribution_score_upsert(
    contributor: str,
    *,
    score_delta: float,
    job_count_delta: int = 1,
) -> None:
    """Accumulate contribution score for a named contributor."""
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO contribution_scores (contributor, score, job_count, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(contributor) DO UPDATE SET
                    score = score + excluded.score,
                    job_count = job_count + excluded.job_count,
                    updated_at = excluded.updated_at""",
                (contributor, score_delta, job_count_delta, now),
            )
            conn.commit()
        finally:
            conn.close()


def db_contribution_scores_list(*, limit: int = 100) -> list[dict[str, Any]]:
    """Return contribution scores sorted by score DESC."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM contribution_scores ORDER BY score DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
