"""事实护栏（fact guard）— 确定性校验 LLM 产出是否忠于原始材料。

背景（同事实测反馈，2026-06-11）：
  - 出题器把「月复合增长 12%」误读成「月流失率 12%」，还推导出「年化 78%」
  - 不同指标的数字互相搬用（毛利率 58% ↔ 客户集中度 46%）
  - 要点提炼凭空编出材料里没有的数字（32 张 GPU / 3000 万参数）

护栏原则：LLM 的输出里出现的**每一个数字**都必须能在原始材料里找到；
引用的「证据原句」必须真的是材料的子串。全部确定性实现，零 LLM。
"""
from __future__ import annotations

import re

# 全角数字/小数点 → 半角，统一后再提取
_FULLWIDTH = str.maketrans("０１２３４５６７８９．", "0123456789.")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# 证据比对时去掉的空白与标点（LLM 引用时常丢标点/空格，不应因此误判）
_SQUASH_RE = re.compile(r"[\s,，。、；;:：!！?？""''\"'()（）—·…-]+")


def _normalize(text: str) -> str:
    return (text or "").translate(_FULLWIDTH)


def extract_numbers(text: str) -> set[str]:
    """提取文本中的所有数字 token（规整小数尾零，'12.0' 与 '12' 视为同一数）。"""
    nums: set[str] = set()
    for m in _NUM_RE.finditer(_normalize(text)):
        s = m.group()
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        nums.add(s)
    return nums


def ungrounded_numbers(candidate: str, *sources: str) -> set[str]:
    """返回 candidate 中出现、但任何 source 里都找不到的数字集合。"""
    src: set[str] = set()
    for s in sources:
        src |= extract_numbers(s)
    return {n for n in extract_numbers(candidate) if n not in src}


def numbers_grounded(candidate: str, *sources: str) -> bool:
    """candidate 里的每个数字都能在 sources 中找到 → True。无数字也算 True。"""
    return not ungrounded_numbers(candidate, *sources)


def _squash(text: str) -> str:
    return _SQUASH_RE.sub("", _normalize(text))


def evidence_found(evidence: str, source: str) -> bool:
    """证据原句（忽略空白/标点差异后）确实是材料子串 → True。空证据 → False。"""
    ev = _squash(evidence)
    if not ev:
        return False
    return ev in _squash(source)
