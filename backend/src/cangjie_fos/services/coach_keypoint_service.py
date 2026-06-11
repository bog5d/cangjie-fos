"""
需求01·A1 — BP 逐字稿要点提炼器（结构化输出）。

把一份 BP 逐字稿（每页说词）打散成一组结构化「核心要点」，作为后续
「覆盖率打分」的标准答案来源。

设计原则（沿用 dd_checklist_parser 范式）：
  - 长文本分块（4000 字/块，300 字重叠），逐块提取后去重合并
  - LLM 只负责语义提炼；输出用 Pydantic 约束，杜绝裸 dict 漂移
  - _llm_extract_keypoints_chunk 可被测试 monkeypatch，全链路无需真实 LLM

要点形状：{point_no, page_no, point_text, weight, evidence}
  weight: 'core'(必讲) | 'normal'(应讲) | 'minor'(可选) —— 影响覆盖率权重
  evidence: 材料原句出处；含数字的要点必须有有效出处，否则被事实护栏丢弃
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field, ValidationError

from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry
from cangjie_fos.services.fact_guard import evidence_found, extract_numbers, ungrounded_numbers

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 4000
_CHUNK_OVERLAP = 300

_WEIGHTS = {"core", "normal", "minor"}


class KeyPoint(BaseModel):
    """BP 提炼出的单个核心要点。"""
    point_no: str = Field(..., description="全局序号")
    page_no: int = Field(0, description="所属页码，未知为 0")
    point_text: str = Field(..., description="要点内容（一句话）")
    weight: str = Field("normal", description="core/normal/minor")
    evidence: str = Field("", description="材料原句出处")


def extract_key_points(bp_text: str) -> list[dict]:
    """从 BP 逐字稿提取结构化要点列表。

    返回 [{point_no, page_no, point_text, weight}, ...]，
    point_no 连续重编号；去重以 point_text 前 50 字为 key。
    """
    if not bp_text or not bp_text.strip():
        return []

    chunks = _split_into_chunks(bp_text, _CHUNK_SIZE, _CHUNK_OVERLAP)
    all_points: list[dict] = []
    seen: set[str] = set()

    for chunk in chunks:
        for point in _llm_extract_keypoints_chunk(chunk):
            key = point["point_text"][:50].strip().lower()
            if key and key not in seen:
                seen.add(key)
                all_points.append(point)

    for i, point in enumerate(all_points):
        point["point_no"] = str(i + 1)
    return all_points


def _split_into_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    """将长文本分割为有重叠的块列表（与 dd_checklist_parser 一致）。"""
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _llm_extract_keypoints_chunk(chunk_text: str) -> list[dict]:
    """对单个文本块调用 LLM 提取要点（可被测试 monkeypatch）。"""
    client = get_dd_llm_client()
    prompt = f"""以下是一份创业公司 BP（商业计划书）路演逐字稿的片段：

{chunk_text}

请提取演讲者在这段里应当向投资人讲清楚的「核心要点」（忽略口水话、过渡句、寒暄）。

硬性规则（违反即作废）：
1. 只许概括原文已有的信息。要点里的每一个数字必须原样来自上面的片段，
   禁止推导、禁止从你的常识补充材料里没有的数据。
2. 每个要点带 "evidence" 字段：逐字引用片段中支撑该要点的那句原文，不许改写。

以 JSON 数组返回，每项格式：
{{"page_no": 页码数字(未知填0), "point_text": "一句话要点", "weight": "core或normal或minor", "evidence": "原文出处"}}
weight 判断：投资决策必听的关键信息(如商业模式/壁垒/财务核心数据)=core；
应当覆盖的支撑信息=normal；锦上添花=minor。

只返回 JSON 数组，不要任何解释或 markdown 标记："""

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()

    raw = call_with_retry(_call, max_retries=3)
    return _filter_grounded_points(_parse_keypoints_json(raw), chunk_text)


def _filter_grounded_points(points: list[dict], source_text: str) -> list[dict]:
    """事实护栏：丢弃含原文中不存在数字、或数据类要点无有效出处的要点。

    规则（同事实测反馈的幻觉案例驱动）：
      - 要点里的数字必须能在原文找到（拦「32 张 GPU」「3000 万参数」这类编造）
      - 含数字的要点必须带可验证的 evidence 原句（拦「客户留存率 58%」这类
        数字真实存在、但被搬到别的指标上的串号 —— 出处一晒就露馅）
      - 给了 evidence 但原文里找不到 → 一律丢弃
    """
    kept: list[dict] = []
    for p in points:
        text = p.get("point_text", "")
        ev = (p.get("evidence") or "").strip()
        bad = ungrounded_numbers(text, source_text)
        if bad:
            logger.warning("要点护栏：丢弃含原文中不存在数字 %s 的要点: %s", bad, text[:60])
            continue
        if ev and not evidence_found(ev, source_text):
            logger.warning("要点护栏：丢弃出处对不上原文的要点: %s", text[:60])
            continue
        if extract_numbers(text) and not ev:
            logger.warning("要点护栏：丢弃含数字但无出处的要点: %s", text[:60])
            continue
        kept.append(p)
    return kept


def _parse_keypoints_json(raw: str) -> list[dict]:
    """清洗 markdown 包裹 + 解析为受校验的要点 dict 列表。"""
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        items = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        logger.error("要点 JSON 解析失败: %s\n原文: %s", e, raw[:300])
        return []
    if not isinstance(items, list):
        return []

    out: list[dict] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("point_text"):
            continue
        weight = str(item.get("weight", "normal")).strip().lower()
        if weight not in _WEIGHTS:
            weight = "normal"
        try:
            kp = KeyPoint(
                point_no=str(i + 1),
                page_no=int(item.get("page_no", 0) or 0),
                point_text=str(item["point_text"]).strip(),
                weight=weight,
                evidence=str(item.get("evidence", "")).strip(),
            )
        except (ValidationError, ValueError, TypeError):
            continue
        out.append(kp.model_dump())
    return out
