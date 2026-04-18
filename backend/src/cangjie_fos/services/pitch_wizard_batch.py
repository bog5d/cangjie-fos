"""与 AI_Pitch_Coach app.py 一致的批次名 / session_notes 拼装（无 UI 依赖）。"""
from __future__ import annotations

import json
import re

from cangjie_fos.schemas.pitch_upload_wizard import SniperRow

# 与 app.py 一致
SCENE_PLACEHOLDER = "—— 请先选择业务场景 ——"


def safe_fs_segment(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", name.strip())
    s = s[:200]
    return s or "未命名批次"


def compute_batch_name(*, institution_name: str, batch_label: str) -> str:
    inst = (institution_name or "").strip()
    lbl = (batch_label or "").strip()
    return inst or lbl or "未命名批次"


def sniper_rows_to_json(rows: list[SniperRow]) -> str:
    out: list[dict[str, str]] = []
    for r in rows:
        q = (r.quote or "").strip()
        rr = (r.reason or "").strip()
        if q or rr:
            out.append({"quote": q, "reason": rr})
    return json.dumps(out, ensure_ascii=False)


def build_session_notes(
    *,
    investor_name: str,
    interviewee: str,
    speaker_hint: str,
) -> str:
    parts: list[str] = []
    inv = (investor_name or "").strip()
    if inv:
        parts.append(f"【接待投资人】{inv}")
    sh = (speaker_hint or "").strip()
    if interviewee.strip() and sh:
        parts.append(f"身份映射提示：被访谈人「{interviewee.strip()}」= {sh}。")
    return "\n".join(parts).strip()
