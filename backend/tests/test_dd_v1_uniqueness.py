"""A2 · G-A2-10：**材料唯一性口径 + 索引件排除** —— 判别力用例。

## 为什么要有这个文件

独立监工提出「归一做通 ⇒ CONFLICT 从 0 反弹，但 MATCHED 仍 0」，并建议新增
「材料类型唯一性」一格。司仓**独立复现**（逐冲突组做文件级取证）后确认主张成立，
但根因更精确：

- 「00_索引.md」被解析成 audit_report / financial_statement ⇒ **类型误分类**
  ⇒ 与真审计报告同主体同期间同类型落进同一桶 ⇒ **假 CONFLICT**；
- 「工商底档5/6/7/9/10.pdf」互相冲突 ⇒ **期间内合法多份**（同一批材料的分册）；
- 「5.1.3关联交易管理制度.pdf」被当成 charter ⇒ **类型误分类**。

⇒ 处置两件事（缺一不可）：
**10a 索引/目录件不是材料**（不参与类型证据、不参与冲突判定、不可交付，但**留痕**）；
**10b 唯一性口径**：`ANNUAL_UNIQUE`（审计报告：一年一份）⇒ 异哈希**必须报**真冲突；
`MULTI_LEGAL`（执照正副本 / 章程修正案 / 底档分册 / 按月报表）⇒ **不报**冲突，只留痕。

## ★ 判据必须**双向**（本文件的核心断言）

- 多份合法的**不得**报 CONFLICT；
- 唯一性类的**真冲突仍必须报** —— 不得为了消 CONFLICT 把真冲突一起改没。

## 红线

不得关掉哈希比较、不得用阈值放松来消 CONFLICT。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import (
    dd_v1_card_service as cs,
    dd_v1_doc_type_service as dts,
    dd_v1_manifest_service as mf,
    dd_v1_match_service as ms,
    dd_v1_parser_service as ps,
    dd_v1_requirement_service as rq,
)


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(tmp_path / "无策略.json"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_plane" / "manifest.sqlite"


def _setup(tmp_path, files: dict[str, str], lib="lib1"):
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.register_library(lib, str(root), authorized_by="A2", db_path=_db(tmp_path))
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def _register(tmp_path, lib, eid, name, relation="subsidiary"):
    rq.register_entity(lib, eid, name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _obl_status(tmp_path, raw_text, lib):
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": raw_text}], db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    return ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))


def _cards(tmp_path, lib):
    conn = mf._connect(_db(tmp_path))
    try:
        return {r["rel_path"]: dict(r) for r in
                conn.execute("SELECT * FROM dd_v1_material_cards WHERE library_id=?",
                             (lib,)).fetchall()}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# 唯一性口径（公开 API）
# ═══════════════════════════════════════════════════════════════════════


def test_uniqueness_api_covers_every_canonical_key():
    """★ 10 个规范 key 都必须有唯一性口径（漏一个 = 该类型默默按未知处理）。"""
    keys = [k for k, _ in rq._DOC_TYPE_RULES]
    missing = [k for k in keys if rq.doc_type_uniqueness(k) == "UNKNOWN"]
    assert not missing, f"这些规范类型没有唯一性口径：{missing}"


def test_audit_report_is_annual_unique():
    assert rq.doc_type_uniqueness("audit_report") == "ANNUAL_UNIQUE"


def test_unknown_key_is_unknown():
    assert rq.doc_type_uniqueness("") == "UNKNOWN"
    assert rq.doc_type_uniqueness("pdf") == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════
# 10a 索引/目录件不是材料
# ═══════════════════════════════════════════════════════════════════════


def test_index_artifact_detection_is_conservative():
    assert dts.is_index_artifact("00_索引.md") is True
    assert dts.is_index_artifact("索引.md") is True
    assert dts.is_index_artifact("材料目录.xlsx") is True
    assert dts.is_index_artifact("README.txt") is True
    # 真材料**不得**被误判成索引件
    assert dts.is_index_artifact("2022年审计报告.pdf") is False
    assert dts.is_index_artifact("公司章程.pdf") is False
    assert dts.is_index_artifact("") is False


def test_index_artifact_card_has_empty_doc_type(tmp_path):
    lib = _setup(tmp_path, {
        "甲公司/00_索引.md": "本目录包含：2022年审计报告.pdf",
        "甲公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论，由甲公司出具。",
    })
    cards = _cards(tmp_path, lib)
    idx = next(c for p, c in cards.items() if "索引" in p)
    real = next(c for p, c in cards.items() if p.endswith(".pdf"))
    assert idx["doc_type"] == "", "索引件不得有材料类型"
    assert real["doc_type"] == "audit_report", "真审计报告的类型必须仍然认得出"


def test_index_artifact_does_not_create_conflict(tmp_path):
    """★ 判别力：修复前「索引件 + 真审计报告」会报假 CONFLICT，修复后不得报。"""
    lib = _setup(tmp_path, {
        "甲公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论，由甲公司出具。",
        "甲公司/00_索引.md": "本目录包含：2022年审计报告.pdf",
    })
    _register(tmp_path, lib, "E1", "甲公司")
    st = _obl_status(tmp_path, "2022年度审计报告", lib)
    assert not st.get("conflicts"), f"索引件不得造成冲突：{st.get('conflicts')}"
    assert st.get("index_artifacts"), "索引件必须**留痕**，不得静默丢弃"


# ═══════════════════════════════════════════════════════════════════════
# 10b 唯一性口径（★ 双向判据）
# ═══════════════════════════════════════════════════════════════════════


def test_multi_legal_does_not_report_conflict(tmp_path):
    """★ 判别力：章程（可有多份/修正案）两份异哈希**不得**报 CONFLICT，且必须留痕。"""
    lib = _setup(tmp_path, {
        "甲公司/公司章程.pdf": "本公司章程 第一条 总则……",
        "甲公司/公司章程-修正案.pdf": "本公司章程修正案 修正第一条……",
    })
    _register(tmp_path, lib, "E1", "甲公司")
    st = _obl_status(tmp_path, "公司章程", lib)
    assert not st.get("conflicts"), f"合法多份不得报冲突：{st.get('conflicts')}"
    assert st.get("multi_legal"), "合法多份必须留痕"


def test_annual_unique_real_conflict_still_reported(tmp_path):
    """★ 判别力（双向的另一侧）：审计报告（一年一份）两份异哈希**必须**报 CONFLICT。

    这是红线：不得为了消 CONFLICT 把真冲突一起改没。
    """
    lib = _setup(tmp_path, {
        "甲公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论（初稿）。",
        "甲公司/2022年审计报告-修订.pdf": "本报告为2022年度财务审计结论（修订稿）。",
    })
    _register(tmp_path, lib, "E1", "甲公司")
    st = _obl_status(tmp_path, "2022年度审计报告", lib)
    assert st.get("conflicts"), "年度唯一类型的真冲突必须仍然报出来（判据双向）"
    assert st["conflicts"][0]["distinct_hashes"] >= 2


def test_unregistered_subject_still_not_conflict(tmp_path):
    """红线：主体未登记 ⇒ 不得报 CONFLICT（与 G6 v2/v3 一致，不得被本包破坏）。"""
    lib = _setup(tmp_path, {
        "甲公司/2022年审计报告.pdf": "本报告为2022年度财务审计结论（初稿）。",
        "甲公司/2022年审计报告-修订.pdf": "本报告为2022年度财务审计结论（修订稿）。",
    })
    # **不**登记主体
    st = _obl_status(tmp_path, "2022年度审计报告", lib)
    assert not st.get("conflicts"), "主体未登记时不得报 CONFLICT"
