"""素材/匹配/健康度领域 DB 操作。

涵盖：assets / asset_scan_config / asset_health_history /
      material_contributions / match_sessions / match_outcomes /
      follow_up_items（行动项）

与 pitch_job_db.py 共享同一个 SQLite 文件，通过 db_base._connect() 获取连接。
"""
from __future__ import annotations

import json
import time
import uuid as _uuid
from typing import Any

from cangjie_fos.services.db_base import _connect, _write_lock

# ── match_sessions 的 JSON 列 ─────────────────────────────────────────────────
_MATCH_JSON_COLS: frozenset[str] = frozenset({"requirements", "results", "confirmed_files"})

# ── 资产状态合法值 ─────────────────────────────────────────────────────────────
_VALID_ASSET_STATUSES: frozenset[str] = frozenset({"draft", "approved", "sent", "archived"})


def _match_row_to_dict(row: Any) -> dict[str, Any]:
    d: dict[str, Any] = dict(row)
    for col in _MATCH_JSON_COLS:
        raw = d.get(col)
        if isinstance(raw, str):
            try:
                d[col] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                d[col] = []
    return d


# ---------------------------------------------------------------------------
# assets — 素材扫描结果持久化
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
    """Upsert 单条资产记录（relative_path 作唯一键）。"""
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
        cur = conn.execute("SELECT * FROM assets ORDER BY indexed_at DESC LIMIT ?", (lim,))
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


def db_assets_search_by_keywords(tenant_id: str, keywords: list[str]) -> list[dict[str, Any]]:
    """查询素材库中与关键词匹配的素材（基于 material_contributions 表 tags/asset_filename）。"""
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
                break
    return matched


# ---------------------------------------------------------------------------
# asset_scan_config — 扫描配置
# ---------------------------------------------------------------------------

def db_scan_config_get() -> dict[str, Any] | None:
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
    snaps = db_health_snapshot_list(limit=1)
    return snaps[0] if snaps else None


# ---------------------------------------------------------------------------
# material_contributions — 素材贡献度
# ---------------------------------------------------------------------------

def db_material_contribution_upsert(
    asset_filename: str,
    relative_path: str,
    *,
    tags: list[str] | None = None,
    contribution_score_delta: float = 0.0,
    usage_count_delta: int = 0,
) -> None:
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


def db_material_contribution_bulk_upsert(
    tenant_id: str, asset_ids: list[str], action: str
) -> None:
    """批量 upsert 素材贡献度（路演用到哪些素材 → 增加 usage_count）。"""
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
# match_sessions — 尽调响应台会话
# ---------------------------------------------------------------------------

def db_match_session_create(
    session_id: str,
    institution: str,
    req_text: str,
    requirements: list[dict],
    results: list[dict],
) -> None:
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO match_sessions
                    (id, created_at, institution, req_text, requirements, results, status)
                VALUES (?, ?, ?, ?, ?, ?, 'draft')""",
                (
                    session_id, now, str(institution), str(req_text),
                    json.dumps(requirements, ensure_ascii=False),
                    json.dumps(results, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def db_match_session_get(session_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM match_sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    return _match_row_to_dict(row) if row else None


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


# ---------------------------------------------------------------------------
# match_outcomes — 智能体学习飞轮
# ---------------------------------------------------------------------------

def db_match_outcome_batch_save(
    session_id: str,
    institution: str,
    selected_paths: list[str],
    candidate_paths: list[str],
    selected_names: list[str] | None = None,
    candidate_names: list[str] | None = None,
) -> None:
    if not selected_paths and not candidate_paths:
        return
    now = time.time()
    selected_set = set(selected_paths)
    all_paths = list(dict.fromkeys(list(candidate_paths) + list(selected_paths)))

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
    """从历史 match_outcomes 计算机构偏好画像。"""
    if not institution:
        return {"institution": "", "total_sessions": 0, "preferred_paths": [], "preferred_tags": []}

    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT asset_path, asset_name, COUNT(*) AS select_count
               FROM match_outcomes WHERE institution = ? AND was_selected = 1
               GROUP BY asset_path ORDER BY select_count DESC LIMIT 50""",
            (institution,),
        )
        selected_rows = cur.fetchall()

        cur2 = conn.execute(
            """SELECT COUNT(DISTINCT session_id) AS total_sessions,
                      SUM(was_selected) AS total_selected, MAX(created_at) AS last_contact
               FROM match_outcomes WHERE institution = ?""",
            (institution,),
        )
        stats = dict(cur2.fetchone() or {})

        preferred_paths = [row["asset_path"] for row in selected_rows]
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
    """机构智慧简报：历史画像摘要 + 缺口检测。"""
    empty = {
        "institution": institution,
        "has_history": False,
        "total_sessions": 0,
        "last_contact": None,
        "preferred_paths": [],
        "preferred_tags": [],
        "gap_hints": [],
    }
    if not institution:
        return {**empty, "institution": ""}

    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT results, created_at FROM match_sessions
               WHERE institution = ? AND status = 'confirmed'
               ORDER BY created_at DESC LIMIT 20""",
            (institution,),
        )
        confirmed_sessions = cur.fetchall()

        cur2 = conn.execute(
            "SELECT COUNT(*) AS n, MAX(created_at) AS last_contact FROM match_sessions WHERE institution = ?",
            (institution,),
        )
        stats = dict(cur2.fetchone() or {})
    finally:
        conn.close()

    total_sessions = int(stats.get("n") or 0)
    if not total_sessions:
        return {**empty, "has_history": False, "total_sessions": 0}

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
    """资产 Wiki 摘要：从 match_outcomes 聚合选用历史。"""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT institution, COUNT(*) AS times FROM match_outcomes
               WHERE asset_path = ? AND was_selected = 1
               GROUP BY institution ORDER BY times DESC LIMIT 5""",
            (relative_path,),
        )
        institutions = [{"institution": r["institution"], "times": r["times"]} for r in cur.fetchall()]

        cur2 = conn.execute(
            "SELECT MAX(created_at) AS last_selected FROM match_outcomes WHERE asset_path = ? AND was_selected = 1",
            (relative_path,),
        )
        row2 = cur2.fetchone()
        last_selected = dict(row2).get("last_selected") if row2 else None

        cur3 = conn.execute("SELECT COUNT(*) AS n FROM match_outcomes WHERE asset_path = ?", (relative_path,))
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


# ---------------------------------------------------------------------------
# 机构档案查询
# ---------------------------------------------------------------------------

def db_institutions_list() -> list[dict[str, Any]]:
    """返回所有有已确认 bundle 的机构，按最近活动倒序。"""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT institution, COUNT(*) AS bundle_count, MAX(created_at) AS last_activity
               FROM match_sessions WHERE status = 'confirmed' AND institution != ''
               GROUP BY institution ORDER BY last_activity DESC""",
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def db_institution_archive_get(institution: str) -> dict[str, Any]:
    """返回指定机构的完整档案：已发文件列表 + 打包历史。"""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT id, created_at, req_text, confirmed_files FROM match_sessions
               WHERE status = 'confirmed' AND institution = ? ORDER BY created_at DESC""",
            (institution,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    bundles = []
    all_sent_paths: set[str] = set()
    for row in rows:
        files = json.loads(row["confirmed_files"] or "[]")
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
