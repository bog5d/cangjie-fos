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
from cangjie_fos.engine.coach.llm_judge._config import MAX_COMPLETION_TOKENS_BY_MODEL


def distill_executive_memory_from_diff(
    original: str,
    refined: str,
    tag: str,
) -> ExecutiveMemory:
    """
    V8.6 / V8.6.1：对比改写前后文本，提炼可复用的「易错要点 + 标准口径」写入错题本。
    **固定走 DeepSeek**（`deepseek-chat`），与主评委同一底座；调用方须已通过防噪门。
    """
    o = (original or "").strip()
    r = (refined or "").strip()
    cap = 12_000
    if len(o) > cap:
        o = o[:cap] + "…"
    if len(r) > cap:
        r = r[:cap] + "…"
    tg = (tag or "").strip() or "default"

    distill_schema = json.dumps(
        {
            "type": "object",
            "required": ["raw_text", "correction"],
            "properties": {
                "raw_text": {
                    "type": "string",
                    "description": "用一句话概括原表述中的踩坑点或不当口径（非逐字抄录）",
                },
                "correction": {
                    "type": "string",
                    "description": "业务逻辑层面的纠正建议或高管应遵循的表述偏好/黄金口径",
                },
                "weight": {
                    "type": "number",
                    "description": "重要性 0~5，默认 1",
                },
            },
        },
        ensure_ascii=False,
    )

    system_prompt = f"""你是投后复盘与高管表达教练。主理人刚完成一段「AI 改写或人工深度修订」。
请从「业务逻辑与沟通策略」角度提炼一条可复用记忆，用于未来同场景预防。

要求：
1. raw_text：概括**原表述的问题类型或错误倾向**（不要逐字复制长文，不超过 200 字）。
2. correction：给出**应遵循的口径、结构或偏好**（可含简短示例句式，不超过 300 字）。
3. weight：0~5 的浮点数，越重要越高，默认 1.0。
4. 忽略纯错别字、标点或无关痛痒的润色；聚焦业务与话术逻辑。
5. 仅输出一个 JSON 对象，键为 raw_text、correction、weight。

JSON 形状约束：
{distill_schema}"""

    user_prompt = (
        f"高管/标签上下文：{tg}\n\n"
        f"<BEFORE>\n{o}\n</BEFORE>\n\n"
        f"<AFTER>\n{r}\n</AFTER>\n\n"
        "请输出 JSON。"
    )

    client, model_name = _make_client("deepseek")
    max_tokens = MAX_COMPLETION_TOKENS_BY_MODEL.get(model_name, 8192)

    def _chat_once():
        return client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=max_tokens,
        )

    try:
        response = run_with_backoff(
            _chat_once,
            logger=logger,
            operation="distill_executive_memory_from_diff (deepseek)",
        )
    except APIError as e:
        raise RuntimeError(f"记忆提炼 LLM API 失败: {e}") from e

    choice = response.choices[0] if response.choices else None
    if choice is None or not choice.message or choice.message.content is None:
        raise RuntimeError("记忆提炼 LLM 返回空内容")

    raw_json = choice.message.content.strip()
    try:
        data = json.loads(raw_json)
        if not isinstance(data, dict):
            raise ValueError("根节点须为对象")
        inner = next((v for v in data.values() if isinstance(v, dict)), data)
        raw_text = str(inner.get("raw_text", "")).strip()
        correction = str(inner.get("correction", "")).strip()
        if not raw_text or not correction:
            raise ValueError("raw_text/correction 不能为空")
        w = float(inner.get("weight", 1.0))
        w = max(0.0, min(5.0, w))
        return ExecutiveMemory(tag=tg, raw_text=raw_text, correction=correction, weight=w)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise ValueError(f"记忆提炼 JSON 无效: {e}\n原始: {raw_json[:800]}") from e


def load_transcription_words(path: Path) -> List[TranscriptionWord]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"JSON 根节点必须是数组: {path}")
    out: List[TranscriptionWord] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"第 {i} 项不是对象")
        out.append(TranscriptionWord.model_validate(item))
    return out


