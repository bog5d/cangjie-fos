"""Phase 6 A4：用户提及拜访机构时，拼接档案块供 NPC System Prompt 使用。"""
from __future__ import annotations

from cangjie_fos.services.institution_store import find_matching_names


def build_pre_meeting_institution_block(*, tenant_id: str, user_text: str) -> str:
    t = user_text.strip()
    if not t:
        return ""
    cues = ("明天", "去见", "拜访", "约见", "对接", "会议", "聊一下", "路演")
    if not any(k in t for k in cues):
        return ""
    hits = find_matching_names(tenant_id=tenant_id, text=t)
    if not hits:
        return ""
    lines = ["[战前简报 · 机构档案命中]"]
    for h in hits[:5]:
        lines.append(
            f"- {h.name} | 阶段={h.stage.value} | 温度={h.thermal.value}\n"
            f"  偏好：{h.preferences or '—'}\n"
            f"  疑虑：{h.concerns or '—'}\n"
            f"  摘要：{h.ai_summary or '—'}"
        )
    lines.append("请结合上方档案与 Evolution Guidelines，给出可执行的避坑建议。")
    return "\n".join(lines)
