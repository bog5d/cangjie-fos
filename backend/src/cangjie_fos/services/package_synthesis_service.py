"""需求03 — 引导式提问 + AI 合成材料。

对缺失项：
  1. generate_guiding_questions —— 生成引导问题，问用户要私有信息/口述
  2. synthesize_material —— 把用户零碎回答 + 已有片段，整理生成一份规范材料初稿

事实护栏（复用 fact_guard）：合成稿里的数字必须来自用户提供的素材，
杜绝 AI 凭空编造数据（同需求01 实测教训）。

_llm_questions / _llm_synthesize 可被测试 monkeypatch。
"""
from __future__ import annotations

import json
import logging
import time

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry
from cangjie_fos.services.fact_guard import ungrounded_numbers

logger = logging.getLogger(__name__)


def _get_item(item_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM package_items WHERE id = ?", (item_id,),
        ).fetchone()
    return dict(row) if row else None


# 自动喂给合成的「已有材料片段」最大字符数（控制 token）
_AUTO_SNIPPET_CHARS = 1500


def auto_existing_snippets(item: dict) -> str:
    """若该项匹配到了材料库文件，自动取其正文节选作为「已有片段」。

    对「需更新」项尤其关键：旧版材料正文 + 用户口述的新信息 → 合成新版初稿，
    用户不必手动翻旧文件复制粘贴。
    """
    path = item.get("matched_file_path")
    if not path:
        return ""
    with _connect() as conn:
        row = conn.execute(
            "SELECT content_text, filename FROM dd_asset_index WHERE file_path = ?",
            (path,),
        ).fetchone()
    if not row:
        return ""
    content = (row["content_text"] or "").strip()
    if not content:
        return ""
    return f"（来自已有文件《{row['filename']}》）\n{content[:_AUTO_SNIPPET_CHARS]}"


def generate_guiding_questions(requirement: str, category: str = "") -> list[str]:
    """对一个缺失材料项，生成 3-5 个引导问题（向用户索取私有信息）。"""
    questions = _llm_questions(requirement, category)
    # 兜底：LLM 失败时给一个通用引导
    if not questions:
        return [f"关于「{requirement}」，目前有哪些现成信息可以提供？（数据、时间、相关方等）"]
    return questions


def synthesize_material(
    requirement: str,
    fragments: str,
    existing_snippets: str = "",
    category: str = "",
) -> dict:
    """把用户零碎回答 + 已有片段合成一份材料初稿。

    返回 {draft, dropped_numbers}：
      - draft: 合成稿（经事实护栏校验，剔除了无来源数字的句子）
      - dropped_numbers: 被护栏拦下的、素材中不存在的数字（透明告知用户）
    """
    if not fragments.strip() and not existing_snippets.strip():
        return {"draft": "", "dropped_numbers": []}

    draft = _llm_synthesize(requirement, fragments, existing_snippets, category)
    # 事实护栏：合成稿里的数字必须来自素材（用户片段 + 已有片段 + 需求本身）
    sources = (fragments, existing_snippets, requirement)
    guarded, dropped = _guard_numbers(draft, sources)
    return {"draft": guarded, "dropped_numbers": sorted(dropped)}


def _guard_numbers(draft: str, sources: tuple[str, ...]) -> tuple[str, set[str]]:
    """逐句校验：含「素材里不存在数字」的句子整句剔除，返回(净化稿, 被剔数字集合)。"""
    dropped: set[str] = set()
    kept_lines: list[str] = []
    for line in draft.splitlines():
        bad = ungrounded_numbers(line, *sources)
        if bad:
            dropped |= bad
            logger.warning("合成护栏：剔除含无来源数字 %s 的句子: %s", bad, line[:50])
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip(), dropped


def save_fragments(item_id: str, fragments: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE package_items SET user_fragments = ? WHERE id = ?",
            (fragments, item_id),
        )


def save_draft(item_id: str, draft: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE package_items SET draft_answer = ? WHERE id = ?",
            (draft, item_id),
        )


def synthesize_for_item(item_id: str, fragments: str, existing_snippets: str = "") -> dict:
    """端到端：存用户片段 → （自动补已有片段）→ 合成 → 存初稿。返回合成结果。"""
    item = _get_item(item_id)
    if not item:
        raise ValueError(f"package item {item_id} 不存在")
    save_fragments(item_id, fragments)
    snippets = existing_snippets.strip() or auto_existing_snippets(item)
    result = synthesize_material(
        item["requirement"], fragments, snippets, category=item.get("category", ""),
    )
    result["used_existing"] = bool(snippets)
    save_draft(item_id, result["draft"])
    return result


# ── LLM 注入点（测试 monkeypatch）────────────────────────────────────────────

def _llm_questions(requirement: str, category: str) -> list[str]:
    client = get_dd_llm_client()
    prompt = f"""你是融资材料顾问。创始人缺少这份材料：「{requirement}」（属于{category or '通用'}维度）。

请提出 3-5 个具体的引导问题，帮创始人把写这份材料所需的关键信息口述出来。
问题要具体、可回答（问数据、时间、相关方、关键事实），不要空泛。
返回 JSON 数组：["问题1","问题2",...]
只返回 JSON："""

    def _call() -> list:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.4,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())

    try:
        items = call_with_retry(_call, max_retries=2)
    except Exception as e:  # noqa: BLE001
        logger.error("引导问题 LLM 失败: %s", e)
        return []
    return [str(q).strip() for q in items if str(q).strip()] if isinstance(items, list) else []


def _llm_synthesize(requirement: str, fragments: str, existing_snippets: str, category: str) -> str:
    client = get_dd_llm_client()
    prompt = f"""你是融资材料撰写助手。请根据下面的素材，为「{requirement}」整理一份规范的材料初稿。

【已有材料片段】
{existing_snippets or '（无）'}

【创始人补充的零碎信息/口述】
{fragments or '（无）'}

硬性规则（违反即失败）：
1. 只允许使用上面素材里出现的事实。严禁补充素材里没有的数字、名称、日期。
2. 任何数字都必须原样来自素材，禁止推算、换算、估计。
3. 信息不足的部分直接留白或写「待补充」，不要编。

输出规范的材料正文（可分段、分点），不要解释，不要 markdown 代码块。"""

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()

    try:
        return call_with_retry(_call, max_retries=2)
    except Exception as e:  # noqa: BLE001
        logger.error("材料合成 LLM 失败: %s", e)
        return ""
