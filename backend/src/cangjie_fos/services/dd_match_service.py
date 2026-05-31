"""创建匹配 session、批量 LLM 匹配清单需求 vs 材料库索引。"""
from __future__ import annotations
import json
import logging
import os
import re
import uuid
import time
from typing import Callable

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_index_service import clean_filename
from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry

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


def run_matching(
    session_id: str,
    folder_root: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """
    对 session 的所有需求项，与 folder_root 下的已索引文件做批量匹配。
    同步执行，调用方应包装进 BackgroundTask。

    v0.7.2 改进：
      - 匹配失败的项会显式写入 confidence=0.0（而非留 NULL）
      - 无论中途是否异常，都保证最终标记 session 为 matched（防止前端无限轮询）

    v1.1.3 改进：
      - 新增 progress_callback(done, total) 参数，每批完成后触发
      - 批内结果即时写入 DB（不在所有批完成后才提交），减少部分失败损失
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

        total = len(items)
        matches = _llm_batch_match(
            items, "", index_rows,
            progress_callback=progress_callback,
            total_items=total,
        )

        # ── 最终补写：确保所有项都有 confidence（兼容 _llm_batch_match 被 mock 的场景）──
        # 当 _llm_batch_match 未被 mock 时，批内即时写入已处理此逻辑；
        # 当被 mock 时（测试），仍由此处兜底写入。
        matched_ids = set(matches.keys())
        with _connect() as conn:
            for item_id, result in matches.items():
                conn.execute(
                    """UPDATE dd_match_items
                       SET matched_file_path = ?, matched_filename = ?,
                           confidence = ?, match_reason = ?, candidates_json = ?
                       WHERE id = ?""",
                    (result.get("file_path"), result.get("filename"),
                     result.get("confidence", 0.0), result.get("reason", ""),
                     result.get("candidates_json"),
                     item_id),
                )
            # 未在 matches 中的项显式写入 0.0（避免 NULL 留存）
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
        raw_name = row.get('filename', '')
        text = f"{clean_filename(raw_name)} {raw_name} {row.get('summary') or ''}".lower()
        score = sum(1 for kw in all_keywords if kw in text)
        scored.append((score, row))

    scored.sort(key=lambda x: -x[0])
    return [row for _, row in scored[:top_n]]


def _try_partial_json_parse(raw: str) -> dict:
    """
    截断恢复：从 LLM 输出的不完整 JSON 中提取已完成的 uuid→{...} 块。

    LLM 在 token 上限前截断时，json.loads 会失败，但前面已经完整输出的条目
    仍然可以被提取并使用，避免整批静默归零。

    使用 re.finditer 寻找 "uuid": {...} 完整块（嵌套深度不超过3层，足够覆盖 candidates 结构）。
    """
    results: dict = {}
    # 匹配 "uuid-string": { ... } 块（贪婪 + 允许嵌套一层）
    # 简化策略：找到 "<uuid>": { 开始，然后扫描到匹配的 }
    uuid_re = re.compile(
        r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"'
        r'\s*:\s*(\{)',
    )
    for m in uuid_re.finditer(raw):
        uid = m.group(1)
        start_brace = m.start(2)
        depth = 0
        end_pos = None
        for i in range(start_brace, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break
        if end_pos is None:
            continue  # 未找到匹配的右括号，此条目不完整，跳过
        try:
            obj = json.loads(raw[start_brace:end_pos])
            results[uid] = obj
        except json.JSONDecodeError:
            continue
    return results


def _llm_batch_match(
    items: list[dict],
    file_list_text: str,
    index_rows: list[dict],
    progress_callback: Callable[[int, int], None] | None = None,
    total_items: int | None = None,
) -> dict[str, dict]:
    """
    批量匹配：每次最多 20 条需求（从 30 减少以防 token 溢出），全部文件列表一起发给 LLM。
    每批完成后立即写入 DB（partial save），减少失败损失。
    返回 {item_id: {file_path, filename, confidence, reason}}

    v0.7.2 改进：
      - 使用 dd_llm_client.call_with_retry() 代替裸 except Exception→{}，
        网络抖动不再整批丢弃（3次重试，指数退避）
      - LLM 返回结果不包含某需求 ID 时，仍显式输出 confidence=0.0

    v1.1.3 改进：
      - batch_size: 30 → 20（50项 → 3批，减小单批 token 负担）
      - max_tokens: 3000 → 6000（为 20 项×2 候选留足 buffer）
      - candidates 上限: 3 → 2（进一步缩短输出）
      - 每批结果即时写入 DB（不是最后一次性写入）
      - 截断恢复：json.loads 失败时用 _try_partial_json_parse 挽救部分结果
      - progress_callback 支持（每批结束后调用）
    """
    client = get_dd_llm_client()
    results: dict[str, dict] = {}
    batch_size = 20
    _total = total_items if total_items is not None else len(items)
    completed = 0

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

为每条需求找最多2个最匹配的文件（按相关性降序）。没有匹配的该条 candidates 填 []。
返回 JSON（key 是需求 ID）：
{{
  "需求ID": {{
    "candidates": [
      {{"file_index": N, "confidence": 0到1的小数, "reason": "一句话说明"}},
      {{"file_index": M, "confidence": 0到1的小数, "reason": "一句话说明"}}
    ]
  }}
}}
只返回 JSON："""

        def _do_batch_call() -> dict:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=6000,
                temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.lower().startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                # 截断恢复：尝试从不完整 JSON 中提取已完整输出的条目
                recovered = _try_partial_json_parse(raw)
                if recovered:
                    logger.warning(
                        "LLM 输出 JSON 截断，通过部分解析恢复 %d/%d 条结果",
                        len(recovered), len(batch),
                    )
                    return recovered
                raise  # 无法恢复，继续抛出，交由 call_with_retry 处理

        try:
            batch_results: dict = call_with_retry(_do_batch_call, max_retries=3)
        except Exception as e:
            logger.error("LLM 批量匹配失败（重试3次后）: %s", e)
            batch_results = {}

        # ── 解析并写入本批结果（即时写入，不等所有批完成）──
        batch_item_results: dict[str, dict] = {}
        for item in batch:
            item_result = batch_results.get(item["id"], {})
            raw_candidates = item_result.get("candidates", [])

            # 兼容旧格式（LLM 偶尔返回 file_index 直接在顶层）
            if not raw_candidates and "file_index" in item_result:
                raw_candidates = [item_result]

            resolved_candidates: list[dict] = []
            for cand in raw_candidates:
                file_idx = cand.get("file_index")
                if file_idx is not None and isinstance(file_idx, int) and 0 <= file_idx < len(batch_rows):
                    matched = batch_rows[file_idx]
                    resolved_candidates.append({
                        "file_path": matched["file_path"],
                        "filename": matched["filename"],
                        "confidence": float(cand.get("confidence", 0.5)),
                        "reason": str(cand.get("reason", "")),
                    })

            if resolved_candidates:
                best = resolved_candidates[0]
                batch_item_results[item["id"]] = {
                    "file_path": best["file_path"],
                    "filename": best["filename"],
                    "confidence": best["confidence"],
                    "reason": best["reason"],
                    "candidates_json": json.dumps(resolved_candidates, ensure_ascii=False),
                }
            else:
                batch_item_results[item["id"]] = {
                    "file_path": None,
                    "filename": None,
                    "confidence": 0.0,
                    "reason": "无匹配文件",
                    "candidates_json": None,
                }

        # 即时写入 DB（partial save）
        with _connect() as conn:
            for item_id, res in batch_item_results.items():
                conn.execute(
                    """UPDATE dd_match_items
                       SET matched_file_path = ?, matched_filename = ?,
                           confidence = ?, match_reason = ?, candidates_json = ?
                       WHERE id = ?""",
                    (res.get("file_path"), res.get("filename"),
                     res.get("confidence", 0.0), res.get("reason", ""),
                     res.get("candidates_json"),
                     item_id),
                )

        results.update(batch_item_results)
        completed += len(batch)
        if progress_callback is not None:
            try:
                progress_callback(completed, _total)
            except Exception as cb_err:
                logger.warning("progress_callback 异常: %s", cb_err)

    return results
