"""SQLite 持久化层门面（Facade）— Job 域 + 向后兼容再导出。

架构说明
────────
本模块是 pitch_job_db 的瘦门面（slim facade）。具体职责：

1. **Job 域**：pitch_jobs / review_diffs / investor_prefs /
   job_participants / follow_up_items / institution_pitch_stats。
   这些函数直接定义在此文件。

2. **状态机**：VALID_TRANSITIONS + InvalidTransitionError +
   db_job_transition()（带校验的状态跃迁，与无校验的 db_job_update 并存）。

3. **向后兼容再导出**：将 asset_db / wiki_db / memory_db 中的所有符号
   再导出到本模块的命名空间，确保现有 30+ 个导入站点无需修改。
   例：`from cangjie_fos.services.pitch_job_db import db_wiki_entity_upsert`
   仍然有效。

4. **基础设施再导出**：`_connect`（被 tests、routes、services 直接导入）
   从 db_base 透传。

修改说明（v0.5.3）
──────────────────
- 替换内联 DDL + try/except 迁移 → db_base 统一管理（含 WAL pragma）
- 迁出 wiki_db.py（7 个函数）
- 迁出 memory_db.py（6 个函数）
- 迁出 asset_db.py（20+ 个函数，上一轮已完成）
- 新增状态机跃迁约束
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid as _uuid
from typing import Any

from cangjie_fos.core import paths as fos_paths

# ── DB 路径（权威实现：测试通过 monkeypatch.setattr(pitch_job_db, "_db_path", ...) 隔离）
def _db_path() -> str:
    p = fos_paths.get_backend_root() / "data" / "pitch_jobs.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


# ── 基础设施（统一由 db_base 提供） ──────────────────────────────────────────
# db_base._connect 在运行时优先使用 pitch_job_db._db_path（见 db_base._connect 注释）
from cangjie_fos.services.db_base import (
    _connect,          # 向后兼容：大量外部代码 import _connect from pitch_job_db
    _init_db,          # 向后兼容：test_p1a_schema_migration 直接调用
    _write_lock,       # 进程内唯一写锁，asset_db / wiki_db / memory_db 共享
    _row_to_dict,      # sqlite3.Row → dict，自动反序列化 JSON 列
    _serialize,        # dict/list → JSON string（写入前）
)

# ── 向后兼容再导出：asset 域 ──────────────────────────────────────────────────
from cangjie_fos.services.asset_db import (
    db_asset_upsert,
    db_assets_list,
    db_assets_clear,
    db_asset_status_update,
    db_assets_search_by_keywords,
    db_scan_config_get,
    db_scan_config_set,
    db_health_snapshot_insert,
    db_health_snapshot_list,
    db_health_snapshot_latest,
    db_material_contribution_upsert,
    db_material_contributions_list,
    db_material_contribution_bulk_upsert,
    db_material_match_insert,
    db_material_matches_list,
    db_match_session_create,
    db_match_session_get,
    db_match_session_list,
    db_match_session_update,
    db_match_outcome_batch_save,
    db_institution_match_profile,
    db_institution_briefing,
    db_asset_wiki_summary,
    db_institutions_list,
    db_institution_archive_get,
)

# ── 向后兼容再导出：wiki 域 ───────────────────────────────────────────────────
from cangjie_fos.services.wiki_db import (
    db_wiki_entity_upsert,
    db_wiki_entity_get,
    db_wiki_entity_list,
    db_wiki_link_upsert,
    db_wiki_links_for,
    db_wiki_episode_insert,
    db_wiki_episodes_for_source,
)

# ── 向后兼容再导出：memory 域 ─────────────────────────────────────────────────
from cangjie_fos.services.memory_db import (
    db_exec_memory_insert,
    db_exec_memory_list,
    db_exec_memory_delete,
    db_nightly_suggestion_insert,
    db_nightly_suggestion_list_pending,
    db_nightly_suggestion_mark_consumed,
)

# ── __all__：让 import * 也能透传（IDE、linter 友好） ─────────────────────────
__all__ = [
    # infrastructure
    "_connect",
    # asset domain
    "db_asset_upsert", "db_assets_list", "db_assets_clear",
    "db_asset_status_update", "db_assets_search_by_keywords",
    "db_scan_config_get", "db_scan_config_set",
    "db_health_snapshot_insert", "db_health_snapshot_list", "db_health_snapshot_latest",
    "db_material_contribution_upsert", "db_material_contributions_list",
    "db_material_contribution_bulk_upsert",
    "db_material_match_insert", "db_material_matches_list",
    "db_match_session_create", "db_match_session_get",
    "db_match_session_list", "db_match_session_update",
    "db_match_outcome_batch_save",
    "db_institution_match_profile", "db_institution_briefing",
    "db_asset_wiki_summary",
    "db_institutions_list", "db_institution_archive_get",
    # wiki domain
    "db_wiki_entity_upsert", "db_wiki_entity_get", "db_wiki_entity_list",
    "db_wiki_link_upsert", "db_wiki_links_for",
    "db_wiki_episode_insert", "db_wiki_episodes_for_source",
    # memory domain
    "db_exec_memory_insert", "db_exec_memory_list", "db_exec_memory_delete",
    "db_nightly_suggestion_insert", "db_nightly_suggestion_list_pending",
    "db_nightly_suggestion_mark_consumed",
    # job domain (defined below)
    "db_job_create", "db_job_update", "db_job_get",
    "db_job_list_for_tenant", "db_job_list_recent_errors", "db_job_list_risk_keywords",
    "db_job_bind_institution", "db_job_transition",
    "db_diff_insert", "db_diff_list_pending", "db_diff_mark_extracted",
    "db_pref_insert", "db_pref_list_for_tenant",
    "db_speaker_summary",
    "db_participants_get", "db_participants_save",
    "db_follow_up_insert", "db_follow_up_list",
    "db_follow_up_mark_done", "db_follow_up_list_by_job",
    "db_institution_pitch_stats",
    # state machine
    "VALID_TRANSITIONS", "InvalidTransitionError",
]

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

# 所有可写列（不含主键 job_id 和创建时间 created_at）
_WRITABLE_COLS = {
    "status",
    "participants_confirmed",
    "category",
    "institution_id",
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
    "is_roadshow",
    "confirmed_speakers_json",
    "referrer",
}

# ─────────────────────────────────────────────────────────────────────────────
# 状态机
# ─────────────────────────────────────────────────────────────────────────────

#: 合法的状态跃迁表。key = 当前状态，value = 允许跃迁到的状态集合。
#: 只有通过 db_job_transition() 才会做校验；
#: db_job_update() 仍然是无校验的"万能"更新，供遗留代码和紧急补丁使用。
VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending":           frozenset({"transcribing", "failed"}),
    "transcribing":      frozenset({"awaiting_speakers", "evaluating", "failed"}),
    "awaiting_speakers": frozenset({"resuming_analysis", "failed"}),
    "resuming_analysis": frozenset({"evaluating", "failed"}),
    "evaluating":        frozenset({"completed", "failed"}),
    "completed":         frozenset({"evaluating"}),   # 允许重跑评估
    "failed":            frozenset({"evaluating"}),   # 允许重跑评估
}


class InvalidTransitionError(ValueError):
    """状态跃迁不合法时抛出，附带 from/to 信息。"""

    def __init__(self, from_status: str, to_status: str) -> None:
        allowed = VALID_TRANSITIONS.get(from_status, frozenset())
        super().__init__(
            f"非法状态跃迁：{from_status!r} → {to_status!r}。"
            f"从 {from_status!r} 允许的目标：{sorted(allowed)}"
        )
        self.from_status = from_status
        self.to_status = to_status


def db_job_transition(job_id: str, to_status: str, **extra: Any) -> None:
    """带跃迁校验的状态更新。

    先读当前状态，如果跃迁不合法则抛出 InvalidTransitionError；
    合法则以原子写入方式更新 status 及其他 extra 字段。

    extra 支持与 db_job_update() 相同的关键字（substatus、error_summary 等）。

    注意：此函数读-改-写非严格原子（read + write 分两次），适合后台单线程 pipeline
    调用。若需严格原子（多线程竞争场景），请在持有 _write_lock 外层包装使用。
    """
    job = db_job_get(job_id)
    if job is None:
        raise KeyError(f"job_id {job_id!r} 不存在")
    from_status = str(job.get("status", ""))
    allowed = VALID_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise InvalidTransitionError(from_status, to_status)
    db_job_update(job_id, status=to_status, **extra)


# ─────────────────────────────────────────────────────────────────────────────
# Job CRUD
# ─────────────────────────────────────────────────────────────────────────────

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
    """Update any writable fields on the job row（无跃迁约束，向后兼容）。

    如需跃迁校验，请改用 db_job_transition()。
    Accepted kwargs: status, original_report, edited_report, words_json,
    audio_path, html_report_path, committed_at, exp_delta, exp_reason,
    error_summary, error_detail, error_code, substatus, …

    dict/list 值会被自动 JSON 序列化。
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

    JSON columns (original_report, edited_report, words_json, warnings,
    confirmed_speakers_json) are returned as already-deserialized Python objects.
    A 'report' key is added as alias: edited_report if set, else original_report.
    """
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM pitch_jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    d = _row_to_dict(row)
    # backward-compat alias
    d["report"] = d["edited_report"] if d.get("edited_report") is not None else d.get("original_report")
    return d


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

    result = []
    for row in rows:
        d = _row_to_dict(row)
        d["report"] = d["edited_report"] if d.get("edited_report") is not None else d.get("original_report")
        result.append((row["job_id"], d))
    return result


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


def db_job_bind_institution(job_id: str, institution_name: str) -> None:
    """将机构名称写入 pitch_jobs.institution_id，同步回填该 job 的 follow_up_items。"""
    if not institution_name:
        return
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE pitch_jobs SET institution_id = ? WHERE job_id = ?",
                (institution_name, job_id),
            )
            conn.execute(
                "UPDATE follow_up_items SET institution_id = ? WHERE job_id = ? AND institution_id = ''",
                (institution_name, job_id),
            )
            conn.commit()
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# review_diffs — 进化飞轮：捕获 original vs edited diff
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# investor_prefs — 结构化投资人偏好
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# job_participants — 参与人身份确认
# ─────────────────────────────────────────────────────────────────────────────

_PARTICIPANT_VALID_ROLES = {
    "企业方创始人", "企业方高管", "企业方投融资",
    "GP执行", "LP投资方", "政府招商", "其他",
}


def db_speaker_summary(job_id: str) -> list[dict[str, Any]]:
    """从 words_json 提取每位说话人的前3段话，供用户对照身份。

    words_json 是逐词（word-level）数据，每条 entry 含：
      text, start_time（秒）, end_time（秒）, speaker_id

    聚合策略：
    - 以【说话人切换】为段落边界——这是唯一可靠的边界标志。
      中文 ASR 逐字输出时，字间自然停顿常超过 1-2 秒，时间阈值容易误切。
    - 同一说话人连续词全部拼合为一段（speaker turn）。
    - 每段超过 MAX_CHARS 字时截断并用「…」结尾。
    - 每位说话人最多展示 MAX_LINES 段（取其最早出现的段落）。
    - word_count 统计该说话人的总字符数。
    """
    MAX_LINES = 3
    MAX_CHARS = 80

    job = db_job_get(job_id)
    if not job:
        return []
    words_json = job.get("words_json") or []
    if isinstance(words_json, str):
        try:
            words_json = json.loads(words_json)
        except Exception:
            return []
    if not words_json:
        return []

    # ── 第一步：按说话人切换把逐词流分成「speaker turns」 ─────────────
    # turns: [{"speaker_id": str, "text": str}, ...]
    turns: list[dict[str, str]] = []
    cur_sid: str = ""
    cur_buf: list[str] = []

    for w in words_json:
        sid = str(w.get("speaker_id", "0"))
        word = str(w.get("text", "")).strip()
        if not word:
            continue
        if sid != cur_sid:
            if cur_buf and cur_sid:
                turns.append({"speaker_id": cur_sid, "text": "".join(cur_buf)})
            cur_sid = sid
            cur_buf = [word]
        else:
            cur_buf.append(word)

    if cur_buf and cur_sid:
        turns.append({"speaker_id": cur_sid, "text": "".join(cur_buf)})

    # ── 第二步：按说话人聚合，取前 MAX_LINES 个 turn ────────────────
    speaker_lines: dict[str, list[str]] = {}
    speaker_char_counts: dict[str, int] = {}

    for turn in turns:
        sid = turn["speaker_id"]
        text = turn["text"]
        speaker_char_counts[sid] = speaker_char_counts.get(sid, 0) + len(text)
        if sid not in speaker_lines:
            speaker_lines[sid] = []
        if len(speaker_lines[sid]) < MAX_LINES:
            display = text[:MAX_CHARS] + ("…" if len(text) > MAX_CHARS else "")
            speaker_lines[sid].append(display)

    return [
        {
            "speaker_id": sid,
            "sample_lines": lines,
            "word_count": speaker_char_counts.get(sid, 0),
        }
        for sid, lines in sorted(speaker_lines.items())
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


# ─────────────────────────────────────────────────────────────────────────────
# follow_up_items — 路演后续行动项
# ─────────────────────────────────────────────────────────────────────────────

def db_follow_up_insert(
    *,
    tenant_id: str,
    job_id: str,
    institution_id: str = "",
    actor: str = "我方",
    action: str,
    priority: str = "normal",
    source: str = "commitment",
) -> str:
    """插入一条待跟进行动项，返回新生成的 id。"""
    item_id = str(_uuid.uuid4())
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO follow_up_items
                    (id, tenant_id, job_id, institution_id, actor, action, priority, source, done, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (item_id, tenant_id, job_id, institution_id, actor, action, priority, source, time.time()),
            )
            conn.commit()
        finally:
            conn.close()
    return item_id


def db_follow_up_list(
    tenant_id: str,
    *,
    limit: int = 50,
    include_done: bool = False,
) -> list[dict]:
    """列出租户的待跟进行动项（默认只返回未完成的）。"""
    conn = _connect()
    try:
        where = "tenant_id = ?"
        params: list = [tenant_id]
        if not include_done:
            where += " AND done = 0"
        cur = conn.execute(
            f"SELECT * FROM follow_up_items WHERE {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def db_follow_up_mark_done(item_id: str) -> bool:
    """将指定行动项标记为已完成，返回是否找到该记录。"""
    with _write_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE follow_up_items SET done = 1, done_at = ? WHERE id = ?",
                (time.time(), item_id),
            )
            conn.commit()
            return (cur.rowcount or 0) > 0
        finally:
            conn.close()


def db_follow_up_list_by_job(job_id: str) -> list[dict]:
    """返回指定 job 的所有行动项（含已完成）。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM follow_up_items WHERE job_id = ? ORDER BY created_at ASC",
            (job_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# institution_pitch_stats — 机构路演统计
# ─────────────────────────────────────────────────────────────────────────────

def db_institution_pitch_stats(tenant_id: str) -> list[dict]:
    """返回各机构的路演统计（次数 + 最近路演时间）。

    数据来源双路合并：
      1. pitch_jobs.institution_id（参与人确认后由 db_job_bind_institution 写入）
      2. job_participants.institution（participant 级别明细，未必已绑定到主记录）
    两路取并集，同一机构取 max(count) 和 max(last_pitch_at)。
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            WITH from_jobs AS (
                SELECT
                    institution_id AS institution,
                    COUNT(DISTINCT job_id) AS pitch_count,
                    MAX(created_at)        AS last_pitch_at
                FROM pitch_jobs
                WHERE tenant_id = ?
                  AND institution_id != ''
                  AND status = 'completed'
                GROUP BY institution_id
            ),
            from_participants AS (
                SELECT
                    jp.institution,
                    COUNT(DISTINCT jp.job_id) AS pitch_count,
                    MAX(pj.created_at)         AS last_pitch_at
                FROM job_participants jp
                JOIN pitch_jobs pj ON pj.job_id = jp.job_id
                WHERE jp.tenant_id = ?
                  AND jp.institution != ''
                  AND pj.status = 'completed'
                GROUP BY jp.institution
            ),
            merged AS (
                SELECT institution, pitch_count, last_pitch_at FROM from_jobs
                UNION ALL
                SELECT institution, pitch_count, last_pitch_at FROM from_participants
            )
            SELECT
                institution,
                SUM(pitch_count)   AS pitch_count,
                MAX(last_pitch_at) AS last_pitch_at
            FROM merged
            GROUP BY institution
            ORDER BY pitch_count DESC, last_pitch_at DESC
            """,
            (tenant_id, tenant_id),
        ).fetchall()
        return [
            {
                "institution": r["institution"],
                "pitch_count": int(r["pitch_count"]),
                "last_pitch_at": r["last_pitch_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()
