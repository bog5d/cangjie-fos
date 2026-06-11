"""
需求01·B1 — 答疑 AI 审问·出题器 + 可复用问题库。

三来源合流：
  1. AI 生成（按 财务/法务/业务/技术/团队/竞争 分组）
  2. 从 qa_question_bank 迁移历史真实问题（跨机构/项目复用）
  3. 实战沉淀回写（grade 后 upsert，hit_count++）

bigram 去重沿用 dd_qa_service 思路，实现「70% 问题重复」的复用率。
_llm_generate_questions 可被测试 monkeypatch。
"""
from __future__ import annotations

import json
import logging
import time
import uuid

from pydantic import BaseModel, Field

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry
from cangjie_fos.services.fact_guard import evidence_found, ungrounded_numbers

logger = logging.getLogger(__name__)

_CATEGORIES = ("财务", "法务", "业务", "技术", "团队", "竞争")
# 与历史问题的 bigram 重合度高于此值视为重复，不再 AI 重出
# 取 0.5 与 dd_qa_service._HIT_THRESHOLD 对齐：中文短问句经停用字过滤后 bigram 稀疏，
# 阈值过高会漏判（"…这么低？" vs "…这么低呀？" 仅 0.57）。
_DEDUP_THRESHOLD = 0.5
_STOP_CHARS = set("的和与或等及请问贵公司你们我们是否有没有如何怎么这个那个")


class Question(BaseModel):
    question_id: str = Field(..., description="问题ID")
    category: str = Field(..., description="分组：财务/法务/业务/技术/团队/竞争")
    question_text: str = Field(..., description="问题正文")
    answer_points: list[str] = Field(default_factory=list, description="应答要点")
    source: str = Field("ai", description="ai/migrated/real")
    evidence: str = Field("", description="材料原句出处（AI 生成题必填，历史题为空）")


def _bigrams(text: str) -> set[str]:
    out: set[str] = set()
    for i in range(len(text) - 1):
        bg = text[i:i + 2]
        if not any(c in _STOP_CHARS for c in bg):
            out.add(bg)
    return out


def _similarity(a: str, b: str) -> float:
    """bigram Jaccard 相似度。"""
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def generate_questions(
    material: str,
    tenant_id: str = "default",
    sector: str = "",
    round_stage: str = "",
    limit: int = 12,
) -> list[dict]:
    """生成压力测试问题清单（历史迁移优先 + AI 补足，去重）。

    返回 [{question_id, category, question_text, answer_points, source}, ...]
    """
    # 1) 历史迁移：同赛道/阶段的高频问题优先
    migrated = _migrate_history(tenant_id, sector, round_stage, limit)

    # 2) AI 生成补足
    ai_items = _llm_generate_questions(material, sector, round_stage)

    # 3) 合流去重（历史问题优先占位）
    result: list[dict] = list(migrated)
    existing = [q["question_text"] for q in result]
    for item in ai_items:
        qt = item.get("question_text", "").strip()
        if not qt:
            continue
        if any(_similarity(qt, e) >= _DEDUP_THRESHOLD for e in existing):
            continue
        existing.append(qt)
        result.append({
            "question_id": str(uuid.uuid4()),
            "category": item.get("category", "业务"),
            "question_text": qt,
            "answer_points": item.get("answer_points", []),
            "source": "ai",
            "evidence": str(item.get("evidence", "")).strip(),
        })
        if len(result) >= limit:
            break
    return result[:limit]


def _migrate_history(tenant_id: str, sector: str, round_stage: str, limit: int) -> list[dict]:
    """从 qa_question_bank 迁移历史问题（按命中次数降序）。"""
    clauses = ["tenant_id = ?"]
    params: list = [tenant_id]
    if sector:
        clauses.append("sector = ?")
        params.append(sector)
    if round_stage:
        clauses.append("round_stage = ?")
        params.append(round_stage)
    where = " AND ".join(clauses)
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT id, category, question_text, answer_points_json
                FROM qa_question_bank WHERE {where}
                ORDER BY hit_count DESC, created_at DESC LIMIT ?""",
            params,
        ).fetchall()
    return [{
        "question_id": r["id"],
        "category": r["category"],
        "question_text": r["question_text"],
        "answer_points": json.loads(r["answer_points_json"] or "[]"),
        "source": "migrated",
        "evidence": "",
    } for r in rows]


def upsert_question_bank(
    tenant_id: str,
    question_text: str,
    answer_points: list[str],
    category: str = "业务",
    sector: str = "",
    round_stage: str = "",
    source: str = "real",
) -> str:
    """把问题 upsert 进可复用库；已存在相似问题则 hit_count++ 并返回旧 id。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, question_text FROM qa_question_bank WHERE tenant_id = ? AND sector = ?",
            (tenant_id, sector),
        ).fetchall()
        for r in rows:
            if _similarity(question_text, r["question_text"]) >= _DEDUP_THRESHOLD:
                conn.execute(
                    "UPDATE qa_question_bank SET hit_count = hit_count + 1 WHERE id = ?",
                    (r["id"],),
                )
                return r["id"]
        qid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO qa_question_bank
               (id, tenant_id, sector, round_stage, category, question_text,
                answer_points_json, source, hit_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (qid, tenant_id, sector, round_stage, category, question_text,
             json.dumps(answer_points, ensure_ascii=False), source, time.time()),
        )
    return qid


def _llm_generate_questions(material: str, sector: str, round_stage: str) -> list[dict]:
    """LLM 按六大维度生成投资人压力问题（可被测试 monkeypatch）。"""
    client = get_dd_llm_client()
    cats = "、".join(_CATEGORIES)
    prompt = f"""你是资深投资人，正在对一家公司做投前尽调答疑。
赛道：{sector or '未指定'}；融资阶段：{round_stage or '未指定'}。

公司材料摘要：
{material[:6000]}

请按以下维度各提 1-2 个最尖锐、最容易问倒创始人的问题：{cats}。
每个问题给出 2-3 条「合格回答应当命中的要点」。

硬性规则（违反即作废）：
1. 问题和要点里出现的每一个数字，必须原样来自上面的材料。禁止自行推导新数字
   （如用月增长率推算年化），禁止把不同指标的数字互相搬用（如把客户集中度当毛利率）。
2. 每个问题必须带 "evidence" 字段：逐字引用材料中触发该问题的那句原文，不许改写。
   提不出原句出处的问题不要输出。

返回 JSON 数组，每项：
{{"category": "维度", "question_text": "问题", "answer_points": ["要点1","要点2"], "evidence": "材料原句"}}
只返回 JSON 数组："""

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()

    try:
        raw = call_with_retry(_call, max_retries=3)
    except Exception as e:
        logger.error("出题 LLM 失败: %s", e)
        return []

    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        items = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        logger.error("出题 JSON 解析失败: %s", e)
        return []
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items:
        if isinstance(item, dict) and item.get("question_text"):
            cat = str(item.get("category", "业务")).strip()
            out.append({
                "category": cat if cat in _CATEGORIES else "业务",
                "question_text": str(item["question_text"]).strip(),
                "answer_points": [str(p) for p in item.get("answer_points", []) if p],
                "evidence": str(item.get("evidence", "")).strip(),
            })
    return _filter_grounded_questions(out, material)


def _filter_grounded_questions(items: list[dict], material: str) -> list[dict]:
    """事实护栏：丢弃无有效证据、或数字不来自材料的 AI 生成题。

    同事实测发现的两类幻觉都在这里拦：
      - 推导/搬用数字（月增12% → 年化流失78%）→ 数字不在材料里，丢弃
      - 凭空引用 → evidence 不是材料子串，丢弃
    """
    kept: list[dict] = []
    for item in items:
        qt = item.get("question_text", "")
        if not evidence_found(item.get("evidence", ""), material):
            logger.warning("出题护栏：丢弃无有效材料出处的问题: %s", qt[:60])
            continue
        bad = ungrounded_numbers(
            qt + "；" + "；".join(item.get("answer_points") or []), material,
        )
        if bad:
            logger.warning("出题护栏：丢弃含材料中不存在数字 %s 的问题: %s", bad, qt[:60])
            continue
        kept.append(item)
    return kept
