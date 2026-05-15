"""
LLM 逻辑打分模块 2.0：三巨头模型路由（DeepSeek / Kimi / Qwen-Max）+ AnalysisReport 契约。
仓库发版 V7.5（与 build_release.CURRENT_VERSION 对齐）。
V7.5：max_tokens 扩容、截断 JSON 抢救、结构化狙击清单；沿用转写/QA 分池与超长截断。
支持显式业务上下文与 QA 知识库注入，结构化防幻觉 Prompt。
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, List

from openai import APIError, OpenAI
from pydantic import ValidationError

from cangjie_fos.engine.retry_policy import run_with_backoff
from cangjie_fos.engine.language_detector import detect_language_from_words, get_language_prompt_hint
from cangjie_fos.engine.schema import (
    AnalysisReport,
    ExecutiveMemory,
    IntelAction,
    IntelQuestion,
    IntelSignal,
    MagicRefinementResult,
    RiskPoint,
    RiskScanResult,
    RiskTargetCandidate,
    RoadshowIntelReport,
    SceneAnalysis,
    TranscriptionWord,
)
from cangjie_fos.engine.runtime_paths import get_writable_app_root


def _recover_risk_point_dicts_from_truncated_json(raw: str) -> list[dict[str, Any]] | None:
    """
    在整段响应非法 JSON 时，定位 risk_points 数组，用 JSONDecoder.raw_decode
    顺序解析其中每一个完整对象，丢弃末尾未完成碎片（非正则拼接）。
    """
    marker = '"risk_points"'
    mi = raw.find(marker)
    if mi < 0:
        return None
    lb = raw.find("[", mi)
    if lb < 0:
        return None
    decoder = json.JSONDecoder()
    pos = lb + 1
    n = len(raw)
    items: list[dict[str, Any]] = []
    while pos < n:
        while pos < n and raw[pos] in " \t\n\r,":
            pos += 1
        if pos >= n or raw[pos] == "]":
            break
        try:
            obj, end = decoder.raw_decode(raw, pos)
            if isinstance(obj, dict):
                items.append(obj)
            pos = end
        except json.JSONDecodeError:
            break
    return items or None


def _closing_brace_indices_outside_strings(s: str) -> list[int]:
    """从左到右记录所有位于 JSON 字符串外的 `}` 下标（供逆向裁剪候选）。"""
    in_str = False
    escape = False
    out: list[int] = []
    for i, c in enumerate(s):
        if escape:
            escape = False
            continue
        if in_str:
            if c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "}":
            out.append(i)
    return out


def salvage_risk_point_dicts_from_truncated_llm_json(raw: str) -> list[dict[str, Any]] | None:
    """
    抢救 `risk_points` 中已完整闭合的对象列表。
    顺序：① 数组内 raw_decode 增量解析；② 自右向左在字符串外截取到最后一个 `}` 再试；
    ③ 自尾向前逐字符缩短再试。全程不抛 JSONDecodeError。
    """
    if not (raw or "").strip():
        return None
    direct = _recover_risk_point_dicts_from_truncated_json(raw)
    if direct:
        return direct
    mi = raw.find('"risk_points"')
    if mi < 0:
        return None
    lb = raw.find("[", mi)
    if lb < 0:
        return None
    for j in reversed(_closing_brace_indices_outside_strings(raw)):
        if j <= lb:
            continue
        prefix = raw[: j + 1].rstrip()
        got = _recover_risk_point_dicts_from_truncated_json(prefix)
        if got:
            return got
    rstrip = raw.rstrip()
    max_trim = min(8000, max(0, len(rstrip)))
    for t in range(1, max_trim + 1):
        got = _recover_risk_point_dicts_from_truncated_json(rstrip[:-t].rstrip())
        if got:
            return got
    return None


def _is_valid_risk_point(rp: RiskPoint) -> bool:
    """空壳 RiskPoint 守门：tier1 和 improvement_suggestion 均非空才算有效。"""
    return bool((rp.tier1_general_critique or "").strip()) and bool(
        (rp.improvement_suggestion or "").strip()
    )


def salvage_truncated_analysis_report(raw: str) -> AnalysisReport | None:
    """将截断 LLM 输出抢救为可展示的 AnalysisReport；无法抢救时返回 None。"""
    dicts = salvage_risk_point_dicts_from_truncated_llm_json(raw)
    if not dicts:
        return None
    risks: list[RiskPoint] = []
    for d in dicts:
        try:
            risks.append(RiskPoint.model_validate(d))
        except ValidationError:
            continue
    # Fix 4: 过滤空壳 RiskPoint（tier1 或 improvement 为空）
    risks = [rp for rp in risks if _is_valid_risk_point(rp)]
    if not risks:
        return None
    total_ded = sum(int(r.score_deduction or 0) for r in risks)
    total_ded = min(100, max(0, total_ded))
    score = max(0, min(100, 100 - total_ded))
    return AnalysisReport(
        scene_analysis=SceneAnalysis(
            scene_type="（模型 JSON 被 API 截断，已抢救部分风险点）",
            speaker_roles="请结合录音与审查台人工复核",
        ),
        total_score=score,
        total_score_deduction_reason=(
            "（输出被长度截断，系统已丢弃未完成片段；建议缩短上下文或重试）"
        ),
        risk_points=risks,
    )


def _salvage_analysis_report_from_truncated_json(raw: str) -> AnalysisReport | None:
    return salvage_truncated_analysis_report(raw)


def _salvage_risk_scan_result(raw: str, original_error: Exception) -> RiskScanResult | None:
    """
    阶段一 JSON 截断时的最大努力抢救：
    1. 尝试从已截断的 JSON 中解析 scene_analysis；
    2. 成功时返回含空 targets 的 RiskScanResult（总比崩溃好）；
    3. 解析失败返回 None，由调用方决定是否抛异常。
    """
    if not (raw or "").strip():
        return None
    # 先尝试完整解析（带 try 双保险）
    try:
        return RiskScanResult.model_validate_json(raw)
    except Exception:
        pass
    # 从截断 JSON 中提取 scene_analysis
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 逆向裁剪至最后合法 `}`
        for i in range(len(raw) - 1, -1, -1):
            if raw[i] == "}":
                try:
                    data = json.loads(raw[: i + 1])
                    break
                except json.JSONDecodeError:
                    continue
        else:
            return None
    if not isinstance(data, dict):
        return None
    sa_raw = data.get("scene_analysis")
    if not isinstance(sa_raw, dict):
        return None
    try:
        sa = SceneAnalysis.model_validate(sa_raw)
    except (ValidationError, Exception):
        return None
    targets_raw = data.get("targets") or []
    valid_targets: list[RiskTargetCandidate] = []
    if isinstance(targets_raw, list):
        for item in targets_raw:
            try:
                valid_targets.append(RiskTargetCandidate.model_validate(item))
            except (ValidationError, Exception):
                continue
    return RiskScanResult(scene_analysis=sa, targets=valid_targets)


def _validation_suggests_truncated_json(e: ValidationError) -> bool:
    for err in e.errors():
        if err.get("type") == "json_invalid":
            ctx = err.get("ctx") or {}
            je = ctx.get("error")
            if je is not None:
                m = str(je).lower()
                if "eof" in m or "unterminated" in m or "delimiter" in m:
                    return True
    msg = str(e).lower()
    return "eof" in msg or "invalid json" in msg

