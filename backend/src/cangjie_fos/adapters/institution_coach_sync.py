"""FOS 机构名投影到 Pitch_Coach institution_registry（单向、失败不抛）。"""
from __future__ import annotations

import logging

from cangjie_fos.core.config import settings
from cangjie_fos.core.paths import ensure_pitch_coach_import_path

logger = logging.getLogger(__name__)


def project_institution_to_coach_registry(*, name: str, tenant_id: str | None = None) -> None:  # noqa: ARG001
    """将规范机构名写入 Coach `institutions.json`；tenant_id 预留日志关联。"""
    if not settings.sync_institution_to_coach:
        return
    nm = (name or "").strip()
    if not nm:
        return
    try:
        ensure_pitch_coach_import_path()
        from institution_registry import register

        register(nm)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "institution_coach_sync_failed name=%s tenant_id=%s err=%s",
            nm,
            tenant_id,
            e,
        )
