"""进化飞轮：把 investor_prefs 格式化成 explicit_context 条目，注入 Coach pipeline。

返回值是一个 dict，调用方只需 explicit_context.update(build_investor_context(...)) 即可。
格式化成自然语言，让 LLM 理解历史偏好并调整输出风格。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

_MAX_PREFS = 15          # 单次注入偏好上限，防止 context 过长
_MAX_CHARS = 800         # 注入文字总长度上限


def _fmt_score_bias(pref_value: Any) -> str:
    if not isinstance(pref_value, dict):
        return ""
    delta = pref_value.get("delta", 0)
    direction = "上调" if delta > 0 else "下调"
    return f"该投资人倾向于将 LLM 评分{direction} {abs(delta)} 分左右"


def _fmt_risk_calibration(pref_key: str, pref_value: Any) -> str:
    if "add" in pref_key:
        count = pref_value.get("count", 0) if isinstance(pref_value, dict) else 0
        return f"该投资人倾向于额外补充 {count} 个风险点（LLM 可适当增加风险维度）"
    if "remove" in pref_key:
        return "该投资人倾向于删减部分风险点（LLM 可减少冗余风险描述）"
    return ""


def _fmt_risk_level_adjustment(pref_key: str, pref_value: Any) -> str:
    if not isinstance(pref_value, dict):
        return ""
    from_lvl = pref_value.get("from", "")
    to_lvl = pref_value.get("to", "")
    if from_lvl and to_lvl:
        return f"该投资人倾向于将「{from_lvl}」级风险点升级为「{to_lvl}」（LLM 可适当提升风险等级判断）"
    return ""


_FORMATTERS = {
    "score_bias": _fmt_score_bias,
    "risk_calibration": lambda key, val: _fmt_risk_calibration(key, val),
    "risk_level_adjustment": lambda key, val: _fmt_risk_level_adjustment(key, val),
}


def build_investor_context(tenant_id: str) -> dict[str, str]:
    """查询该租户的历史偏好，返回可直接 merge 进 explicit_context 的 dict。

    如果无偏好数据或查询失败，返回空 dict（不影响 pipeline 正常运行）。
    """
    try:
        from cangjie_fos.services.pitch_job_db import db_pref_list_for_tenant  # noqa: PLC0415

        prefs = db_pref_list_for_tenant(tenant_id, limit=_MAX_PREFS)
        if not prefs:
            return {}

        # 去重：同一 pref_key 只取最新一条
        seen: set[str] = set()
        deduped = []
        for p in prefs:
            key = p.get("pref_key", "")
            if key not in seen:
                seen.add(key)
                deduped.append(p)

        # 按类型聚合，格式化成自然语言
        lines: list[str] = []
        type_counts: dict[str, int] = defaultdict(int)
        for pref in deduped:
            ptype = pref.get("pref_type", "")
            pkey = pref.get("pref_key", "")
            pval = pref.get("pref_value")
            formatter = _FORMATTERS.get(ptype)
            if not formatter:
                continue
            try:
                if ptype == "score_bias":
                    line = formatter(pval)
                else:
                    line = formatter(pkey, pval)
                if line:
                    lines.append(f"- {line}")
                    type_counts[ptype] += 1
            except Exception:  # noqa: BLE001
                continue

        if not lines:
            return {}

        text = "【投资人历史偏好（请参考，不强制执行）】\n" + "\n".join(lines)
        # 截断保护
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + "…"

        logger.info(
            "evolution_inject tenant=%s pref_count=%d types=%s",
            tenant_id,
            len(lines),
            dict(type_counts),
        )
        return {"investor_preferences": text}

    except Exception:  # noqa: BLE001
        logger.warning("evolution_inject_failed tenant=%s, skipping", tenant_id, exc_info=True)
        return {}
