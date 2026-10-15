"""召回与判定链回归（WP7 独立验收 D-1 / D-4）。

D-4（最严重）：召回只从 ``doc_type`` 取词，义务原文一个词都不用。
大量尽调要求识别不出 ``doc_type``（如「请说明实际控制人及股权结构」），
于是 ``terms=[]`` → **一次 FTS 查询都不发** → 恒 0 召回 → 恒判 MISSING。
失败方向是 fail-closed（不会误交付），但输出的是**自信的错误答案**：
材料就在库里、索引也建好了，只是没去查，用户会照着去追不存在的缺口。

D-1：``judge`` 把 ``not results`` 短路成 MISSING，排在
「要求主体范围却无权威名单 → UNCERTAIN」之前，该规则永远执行不到。
D-1 与 D-4 是同一条链上的两点：修一半不够。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_requirement_service as rq


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    # 统一加载测试策略：PUBLIC 可外发，其余不可；避免「无策略全拒」淹没断言
    p = Path(tmp_path) / "_policy.json"
    p.write_text(
        '{"policy_version":"t","default_level":"RESTRICTED","levels":{'
        '"PUBLIC":{"externally_sendable":true,"requires_review":true},'
        '"INTERNAL":{"externally_sendable":false,"requires_review":true},'
        '"CONFIDENTIAL":{"externally_sendable":false,"requires_review":true},'
        '"RESTRICTED":{"externally_sendable":false,"requires_review":true}},"rules":[]}',
        encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(p))
    mf.close_all()
    yield
    mf.close_all()


def _seed(tmp_path, files: dict[str, str]):
    lib = "L"
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    mf.register_library(lib, str(root), authorized_by="t", db_path=None)
    for rel, content in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    mf.build_manifest(lib, db_path=None)
    ps.parse_pending_batch(lib, db_path=None)
    cs.build_cards_for_library(lib, db_path=None)
    return lib


# ── D-4：召回必须用义务原文 ───────────────────────────────────────────────
def test_doc_type_empty_but_text_has_terms_still_recalls(tmp_path):
    """**本文件的核心回归**：doc_type 为空、原文含可命中词时，召回不得为 0。"""
    lib = _seed(tmp_path, {
        "股权结构说明.txt": "实际控制人及股权结构说明\n本公司实际控制人为自然人，"
                          "通过两层持股架构控制被投企业。\n",
    })
    rq.ingest_checklist(lib, [{"item_no": "L2", "raw_text": "请说明实际控制人及股权结构"}],
                        db_path=None)
    obl = rq.list_obligations(lib, db_path=None)[0]
    assert obl["doc_type"] == "", "前置条件：这条识别不出 doc_type"

    st = ms.match_obligation(lib, obl["obligation_id"], db_path=None)
    assert st["candidate_count"] > 0, "doc_type 为空也必须靠原文召回"
    assert st["recall_terms"], "必须记录实际用了哪些检索词"
    assert st["actually_searched"] is True


def test_unmapped_doc_type_returns_empty_not_english_key():
    """未映射的 doc_type 必须返回空列表，不能把英文 key 拿去搜中文语料。"""
    assert rq.doc_type_search_terms("financial_report") == []
    assert rq.doc_type_search_terms("完全不存在的类型") == []
    assert rq.doc_type_search_terms("") == []
    # 已映射的仍要正常翻译
    assert "审计报告" in rq.doc_type_search_terms("audit_report")


def test_text_search_terms_drops_request_verbs():
    """抽词要剥掉「请提供」这类请求前缀，否则全是无意义碎片。"""
    terms = rq.text_search_terms("请说明实际控制人及股权结构")
    assert terms, "应抽出可命中词"
    assert not any(t.startswith("请") for t in terms), terms
    assert not any(t == "提供" for t in terms), terms


def test_recall_prefers_doctype_terms_over_text(tmp_path):
    """doc_type 词与原文词同时存在时，两者都要用（doc_type 优先）。"""
    lib = _seed(tmp_path, {"审计报告.md": "本报告为2023年度审计结论。\n"})
    rq.ingest_checklist(lib, [{"item_no": "A", "raw_text": "请提供2023年度审计报告"}],
                        db_path=None)
    obl = rq.list_obligations(lib, db_path=None)[0]
    assert obl["doc_type"] == "audit_report"
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=None)
    assert "审计报告" in st["recall_terms"], "doc_type 词应优先使用"
    assert st["candidate_count"] > 0


# ── D-1：「没查」与「查了没有」必须分开 ───────────────────────────────────
def test_group_scope_without_registry_is_uncertain_not_missing(tmp_path):
    """要求「集团及下属公司」但无权威名单 → UNCERTAIN，不是 MISSING。"""
    lib = _seed(tmp_path, {"子公司甲/说明.txt": "集团及下属公司的组织架构见附件。\n"})
    rq.ingest_checklist(lib, [{"item_no": "L3", "raw_text": "请提供集团及下属公司的完整组织架构"}],
                        db_path=None)
    obl = rq.list_obligations(lib, db_path=None)[0]
    assert obl["entity_scope"] == "group_and_subs"
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=None)
    assert st["verdict"] == ms.V_UNCERTAIN, "无权威名单时不得判缺材料"
    assert "权威主体名单" in st["missing_detail"]


def test_no_recall_terms_is_uncertain_not_missing(tmp_path):
    """连检索词都提不出来 = **没真正查过**，判 UNCERTAIN 而非 MISSING。"""
    lib = _seed(tmp_path, {"x.txt": "正文\n"})
    rq.ingest_checklist(lib, [{"item_no": "Z", "raw_text": "请提供"}], db_path=None)
    obl = rq.list_obligations(lib, db_path=None)[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=None)
    assert st["recall_terms"] == []
    assert st["actually_searched"] is False
    assert st["verdict"] == ms.V_UNCERTAIN, "没查过不能断言缺材料"
    assert "没有真正检索过" in st["missing_detail"]


def test_genuinely_searched_and_absent_is_missing(tmp_path):
    """确实检索了、确实没有 → MISSING（这条不能被改坏）。"""
    lib = _seed(tmp_path, {"营业执照.txt": "营业执照正文\n"})
    rq.ingest_checklist(lib, [{"item_no": "A", "raw_text": "请提供发明专利证书"}],
                        db_path=None)
    obl = rq.list_obligations(lib, db_path=None)[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=None)
    assert st["actually_searched"] is True
    assert st["verdict"] == ms.V_MISSING


# ── D-5：取词不得系统性偏向句首 ───────────────────────────────────────────
def test_tail_keyword_is_kept_in_recall_terms():
    """**D-5 核心回归**：关键名词只在句尾时，取词必须够得到。

    原实现「4 字滑窗 + 只留前 6 个」从位置 0 顺序生成，
    截断后**只覆盖句首约 9 个字**，句尾信息永远取不到：

        「请说明实际控制人及股权结构」
          → ['实际控制','际控制人','控制人及','制人及股','人及股权','及股权结']
          没有「股权结构」

    这是「碰巧对」不是「设计上对」：只要关键词不在句首那 6 个窗口内就 0 召回，
    而判定仍是 MISSING —— **自信的错误答案**，用户会去追不存在的缺口。
    """
    terms = rq.text_search_terms("请说明实际控制人及股权结构")
    assert "股权结构" in terms, f"句尾关键词被丢弃：{terms}"


def test_recall_covers_all_units_across_the_sentence():
    """按功能词切出的**每个**语义单元都要露脸，不被前面的挤掉。"""
    for text, want in [
        ("请提供被投企业最近三年经审计的财务报告及审计意见", "审计意见"),
        ("请提供前十大股东名单及其持股比例", "持股比例"),
    ]:
        terms = rq.text_search_terms(text)
        assert want in terms, f"{text} 丢了句尾单元 {want}：{terms}"


def test_no_cross_boundary_fragments():
    """切分后不应再产生跨词边界的碎片。

    「制人及股」这类词在二元组 FTS 索引下几乎必然 0 命中，
    只会白发查询、拖慢召回。
    """
    terms = rq.text_search_terms("请说明实际控制人及股权结构")
    for t in terms:
        for boundary in ("及", "和", "与", "其", "的"):
            assert not (t.startswith(boundary) or t.endswith(boundary)), \
                f"跨词边界碎片：{t}"


def test_tail_only_keyword_still_recall_end_to_end(tmp_path):
    """端到端：关键信息只在句尾、材料标题就是该词 → 召回不得为 0。"""
    lib = _seed(tmp_path, {
        "股权结构说明.txt": "实际控制人及股权结构说明\n"
                          "泽天科技第一大股东为长风资本，持股 42%。\n",
    })
    rq.ingest_checklist(lib, [{"item_no": "L2", "raw_text": "请说明实际控制人及股权结构"}],
                        db_path=None)
    obl = rq.list_obligations(lib, db_path=None)[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=None)
    assert st["candidate_count"] > 0, "句尾关键词也必须召回得到"
    assert st["verdict"] != ms.V_MISSING, "材料就在库里，不得判缺材料"
