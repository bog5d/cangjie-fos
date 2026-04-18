"""文本 Diff（捕获层）。"""
from __future__ import annotations

import difflib


def build_unified_diff(*, ai_text: str, user_text: str, context_lines: int = 3) -> str:
    a = ai_text.splitlines(keepends=True)
    b = user_text.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            a,
            b,
            fromfile="ai",
            tofile="user",
            n=context_lines,
        )
    )
