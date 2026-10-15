"""DD-V1 需求拆解与多文件匹配测试（WP3）。

必须守住的：
1. **机构原编号与原文零丢失**——拆分不得覆盖或丢失原件。
2. **拆不出的维度留 UNKNOWN**，相对年份缺锚点不得擅自假定。
3. **主体范围必须有权威名单**，没有名单不得用目录名凑数（对治 D2/D3）。
4. **四维覆盖**：找到一份相关文件 ≠ 整项完成（对治旧「每条需求选一个最佳文件」）。
5. **候选上限是可配置参数**，不是硬编码 2（对治 D3）。
6. **受限材料不得顶替**判 MATCHED（对应硬门槛 HG1）。
7. **决策记忆五项复验**（对治 D4 的写而不读）。
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
    # WP7 起披露走版本化策略；本文件统一在**已知策略**下运行，
    # 避免「无策略一律不可外发」的安全默认把所有用例都判成 RESTRICTED。
    _enable_test_policy(monkeypatch, tmp_path)
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path: Path):
    return tmp_path / "_dp" / "manifest.sqlite"


# ── 披露策略夹具（WP7）─────────────────────────────────────────────────────
# WP3/WP4 时期的测试用 `sensitivity="public"` 绕过 Gate，那正是二值判定的漏洞：
# 任意非空值都放行。WP7 改为版本化策略后，未知等级一律不可外发，
# 因此这些用例必须加载真实策略并使用**策略认识的级别名**。
import json as _json
from pathlib import Path as _Path

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


def _enable_test_policy(monkeypatch, tmp_path) -> None:
    """在测试里加载一份可发 PUBLIC 的策略，其余级别仍不可外发。"""
    p = _Path(tmp_path) / "_policy.json"
    p.write_text(_json.dumps(_TEST_POLICY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(p))



def _lib(tmp_path: Path, name="lib1"):
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    mf.register_library(name, str(root), authorized_by="波总", db_path=_db(tmp_path))
    return name, root


# ── 1. 原文与编号零丢失 ───────────────────────────────────────────────────
def test_original_number_and_text_preserved(tmp_path):
    lib, _ = _lib(tmp_path)
    rows = [
        {"item_no": "3.2.1", "raw_text": "请提供集团及下属公司2021-2023年度审计报告"},
        {"item_no": "3.2.2", "raw_text": "请提供母公司最近三年财务报表"},
    ]
    res = rq.ingest_checklist(lib, rows, db_path=_db(tmp_path))
    assert res["items"] == 2
    assert res["original_text_roundtrip_ok"] is True

    items = {i["item_no"]: i["raw_text"] for i in
             mf._connect(_db(tmp_path)).execute(
                 "SELECT item_no, raw_text FROM dd_v1_checklist_items").fetchall()}
    assert items["3.2.1"] == "请提供集团及下属公司2021-2023年度审计报告"
    assert items["3.2.2"] == "请提供母公司最近三年财务报表"


def test_empty_text_is_rejected_not_fabricated(tmp_path):
    lib, _ = _lib(tmp_path)
    res = rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "   "}],
                              db_path=_db(tmp_path))
    assert res["items"] == 0
    assert res["dropped"], "空原文必须被拒并留痕，不得凭空生成要求"


def test_obligation_points_back_to_original(tmp_path):
    lib, _ = _lib(tmp_path)
    raw = "请提供集团及下属公司2021-2023年度审计报告"
    rq.ingest_checklist(lib, [{"item_no": "A1", "raw_text": raw}], db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    item = rq.get_item(obl["item_uid"], db_path=_db(tmp_path))
    assert item["raw_text"] == raw, "拆分后必须能指回机构原文"
    assert item["item_no"] == "A1"


# ── 2. 维度识别与 UNKNOWN 纪律 ─────────────────────────────────────────────
def test_explicit_period_is_fact():
    ob = rq.build_obligations("请提供2021-2023年度审计报告")[0]
    assert ob.period_from == 2021 and ob.period_to == 2023
    assert ob.period_basis == rq.FACT


def test_relative_period_without_anchor_not_assumed():
    """「最近三年」无锚点时不得擅自假定年份。"""
    ob = rq.build_obligations("请提供母公司最近三年财务报表")[0]
    assert ob.period_from == 0 and ob.period_to == 0
    assert ob.period_basis == "relative_unresolved"
    assert any("锚定年" in n for n in ob.notes)


def test_relative_period_with_anchor():
    ob = rq.build_obligations("请提供最近三年审计报告", anchor_year=2023)[0]
    assert (ob.period_from, ob.period_to) == (2021, 2023)


def test_entity_scope_only_from_explicit_text():
    assert rq.build_obligations("集团及下属公司审计报告")[0].entity_scope == "group_and_subs"
    assert rq.build_obligations("母公司财务报表")[0].entity_scope == "parent_only"
    assert rq.build_obligations("提供审计报告")[0].entity_basis == rq.UNKNOWN


def test_caliber_and_seal():
    ob = rq.build_obligations("请提供集团合并财务报表，需盖章并签字")[0]
    assert ob.caliber == "consolidated" and ob.caliber_basis == rq.FACT
    assert ob.seal_required == "seal_and_sign"


def test_unknown_dimensions_stay_unknown():
    ob = rq.build_obligations("请提供相关材料")[0]
    for d in ("entity_basis", "period_basis", "doc_type_basis", "caliber_basis"):
        assert getattr(ob, d) == rq.UNKNOWN, d


def test_parallel_split_keeps_all_parts():
    obs = rq.build_obligations("请提供营业执照、公司章程、股东会决议")
    assert len(obs) >= 3, "并列要求必须拆成多条原子义务"
    joined = " ".join(o.obligation for o in obs)
    for kw in ("营业执照", "公司章程", "股东会决议"):
        assert kw in joined


# ── 3. 权威主体名单 ────────────────────────────────────────────────────────
def test_entity_registration_requires_source(tmp_path):
    lib, _ = _lib(tmp_path)
    with pytest.raises(ValueError, match="source_ref"):
        rq.register_entity(lib, "E1", "某某公司", db_path=_db(tmp_path))


def test_entities_resolve_by_scope_and_validity(tmp_path):
    lib, _ = _lib(tmp_path)
    rq.register_entity(lib, "P", "集团母公司", relation="parent",
                       is_group_root=True, source_ref="工商登记", db_path=_db(tmp_path))
    rq.register_entity(lib, "S1", "子公司甲", relation="subsidiary",
                       parent_id="P", source_ref="工商登记", db_path=_db(tmp_path))
    rq.register_entity(lib, "S2", "已注销子公司", relation="subsidiary",
                       parent_id="P", valid_from=2015, valid_to=2019,
                       source_ref="工商登记", db_path=_db(tmp_path))

    assert len(rq.resolve_entities(lib, "group_and_subs", db_path=_db(tmp_path))) == 3
    assert len(rq.resolve_entities(lib, "subsidiaries", db_path=_db(tmp_path))) == 2
    got = rq.resolve_entities(lib, "subsidiaries", as_of_year=2023, db_path=_db(tmp_path))
    assert [e["display_name"] for e in got] == ["子公司甲"], "已注销主体不得计入当期"


def test_no_registry_means_no_entities(tmp_path):
    lib, _ = _lib(tmp_path)
    assert rq.resolve_entities(lib, "group_and_subs", db_path=_db(tmp_path)) == []


# ── 4. 端到端匹配：四维覆盖 ───────────────────────────────────────────────
def _seed_library(tmp_path, lib, root, files: dict[str, str]):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))


def _audit(year, entity="子公司甲"):
    return f"审计报告\n本报告为{year}年度财务审计结论，由{entity}出具。\n"


def _unlock_sensitivity(lib, db, rel: str):
    """把指定材料的敏感等级标为 public（模拟已接入披露政策）。

    没有这一步，认知卡的 sensitivity 恒 UNKNOWN，
    按硬门槛 HG1 一律不得自动纳入对外交付 → 判定只会是 RESTRICTED。
    """
    fid = mf.get_manifest_entry(lib, rel, db_path=db)["file_id"]
    conn = mf._connect(db)
    conn.execute("UPDATE dd_v1_material_cards SET sensitivity='public' WHERE file_id=?",
                 (fid,))
    conn.commit()
    return fid


def test_single_file_does_not_satisfy_multi_year_requirement(tmp_path):
    """核心：找到一份审计报告 ≠ 三年要求被满足。"""
    lib, root = _lib(tmp_path)
    _seed_library(tmp_path, lib, root, {"子公司甲/审计报告2022.txt": _audit(2022)})
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供子公司甲2021-2023年度审计报告"}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))

    assert st["need_periods"] == 3
    assert st["period_cov"] < 1.0
    assert st["verdict"] == ms.V_PARTIAL
    assert "期间缺" in st["missing_detail"]


def test_three_years_one_each_is_matched(tmp_path):
    lib, root = _lib(tmp_path)
    _seed_library(tmp_path, lib, root, {
        "子公司甲/审计报告2021.txt": _audit(2021),
        "子公司甲/审计报告2022.txt": _audit(2022),
        "子公司甲/审计报告2023.txt": _audit(2023),
    })
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供子公司甲2021-2023年度审计报告"}],
                        db_path=_db(tmp_path))
    for y in (2021, 2022, 2023):
        _unlock_sensitivity(lib, _db(tmp_path), f"子公司甲/审计报告{y}.txt")
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    assert st["period_cov"] == 1.0
    assert st["deliverable_count"] == 3
    assert st["verdict"] == ms.V_MATCHED


def test_group_requirement_without_registry_is_uncertain(tmp_path):
    """要求集团全范围但没有权威名单 → UNCERTAIN，不得用目录名凑数。"""
    lib, root = _lib(tmp_path)
    _seed_library(tmp_path, lib, root, {"子公司甲/审计报告2023.txt": _audit(2023)})
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供集团及下属公司2023年度审计报告"}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    assert st["verdict"] == ms.V_UNCERTAIN
    assert st["need_entities"] == 0


def test_group_requirement_with_registry_checks_every_entity(tmp_path):
    lib, root = _lib(tmp_path)
    _seed_library(tmp_path, lib, root, {"子公司甲/审计报告2023.txt": _audit(2023)})
    rq.register_entity(lib, "S1", "子公司甲", relation="subsidiary",
                       source_ref="工商登记", db_path=_db(tmp_path))
    rq.register_entity(lib, "S2", "子公司乙", relation="subsidiary",
                       source_ref="工商登记", db_path=_db(tmp_path))
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供集团及下属公司2023年度审计报告"}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    assert st["need_entities"] == 2
    assert st["verdict"] == ms.V_PARTIAL, "只有 1/2 主体 → 必须 PARTIAL"
    assert "主体缺" in st["missing_detail"]


def test_no_material_is_missing(tmp_path):
    lib, root = _lib(tmp_path)
    _seed_library(tmp_path, lib, root, {"子公司甲/营业执照.txt": "营业执照正文"})
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    assert st["verdict"] in (ms.V_MISSING, ms.V_PARTIAL)


# ── 5. 候选上限可配置（对治 D3「最多 2 份」）──────────────────────────────
def test_candidate_cap_is_configurable_not_hardcoded_two(tmp_path):
    lib, root = _lib(tmp_path)
    files = {f"子公司甲/审计报告{y}.txt": _audit(y) for y in range(2016, 2026)}
    _seed_library(tmp_path, lib, root, files)
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供审计报告"}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]

    low = ms.match_obligation(lib, obl["obligation_id"], candidate_cap=2, db_path=_db(tmp_path))
    high = ms.match_obligation(lib, obl["obligation_id"], candidate_cap=20, db_path=_db(tmp_path))
    assert high["candidate_count"] >= low["candidate_count"]
    assert high["candidate_count"] > 2, "候选上限必须真能放到 2 份以上（旧实现硬编码 2）"
    assert ms.DEFAULT_CANDIDATE_CAP >= 10


def test_capping_is_recorded_not_silent(tmp_path):
    lib, root = _lib(tmp_path)
    files = {f"子公司甲/审计报告{y}.txt": _audit(y) for y in range(2010, 2024)}
    _seed_library(tmp_path, lib, root, files)
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供审计报告"}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.match_obligation(lib, obl["obligation_id"], candidate_cap=2, db_path=_db(tmp_path))
    assert st["capped"] == 1, "候选被截断必须显式标记，不得静默丢弃"


# ── 6. 受限材料不得判 MATCHED（硬门槛 HG1）────────────────────────────────
def test_unknown_sensitivity_blocks_matched(tmp_path):
    """敏感等级未知 → 不得自动纳入可对外交付结果，因此不能判 MATCHED。"""
    lib, root = _lib(tmp_path)
    _seed_library(tmp_path, lib, root, {"子公司甲/审计报告2023.txt": _audit(2023)})
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    assert st["deliverable_count"] == 0
    assert st["verdict"] == ms.V_RESTRICTED
    ms_ = ms.list_matches(obl["obligation_id"], db_path=_db(tmp_path))
    assert all(m["deliverable"] == 0 for m in ms_)


def test_marking_sensitivity_unlocks_delivery(tmp_path):
    """一旦政策给出敏感等级且允许，才可能判 MATCHED。"""
    lib, root = _lib(tmp_path)
    _seed_library(tmp_path, lib, root, {"子公司甲/审计报告2023.txt": _audit(2023)})
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    fid = mf.get_manifest_entry(lib, "子公司甲/审计报告2023.txt",
                                db_path=_db(tmp_path))["file_id"]
    cs.cache_text(fid, lib, _audit(2023), method="raw", db_path=_db(tmp_path))
    cs.build_card(mf.get_manifest_entry(lib, "子公司甲/审计报告2023.txt", db_path=_db(tmp_path)),
                  text=_audit(2023), db_path=_db(tmp_path))
    conn = mf._connect(_db(tmp_path))
    conn.execute("UPDATE dd_v1_material_cards SET sensitivity='public' WHERE file_id=?", (fid,))
    conn.commit()

    st = ms.match_obligation(lib, obl["obligation_id"], db_path=_db(tmp_path))
    assert st["deliverable_count"] >= 1
    assert st["verdict"] == ms.V_MATCHED


# ── 7. 一个文件服务多条义务 + D4 记忆复验 ─────────────────────────────────
def test_one_file_can_serve_multiple_obligations(tmp_path):
    lib, root = _lib(tmp_path)
    _seed_library(tmp_path, lib, root, {"子公司甲/审计报告2023.txt": _audit(2023)})
    rq.ingest_checklist(lib, [
        {"item_no": "1", "raw_text": "请提供2023年度审计报告"},
        {"item_no": "2", "raw_text": "请提供2023年度审计"},
    ], db_path=_db(tmp_path))
    obl_ids = [o["obligation_id"] for o in rq.list_obligations(lib, db_path=_db(tmp_path))]
    for oid in obl_ids:
        ms.match_obligation(lib, oid, db_path=_db(tmp_path))
    fid = mf.get_manifest_entry(lib, "子公司甲/审计报告2023.txt", db_path=_db(tmp_path))["file_id"]
    assert ms.file_serves_count(fid, db_path=_db(tmp_path)) >= 1


def test_memory_revalidation_rejects_wrong_entity():
    ok, why = ms.revalidate_memory_hit(
        {"last_institution": "子公司甲"}, "子公司甲", None, None)
    assert ok and "通过" in why
    ok, why = ms.revalidate_memory_hit(
        {"last_institution": "子公司甲"}, "子公司乙", None, None)
    assert not ok and "主体不符" in why


def test_memory_revalidation_rejects_period_mismatch():
    card = {"fiscal_period": "2019"}
    ok, why = ms.revalidate_memory_hit(
        {"last_institution": "子公司甲"}, "子公司甲", (2021, 2023), card)
    assert not ok and "期间不符" in why


def test_memory_revalidation_rejects_expired():
    ok, why = ms.revalidate_memory_hit(
        {"last_institution": "A", "valid_to": 2020}, "A", None, None)
    assert not ok and "失效期" in why


# ── 8. 批量与可观测 ───────────────────────────────────────────────────────
def test_match_library_returns_verdict_tally(tmp_path):
    lib, root = _lib(tmp_path)
    _seed_library(tmp_path, lib, root, {"子公司甲/审计报告2023.txt": _audit(2023)})
    rq.ingest_checklist(lib, [
        {"item_no": "1", "raw_text": "请提供2023年度审计报告"},
        {"item_no": "2", "raw_text": "请提供2020-2022年度营业执照"},
    ], db_path=_db(tmp_path))
    res = ms.match_library(lib, db_path=_db(tmp_path))
    assert res["obligations"] == 2
    assert res["candidate_cap"] >= 10
    assert sum(res["by_verdict"].values()) == 2


def test_obligation_quality_reports_unknown_share(tmp_path):
    lib, _ = _lib(tmp_path)
    rq.ingest_checklist(lib, [
        {"item_no": "1", "raw_text": "请提供集团及下属公司2021-2023年度审计报告"},
        {"item_no": "2", "raw_text": "请提供相关材料"},
    ], db_path=_db(tmp_path))
    q = rq.obligation_quality(lib, db_path=_db(tmp_path))
    assert q["obligations"] >= 2
    assert q["by_dimension"]["entity_basis"][rq.UNKNOWN] >= 1
    assert q["entities_registered"] == 0
