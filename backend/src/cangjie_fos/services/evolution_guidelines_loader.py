"""读取 evolution_guidelines.jsonl 供 NPC System Prompt 注入（Phase 5 A3）。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from cangjie_fos.core import paths as fos_paths

logger = logging.getLogger(__name__)


def load_recent_guidelines_for_prompt(*, tenant_id: str, max_lines: int = 12, max_chars: int = 2400) -> str:
    """取近期与当前 tenant 或全局相关的指南文本（多行 JSONL）。"""
    fp: Path = fos_paths.get_backend_root() / "data" / "evolution" / "evolution_guidelines.jsonl"
    if not fp.is_file():
        return ""
    lines: list[str] = []
    try:
        raw_lines = fp.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.warning("evolution_guidelines_read_failed: %s", e)
        return ""
    for row in raw_lines[-200:]:
        row = row.strip()
        if not row:
            continue
        try:
            obj = json.loads(row)
        except json.JSONDecodeError:
            continue
        scope = str(obj.get("tenant_scope") or "")
        if scope not in ("", "all", tenant_id):
            continue
        text = (obj.get("text") or "").strip()
        if text:
            lines.append(f"- {text}")
    if not lines:
        return ""
    blob = "\n".join(lines[-max_lines:])
    return blob[:max_chars]
