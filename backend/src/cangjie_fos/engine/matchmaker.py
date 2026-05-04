"""
MatchMaker V5.1 — 尽调响应台匹配引擎（Skill 协议版）。

核心流程：
  Step 1：解析机构尽调需求清单（LLM 一次调用，或启发式降级）
  Step 2：本地 BM25 关键词检索 asset 列表（零 LLM 成本，零延迟）
  Step 2.5：机构历史偏好加权（来自 match_outcomes 表的真实反馈）
  Step 3：绿/黄/红/灰 四色匹配结果

颜色语义：
  绿（green）：置信度 >= 0.70，可自动选中
  黄（yellow）：置信度 0.40~0.70，建议人工确认
  红（red）：置信度 < 0.40，匹配度低，建议人工指定
  灰（gray）：完全没有匹配，触发资产缺失预警

Skill 协议设计（MatcherSkill Protocol）：
  - 所有匹配实现遵循统一接口，调用方无需感知底层算法
  - 当前实现：BM25MatcherSkill（纯标准库，零延迟）
  - 未来可无缝替换：BM25+LLM重排序 → 全LLM推理
  - 通过 get_default_matcher() 工厂获取当前最优实现

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
from typing import Optional, Protocol, runtime_checkable

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


# ─── MatcherSkill 协议（所有匹配实现必须遵循此接口）────────────────────────────

@runtime_checkable
class MatcherSkill(Protocol):
    """匹配器技能协议。

    遵循此接口可让底层匹配算法无缝替换，调用方代码永远不变。

    进化路径::

        BM25MatcherSkill（现在）
            ↓ 积累 match_outcomes 数据
        BM25 + 机构历史偏好加权（V5.1，当前）
            ↓ 数据量够时接 LLM 重排序层
        BM25 召回 + LLM 精排（V5.2，下一步）
            ↓ 路演结束后自动触发
        全自动主动匹配（V6.0，最终形态）
    """

    def match(
        self,
        requirements: list[RequirementItem],
        assets: list[dict],
        institution: str = "",
        institution_profile: dict | None = None,
        top_n: int = 5,
    ) -> list[MatchResult]:
        """执行匹配，返回有序结果列表。

        Args:
            requirements: 解析后的需求条目列表
            assets: 候选资产列表（来自 db_assets_list）
            institution: 机构名称（仅用于日志，实际加权由 institution_profile 驱动）
            institution_profile: 机构历史偏好画像（由调用方从 DB 注入）。
                期望结构：{
                    "preferred_paths": list[str],   # 历史被选中文件的 relative_path
                    "preferred_tags": list[str],    # 历史被选中文件的 tags 聚合
                    "total_sessions": int,
                }
            top_n: 每条需求最多返回几个候选
        Returns:
            MatchResult 列表，与 requirements 一一对应
        """
        ...


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
    for word in re.findall(r'[a-zA-Z]{2,}', text):
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


# ─── 机构历史偏好加权（Step 2.5）──────────────────────────────────────────────

def _compute_boost_factor(institution_profile: dict | None) -> float:
    """根据机构历史匹配次数动态计算 boost_factor。

    数据量越多，历史偏好越可信，加权越大：

    ==================  ================  =============================
    历史匹配次数        boost_factor      说明
    ==================  ================  =============================
    0-3 次              1.0               数据太少，偏好不可信，不加权
    4-10 次             1.2               轻微偏好，保留探索空间
    11-30 次            1.3               偏好稳定，信任历史（原固定值）
    30+ 次              1.5               高度稳定，大力加权
    ==================  ================  =============================
    """
    if not institution_profile:
        return 1.0
    sessions = institution_profile.get("total_sessions", 0) or 0
    if sessions <= 3:
        return 1.0
    if sessions <= 10:
        return 1.2
    if sessions <= 30:
        return 1.3
    return 1.5


def _apply_institution_boost(
    scored: list[tuple[float, dict, list[str]]],
    institution_profile: dict | None,
    boost_factor: float = 1.3,
) -> list[tuple[float, dict, list[str]]]:
    """根据机构历史 match_outcomes 数据，对候选文件做偏好加权。

    加权逻辑：
      - 文件 relative_path 出现在历史 preferred_paths → ×boost_factor
      - 文件 tags 与历史 preferred_tags 有交集 → ×boost_factor
      - 两者都满足也只加一次（避免双倍膨胀）

    boost_factor 默认 1.3（保守）：既能让历史偏好文件排名靠前，
    又不会因一两次历史记录完全压制新文件。数据积累到 10+ 次后可调高到 1.5。
    """
    if not institution_profile:
        return scored
    preferred_paths = set(institution_profile.get("preferred_paths") or [])
    preferred_tags = set(institution_profile.get("preferred_tags") or [])
    if not preferred_paths and not preferred_tags:
        return scored

    result: list[tuple[float, dict, list[str]]] = []
    for score, asset, fields in scored:
        path = asset.get("relative_path", "")
        tags = set(asset.get("tags") or [])
        if path in preferred_paths or (tags & preferred_tags):
            result.append((score * boost_factor, asset, fields + ["[机构历史偏好↑]"]))
        else:
            result.append((score, asset, fields))
    result.sort(key=lambda x: x[0], reverse=True)
    return result


# ─── BM25MatcherSkill（当前默认实现）──────────────────────────────────────────

class BM25MatcherSkill:
    """基于 BM25 + 机构历史偏好加权的匹配器。

    实现 MatcherSkill 协议。可通过 get_default_matcher() 获取实例。

    内部流程：
      1. 为每条需求对所有资产做 BM25 评分
      2. 如果传入 institution_profile，对历史偏好文件做加权
      3. 取 Top-N，分配颜色
    """

    def match(
        self,
        requirements: list[RequirementItem],
        assets: list[dict],
        institution: str = "",
        institution_profile: dict | None = None,
        top_n: int = 5,
    ) -> list[MatchResult]:
        return [
            MatchResult(
                requirement=req,
                candidates=self._match_one(req, assets, institution_profile, top_n),
            )
            for req in requirements
        ]

    def _match_one(
        self,
        req: RequirementItem,
        assets: list[dict],
        institution_profile: dict | None,
        top_n: int,
    ) -> list[MatchCandidate]:
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

        # Step 2.5：机构历史偏好加权（boost_factor 根据历史数据量动态调整）
        boost = _compute_boost_factor(institution_profile)
        scored = _apply_institution_boost(scored, institution_profile, boost_factor=boost)

        candidates: list[MatchCandidate] = []
        for score, asset, fields in scored[:top_n]:
            capped = min(1.0, score)  # boost 后分数可能超过 1.0，截断
            if capped >= THRESHOLD_GREEN:
                color = COLOR_GREEN
            elif capped >= THRESHOLD_YELLOW:
                color = COLOR_YELLOW
            else:
                color = COLOR_RED
            candidates.append(
                MatchCandidate(asset=asset, score=capped, color=color, matched_fields=fields)
            )
        return candidates


def get_default_matcher() -> BM25MatcherSkill:
    """获取当前默认匹配器实例。

    工厂函数，隔离调用方与具体实现。未来升级到 LLMMatcherSkill 只需改这里。
    """
    return BM25MatcherSkill()


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
