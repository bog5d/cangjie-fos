"""GitHub 同步服务 — coach_data 仓库双向同步。

功能：
- push_pitch_job(job_id)      路演确认后，把分析报告 JSON push 到 analytics/{tenant_id}/
- push_match_session(sid)     匹配确认后，把匹配记录 push 到 match_sessions/
- pull_latest()               启动时拉取仓库最新文件，更新本地数据
- is_configured()             检查 token/repo 是否已配置

使用 GitHub REST API（不依赖 git 客户端，Windows 开箱即用）。
配置方式：backend/.env 中添加：
  COACH_DATA_GITHUB_TOKEN=ghp_xxxx
  COACH_DATA_GITHUB_REPO=bog5d/coach_data
  COACH_DATA_TENANT_ID=zt   # 这台机器归属的公司/团队标识
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ─── 同步状态追踪 ──────────────────────────────────────────────────────────────

_sync_state: dict[str, Any] = {
    "is_syncing": False,
    "last_synced_at": None,   # float timestamp
    "last_result": None,       # {"pitch_imported": N, "match_imported": M}
    "last_error": None,        # str | None
}


def _reset_sync_state() -> None:
    """测试用：重置同步状态。"""
    global _sync_state
    _sync_state = {
        "is_syncing": False,
        "last_synced_at": None,
        "last_result": None,
        "last_error": None,
    }


def get_sync_status() -> dict[str, Any]:
    """返回当前同步状态快照（供 API 端点使用）。"""
    return {
        "configured": is_configured(),
        "is_syncing": _sync_state["is_syncing"],
        "last_synced_at": _sync_state["last_synced_at"],
        "last_result": _sync_state["last_result"],
        "last_error": _sync_state["last_error"],
    }



def _cfg() -> dict[str, str]:
    return {
        "token": os.getenv("COACH_DATA_GITHUB_TOKEN", "").strip(),
        "repo":  os.getenv("COACH_DATA_GITHUB_REPO", "bog5d/coach_data").strip(),
        "tenant": os.getenv("COACH_DATA_TENANT_ID", "default").strip(),
    }


def is_configured() -> bool:
    """返回 True 说明 token 已配置，同步功能启用。"""
    return bool(_cfg()["token"])


# ─── GitHub API 基础操作 ───────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    cfg = _cfg()
    return {
        "Authorization": f"token {cfg['token']}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "CangJie-FOS",
    }


def _get_file_sha(path: str) -> str | None:
    """获取文件当前 SHA（更新文件时必须提供）。"""
    import urllib.request
    cfg = _cfg()
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{path}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("sha")
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None  # 文件不存在或网络错误


def _put_file(path: str, content_dict: dict[str, Any], message: str) -> bool:
    """PUT 一个 JSON 文件到 GitHub，自动处理创建/更新。返回是否成功。"""
    import urllib.request
    import urllib.error

    cfg = _cfg()
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{path}"
    content_bytes = json.dumps(content_dict, ensure_ascii=False, indent=2).encode("utf-8")
    content_b64 = base64.b64encode(content_bytes).decode("ascii")

    sha = _get_file_sha(path)
    payload: dict[str, Any] = {
        "message": message,
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=_headers(), method="PUT")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.getcode()
            return status in (200, 201)
    except urllib.error.HTTPError as e:
        logger.warning("GitHub PUT 失败 %s: %s %s", path, e.code, e.reason)
        return False
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.warning("GitHub PUT 异常 %s: %s", path, e)
        return False


def _list_folder(folder: str) -> list[dict]:
    """列举仓库某目录下所有文件，返回 [{name, path, download_url}]。"""
    import urllib.request
    import urllib.error

    cfg = _cfg()
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{folder}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            items = json.loads(resp.read())
            if isinstance(items, list):
                return [i for i in items if i.get("type") == "file"]
            return []
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        logger.warning("GitHub 列目录失败 %s: %s", folder, e)
        return []
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.warning("GitHub 列目录异常 %s: %s", folder, e)
        return []


def _list_folder_recursive(folder: str) -> list[dict]:
    """递归列举目录下所有 JSON 文件（含子目录）。"""
    result = []
    import urllib.request as _ur
    cfg = _cfg()
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{folder}"
    req = _ur.Request(url, headers=_headers())
    try:
        with _ur.urlopen(req, timeout=15) as resp:
            items = json.loads(resp.read())
    except Exception:  # noqa: BLE001
        return []
    for item in items:
        if item.get("type") == "file":
            result.append(item)
        elif item.get("type") == "dir":
            result.extend(_list_folder_recursive(item["path"]))
    return result


def _download_json(download_url: str) -> dict | None:
    """下载 JSON 文件内容。"""
    import urllib.request
    try:
        req = urllib.request.Request(download_url, headers={"User-Agent": "CangJie-FOS"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.warning("GitHub 下载失败 %s: %s", download_url, e)
        return None


# ─── 数据导出格式 ─────────────────────────────────────────────────────────────

def _job_to_export(job_row: dict) -> dict[str, Any]:
    """把 pitch_jobs 行转换为导出 JSON（兼容 coach_data analytics/ 格式）。"""
    report = {}
    # 优先用人工确认后的报告
    for key in ("edited_report", "original_report"):
        raw = job_row.get(key)
        if raw:
            report = json.loads(raw) if isinstance(raw, str) else raw
            break

    committed_at = job_row.get("committed_at") or job_row.get("created_at") or time.time()
    locked_iso = datetime.fromtimestamp(committed_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    created_iso = datetime.fromtimestamp(
        job_row.get("created_at") or committed_at, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 从报告提取评分数据（兼容 FSS 格式）
    total_score = report.get("total_score", 0)
    risk_breakdown = report.get("risk_breakdown", {})

    return {
        "session_id": job_row.get("job_id", ""),
        "generated_at": created_iso,
        "locked_at": locked_iso,
        "status": "locked",
        "version": "FOS_V5.2",
        "fos_source": "cangjie_fos",                          # 区分来源
        "company_id": job_row.get("tenant_id", ""),
        "interviewee": job_row.get("interviewee", ""),
        "institution_canonical": report.get("institution", ""),
        "total_score": total_score,
        "risk_breakdown": risk_breakdown,
        "participants": job_row.get("participants") or [],     # 参与者元数据（待实现）
        "recording_label": job_row.get("interviewee", ""),
        "fundraising_outcome": report.get("fundraising_outcome", ""),
    }


def _match_session_to_export(session_row: dict) -> dict[str, Any]:
    """把 match_sessions 行转换为导出 JSON。"""
    results = session_row.get("results") or "[]"
    if isinstance(results, str):
        results = json.loads(results)

    confirmed_files = session_row.get("confirmed_files") or "[]"
    if isinstance(confirmed_files, str):
        confirmed_files = json.loads(confirmed_files)

    created_at = session_row.get("created_at") or time.time()
    created_iso = datetime.fromtimestamp(created_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "session_id": session_row.get("id", ""),
        "fos_source": "cangjie_fos",
        "created_at": created_iso,
        "institution": session_row.get("institution", ""),
        "req_text": session_row.get("req_text", ""),
        "status": session_row.get("status", ""),
        "confirmed_files": confirmed_files,
        "match_count": len(results),
    }


# ─── 公开接口 ─────────────────────────────────────────────────────────────────

def push_pitch_job(job_id: str) -> bool:
    """
    把一条 pitch_jobs 记录 push 到 analytics/{tenant_id}/{job_id}.json。
    在 pitch_job_review_commit 之后作为 background_task 调用。
    """
    if not is_configured():
        return False

    from cangjie_fos.services.pitch_job_db import db_job_get  # 避免循环 import

    row = db_job_get(job_id)
    if not row:
        logger.warning("push_pitch_job: 找不到 job_id=%s", job_id)
        return False

    cfg = _cfg()
    tenant = row.get("tenant_id") or cfg["tenant"]
    export = _job_to_export(row)

    # 使用 interviewee 或 job_id 作为文件名
    label = (row.get("interviewee") or job_id)[:40].replace("/", "_").replace(" ", "_")
    filename = f"{label}_{job_id[:8]}.json"
    path = f"analytics/{tenant}/{filename}"

    ok = _put_file(path, export, f"sync pitch: {tenant} {label}")
    if ok:
        logger.info("✅ GitHub sync push: %s", path)
    return ok


def push_match_session(session_id: str) -> bool:
    """
    把一条 match_sessions 记录 push 到 match_sessions/{tenant_id}/{session_id}.json。
    在 post_match_confirm_route 之后作为 background_task 调用。
    """
    if not is_configured():
        return False

    from cangjie_fos.services.pitch_job_db import _connect  # type: ignore

    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM match_sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        logger.warning("push_match_session: 找不到 session_id=%s", session_id)
        return False

    row_dict = dict(row)
    cfg = _cfg()
    # TODO: 当 match_sessions 表新增 tenant_id 列后，改为：
    #   tenant = row_dict.get("tenant_id") or cfg["tenant"]
    # 目前表中无 tenant_id 列，暂时使用环境变量配置值
    tenant = cfg["tenant"]
    export = _match_session_to_export(row_dict)

    path = f"match_sessions/{tenant}/{session_id}.json"
    ok = _put_file(path, export, f"sync match: {tenant} {row_dict.get('institution','')}")
    if ok:
        logger.info("✅ GitHub sync push match: %s", path)
    return ok


def push_roadshow_report(job_id: str) -> bool:
    """把路演情报报告 push 到 analytics/{tenant_id}/roadshow_{date}_{job_id[:8]}.json。

    Phase 7.5: 路演分析完成后作为 background_task 调用。
    """
    if not is_configured():
        return False

    from cangjie_fos.services.pitch_job_db import db_job_get  # noqa: PLC0415

    row = db_job_get(job_id)
    if not row:
        logger.warning("push_roadshow_report: 找不到 job_id=%s", job_id)
        return False

    report = row.get("original_report") or {}
    confirmed_speakers = row.get("confirmed_speakers_json") or []

    import datetime as _dt  # noqa: PLC0415
    date_str = _dt.datetime.fromtimestamp(row.get("created_at", 0)).strftime("%Y%m%d")

    cfg = _cfg()
    tenant = row.get("tenant_id") or cfg["tenant"]
    label = (row.get("interviewee") or job_id)[:30].replace("/", "_").replace(" ", "_")

    export = {
        "session_id": job_id,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "type": "roadshow_intel",
        "version": "FOS_V7.5",
        "fos_source": "cangjie_fos",
        "company_id": tenant,
        "institution": row.get("institution_id", ""),
        "referrer": row.get("referrer", ""),
        "interviewee": row.get("interviewee", ""),
        "meeting_atmosphere": report.get("meeting_atmosphere", ""),
        "meeting_stage": report.get("meeting_stage", ""),
        "atmosphere_summary": report.get("atmosphere_summary", ""),
        "key_questions": report.get("key_questions", []),
        "interest_signals": report.get("interest_signals", []),
        "hidden_concerns": report.get("hidden_concerns", []),
        "next_actions": report.get("next_actions", []),
        "competitor_mentions": report.get("competitor_mentions", []),
        "timeline_signals": report.get("timeline_signals", ""),
        "dominant_speaker": report.get("dominant_speaker", ""),
        "confirmed_speakers": confirmed_speakers,
    }

    filename = f"roadshow_{date_str}_{job_id[:8]}.json"
    path = f"analytics/{tenant}/{filename}"

    ok = _put_file(path, export, f"roadshow intel: {tenant} {label}")
    if ok:
        logger.info("✅ GitHub sync push roadshow: %s", path)
    return ok


def pull_latest() -> dict[str, int]:
    """
    启动时调用：拉取 analytics/ 和 match_sessions/ 下的新文件，
    返回 {"pitch_imported": N, "match_imported": M}。
    新文件定义：本地 pitch_jobs 或 match_sessions 表中不存在的 session_id。
    同步状态写入 _sync_state 供 get_sync_status() 查询。
    """
    _sync_state["is_syncing"] = True
    _sync_state["last_error"] = None
    if not is_configured():
        _sync_state["is_syncing"] = False
        _sync_state["last_synced_at"] = time.time()
        _sync_state["last_result"] = {"pitch_imported": 0, "match_imported": 0}
        return {"pitch_imported": 0, "match_imported": 0}
    try:
        result = _pull_latest_inner()
        _sync_state["last_result"] = result
        _sync_state["last_synced_at"] = time.time()
        return result
    except Exception as e:
        _sync_state["last_error"] = str(e)
        logger.warning("pull_latest 失败: %s", e)
        return {"pitch_imported": 0, "match_imported": 0}
    finally:
        _sync_state["is_syncing"] = False


def _pull_latest_inner() -> dict[str, int]:

    from cangjie_fos.services.pitch_job_db import _connect  # type: ignore

    cfg = _cfg()
    pitch_count = 0
    match_count = 0

    # ── 拉取 analytics/ 下所有子目录 ──────────────────────────────────────────
    try:
        # 列出 analytics/ 下的所有目录（不同 tenant）
        import urllib.request
        url = f"https://api.github.com/repos/{cfg['repo']}/contents/analytics"
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=15) as resp:
            tenant_dirs = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.warning("pull_latest: 无法读取 analytics/: %s", e)
        tenant_dirs = []

    for tdir in tenant_dirs:
        if tdir.get("type") != "dir":
            continue
        # 递归处理子目录（如 analytics/zt/dd/）
        sub_files = _list_folder_recursive(tdir["path"])
        for f in sub_files:
            if not f["name"].endswith(".json"):
                continue
            # ── 用文件名前8位快速判重，跳过已有记录（避免下载）──
            fname = f["name"]  # e.g. "2026-05-16_be3a6c4e.json" or "roadshow_20260515_7db16569.json"
            parts = fname.replace(".json", "").split("_")
            id_hint = parts[-1] if parts else ""  # 取最后一段（8位 job_id 前缀）
            if len(id_hint) >= 8:
                conn = _connect()
                try:
                    pre_exists = conn.execute(
                        "SELECT 1 FROM pitch_jobs WHERE job_id LIKE ?", (id_hint + "%",)
                    ).fetchone()
                finally:
                    conn.close()
                if pre_exists:
                    continue  # 本地已有，跳过下载

            data = _download_json(f["download_url"])
            if not data:
                continue
            session_id = data.get("session_id", "")
            if not session_id:
                continue
            # fos_source 为 cangjie_fos 的才导入（跳过 FSS 旧数据）
            if data.get("fos_source") != "cangjie_fos":
                continue
            # 精确判重
            conn = _connect()
            try:
                exists = conn.execute(
                    "SELECT 1 FROM pitch_jobs WHERE job_id = ?", (session_id,)
                ).fetchone()
            finally:
                conn.close()
            if not exists:
                _import_remote_pitch(data)
                pitch_count += 1

    # ── 拉取 match_sessions/ 下所有子目录 ─────────────────────────────────────
    import urllib.request as _ur
    try:
        url2 = f"https://api.github.com/repos/{cfg['repo']}/contents/match_sessions"
        req2 = _ur.Request(url2, headers=_headers())
        with _ur.urlopen(req2, timeout=15) as resp2:
            ms_dirs = json.loads(resp2.read())
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        ms_dirs: list[dict[str, Any]] = []

    for mdir in ms_dirs:
        if mdir.get("type") != "dir":
            continue
        files = _list_folder(mdir["path"])
        for f in files:
            if not f["name"].endswith(".json"):
                continue
            data = _download_json(f["download_url"])
            if not data or data.get("fos_source") != "cangjie_fos":
                continue
            session_id = data.get("session_id", "")
            if not session_id:
                continue
            conn = _connect()
            try:
                exists = conn.execute(
                    "SELECT 1 FROM match_sessions WHERE id = ?", (session_id,)
                ).fetchone()
            finally:
                conn.close()
            if not exists:
                _import_remote_match(data)
                match_count += 1

    if pitch_count or match_count:
        logger.info("✅ GitHub pull: 新增 pitch=%d, match=%d", pitch_count, match_count)
    return {"pitch_imported": pitch_count, "match_imported": match_count}


# ─── 导入辅助 ─────────────────────────────────────────────────────────────────

def _import_remote_pitch(data: dict) -> None:
    """把远端 pitch JSON 作为只读记录写入本地 pitch_jobs，并同步创建机构记录。"""
    from cangjie_fos.services.pitch_job_db import _connect  # type: ignore

    job_id = data["session_id"]
    tenant_id = data.get("company_id", "remote")
    locked_at = data.get("locked_at", "")
    try:
        ts = datetime.strptime(locked_at, "%Y-%m-%dT%H:%M:%SZ").timestamp()
    except (ValueError, TypeError):
        ts = time.time()

    # 路演情报 JSON 用 institution 字段；普通复盘 JSON 用 institution_canonical
    is_roadshow = data.get("type") == "roadshow_intel"
    institution_name = (
        data.get("institution") if is_roadshow
        else data.get("institution_canonical", "")
    ) or ""

    # 重建最小化 report 以便 UI 能展示
    report = {
        "total_score": data.get("total_score", 0),
        "risk_breakdown": data.get("risk_breakdown", {}),
        "institution": institution_name,
        "fos_source": "remote_sync",
    }
    conn = _connect()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO pitch_jobs
               (job_id, tenant_id, status, created_at, original_report, interviewee,
                substatus, institution_id)
               VALUES (?, ?, 'locked', ?, ?, ?, 'synced_from_remote', ?)""",
            (
                job_id, tenant_id, ts,
                json.dumps(report, ensure_ascii=False),
                data.get("interviewee", ""),
                institution_name,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # ── 同步创建机构记录（INSERT OR IGNORE — 不覆盖用户已有编辑）─────────────────
    if institution_name.strip():
        _ensure_institution(tenant_id, institution_name, data, is_roadshow)


def _ensure_institution(
    tenant_id: str, name: str, data: dict, is_roadshow: bool
) -> None:
    """在 institutions 表中 INSERT OR IGNORE 一条机构记录（仅首次创建，不覆盖）。"""
    import sqlite3 as _sqlite3
    from cangjie_fos.core import paths as _paths

    db_path = _paths.get_backend_root() / "data" / "institutions.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # 推断阶段和热度
    stage = "pitched"   # 有了路演/复盘记录，至少是 pitched 阶段
    atmosphere = data.get("meeting_atmosphere", "")
    if atmosphere == "hot":
        thermal = "hot"
    elif atmosphere == "warm":
        thermal = "warm"
    else:
        thermal = "cold"

    institution_id = str(uuid.uuid4()).replace("-", "")[:16]

    conn = _sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS institutions (
                institution_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stage TEXT NOT NULL,
                thermal TEXT NOT NULL,
                preferences TEXT NOT NULL DEFAULT '',
                concerns TEXT NOT NULL DEFAULT '',
                ai_summary TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                source_trace_id TEXT,
                UNIQUE(tenant_id, name)
            )"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO institutions
               (institution_id, tenant_id, name, stage, thermal,
                preferences, concerns, ai_summary, updated_at, source_trace_id)
               VALUES (?, ?, ?, ?, ?, '', '', ?, ?, ?)""",
            (
                institution_id, tenant_id, name, stage, thermal,
                f"从 GitHub 同步（{'路演情报' if is_roadshow else '复盘分析'}）",
                time.time(),
                data.get("session_id", ""),
            ),
        )
        conn.commit()
        logger.info("✅ 机构记录同步: tenant=%s name=%s stage=%s", tenant_id, name, stage)
    except Exception as e:  # noqa: BLE001
        logger.warning("_ensure_institution 写入失败: %s", e)
    finally:
        conn.close()


def push_dd_session(session_id: str) -> bool:
    """
    把尽调会话摘要 push 到 analytics/{tenant}/dd/{date}_{session_id[:8]}.json。
    在 export 成功后作为 background_task 调用。
    """
    if not is_configured():
        return False

    from cangjie_fos.services.db_base import _connect
    import datetime as _dt

    with _connect() as conn:
        session_row = conn.execute(
            "SELECT * FROM dd_match_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not session_row:
            logger.warning("push_dd_session: session 不存在 %s", session_id)
            return False
        session = dict(session_row)

        items = [
            dict(r)
            for r in conn.execute(
                """SELECT item_no, category, requirement, matched_filename,
                          confidence, user_confirmed, user_skipped
                   FROM dd_match_items WHERE session_id = ? ORDER BY item_no""",
                (session_id,),
            ).fetchall()
        ]

    cfg = _cfg()
    tenant = session.get("tenant_id") or cfg["tenant"]
    date_str = _dt.date.today().isoformat()
    filename = f"{date_str}_{session_id[:8]}.json"
    path = f"analytics/{tenant}/dd/{filename}"

    export_payload = {
        "session_id": session_id,
        "institution_name": session.get("institution_name", ""),
        "checklist_name": session.get("checklist_name", ""),
        "folder_root": session.get("folder_root", ""),
        "status": session.get("status", ""),
        "created_at": _dt.datetime.fromtimestamp(
            session.get("created_at") or 0, tz=_dt.timezone.utc
        ).isoformat(),
        "item_count": len(items),
        "exported_count": sum(
            1 for i in items if i.get("user_confirmed") and not i.get("user_skipped")
        ),
        "missing_count": sum(1 for i in items if i.get("user_skipped")),
        "items": items,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }

    ok = _put_file(
        path,
        export_payload,
        f"dd session: {tenant} {session.get('institution_name') or session_id[:8]}",
    )
    if ok:
        logger.info("✅ GitHub sync DD session: %s", path)
    return ok


def _import_remote_match(data: dict) -> None:
    """把远端 match_sessions JSON 写入本地 match_sessions。"""
    from cangjie_fos.services.pitch_job_db import _connect  # type: ignore

    session_id = data["session_id"]
    created_iso = data.get("created_at", "")
    try:
        ts = datetime.strptime(created_iso, "%Y-%m-%dT%H:%M:%SZ").timestamp()
    except (ValueError, TypeError):
        ts = time.time()

    confirmed_files = data.get("confirmed_files", [])
    conn = _connect()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO match_sessions
               (id, created_at, institution, req_text, requirements, results, status, confirmed_files)
               VALUES (?, ?, ?, ?, '[]', '[]', ?, ?)""",
            (
                session_id, ts,
                data.get("institution", ""),
                data.get("req_text", ""),
                data.get("status", "confirmed"),
                json.dumps(confirmed_files, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()
