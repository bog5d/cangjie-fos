"""语义召回沉淀词库 —— 让「换了说法」的文件也能被召回。

背景（prefilter_miss 根因）：尽调预筛靠汉字二元组关键词，需求和文件用词不
重叠（近义/术语/简称）就召不回。例：需求「增值税申报表」，文件名叫「纳税申报_
VAT」，一个 bigram 都不重合 → 文件进不了候选池 → 漏召回。

设计（王波定的三段兜底，2026-08）：
  1. 网好 → 用 LLM 把需求扩展出相关词（愿意花点钱）。
  2. 用的过程中 → 把「需求词 → 相关词」持续沉淀进本地 dd_semantic_links（无人工维护）。
  3. 网烂 → 直接用沉淀好的词库兜底扩展，不联网也能召回。

本质是「把贵的语义结果缓存下来，离线时降级用缓存」。词库越用越厚，联网调用
越来越少（缓存够了就不调 API）。

沉淀来源有二：
  - **确认即学**：record_session_decisions 里每条人工确认的「需求↔文件」都调
    learn_from_confirmation()，把文件名里的独特词沉淀为该需求词的相关词。
  - **联网扩展**：get_expansions() 冷查询时调 LLM 拿近义词，顺手沉淀。

安全：本模块只做召回（放宽候选池），不做判定——精度仍由下游全文精判把关，
所以「多召回几个」低风险；宁可多进池，不可漏。
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from cangjie_fos.services.db_base import _connect

_log = logging.getLogger(__name__)

# 与 dd_match_service 保持一致的停用字（语义稀薄、无区分度）
_STOP_CHARS = set("的和与或等及提供相关情况说明文件资料证明（）、，。是有无")

# 沉淀时每侧关键词上限，防止一次学习产生过多笛卡尔积链接
_MAX_TERMS_PER_SIDE = 10
# 扩展命中所需最小权重（沉淀次数），过滤偶发噪音
_MIN_WEIGHT = 2
# 单次扩展返回的相关词上限
_MAX_EXPANSIONS = 12
# 缓存扩展达到此数即认为「够用」，不再联网调 LLM（控制成本的闸）
_SUFFICIENT_CACHED = 4


def _bigrams(text: str) -> set[str]:
    """二元组关键词（剔除含停用字的组合）。与 dd_match_service._requirement_bigrams 同规则
    （需求侧查词用，需和预筛 kws 对齐，故不强制汉字）。"""
    out: set[str] = set()
    for i in range(len(text) - 1):
        bg = text[i : i + 2]
        if not any(c in _STOP_CHARS for c in bg):
            out.add(bg)
    return out


def _is_han(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def _han_bigrams(text: str) -> set[str]:
    """纯汉字二元组——用于「相关词」侧，剔除扩展名/数字/英文缩写等噪音
    （如文件名 '纳税申报_VAT_2023.pdf' 只取 纳税/税申/申报，不要 .p/df/20/VA）。"""
    out: set[str] = set()
    for i in range(len(text) - 1):
        a, b = text[i], text[i + 1]
        if _is_han(a) and _is_han(b) and a not in _STOP_CHARS and b not in _STOP_CHARS:
            out.add(a + b)
    return out


# ── 沉淀 ─────────────────────────────────────────────────────────────────────

def learn_link(term: str, related: str, *, source: str = "match",
               initial_weight: int = 1, conn=None) -> None:
    """把一条「需求词 term → 相关词 related」写入词库（已存在则权重+1）。

    initial_weight：首次插入的初始权重。确认沉淀用 1（需跨机构再确认一次才够阈值、
    抗噪）；联网 LLM 近义词质量高、且只影响召回，用 _MIN_WEIGHT 让它当轮即可用。
    """
    term = (term or "").strip()
    related = (related or "").strip()
    if not term or not related or term == related:
        return
    own = conn is None
    if own:
        conn = _connect()
    try:
        now = time.time()
        cur = conn.execute(
            "SELECT weight FROM dd_semantic_links WHERE term = ? AND related = ?",
            (term, related),
        ).fetchone()
        if cur:
            conn.execute(
                "UPDATE dd_semantic_links SET weight = weight + 1, updated_at = ?, source = ? "
                "WHERE term = ? AND related = ?",
                (now, source, term, related),
            )
        else:
            conn.execute(
                "INSERT INTO dd_semantic_links (term, related, weight, source, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (term, related, max(1, initial_weight), source, now),
            )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def learn_from_confirmation(requirement: str, filename: str, summary: str = "", *, conn=None) -> int:
    """从一条已确认的「需求↔文件」学习：需求词 → 文件独特词。

    文件独特词 = 文件名/摘要的 bigram 中、不在需求里的那些（正是「换的说法」）。
    返回新建/累加的链接数。
    """
    req_terms = list(_bigrams(requirement))[:_MAX_TERMS_PER_SIDE]
    # 相关词只取纯汉字（剔除扩展名/数字/英文噪音），并去掉需求里已有的词
    file_terms = _han_bigrams(f"{filename} {summary}") - _bigrams(requirement)
    file_terms = list(file_terms)[:_MAX_TERMS_PER_SIDE]
    if not req_terms or not file_terms:
        return 0
    own = conn is None
    if own:
        conn = _connect()
    n = 0
    try:
        for t in req_terms:
            for r in file_terms:
                learn_link(t, r, source="match", conn=conn)
                n += 1
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return n


# ── 扩展（召回时用）───────────────────────────────────────────────────────────

def expand_from_cache(keywords: set[str], *, conn=None) -> set[str]:
    """纯离线：从沉淀词库为一组需求词查出相关词（weight ≥ 阈值）。"""
    kws = [k for k in keywords if k]
    if not kws:
        return set()
    own = conn is None
    if own:
        conn = _connect()
    try:
        placeholders = ",".join("?" * len(kws))
        # 阈值作用在**单条链接**权重上（同一 term→related 被确认/种词 ≥N 次才算数），
        # 而不是跨多个需求词求和——否则一次确认里多个需求词都指向同一相关词会被误当"多次证实"。
        rows = conn.execute(
            f"SELECT related, MAX(weight) AS w FROM dd_semantic_links "
            f"WHERE term IN ({placeholders}) AND weight >= ? GROUP BY related "
            f"ORDER BY w DESC LIMIT ?",
            (*kws, _MIN_WEIGHT, _MAX_EXPANSIONS),
        ).fetchall()
    finally:
        if own:
            conn.close()
    return {r["related"] for r in rows if r["related"] not in keywords}


def _llm_expand_requirement(requirement: str) -> list[str]:
    """联网 seam：让 LLM 给需求扩展近义词/术语/简称（best-effort，单次不重试）。

    离线或无 Key 时快速失败返回 []（不 raise、不拖住调用方）。测试里被 monkeypatch。
    """
    req = (requirement or "").strip()
    if not req:
        return []
    try:
        from cangjie_fos.services.dd_llm_client import get_dd_llm_client  # noqa: PLC0415

        client = get_dd_llm_client()  # 无 Key 会 raise → 下面兜住
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content":
                 "你是尽调材料检索助手。给定一条材料需求，列出它在文件命名里"
                 "可能出现的近义词、专业术语、常见简称/英文缩写。只输出词，用中文"
                 "逗号分隔，不超过8个，不要解释。"},
                {"role": "user", "content": req},
            ],
            temperature=0,
            timeout=8,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        _log.debug("语义扩展联网失败（降级用缓存）：%s", e)
        return []
    # 解析：中英文逗号/顿号/换行分隔
    import re  # noqa: PLC0415

    parts = re.split(r"[,，、\n;；]+", text)
    return [p.strip() for p in parts if p.strip()][:8]


def get_expansions(
    requirement: str,
    base_keywords: set[str],
    *,
    allow_online: bool = True,
    conn=None,
) -> set[str]:
    """召回扩展词：优先用沉淀词库；不够且允许联网时调 LLM 并顺手沉淀。

    - 缓存已够（≥ _SUFFICIENT_CACHED）→ 直接返回缓存，不联网（省钱）。
    - 缓存不够且 allow_online → 调 LLM 拿近义词，沉淀进词库，合并返回。
    - 联网失败（离线）→ 静默返回缓存。
    """
    own = conn is None
    if own:
        conn = _connect()
    try:
        cached = expand_from_cache(base_keywords, conn=conn)
        if not allow_online or len(cached) >= _SUFFICIENT_CACHED:
            return cached
        synonyms = _llm_expand_requirement(requirement)
        if synonyms:
            # 沉淀：需求词 → 每个近义词（source=online，当轮即可用 → initial_weight=阈值）
            for t in list(base_keywords)[:_MAX_TERMS_PER_SIDE]:
                for syn in synonyms:
                    learn_link(t, syn, source="online", initial_weight=_MIN_WEIGHT, conn=conn)
            if own:
                conn.commit()
        return cached | {s for s in synonyms if s not in base_keywords}
    finally:
        if own:
            conn.close()
