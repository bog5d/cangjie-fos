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
from cangjie_fos.engine.coach.llm_judge._prompts import _normalize_explicit_context, format_transcript_for_llm
from cangjie_fos.engine.coach.llm_judge._config import JUDGE_MODEL_KEYS, MAX_COMPLETION_TOKENS_BY_MODEL, MAX_TRANSCRIPT_CHARS

logger = logging.getLogger(__name__)

def run_roadshow_intel_analysis(
    words: list[Any],
    *,
    model_choice: str = "deepseek",
    explicit_context: dict[str, Any] | None = None,
    on_notice: Callable[[str], None] | None = None,
) -> RoadshowIntelReport:
    """
    路演情报分析：不打分、不评判发言好坏，专注提取关键情报。
    适用于 category == '01_机构路演' 的场景。
    """
    if model_choice not in JUDGE_MODEL_KEYS:
        raise ValueError('model_choice 必须是 "deepseek"、"kimi" 或 "qwen"')

    ctx = _normalize_explicit_context(explicit_context)

    # 格式化转写（不超过 80000 字）
    transcript_parts: list[str] = []
    for w in words or []:
        if isinstance(w, dict):
            sid = w.get("speaker_id", "0")
            txt = w.get("text", "")
        else:
            sid = getattr(w, "speaker_id", "0")
            txt = getattr(w, "text", "")
        if txt:
            transcript_parts.append(f"[{sid}] {txt}")
    transcript = "\n".join(transcript_parts)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS]
        logger.warning("路演情报分析：转写超过上限，已截取")

    schema_str = json.dumps(RoadshowIntelReport.model_json_schema(), ensure_ascii=False)

    system_prompt = f"""你是一位拥有15年经验的一级市场情报分析师，专注于LP/GP关系建立和募资情报提取。

你的任务是从以下路演/投资人会议的转写稿中，**提取关键情报**——不打分、不评判发言人好坏，只做情报官的工作。

<MEETING_CONTEXT>
会议标识：{ctx.get("recording_label") or ctx.get("interviewee") or "路演"}
参会背景：{ctx.get("session_notes") or "无额外备注"}
</MEETING_CONTEXT>

<TASK>
1. meeting_atmosphere: 整体氛围（hot/warm/cold）
2. meeting_stage: 沟通阶段（first_contact/deep_discussion/pre_dd/unknown）
3. atmosphere_summary: 100字内总结会议氛围和对方态度
4. key_questions: 提取对方提出的关键问题（最多8条），每条含：
   - speaker_id: 说话人ID（如 A/B/1/2，来自转写标记）
   - verbatim: 问题原话（逐字摘录，不润色）
   - underlying_concern: 问题背后的真实关切（30字内）
   - priority: high/medium/low
5. interest_signals: 兴趣信号（最多10条），每条含：
   - speaker_id: 说话人ID
   - verbatim: 原话摘录（逐字）
   - signal_type: positive/concern/neutral
   - interpretation: 解读（30字内）
6. hidden_concerns: 没有明说但反复出现的话题（最多5条，每条30字内）
7. key_verbatim_moments: 最重要的3-5句原话（用引号包裹，逐字摘录）
8. institution_update: 对机构的了解更新（投资偏好/决策风格/限制条件等，200字内）
9. next_actions: 下一步行动清单，区分commitment（会上承诺的）和suggestion（AI建议的）

重要原则：
- 原话摘录必须100%忠实转写，禁止润色
- 不要评判谁说话好不好
- 只关注"他们说了什么、问了什么、显露了什么信号"
- 若转写中没有明确内容，相关字段输出空数组，不要编造
- 仅输出符合 JSON Schema 的单个对象
</TASK>

<JSON_SCHEMA>
{schema_str}
</JSON_SCHEMA>"""

    user_prompt = f"以下是本场路演/会议的转写稿（说话人ID前置）：\n\n{transcript}\n\n请输出 RoadshowIntelReport JSON 对象。"

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
            operation=f"roadshow_intel_analysis ({model_choice})",
        )
    except APIError as e:
        raise RuntimeError(f"路演情报分析 LLM API 失败: {e}") from e

    choice = response.choices[0] if response.choices else None
    if choice is None or not choice.message or choice.message.content is None:
        raise RuntimeError("路演情报分析 LLM 返回空内容")

    raw_json = choice.message.content.strip()
    try:
        report = RoadshowIntelReport.model_validate_json(raw_json)
    except (ValidationError, Exception) as e:
        try:
            outer = json.loads(raw_json)
            inner = next((v for v in outer.values() if isinstance(v, dict)), outer)
            report = RoadshowIntelReport.model_validate(inner)
        except Exception as e2:
            logger.error("RoadshowIntelReport 解析失败: %s\n原始: %s", e2, raw_json[:2000])
            # 降级：返回一个只有 atmosphere_summary 的最小合法报告
            report = RoadshowIntelReport(
                meeting_atmosphere="warm",
                atmosphere_summary=f"AI 解析失败，请人工查看转写稿。原始输出已记录。原因：{e2}",
            )
            if callable(on_notice):
                try:
                    on_notice("⚠️ 路演情报分析 JSON 解析失败，已生成最小报告，建议手动补充。")
                except Exception:
                    pass

    logger.info(
        "roadshow_intel_analysis 完成 model=%s atmosphere=%s questions=%d signals=%d",
        model_name,
        report.meeting_atmosphere,
        len(report.key_questions),
        len(report.interest_signals),
    )
    return report


def _save_report(path: Path, report: AnalysisReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("已写入: %s", path)
