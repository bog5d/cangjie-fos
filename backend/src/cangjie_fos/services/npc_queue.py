"""NPC 主动推送：内存脚本队列（长轮询 / WS 共用）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NpcLine:
    id: int
    role: str
    text: str
    proactive: bool


_LINES: list[NpcLine] = [
    NpcLine(0, "豆豆", "波总，今晚先把「数据室」三项勾齐？", True),
    NpcLine(1, "豆豆", "Teaser 里估值口径要不要压一档？", True),
    NpcLine(2, "豆豆", "Partner 会前，狙击手清单要不要再跑一遍？", True),
    NpcLine(3, "系统", "长轮询游标已回绕，可继续监听。", False),
]


def peek_lines_after(cursor: int) -> tuple[list[NpcLine], int]:
    """返回 cursor 之后的一批行及新游标。"""
    if cursor < 0:
        cursor = 0
    if cursor >= len(_LINES):
        cursor = 0
    batch = _LINES[cursor : cursor + 2]
    next_c = cursor + len(batch)
    if next_c >= len(_LINES):
        next_c = 0
    return batch, next_c


def line_by_index(idx: int) -> NpcLine | None:
    if 0 <= idx < len(_LINES):
        return _LINES[idx]
    return None
