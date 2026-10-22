"""DD-V1 五维齐套与「应有几份」测试（A3 · G-A3-1 / G-A3-3）。

## 判据对应

- **A3-1**（份数承载）：``expected_count`` + ``expected_count_basis`` 存在；
  合成「一式两份」→ 2/FACT；解析不出 → 空/UNKNOWN → 判 UNCERTAIN；
  ★ **不得默认 1 份**。
- **A3-3**（五维齐套）：主体 / 期间 / 材料类型 / 必备附件 / 份数
  各自缺 1 项 → 判对且 ``missing_detail`` **指名缺哪一维**；
  份数不可判定 → UNCERTAIN；★ 不得笼统写「材料缺失」。

## 三态语义（A3-1）

``expected_count`` = ``0``   ⇒ 清单**未规定**份数（该维不构成门槛）
``expected_count`` = ``None`` ⇒ 清单**提及**份数但**解析不出**（不可判定 ⇒ UNCERTAIN）
``expected_count`` = ``N>0``  ⇒ 权威份数 N
"""
from __future__ import annotations

import json as _json
from pathlib import Path as _Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_qc_service as qc
from cangjie_fos.services import dd_v1_requirement_service as rq

_TEST_POLICY = {
    "policy_version": "test-v1",
    "default_level": "RESTRICTED",
    "levels": {
        "PUBLIC": {"externally_sendable": True, "requires_review": True},
        "INTERNAL": {"externally_sendable": False, "requires_review": True},
        "CONFIDENTIAL": {"externally_sendable": False, "requires_review": True},
        "RESTRICTED": {"externally_sendable": False, "requires_review": True},
    },
    "rules": [],
}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    p = _Path(tmp_path) / "_policy.json"
    p.write_text(_json.dumps(_TEST_POLICY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(p))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path: Path):
    return tmp_path / "_dp" / "manifest.sqlite"


def _audit(year, entity="子公司甲"):
    return f"审计报告\n本报告为{year}年度财务审计结论，由{entity}出具。\n"


def _setup(tmp_path, files: dict[str, str]):
    lib = "lib1"
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    mf.register_library(lib, str(root), authorized_by="波总", db_path=_db(tmp_path))
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib, root


def _register_subject(tmp_path, lib, name="子公司甲", relation="subsidiary",
                      eid="S1"):
    rq.register_entity(lib, eid, name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _unlock(lib, db, rel, sensitivity="PUBLIC"):
    fid = mf.get_manifest_entry(lib, rel, db_path=db)["file_id"]
    conn = mf._connect(db)
    conn.execute("UPDATE dd_v1_material_cards SET sensitivity=? WHERE file_id=?",
                 (sensitivity, fid))
    conn.commit()
    return fid


def _one_obligation(tmp_path, lib, raw_text, item_no="1"):
    rq.ingest_checklist(lib, [{"item_no": item_no, "raw_text": raw_text}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    return obl


def _match(tmp_path, lib, obl):
    return ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))


# ── A3-1：份数承载与解析 ──────────────────────────────────────────────────
def test_yishi_liangfen_parses_to_two_with_fact_basis():
    """「一式两份」⇒ expected_count=2 且 basis=FACT。"""
    obl = rq.build_obligations("请提供2023年度审计报告一式两份")[0]
    assert obl.expected_count == 2
    assert obl.expected_count_basis == rq.FACT
    assert obl.to_dict()["expected_count"] == 2
    assert obl.to_dict()["expected_count_basis"] == rq.FACT


def test_count_absent_is_zero_and_does_not_gate_the_verdict(tmp_path):
    """清单没提份数 ⇒ 0（不构成门槛），**不得**因此把义务判成 UNCERTAIN。"""
    obl = rq.build_obligations("请提供2023年度审计报告")[0]
    assert obl.expected_count == 0
    assert obl.expected_count_basis == rq.UNKNOWN

    lib, _ = _setup(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _register_subject(tmp_path, lib)
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    obl = _one_obligation(tmp_path, lib, "请提供2023年度审计报告")
    st = _match(tmp_path, lib, obl)
    assert st["verdict"] == ms.V_MATCHED, \
        f"未提份数不构成门槛：{st['verdict']} / {st['missing_detail']}"
    assert "份数不可判定" not in st["missing_detail"]


def test_count_unparseable_is_empty_not_one():
    """提及份数但解析不出 ⇒ **空值**（None），**不是 1**。"""
    obl = rq.build_obligations("请提供2023年度审计报告若干份")[0]
    assert obl.expected_count is None
    assert obl.expected_count_basis == rq.UNKNOWN
    assert obl.expected_count != 1, "★ 不得默认 1 份"


def test_part_of_word_is_not_a_count_mention():
    """「部分材料」里的「份」不是份数要求 ⇒ 不得把义务判成不可判定。"""
    obl = rq.build_obligations("请提供部分材料")[0]
    assert obl.expected_count == 0


def test_multiple_counts_are_summed_as_inferred():
    """同一段里出现多个份数 ⇒ 求和，basis=INFERRED（非明文单数）。"""
    obl = rq.build_obligations("正本1份 副本1份")[0]
    assert obl.expected_count == 2
    assert obl.expected_count_basis == rq.INFERRED


def test_split_parts_keep_their_own_count():
    """「正本1份、副本1份」被拆成两条义务 ⇒ **各管各的** 1 份。"""
    obls = rq.build_obligations("正本1份、副本1份")
    assert len(obls) == 2
    assert [o.expected_count for o in obls] == [1, 1]


# ── A3-1 + A3-3：份数不可判定 ⇒ UNCERTAIN（真实链路）────────────────────
def test_undeterminable_count_makes_obligation_uncertain(tmp_path):
    lib, _ = _setup(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _register_subject(tmp_path, lib)
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    obl = _one_obligation(tmp_path, lib, "请提供2023年度审计报告若干份")
    assert obl["expected_count"] is None

    st = _match(tmp_path, lib, obl)
    assert st["verdict"] == ms.V_UNCERTAIN, "份数不可判定 ⇒ 必须 UNCERTAIN"
    assert "份数不可判定" in st["missing_detail"]
    assert "维度：份数" in st["missing_detail"]
    assert st["count_expected"] is None


def test_count_shortfall_is_partial_and_names_the_dimension(tmp_path):
    lib, _ = _setup(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _register_subject(tmp_path, lib)
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    obl = _one_obligation(tmp_path, lib, "请提供2023年度审计报告一式两份")
    assert obl["expected_count"] == 2

    st = _match(tmp_path, lib, obl)
    assert st["verdict"] == ms.V_PARTIAL, "应有 2 份只找到 1 份 ⇒ PARTIAL"
    assert "份数缺 1/2 份" in st["missing_detail"]
    assert "维度：份数" in st["missing_detail"]
    assert st["count_expected"] == 2
    assert st["count_available"] == 1


# ── A3-3：五维各自缺 1 项 ⇒ 判对且指名缺哪一维 ──────────────────────────
def test_missing_entity_dimension_is_named(tmp_path):
    lib, _ = _setup(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _register_subject(tmp_path, lib, eid="S1")
    _register_subject(tmp_path, lib, name="子公司乙", eid="S2")
    obl = _one_obligation(tmp_path, lib, "请提供集团及下属公司2023年度审计报告")
    st = _match(tmp_path, lib, obl)
    assert st["need_entities"] == 2
    assert st["verdict"] == ms.V_PARTIAL
    assert "主体缺" in st["missing_detail"]
    assert "维度：主体" in st["missing_detail"]


def test_missing_period_dimension_is_named(tmp_path):
    lib, _ = _setup(tmp_path, {"子公司甲/审计报告2022.txt": _audit(2022)})
    _register_subject(tmp_path, lib)
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2022.txt")
    obl = _one_obligation(tmp_path, lib, "请提供子公司甲2021-2023年度审计报告")
    st = _match(tmp_path, lib, obl)
    assert st["verdict"] == ms.V_PARTIAL
    assert "期间缺" in st["missing_detail"]
    assert "维度：期间" in st["missing_detail"]


def test_missing_doctype_dimension_is_named(tmp_path):
    """类型维缺 ⇒ 必须指名「材料类型」，不得笼统写「材料缺失」。"""
    lib, _ = _setup(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _register_subject(tmp_path, lib, eid="S1")
    _register_subject(tmp_path, lib, name="子公司乙", eid="S2")
    obl = _one_obligation(tmp_path, lib, "请提供集团及下属公司2023年度审计报告")
    st = _match(tmp_path, lib, obl)
    assert st["verdict"] == ms.V_PARTIAL
    assert "材料类型缺" in st["missing_detail"], \
        f"类型维必须指名：{st['missing_detail']}"
    assert "维度：材料类型" in st["missing_detail"]
    assert "材料缺失" not in st["missing_detail"].replace("未检索到任何候选材料", "")


def test_missing_attachment_dimension_is_named(tmp_path):
    lib, _ = _setup(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _register_subject(tmp_path, lib)
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    obl = _one_obligation(tmp_path, lib, "请提供2023年度审计报告及附件")
    st = _match(tmp_path, lib, obl)
    assert st["verdict"] == ms.V_PARTIAL
    assert "必备附件缺失" in st["missing_detail"]
    assert "维度：必备附件" in st["missing_detail"]


def test_missing_count_dimension_is_named(tmp_path):
    lib, _ = _setup(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _register_subject(tmp_path, lib)
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    obl = _one_obligation(tmp_path, lib, "请提供2023年度审计报告一式两份")
    st = _match(tmp_path, lib, obl)
    assert "份数缺" in st["missing_detail"]
    assert "维度：份数" in st["missing_detail"]


# ── qc_service 单元口径 ───────────────────────────────────────────────────
def test_count_dimension_three_states():
    """0 = 未规定（不构成门槛）/ None = 不可判定 / N = 权威份数。"""
    not_stated = qc.count_dimension({"expected_count": 0}, 3)
    assert not_stated["required"] is False
    assert not_stated["determinable"] is True
    assert not_stated["ok"] is True

    unknown = qc.count_dimension({"expected_count": None}, 3)
    assert unknown["required"] is True
    assert unknown["determinable"] is False
    assert unknown["ok"] is False
    assert "不得默认 1 份" in unknown["detail"]

    short = qc.count_dimension({"expected_count": 2}, 1)
    assert short["ok"] is False
    assert "份数缺 1/2 份" in short["detail"]

    enough = qc.count_dimension({"expected_count": 2}, 2)
    assert enough["ok"] is True


def test_completeness_reports_every_dimension():
    q = qc.build_completeness(
        {"expected_count": 2},
        {"entity": {"covered": 1, "total": 2},
         "period": {"covered": 1, "total": 1},
         "doctype": {"covered": 1, "total": 1},
         "attachment": {"covered": 0, "total": 0}},
        1)
    assert [d["dimension"] for d in q["dimensions"]] == list(qc.DIMENSIONS)
    assert "主体" in q["missing_labels"]
    assert "必备附件" not in q["missing_labels"], "未提附件 ⇒ 不构成门槛"
    assert q["complete"] is False
