"""
需求01·A2 — 路演要点「覆盖率」打分器（新打分轴）。

与 evaluate_pitch（复盘减分制风险扫描）相反：这里是**正向覆盖率打分** ——
给定 BP 要点清单 + 录音转写，判断每个要点是「讲到 / 弱讲 / 漏讲」，
算出加权覆盖率，并列出漏讲要点 + 改进建议。

确定性优先：时长、语速、字数等可由词级时间戳直接算的指标**绝不喂 LLM**。
LLM 只做不可替代的语义判断（要点是否命中）。
_llm_judge_coverage 可被测试 monkeypatch。
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry

logger = logging.getLogger(__name__)

# 加权覆盖率：core 计 3 分，normal 2 分，minor 1 分；命中给满，弱讲给一半，漏讲 0
_WEIGHT_SCORE = {"core": 3.0, "normal": 2.0, "minor": 1.0}
_HIT_RATIO = {"covered": 1.0, "weak": 0.5, "missed": 0.0}


class CoverageReport(BaseModel):
    coverage_score: float = Field(..., description="加权覆盖率 0-100")
    covered_points: list[dict] = Field(default_factory=list, description="命中要点（含 weak）")
    missed_points: list[dict] = Field(default_factory=list, description="漏讲要点")
    suggestions: list[str] = Field(default_factory=list, description="改进建议")
    duration_sec: float = Field(0.0, description="录音时长(秒)")
    speech_rate: float = Field(0.0, description="语速(字/分钟)")
    word_count: int = Field(0, description="转写字数")


def compute_delivery_metrics(words: list) -> dict:
    """从词级时间戳算确定性指标：时长 / 字数 / 语速（字/分钟）。零 LLM。

    words: list[TranscriptionWord]（或带 start_time/end_time/text 的对象/dict）。
    """
    if not words:
        return {"duration_sec": 0.0, "word_count": 0, "speech_rate": 0.0}

    def _attr(w, name):
        return w.get(name) if isinstance(w, dict) else getattr(w, name, None)

    starts = [float(_attr(w, "start_time") or 0.0) for w in words]
    ends = [float(_attr(w, "end_time") or 0.0) for w in words]
    duration = max(ends) - min(starts) if ends and starts else 0.0
    duration = max(duration, 0.0)

    # 字数：中文按字符计（每个 TranscriptionWord.text 可能是一个字或词）
    char_count = sum(len(str(_attr(w, "text") or "")) for w in words)
    rate = (char_count / duration * 60.0) if duration > 0 else 0.0
    return {
        "duration_sec": round(duration, 2),
        "word_count": char_count,
        "speech_rate": round(rate, 1),
    }


def score_coverage(key_points: list[dict], transcript: str, words: list | None = None) -> dict:
    """对照要点清单与转写文本，输出覆盖率报告 dict。

    key_points: extract_key_points 的输出
    transcript: 录音转写纯文本
    words: 可选词级列表，用于算时长/语速（不传则这些指标为 0）
    """
    metrics = compute_delivery_metrics(words or [])

    if not key_points:
        report = CoverageReport(coverage_score=0.0, **metrics)
        return report.model_dump()

    judgments = _llm_judge_coverage(key_points, transcript)

    covered: list[dict] = []
    missed: list[dict] = []
    earned = 0.0
    total = 0.0
    for kp in key_points:
        weight = kp.get("weight", "normal")
        w = _WEIGHT_SCORE.get(weight, 2.0)
        total += w
        verdict = judgments.get(kp["point_no"], {})
        status = verdict.get("status", "missed")
        if status not in _HIT_RATIO:
            status = "missed"
        earned += w * _HIT_RATIO[status]
        enriched = {**kp, "status": status, "evidence": verdict.get("evidence", "")}
        if status == "missed":
            missed.append(enriched)
        else:
            covered.append(enriched)

    coverage = round(earned / total * 100.0, 1) if total > 0 else 0.0
    suggestions = _build_suggestions(missed)

    report = CoverageReport(
        coverage_score=coverage,
        covered_points=covered,
        missed_points=missed,
        suggestions=suggestions,
        **metrics,
    )
    return report.model_dump()


def _build_suggestions(missed: list[dict]) -> list[str]:
    """漏讲要点 → 改进建议（确定性生成，不耗 LLM）。"""
    out: list[str] = []
    core_missed = [m for m in missed if m.get("weight") == "core"]
    if core_missed:
        names = "、".join(m["point_text"][:20] for m in core_missed[:3])
        out.append(f"⚠️ 漏讲 {len(core_missed)} 个关键要点（如：{names}），投资人最关心的信息没覆盖，务必补上。")
    weak = [m for m in missed if m.get("status") == "weak"]
    if weak:
        out.append(f"有 {len(weak)} 个要点只是一带而过，建议展开讲透，给出数据或案例支撑。")
    if not out and missed:
        out.append(f"还有 {len(missed)} 个次要要点未覆盖，可酌情补充。")
    return out


def _llm_judge_coverage(key_points: list[dict], transcript: str) -> dict:
    """LLM 判断每个要点是 covered/weak/missed（可被测试 monkeypatch）。

    返回 {point_no: {"status": "covered|weak|missed", "evidence": "..."}}
    """
    point_lines = "\n".join(
        f"要点{kp['point_no']}（{kp.get('weight','normal')}）：{kp['point_text']}"
        for kp in key_points
    )
    prompt = f"""你是路演陪练教练。下面是演讲者应当讲到的要点清单，以及他这一遍的录音转写。
请判断每个要点的覆盖情况。

【应讲要点】
{point_lines}

【录音转写】
{transcript[:6000]}

对每个要点判定：
- covered：讲清楚了
- weak：提到了但一带而过/没讲透
- missed：完全没讲

返回 JSON（key 是要点序号）：
{{"要点序号": {{"status": "covered|weak|missed", "evidence": "转写中的依据片段或空"}}}}
只返回 JSON："""

    client = get_dd_llm_client()

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()

    try:
        raw = call_with_retry(_call, max_retries=3)
    except Exception as e:
        logger.error("覆盖率判定 LLM 失败，全部记为 missed: %s", e)
        return {}

    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        parsed = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        logger.error("覆盖率 JSON 解析失败: %s", e)
        return {}
    return parsed if isinstance(parsed, dict) else {}
