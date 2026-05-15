"""数据库基础设施层：连接管理、DDL、版本化迁移、序列化工具。

所有领域 DB 模块（pitch_job_db / asset_db / wiki_db / memory_db）均从此模块
获取连接和工具函数。同一进程内共享同一个 SQLite 文件 + 同一把写锁。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from cangjie_fos.core import paths as fos_paths

# ── 写锁（全局唯一，所有模块共享） ───────────────────────────────────────────
_write_lock = threading.Lock()

# ── JSON 列名集合（序列化/反序列化时用） ─────────────────────────────────────
_JSON_COLS: frozenset[str] = frozenset({
    "original_report",
    "edited_report",
    "words_json",
    "warnings",
    "confirmed_speakers_json",
})

# ── 完整 DDL（含所有历史新增列，新安装一步到位） ──────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS pitch_jobs (
    job_id                  TEXT PRIMARY KEY,
    tenant_id               TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending',
    created_at              REAL NOT NULL,
    original_report         TEXT,
    edited_report           TEXT,
    words_json              TEXT,
    audio_path              TEXT,
    committed_at            REAL,
    exp_delta               INTEGER DEFAULT 0,
    exp_reason              TEXT DEFAULT '',
    error_summary           TEXT,
    error_detail            TEXT,
    error_code              TEXT,
    html_report_path        TEXT,
    interviewee             TEXT,
    warnings                TEXT,
    substatus               TEXT,
    participants_confirmed  INTEGER NOT NULL DEFAULT 0,
    category                TEXT NOT NULL DEFAULT '',
    institution_id          TEXT NOT NULL DEFAULT '',
    is_roadshow             INTEGER NOT NULL DEFAULT 0,
    confirmed_speakers_json TEXT,
    referrer                TEXT NOT NULL DEFAULT ''
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
    indexed_at      REAL NOT NULL,
    asset_status    TEXT NOT NULL DEFAULT 'approved'
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

CREATE TABLE IF NOT EXISTS follow_up_items (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    job_id          TEXT NOT NULL,
    institution_id  TEXT NOT NULL DEFAULT '',
    actor           TEXT NOT NULL DEFAULT '我方',
    action          TEXT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'normal',
    source          TEXT NOT NULL DEFAULT 'commitment',
    done            INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    done_at         REAL
);
CREATE INDEX IF NOT EXISTS idx_follow_up_tenant ON follow_up_items(tenant_id, done, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_follow_up_job ON follow_up_items(job_id);

CREATE TABLE IF NOT EXISTS dd_asset_index (
    id          TEXT PRIMARY KEY,
    folder_root TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    filename    TEXT NOT NULL,
    file_type   TEXT NOT NULL,
    summary     TEXT,
    readable    INTEGER NOT NULL DEFAULT 1,
    indexed_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS dd_match_sessions (
    session_id     TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    checklist_name TEXT,
    folder_root    TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     REAL NOT NULL,
    completed_at   REAL
);

CREATE TABLE IF NOT EXISTS dd_match_items (
    id                TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL,
    item_no           TEXT NOT NULL,
    category          TEXT,
    requirement       TEXT NOT NULL,
    matched_file_path TEXT,
    matched_filename  TEXT,
    confidence        REAL,
    match_reason      TEXT,
    user_confirmed    INTEGER NOT NULL DEFAULT 0,
    user_skipped      INTEGER NOT NULL DEFAULT 0
);
"""

# ── 版本化迁移列表（既有 DB 升级用，新安装 DDL 已包含所有列） ─────────────────
# 格式：(版本号, SQL语句)
# 注意：如果列已存在（新安装或重复运行），ALTER TABLE 报错会被吞掉并标记为已应用。
_MIGRATIONS: list[tuple[int, str]] = [
    (1,  "ALTER TABLE pitch_jobs ADD COLUMN html_report_path TEXT"),
    (2,  "ALTER TABLE pitch_jobs ADD COLUMN interviewee TEXT"),
    (3,  "ALTER TABLE pitch_jobs ADD COLUMN warnings TEXT"),
    (4,  "ALTER TABLE pitch_jobs ADD COLUMN substatus TEXT"),
    (5,  "ALTER TABLE assets ADD COLUMN asset_status TEXT NOT NULL DEFAULT 'approved'"),
    (6,  "ALTER TABLE pitch_jobs ADD COLUMN participants_confirmed INTEGER NOT NULL DEFAULT 0"),
    (7,  "ALTER TABLE pitch_jobs ADD COLUMN category TEXT NOT NULL DEFAULT ''"),
    (8,  "ALTER TABLE pitch_jobs ADD COLUMN institution_id TEXT NOT NULL DEFAULT ''"),
    (9,  "ALTER TABLE pitch_jobs ADD COLUMN is_roadshow INTEGER NOT NULL DEFAULT 0"),
    (10, "ALTER TABLE pitch_jobs ADD COLUMN confirmed_speakers_json TEXT"),
    (11, "ALTER TABLE pitch_jobs ADD COLUMN referrer TEXT NOT NULL DEFAULT ''"),
]


def _db_path() -> str:
    p = fos_paths.get_backend_root() / "data" / "pitch_jobs.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """版本化迁移：建表追踪已应用版本，每次只运行未应用的 migration。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        )
    """)
    conn.commit()

    applied: set[int] = {
        row[0] for row in conn.execute("SELECT version FROM _schema_migrations")
    }

    for version, sql in _MIGRATIONS:
        if version in applied:
            continue
        try:
            conn.execute(sql)
        except Exception as exc:
            # 列已存在（已是 DDL 的一部分）：吞掉错误，标记为已应用
            msg = str(exc).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                raise  # 非预期错误，向上抛
        # 无论 SQL 成功还是"已存在"，都记录为已应用
        conn.execute(
            "INSERT OR IGNORE INTO _schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, time.time()),
        )
        conn.commit()


def _init_db(conn: sqlite3.Connection) -> None:
    """初始化 schema 并运行待应用迁移。"""
    conn.executescript(_DDL)
    conn.commit()
    _run_migrations(conn)


def _connect() -> sqlite3.Connection:
    """打开（或创建）DB，确保 schema 存在。WAL 模式支持并发读写。

    DB 路径解析顺序（向后兼容测试隔离模式）：
    1. 如果 cangjie_fos.services.pitch_job_db 已加载，使用其 _db_path()；
       测试通过 monkeypatch.setattr(pitch_job_db, "_db_path", ...) 隔离 DB。
    2. 否则回退到本模块的 _db_path()（db_base 独立使用场景）。
    """
    import sys as _sys
    _pjdb = _sys.modules.get("cangjie_fos.services.pitch_job_db")
    if _pjdb is not None and hasattr(_pjdb, "_db_path"):
        db_path_str = _pjdb._db_path()
    else:
        db_path_str = _db_path()
    conn = sqlite3.connect(db_path_str, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32000")
    _init_db(conn)
    return conn


# 公开别名，供需要直接使用连接的模块调用
get_connection = _connect


# ── 序列化工具 ────────────────────────────────────────────────────────────────

def _serialize(col: str, value: Any) -> Any:
    """将 JSON 列的 dict/list 值序列化为字符串；其他值原样返回。"""
    if col in _JSON_COLS and isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _row_to_dict(row: sqlite3.Row, json_cols: frozenset[str] | None = None) -> dict[str, Any]:
    """将 sqlite3.Row 转为 dict，自动反序列化 JSON 列。"""
    cols = json_cols if json_cols is not None else _JSON_COLS
    d: dict[str, Any] = dict(row)
    for col in cols:
        raw = d.get(col)
        if isinstance(raw, str):
            try:
                d[col] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
    return d
