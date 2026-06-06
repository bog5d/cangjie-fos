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
    """返回 session 的所有需求项（含匹配结果）。

    富化：按 matched_file_path 关联 dd_asset_index，带出 is_encrypted /
    unlock_password，供前端显示🔒标记与密码输入框（gk 模式 F3）。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM dd_match_items WHERE session_id = ? ORDER BY item_no",
            (session_id,),
        ).fetchall()
        items = [dict(r) for r in rows]

        # 一次性取出本 session 涉及文件的加密状态/密码，避免逐条查询
        paths = [it["matched_file_path"] for it in items if it.get("matched_file_path")]
        enc_map: dict[str, dict] = {}
        if paths:
            placeholders = ",".join("?" * len(paths))
            for r in conn.execute(
                f"SELECT file_path, is_encrypted, unlock_password "
                f"FROM dd_asset_index WHERE file_path IN ({placeholders})",
                paths,
            ).fetchall():
                enc_map[r["file_path"]] = dict(r)

    for it in items:
        meta = enc_map.get(it.get("matched_file_path") or "", {})
        it["is_encrypted"] = meta.get("is_encrypted", 0)
        it["unlock_password"] = meta.get("unlock_password", "")
    return items


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

    v1.6.0 加固（P0）：
      - 内部抛异常时 session 标记为 'failed'（而非沿用旧的一律 'matched'），
        前端/导出据此区分"真完成"与"中途崩溃"，避免把残缺结果当成功结果。
      - 早退（无索引文件）等正常路径仍标记 'matched'。
    """
    failed = False
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

        # ── 阶段3：跨机构决策记忆覆盖（人工确认过的同类需求→文件，直接沿用）──
        # 材料库共享 → A 机构沉淀的「需求→文件」映射可惠及 B/C/D。
        # 命中即把该项锁定为记忆文件（高置信 + green），后续精判跳过省 token。
        try:
            _apply_decision_memory(session_id, items, index_rows)
        except Exception as e:  # noqa: BLE001
            logger.warning("决策记忆覆盖失败（不影响主流程）: %s", e)

        # ── 阶段1+2：全文精判 + 机器验证（红/黄/绿 + 原文证据）──
        # 只对「有正文可读」且「非记忆锁定」的已匹配项逐条核对正文。
        try:
            _refine_session_matches(session_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("精判/验证阶段失败（不影响主流程）: %s", e)

    except Exception as e:
        logger.error("匹配任务异常 session=%s: %s", session_id, e)
        failed = True
    finally:
        # 无论成功/失败，都必须给 session 一个终态，否则前端轮询会永久挂起。
        # 区分 failed / matched：失败时前端可提示"匹配中断，请重试"，
        # 导出逻辑也不会把残缺结果当作已完成结果。
        if failed:
            _mark_session_failed(session_id)
        else:
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


def _mark_session_failed(session_id: str) -> None:
    """匹配中途崩溃时调用：标记 'failed'，前端据此提示重试，导出不当成已完成。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_sessions SET status = 'failed', completed_at = ? WHERE session_id = ?",
            (time.time(), session_id),
        )


# ── 精判 / 验证 / 跨机构学习 常量 ─────────────────────────────────────────────
# 精判节点喂给 LLM 的单文件正文最大字符数（控制 token，可调）
_REFINE_CONTENT_CHARS = 4000

# 红/黄/绿判定阈值（与 engine/matchmaker.py 四色逻辑一致）
_VERDICT_GREEN = 0.70   # ≥ 此值：高可信，可一键放行
_VERDICT_YELLOW = 0.40  # [此值, GREEN)：建议人工核对；< 此值：低可信（红）

# 跨机构决策记忆命中后写入的标记前缀（精判节点据此跳过，不重复消耗 token）
MEMORY_REASON_PREFIX = "🧠 历史沿用"
# 命中记忆时赋予的置信度（人工确认过的同类需求→文件映射，高可信）
_MEMORY_CONFIDENCE = 0.97


def _confidence_to_verdict(conf: float | None) -> str:
    """置信度 → 红/黄/绿判定。供机器验证节点与人工闸消费。"""
    c = conf or 0.0
    if c >= _VERDICT_GREEN:
        return "green"
    if c >= _VERDICT_YELLOW:
        return "yellow"
    return "red"


def normalize_requirement(req: str) -> str:
    """需求文本归一化，作为跨机构决策记忆的 key。

    材料库共享（同一融资项目，不同投资人各发各的清单）→「需求→文件」映射
    可在机构间复用。不同机构对同一份材料的措辞会有差异，故归一化：
      - 去空白 / 标点 / 年份 / 括号注释
      - 转小写
    使「近三年财务报表」与「近 3 年财报」尽量落到相近的 key（粗粒度，命中即省一次精判）。
    """
    s = (req or "").lower().strip()
    s = re.sub(r"20\d{2}\s*[-年/]?\s*\d{0,2}\s*[-月/]?\s*\d{0,2}\s*日?", "", s)
    s = re.sub(r"[（(【\[].{0,12}[）)\]】]", "", s)
    s = re.sub(r"[\s　,.，。、；;:：!！?？|/\\\-_~·\"'“”‘’()（）]+", "", s)
    return s


# 关键词匹配用停用字（语义稀薄、对匹配无区分度）
_STOP_CHARS = set("的和与或等及提供相关情况说明文件资料证明（）、，。是有无")

# 单条文件摘要的最大字符数，超出截断以防 LLM 上下文溢出
_MAX_SUMMARY_CHARS = 150


def _build_file_list_text(rows: list[dict]) -> str:
    """构建发给 LLM 的文件列表文本，超长摘要截断到 _MAX_SUMMARY_CHARS。"""
    lines = []
    for i, r in enumerate(rows):
        summary = r.get("summary") or "无摘要"
        if len(summary) > _MAX_SUMMARY_CHARS:
            summary = summary[:_MAX_SUMMARY_CHARS] + "…"
        lines.append(f"[{i}] 文件名：{r['filename']}  摘要：{summary}")
    return "\n".join(lines)


def _requirement_bigrams(req: str) -> set[str]:
    """从需求文本提取汉字二元组关键词（剔除含停用字的组合）。"""
    keywords: set[str] = set()
    for i in range(len(req) - 1):
        bigram = req[i : i + 2]
        if not any(c in _STOP_CHARS for c in bigram):
            keywords.add(bigram)
    return keywords


def _row_search_text(row: dict) -> str:
    """文件行的可搜索文本（清洗后文件名 + 原文件名 + 摘要，统一小写）。"""
    raw_name = row.get("filename", "")
    return f"{clean_filename(raw_name)} {raw_name} {row.get('summary') or ''}".lower()


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

    all_keywords: set[str] = set()
    for item in batch_items:
        all_keywords |= _requirement_bigrams(item.get("requirement", ""))

    scored: list[tuple[int, dict]] = []
    for row in index_rows:
        text = _row_search_text(row)
        score = sum(1 for kw in all_keywords if kw in text)
        scored.append((score, row))

    scored.sort(key=lambda x: -x[0])
    return [row for _, row in scored[:top_n]]


def _keyword_fallback_match(
    batch: list[dict],
    batch_rows: list[dict],
) -> dict[str, dict]:
    """LLM 全失败（重试耗尽）时的降级匹配。

    用汉字 bigram 关键词为每条需求在 batch_rows 中找单个最相关文件，
    返回与 LLM 输出同构的 dict（{item_id: {"candidates": [...]}}），
    使下游解析逻辑无需改动即可复用。

    - 命中（score>0）：给一个降级置信度 0.3（UI 显示红色低置信徽章），
      reason 标注"⚠️ AI暂不可用，关键词匹配"，让用户清楚这不是 AI 判断。
    - 无任何关键词命中：返回空 candidates（不硬塞错误文件）。
    """
    results: dict[str, dict] = {}
    for item in batch:
        keywords = _requirement_bigrams(item.get("requirement", ""))
        best_idx: int | None = None
        best_score = 0
        for idx, row in enumerate(batch_rows):
            text = _row_search_text(row)
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx is not None and best_score > 0:
            results[item["id"]] = {
                "candidates": [{
                    "file_index": best_idx,
                    "confidence": 0.3,
                    "reason": "⚠️ AI暂不可用，关键词匹配",
                }]
            }
        else:
            results[item["id"]] = {"candidates": []}
    return results


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
        batch_file_list_text = _build_file_list_text(batch_rows)
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
            # LLM 三次重试全失败（服务宕机/持续超时）→ 降级为关键词匹配，
            # 而非整批静默归零。让相关项仍有低置信度匹配，并明确标注 AI 不可用。
            logger.error("LLM 批量匹配失败（重试3次后），降级关键词匹配: %s", e)
            batch_results = _keyword_fallback_match(batch, batch_rows)

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


# ═══════════════════════════════════════════════════════════════════════════
# 阶段1+2：全文精判 + 机器验证（evaluator）
# ═══════════════════════════════════════════════════════════════════════════

def _llm_refine_candidate(
    client, requirement: str, filename: str, content_text: str,
) -> dict:
    """精判单条：把候选文件正文喂 LLM，判断是否真满足该需求。

    返回 {"satisfies": bool, "confidence": float, "evidence": str}。
    这是「看 20 字摘要」→「看正文」的关键一步，也产出供机器验证的原文证据。
    抽成独立函数便于测试 monkeypatch。
    """
    content = (content_text or "")[:_REFINE_CONTENT_CHARS]
    prompt = f"""你是尽调材料核对员。请判断下面这份文件是否满足机构的这条需求。

机构需求：{requirement}
候选文件名：{filename}
文件正文（节选）：
{content}

严格依据正文内容判断（不要凭文件名猜测）。只返回 JSON：
{{"satisfies": true 或 false, "confidence": 0到1的小数, "evidence": "支撑判断的原文关键片段或一句话理由（40字内）"}}
只返回 JSON："""

    def _call() -> dict:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())

    return call_with_retry(_call, max_retries=2)


def _refine_session_matches(session_id: str) -> None:
    """对 session 已匹配项做全文精判 + 验证，写回 confidence/verdict/evidence。

    规则：
      - 记忆锁定项（match_reason 以 MEMORY_REASON_PREFIX 开头）：直接给 green，跳过 LLM。
      - 有正文（content_text）的已匹配项：喂正文精判，按结果调整 confidence + 证据。
        · satisfies=False → confidence 压到 ≤0.3（红），让人重点复核。
        · satisfies=True  → 采用精判 confidence（与原值取较高，避免误伤）。
      - 无正文（图片/加密件等）已匹配项：不精判，verdict 由现有 confidence 推出，
        evidence 标注「正文不可读，未精判」。
      - 未匹配项（无 matched_file_path）：verdict=red。
    所有项最终都带上 verdict，供前端人工闸消费（绿一键过 / 黄重点看 / 红改）。
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT i.id, i.requirement, i.matched_file_path, i.matched_filename,
                      i.confidence, i.match_reason, a.content_text
               FROM dd_match_items i
               LEFT JOIN dd_asset_index a ON a.file_path = i.matched_file_path
               WHERE i.session_id = ?""",
            (session_id,),
        ).fetchall()]

    # 仅当存在「有正文的非记忆锁定已匹配项」时才需要 LLM 客户端（避免无谓初始化）
    needs_llm = any(
        r.get("matched_file_path") and (r.get("content_text") or "").strip()
        and not (r.get("match_reason") or "").startswith(MEMORY_REASON_PREFIX)
        for r in rows
    )
    client = get_dd_llm_client() if needs_llm else None

    for r in rows:
        item_id = r["id"]
        path = r.get("matched_file_path")
        reason = r.get("match_reason") or ""
        cur_conf = r.get("confidence") or 0.0

        # 未匹配项：直接红判
        if not path:
            _update_verdict(item_id, _confidence_to_verdict(cur_conf), "")
            continue

        # 记忆锁定项：信任人工历史选择，直接 green
        if reason.startswith(MEMORY_REASON_PREFIX):
            _update_verdict(item_id, "green", "历史人工确认沿用")
            continue

        content = (r.get("content_text") or "").strip()
        if not content or client is None:
            # 正文不可读：不精判，仅据现有置信度给信号
            _update_verdict(
                item_id, _confidence_to_verdict(cur_conf),
                "（正文不可读，未精判）",
            )
            continue

        # 有正文 → 全文精判
        try:
            res = _llm_refine_candidate(
                client, r["requirement"], r.get("matched_filename") or "", content,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("精判失败 item=%s: %s（保留原匹配）", item_id, e)
            _update_verdict(item_id, _confidence_to_verdict(cur_conf), "")
            continue

        satisfies = bool(res.get("satisfies", True))
        evidence = str(res.get("evidence", ""))[:200]
        try:
            refined_conf = float(res.get("confidence", cur_conf))
        except (TypeError, ValueError):
            refined_conf = cur_conf
        refined_conf = max(0.0, min(1.0, refined_conf))

        if not satisfies:
            new_conf = min(cur_conf, 0.3, refined_conf)
        else:
            new_conf = max(cur_conf, refined_conf)

        verdict = _confidence_to_verdict(new_conf)
        with _connect() as conn:
            conn.execute(
                """UPDATE dd_match_items
                   SET confidence = ?, verdict = ?, evidence = ?
                   WHERE id = ?""",
                (new_conf, verdict, evidence, item_id),
            )


def _update_verdict(item_id: str, verdict: str, evidence: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_items SET verdict = ?, evidence = ? WHERE id = ?",
            (verdict, evidence, item_id),
        )


# ═══════════════════════════════════════════════════════════════════════════
# 阶段3：跨机构决策记忆（材料库共享 → 需求→文件 映射全局复用）
# ═══════════════════════════════════════════════════════════════════════════

def record_session_decisions(session_id: str) -> int:
    """把 session 中「已确认」的需求→文件映射写入 dd_decision_memory。

    每次人工确认即沉淀一条全局记忆（机构无关，按归一化需求聚合）。
    返回写入/累加的条数。下一次任意机构遇到同类需求时即可直接沿用。
    """
    with _connect() as conn:
        rows = conn.execute(
            """SELECT i.requirement, i.matched_file_path, i.matched_filename,
                      s.institution_name
               FROM dd_match_items i
               JOIN dd_match_sessions s ON s.session_id = i.session_id
               WHERE i.session_id = ? AND i.user_confirmed = 1
                 AND i.matched_file_path IS NOT NULL AND i.matched_file_path != ''""",
            (session_id,),
        ).fetchall()
        n = 0
        now = time.time()
        for row in rows:
            req = row["requirement"] or ""
            norm = normalize_requirement(req)
            if not norm:
                continue
            path = row["matched_file_path"]
            mem_id = f"{norm}::{path}"
            existing = conn.execute(
                "SELECT confirm_count FROM dd_decision_memory WHERE id = ?",
                (mem_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE dd_decision_memory
                       SET confirm_count = confirm_count + 1, last_institution = ?,
                           updated_at = ?, requirement = ?, filename = ?
                       WHERE id = ?""",
                    (row["institution_name"] or "", now, req,
                     row["matched_filename"] or "", mem_id),
                )
            else:
                conn.execute(
                    """INSERT INTO dd_decision_memory
                       (id, requirement_norm, requirement, file_path, filename,
                        confirm_count, last_institution, updated_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                    (mem_id, norm, req, path, row["matched_filename"] or "",
                     row["institution_name"] or "", now),
                )
            n += 1
    return n


def lookup_decision_memory(requirement: str) -> dict | None:
    """查归一化需求对应的历史人工确认文件（取确认次数最高的一条）。"""
    norm = normalize_requirement(requirement)
    if not norm:
        return None
    with _connect() as conn:
        row = conn.execute(
            """SELECT file_path, filename, confirm_count
               FROM dd_decision_memory
               WHERE requirement_norm = ?
               ORDER BY confirm_count DESC, updated_at DESC
               LIMIT 1""",
            (norm,),
        ).fetchone()
    return dict(row) if row else None


def _apply_decision_memory(
    session_id: str, items: list[dict], index_rows: list[dict],
) -> int:
    """对每条需求查跨机构记忆；命中且记忆文件仍在当前库 → 锁定为该文件。

    「仍在当前库」用 index_rows 的 file_path 集合判断（材料库共享，但偶有增删）。
    命中项写入高置信 + MEMORY_REASON_PREFIX 标记，精判阶段据此跳过。
    返回命中并覆盖的条数。
    """
    available = {r["file_path"] for r in index_rows}
    hits = 0
    for item in items:
        mem = lookup_decision_memory(item.get("requirement", ""))
        if not mem:
            continue
        if mem["file_path"] not in available:
            continue  # 记忆文件已不在当前材料库，不强行套用
        reason = f"{MEMORY_REASON_PREFIX}（历史已确认{mem.get('confirm_count', 1)}次）"
        candidates_json = json.dumps([{
            "file_path": mem["file_path"],
            "filename": mem.get("filename", ""),
            "confidence": _MEMORY_CONFIDENCE,
            "reason": reason,
        }], ensure_ascii=False)
        with _connect() as conn:
            conn.execute(
                """UPDATE dd_match_items
                   SET matched_file_path = ?, matched_filename = ?,
                       confidence = ?, match_reason = ?, candidates_json = ?
                   WHERE id = ?""",
                (mem["file_path"], mem.get("filename", ""), _MEMORY_CONFIDENCE,
                 reason, candidates_json, item["id"]),
            )
        hits += 1
    return hits
