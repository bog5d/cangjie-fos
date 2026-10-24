"""开发者可见：记录每步实际注入 LLM 的 prompt（解析后澄清 / 粗筛匹配 / 全文精判）。

目的：让开发者能看到"这一步到下一步到底喂了什么提示词 + 注入了什么背景/规则",
便于发现 prompt 不对、定位匹配质量问题。每个 session 每个 stage 只留最新一条
（INSERT OR REPLACE），避免精判逐候选写入把表撑爆。

record_prompt 全程吞异常——记录失败绝不能影响主流程（匹配/精判）。
"""
from __future__ import annotations

import logging
import time

from cangjie_fos.services.db_base import _connect

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 16000

# 各阶段中文名（前端展示用）
STAGE_LABELS = {
    "clarify": "解析后·AI自检澄清",
    "matching": "粗筛匹配（文件名+摘要）",
    "verifying": "全文精判验证",
}


def record_prompt(session_id: str | None, stage: str, text: str) -> None:
    """记录某 session 某 stage 实际发送的 prompt（截断 + 幂等覆盖，失败静默）。"""
    if not session_id or not stage:
        return
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO dd_prompt_log
                   (session_id, stage, prompt_text, created_at) VALUES (?, ?, ?, ?)""",
                (session_id, stage, (text or "")[:MAX_PROMPT_CHARS], time.time()),
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("record_prompt 失败（忽略）: %s", e)


def get_prompts(session_id: str) -> list[dict]:
    """返回该 session 已记录的各阶段 prompt（含中文标签），按阶段固定顺序。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT stage, prompt_text, created_at FROM dd_prompt_log WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    order = {"clarify": 0, "matching": 1, "verifying": 2}
    out = [
        {"stage": r["stage"], "label": STAGE_LABELS.get(r["stage"], r["stage"]),
         "prompt_text": r["prompt_text"], "created_at": r["created_at"]}
        for r in rows
    ]
    out.sort(key=lambda x: order.get(x["stage"], 99))
    return out
