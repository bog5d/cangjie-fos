"""夜间自动进化结算服务（Phase 3）。

每晚2点由 APScheduler 触发，逐租户执行：
1. 偏好提取（pending review_diffs → investor_prefs）
2. 规则性素材建议生成
3. 写入 nightly_suggestions 表供豆豆次日注入
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

import structlog

from cangjie_fos.services.pitch_job_db import (
    _connect,
    _write_lock,
    db_nightly_suggestion_insert,
    db_job_list_risk_keywords,
    db_material_contributions_list,
)

log = structlog.get_logger(__name__)


def _list_active_tenant_ids() -> list[str]:
    """返回 pitch_jobs 中所有有 completed 状态记录的 tenant_id（去重）。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT DISTINCT tenant_id FROM pitch_jobs WHERE status = 'completed'"
        )
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def _simple_tfidf_score(keyword: str, asset_filename: str, asset_tags: list[str]) -> float:
    """纯 Python TF-IDF 简化打分：keyword 在 asset 标签/文件名中命中得分。"""
    kw = keyword.casefold()
    score = 0.0
    filename_lower = asset_filename.casefold()
    if kw in filename_lower:
        score += 2.0
    for tag in asset_tags:
        if kw in tag.casefold():
            score += 1.5
    return score


def _generate_material_suggestions(tenant_id: str) -> list[dict[str, Any]]:
    """真实素材建议计算（Phase 4 — 基于 TF-IDF 风险覆盖率分析）。"""
    # Step 1: 读取最近10条已完成路演的风险关键词
    job_risks = db_job_list_risk_keywords(tenant_id, limit=10)
    all_keywords: list[str] = []
    for job in job_risks:
        for rp in job.get("risk_points") or []:
            for field in ("original_text", "category", "type"):
                val = rp.get(field)
                if val and isinstance(val, str) and val.strip():
                    all_keywords.append(val.strip().casefold())

    # Step 2: 读取素材库数据
    all_assets = db_material_contributions_list(limit=200)

    suggestions: list[dict[str, Any]] = []

    # Step 3a: 找出覆盖率低于30%的风险点类型 → 生成 "material_update" 建议
    if all_keywords and all_assets:
        unique_kws = list(dict.fromkeys(all_keywords))  # 保留顺序去重
        uncovered: list[str] = []
        for kw in unique_kws:
            covered = any(
                _simple_tfidf_score(kw, a["asset_filename"], a.get("tags") or []) > 0
                for a in all_assets
            )
            if not covered:
                uncovered.append(kw)

        coverage_rate = 1.0 - len(uncovered) / len(unique_kws) if unique_kws else 1.0
        if coverage_rate < 0.30 and uncovered:
            top_uncovered = uncovered[:3]
            suggestions.append({
                "type": "material_update",
                "content": f"风险点素材覆盖率仅 {coverage_rate:.0%}，高频未覆盖风险：{', '.join(top_uncovered)}，建议补充对应素材。",
                "priority": 4,
            })

    # Step 3b: 找出 contribution_score 为0但被多次引用的素材 → 生成 "institution_insight" 建议
    for asset in all_assets:
        if int(asset.get("usage_count") or 0) >= 3 and float(asset.get("contribution_score") or 0.0) == 0.0:
            suggestions.append({
                "type": "institution_insight",
                "content": f"素材「{asset['asset_filename']}」已被引用 {asset['usage_count']} 次但贡献分为零，建议评估其实际价值并更新贡献评分。",
                "asset_id": asset["asset_filename"],
                "priority": 5,
            })

    # Step 3c: 兜底：近期活跃但无素材库数据时，给出基础建议
    if not suggestions and job_risks:
        suggestions.append({
            "type": "material_update",
            "content": f"已完成 {len(job_risks)} 次路演评估，素材库暂无匹配数据，建议运行「向上扫描」同步素材索引。",
            "priority": 5,
        })

    return suggestions


async def nightly_settle_for_tenant(tenant_id: str) -> int:
    """对单租户执行夜间结算，返回写入建议条数。"""
    log.info("nightly_settle_start", tenant_id=tenant_id)
    count = 0

    # Step 1: 偏好提取
    try:
        from cangjie_fos.services.evolution_extractor import run_preference_extraction  # noqa: PLC0415
        extracted = run_preference_extraction(tenant_id=tenant_id)
        log.info("nightly_pref_extracted", tenant_id=tenant_id, count=extracted)
    except (RuntimeError, OSError, ValueError) as exc:
        log.warning("nightly_pref_extraction_failed", tenant_id=tenant_id, error=str(exc))

    # Step 2: 生成素材建议
    try:
        suggestions = _generate_material_suggestions(tenant_id)
    except Exception as exc:
        log.warning("nightly_material_suggestions_failed", tenant_id=tenant_id, error=str(exc))
        suggestions = []

    # Step 3: 写入 nightly_suggestions 表
    for s in suggestions:
        try:
            db_nightly_suggestion_insert(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                type=s["type"],
                content=s["content"],
                asset_id=s.get("asset_id"),
                priority=s.get("priority", 5),
            )
            count += 1
        except Exception as exc:
            log.warning("nightly_suggestion_insert_failed", error=str(exc))

    log.info("nightly_settle_done", tenant_id=tenant_id, suggested=count)

    # 推送结算摘要到 NPC 消息队列，下次用户打开面板时可见
    try:
        from cangjie_fos.services.npc_queue import push_line  # noqa: PLC0415
        from datetime import datetime as _dt  # noqa: PLC0415
        ts = _dt.now().strftime("%m/%d %H:%M")
        push_line(
            role="assistant",
            text=f"【{ts} 夜间沉淀完成】今晚为 {tenant_id} 提炼了 {count} 条进化建议，请查看「夜间建议」面板。",
            proactive=True,
        )
    except Exception as exc:
        log.warning("nightly_settle_push_line_failed", error=str(exc))

    return count


async def nightly_settle_all_tenants() -> None:
    """APScheduler cron 入口：遍历所有活跃租户执行夜间结算。"""
    log.info("nightly_settle_all_start")
    try:
        tenant_ids = _list_active_tenant_ids()
    except Exception as exc:
        log.error("nightly_settle_list_tenants_failed", error=str(exc))
        return

    for tenant_id in tenant_ids:
        try:
            await nightly_settle_for_tenant(tenant_id)
        except (RuntimeError, OSError, ValueError) as exc:
            log.error("nightly_settle_tenant_failed", tenant_id=tenant_id, error=str(exc))

    log.info("nightly_settle_all_done", tenant_count=len(tenant_ids))
