"""需求03 — 数据包「缺口分析」编排。

扫描已索引材料库 → 对照标准模板逐项匹配 → 把每项归为 已有/需更新/缺失。

设计：独立的 package_sessions/package_items 表（与尽调台隔离，不污染其会话列表），
但匹配内核**复用尽调引擎的纯函数**（关键词预筛 + 文件列表构建 + 红黄绿阈值），
以及 dd_index 的扫描索引（材料库索引机构无关、全局共享）。

_llm_match_package 可被测试 monkeypatch，全链路无需真实 LLM。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Callable

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_index_service import get_index_by_folder
from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry
from cangjie_fos.services.dd_match_service import (
    _build_file_list_text,
    _prefilter_files_for_batch,
    _VERDICT_GREEN,
    _VERDICT_YELLOW,
)
from cangjie_fos.services.package_template_store import (
    BUILTIN_ID,
    get_template_items,
    template_exists,
)

logger = logging.getLogger(__name__)

# 匹配上但文件超过此天数未更新 → 归为「需更新」（即便置信度高）
_STALE_DAYS = 365
_STALE_SECONDS = _STALE_DAYS * 24 * 3600

# gap_state 取值
HAVE = "have"        # 已有（高置信 + 不过期）
UPDATE = "update"    # 需更新（中置信 / 过期）
MISSING = "missing"  # 缺失（无匹配 / 低置信）
PENDING = "pending"  # 未分析


def create_session(
    tenant_id: str,
    folder_root: str,
    title: str = "",
    template_id: str = BUILTIN_ID,
) -> dict:
    """创建数据包补全会话，按所选模板（DB，可编辑）铺开待检项。返回 {session_id, count}。"""
    if not template_exists(template_id, tenant_id):
        raise ValueError(f"模板 {template_id} 不存在")
    template = get_template_items(template_id, tenant_id)
    if not template:
        raise ValueError(f"模板 {template_id} 没有任何条目，请先编辑模板")
    session_id = str(uuid.uuid4())
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO package_sessions
               (session_id, tenant_id, title, folder_root, template_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (session_id, tenant_id, title, folder_root, template_id, now),
        )
        for it in template:
            conn.execute(
                """INSERT INTO package_items
                   (id, session_id, item_no, category, requirement, importance,
                    gap_state, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (str(uuid.uuid4()), session_id, it["item_no"], it["category"],
                 it["requirement"], it["importance"], now),
            )
    return {"session_id": session_id, "count": len(template)}


def get_session(session_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM package_sessions WHERE session_id = ?", (session_id,),
        ).fetchone()
    return dict(row) if row else None


def list_items(session_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM package_items WHERE session_id = ? ORDER BY CAST(item_no AS INTEGER)",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# 完整度评分权重：core 项权重 2，normal 项 1；已有计满分，需更新计一半，缺失 0。
_IMP_WEIGHT = {"core": 2.0, "normal": 1.0}
_STATE_RATIO = {HAVE: 1.0, UPDATE: 0.5, MISSING: 0.0, PENDING: 0.0}


def gap_summary(session_id: str) -> dict:
    """按 gap_state 汇总条数 + 加权完整度评分 + 分维度细分，供前端缺口看板。"""
    items = list_items(session_id)
    counts = {HAVE: 0, UPDATE: 0, MISSING: 0, PENDING: 0}
    earned = 0.0
    total_w = 0.0
    by_cat: dict[str, dict] = {}
    for it in items:
        state = it.get("gap_state", PENDING)
        counts[state] = counts.get(state, 0) + 1
        w = _IMP_WEIGHT.get(it.get("importance", "normal"), 1.0)
        total_w += w
        earned += w * _STATE_RATIO.get(state, 0.0)
        cat = it.get("category", "未分类")
        c = by_cat.setdefault(cat, {"have": 0, "update": 0, "missing": 0, "pending": 0, "total": 0})
        c[state if state in c else "pending"] += 1
        c["total"] += 1
    score = round(earned / total_w * 100.0, 1) if total_w > 0 else 0.0
    # 必备项（core）缺失数：投资人必看却没有的，单独点名
    core_missing = sum(
        1 for it in items
        if it.get("importance") == "core" and it.get("gap_state") == MISSING
    )
    return {
        "total": len(items),
        "have": counts[HAVE],
        "update": counts[UPDATE],
        "missing": counts[MISSING],
        "pending": counts[PENDING],
        "score": score,
        "core_missing": core_missing,
        "by_category": by_cat,
    }


def list_sessions(tenant_id: str = "default", limit: int = 10) -> list[dict]:
    """列出最近的数据包会话（仅本功能，scenario 隔离天然成立——独立表）。"""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT s.session_id, s.tenant_id, s.title, s.folder_root, s.status,
                      s.created_at, s.completed_at,
                      COUNT(i.id) AS item_count,
                      SUM(CASE WHEN i.gap_state = 'missing' THEN 1 ELSE 0 END) AS missing_count
               FROM package_sessions s
               LEFT JOIN package_items i ON i.session_id = s.session_id
               WHERE s.tenant_id = ?
               GROUP BY s.session_id
               ORDER BY s.created_at DESC
               LIMIT ?""",
            (tenant_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _classify(confidence: float, mtime: float | None, now: float) -> str:
    """置信度 + 文件新鲜度 → 缺口三态。"""
    if confidence < _VERDICT_YELLOW:
        return MISSING
    # 匹配上了：高置信但文件陈旧 → 需更新；中置信 → 需更新（待核）；高置信且新 → 已有
    if confidence >= _VERDICT_GREEN:
        if mtime and (now - mtime) > _STALE_SECONDS:
            return UPDATE
        return HAVE
    return UPDATE


def run_gap_analysis(
    session_id: str,
    folder_root: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """对会话每个模板项与材料库索引匹配，归类缺口。同步执行，调用方包 BackgroundTask。

    无论中途是否异常，最终都给 session 一个终态（done/failed），防止前端无限轮询。
    """
    failed = False
    try:
        index_rows = get_index_by_folder(folder_root)
        items = list_items(session_id)
        if not items:
            return

        now = time.time()
        # 索引为空：所有项判缺失（材料库没扫到东西）
        if not index_rows:
            with _connect() as conn:
                for it in items:
                    conn.execute(
                        "UPDATE package_items SET gap_state = ?, confidence = 0.0, "
                        "match_reason = '材料库为空，未找到任何文件' WHERE id = ?",
                        (MISSING, it["id"]),
                    )
            return

        mtime_by_path = {r["file_path"]: r.get("mtime") for r in index_rows}
        matches = _llm_match_package(items, index_rows)

        total = len(items)
        with _connect() as conn:
            for i, it in enumerate(items):
                m = matches.get(it["id"], {})
                conf = float(m.get("confidence", 0.0) or 0.0)
                path = m.get("file_path")
                mtime = mtime_by_path.get(path) if path else None
                state = _classify(conf, mtime, now)
                conn.execute(
                    """UPDATE package_items
                       SET matched_file_path = ?, matched_filename = ?, confidence = ?,
                           match_reason = ?, gap_state = ?
                       WHERE id = ?""",
                    (path, m.get("filename"), conf, m.get("reason", ""), state, it["id"]),
                )
                if progress_callback and (i + 1) % 5 == 0:
                    progress_callback(i + 1, total)
    except Exception as e:  # noqa: BLE001
        logger.error("数据包缺口分析异常 session=%s: %s", session_id, e)
        failed = True
    finally:
        status = "failed" if failed else "done"
        with _connect() as conn:
            conn.execute(
                "UPDATE package_sessions SET status = ?, completed_at = ? WHERE session_id = ?",
                (status, time.time(), session_id),
            )


def _llm_match_package(items: list[dict], index_rows: list[dict]) -> dict[str, dict]:
    """对模板项批量匹配材料库文件（可被测试 monkeypatch）。

    复用尽调引擎的关键词预筛 + 文件列表构建（含注入打码）。模板项数量有限
    （标准模板 ~21 条），单批一次发完即可。
    返回 {item_id: {file_path, filename, confidence, reason}}。
    """
    batch_rows = _prefilter_files_for_batch(items, index_rows, top_n=50)
    file_list_text = _build_file_list_text(batch_rows)
    req_lines = "\n".join(
        f"需求{i + 1}（ID:{it['id']}）：{it['requirement']}"
        for i, it in enumerate(items)
    )
    prompt = f"""你是融资材料管理助手。以下是材料库中的文件（编号+摘要）：

{file_list_text}

以下是一份「标准数据包」要求具备的材料项：
{req_lines}

为每条要求找最匹配的 1 个文件。没有合适文件的该条 candidates 填 []。
只依据文件名/摘要与要求的真实相关性判断，不要硬凑。
返回 JSON（key 是需求 ID）：
{{"需求ID": {{"candidates": [{{"file_index": N, "confidence": 0到1的小数, "reason": "一句话说明"}}]}}}}
只返回 JSON："""

    client = get_dd_llm_client()

    def _call() -> dict:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())

    try:
        parsed = call_with_retry(_call, max_retries=3)
    except Exception as e:  # noqa: BLE001
        logger.error("数据包匹配 LLM 失败: %s", e)
        return {}

    out: dict[str, dict] = {}
    for it in items:
        res = parsed.get(it["id"], {}) if isinstance(parsed, dict) else {}
        cands = res.get("candidates", []) if isinstance(res, dict) else []
        best = None
        for cand in cands:
            idx = cand.get("file_index")
            if isinstance(idx, int) and 0 <= idx < len(batch_rows):
                best = {
                    "file_path": batch_rows[idx]["file_path"],
                    "filename": batch_rows[idx]["filename"],
                    "confidence": float(cand.get("confidence", 0.5)),
                    "reason": str(cand.get("reason", "")),
                }
                break
        if best:
            out[it["id"]] = best
    return out
