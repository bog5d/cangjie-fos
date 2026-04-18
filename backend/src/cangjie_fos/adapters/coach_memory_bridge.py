"""FOS 纠错 → Pitch_Coach memory_engine.capture_and_distill_diff（REFACTOR_PLAN P1）。"""
from __future__ import annotations

import logging
from typing import Any

from cangjie_fos.core.paths import ensure_pitch_coach_import_path

logger = logging.getLogger(__name__)


def try_capture_diff_to_executive_memory(
    *,
    tenant_id: str,
    ai_text: str,
    user_text: str,
    tag: str,
    risk_type: str = "",
) -> Any:
    """
    调用 Coach 防噪门 + 静默收割；company_id 不可解析或 Coach 异常时返回 None，不抛。
    返回值为 Coach `ExecutiveMemory | None`（不在此处强类型 import schema，避免 import 顺序问题）。
    """
    try:
        ensure_pitch_coach_import_path()
        from agent_tenant import resolve_memory_company_id
        from memory_engine import capture_and_distill_diff

        cid = resolve_memory_company_id(tenant_id)
        if not cid:
            return None
        tg = (tag or "").strip() or "default"
        return capture_and_distill_diff(
            ai_text,
            user_text,
            cid,
            tg,
            risk_type=(risk_type or "").strip(),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "coach_memory_bridge_failed tenant_id=%s tag=%s err=%s",
            tenant_id,
            tag,
            e,
        )
        return None
