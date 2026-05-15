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

from cangjie_fos.engine.coach.llm_judge._evaluation import _make_client
from cangjie_fos.engine.coach.llm_judge._config import MAX_COMPLETION_TOKENS_BY_MODEL, JUDGE_MODEL_KEYS
from cangjie_fos.engine.coach.llm_judge._prompts import _normalize_explicit_context

def refine_risk_point(
    rp_dict: dict[str, Any],
    words: List[TranscriptionWord],
    *,
    model_choice: str = "deepseek",
    explicit_context: dict[str, Any] | None = None,
    qa_text: str = "",
    refinement_note: str = "",
) -> RiskPoint:
    """
    局部精炼：对单个风险点调用 LLM 深度重写。
    提取该条目对应的词段作为上下文，注入主理人批示意见，返回精炼后的 RiskPoint。
    词级索引（start/end_word_index）在 prompt 中要求 LLM 保持一致。
    """
    if model_choice not in JUDGE_MODEL_KEYS:
        raise ValueError('model_choice 必须是 "deepseek"、"kimi" 或 "qwen"')
    ctx = _normalize_explicit_context(explicit_context)
    sw = int(rp_dict.get("start_word_index", 0))
    ew = int(rp_dict.get("end_word_index", 0))

    # 提取对应词段（向前后各扩 5 词作上下文）
    n = len(words)
    seg_start = max(0, sw - 5)
    seg_end = min(n - 1, ew + 5)
    segment_words = words[seg_start: seg_end + 1]
    segment_text = " ".join(f"[{w.word_index}]{w.text}" for w in segment_words)

    rp_json_str = json.dumps(rp_dict, ensure_ascii=False, indent=2)
    note_block = (refinement_note or "").strip() or "（无额外批示，请基于逐字稿和 QA 自行深化分析）"
    kb_block = (qa_text or "").strip() or "未提供参考QA知识库。"
    schema_str = json.dumps(RiskPoint.model_json_schema(), ensure_ascii=False)

    system_prompt = f"""你是一位拥有15年一线投行经验的「顶级金牌路演教练」。
主理人对 AI 初稿中的一个风险点不满意，需要你对其进行深度精炼。

<CONTEXT>
业务场景：{ctx["biz_type"]}
双方角色：{ctx["exact_roles"]}
项目名称：{ctx["project_name"]}
被访谈对象：{ctx["interviewee"]}
</CONTEXT>

<KNOWLEDGE_BASE>
{kb_block}
</KNOWLEDGE_BASE>

<TASK>
对以下风险点进行深度精炼。要求：
1. 保持 start_word_index={sw} / end_word_index={ew} 不变（除非主理人明确要求调整）
2. 所有分析必须立足于【发言人】视角
3. improvement_suggestion 必须给出具体话术示范
4. is_manual_entry 必须为 false
5. needs_refinement 必须为 false
6. refinement_note 必须为空字符串 ""
7. 严格按照 JSON Schema 输出单个 RiskPoint 对象
</TASK>

<ORIGINAL_RISK_POINT>
{rp_json_str}
</ORIGINAL_RISK_POINT>

<PRINCIPAL_INSTRUCTION>
{note_block}
</PRINCIPAL_INSTRUCTION>

<JSON_SCHEMA>
{schema_str}
</JSON_SCHEMA>"""

    user_prompt = (
        f"以下是该风险点对应的逐字稿片段（词索引 {seg_start}–{seg_end}）：\n\n{segment_text}\n\n"
        "请输出精炼后的完整 RiskPoint JSON 对象。"
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
            temperature=0.3,
            max_tokens=max_tokens,
        )

    try:
        response = run_with_backoff(
            _chat_once,
            logger=logger,
            operation=f"refine_risk_point ({model_choice})",
        )
    except APIError as e:
        raise RuntimeError(f"精炼 LLM API 失败: {e}") from e

    choice = response.choices[0] if response.choices else None
    if choice is None or not choice.message or choice.message.content is None:
        raise RuntimeError("精炼 LLM 返回空内容")

    raw_json = choice.message.content.strip()
    try:
        rp = RiskPoint.model_validate_json(raw_json)
    except (ValidationError, Exception) as e:
        # 尝试将外层包装剥除（有时 LLM 会套一层 {"risk_point": {...}}）
        try:
            outer = json.loads(raw_json)
            inner = next(
                (v for v in outer.values() if isinstance(v, dict)), outer
            )
            rp = RiskPoint.model_validate(inner)
        except Exception:
            raise ValueError(f"精炼结果不符合 RiskPoint 契约: {e}\n原始: {raw_json[:500]}") from e

    # 确保词索引一致性：若 LLM 偏离，强制修正
    rp = rp.model_copy(update={
        "start_word_index": sw,
        "end_word_index": ew,
        "needs_refinement": False,
        "refinement_note": "",
    })
    return rp


def refine_single_risk_point(
    risk_point_id: str,
    user_instruction: str,
    context_text: str,
    original_suggestion: str,
    *,
    model_choice: str = "deepseek",
    explicit_context: dict[str, Any] | None = None,
    qa_text: str = "",
) -> MagicRefinementResult:
    """
    V9.6「魔法对话框」后端：按业务员微调指令重写单条 improvement_suggestion。
    返回带 risk_point_id 的结构化结果，供前端写回 Session / 草稿。
    """
    if model_choice not in JUDGE_MODEL_KEYS:
        raise ValueError('model_choice 必须是 "deepseek"、"kimi" 或 "qwen"')
    inst = (user_instruction or "").strip()
    if not inst:
        raise ValueError("user_instruction 不能为空")
    rid = (risk_point_id or "").strip() or "unknown"

    # context_text 截断保护：超长时截取头部（约 4000 字），防 token 超限
    _ctx_raw = (context_text or "").strip()
    _ctx_use = _ctx_raw[:4000] if len(_ctx_raw) > 4000 else _ctx_raw
    if len(_ctx_raw) > 4000:
        logger.warning(
            "refine_single_risk_point: context_text 超过 4000 字（实际 %d 字），已截取头部",
            len(_ctx_raw),
        )

    ctx = _normalize_explicit_context(explicit_context)
    kb_block = (qa_text or "").strip() or "未提供参考QA知识库。"
    mini_schema = json.dumps(
        {
            "type": "object",
            "required": ["improvement_suggestion"],
            "properties": {
                "improvement_suggestion": {
                    "type": "string",
                    "description": "按用户指令重写后的完整改进建议正文",
                }
            },
        },
        ensure_ascii=False,
    )

    system_prompt = f"""你是军工/硬科技投资界顶尖 IR 专家。主理人要对一条「改进建议」做局部重写。
仅输出一个 JSON 对象，且必须包含键 improvement_suggestion（字符串）。

<CONTEXT>
业务场景：{ctx["biz_type"]}
双方角色：{ctx["exact_roles"]}
项目：{ctx["project_name"]}
被访谈对象：{ctx["interviewee"]}
</CONTEXT>
<KNOWLEDGE_BASE>
{kb_block}
</KNOWLEDGE_BASE>

<TASK>
1. 严格服从 <USER_INSTRUCTION>，在保留事实与合规的前提下重写建议正文。
2. 遵守私募合规：禁止保本保收益、禁止过度承诺。
3. 可引用 <CONTEXT_TEXT> 中的事实，勿捏造录音中不存在的内容。
</TASK>

JSON 形状约束：
{mini_schema}"""

    user_prompt = (
        f"<ORIGINAL_SUGGESTION>\n{(original_suggestion or '').strip()}\n</ORIGINAL_SUGGESTION>\n\n"
        f"<CONTEXT_TEXT>\n{_ctx_use}\n</CONTEXT_TEXT>\n\n"
        f"<USER_INSTRUCTION>\n{inst}\n</USER_INSTRUCTION>\n\n"
        "请仅输出 JSON。"
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
            temperature=0.35,
            max_tokens=max_tokens,
        )

    try:
        response = run_with_backoff(
            _chat_once,
            logger=logger,
            operation=f"refine_single_risk_point ({model_choice})",
        )
    except APIError as e:
        raise RuntimeError(f"魔法对话框 LLM API 失败: {e}") from e

    choice = response.choices[0] if response.choices else None
    if choice is None or not choice.message or choice.message.content is None:
        raise RuntimeError("魔法对话框 LLM 返回空内容")

    raw_json = choice.message.content.strip()
    try:
        data = json.loads(raw_json)
        if not isinstance(data, dict):
            raise ValueError("根须为对象")
        inner = next((v for v in data.values() if isinstance(v, dict)), data)
        sug = str(inner.get("improvement_suggestion", "")).strip()
        if not sug:
            raise ValueError("improvement_suggestion 为空")
        return MagicRefinementResult(risk_point_id=rid, improvement_suggestion=sug)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise ValueError(f"魔法对话框 JSON 无效: {e}\n原始: {raw_json[:800]}") from e


def polish_manual_risk_point(
    raw_description: str,
    *,
    model_choice: str = "deepseek",
    explicit_context: dict[str, Any] | None = None,
    qa_text: str = "",
) -> RiskPoint:
    """
    AI 润色：将主理人的原始文字描述结构化为标准 RiskPoint 格式并插入报告。
    返回的 RiskPoint 中 is_manual_entry=True、start/end_word_index=0。
    """
    desc = (raw_description or "").strip()
    if not desc:
        raise ValueError("描述不能为空，请填写至少一句话再调用 LLM 润色。")
    if model_choice not in JUDGE_MODEL_KEYS:
        raise ValueError('model_choice 必须是 "deepseek"、"kimi" 或 "qwen"')

    ctx = _normalize_explicit_context(explicit_context)
    kb_block = (qa_text or "").strip() or "未提供参考QA知识库。"
    schema_str = json.dumps(RiskPoint.model_json_schema(), ensure_ascii=False)

    system_prompt = f"""你是一位拥有15年一线投行经验的「顶级金牌路演教练」。
主理人手动输入了一段观察，请将其结构化为标准的风险点分析格式。

<CONTEXT>
业务场景：{ctx["biz_type"]}
双方角色：{ctx["exact_roles"]}
项目名称：{ctx["project_name"]}
被访谈对象：{ctx["interviewee"]}
</CONTEXT>

<KNOWLEDGE_BASE>
{kb_block}
</KNOWLEDGE_BASE>

<TASK>
将主理人的原始观察扩写为完整的 RiskPoint 分析。要求：
1. is_manual_entry 必须为 true（这是人工标记的遗漏点，无词级音频切片）
2. start_word_index 和 end_word_index 均必须为 0
3. needs_refinement 必须为 false
4. refinement_note 必须为空字符串 ""
5. 在 improvement_suggestion 中给出具体话术示范
6. 根据分析严重程度合理设置 risk_level 与 score_deduction
7. 坚守合规底线，严禁过度承诺
8. 严格按照 JSON Schema 输出单个 RiskPoint 对象
</TASK>

<JSON_SCHEMA>
{schema_str}
</JSON_SCHEMA>"""

    user_prompt = f"以下是主理人的原始观察，请将其结构化：\n\n{desc}"

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
            temperature=0.3,
            max_tokens=max_tokens,
        )

    try:
        response = run_with_backoff(
            _chat_once,
            logger=logger,
            operation=f"polish_manual_risk_point ({model_choice})",
        )
    except APIError as e:
        raise RuntimeError(f"润色 LLM API 失败: {e}") from e

    choice = response.choices[0] if response.choices else None
    if choice is None or not choice.message or choice.message.content is None:
        raise RuntimeError("润色 LLM 返回空内容")

    raw_json = choice.message.content.strip()
    try:
        rp = RiskPoint.model_validate_json(raw_json)
    except (ValidationError, Exception) as e:
        try:
            outer = json.loads(raw_json)
            inner = next(
                (v for v in outer.values() if isinstance(v, dict)), outer
            )
            rp = RiskPoint.model_validate(inner)
        except Exception:
            raise ValueError(f"润色结果不符合 RiskPoint 契约: {e}\n原始: {raw_json[:500]}") from e

    # 强制人工条目标记
    rp = rp.model_copy(update={
        "is_manual_entry": True,
        "start_word_index": 0,
        "end_word_index": 0,
        "needs_refinement": False,
        "refinement_note": "",
    })
    return rp


