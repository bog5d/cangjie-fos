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
    institution_name: str = "",
) -> str:
    """创建匹配会话，存储清单需求项。返回 session_id。"""
    session_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_sessions
               (session_id, tenant_id, checklist_name, folder_root, institution_name, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (session_id, tenant_id, checklist_name, folder_root, institution_name, time.time()),
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

    v0.7.2 改进：
      - 匹配失败的项会显式写入 confidence=0.0（而非留 NULL）
      - 无论中途是否异常，都保证最终标记 session 为 matched（防止前端无限轮询）
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

        matches = _llm_batch_match(items, "", index_rows)

        # ── v0.7.2: 写入匹配结果 + 显式标记未匹配项 ──
        matched_ids = set(matches.keys())
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
            # —— 把 LLM 未返回的项显式标为 confidence=0.0 ——
            # 原 v0.7.0 行为：LLM 返回 {} 时，不写任何 UPDATE，
            #   confidence 留在 DB 为 NULL，前端无法区分「未匹配」和「未处理」。
            # v0.7.2 修复：显式写入 0.0。
            for item in items:
                if item["id"] not in matched_ids:
                    conn.execute(
                        """UPDATE dd_match_items
                           SET confidence = 0.0, match_reason = '未匹配'
                           WHERE id = ?""",
                        (item["id"],),
                    )
    except Exception as e:
        logger.error("匹配任务异常 session=%s: %s", session_id, e)
    finally:
        # 无论成功/失败/异常，都必须将 session 标记为完成
        # 否则前端轮询会永久挂起
        _mark_session_done(session_id)


def _get_index_for_folder(folder_root: str) -> list[dict]:
    """返回文件夹下所有已索引文件。
    注意：不再过滤 readable=1，确保图片型PDF、加密文件等仍通过文件名参与匹配。
    summary 为 NULL 时 prefilter 仍可用文件名做关键词匹配。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT file_path, filename, summary FROM dd_asset_index WHERE folder_root = ?",
            (folder_root,),
        ).fetchall()
    return [dict(r) for r in rows]


def _mark_session_done(session_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_sessions SET status = 'matched', completed_at = ? WHERE session_id = ?",
            (time.time(), session_id),
        )


def _prefilter_files_for_batch(
    batch_items: list[dict],
    index_rows: list[dict],
    top_n: int = 50,
) -> list[dict]:
    """
    关键词预筛：从 index_rows 中找出与当前批次需求最相关的 top_n 个文件。
    文件数不超过 top_n 时直接返回全量。
    使用汉字二元组（bigram）匹配，忽略停用字。
    """
    if len(index_rows) <= top_n:
        return index_rows

    stop_chars = set("的和与或等及提供相关情况说明文件资料证明（）、，。是有无")
    all_keywords: set[str] = set()
    for item in batch_items:
        req = item.get("requirement", "")
        for i in range(len(req) - 1):
            bigram = req[i : i + 2]
            if not any(c in stop_chars for c in bigram):
                all_keywords.add(bigram)

    scored: list[tuple[int, dict]] = []
    for row in index_rows:
        text = f"{row.get('filename', '')} {row.get('summary') or ''}".lower()
        score = sum(1 for kw in all_keywords if kw in text)
        scored.append((score, row))

    scored.sort(key=lambda x: -x[0])
    return [row for _, row in scored[:top_n]]


def _llm_batch_match(
    items: list[dict],
    file_list_text: str,
    index_rows: list[dict],
) -> dict[str, dict]:
    """
    批量匹配：每次最多 30 条需求，全部文件列表一起发给 LLM。
    返回 {item_id: {file_path, filename, confidence, reason}}

    v0.7.2 改进：
      - 使用 dd_llm_client.call_with_retry() 代替裸 except Exception→{}，
        网络抖动不再整批丢弃（3次重试，指数退避）
      - LLM 返回结果不包含某需求 ID 时，仍显式输出 confidence=0.0
    """
    from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry

    client = get_dd_llm_client()
    results: dict[str, dict] = {}
    batch_size = 30

    for start in range(0, len(items), batch_size):
        batch = items[start: start + batch_size]
        batch_rows = _prefilter_files_for_batch(batch, index_rows, top_n=50)
        batch_file_list_text = "\n".join(
            f"[{i}] 文件名：{r['filename']}  摘要：{r['summary'] or '无摘要'}"
            for i, r in enumerate(batch_rows)
        )
        req_lines = "\n".join(
            f"需求{i + 1}（ID:{item['id']}）：{item['requirement']}"
            for i, item in enumerate(batch)
        )
        prompt = f"""你是尽调助手。以下是我们材料库中的文件（编号+摘要）：

{batch_file_list_text}

以下是机构的尽调需求：
{req_lines}

为每条需求找最匹配的文件（用文件编号[N]表示）。没有匹配的填 null。
返回 JSON（key 是需求 ID）：
{{
  "需求ID": {{"file_index": N或null, "confidence": 0到1的小数, "reason": "一句话说明"}}
}}
只返回 JSON："""

        # ── v0.7.2: 带重试的 LLM 调用 ──
        # 原 v0.7.0 中 except Exception: batch_results = {} 意味着
        # 一次网络超时就丢弃整批30条，用户看到全「无匹配」会很困惑。
        # 现在改为 3 次重试后才投降。
        def _do_batch_call() -> dict:
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
            return json.loads(raw.strip())

        try:
            batch_results: dict = call_with_retry(_do_batch_call, max_retries=3)
        except Exception as e:
            logger.error("LLM 批量匹配失败（重试3次后）: %s", e)
            batch_results = {}

        for item in batch:
            item_result = batch_results.get(item["id"], {})
            file_idx = item_result.get("file_index")
            if file_idx is not None and isinstance(file_idx, int) and 0 <= file_idx < len(batch_rows):
                matched = batch_rows[file_idx]
                results[item["id"]] = {
                    "file_path": matched["file_path"],
                    "filename": matched["filename"],
                    "confidence": float(item_result.get("confidence", 0.5)),
                    "reason": str(item_result.get("reason", "")),
                }
            else:
                # ── 即使 LLM 没返回这个 ID，也显式输出 confidence=0.0 ──
                results[item["id"]] = {
                    "file_path": None,
                    "filename": None,
                    "confidence": 0.0,
                    "reason": "无匹配文件",
                }

    return results
