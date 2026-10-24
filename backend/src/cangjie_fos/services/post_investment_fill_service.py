"""投后季报草稿填充引擎。

从材料索引中提取每个【】空格/字段的具体值，存入 dd_match_items.draft_answer。
叙述型（narrative）生成简要概述；无匹配的留空（人工填写）。
"""
from __future__ import annotations

import logging
import time

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry

logger = logging.getLogger(__name__)

_MAX_SUMMARY_CHARS = 400
_BATCH_SIZE = 10


def run_draft_fill(session_id: str) -> None:
    """为投后 session 的每个已匹配项，用 LLM 从文件摘要中提取填充值。
    无匹配（confidence=0 / matched_file_path=NULL）的项留空。
    """
    with _connect() as conn:
        items = [dict(r) for r in conn.execute(
            """SELECT i.id, i.requirement, i.field_kind, i.matched_file_path,
                      a.summary
               FROM dd_match_items i
               LEFT JOIN dd_asset_index a ON a.file_path = i.matched_file_path
               WHERE i.session_id = ?
               ORDER BY CAST(i.item_no AS INTEGER)""",
            (session_id,),
        ).fetchall()]

    if not items:
        return

    # 只对有匹配文件的项做填充
    fillable = [it for it in items if it.get("matched_file_path")]
    if not fillable:
        logger.info("投后填充：session %s 无已匹配项，跳过", session_id)
        return

    client = get_dd_llm_client()

    for start in range(0, len(fillable), _BATCH_SIZE):
        batch = fillable[start: start + _BATCH_SIZE]
        _fill_batch(session_id, batch, client)

    logger.info("投后填充完成：session %s，%d 项", session_id, len(fillable))


def _fill_batch(session_id: str, batch: list[dict], client) -> None:
    """对一批 items 调用 LLM 提取填充值，写入 draft_answer。"""
    # 构建批量提示
    req_lines = []
    for i, item in enumerate(batch):
        summary = (item.get("summary") or "无摘要")[:_MAX_SUMMARY_CHARS]
        field_kind = item.get("field_kind", "blank")
        if field_kind == "narrative":
            req_lines.append(
                f"需求{i + 1}（ID:{item['id']}）[叙述型] 章节：{item['requirement']}\n摘要：{summary}"
            )
        else:
            req_lines.append(
                f"需求{i + 1}（ID:{item['id']}）[填空] 句子：{item['requirement']}\n摘要：{summary}"
            )

    prompt = f"""你是投后季报填写助手。请根据每条材料摘要，为对应空格提取填写值。

{chr(10).join(req_lines)}

对每条需求：
- [填空] 型：只返回需要填入空格的具体值（数字/名词/日期），不要解释；找不到返回空字符串。
- [叙述型] 型：用摘要内容写一段100字以内的描述；找不到返回空字符串。

返回 JSON（key 是需求 ID）：
{{"需求ID": "填充值或空字符串", ...}}
只返回 JSON："""

    def _call() -> dict:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0,
        )
        import json
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        return json.loads(raw)

    try:
        results: dict = call_with_retry(_call, max_retries=3)
    except Exception as e:
        logger.error("投后填充 LLM 失败（session=%s）: %s", session_id, e)
        results = {}

    with _connect() as conn:
        for item in batch:
            answer = str(results.get(item["id"], "") or "").strip()
            conn.execute(
                "UPDATE dd_match_items SET draft_answer = ? WHERE id = ?",
                (answer, item["id"]),
            )
