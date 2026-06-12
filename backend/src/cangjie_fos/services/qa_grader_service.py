"""
需求01·B2 — 答疑 AI 审问·答案评估器。

给定（问题 + 应答要点 + 用户录音转写），评估：
  - 命中要点率（answer_points 覆盖情况）
  - 逻辑漏洞 / 风险表述（借鉴 evaluate_pitch 的 tier1/tier2 论证框架，但独立实现）

answer 评分后由调用方决定是否 upsert 回 qa_question_bank（实战沉淀）。
_llm_grade 可被测试 monkeypatch。
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry
from cangjie_fos.services.fact_guard import numbers_grounded, ungrounded_numbers

logger = logging.getLogger(__name__)


class AnswerGrade(BaseModel):
    score: float = Field(..., description="0-100 综合分")
    hit_points: list[str] = Field(default_factory=list, description="命中的应答要点")
    missed_points: list[str] = Field(default_factory=list, description="遗漏的应答要点")
    logic_flaws: list[str] = Field(default_factory=list, description="逻辑漏洞")
    risk_statements: list[str] = Field(default_factory=list, description="风险表述（可能被投资人抓住）")
    feedback: str = Field("", description="一句话总评")


def grade_answer(question: str, answer_points: list[str], transcript: str) -> dict:
    """评估一次答疑回答。返回 AnswerGrade dict。"""
    if not transcript or not transcript.strip():
        return AnswerGrade(
            score=0.0,
            missed_points=list(answer_points),
            feedback="未检测到有效回答内容。",
        ).model_dump()

    result = _llm_grade(question, answer_points, transcript)

    hit = [str(p) for p in result.get("hit_points", [])]
    missed = [str(p) for p in result.get("missed_points", [])]
    # 命中率兜底：LLM 没给分时按命中比例算
    if "score" in result:
        try:
            score = float(result["score"])
        except (ValueError, TypeError):
            score = _ratio_score(hit, answer_points)
    else:
        score = _ratio_score(hit, answer_points)

    # 事实护栏：反馈里出现的数字必须来自问题/要点/回答本身，
    # 拦截评估器自己推导或编造数字（如把月增 12% 演绎成年化流失 78%）
    sources = (question, "；".join(answer_points), transcript)
    feedback = str(result.get("feedback", ""))
    if not numbers_grounded(feedback, *sources):
        logger.warning("评分护栏：总评含无来源数字，已置空: %s", feedback[:60])
        feedback = ""

    grade = AnswerGrade(
        score=round(max(0.0, min(100.0, score)), 1),
        hit_points=hit,
        missed_points=missed or _infer_missed(hit, answer_points),
        logic_flaws=_drop_ungrounded(result.get("logic_flaws", []), sources, "逻辑漏洞"),
        risk_statements=_drop_ungrounded(result.get("risk_statements", []), sources, "风险表述"),
        feedback=feedback,
    )
    return grade.model_dump()


def _drop_ungrounded(items: list, sources: tuple[str, ...], label: str) -> list[str]:
    """丢弃含「问题/要点/回答中都不存在的数字」的条目。"""
    kept: list[str] = []
    for x in items:
        s = str(x)
        bad = ungrounded_numbers(s, *sources)
        if bad:
            logger.warning("评分护栏：丢弃含无来源数字 %s 的%s: %s", bad, label, s[:60])
            continue
        kept.append(s)
    return kept


def _ratio_score(hit: list[str], answer_points: list[str]) -> float:
    if not answer_points:
        return 60.0 if hit else 0.0
    return len(hit) / len(answer_points) * 100.0


def _infer_missed(hit: list[str], answer_points: list[str]) -> list[str]:
    hit_set = {h.strip() for h in hit}
    return [p for p in answer_points if p.strip() not in hit_set]


def _llm_grade(question: str, answer_points: list[str], transcript: str) -> dict:
    """LLM 评估回答（可被测试 monkeypatch）。"""
    points_text = "\n".join(f"- {p}" for p in answer_points) or "（无预设要点，按常识评估）"
    prompt = f"""你是资深投资人，正在评估创始人对一个尽调问题的口头回答。

【问题】{question}

【合格回答应命中的要点】
{points_text}

【创始人的回答（录音转写）】
{transcript[:5000]}

请评估：
1. 命中了哪些要点 / 遗漏了哪些要点
2. 回答里有无逻辑漏洞
3. 有无「风险表述」（可能被投资人抓住做文章的话）

硬性规则：你的评估里引用的任何数字，必须原样出现在上面的问题、要点或回答中。
禁止自行推导新数字（如年化换算），禁止引用这三处都没有的数据。

返回 JSON：
{{"score": 0到100整数, "hit_points": ["命中要点"], "missed_points": ["遗漏要点"],
  "logic_flaws": ["逻辑漏洞"], "risk_statements": ["风险表述"], "feedback": "一句话总评"}}
只返回 JSON："""

    client = get_dd_llm_client()

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()

    try:
        raw = call_with_retry(_call, max_retries=3)
    except Exception as e:
        logger.error("答案评估 LLM 失败: %s", e)
        return {}

    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        parsed = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        logger.error("答案评估 JSON 解析失败: %s", e)
        return {}
    return parsed if isinstance(parsed, dict) else {}
