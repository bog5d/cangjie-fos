"""创建匹配 session、批量 LLM 匹配清单需求 vs 材料库索引。"""
from __future__ import annotations
import json
import logging
import os
import uuid
import time

from cangjie_fos.services.db_base import _connect

logger = logging.getLogger(__name__)


def create_match_session(
    tenant_id: str,
    checklist_name: str,
    folder_root: str,
    items: list[dict],
) -> str:
    """创建匹配会话，存储清单需求项。返回 session_id。"""
    session_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_sessions
               (session_id, tenant_id, checklist_name, folder_root, status, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (session_id, tenant_id, checklist_name, folder_root, time.time()),
        )
        for item in items:
            conn.execute(
                """INSERT INTO dd_match_items
                   (id, session_id, item_no, category, requirement)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), session_id, item["item_no"],
                 item.get("category", ""), item["requirement"]),
            )
    return session_id


def get_session_items(session_id: str) -> list[dict]:
    """返回 session 的所有需求项（含匹配结果）。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM dd_match_items WHERE session_id = ? ORDER BY item_no",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def run_matching(session_id: str, folder_root: str) -> None:
    """
    对 session 的所有需求项，与 folder_root 下的已索引文件做批量匹配。
    同步执行，调用方应包装进 BackgroundTask。
    无论中途是否异常，都保证最终标记 session 为 matched（防止前端无限轮询）。
    """
    try:
        index_rows = _get_index_for_folder(folder_root)
        if not index_rows:
            logger.warning("文件夹 %s 没有已索引文件，跳过匹配", folder_root)
            return

        with _connect() as conn:
            items = [dict(r) for r in conn.execute(
                "SELECT id, requirement FROM dd_match_items WHERE session_id = ?",
                (session_id,),
            ).fetchall()]

        if not items:
            return

        file_list_text = "\n".join(
            f"[{i}] 文件名：{r['filename']}  摘要：{r['summary'] or '无摘要'}"
            for i, r in enumerate(index_rows)
        )
        matches = _llm_batch_match(items, file_list_text, index_rows)

        with _connect() as conn:
            for item_id, result in matches.items():
                conn.execute(
                    """UPDATE dd_match_items
                       SET matched_file_path = ?, matched_filename = ?,
                           confidence = ?, match_reason = ?
                       WHERE id = ?""",
                    (result.get("file_path"), result.get("filename"),
                     result.get("confidence", 0.0), result.get("reason", ""),
                     item_id),
                )
    except Exception as e:
        logger.error("匹配任务异常 session=%s: %s", session_id, e)
    finally:
        # 无论成功/失败/异常，都必须将 session 标记为完成
        # 否则前端轮询会永久挂起
        _mark_session_done(session_id)


def _get_index_for_folder(folder_root: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT file_path, filename, summary FROM dd_asset_index WHERE folder_root = ? AND readable = 1",
            (folder_root,),
        ).fetchall()
    return [dict(r) for r in rows]


def _mark_session_done(session_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_sessions SET status = 'matched', completed_at = ? WHERE session_id = ?",
            (time.time(), session_id),
        )


def _llm_batch_match(
    items: list[dict],
    file_list_text: str,
    index_rows: list[dict],
) -> dict[str, dict]:
    """
    批量匹配：每次最多 30 条需求，全部文件列表一起发给 LLM。
    返回 {item_id: {file_path, filename, confidence, reason}}
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY", ""), base_url="https://api.deepseek.com")
    results: dict[str, dict] = {}
    batch_size = 30

    for start in range(0, len(items), batch_size):
        batch = items[start: start + batch_size]
        req_lines = "\n".join(
            f"需求{i + 1}（ID:{item['id']}）：{item['requirement']}"
            for i, item in enumerate(batch)
        )
        prompt = f"""你是尽调助手。以下是我们材料库中的文件（编号+摘要）：

{file_list_text}

以下是机构的尽调需求：
{req_lines}

为每条需求找最匹配的文件（用文件编号[N]表示）。没有匹配的填 null。
返回 JSON（key 是需求 ID）：
{{
  "需求ID": {{"file_index": N或null, "confidence": 0到1的小数, "reason": "一句话说明"}}
}}
只返回 JSON："""

        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.lower().startswith("json"):
                    raw = raw[4:]
            batch_results: dict = json.loads(raw.strip())
        except Exception as e:
            logger.error("LLM 批量匹配失败: %s", e)
            batch_results = {}

        for item in batch:
            item_result = batch_results.get(item["id"], {})
            file_idx = item_result.get("file_index")
            if file_idx is not None and isinstance(file_idx, int) and 0 <= file_idx < len(index_rows):
                matched = index_rows[file_idx]
                results[item["id"]] = {
                    "file_path": matched["file_path"],
                    "filename": matched["filename"],
                    "confidence": float(item_result.get("confidence", 0.5)),
                    "reason": str(item_result.get("reason", "")),
                }
            else:
                results[item["id"]] = {
                    "file_path": None,
                    "filename": None,
                    "confidence": 0.0,
                    "reason": "无匹配文件",
                }

    return results
