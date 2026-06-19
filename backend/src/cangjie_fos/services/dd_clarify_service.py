"""解析后人类在环（HITL）——AI 自检澄清。

工作流位置：清单解析完 → 【本环节】→ 匹配。
  1. 给出解析摘要（共多少条、按大类分布），让人先确认"拆解对不对"。
  2. AI 自检：哪些会影响匹配准确性、但它拿不准的点，生成选择题问人
     （像确认开发需求一样：双主体如何区分？年份口径？某条到底要哪一年？）。
  3. 人回答（可跳过）→ 答案汇总成「人工澄清补充」追加进 session.context_note，
     匹配/精判 prompt 自动吃到（context_note 已是既有注入通道，无需改匹配管线）。

不答就凭现状走；答了更精确。_llm_clarify 可被测试 monkeypatch，全链路无需真实 LLM。
"""
from __future__ import annotations

import json
import logging
import uuid

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry

logger = logging.getLogger(__name__)

_MAX_QUESTIONS = 5


def _load_session(session_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT session_id, context_note, clarify_json FROM dd_match_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def _load_items(session_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT requirement, category FROM dd_match_items WHERE session_id = ? ORDER BY item_no",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def parse_summary(items: list[dict]) -> dict:
    """确定性解析摘要：总数 + 按大类分布（供人确认拆解对不对，零 LLM）。"""
    by_cat: dict[str, int] = {}
    for it in items:
        cat = (it.get("category") or "未分类").strip() or "未分类"
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return {"total": len(items), "by_category": by_cat}


def generate_clarifications(session_id: str) -> dict:
    """生成解析摘要 + AI 自检澄清选择题，落库。返回 {summary, questions}。"""
    session = _load_session(session_id)
    if session is None:
        raise ValueError(f"会话 {session_id} 不存在")
    items = _load_items(session_id)
    summary = parse_summary(items)

    questions = _llm_clarify(items, session.get("context_note") or "")
    # 规整 + 封顶 + 加 id
    norm: list[dict] = []
    for q in questions[:_MAX_QUESTIONS]:
        qt = str(q.get("question", "")).strip()
        opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
        if not qt or len(opts) < 2:
            continue
        norm.append({
            "id": str(uuid.uuid4()),
            "question": qt,
            "options": opts,
            "allow_multi": bool(q.get("allow_multi", False)),
            "answer": "",
        })

    payload = {"summary": summary, "questions": norm}
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_sessions SET clarify_json = ? WHERE session_id = ?",
            (json.dumps(payload, ensure_ascii=False), session_id),
        )
    return payload


def get_clarifications(session_id: str) -> dict | None:
    session = _load_session(session_id)
    if session is None:
        return None
    raw = session.get("clarify_json") or ""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def submit_answers(session_id: str, answers: dict[str, str]) -> dict:
    """回填答案 → 汇总成「人工澄清补充」追加进 context_note。返回 {ok, appended}。

    answers: {question_id: 选中的选项文本（或多选用、分隔）}。
    幂等近似：每次重新生成澄清补充块并替换 context_note 里的旧块。
    """
    session = _load_session(session_id)
    if session is None:
        raise ValueError(f"会话 {session_id} 不存在")
    clar = get_clarifications(session_id) or {"summary": {}, "questions": []}

    answered: list[tuple[str, str]] = []
    for q in clar.get("questions", []):
        a = (answers.get(q["id"]) or "").strip()
        q["answer"] = a
        if a:
            answered.append((q["question"], a))

    appended = _build_clarify_block(answered)
    base = _strip_clarify_block(session.get("context_note") or "")
    new_context = (base + ("\n\n" if base and appended else "") + appended).strip()

    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_sessions SET clarify_json = ?, context_note = ? WHERE session_id = ?",
            (json.dumps(clar, ensure_ascii=False), new_context, session_id),
        )
    return {"ok": True, "answered": len(answered), "appended": appended}


_CLARIFY_MARK = "【人工澄清补充】"


def _build_clarify_block(answered: list[tuple[str, str]]) -> str:
    if not answered:
        return ""
    lines = [_CLARIFY_MARK]
    for q, a in answered:
        lines.append(f"- {q} → {a}")
    return "\n".join(lines)


def _strip_clarify_block(context: str) -> str:
    """移除既有的澄清补充块（重答时替换，不累积）。"""
    idx = context.find(_CLARIFY_MARK)
    return context[:idx].strip() if idx >= 0 else context


def _llm_clarify(items: list[dict], context_note: str) -> list[dict]:
    """AI 自检：对会影响匹配准确性、但拿不准的点生成选择题（可被测试 monkeypatch）。"""
    if not items:
        return []
    req_lines = "\n".join(f"- {it['requirement']}" for it in items[:60])
    prompt = f"""你是尽调材料匹配助手。在开始把下面这些需求项匹配到材料库文件【之前】，
请先自检：有哪些**会影响匹配准确性、但你拿不准、需要先跟人确认**的点？

已知项目背景：{context_note or "（无）"}

需求清单：
{req_lines}

请只针对真正会导致匹配错误的歧义生成澄清问题（如：是否多主体需分开、某条要哪一年/哪一期、
口径定义、近义材料如何区分）。做成**选择题**，每题 2-4 个选项，让人一秒能选。
没有拿不准的就返回空数组。最多 {_MAX_QUESTIONS} 题。

返回 JSON 数组：
[{{"question": "问题", "options": ["选项1","选项2"], "allow_multi": false}}]
只返回 JSON："""

    def _call() -> list:
        client = get_dd_llm_client()
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())

    try:
        items_out = call_with_retry(_call, max_retries=2)
    except Exception as e:  # noqa: BLE001
        logger.warning("澄清问题生成失败（不阻断，按无澄清走）: %s", e)
        return []
    return items_out if isinstance(items_out, list) else []
