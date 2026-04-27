"""Phase 6 A2：路演复盘后抽取机构情报并落盘。"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from typing import Any

from cangjie_fos.schemas.institution import InstitutionProfile, InstitutionThermal, PipelineStage
from cangjie_fos.services.institution_store import get_by_name, upsert_institution

logger = logging.getLogger(__name__)

_VC_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("红杉资本", ("红杉资本", "红杉", "Sequoia", "sequoia")),
    ("高瓴资本", ("高瓴资本", "高瓴", "Hillhouse")),
    ("经纬中国", ("经纬中国", "经纬创投", "经纬")),
    ("真格基金", ("真格基金", "真格")),
    ("蓝驰创投", ("蓝驰创投", "蓝驰")),
]


def _words_to_transcript(words: list[Any] | None) -> str:
    parts: list[str] = []
    for w in words or []:
        if w is None:
            continue
        t = getattr(w, "text", None)
        if t is None and isinstance(w, dict):
            t = w.get("text")
        if t:
            parts.append(str(t))
    return " ".join(parts)


def _infer_stage(transcript: str) -> PipelineStage:
    if re.search(r"term\s*sheet|条款清单|估值条款", transcript, re.I):
        return PipelineStage.TERM_SHEET
    if re.search(r"尽调|dd\b|数据室|due diligence", transcript, re.I):
        return PipelineStage.DD
    if re.search(r"路演|teaser|初次沟通|pitch", transcript, re.I):
        return PipelineStage.PITCHED
    return PipelineStage.TARGETED


def _infer_thermal(transcript: str) -> InstitutionThermal:
    if re.search(r"冷淡|不感兴趣|pass|暂缓", transcript):
        return InstitutionThermal.COLD
    if re.search(r"非常积极|强烈兴趣|hot|推进很快", transcript, re.I):
        return InstitutionThermal.HOT
    return InstitutionThermal.WARM


def _report_bits(report: Any) -> tuple[str, str, str]:
    prefs = ""
    concerns = ""
    summary = ""
    try:
        ph = getattr(report, "positive_highlights", None) or []
        rp = getattr(report, "risk_points", None) or []
        if isinstance(ph, list):
            prefs = "；".join(str(x) for x in ph[:4])
        if isinstance(rp, list):
            concerns = "；".join(str(x) for x in rp[:4])
        summary = (getattr(report, "total_score_deduction_reason", None) or "").strip()
        if not summary and isinstance(rp, list) and rp:
            summary = str(rp[0])[:200]
    except Exception:  # noqa: BLE001
        pass
    return prefs, concerns, summary


def _detect_institution_names(transcript: str) -> list[str]:
    found: list[str] = []
    for canonical, alts in _VC_ALIASES:
        for a in alts:
            if a and a in transcript:
                if canonical not in found:
                    found.append(canonical)
                break
    return found


def _llm_extract(transcript: str, report: Any) -> list[dict[str, Any]] | None:
    key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    prefs, concerns, _ = _report_bits(report)
    prompt = (
        "从路演转写中抽取主要外部投资机构（若有）。若无明确机构名，返回空数组。\n"
        "每项含: name, stage(one of targeted,pitched,dd,term_sheet), "
        "thermal(one of cold,warm,hot), preferences, concerns, ai_summary。\n"
        f"转写摘录（截断）：{transcript[:6000]}\n"
        f"已知复盘要点-亮点：{prefs[:800]}\n疑虑：{concerns[:800]}\n"
        "只输出 JSON 数组，不要 Markdown。"
    )
    try:
        from openai import OpenAI

        if os.getenv("DEEPSEEK_API_KEY"):
            client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
            model = os.getenv("CANGJIE_INSTITUTION_MODEL", "deepseek-chat")
        else:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            model = os.getenv("CANGJIE_INSTITUTION_MODEL", "gpt-4o-mini")
        r = client.chat.completions.create(
            model=model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "你是一级市场情报官，只输出合法 JSON 数组。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200,
        )
        raw = (r.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip("` \n")
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception as e:  # noqa: BLE001
        logger.warning("institution_llm_extract_failed: %s", e)
    return None


def extract_and_persist_institution_intel(
    *,
    tenant_id: str,
    words: list[Any],
    report: Any,
    trace_id: str | None,
    explicit_context: dict[str, Any] | None,
) -> None:
    transcript = _words_to_transcript(words)
    if explicit_context:
        fn = explicit_context.get("filename") or explicit_context.get("name")
        if fn:
            transcript = f"{transcript}\n[文件名提示]{fn}"

    rows = _llm_extract(transcript, report)
    if not rows:
        names = _detect_institution_names(transcript)
        if not names:
            return
        prefs, concerns, summ = _report_bits(report)
        stage = _infer_stage(transcript)
        thermal = _infer_thermal(transcript)
        rows = [
            {
                "name": n,
                "stage": stage.value,
                "thermal": thermal.value,
                "preferences": prefs or "关注业务质量与执行节奏",
                "concerns": concerns or "关注数据一致性与风险披露",
                "ai_summary": summ or f"来自路演情报抽取（{n}）",
            }
            for n in names
        ]

    now = time.time()
    for item in rows[:5]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            stage = PipelineStage(str(item.get("stage") or "pitched"))
        except ValueError:
            stage = _infer_stage(transcript)
        try:
            thermal = InstitutionThermal(str(item.get("thermal") or "warm"))
        except ValueError:
            thermal = _infer_thermal(transcript)
        prefs = str(item.get("preferences") or "")[:2000]
        concerns = str(item.get("concerns") or "")[:2000]
        summ = str(item.get("ai_summary") or "")[:2000]

        existing = get_by_name(tenant_id=tenant_id, name=name)
        iid = existing.institution_id if existing else uuid.uuid4().hex
        upsert_institution(
            InstitutionProfile(
                institution_id=iid,
                tenant_id=tenant_id,
                name=name,
                stage=stage,
                thermal=thermal,
                preferences=prefs,
                concerns=concerns,
                ai_summary=summ,
                updated_at=now,
                source_trace_id=trace_id,
            )
        )
        logger.info("institution_intel_upserted name=%s tenant_id=%s trace=%s", name, tenant_id, trace_id)
