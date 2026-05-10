"""SQLite 持久化层：Pitch Job（Phase 6.4 Task 1）。

替代纯内存的 pitch_job_store.py，支持 FastAPI BackgroundTasks 多线程写入。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid as _uuid
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

CREATE TABLE IF NOT EXISTS nightly_suggestions (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    created_at  REAL NOT NULL,
    consumed_at REAL,
    type        TEXT NOT NULL,
    content     TEXT NOT NULL,
    asset_id    TEXT,
    priority    INTEGER DEFAULT 5
);
CREATE INDEX IF NOT EXISTS idx_nightly_suggestions_pending
    ON nightly_suggestions(tenant_id, consumed_at) WHERE consumed_at IS NULL;

CREATE TABLE IF NOT EXISTS assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    filename        TEXT NOT NULL,
    relative_path   TEXT NOT NULL,
    full_path       TEXT,
    last_modified   TEXT,
    summary         TEXT DEFAULT '',
    tags            TEXT DEFAULT '[]',
    scan_dir        TEXT,
    indexed_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_path ON assets(relative_path);

CREATE TABLE IF NOT EXISTS asset_scan_config (
    id          INTEGER PRIMARY KEY,
    scan_dir    TEXT NOT NULL DEFAULT '',
    auto_scan   INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_health_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at     REAL NOT NULL,
    score           INTEGER NOT NULL DEFAULT 0,
    total_files     INTEGER NOT NULL DEFAULT 0,
    indexed_files   INTEGER NOT NULL DEFAULT 0,
    missing_cats    TEXT DEFAULT '[]',
    scan_dir        TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_asset_health_snapshot ON asset_health_history(snapshot_at DESC);

CREATE TABLE IF NOT EXISTS match_sessions (
    id               TEXT PRIMARY KEY,
    created_at       REAL NOT NULL,
    institution      TEXT NOT NULL DEFAULT '',
    req_text         TEXT NOT NULL DEFAULT '',
    requirements     TEXT NOT NULL DEFAULT '[]',
    results          TEXT NOT NULL DEFAULT '[]',
    status           TEXT NOT NULL DEFAULT 'draft',
    confirmed_files  TEXT DEFAULT '[]',
    output_dir       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_match_sessions_created ON match_sessions(created_at DESC);

CREATE TABLE IF NOT EXISTS match_outcomes (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    institution  TEXT NOT NULL DEFAULT '',
    asset_path   TEXT NOT NULL,
    asset_name   TEXT NOT NULL DEFAULT '',
    was_selected INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_match_outcomes_institution ON match_outcomes(institution);
CREATE INDEX IF NOT EXISTS idx_match_outcomes_session ON match_outcomes(session_id);

CREATE TABLE IF NOT EXISTS wiki_entities (
    name            TEXT PRIMARY KEY,
    entity_type     TEXT NOT NULL DEFAULT 'concept',
    aliases         TEXT NOT NULL DEFAULT '[]',
    profile_json    TEXT NOT NULL DEFAULT '{}',
    timeline_json   TEXT NOT NULL DEFAULT '[]',
    summary         TEXT NOT NULL DEFAULT '',
    confidence      REAL NOT NULL DEFAULT 1.0,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wiki_entities_type ON wiki_entities(entity_type);

CREATE TABLE IF NOT EXISTS wiki_links (
    id              TEXT PRIMARY KEY,
    source_name     TEXT NOT NULL,
    target_name     TEXT NOT NULL,
    relationship    TEXT NOT NULL,
    context         TEXT NOT NULL DEFAULT '',
    strength        REAL NOT NULL DEFAULT 1.0,
    source_doc      TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL,
    invalid_at      REAL,
    UNIQUE(source_name, target_name, relationship)
);
CREATE INDEX IF NOT EXISTS idx_wiki_links_source ON wiki_links(source_name);
CREATE INDEX IF NOT EXISTS idx_wiki_links_target ON wiki_links(target_name);

CREATE TABLE IF NOT EXISTS wiki_episodes (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,
    source_id       TEXT NOT NULL DEFAULT '',
    raw_text        TEXT NOT NULL,
    entity_names    TEXT NOT NULL DEFAULT '[]',
    extracted_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wiki_episodes_source ON wiki_episodes(source_id);

CREATE TABLE IF NOT EXISTS job_participants (
    id           TEXT PRIMARY KEY,
    job_id       TEXT NOT NULL,
    tenant_id    TEXT NOT NULL,
    speaker_id   TEXT NOT NULL,
    real_name    TEXT NOT NULL DEFAULT '',
    institution  TEXT NOT NULL DEFAULT '',
    role         TEXT NOT NULL DEFAULT '其他',
    title        TEXT NOT NULL DEFAULT '',
    confirmed_at REAL NOT NULL,
    confirmed_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_job_participants_job ON job_participants(job_id);
CREATE INDEX IF NOT EXISTS idx_job_participants_tenant ON job_participants(tenant_id);
"""

# Columns that store JSON-serialized Python objects.
_JSON_COLS = {"original_report", "edited_report", "words_json", "warnings"}

# All writable columns (excludes job_id and created_at which are set at insert time).
_WRITABLE_COLS = {
    "status",
    "participants_confirmed",
    "category",
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
        "ALTER TABLE assets ADD COLUMN asset_status TEXT NOT NULL DEFAULT 'approved'",
        "ALTER TABLE pitch_jobs ADD COLUMN participants_confirmed INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE pitch_jobs ADD COLUMN category TEXT NOT NULL DEFAULT ''",
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
    tenant_id: str, *, limit: int = 50, offset: int = 0
) -> list[tuple[str, dict[str, Any]]]:
    """Return list of (job_id, row_dict) sorted by created_at DESC."""
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM pitch_jobs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (tenant_id, lim, off),
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
# job_participants — 参与人身份确认
# ---------------------------------------------------------------------------

_PARTICIPANT_VALID_ROLES = {
    "企业方创始人", "企业方高管", "企业方投融资",
    "GP执行", "LP投资方", "政府招商", "其他",
}


def db_speaker_summary(job_id: str) -> list[dict[str, Any]]:
    """从 words_json 提取每位说话人的前3句原文，供用户对照身份。"""
    job = db_job_get(job_id)
    if not job:
        return []
    words_json = job.get("words_json") or []
    if isinstance(words_json, str):
        try:
            words_json = json.loads(words_json)
        except Exception:
            return []

    speakers: dict[str, list[str]] = {}
    speaker_counts: dict[str, int] = {}
    for w in words_json:
        sid = str(w.get("speaker_id", "0"))
        text = str(w.get("text", "")).strip()
        if not text:
            continue
        speaker_counts[sid] = speaker_counts.get(sid, 0) + 1
        if sid not in speakers:
            speakers[sid] = []
        if len(speakers[sid]) < 3:
            speakers[sid].append(text[:120])

    return [
        {
            "speaker_id": sid,
            "sample_lines": lines,
            "word_count": speaker_counts.get(sid, 0),
        }
        for sid, lines in sorted(speakers.items())
    ]


def db_participants_get(job_id: str) -> list[dict[str, Any]]:
    """返回该 job 已确认的参与人列表。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM job_participants WHERE job_id = ? ORDER BY rowid",
            (job_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def db_participants_save(
    *,
    job_id: str,
    tenant_id: str,
    participants: list[dict[str, Any]],
    confirmed_by: str,
) -> None:
    """原子地保存参与人列表并将 job 标记为已确认。"""
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM job_participants WHERE job_id = ?", (job_id,))
            for p in participants:
                role = p.get("role", "其他")
                if role not in _PARTICIPANT_VALID_ROLES:
                    role = "其他"
                conn.execute(
                    """INSERT INTO job_participants
                        (id, job_id, tenant_id, speaker_id, real_name, institution, role, title, confirmed_at, confirmed_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid.uuid4()),
                        job_id,
                        tenant_id,
                        str(p.get("speaker_id", "")),
                        str(p.get("real_name", "")).strip(),
                        str(p.get("institution", "")).strip(),
                        role,
                        str(p.get("title", "")).strip(),
                        now,
                        confirmed_by,
                    ),
                )
            conn.execute(
                "UPDATE pitch_jobs SET participants_confirmed = 1 WHERE job_id = ?",
                (job_id,),
            )
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


# ---------------------------------------------------------------------------
# nightly_suggestions — Phase 3: 夜间自动进化建议
# ---------------------------------------------------------------------------


def db_nightly_suggestion_insert(
    *,
    id: str,
    tenant_id: str,
    type: str,
    content: str,
    asset_id: str | None = None,
    priority: int = 5,
) -> None:
    """Insert a nightly suggestion record."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO nightly_suggestions
                    (id, tenant_id, created_at, type, content, asset_id, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (id, tenant_id, time.time(), type, content, asset_id, priority),
            )
            conn.commit()
        finally:
            conn.close()


def db_nightly_suggestion_list_pending(
    tenant_id: str, *, limit: int = 3, max_priority: int = 5
) -> list[dict[str, Any]]:
    """Return unconsumed suggestions for a tenant with priority <= max_priority."""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT * FROM nightly_suggestions
               WHERE tenant_id = ? AND consumed_at IS NULL AND priority <= ?
               ORDER BY priority ASC, created_at ASC LIMIT ?""",
            (tenant_id, max_priority, max(1, min(int(limit), 20))),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def db_nightly_suggestion_mark_consumed(suggestion_id: str) -> None:
    """Mark a nightly suggestion as consumed."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE nightly_suggestions SET consumed_at = ? WHERE id = ?",
                (time.time(), suggestion_id),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Phase 4: 全数据关联查询函数
# ---------------------------------------------------------------------------


def db_job_list_risk_keywords(tenant_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """查询某租户最近N条已完成路演的风险点列表（用于素材匹配分析）。

    返回格式: [{"job_id": str, "risk_points": list, "created_at": float}, ...]
    """
    lim = max(1, min(int(limit), 50))
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT job_id, original_report, edited_report, created_at "
            "FROM pitch_jobs WHERE tenant_id = ? AND status = 'completed' "
            "ORDER BY created_at DESC LIMIT ?",
            (tenant_id, lim),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        d = dict(row)
        # Prefer edited_report, fall back to original_report
        report_raw = d.get("edited_report") or d.get("original_report")
        report: dict = {}
        if isinstance(report_raw, str):
            try:
                report = json.loads(report_raw)
            except Exception:
                pass
        elif isinstance(report_raw, dict):
            report = report_raw

        risk_points = report.get("risk_points") or []
        result.append({
            "job_id": d["job_id"],
            "risk_points": risk_points,
            "created_at": d["created_at"],
        })
    return result


def db_assets_search_by_keywords(tenant_id: str, keywords: list[str]) -> list[dict[str, Any]]:
    """查询素材库中与关键词匹配的素材（基于 material_contributions 表 tags/asset_filename 字段）。

    返回格式: [{"asset_filename": str, "relative_path": str, "tags": list, "usage_count": int, ...}, ...]
    tenant_id 参数保留扩展用（当前表不含 tenant_id，返回全局数据）。
    """
    if not keywords:
        return []

    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT asset_filename, relative_path, tags, usage_count, contribution_score, last_used_at "
            "FROM material_contributions ORDER BY usage_count DESC LIMIT 500"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    matched = []
    kw_lower = [kw.casefold() for kw in keywords if kw.strip()]
    for row in rows:
        d = dict(row)
        tags: list[str] = []
        if isinstance(d.get("tags"), str):
            try:
                tags = json.loads(d["tags"])
            except Exception:
                tags = []
        elif isinstance(d.get("tags"), list):
            tags = d["tags"]
        d["tags"] = tags

        filename_lower = (d.get("asset_filename") or "").casefold()
        tags_lower = [t.casefold() for t in tags]
        for kw in kw_lower:
            if kw in filename_lower or any(kw in t for t in tags_lower):
                matched.append(d)
                break  # avoid duplicate entries per asset

    return matched


def db_material_contribution_bulk_upsert(
    tenant_id: str, asset_ids: list[str], action: str
) -> None:
    """批量 upsert 素材贡献度（路演用到了哪些素材 → 增加 usage_count）。

    asset_ids: asset_filename 列表
    action: 操作类型标注（用于日志，不影响 DB 写入逻辑）
    tenant_id 参数保留扩展用。
    """
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            for asset_id in asset_ids:
                conn.execute(
                    """INSERT INTO material_contributions
                        (asset_filename, relative_path, contribution_score, usage_count, last_used_at, tags, updated_at)
                    VALUES (?, ?, 0.0, 1, ?, '[]', ?)
                    ON CONFLICT(relative_path) DO UPDATE SET
                        usage_count = usage_count + 1,
                        last_used_at = excluded.last_used_at,
                        updated_at = excluded.updated_at""",
                    (asset_id, asset_id, now, now),
                )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# assets — 向上扫描结果持久化
# ---------------------------------------------------------------------------


def db_asset_upsert(
    filename: str,
    relative_path: str,
    full_path: str = "",
    last_modified: str = "",
    summary: str = "",
    tags: list[str] | None = None,
    scan_dir: str = "",
) -> None:
    """Upsert 单条资产记录（相对路径作唯一键）。"""
    now = time.time()
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO assets
                    (filename, relative_path, full_path, last_modified, summary, tags, scan_dir, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(relative_path) DO UPDATE SET
                    filename      = excluded.filename,
                    full_path     = excluded.full_path,
                    last_modified = excluded.last_modified,
                    summary       = excluded.summary,
                    tags          = excluded.tags,
                    scan_dir      = excluded.scan_dir,
                    indexed_at    = excluded.indexed_at""",
                (filename, relative_path, full_path, last_modified, summary, tags_json, scan_dir, now),
            )
            conn.commit()
        finally:
            conn.close()


def db_assets_list(limit: int = 500) -> list[dict[str, Any]]:
    """返回资产列表，按 indexed_at 倒序。"""
    lim = max(1, min(int(limit), 2000))
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM assets ORDER BY indexed_at DESC LIMIT ?", (lim,)
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except (json.JSONDecodeError, ValueError):
            d["tags"] = []
        result.append(d)
    return result


def db_assets_clear() -> int:
    """删除全部资产记录，返回删除行数。"""
    with _write_lock:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM assets")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


def db_scan_config_get() -> dict[str, Any] | None:
    """返回扫描配置（单行），无配置时返回 None。"""
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM asset_scan_config WHERE id = 1")
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    d = dict(row)
    d["auto_scan"] = bool(d.get("auto_scan", 0))
    return d


def db_scan_config_set(scan_dir: str, auto_scan: bool = False) -> None:
    """写入（或覆盖）扫描配置。"""
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO asset_scan_config (id, scan_dir, auto_scan, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    scan_dir   = excluded.scan_dir,
                    auto_scan  = excluded.auto_scan,
                    updated_at = excluded.updated_at""",
                (str(scan_dir), int(auto_scan), now),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# asset_health_history — 资产活力雷达快照
# ---------------------------------------------------------------------------


def db_health_snapshot_insert(
    score: int,
    total_files: int,
    indexed_files: int,
    missing_cats: list[str] | None = None,
    scan_dir: str = "",
) -> int:
    """插入一条健康度快照，返回 rowid。"""
    now = time.time()
    cats_json = json.dumps(missing_cats or [], ensure_ascii=False)
    with _write_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """INSERT INTO asset_health_history
                    (snapshot_at, score, total_files, indexed_files, missing_cats, scan_dir)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (now, int(score), int(total_files), int(indexed_files), cats_json, str(scan_dir)),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()


def db_health_snapshot_list(limit: int = 30) -> list[dict[str, Any]]:
    """返回最近 N 条快照，按 snapshot_at 倒序。"""
    lim = max(1, min(int(limit), 365))
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM asset_health_history ORDER BY snapshot_at DESC LIMIT ?", (lim,)
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["missing_cats"] = json.loads(d.get("missing_cats") or "[]")
        except (json.JSONDecodeError, ValueError):
            d["missing_cats"] = []
        result.append(d)
    return result


def db_health_snapshot_latest() -> dict[str, Any] | None:
    """返回最新一条快照，若无则返回 None。"""
    snaps = db_health_snapshot_list(limit=1)
    return snaps[0] if snaps else None


# ---------------------------------------------------------------------------
# match_sessions — 尽调响应台会话持久化
# ---------------------------------------------------------------------------

_MATCH_JSON_COLS = {"requirements", "results", "confirmed_files"}


def _match_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d: dict[str, Any] = dict(row)
    for col in _MATCH_JSON_COLS:
        raw = d.get(col)
        if isinstance(raw, str):
            try:
                d[col] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                d[col] = []
    return d


def db_match_session_create(
    session_id: str,
    institution: str,
    req_text: str,
    requirements: list[dict],
    results: list[dict],
) -> None:
    """插入新匹配会话记录。"""
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO match_sessions
                    (id, created_at, institution, req_text, requirements, results, status)
                VALUES (?, ?, ?, ?, ?, ?, 'draft')""",
                (
                    session_id,
                    now,
                    str(institution),
                    str(req_text),
                    json.dumps(requirements, ensure_ascii=False),
                    json.dumps(results, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def db_match_session_get(session_id: str) -> dict[str, Any] | None:
    """按 ID 取会话，不存在返回 None。"""
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM match_sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    return _match_row_to_dict(row) if row else None


def db_match_session_list(limit: int = 50) -> list[dict[str, Any]]:
    """返回最近 N 条会话，按 created_at 倒序。"""
    lim = max(1, min(int(limit), 200))
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM match_sessions ORDER BY created_at DESC LIMIT ?", (lim,)
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_match_row_to_dict(r) for r in rows]


def db_match_session_update(session_id: str, **kwargs: Any) -> None:
    """更新会话字段（status / confirmed_files / output_dir）。"""
    _allowed = {"status", "confirmed_files", "output_dir"}
    updates: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k not in _allowed:
            continue
        if k in _MATCH_JSON_COLS and isinstance(v, (list, dict)):
            updates[k] = json.dumps(v, ensure_ascii=False)
        else:
            updates[k] = v
    if not updates:
        return
    set_clause = ", ".join(f"{col} = ?" for col in updates)
    values = list(updates.values()) + [session_id]
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE match_sessions SET {set_clause} WHERE id = ?",  # noqa: S608
                values,
            )
            conn.commit()
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# Wiki Knowledge Graph — 实体 CRUD
# ─────────────────────────────────────────────────────────────────

def db_wiki_entity_upsert(
    *,
    name: str,
    entity_type: str = "concept",
    aliases: list[str] | None = None,
    profile_json: dict[str, Any] | None = None,
    summary: str = "",
    confidence: float = 1.0,
    timeline_event: dict[str, Any] | None = None,
) -> None:
    """插入或更新实体页面。timeline_event 会追加到时间线，而非覆盖。"""
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            # 读取现有时间线
            cur = conn.execute(
                "SELECT timeline_json FROM wiki_entities WHERE name = ?", (name,)
            )
            row = cur.fetchone()
            if row:
                try:
                    existing_timeline: list[dict[str, Any]] = json.loads(row["timeline_json"])
                except (json.JSONDecodeError, TypeError):
                    existing_timeline = []
            else:
                existing_timeline = []

            if timeline_event:
                existing_timeline.append({
                    "date": timeline_event.get("date") or "",
                    "event": timeline_event.get("event") or "",
                    "recorded_at": now,
                })

            conn.execute(
                """
                INSERT INTO wiki_entities
                    (name, entity_type, aliases, profile_json, timeline_json, summary, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    entity_type  = excluded.entity_type,
                    aliases      = excluded.aliases,
                    profile_json = excluded.profile_json,
                    timeline_json = excluded.timeline_json,
                    summary      = CASE WHEN excluded.summary != '' THEN excluded.summary ELSE wiki_entities.summary END,
                    confidence   = excluded.confidence,
                    updated_at   = excluded.updated_at
                """,
                (
                    name,
                    entity_type,
                    json.dumps(aliases or [], ensure_ascii=False),
                    json.dumps(profile_json or {}, ensure_ascii=False),
                    json.dumps(existing_timeline, ensure_ascii=False),
                    summary,
                    confidence,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def db_wiki_entity_get(name: str) -> dict[str, Any] | None:
    """读取单个实体页面，返回 None 如果不存在。JSON 字段自动解析。"""
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM wiki_entities WHERE name = ?", (name,))
        row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        for col in ("aliases", "profile_json", "timeline_json"):
            raw = d.get(col)
            if isinstance(raw, str):
                try:
                    d[col] = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    d[col] = [] if col != "profile_json" else {}
        return d
    finally:
        conn.close()


def db_wiki_entity_list(
    entity_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """列出所有（或指定类型）实体，按 updated_at 倒序。"""
    conn = _connect()
    try:
        if entity_type:
            cur = conn.execute(
                "SELECT * FROM wiki_entities WHERE entity_type = ? ORDER BY updated_at DESC LIMIT ?",
                (entity_type, limit),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM wiki_entities ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        d = dict(row)
        for col in ("aliases", "profile_json", "timeline_json"):
            raw = d.get(col)
            if isinstance(raw, str):
                try:
                    d[col] = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    d[col] = [] if col != "profile_json" else {}
        result.append(d)
    return result


# ─────────────────────────────────────────────────────────────────
# Wiki Knowledge Graph — 链接 CRUD
# ─────────────────────────────────────────────────────────────────

def db_wiki_link_upsert(
    *,
    source_name: str,
    target_name: str,
    relationship: str,
    context: str = "",
    strength: float = 1.0,
    source_doc: str = "",
    invalidate: bool = False,
) -> None:
    """建立或更新双向链接。invalidate=True 时标记该链接为失效（Zep 模式）。"""
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            if invalidate:
                conn.execute(
                    """
                    UPDATE wiki_links SET invalid_at = ?
                    WHERE source_name = ? AND target_name = ? AND relationship = ?
                      AND invalid_at IS NULL
                    """,
                    (now, source_name, target_name, relationship),
                )
            else:
                link_id = str(_uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO wiki_links
                        (id, source_name, target_name, relationship, context, strength, source_doc, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_name, target_name, relationship) DO UPDATE SET
                        context    = excluded.context,
                        strength   = excluded.strength,
                        source_doc = excluded.source_doc,
                        invalid_at = NULL
                    """,
                    (link_id, source_name, target_name, relationship, context, strength, source_doc, now),
                )
            conn.commit()
        finally:
            conn.close()


def db_wiki_links_for(
    entity_name: str,
    include_invalid: bool = False,
) -> list[dict[str, Any]]:
    """返回某实体的所有出向链接（source = entity_name）。"""
    conn = _connect()
    try:
        if include_invalid:
            cur = conn.execute(
                "SELECT * FROM wiki_links WHERE source_name = ? ORDER BY created_at DESC",
                (entity_name,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM wiki_links WHERE source_name = ? AND invalid_at IS NULL ORDER BY created_at DESC",
                (entity_name,),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# Wiki Knowledge Graph — Episodes（原始文档记录）
# ─────────────────────────────────────────────────────────────────

def db_wiki_episode_insert(
    *,
    source_type: str,
    source_id: str,
    raw_text: str,
    entity_names: list[str],
) -> str:
    """记录一次摄入事件，返回新建的 episode id。"""
    episode_id = str(_uuid.uuid4())
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO wiki_episodes (id, source_type, source_id, raw_text, entity_names, extracted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (episode_id, source_type, source_id, raw_text, json.dumps(entity_names, ensure_ascii=False), now),
            )
            conn.commit()
        finally:
            conn.close()
    return episode_id


def db_wiki_episodes_for_source(source_id: str) -> list[dict[str, Any]]:
    """按 source_id 查询 episodes，entity_names 自动反序列化。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM wiki_episodes WHERE source_id = ? ORDER BY extracted_at DESC",
            (source_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        d = dict(row)
        raw = d.get("entity_names")
        if isinstance(raw, str):
            try:
                d["entity_names"] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                d["entity_names"] = []
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# 资产状态管理
# ---------------------------------------------------------------------------

_VALID_ASSET_STATUSES = frozenset({"draft", "approved", "sent", "archived"})


def db_asset_status_update(relative_paths: list[str], status: str) -> int:
    """批量更新文件状态，返回实际更新行数。"""
    if status not in _VALID_ASSET_STATUSES:
        raise ValueError(f"无效状态: {status!r}，允许值: {_VALID_ASSET_STATUSES}")
    if not relative_paths:
        return 0
    with _write_lock:
        conn = _connect()
        try:
            placeholders = ",".join("?" * len(relative_paths))
            cur = conn.execute(
                f"UPDATE assets SET asset_status=? WHERE relative_path IN ({placeholders})",
                [status, *relative_paths],
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 机构档案查询
# ---------------------------------------------------------------------------


def db_institutions_list() -> list[dict[str, Any]]:
    """返回所有有已确认 bundle 的机构名称列表，按最近活动倒序。"""
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT institution,
                   COUNT(*) AS bundle_count,
                   MAX(created_at) AS last_activity
            FROM match_sessions
            WHERE status = 'confirmed' AND institution != ''
            GROUP BY institution
            ORDER BY last_activity DESC
            """,
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def db_institution_archive_get(institution: str) -> dict[str, Any]:
    """返回指定机构的完整档案：已发文件列表 + 打包历史。"""
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT id, created_at, req_text, confirmed_files
            FROM match_sessions
            WHERE status = 'confirmed' AND institution = ?
            ORDER BY created_at DESC
            """,
            (institution,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    import json as _json  # noqa: PLC0415

    bundles = []
    all_sent_paths: set[str] = set()
    for row in rows:
        files = _json.loads(row["confirmed_files"] or "[]")
        bundles.append({
            "session_id": row["id"],
            "created_at": row["created_at"],
            "req_text": row["req_text"],
            "files": files,
        })
        for f in files:
            path = f.get("relative_path") or f.get("filename", "")
            if path:
                all_sent_paths.add(path)

    return {
        "institution": institution,
        "bundle_count": len(bundles),
        "total_sent_files": len(all_sent_paths),
        "bundles": bundles,
    }


# ---------------------------------------------------------------------------
# 匹配结果记忆（match_outcomes）— 智能体学习飞轮的数据基础
# ---------------------------------------------------------------------------


def db_match_outcome_batch_save(
    session_id: str,
    institution: str,
    selected_paths: list[str],
    candidate_paths: list[str],
    selected_names: list[str] | None = None,
    candidate_names: list[str] | None = None,
) -> None:
    """批量写入一次匹配会话的结果记忆。

    每次人工 confirm 后调用，记录：
      - 哪些候选文件被选中（was_selected=1）
      - 哪些候选文件被放弃（was_selected=0）

    这份数据是机构偏好画像（db_institution_match_profile）的原始材料，
    积累后可驱动 BM25MatcherSkill 的历史偏好加权，让匹配越来越准。

    Args:
        session_id: 关联的 match_sessions.id
        institution: 机构名称
        selected_paths: 被人工选中的文件 relative_path 列表
        candidate_paths: 所有候选文件的 relative_path 列表（包含未被选中的）
        selected_names: 被选中文件的 filename 列表（可选，仅供展示）
        candidate_names: 所有候选文件的 filename 列表（可选）
    """
    if not selected_paths and not candidate_paths:
        return
    now = time.time()
    selected_set = set(selected_paths)
    # 合并所有涉及文件（避免重复）
    all_paths = list(dict.fromkeys(list(candidate_paths) + list(selected_paths)))

    # 构建 path → name 映射
    name_map: dict[str, str] = {}
    if candidate_names:
        for p, n in zip(candidate_paths, candidate_names):
            name_map[p] = n
    if selected_names:
        for p, n in zip(selected_paths, selected_names):
            name_map[p] = n

    with _write_lock:
        conn = _connect()
        try:
            for path in all_paths:
                if not path:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO match_outcomes
                       (id, session_id, institution, asset_path, asset_name, was_selected, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"{session_id}::{path}",
                        session_id,
                        institution or "",
                        path,
                        name_map.get(path, ""),
                        1 if path in selected_set else 0,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()


def db_institution_match_profile(institution: str) -> dict[str, Any]:
    """从历史 match_outcomes 计算机构偏好画像。

    返回结构（供 BM25MatcherSkill 的 institution_profile 参数使用）::

        {
            "institution": "红杉资本",
            "total_sessions": 5,           # 历史匹配次数
            "total_selected": 23,          # 历史累计选中文件数
            "avg_selected_per_session": 4.6,
            "preferred_paths": [...],      # 被选中 ≥1 次的 relative_path，按频率降序
            "preferred_tags": [...],       # 从 assets 表 join 出的标签（需调用方提供资产列表）
            "last_contact": 1714000000.0,  # 最近一次匹配的时间戳
        }

    注意：preferred_tags 需要调用方在资产列表中二次 join，此处只返回 preferred_paths。
    上层（post_match_route）负责将 preferred_paths 和资产库 tags 做联合，
    或直接将整个资产库传给 _apply_institution_boost 做路径匹配即可。
    """
    if not institution:
        return {"institution": "", "total_sessions": 0, "preferred_paths": [], "preferred_tags": []}

    conn = _connect()
    try:
        # 被选中的文件（按选中次数降序）
        cur = conn.execute(
            """
            SELECT asset_path, asset_name, COUNT(*) AS select_count
            FROM match_outcomes
            WHERE institution = ? AND was_selected = 1
            GROUP BY asset_path
            ORDER BY select_count DESC
            LIMIT 50
            """,
            (institution,),
        )
        selected_rows = cur.fetchall()

        # 总体统计
        cur2 = conn.execute(
            """
            SELECT
                COUNT(DISTINCT session_id) AS total_sessions,
                SUM(was_selected)          AS total_selected,
                MAX(created_at)            AS last_contact
            FROM match_outcomes
            WHERE institution = ?
            """,
            (institution,),
        )
        stats = dict(cur2.fetchone() or {})

        preferred_paths = [row["asset_path"] for row in selected_rows]

        # 从 assets 表 join 出偏好文件的 tags（按频率聚合，取 Top-20）
        preferred_tags: list[str] = []
        if preferred_paths:
            placeholders = ",".join("?" * len(preferred_paths))
            cur3 = conn.execute(
                f"SELECT tags FROM assets WHERE relative_path IN ({placeholders})",
                preferred_paths,
            )
            tags_counter: dict[str, int] = {}
            for row in cur3.fetchall():
                try:
                    tags_list = json.loads(row["tags"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    tags_list = []
                for tag in tags_list:
                    tag_str = str(tag).strip()
                    if tag_str:
                        tags_counter[tag_str] = tags_counter.get(tag_str, 0) + 1
            preferred_tags = [t for t, _ in sorted(tags_counter.items(), key=lambda x: -x[1])[:20]]
    finally:
        conn.close()

    total_sessions = int(stats.get("total_sessions") or 0)
    total_selected = int(stats.get("total_selected") or 0)

    return {
        "institution": institution,
        "total_sessions": total_sessions,
        "total_selected": total_selected,
        "avg_selected_per_session": round(total_selected / total_sessions, 1) if total_sessions > 0 else 0.0,
        "preferred_paths": preferred_paths,
        "preferred_tags": preferred_tags,
        "last_contact": stats.get("last_contact"),
    }


def db_institution_briefing(institution: str) -> dict[str, Any]:
    """机构智慧简报：历史画像摘要 + 缺口检测。

    缺口 = 历史已确认 session 中 color 为 gray/red 的需求条目。
    这些需求当时没有可用文件满足，代表素材库已知短板。

    注意：session 计数从 match_sessions 表读取（而非 match_outcomes），
    因为 match_sessions 记录了每次匹配行为，match_outcomes 只记录飞轮确认后的文件。
    """
    if not institution:
        return {
            "institution": "",
            "has_history": False,
            "total_sessions": 0,
            "last_contact": None,
            "preferred_paths": [],
            "preferred_tags": [],
            "gap_hints": [],
        }

    conn = _connect()
    try:
        # 从 match_sessions 查全部 confirmed session
        cur = conn.execute(
            """
            SELECT results, created_at
            FROM match_sessions
            WHERE institution = ? AND status = 'confirmed'
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (institution,),
        )
        confirmed_sessions = cur.fetchall()

        # 总 session 数（包含非 confirmed）
        cur2 = conn.execute(
            "SELECT COUNT(*) AS n, MAX(created_at) AS last_contact FROM match_sessions"
            " WHERE institution = ?",
            (institution,),
        )
        stats = dict(cur2.fetchone() or {})
    finally:
        conn.close()

    total_sessions = int(stats.get("n") or 0)
    if not total_sessions:
        return {
            "institution": institution,
            "has_history": False,
            "total_sessions": 0,
            "last_contact": None,
            "preferred_paths": [],
            "preferred_tags": [],
            "gap_hints": [],
        }

    # 缺口检测
    gap_hints: list[str] = []
    seen: set[str] = set()
    for sess in confirmed_sessions:
        try:
            results = json.loads(sess["results"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        for result in results:
            if result.get("color") in ("gray", "red"):
                desc = (result.get("requirement") or {}).get("description", "").strip()
                if desc and desc not in seen and len(gap_hints) < 5:
                    gap_hints.append(desc)
                    seen.add(desc)

    # 偏好路径/标签从 match_outcomes（飞轮数据）读取，可能为空（新机构正常）
    profile = db_institution_match_profile(institution)

    return {
        "institution": institution,
        "has_history": True,
        "total_sessions": total_sessions,
        "last_contact": stats.get("last_contact"),
        "preferred_paths": profile["preferred_paths"][:5],
        "preferred_tags": profile["preferred_tags"][:10],
        "gap_hints": gap_hints,
    }


def db_asset_wiki_summary(relative_path: str) -> dict[str, Any]:
    """资产 Wiki 摘要：从 match_outcomes 聚合选用历史。

    返回:
        total_selected: 被选中的总次数
        total_shown:    出现在候选列表的总次数
        selection_rate: 选中率 (0.0~1.0)
        institutions:   [{institution, times}] 按频率降序
        last_selected:  最近一次被选中的时间戳
    """
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT institution, COUNT(*) AS times
            FROM match_outcomes
            WHERE asset_path = ? AND was_selected = 1
            GROUP BY institution
            ORDER BY times DESC
            LIMIT 5
            """,
            (relative_path,),
        )
        institutions = [{"institution": r["institution"], "times": r["times"]}
                        for r in cur.fetchall()]

        cur2 = conn.execute(
            "SELECT MAX(created_at) AS last_selected FROM match_outcomes"
            " WHERE asset_path = ? AND was_selected = 1",
            (relative_path,),
        )
        row2 = cur2.fetchone()
        last_selected = dict(row2).get("last_selected") if row2 else None

        cur3 = conn.execute(
            "SELECT COUNT(*) AS n FROM match_outcomes WHERE asset_path = ?",
            (relative_path,),
        )
        row3 = cur3.fetchone()
        total_shown = int(dict(row3).get("n") or 0) if row3 else 0
    finally:
        conn.close()

    total_selected = sum(i["times"] for i in institutions)
    return {
        "relative_path": relative_path,
        "total_selected": total_selected,
        "total_shown": total_shown,
        "selection_rate": round(total_selected / total_shown, 2) if total_shown > 0 else 0.0,
        "institutions": institutions,
        "last_selected": last_selected,
    }
