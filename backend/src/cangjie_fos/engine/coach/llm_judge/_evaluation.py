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

from cangjie_fos.engine.coach.llm_judge._config import truncate_qa_text, truncate_company_background, MAX_TRANSCRIPT_CHARS, MAX_QA_CHARS, MAX_COMPLETION_TOKENS_BY_MODEL, JUDGE_MODEL_KEYS, ROUTER
from cangjie_fos.engine.coach.llm_judge._prompts import _build_system_prompt, _build_risk_scan_system_prompt, _build_deep_single_risk_system_prompt, _clamp_word_span, format_transcript_for_llm
from cangjie_fos.engine.coach.llm_judge._salvage import _salvage_risk_scan_result, _is_valid_risk_point

logger = logging.getLogger(__name__)

def _make_client(model_key: str) -> tuple[OpenAI, str]:
    if model_key not in ROUTER:
        raise ValueError(f"未知模型键: {model_key}，应为 deepseek / kimi / qwen")
    cfg = ROUTER[model_key]
    api_key = os.getenv(cfg["api_key_env"])
    if not api_key:
        raise ValueError(f"未设置环境变量 {cfg['api_key_env']}")
    client = OpenAI(
        base_url=cfg["base_url"],
        api_key=api_key,
    )
    return client, cfg["model"]


def _compose_total_deduction_reason(risk_points: list[RiskPoint], total_ded: int) -> str:
    if not risk_points:
        return "未发现显著风险点，未执行扣分。"
    return (
        f"共 {len(risk_points)} 个风险点，合计扣分 {total_ded} 分；"
        "各条目依据见 deduction_reason。"
    )


def deep_evaluate_single_risk(
    words: List[TranscriptionWord],
    target: RiskTargetCandidate,
    *,
    model_choice: str = "deepseek",
    explicit_context: dict[str, Any] | None = None,
    qa_text: str = "",
    company_background: str = "",
    historical_memories: list[ExecutiveMemory] | None = None,
    lang_hint: str = "",  # P3.3: 语言指令（英文访谈时非空）
) -> RiskPoint:
    """
    V9.6 阶段二：针对单个靶点调用 LLM，生成完整 RiskPoint（军工 / 硬科技 IR 深评视角）。
    """
    if model_choice not in JUDGE_MODEL_KEYS:
        raise ValueError('model_choice 必须是 "deepseek"、"kimi" 或 "qwen"')
    n = len(words)
    sw = int(target.start_word_index)
    ew = int(target.end_word_index)
    span = _clamp_word_span(sw, ew, n)
    if span is None:
        raise ValueError("词列表为空，无法深评")
    sw, ew = span
    seg_start = max(0, sw - 40)
    seg_end = min(n - 1, ew + 40)
    segment_words = words[seg_start : seg_end + 1]
    segment_text = " ".join(f"[{w.word_index}]{w.text}" for w in segment_words)

    qa_use = (qa_text or "").strip()
    qa_use, _ = truncate_qa_text(qa_use, MAX_QA_CHARS)

    schema_str = json.dumps(RiskPoint.model_json_schema(), ensure_ascii=False)
    system_prompt = _build_deep_single_risk_system_prompt(
        schema_str,
        explicit_context,
        qa_use,
        company_background,
        historical_memories=historical_memories,
    ) + lang_hint  # P3.3: 英文访谈时追加语言指令

    target_json = json.dumps(
        {
            "start_word_index": sw,
            "end_word_index": ew,
            "problem_description": target.problem_description,
            "risk_type": target.risk_type,
        },
        ensure_ascii=False,
    )
    _user_risk_prefix = (
        "[RISK TARGET]\n" if lang_hint else "【风险靶点】\n"
    )
    _user_transcript_label = (
        "Surrounding transcript segment (with [index] anchors):\n\n"
        if lang_hint
        else "以下是该靶点周边的转写片段（含 [索引] 词锚）：\n\n"
    )
    _user_output_instruction = (
        "Output a single RiskPoint JSON object."
        if lang_hint
        else "请输出单个 RiskPoint JSON 对象。"
    )
    user_prompt = (
        f"{_user_risk_prefix}{target_json}\n\n"
        f"{_user_transcript_label}{segment_text}\n\n"
        f"{_user_output_instruction}"
    )

    client, model_name = _make_client(model_choice)
    max_tokens = MAX_COMPLETION_TOKENS_BY_MODEL.get(model_name, 8192)

    def _chat_once():
        return client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.25,
            max_tokens=max_tokens,
        )

    try:
        response = run_with_backoff(
            _chat_once,
            logger=logger,
            operation=f"deep_evaluate_single_risk ({model_choice})",
        )
    except APIError as e:
        raise RuntimeError(f"深评 LLM API 失败: {e}") from e

    choice = response.choices[0] if response.choices else None
    if choice is None or not choice.message or choice.message.content is None:
        raise RuntimeError("深评 LLM 返回空内容")

    raw_json = choice.message.content.strip()
    try:
        rp = RiskPoint.model_validate_json(raw_json)
    except ValidationError:
        try:
            outer = json.loads(raw_json)
            inner = next((v for v in outer.values() if isinstance(v, dict)), outer)
            rp = RiskPoint.model_validate(inner)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"深评结果不符合 RiskPoint 契约: {e}\n原始: {raw_json[:800]}") from e

    return rp.model_copy(
        update={
            "start_word_index": sw,
            "end_word_index": ew,
            "needs_refinement": False,
            "refinement_note": "",
        }
    )


@dataclass
class PitchEvalContext:
    """两阶段 pitch 评估的共享中间上下文（供 LangGraph 多节点与单函数入口复用）。"""

    words: List[TranscriptionWord]
    transcript: str
    qa_use: str
    bg_use: str
    lang_hint: str
    detected_lang: str
    model_choice: str
    explicit_context: dict[str, Any] | None
    on_notice: Callable[[str], None] | None
    historical_memories: list[ExecutiveMemory] | None
    asset_reference_markdown: str


def prepare_pitch_evaluation_context(
    words: List[TranscriptionWord],
    model_choice: str,
    *,
    explicit_context: dict[str, Any] | None = None,
    qa_text: str = "",
    company_background: str = "",
    on_notice: Callable[[str], None] | None = None,
    historical_memories: list[ExecutiveMemory] | None = None,
    asset_reference_markdown: str = "",
) -> PitchEvalContext:
    if model_choice not in JUDGE_MODEL_KEYS:
        raise ValueError('model_choice 必须是 "deepseek"、"kimi" 或 "qwen"')

    _detected_lang = detect_language_from_words(words)
    _lang_hint = get_language_prompt_hint(_detected_lang)
    if _detected_lang == "en":
        logger.info("evaluate_pitch: 检测到英文访谈，已启用英文响应模式")

    transcript = format_transcript_for_llm(words)
    if not transcript.strip():
        raise ValueError("转写词列表为空，无法评估")

    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS]
        logger.warning(
            "转写已超过 MAX_TRANSCRIPT_CHARS=%d，已截取前缀以稳定上下文",
            MAX_TRANSCRIPT_CHARS,
        )

    qa_use = (qa_text or "").strip()
    qa_use, qa_truncated = truncate_qa_text(qa_use, MAX_QA_CHARS)
    if qa_truncated:
        warn_msg = (
            "⚠️ QA 补充材料字数超载（超过3万字），为防止 AI 崩溃，已截取核心头尾条款"
        )
        logger.warning("%s", warn_msg)
        if callable(on_notice):
            try:
                on_notice(warn_msg)
            except Exception as e:
                logger.exception("on_notice 回调失败: %s", e)

    bg_use, _ = truncate_company_background(company_background or "")
    asset_ref = (asset_reference_markdown or "").strip()
    if len(asset_ref) > 1200:
        asset_ref = asset_ref[:1200] + "…"

    return PitchEvalContext(
        words=words,
        transcript=transcript,
        qa_use=qa_use,
        bg_use=bg_use,
        lang_hint=_lang_hint,
        detected_lang=_detected_lang,
        model_choice=model_choice,
        explicit_context=explicit_context,
        on_notice=on_notice,
        historical_memories=historical_memories,
        asset_reference_markdown=asset_ref,
    )


def run_phase1_risk_scan(ctx: PitchEvalContext) -> tuple[RiskScanResult, bool]:
    _stage1_truncated = False
    scan_schema = json.dumps(RiskScanResult.model_json_schema(), ensure_ascii=False)
    _qa_for_scan = (ctx.qa_use or "").strip()
    if ctx.asset_reference_markdown:
        _qa_for_scan = (
            (_qa_for_scan + "\n\n" if _qa_for_scan else "")
            + "以下为库中现有参考资产（仅作核实线索，禁止捏造不存在事实）：\n"
            + ctx.asset_reference_markdown
        )
    scan_system = _build_risk_scan_system_prompt(
        scan_schema,
        ctx.explicit_context,
        _qa_for_scan,
        ctx.bg_use,
        historical_memories=ctx.historical_memories,
    ) + ctx.lang_hint

    _scan_user_prefix = (
        "The following is the interview transcript (each word prefixed with [index]):\n\n"
        if ctx.detected_lang == "en"
        else "以下是本场沟通转写（每个词前有 [索引]，targets 中索引必须来自这些锚点）：\n\n"
    )
    scan_user = _scan_user_prefix + ctx.transcript

    client, model_name = _make_client(ctx.model_choice)
    max_tokens = MAX_COMPLETION_TOKENS_BY_MODEL.get(model_name, 8192)

    logger.info(
        "V9.6 两阶段评估: scan router_key=%s model=%s 词数=%d",
        ctx.model_choice,
        model_name,
        len(ctx.words),
    )

    t_api0 = time.monotonic()

    def _scan_chat():
        return client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": scan_system},
                {"role": "user", "content": scan_user},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=max_tokens,
        )

    try:
        scan_resp = run_with_backoff(
            _scan_chat,
            logger=logger,
            operation=f"risk_scan ({ctx.model_choice})",
        )
    except APIError as e:
        logger.exception("阶段一扫描 API 失败")
        raise RuntimeError(f"LLM API 请求失败: {e}") from e
    except (RuntimeError, ValueError, OSError) as e:
        logger.exception("阶段一扫描异常")
        raise RuntimeError(f"LLM 调用异常: {e}") from e

    logger.info(
        "阶段一 scan 成功 model=%s 耗时=%.2fs",
        model_name,
        time.monotonic() - t_api0,
    )

    sch = scan_resp.choices[0] if scan_resp.choices else None
    if sch is None or not sch.message or sch.message.content is None:
        raise RuntimeError("阶段一 LLM 返回空内容")

    raw_scan = sch.message.content.strip()
    try:
        scan = RiskScanResult.model_validate_json(raw_scan)
    except (ValidationError, Exception) as e:
        scan = _salvage_risk_scan_result(raw_scan, e)
        if scan is None:
            logger.error("RiskScanResult 无法抢救: %s\n原始: %s", e, raw_scan[:2000])
            raise ValueError(f"模型输出不符合 RiskScanResult 契约: {e}") from e
        warn_msg = "⚠️ 阶段一扫描结果 JSON 被截断，已抢救 scene_analysis，靶点列表可能不完整。"
        logger.warning(warn_msg)
        _stage1_truncated = True
        if callable(ctx.on_notice):
            try:
                ctx.on_notice(warn_msg)
            except Exception as e:
                logger.warning("on_notice 回调失败: %s", e)

    return scan, _stage1_truncated


def run_phase2_deep_eval_and_assemble_report(
    ctx: PitchEvalContext,
    scan: RiskScanResult,
    stage1_truncated: bool,
) -> AnalysisReport:
    n_words = len(ctx.words)

    valid_targets: list[tuple[int, RiskTargetCandidate]] = []
    for i, t in enumerate(scan.targets):
        span = _clamp_word_span(t.start_word_index, t.end_word_index, n_words)
        if span is None:
            continue
        sw, ew = span
        valid_targets.append(
            (
                i,
                RiskTargetCandidate(
                    start_word_index=sw,
                    end_word_index=ew,
                    problem_description=t.problem_description,
                    risk_type=t.risk_type,
                ),
            )
        )

    max_workers = min(len(valid_targets), 6) if valid_targets else 1
    results: dict[int, RiskPoint] = {}

    def _eval_one(idx: int, tc: RiskTargetCandidate) -> tuple[int, RiskPoint | None]:
        try:
            rp = deep_evaluate_single_risk(
                ctx.words,
                tc,
                model_choice=ctx.model_choice,
                explicit_context=ctx.explicit_context,
                qa_text=ctx.qa_use,
                company_background=ctx.bg_use,
                historical_memories=ctx.historical_memories,
                lang_hint=ctx.lang_hint,
            )
            return idx, rp
        except (RuntimeError, ValueError, json.JSONDecodeError, KeyError, TypeError) as e:
            logger.exception("靶点 %d 深评失败: %s，已跳过", idx, e)
            return idx, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_eval_one, idx, tc): idx for idx, tc in valid_targets}
        for future in as_completed(futures):
            idx, rp = future.result()
            if rp is not None:
                results[idx] = rp

    risk_points: list[RiskPoint] = [results[idx] for idx in sorted(results.keys())]

    total_ded = sum(int(r.score_deduction or 0) for r in risk_points)
    total_ded = min(100, max(0, total_ded))
    score = max(0, min(100, 100 - total_ded))
    reason = _compose_total_deduction_reason(risk_points, total_ded)

    report = AnalysisReport(
        scene_analysis=scan.scene_analysis,
        total_score=score,
        total_score_deduction_reason=reason,
        positive_highlights=list(getattr(scan, "highlights", None) or []),
        risk_points=risk_points,
    )

    if stage1_truncated:
        _note = "⚠️【阶段一扫描被截断】风险点列表可能不完整，建议重试或缩短录音。"
        _existing = (report.total_score_deduction_reason or "").strip()
        report = report.model_copy(
            update={"total_score_deduction_reason": (_note + " " + _existing).strip()}
        )

    return report


def evaluate_pitch(
    words: List[TranscriptionWord],
    model_choice: str = "deepseek",
    *,
    explicit_context: dict[str, Any] | None = None,
    qa_text: str = "",
    company_background: str = "",
    on_notice: Callable[[str], None] | None = None,
    historical_memories: list[ExecutiveMemory] | None = None,
) -> AnalysisReport:
    """
    V9.6：两阶段评估 — 先 scan_risk_targets（找靶子），再对每靶点 deep_evaluate_single_risk（单点爆破）。
    explicit_context 建议包含：biz_type, exact_roles, project_name, interviewee；
    可选 session_notes（本段备注）、recording_label（录音文件名标识）。
    """
    ctx = prepare_pitch_evaluation_context(
        words,
        model_choice,
        explicit_context=explicit_context,
        qa_text=qa_text,
        company_background=company_background,
        on_notice=on_notice,
        historical_memories=historical_memories,
    )
    scan, stage1_truncated = run_phase1_risk_scan(ctx)
    return run_phase2_deep_eval_and_assemble_report(ctx, scan, stage1_truncated)

