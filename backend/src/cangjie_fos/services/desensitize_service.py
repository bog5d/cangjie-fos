"""文字稿脱敏（上传前防敏感信息外泄）。

背景：团队改用离线设备把录音转成文字稿，音频不再进系统（隐私 + 绕开不稳的本地 ASR）。
文字稿在**进入分析/存库/GitHub 同步之前**先脱敏。三类：
  1. identity —— 身份类：手机/身份证/银行卡/邮箱/座机（正则，通用）+ 团队维护的人名词典
  2. secret   —— 商业秘密：团队维护的产品代号/客户名/技术代号等词典
  3. military —— 涉军：内置涉军关键词起步表 + 团队自定义

**全程确定性（正则 + 词典），不调 LLM**——脱敏是安全底线，绝不能依赖会漂移的模型。
返回脱敏文本 + 命中清单供人工复核。原文不落库（hits 仅即时返回给操作者审核）。
"""
from __future__ import annotations

import re
import time
import uuid

from cangjie_fos.services.db_base import _connect

# ── 身份类正则（通用结构化）────────────────────────────────────────────────────
# 顺序敏感：先长后短，避免身份证被银行卡规则截断。
_IDENTITY_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("邮箱", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[邮箱]"),
    ("身份证", re.compile(r"[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"), "[身份证]"),
    ("银行卡", re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "[银行卡]"),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机]"),
    ("座机", re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)"), "[电话]"),
]

# ── 涉军关键词起步表（团队可在此基础上增补）──────────────────────────────────
# 保守：只放"军事实体/涉密"这类明确词，避免误伤普通业务表述。
_BUILTIN_MILITARY_TERMS: tuple[str, ...] = (
    "军方", "部队", "军工", "军品", "军用", "国防", "总装备部", "装备部",
    "涉密", "涉军", "保密资质", "武器", "导弹", "雷达", "军区", "作战部",
    "参谋部", "司令部", "军委", "军事科学院", "国防科工局",
)

_CATEGORY_DEFAULT_REPL = {
    "identity": "[人名]",
    "secret": "[商密]",
    "military": "[涉军]",
}


def _ensure_table() -> None:
    """幂等建团队脱敏词典表（隔离新表，不动既有迁移链）。"""
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS desensitize_terms (
                id          TEXT PRIMARY KEY,
                tenant_id   TEXT NOT NULL,
                category    TEXT NOT NULL,
                term        TEXT NOT NULL,
                replacement TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_desensitize_tenant ON desensitize_terms(tenant_id)"
        )


def add_term(tenant_id: str, category: str, term: str, replacement: str = "") -> str:
    """新增一条团队脱敏词条。category ∈ {identity, secret, military}。"""
    if category not in _CATEGORY_DEFAULT_REPL:
        raise ValueError(f"未知脱敏类别：{category}")
    term = (term or "").strip()
    if not term:
        raise ValueError("term 不能为空")
    repl = (replacement or "").strip() or _CATEGORY_DEFAULT_REPL[category]
    _ensure_table()
    tid = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO desensitize_terms (id, tenant_id, category, term, replacement, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (tid, tenant_id, category, term, repl, time.time()),
        )
    return tid


def list_terms(tenant_id: str, category: str = "") -> list[dict]:
    _ensure_table()
    with _connect() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM desensitize_terms WHERE tenant_id=? AND category=? ORDER BY created_at DESC",
                (tenant_id, category),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM desensitize_terms WHERE tenant_id=? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_term(term_id: str) -> None:
    _ensure_table()
    with _connect() as conn:
        conn.execute("DELETE FROM desensitize_terms WHERE id=?", (term_id,))


def _load_dict_rules(tenant_id: str, categories: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """汇总词典规则 (category, term, replacement)，含内置涉军表。长词优先。"""
    rules: list[tuple[str, str, str]] = []
    if "military" in categories:
        for t in _BUILTIN_MILITARY_TERMS:
            rules.append(("military", t, _CATEGORY_DEFAULT_REPL["military"]))
    for row in list_terms(tenant_id):
        if row["category"] in categories:
            rules.append((row["category"], row["term"], row["replacement"]))
    # 去重后按 term 长度降序，避免短词先替换切断长词
    seen = set()
    uniq = []
    for cat, term, repl in rules:
        key = (cat, term)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((cat, term, repl))
    uniq.sort(key=lambda x: -len(x[1]))
    return uniq


def desensitize(
    text: str,
    *,
    tenant_id: str = "default",
    categories: tuple[str, ...] = ("identity", "secret", "military"),
) -> dict:
    """对文字稿脱敏。返回 {masked_text, hits:[{category,type,original,masked}], count}。

    ⚠️ 只脱"身份/商密/涉军"，**绝不动业务数字**（金额/产品数/技术口径）——
    否则 BP-访谈口径比对这类靠数字的分析会失效。
    """
    if not text:
        return {"masked_text": "", "hits": [], "count": 0}

    hits: list[dict] = []
    masked = text

    # ① 身份类正则
    if "identity" in categories:
        for label, pat, repl in _IDENTITY_PATTERNS:
            def _sub(m, _label=label, _repl=repl):
                hits.append({"category": "identity", "type": _label,
                             "original": m.group(0), "masked": _repl})
                return _repl
            masked = pat.sub(_sub, masked)

    # ② 词典（身份人名 / 商密 / 涉军），长词优先
    for cat, term, repl in _load_dict_rules(tenant_id, categories):
        if term and term in masked:
            n = masked.count(term)
            masked = masked.replace(term, repl)
            type_label = {"identity": "人名/身份", "secret": "商业秘密", "military": "涉军"}[cat]
            for _ in range(n):
                hits.append({"category": cat, "type": type_label,
                             "original": term, "masked": repl})

    return {"masked_text": masked, "hits": hits, "count": len(hits)}
