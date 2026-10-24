"""语义召回沉淀词库测试（dd_semantic_cache）+ 与预筛的集成。

全部离线：联网 seam _llm_expand_requirement 一律 monkeypatch，不真调 API。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import dd_semantic_cache as sem


# ── 沉淀 + 离线扩展 ───────────────────────────────────────────────────────────

def test_learn_from_confirmation_creates_links():
    n = sem.learn_from_confirmation("营业执照", "工商登记证照扫描件.pdf")
    assert n > 0
    # 单次确认 → 权重 1，低于阈值(_MIN_WEIGHT=2)，离线扩展还不给
    assert sem.expand_from_cache(sem._bigrams("营业执照")) == set()


def test_two_confirmations_reach_threshold():
    sem.learn_from_confirmation("营业执照", "工商登记证照扫描件.pdf")
    sem.learn_from_confirmation("营业执照", "工商登记证照扫描件.pdf")  # 权重累加到 2
    exp = sem.expand_from_cache(sem._bigrams("营业执照"))
    assert exp, "两次确认后应能离线扩展出相关词"
    # 相关词应来自文件名里「需求没有的词」
    assert any(k in exp for k in ("工商", "登记", "证照", "扫描"))


def test_expand_empty_when_no_cache():
    assert sem.expand_from_cache(sem._bigrams("从未见过的需求")) == set()


def test_expand_ignores_original_keywords():
    """扩展结果不含需求自身的词（只补'换的说法'）。"""
    sem.learn_from_confirmation("营业执照", "营业执照副本扫描件.pdf")
    sem.learn_from_confirmation("营业执照", "营业执照副本扫描件.pdf")
    exp = sem.expand_from_cache(sem._bigrams("营业执照"))
    assert "营业" not in exp and "执照" not in exp


# ── 在线 seam：种词 + 成本闸 ──────────────────────────────────────────────────

def test_get_expansions_offline_returns_cache_only(monkeypatch):
    """联网失败（离线）→ 静默返回缓存，不报错。"""
    monkeypatch.setattr(sem, "_llm_expand_requirement", lambda req: [])
    sem.learn_from_confirmation("增值税申报表", "纳税申报_VAT_2023.pdf")
    sem.learn_from_confirmation("增值税申报表", "纳税申报_VAT_2023.pdf")
    base = sem._bigrams("增值税申报表")
    exp = sem.get_expansions("增值税申报表", base, allow_online=True)
    assert "纳税" in exp  # 来自缓存


def test_get_expansions_online_seeds_and_returns(monkeypatch):
    """网好 → 调 LLM 拿近义词，沉淀进词库且当轮返回。"""
    called = {}
    def fake_llm(req):
        called["req"] = req
        return ["纳税申报", "增值税", "VAT"]
    monkeypatch.setattr(sem, "_llm_expand_requirement", fake_llm)

    base = sem._bigrams("增值税申报表")
    exp = sem.get_expansions("增值税申报表", base, allow_online=True)
    assert called["req"] == "增值税申报表"
    assert "纳税申报" in exp and "VAT" in exp
    # 已沉淀，且用初始权重=阈值 → 下次纯离线也能查到
    cached = sem.expand_from_cache(base)
    assert "纳税申报" in cached


def test_get_expansions_sufficient_cache_skips_online(monkeypatch):
    """缓存已够（≥4）→ 不再联网调 API（省钱闸）。"""
    # 预置 4 个 weight≥2 的相关词
    for r in ("纳税申报", "税务登记", "完税凭证", "税单据"):
        sem.learn_link("增值", r, initial_weight=2)
    def boom(req):
        raise AssertionError("缓存够时不应联网")
    monkeypatch.setattr(sem, "_llm_expand_requirement", boom)
    exp = sem.get_expansions("增值税申报表", sem._bigrams("增值税申报表"), allow_online=True)
    assert len(exp) >= 4


def test_get_expansions_allow_online_false_never_calls(monkeypatch):
    def boom(req):
        raise AssertionError("allow_online=False 不应联网")
    monkeypatch.setattr(sem, "_llm_expand_requirement", boom)
    exp = sem.get_expansions("任意需求", sem._bigrams("任意需求"), allow_online=False)
    assert exp == set()


# ── 与 dd_match_service 预筛集成 ──────────────────────────────────────────────

def test_item_keywords_includes_cache_expansions():
    from cangjie_fos.services.dd_match_service import _item_keywords
    sem.learn_link("营业", "工商", initial_weight=2)
    kws = _item_keywords({"requirement": "营业执照"})
    assert "工商" in kws


def test_prefilter_recalls_paraphrased_file():
    """核心价值：靠沉淀词库把「一个 bigram 都不重合」的文件召回候选池。"""
    from cangjie_fos.services.dd_match_service import _prefilter_files_for_batch
    # 需求「营业执照」，目标文件叫「工商登记证」——字面零重合
    for r in ("工商", "登记"):
        sem.learn_link("营业", r, initial_weight=2)
        sem.learn_link("执照", r, initial_weight=2)
    index_rows = [
        {"filename": "无关的产品手册.pdf", "summary": ""},
        {"filename": "工商登记证.pdf", "summary": ""},
    ]
    batch = [{"id": "1", "requirement": "营业执照"}]
    # top_n=1 强制走打分选择（否则文件数≤top_n会全量返回）
    picked = _prefilter_files_for_batch(batch, index_rows, top_n=1)
    names = [r["filename"] for r in picked]
    assert "工商登记证.pdf" in names, "沉淀词库应把改了说法的文件召回"


def test_record_decisions_sediments_semantic_link():
    """确认导出 → record_session_decisions 顺手把语义关联沉淀进词库。"""
    from cangjie_fos.services.dd_match_service import record_session_decisions
    from cangjie_fos.services.db_base import _connect
    import time as _t

    with _connect() as conn:
        conn.execute(
            "INSERT INTO dd_match_sessions (session_id, tenant_id, institution_name, created_at) "
            "VALUES ('s1','zt','红杉',?)", (_t.time(),))
        conn.execute(
            "INSERT INTO dd_match_items (id, session_id, item_no, requirement, "
            "matched_file_path, matched_filename, user_confirmed, decisions_recorded) "
            "VALUES ('i1','s1','1','营业执照','/x/工商登记证.pdf','工商登记证.pdf',1,0)")
    record_session_decisions("s1")
    # 需求词 → 文件独特词 应已入库
    exp = sem.expand_from_cache(sem._bigrams("营业执照"))
    # 单次确认权重1 < 阈值2，这里直接查原始链接存在即可
    from cangjie_fos.services.db_base import _connect as _c
    with _c() as conn:
        rows = conn.execute("SELECT related FROM dd_semantic_links WHERE term IN ('营业','执照')").fetchall()
    assert any(r["related"] in ("工商", "登记", "记证", "证") for r in rows)
