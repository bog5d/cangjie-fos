"""附件覆盖维度与 HG2 跨主体复用检测测试（WP6 前补齐两处自陈缺口）。

背景：
- 硬门槛要求的第四维是「必备附件覆盖」，此前 related_files 恒 UNKNOWN，
  导致义务一旦要求附件，该维度**永远为 0**，M2 永远不可能达标。
- HG2 此前只能查「同一 file_id 挂多个主体」，查不到
  「拿 A 公司的材料顶 B 公司要求」这种更常见的错法。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_requirement_service as rq


# ── 披露策略夹具（WP7）─────────────────────────────────────────────────────
# WP3–WP6 时期的用例用 `sensitivity="PUBLIC"` 绕过 Gate，那正是二值判定的漏洞：
# 任意非空值都放行。WP7 改为版本化策略后，未知等级一律不可外发，
# 因此本文件统一在**已知策略**下运行。
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
    p = _Path(tmp_path) / "_policy.json"
    p.write_text(_json.dumps(_TEST_POLICY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(p))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    _enable_test_policy(monkeypatch, tmp_path)
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path: Path):
    return tmp_path / "_dp" / "manifest.sqlite"


def _seed(tmp_path, files: dict[str, str]):
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
    return lib


def _register_subject(tmp_path, lib, name="子公司甲", relation="subsidiary"):
    """把主体登记进**权威名单**（``dd_v1_entities``）。

    ## 为什么这些既有用例必须补这一行（G6 v2）

    认知卡的 ``entity`` 是**父目录名**（INFERRED/path_segment），
    而冲突分桶 / STALE 判定**只认权威名单**（任务书 G6：
    「主体未知的不同法人同年材料不报 CONFLICT；**登记同主体**且哈希不同才报 CONFLICT」）。
    这些用例的 docstring 本来就在测「**子公司甲**的审计报告…」，
    但它们**没有登记主体** ⇒ 过去是靠「目录名冒充主体」才拿到 MATCHED / PARTIAL
    —— 那是 G6 v2 修掉的缺陷，不是它们想测的东西。

    ⇒ 补登记后，它们才真的在测自己声称的东西；**断言一字未改**。
    """
    rq.register_entity(lib, "S1", name, relation=relation,
                       source_ref="工商登记", db_path=_db(tmp_path))


def _unlock(lib, db, rel, sensitivity="PUBLIC"):
    fid = mf.get_manifest_entry(lib, rel, db_path=db)["file_id"]
    conn = mf._connect(db)
    conn.execute("UPDATE dd_v1_material_cards SET sensitivity=? WHERE file_id=?",
                 (sensitivity, fid))
    conn.commit()
    return fid


# ── 1. 附件关系识别 ──────────────────────────────────────────────────────
def test_same_stem_different_ext_is_attachment(tmp_path):
    lib = _seed(tmp_path, {
        "子公司甲/审计报告2023.txt": "审计报告正文",
        "子公司甲/审计报告2023_附表.txt": "审计报告附表内容",
    })
    card = cs.get_card(mf.get_manifest_entry(
        lib, "子公司甲/审计报告2023.txt", db_path=_db(tmp_path))["file_id"],
        db_path=_db(tmp_path))
    assert card["fields"]["related_files"]["value"] == ["子公司甲/审计报告2023_附表.txt"]
    assert card["fields"]["related_files"]["provenance"] == cs.INFERRED


def test_unrelated_files_are_not_attachments(tmp_path):
    lib = _seed(tmp_path, {
        "子公司甲/审计报告2023.txt": "审计报告正文",
        "子公司甲/营业执照2023.txt": "营业执照正文",
    })
    card = cs.get_card(mf.get_manifest_entry(
        lib, "子公司甲/审计报告2023.txt", db_path=_db(tmp_path))["file_id"],
        db_path=_db(tmp_path))
    assert card["fields"]["related_files"]["value"] == [], "同目录不等于附件，不得臆造关系"


def test_cross_directory_not_linked(tmp_path):
    lib = _seed(tmp_path, {
        "子公司甲/审计报告2023.txt": "正文",
        "子公司乙/审计报告2023.txt": "正文",
    })
    card = cs.get_card(mf.get_manifest_entry(
        lib, "子公司甲/审计报告2023.txt", db_path=_db(tmp_path))["file_id"],
        db_path=_db(tmp_path))
    assert card["fields"]["related_files"]["value"] == [], "跨目录不猜关系"


def test_attach_key_strips_version_and_year():
    assert cs._attach_key("审计报告2023.pdf") == cs._attach_key("审计报告最终版_v2.pdf")
    assert cs._attach_key("审计报告2023.pdf") == cs._attach_key("审计报告盖章版.pdf")
    assert cs._attach_key("审计报告2023.pdf") != cs._attach_key("营业执照2023.pdf")


# ── 2. 附件维度进入覆盖判定 ──────────────────────────────────────────────
def test_obligation_requiring_attachment_without_related_is_partial(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": "审计报告\n本报告为2023年度审计结论。\n"})
    _register_subject(tmp_path, lib)          # G6 v2：主体须在权威名单里
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    rq.ingest_checklist(lib, [{"item_no": "1",
                              "raw_text": "请提供2023年度审计报告及其附件"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    assert obl["needs_attachments"] == 1
    st = ms.get_status(obl["obligation_id"], db_path=_db(tmp_path))
    assert st["attach_cov"] < 1.0
    assert st["verdict"] == ms.V_PARTIAL
    assert "必备附件缺失" in st["missing_detail"]


def test_obligation_requiring_attachment_with_related_can_match(tmp_path):
    lib = _seed(tmp_path, {
        "子公司甲/审计报告2023.txt": "审计报告\n本报告为2023年度审计结论。\n",
        "子公司甲/审计报告2023_附表.txt": "审计报告附表内容",
    })
    _register_subject(tmp_path, lib)          # G6 v2：主体须在权威名单里
    for rel in ("子公司甲/审计报告2023.txt", "子公司甲/审计报告2023_附表.txt"):
        _unlock(lib, _db(tmp_path), rel)
    rq.ingest_checklist(lib, [{"item_no": "1",
                              "raw_text": "请提供2023年度审计报告及其附件"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.get_status(obl["obligation_id"], db_path=_db(tmp_path))
    assert st["attach_cov"] == 1.0, "有可观察的关联件时附件维度应满足"
    assert st["verdict"] == ms.V_MATCHED


def test_obligation_without_attachment_requirement_is_not_penalised(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": "审计报告\n本报告为2023年度审计结论。\n"})
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    obl = rq.list_obligations(lib, db_path=_db(tmp_path))[0]
    st = ms.get_status(obl["obligation_id"], db_path=_db(tmp_path))
    assert st["attach_cov"] == 1.0


# ── 3. HG2 跨主体复用检测 ────────────────────────────────────────────────
def test_cross_entity_substitution_detected(tmp_path):
    """一份挂多主体的材料 → HG2 必须报出来。"""
    pool = [
        {"file_id": "f1", "card": {"entity": "子公司甲", "fiscal_period": "2023",
                                   "purpose": []}},
        {"file_id": "f1", "card": {"entity": "子公司乙", "fiscal_period": "2023",
                                   "purpose": []}},
    ]
    need = [{"display_name": "子公司甲"}, {"display_name": "子公司乙"}]
    out = ms.detect_entity_substitution(pool, need)
    assert len(out) == 1
    assert out[0]["file_id"] == "f1"
    assert set(out[0]["entities"]) == {"子公司甲", "子公司乙"}


def test_single_entity_material_not_flagged(tmp_path):
    pool = [{"file_id": "f1", "card": {"entity": "子公司甲"}}]
    need = [{"display_name": "子公司甲"}, {"display_name": "子公司乙"}]
    assert ms.detect_entity_substitution(pool, need) == []
