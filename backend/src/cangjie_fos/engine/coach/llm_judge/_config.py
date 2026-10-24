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

# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# V7.0：录音转写与 QA 补充材料字数池物理隔离
MAX_TRANSCRIPT_CHARS = 80_000
MAX_QA_CHARS = 30_000
MAX_COMPANY_BG_CHARS = 8_000

# OpenAI 兼容接口 completion 上限（按模型典型能力设安全值，避免默认过小导致 JSON 拦腰截断）
MAX_COMPLETION_TOKENS_BY_MODEL: dict[str, int] = {
    "deepseek-chat": 8192,
    "moonshot-v1-32k": 8192,
    "qwen-max": 8192,
}

MIDDLE_OMIT_MARK = "\n...[内容过长，系统已智能省略中间部分]...\n"


def truncate_qa_text(qa: str, max_chars: int = MAX_QA_CHARS) -> tuple[str, bool]:
    """
    超长 QA 掐头去尾，中间用省略标记连接。
    返回 (处理后文本, 是否发生过截断)；结果长度保证不超过 max_chars。
    """
    q = (qa or "").strip()
    if len(q) <= max_chars:
        return q, False
    m = len(MIDDLE_OMIT_MARK)
    if max_chars <= m:
        return q[:max_chars], True
    inner = max_chars - m
    head_n = inner // 2
    tail_n = inner - head_n
    return q[:head_n] + MIDDLE_OMIT_MARK + q[-tail_n:], True


def truncate_company_background(bg: str, max_chars: int = MAX_COMPANY_BG_CHARS) -> tuple[str, bool]:
    """
    公司背景超出限制时截取头部（优先保留公司核心信息）。
    返回 (处理后文本, 是否发生过截断)。
    """
    b = (bg or "").strip()
    if len(b) <= max_chars:
        return b, False
    return b[:max_chars], True


def detect_logical_conflict(company_background: str, sniper_targets_json: str) -> list[str]:
    """
    检测公司背景与狙击目标之间的潜在逻辑冲突（冲突报警机制）。
    简单关键词重叠检测：若狙击 reason 中长度>4（5 字以上）的词片段出现在背景中，触发警告；总告警数上限 3 条。
    返回警告字符串列表；无冲突或输入为空时返回 []。
    """
    bg = (company_background or "").strip()
    sj = (sniper_targets_json or "").strip()
    if not bg or not sj:
        return []
    try:
        snipers = json.loads(sj)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(snipers, list):
        return []
    warnings: list[str] = []
    for item in snipers:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason", "")).strip()
        if not reason:
            continue
        # 按常见分隔符拆词，取长度 > 4 的片段做关键词（5 字以上才触发，避免通用词 FP）
        fragments = re.split(r"[，,、。.；;\s]+", reason)
        matched_frag: str = ""
        for frag in fragments:
            frag = frag.strip()
            if len(frag) > 4 and frag in bg:
                matched_frag = frag
                break
        # 如果分隔符拆词未命中，进一步用滑动窗口（步长3~8字）查找共现关键词
        if not matched_frag:
            for win in range(5, min(len(reason) + 1, 9)):
                for start in range(0, len(reason) - win + 1):
                    sub = reason[start:start + win]
                    if sub in bg:
                        matched_frag = sub
                        break
                if matched_frag:
                    break
        if matched_frag:
            warnings.append(
                f"潜在冲突：狙击目标「{reason[:30]}」中的关键词「{matched_frag}」出现在公司背景描述中，请确认口径一致性"
            )
    return warnings[:3]


# 三巨头官方兼容 OpenAI 的路由配置
ROUTER: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_env": "KIMI_API_KEY",
        "model": "moonshot-v1-32k",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "model": "qwen-max",
    },
}

# 主评委与错题提炼（V8.6.1 起统一 DeepSeek 通道，不引入第二家闭源底座）
JUDGE_MODEL_KEYS: frozenset[str] = frozenset({"deepseek", "kimi", "qwen"})

DISPLAY_NAME = {
    "deepseek": "DeepSeek-V3 (deepseek-chat)",
    "kimi": "Kimi (Moonshot moonshot-v1-32k)",
    "qwen": "Qwen-Max (DashScope 兼容模式)",
}


def choose_model_with_timeout(timeout: float = 3) -> str:
    """
    终端 3 秒内可选 k / q 切换模型；超时或未输入则默认 deepseek。
    Windows 下 stdin 无法用 select 可靠做超时，故使用「子线程 readline + 主线程 queue.get 超时」。
    """
    t0 = time.monotonic()
    print(
        "默认使用 DeepSeek-V3 评委。你有 3 秒钟时间输入 k (切换Kimi) 或 q (切换Qwen)，按回车确认。"
        "不输入则默认 DeepSeek...",
        flush=True,
    )

    q: queue.Queue[str] = queue.Queue(maxsize=1)

    def _reader() -> None:
        try:
            line = sys.stdin.readline()
        except Exception:
            q.put("deepseek")
            return
        s = (line or "").strip().lower()
        if s.startswith("k"):
            q.put("kimi")
        elif s.startswith("q"):
            q.put("qwen")
        else:
            q.put("deepseek")

    threading.Thread(target=_reader, daemon=True).start()
    try:
        choice = q.get(timeout=timeout)
        logger.debug("choose_model 耗时 %.2fs", time.monotonic() - t0)
        return choice
    except queue.Empty:
        logger.debug("choose_model 超时，默认 deepseek，耗时 %.2fs", time.monotonic() - t0)
        return "deepseek"

