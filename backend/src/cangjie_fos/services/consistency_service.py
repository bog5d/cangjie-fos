"""跨录音口径一致性对比（F1）。

需求来源：多位同事都要"高管访谈 / 路演之间口径对不对得上"——
  - 同一高管对不同机构说的是否一致
  - 不同高管（CTO/CFO）对同一指标说的是否一致
  - 路演讲的数据与 BP/其他场次是否一致

做法（可测、可控、不玄）：
  1. 取最近 N 场已完成录音（路演/访谈）的逐字稿；
  2. 逐场用 LLM 抽取「关于关键指标/事实的声明」——受控主题词表，输出 {topic, statement}；
  3. 按归一化 topic 跨场分组；
  4. 对「≥2 个来源都谈到」的 topic，调 LLM 判断是否口径冲突（可 monkeypatch）；
     LLM 不可用时降级为"全部多来源 topic 列出待人工核对"。

只做"把话放到一起 + 标疑似冲突"，最终判断交给人。不臆造未出现的数据。
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# 受控主题词表：约束 LLM 抽取，避免主题漂移导致分不到组
CANONICAL_TOPICS = [
    "营收", "利润", "毛利率", "客户数", "订单", "融资金额", "估值",
    "市场规模", "增长率", "技术路线", "团队规模", "上市计划", "竞争壁垒",
]


def _job_transcript(job: dict) -> str:
    """从 job 行的 words_json 拼出纯文本转写。"""
    words = job.get("words_json") or []
    if isinstance(words, str):
        try:
            words = json.loads(words)
        except Exception:  # noqa: BLE001
            words = []
    parts = []
    for w in words:
        if isinstance(w, dict) and w.get("text"):
            parts.append(str(w["text"]))
    return "".join(parts)


def _source_label(job: dict) -> str:
    """人可读的来源标签：被访谈人/机构（时间）。"""
    who = (job.get("interviewee") or "").strip()
    inst = (job.get("institution_id") or "").strip()
    bits = [b for b in (who, inst) if b and not b.startswith("待确认_")]
    return " · ".join(bits) if bits else (job.get("job_id", "")[:8] or "未知场次")


def _norm_topic(topic: str) -> str:
    """topic 归一化：去空白标点，作为分组 key。"""
    return re.sub(r"[\s　,.，。、；;:：!！?？]+", "", (topic or "")).strip().lower()


def run_consistency_check(
    tenant_id: str,
    *,
    limit: int = 8,
    institution_filter: str = "",
) -> dict:
    """跨最近若干场录音做口径一致性对比。

    返回 {
      "checked_sources": [来源标签...],
      "inconsistencies": [{"topic", "entries": [{"source","statement"}], "verdict", "note"}],
      "note": str,
    }
    """
    from cangjie_fos.services.pitch_job_db import db_job_list_for_tenant

    jobs_pairs = db_job_list_for_tenant(tenant_id, limit=max(1, min(int(limit), 30)))
    jobs = [j for _, j in jobs_pairs]
    if institution_filter.strip():
        f = institution_filter.strip()
        jobs = [j for j in jobs if f in (j.get("institution_id") or "")]

    # 收集每场的声明
    # claims_by_topic: {norm_topic: [{"source","statement","topic"}]}
    claims_by_topic: dict[str, list[dict]] = {}
    sources: list[str] = []
    for job in jobs:
        transcript = _job_transcript(job)
        if not transcript.strip():
            continue
        label = _source_label(job)
        sources.append(label)
        try:
            claims = _llm_extract_claims(transcript)
        except Exception as e:  # noqa: BLE001
            logger.warning("口径抽取失败 source=%s: %s", label, e)
            continue
        for c in claims:
            topic = (c.get("topic") or "").strip()
            statement = (c.get("statement") or "").strip()
            if not topic or not statement:
                continue
            claims_by_topic.setdefault(_norm_topic(topic), []).append(
                {"source": label, "statement": statement, "topic": topic}
            )

    if not sources:
        return {"checked_sources": [], "inconsistencies": [],
                "note": "最近没有可对比的录音转写。先上传几场路演/访谈录音再来。"}

    # 找"≥2 个不同来源都谈到"的 topic
    inconsistencies: list[dict] = []
    for _norm, entries in claims_by_topic.items():
        distinct_sources = {e["source"] for e in entries}
        if len(distinct_sources) < 2:
            continue
        topic_disp = entries[0]["topic"]
        statements = [e["statement"] for e in entries]
        try:
            judged = _llm_judge_conflict(topic_disp, statements)
            verdict = "inconsistent" if judged.get("conflict") else "consistent"
            note = str(judged.get("note", ""))
        except Exception as e:  # noqa: BLE001
            logger.warning("口径冲突判定失败 topic=%s: %s（降级为待核对）", topic_disp, e)
            verdict = "review"
            note = "AI 判定不可用，请人工比对"
        # 只把疑似冲突 / 需核对的抛出来（一致的不打扰）
        if verdict in ("inconsistent", "review"):
            inconsistencies.append({
                "topic": topic_disp,
                "entries": entries,
                "verdict": verdict,
                "note": note,
            })

    return {
        "checked_sources": sources,
        "inconsistencies": inconsistencies,
        "note": f"对比了最近 {len(sources)} 场录音的口径。",
    }


def run_bp_consistency_check(
    tenant_id: str,
    bp_text: str,
    *,
    limit: int = 8,
) -> dict:
    """BP 文档 vs 高管访谈 口径一致性比对（吴素实测评为"最有价值"）。

    抽 BP 的关键声明 + 抽最近若干场访谈/路演的声明，按主题交叉比，判三级：
      consistent 一致 / deviation 偏差(方向一致数值有差) / conflict 矛盾(直接冲突)。
    实测能揪出"BP写800万 vs 访谈说8万"这种 100 倍硬矛盾，投资人一追问就崩。

    返回 {bp_topics, checked_interviews, comparisons:[{topic,bp_statement,
          interview_statements,level,note}], hard_conflicts:[...], counts}。
    """
    from cangjie_fos.services.pitch_job_db import db_job_list_for_tenant

    if not (bp_text or "").strip():
        return {"bp_topics": 0, "checked_interviews": [], "comparisons": [],
                "hard_conflicts": [], "counts": {}, "note": "BP 文本为空。"}

    # BP 声明
    try:
        bp_claims = _llm_extract_claims(bp_text)
    except Exception as e:  # noqa: BLE001
        logger.warning("BP 口径抽取失败: %s", e)
        bp_claims = []
    bp_by_topic: dict[str, dict] = {}
    for c in bp_claims:
        topic = (c.get("topic") or "").strip()
        stmt = (c.get("statement") or "").strip()
        if topic and stmt:
            bp_by_topic.setdefault(_norm_topic(topic), {"topic": topic, "statement": stmt})
    if not bp_by_topic:
        return {"bp_topics": 0, "checked_interviews": [], "comparisons": [],
                "hard_conflicts": [], "counts": {},
                "note": "没能从 BP 抽出可比对的关键口径。"}

    # 访谈/路演声明
    jobs = [j for _, j in db_job_list_for_tenant(tenant_id, limit=max(1, min(int(limit), 30)))]
    iv_by_topic: dict[str, list[dict]] = {}
    interviews: list[str] = []
    for job in jobs:
        transcript = _job_transcript(job)
        if not transcript.strip():
            continue
        label = _source_label(job)
        interviews.append(label)
        try:
            claims = _llm_extract_claims(transcript)
        except Exception as e:  # noqa: BLE001
            logger.warning("访谈口径抽取失败 source=%s: %s", label, e)
            continue
        for c in claims:
            topic = (c.get("topic") or "").strip()
            stmt = (c.get("statement") or "").strip()
            if topic and stmt:
                iv_by_topic.setdefault(_norm_topic(topic), []).append(
                    {"source": label, "statement": stmt})

    comparisons: list[dict] = []
    counts = {"consistent": 0, "deviation": 0, "conflict": 0, "review": 0}
    for norm, bp in bp_by_topic.items():
        iv_entries = iv_by_topic.get(norm)
        if not iv_entries:
            continue  # 访谈没提到这个口径 → 无从比对
        iv_stmts = [e["statement"] for e in iv_entries]
        try:
            judged = _llm_judge_bp_vs_interview(bp["topic"], bp["statement"], iv_stmts)
            level = judged.get("level", "review")
            note = str(judged.get("note", ""))
        except Exception as e:  # noqa: BLE001
            logger.warning("BP 口径判定失败 topic=%s: %s", bp["topic"], e)
            level, note = "review", "AI 判定不可用，请人工比对"
        if level not in counts:
            level = "review"
        counts[level] += 1
        comparisons.append({
            "topic": bp["topic"],
            "bp_statement": bp["statement"],
            "interview_statements": iv_entries,
            "level": level,
            "note": note,
        })

    hard = [c for c in comparisons if c["level"] == "conflict"]
    return {
        "bp_topics": len(bp_by_topic),
        "checked_interviews": interviews,
        "comparisons": comparisons,
        "hard_conflicts": hard,
        "counts": counts,
        "note": f"BP {len(bp_by_topic)} 个口径 × 最近 {len(interviews)} 场访谈交叉比对。",
    }


def _llm_judge_bp_vs_interview(topic: str, bp_statement: str, interview_statements: list[str]) -> dict:
    """判 BP 口径与访谈口径的关系（monkeypatch 点）。

    返回 {"level": consistent|deviation|conflict, "note": "一句话点明差异(30字内)"}。
    """
    from cangjie_fos.services.dd_llm_client import call_with_retry, get_dd_llm_client

    ivs = "\n".join(f"- {s}" for s in interview_statements)
    prompt = (
        f"就「{topic}」这个口径，对比 BP 与高管访谈：\n"
        f"BP 的说法：{bp_statement}\n"
        f"访谈里的说法：\n{ivs}\n\n"
        "判断二者关系，只返回 JSON："
        '{"level": "consistent 或 deviation 或 conflict", "note": "如不一致，一句话点明差异(30字内)"}。\n'
        "consistent=完全一致；deviation=方向一致但数值/程度有差；conflict=直接冲突(数字/结论对不上)。"
    )
    client = get_dd_llm_client()

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0,
        )
        return (resp.choices[0].message.content or "{}").strip()

    raw = call_with_retry(_call, max_retries=2)
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {"level": "review", "note": ""}


def _llm_extract_claims(transcript: str) -> list[dict]:
    """从单场转写抽取关于关键指标的声明（monkeypatch 点）。

    返回 [{"topic": 受控主题, "statement": 一句话原意}]，无则空列表。
    """
    from cangjie_fos.services.dd_llm_client import call_with_retry, get_dd_llm_client

    topics = "、".join(CANONICAL_TOPICS)
    truncated = transcript[:6000]
    prompt = (
        "以下是一场路演/高管访谈的逐字稿。请抽取其中**关于下列关键指标/事实的明确声明**：\n"
        f"主题词表（topic 只能取其一）：{topics}\n\n"
        f"逐字稿：\n{truncated}\n\n"
        '以 JSON 数组返回，每项 {"topic": 词表中的一个, "statement": "该场对这个指标说了什么(一句话,含数字)"}。'
        "只抽取转写中真实出现的声明，不要编造；没有就返回 []。只返回 JSON 数组。"
    )
    client = get_dd_llm_client()

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0,
        )
        return (resp.choices[0].message.content or "[]").strip()

    raw = call_with_retry(_call, max_retries=2)
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        items = json.loads(raw.strip())
    except json.JSONDecodeError:
        return []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _llm_judge_conflict(topic: str, statements: list[str]) -> dict:
    """判断同一主题的多条声明是否口径冲突（monkeypatch 点）。

    返回 {"conflict": bool, "note": "冲突点一句话说明"}。
    """
    from cangjie_fos.services.dd_llm_client import call_with_retry, get_dd_llm_client

    joined = "\n".join(f"- {s}" for s in statements)
    prompt = (
        f"以下是不同场次/不同人对「{topic}」的说法：\n{joined}\n\n"
        "判断这些说法之间是否存在**口径不一致/前后矛盾**（数字对不上、结论相反等）。"
        '只返回 JSON：{"conflict": true 或 false, "note": "如冲突，一句话点明冲突在哪(20字内)"}。'
    )
    client = get_dd_llm_client()

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0,
        )
        return (resp.choices[0].message.content or "{}").strip()

    raw = call_with_retry(_call, max_retries=2)
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {"conflict": False, "note": ""}
