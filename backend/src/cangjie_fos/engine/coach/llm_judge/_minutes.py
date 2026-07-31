"""通用会议纪要 LLM 分析（非路演场景）。

复刻 _roadshow.run_roadshow_intel_analysis 的结构：格式化转写 → 注入
MeetingMinutesReport 的 JSON Schema → 调用模型 → 校验 → 兜底最小报告。
与路演情报的区别只在 prompt 和输出 schema：这里产出「会议纪要」而非「投资人情报」。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from openai import APIError
from pydantic import ValidationError

from cangjie_fos.engine.retry_policy import run_with_backoff
from cangjie_fos.engine.schema import MeetingMinutesReport
from cangjie_fos.engine.coach.llm_judge._evaluation import _make_client
from cangjie_fos.engine.coach.llm_judge._prompts import _normalize_explicit_context
from cangjie_fos.engine.coach.llm_judge._config import (
    JUDGE_MODEL_KEYS,
    MAX_COMPLETION_TOKENS_BY_MODEL,
    MAX_TRANSCRIPT_CHARS,
)

logger = logging.getLogger(__name__)


def run_meeting_minutes_analysis(
    words: list[Any],
    *,
    model_choice: str = "deepseek",
    explicit_context: dict[str, Any] | None = None,
    on_notice: Callable[[str], None] | None = None,
) -> MeetingMinutesReport:
    """通用会议纪要分析：把会议录音转写提炼成结构化纪要。

    适用于 category == '06_通用会议纪要' 的场景（高管访谈 / 内部会 / 客户会）。
    """
    if model_choice not in JUDGE_MODEL_KEYS:
        raise ValueError('model_choice 必须是 "deepseek"、"kimi" 或 "qwen"')

    ctx = _normalize_explicit_context(explicit_context)

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
        logger.warning("会议纪要分析：转写超过上限，已截取")

    meeting_title = ctx.get("recording_label") or ctx.get("interviewee") or "会议"
    schema_str = json.dumps(MeetingMinutesReport.model_json_schema(), ensure_ascii=False)

    system_prompt = f"""你是一位资深的会议纪要秘书，擅长把冗长的会议录音提炼成条理清晰的结构化纪要。

你的任务是从以下会议（高管访谈 / 内部会 / 客户沟通会等）的转写稿中，**整理出结构化会议纪要**——不评判发言好坏，不做投资人情报分析，只做纪要秘书的工作。

<MEETING_CONTEXT>
会议标题：{meeting_title}
参会背景：{ctx.get("session_notes") or "无额外备注"}
</MEETING_CONTEXT>

<TASK>
1. meeting_title: 会议主题（若上下文已给出，沿用；否则根据内容概括）
2. attendees: 参会人（能从转写中识别就填，识别不到留空数组，不要编造）
3. summary: 150字内整体纪要（讨论了什么、达成了什么、下一步是什么）
4. key_points: 讨论要点，按主题归纳，每条一句话，最多12条
5. decisions: 会上明确达成的决议/结论，每条一句话，最多8条
6. action_items: 待办行动项，每条含：
   - source: commitment（会上明确承诺的）或 suggestion（建议跟进的）
   - actor: 负责人（我方/对方/具体人名，识别不到填"待定"）
   - action: 行动描述，50字内
   - priority: urgent/normal/optional
7. open_questions: 未解决/待跟进的遗留问题，每条30字内，最多6条

重要原则：
- 忠于转写内容，禁止编造未出现的事实
- 若转写中没有明确内容，相关字段输出空数组
- 仅输出符合 JSON Schema 的单个对象
</TASK>

<JSON_SCHEMA>
{schema_str}
</JSON_SCHEMA>"""

    user_prompt = (
        f"以下是本场会议的转写稿（说话人ID前置）：\n\n{transcript}\n\n"
        "请输出 MeetingMinutesReport JSON 对象。"
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
            operation=f"meeting_minutes_analysis ({model_choice})",
        )
    except APIError as e:
        raise RuntimeError(f"会议纪要分析 LLM API 失败: {e}") from e

    choice = response.choices[0] if response.choices else None
    if choice is None or not choice.message or choice.message.content is None:
        raise RuntimeError("会议纪要分析 LLM 返回空内容")

    raw_json = choice.message.content.strip()
    try:
        report = MeetingMinutesReport.model_validate_json(raw_json)
    except (ValidationError, Exception) as e:  # noqa: BLE001
        try:
            outer = json.loads(raw_json)
            inner = next((v for v in outer.values() if isinstance(v, dict)), outer)
            report = MeetingMinutesReport.model_validate(inner)
        except Exception as e2:  # noqa: BLE001
            logger.error("MeetingMinutesReport 解析失败: %s\n原始: %s", e2, raw_json[:2000])
            report = MeetingMinutesReport(
                meeting_title=meeting_title,
                summary=f"AI 解析失败，请人工查看转写稿。原因：{e2}",
            )
            if callable(on_notice):
                try:
                    on_notice("⚠️ 会议纪要分析 JSON 解析失败，已生成最小纪要，建议手动补充。")
                except Exception:  # noqa: BLE001
                    pass

    logger.info(
        "meeting_minutes_analysis 完成 model=%s key_points=%d decisions=%d actions=%d",
        model_name,
        len(report.key_points),
        len(report.decisions),
        len(report.action_items),
    )
    return report
