"""资产活力雷达服务：计算健康分、写快照、返回趋势。"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from cangjie_fos.services.pitch_job_db import (
    db_assets_list,
    db_health_snapshot_insert,
    db_health_snapshot_latest,
    db_health_snapshot_list,
    db_scan_config_get,
)

logger = logging.getLogger(__name__)

# 融资材料的标准关键词分类
_REQUIRED_CATS: list[dict[str, Any]] = [
    {"id": "bp",        "name": "商业计划书",   "keywords": ["bp", "商业计划", "business plan"]},
    {"id": "finance",   "name": "财务报表",     "keywords": ["财务", "资产负债", "利润", "审计", "financial"]},
    {"id": "equity",    "name": "股权结构",     "keywords": ["股权", "股东", "架构", "equity", "shareholding"]},
    {"id": "team",      "name": "核心团队",     "keywords": ["简历", "团队", "resume", "cv", "team"]},
    {"id": "product",   "name": "产品介绍",     "keywords": ["产品", "product", "方案", "demo"]},
    {"id": "license",   "name": "营业执照",     "keywords": ["营业执照", "business license", "执照"]},
]

_ZOMBIE_DAYS = 90   # 超过此天数未更新 → 僵尸
_SLEEP_DAYS  = 30   # 超过此天数未更新 → 休眠


def _detect_cat(assets: list[dict[str, Any]], cat: dict[str, Any]) -> bool:
    """判断资产列表中是否存在覆盖该分类的文件。
    检查范围：文件名、relative_path（目录名含业务关键词）、tags、summary。
    """
    kws = [k.casefold() for k in cat["keywords"]]
    for a in assets:
        name = (a.get("filename") or "").casefold()
        rel_path = (a.get("relative_path") or "").casefold()
        tags_str = " ".join(a.get("tags") or []).casefold()
        summary = (a.get("summary") or "").casefold()
        text = f"{name} {rel_path} {tags_str} {summary}"
        if any(kw in text for kw in kws):
            return True
    return False


def _parse_date(s: str | None) -> date | None:
    """把 YYYY-MM-DD 字符串解析为 date，失败返回 None。"""
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _scene_distribution(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按文件所在顶层目录统计场景分布，根目录归为「根目录」。"""
    counter: Counter[str] = Counter()
    for a in assets:
        path = (a.get("relative_path") or "").strip("/\\")
        if not path:
            scene = "根目录"
        else:
            scene = Path(path).parts[0] if Path(path).parts else "根目录"
        counter[scene] += 1
    total = sum(counter.values()) or 1
    return [
        {"scene": k, "count": v, "pct": round(v / total * 100)}
        for k, v in counter.most_common(8)
    ]


def compute_health(assets: list[dict[str, Any]]) -> dict[str, Any]:
    """计算健康分（类别覆盖）+ 僵尸清单 + 场景分布。

    评分规则：每覆盖一个分类得 100/len(REQUIRED_CATS) 分，上限 100。
    同时用 FSS 公式计算活力分：max(0, 100 - 僵尸*2 - 休眠*0.5 + 总数*0.1)
    最终 score = 两者平均，综合反映「完整度」与「新鲜度」。
    """
    # ── 分类覆盖 ──────────────────────────────────────────────
    present: list[str] = []
    missing: list[str] = []
    for cat in _REQUIRED_CATS:
        if _detect_cat(assets, cat):
            present.append(cat["name"])
        else:
            missing.append(cat["name"])
    n = len(_REQUIRED_CATS)
    coverage_score = round(len(present) / n * 100) if n else 0

    # ── 时效性（僵尸/休眠） ───────────────────────────────────
    today = date.today()
    zombie_files: list[str] = []
    high_active = sleep_count = zombie_count = 0
    for a in assets:
        d = _parse_date(a.get("last_modified"))
        filename = a.get("filename", "未知文件")
        if d is None:
            sleep_count += 1
            continue
        days = (today - d).days
        if days <= _SLEEP_DAYS:
            high_active += 1
        elif days <= _ZOMBIE_DAYS:
            sleep_count += 1
        else:
            zombie_count += 1
            zombie_files.append(filename)

    total = len(assets)
    if total == 0:
        vitality_score = 0
        score = 0
    else:
        vitality_score = max(0, round(100 - zombie_count * 2 - sleep_count * 0.5 + total * 0.1))
        # 综合分 = 覆盖率 × 0.6 + 活力 × 0.4
        score = round(coverage_score * 0.6 + vitality_score * 0.4)

    return {
        "score": score,
        "coverage_score": coverage_score,
        "vitality_score": vitality_score,
        "present_cats": present,
        "missing_cats": missing,
        "total_cats": n,
        "high_active": high_active,
        "sleep_count": sleep_count,
        "zombie_count": zombie_count,
        "zombie_files": zombie_files[:20],  # 最多展示 20 个
        "scene_distribution": _scene_distribution(assets),
    }


def take_health_snapshot() -> dict[str, Any]:
    """获取当前资产列表、计算健康分、写入快照表，返回快照详情。"""
    assets = db_assets_list(limit=2000)
    cfg = db_scan_config_get()
    scan_dir = (cfg or {}).get("scan_dir", "")

    health = compute_health(assets)
    row_id = db_health_snapshot_insert(
        score=health["score"],
        total_files=len(assets),
        indexed_files=len(assets),
        missing_cats=health["missing_cats"],
        scan_dir=scan_dir,
    )
    snap_at = datetime.now(tz=timezone.utc).isoformat()
    logger.info(
        "health_snapshot id=%d score=%d vitality=%d coverage=%d zombie=%d",
        row_id, health["score"], health["vitality_score"],
        health["coverage_score"], health["zombie_count"],
    )
    return {
        "id": row_id,
        "snapshot_at": snap_at,
        "score": health["score"],
        "coverage_score": health["coverage_score"],
        "vitality_score": health["vitality_score"],
        "total_files": len(assets),
        "present_cats": health["present_cats"],
        "missing_cats": health["missing_cats"],
        "high_active": health["high_active"],
        "sleep_count": health["sleep_count"],
        "zombie_count": health["zombie_count"],
        "zombie_files": health["zombie_files"],
        "scene_distribution": health["scene_distribution"],
        "scan_dir": scan_dir,
    }


def get_health_dashboard() -> dict[str, Any]:
    """返回最新快照 + 近 30 条趋势 + 实时僵尸/场景数据，供前端仪表盘展示。"""
    latest = db_health_snapshot_latest()
    history = db_health_snapshot_list(limit=30)
    trend = [
        {
            "snapshot_at": datetime.fromtimestamp(r["snapshot_at"], tz=timezone.utc).isoformat(),
            "score": r["score"],
            "total_files": r["total_files"],
        }
        for r in history
    ]

    if latest is None:
        return {
            "score": 0,
            "coverage_score": 0,
            "vitality_score": 0,
            "total_files": 0,
            "missing_cats": [],
            "present_cats": [],
            "high_active": 0,
            "sleep_count": 0,
            "zombie_count": 0,
            "zombie_files": [],
            "scene_distribution": [],
            "trend": [],
            "has_data": False,
        }

    # 实时重算僵尸和场景（快照只存分数和缺失分类，实时字段需重新算）
    assets = db_assets_list(limit=2000)
    health = compute_health(assets)

    return {
        "score": latest["score"],
        "coverage_score": health["coverage_score"],
        "vitality_score": health["vitality_score"],
        "total_files": latest["total_files"],
        "missing_cats": latest["missing_cats"],
        "present_cats": [c["name"] for c in _REQUIRED_CATS if c["name"] not in latest["missing_cats"]],
        "high_active": health["high_active"],
        "sleep_count": health["sleep_count"],
        "zombie_count": health["zombie_count"],
        "zombie_files": health["zombie_files"],
        "scene_distribution": health["scene_distribution"],
        "trend": trend,
        "has_data": True,
        "snapshot_at": datetime.fromtimestamp(latest["snapshot_at"], tz=timezone.utc).isoformat(),
    }
