"""报告后处理：用转录 words 重建风险点 original_text，覆盖 LLM 生成的单句摘录。

背景：Coach LangGraph 生成的 original_text 是 LLM 自行摘录的"代表性引文"，
通常只有一句。但 Coach 同时提供了精确的 start_word_index / end_word_index，
指向 ASR 转录 words 列表的真实位置。
本模块利用这些索引，从 words_json 重建完整对话段，替换 original_text。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _words_to_lookup(words_list: list[dict]) -> dict[int, dict]:
    """构建 word_index → word_dict 的快速查找表。"""
    lookup: dict[int, dict] = {}
    for i, w in enumerate(words_list):
        idx = w.get("word_index")
        if idx is None:
            idx = i  # fallback：以列表位置为 index
        lookup[int(idx)] = w
    return lookup


def _reconstruct_segment(
    words_lookup: dict[int, dict],
    start_idx: int,
    end_idx: int,
    *,
    include_speaker: bool = True,
    strip_single_speaker_prefix: bool = True,
) -> str:
    """从 words_lookup 中切出 [start_idx, end_idx] 的文字，并标注发言人变化。

    格式示例（多发言人）：
        [A] 你们的信披机制是怎样的？ [B] 我们每季度会有一次董事会披露…
    单一发言人：
        你们的信披机制是怎样的？
    """
    if start_idx > end_idx or not words_lookup:
        return ""

    # 按 index 顺序收集
    indices = sorted(k for k in words_lookup if start_idx <= k <= end_idx)
    if not indices:
        return ""

    segments: list[str] = []
    current_speaker: str | None = None
    current_tokens: list[str] = []

    for idx in indices:
        w = words_lookup[idx]
        text = (w.get("text") or "").strip()
        if not text:
            continue
        speaker = (w.get("speaker_id") or "").strip()

        if include_speaker and speaker and speaker != current_speaker:
            if current_tokens:
                prefix = f"[{current_speaker}] " if current_speaker else ""
                segments.append(prefix + " ".join(current_tokens))
                current_tokens = []
            current_speaker = speaker
        current_tokens.append(text)

    if current_tokens:
        if include_speaker and current_speaker:
            segments.append(f"[{current_speaker}] " + " ".join(current_tokens))
        else:
            segments.append(" ".join(current_tokens))

    # 单一发言人时可选去掉 speaker 前缀（审查台 HITL 需保留时传 strip_single_speaker_prefix=False）
    if strip_single_speaker_prefix and len(segments) == 1 and segments[0].startswith("["):
        # strip the leading "[X] " prefix
        bracket_end = segments[0].find("] ")
        if bracket_end != -1:
            segments[0] = segments[0][bracket_end + 2:]

    result = " ".join(segments)
    return result.strip()


def expand_risk_original_text(
    report_dict: dict[str, Any],
    words_list: list[dict],
    *,
    min_expand_ratio: float = 1.2,
) -> dict[str, Any]:
    """就地扩展 report_dict 中每条风险点的 original_text。

    只有当重建结果比原始文字长 min_expand_ratio 倍以上时才覆盖，
    避免把 LLM 精心筛选的引文替换成更差的结果。

    返回修改后的 report_dict（同一对象，也可链式调用）。
    """
    if not words_list or not isinstance(report_dict, dict):
        return report_dict

    risk_points = report_dict.get("risk_points")
    if not isinstance(risk_points, list):
        return report_dict

    lookup = _words_to_lookup(words_list)
    expanded_count = 0

    for rp in risk_points:
        if not isinstance(rp, dict):
            continue
        start = rp.get("start_word_index")
        end = rp.get("end_word_index")
        if start is None or end is None:
            continue
        try:
            start, end = int(start), int(end)
        except (TypeError, ValueError):
            continue

        reconstructed = _reconstruct_segment(
            lookup, start, end, strip_single_speaker_prefix=False
        )
        if not reconstructed:
            continue

        original = (rp.get("original_text") or "").strip()
        # 只替换当重建结果明显更长（覆盖更多上下文）时
        if len(reconstructed) >= len(original) * min_expand_ratio or not original:
            rp["original_text"] = reconstructed
            expanded_count += 1

    if expanded_count:
        logger.debug("original_text_expanded count=%d", expanded_count)

    return report_dict
