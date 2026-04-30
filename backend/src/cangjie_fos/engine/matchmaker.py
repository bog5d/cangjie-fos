"""
MatchMaker V5.0 — 尽调响应台匹配引擎（迁自 AI_CangJie_FSS/src/matchmaker_v5.py）。

核心流程：
  Step 1：解析机构尽调需求清单（LLM 一次调用，或启发式降级）
  Step 2：本地 BM25 关键词检索 asset 列表（零 LLM 成本，零延迟）
  Step 3：绿/黄/红/灰 四色匹配结果

颜色语义：
  绿（green）：置信度 >= 0.70，可自动选中
  黄（yellow）：置信度 0.40~0.70，建议人工确认
  红（red）：置信度 < 0.40，匹配度低，建议人工指定
  灰（gray）：完全没有匹配，触发资产缺失预警

设计原则：
  - 纯标准库，零额外依赖（os / json / re / math / collections）
  - LLM 只用于 Step 1 需求解析，失败自动降级为启发式行分割
  - 所有核心函数为纯函数，易于单元测试
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ─── 颜色常量 ────────────────────────────────────────────────────────────────

COLOR_GREEN  = "green"
COLOR_YELLOW = "yellow"
COLOR_RED    = "red"
COLOR_GRAY   = "gray"

THRESHOLD_GREEN  = 0.70
THRESHOLD_YELLOW = 0.40


# ─── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class RequirementItem:
    """机构尽调需求中的一条需求。"""
    description: str
    scene_type: str = ""
    time_range: str = ""


@dataclass
class MatchCandidate:
    """一条需求对应的一个候选文件。"""
    asset: dict
    score: float
    color: str
    matched_fields: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    """一条需求的完整匹配结果。"""
    requirement: RequirementItem
    candidates: list[MatchCandidate]

    @property
    def color(self) -> str:
        if not self.candidates:
            return COLOR_GRAY
        return self.candidates[0].color

    @property
    def best_candidate(self) -> Optional[MatchCandidate]:
        return self.candidates[0] if self.candidates else None


# ─── LLM 需求解析（Step 1）────────────────────────────────────────────────────

_LLM_PARSE_PROMPT = """你是一个尽调材料清单解析助手。
将以下文本解析为结构化 JSON 数组，每条需求一个对象，包含字段：
  - 需求描述（string，必填）
  - 场景类型（string，从以下选：财务审计|税务合规|资产负债|股权结构|知识产权|工商资质|合规诉讼|商业模式|产品介绍|市场分析|高管背景|团队资质|融资协议|客户合同|供应商合同|其他）
  - 时间范围（string，如 "2022-2024"，无则填空字符串）

只输出 JSON 数组，不要解释。

待解析文本：
{text}"""


def _call_llm_parse(text: str, api_key: str = "") -> str:
    """调用 DeepSeek LLM 解析需求清单，返回原始文本。外部可 mock 此函数进行测试。"""
    try:
        import requests  # noqa: PLC0415
        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise ValueError("未配置 DEEPSEEK_API_KEY")
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": _LLM_PARSE_PROMPT.format(text=text)}],
                "max_tokens": 1024,
                "temperature": 0.1,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"LLM 调用失败：{exc}") from exc


def parse_requirements_heuristic(text: str) -> list[RequirementItem]:
    """启发式解析：按行分割，去除序号前缀。LLM 不可用时的降级方案。"""
    if not text or not text.strip():
        return []
    _prefix = re.compile(
        r"^(?:[一二三四五六七八九十百]+[、。．\.]?\s*|"
        r"\d+[\.、)）\]】\s]\s*|"
        r"[a-zA-Z][\.、)）]\s*)"
    )
    items: list[RequirementItem] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = _prefix.sub("", line).strip()
        if line:
            items.append(RequirementItem(description=line))
    return items


def parse_requirements_from_text(
    text: str,
    use_llm: bool = False,
    api_key: str = "",
) -> list[RequirementItem]:
    """主解析入口。use_llm=True 先尝试 LLM，失败降级启发式；默认 False（零成本）。"""
    if not use_llm:
        return parse_requirements_heuristic(text)
    try:
        raw = _call_llm_parse(text, api_key)
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            raise ValueError("未找到 JSON 数组")
        data = json.loads(match.group())
        items = []
        for obj in data:
            desc = str(obj.get("需求描述") or obj.get("description") or "").strip()
            if not desc:
                continue
            items.append(RequirementItem(
                description=desc,
                scene_type=str(obj.get("场景类型") or obj.get("scene_type") or "").strip(),
                time_range=str(obj.get("时间范围") or obj.get("time_range") or "").strip(),
            ))
        return items if items else parse_requirements_heuristic(text)
    except Exception:
        logger.debug("LLM 解析失败，降级为启发式", exc_info=True)
        return parse_requirements_heuristic(text)


# ─── 本地关键词匹配（Step 2）──────────────────────────────────────────────────

def _extract_keywords(text: str) -> list[str]:
    """提取有意义的关键词：4位年份 + 中文词组(2-6字) + ASCII词。"""
    if not text:
        return []
    keywords: set[str] = set()
    for year in re.findall(r'\d{4}', text):
        keywords.add(year)
    for seg in re.split(r'\d+', text):
        for phrase in re.findall(r'[一-鿿]{2,6}', seg):
            keywords.add(phrase)
    for word in re.findall(r'[a-zA-Z]{3,}', text):
        keywords.add(word.lower())
    return [k for k in keywords if len(k) >= 2]


def _tokenize(text: str) -> list[str]:
    return _extract_keywords(text)


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    avg_doc_len: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """BM25 单文档得分（纯标准库，k1=1.5，b=0.75，IDF简化版）。"""
    if not doc_tokens or not query_tokens:
        return 0.0
    doc_tf = Counter(doc_tokens)
    doc_len = len(doc_tokens)
    score = 0.0
    for token in set(query_tokens):
        tf = doc_tf.get(token, 0)
        if tf == 0:
            continue
        idf = math.log(1 + 1.0 / (0 + 0.5))
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / max(avg_doc_len, 1)))
        score += idf * tf_norm
    return score


def _score_asset_for_requirement(
    req: RequirementItem,
    asset: dict,
    avg_doc_len: float = 20.0,
) -> tuple[float, list[str]]:
    """BM25 计算单个 asset 对 requirement 的匹配分（0.0~1.0）。
    字段权重：tags×3.0  filename×2.0  summary×1.5。
    """
    q_tokens = _tokenize(req.description)
    if req.scene_type:
        q_tokens.extend(_tokenize(req.scene_type))
    if req.time_range:
        q_tokens.extend(re.findall(r'\d{4}', req.time_range))
    if not q_tokens:
        return 0.0, []

    filename  = str(asset.get("filename") or "")
    summary   = str(asset.get("summary") or "")
    tags_raw  = asset.get("tags") or []
    tags_str  = " ".join(str(t) for t in tags_raw)

    fn_tokens  = _tokenize(filename)
    sum_tokens = _tokenize(summary)
    tag_tokens = _tokenize(tags_str)

    raw_fn  = _bm25_score(q_tokens, fn_tokens,  avg_doc_len) * 2.0
    raw_sum = _bm25_score(q_tokens, sum_tokens, avg_doc_len) * 1.5
    raw_tag = _bm25_score(q_tokens, tag_tokens, avg_doc_len) * 3.0
    total_raw = raw_fn + raw_sum + raw_tag

    idf_unit = math.log(1 + 1.0 / 0.5)
    max_raw = idf_unit * (2.0 + 1.5 + 3.0) * len(set(q_tokens))
    score = min(1.0, total_raw / max(max_raw, 1e-9))

    matched_fields: list[str] = []
    if raw_fn > 0:  matched_fields.append("filename")
    if raw_sum > 0: matched_fields.append("summary")
    if raw_tag > 0: matched_fields.append("tags")
    return score, matched_fields


def match_requirement_to_assets(
    req: RequirementItem,
    assets: list[dict],
    top_n: int = 3,
) -> list[MatchCandidate]:
    """对单条需求，在 assets 列表中找最匹配的 Top-N 文件。"""
    if not assets:
        return []
    all_lengths = [
        len(_tokenize(str(a.get("summary") or "") + " " + str(a.get("filename") or "")))
        for a in assets
    ]
    avg_len = sum(all_lengths) / len(all_lengths) if all_lengths else 20.0

    scored: list[tuple[float, dict, list[str]]] = []
    for asset in assets:
        score, fields = _score_asset_for_requirement(req, asset, avg_doc_len=avg_len)
        if score > 0:
            scored.append((score, asset, fields))

    scored.sort(key=lambda x: x[0], reverse=True)
    candidates: list[MatchCandidate] = []
    for score, asset, fields in scored[:top_n]:
        if score >= THRESHOLD_GREEN:
            color = COLOR_GREEN
        elif score >= THRESHOLD_YELLOW:
            color = COLOR_YELLOW
        else:
            color = COLOR_RED
        candidates.append(MatchCandidate(asset=asset, score=score, color=color, matched_fields=fields))
    return candidates


def run_matching(
    requirements: list[RequirementItem],
    assets: list[dict],
    top_n: int = 3,
) -> list[MatchResult]:
    """批量匹配所有需求，返回 MatchResult 列表（与 requirements 等长）。"""
    return [
        MatchResult(
            requirement=req,
            candidates=match_requirement_to_assets(req, assets, top_n=top_n),
        )
        for req in requirements
    ]


# ─── 序列化辅助（供 DB / API 使用）──────────────────────────────────────────

def requirement_to_dict(r: RequirementItem) -> dict:
    return {"description": r.description, "scene_type": r.scene_type, "time_range": r.time_range}


def candidate_to_dict(c: MatchCandidate) -> dict:
    return {
        "asset": c.asset,
        "score": round(c.score, 4),
        "color": c.color,
        "matched_fields": c.matched_fields,
    }


def result_to_dict(r: MatchResult) -> dict:
    return {
        "requirement": requirement_to_dict(r.requirement),
        "candidates": [candidate_to_dict(c) for c in r.candidates],
        "color": r.color,
    }


# ─── 格式化工具 ──────────────────────────────────────────────────────────────

_COLOR_EMOJI = {COLOR_GREEN: "✅", COLOR_YELLOW: "⚠️", COLOR_RED: "🔴", COLOR_GRAY: "⬜"}


def format_matching_report(results: list[MatchResult]) -> str:
    """格式化匹配报告为易读文本。"""
    lines = [
        "=" * 56,
        "   尽调响应台 MatchMaker V5.0 — 匹配报告",
        "=" * 56,
        f"需求条数：{len(results)}",
        f"  ✅绿色：{sum(1 for r in results if r.color == COLOR_GREEN)}  "
        f"⚠️黄色：{sum(1 for r in results if r.color == COLOR_YELLOW)}  "
        f"🔴红色：{sum(1 for r in results if r.color == COLOR_RED)}  "
        f"⬜灰色（缺失）：{sum(1 for r in results if r.color == COLOR_GRAY)}",
        "",
    ]
    for i, r in enumerate(results, 1):
        emoji = _COLOR_EMOJI.get(r.color, "•")
        lines.append(f"{emoji} 需求 {i}：{r.requirement.description}")
        if r.requirement.scene_type:
            lines.append(f"   场景类型：{r.requirement.scene_type}")
        if r.candidates:
            for j, c in enumerate(r.candidates[:2], 1):
                lines.append(
                    f"   候选{j}：{c.asset.get('filename', '')}  "
                    f"[{c.score:.0%}] [{c.color}]"
                )
        else:
            lines.append("   ⚠️ 未找到匹配文件（资产缺失预警）")
        lines.append("")
    lines.append("=" * 56)
    return "\n".join(lines)
