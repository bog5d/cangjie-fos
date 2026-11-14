"""DD-V1 · G5 回归测试（多类型材料：组包链按「整段的类型归属」给材料定类型）。

背景（PR #81 已登记缺口 G5，如实复现，不采信自报）：
  G5 原文：「多类型段：组包链按**整段的类型归属**给材料定类型 ⇒ 段内**可外发类**的材料
  被归到同段的**另一类** ⇒ 授权组包取不到它。该材料被披露策略闸拦下（fail-closed：
  无越权外发 ⇒ 非安全缺陷）；该段其余材料一并受影响。既有缺陷、本 PR 未引入。」

本文件把该缺口的**因果链逐环钉住**，并给出判据：
  ① 类型解析层必须保留材料命中的**全部**类型（不能只落一个 key）——成因环；
  ② 认知卡必须**同时**保留全部类型（不能只落单值）——传导环；
  ③ 披露闸的输入必须是**材料自己的类型**，不得是「整段的类型归属」
     ⇒ 段内**可外发类**材料不再被连坐（授权组包取得到它）——后果环；
  ④ ★ **安全方向的红线**（反向对照）：材料只要含有一类**不在**放行清单里的类型，
     整份材料就**不得**外发（fail-closed）；纯受限类材料**仍必须**被拦下。

★ 判据方向：**不得**为了让测试变绿而放宽「可外发」判定（那会把 fail-closed 变成
  fail-open，是**安全方向的反向**）。正解是让材料**同时**保留它命中的全部类型，
  并让披露闸**按材料自己的类型**逐类判定。

零外部调用 / 零费用 / 零真实材料：全部用现场合成的最小材料。
"""
from __future__ import annotations

import json as _json
from pathlib import Path as _Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_doc_type_service as dts
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_policy_service as pol
from cangjie_fos.services import dd_v1_requirement_service as rq

JIA = "合成法人甲"

#: 一段**同时含两类**的正文：审计报告（不可外发）＋ 营业执照（可外发）
MIXED_TEXT = "本公司的2024年度审计报告如下。\n营业执照载明注册资本为人民币100万元。"

#: 只含一类的正文（对照组：不该被牵连）
PURE_LICENSE_TEXT = "营业执照载明注册资本为人民币100万元。"

#: 只含一类的正文（对照组：受限类，必须**仍**被拦）
PURE_AUDIT_TEXT = "本公司的2024年度审计报告如下。"


def _db(tmp_path):
    return tmp_path / "_dp" / "manifest.sqlite"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """数据面隔离到 tmp_path；披露策略用**仓内真实策略**（不放行清单只有 license）。"""
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.delenv("CANGJIE_DD_V1_POLICY", raising=False)
    mf.close_all()
    yield
    mf.close_all()


# ── ① 成因环：类型解析层必须保留全部命中类型 ──────────────────────────────
def test_mixed_text_does_contain_both_types():
    """**前提**：同一段正文里两类**确实都能识别**（否则后面全是空谈）。"""
    spans = rq.parse_doc_type_spans(MIXED_TEXT)
    kinds = {s[0] for s in spans}
    assert "audit_report" in kinds, spans
    assert "license" in kinds, spans


def test_resolve_doc_types_keeps_every_matched_type():
    """★ 成因环判据：多类型正文的**全部**命中类型都要保留。

    修复前：只有单值口径 `resolve_doc_type`（只给第一类）⇒ 材料只能落一个类型
    ⇒ 段内可外发类被同段的另一类吞掉（G5）。
    """
    types, primary, provenance, evidence = dts.resolve_doc_types(
        file_name="混合材料.txt", text=MIXED_TEXT, purpose="")
    assert set(types) == {"audit_report", "license"}, types
    assert primary == "audit_report", primary          # 主类型 = 规则表顺序第一类
    assert provenance == dts.INFERRED
    assert any(e.get("kind") == "multi_type_match" for e in evidence), evidence


def test_resolve_doc_type_single_type_unchanged():
    """**对照组**：单类型正文的读数**不得**因本修复而改变（向后兼容）。"""
    key, provenance, _ = dts.resolve_doc_type(
        file_name="营业执照2024.txt", text=PURE_LICENSE_TEXT, purpose="")
    assert key == "license"
    assert provenance == dts.INFERRED
    types, primary, _prov, _ev = dts.resolve_doc_types(
        file_name="营业执照2024.txt", text=PURE_LICENSE_TEXT, purpose="")
    assert types == ["license"] and primary == "license"


def test_filename_wins_over_content_and_does_not_merge_sources():
    """★ 边界：类型来源**不跨来源合并**（否则合同正文提到执照 ⇒ 被当成执照材料）。"""
    types, primary, _prov, _ev = dts.resolve_doc_types(
        file_name="经营资产租赁合同2024.txt", text=MIXED_TEXT, purpose="")
    assert types == ["contract"], types
    assert primary == "contract"


# ── ② 传导环：认知卡必须同时保留全部类型 ────────────────────────────────
def _card_for(tmp_path, file_name: str, text: str) -> dict:
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    f = root / file_name
    f.write_text(text, encoding="utf-8")
    mf.register_library("lib1", str(root), authorized_by="波总", db_path=_db(tmp_path))
    mf.build_manifest("lib1", db_path=_db(tmp_path))
    row = mf.get_manifest_entry("lib1", file_name, db_path=_db(tmp_path))
    assert row is not None
    return cs.build_card(row, text=text, db_path=_db(tmp_path))


def test_card_keeps_all_types_of_mixed_material(tmp_path):
    """★ 传导环判据：混合材料建出来的卡片**必须**同时保留它命中的全部类型。"""
    card = _card_for(tmp_path, "混合材料.txt", MIXED_TEXT)
    card_types = cs.doc_types_key(card)
    assert set(card_types) == {"audit_report", "license"}, card_types
    # 单值字段仍是**主类型**（向后兼容：既有单值调用方读数不变）
    assert (card.get("doc_type") or {}).get("value") == "audit_report", card.get("doc_type")


def test_card_sensitivity_of_mixed_material_is_strictest(tmp_path):
    """★ 安全方向：混合材料的等级取**最严**（含受限内容 ⇒ 整份材料受限）。"""
    card = _card_for(tmp_path, "混合材料.txt", MIXED_TEXT)
    assert (card.get("sensitivity") or {}).get("value") == "RESTRICTED", card.get("sensitivity")


# ── ③ 后果环：披露闸按**材料自己的类型**逐类判定 ─────────────────────────
def test_type_gate_uses_material_own_types():
    """★ 后果环判据：类型闸逐类判定，**全部**类型都在放行清单内才可外发。"""
    policy = pol.load_policy()
    assert policy.loaded, policy.load_error
    assert policy.sendable_doc_types == ["license"], policy.sendable_doc_types

    ok = pol.evaluate(policy, "PUBLIC", doc_type=["license"], entity=JIA)
    assert ok.externally_sendable is True, ok.reason

    bad = pol.evaluate(policy, "PUBLIC", doc_type=["audit_report"], entity=JIA)
    assert bad.externally_sendable is False, bad.reason

    # ★ fail-closed：含一类不在清单内的类型 ⇒ 整份材料不可外发
    mixed = pol.evaluate(policy, "PUBLIC", doc_type=["audit_report", "license"], entity=JIA)
    assert mixed.externally_sendable is False, mixed.reason


def test_single_type_reading_is_unchanged():
    """★ 向后兼容：单类型调用的结论与修复前**逐位一致**（含垃圾值仍被拦）。"""
    policy = pol.load_policy()
    assert policy.loaded, policy.load_error
    for junk in ("审计报告", "pdf", "not_a_real_key", ""):
        d = pol.evaluate(policy, "PUBLIC", doc_type=junk, entity=JIA)
        assert d.externally_sendable is False, f"{junk!r} 竟被放行"
        assert d.level == "RESTRICTED", junk


# ── ④ 链级复现：整段定类型 ⇒ 段内可外发类材料取不到（授权组包取不到它）──
def _g5_library(tmp_path, monkeypatch):
    """合成一个「横跨两类」的清单段 ＋ 两份材料（一份可外发类、一份受限类）。"""
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    db = _db(tmp_path)
    lib_root = tmp_path / "lib-materials"
    (lib_root / JIA).mkdir(parents=True)
    (lib_root / JIA / "营业执照2024.txt").write_text(
        f"营业执照\n{JIA}\n经营范围：合成样例。\n", encoding="utf-8")
    (lib_root / JIA / "审计报告2024.txt").write_text(
        f"审计报告\n本报告为2024年度财务审计结论，由{JIA}出具。\n", encoding="utf-8")
    mf.register_library("lib-g5", str(lib_root), authorized_by="波总", db_path=db)
    mf.build_manifest("lib-g5", db_path=db)
    ps.parse_pending_batch("lib-g5", db_path=db)
    cs.build_cards_for_library("lib-g5", db_path=db)
    rq.register_entity("lib-g5", "S1", JIA, relation="target",
                       source_ref="合成样例（测试用，非真实登记）", db_path=db)
    # ★ 关键形态：一条清单项横跨两类（用「与」连接 ⇒ **不被拆成两条**）
    #   ⇒ 整段只落**一个**类型（G5 的「整段定类型」）
    rq.ingest_checklist("lib-g5", [
        {"item_no": "1", "raw_text": f"请提供{JIA}营业执照与2024年度审计报告"},
    ], db_path=db)
    ms.match_library("lib-g5", db_path=db)
    return db


def test_segment_type_is_single_but_materials_keep_their_own(tmp_path, monkeypatch):
    """★ 前提复现：整段确实只落**一个**类型（否则本用例不成立）。"""
    db = _g5_library(tmp_path, monkeypatch)
    obls = rq.list_obligations("lib-g5", db_path=db)
    assert len(obls) == 1, [o.get("obligation") for o in obls]
    assert obls[0].get("doc_type") == "audit_report", obls[0].get("doc_type")


def test_g5_chain_license_material_is_retrievable(tmp_path, monkeypatch):
    """★ G5 的核心判据（链级）：段内**可外发类**材料不再被「整段定类型」连坐。

    修复前：披露闸按段类型（audit_report）判定 ⇒ 执照被拦下 ⇒ 授权组包取不到它。
    修复后：披露闸按**材料自己的类型**（license）判定 ⇒ 执照可交付。
    """
    db = _g5_library(tmp_path, monkeypatch)
    obls = rq.list_obligations("lib-g5", db_path=db)
    assert len(obls) == 1
    rows = ms.list_matches(obls[0]["obligation_id"], db_path=db)
    by_rel = {r.get("card_rel_path") or "": r for r in rows}
    lic = by_rel.get(f"{JIA}/营业执照2024.txt")
    aud = by_rel.get(f"{JIA}/审计报告2024.txt")
    assert lic is not None, f"执照材料没进候选：{sorted(by_rel)}"
    assert aud is not None, f"审计报告材料没进候选：{sorted(by_rel)}"

    assert lic["deliverable"] == 1, (
        f"段内可外发类材料被披露闸拦下（G5 未修复）：{lic.get('evidence')}")
    # ★ 安全方向的反向对照：受限类材料**仍必须**被拦下
    assert aud["deliverable"] == 0, (
        f"受限类材料竟被判可交付：{aud.get('evidence')}")
    assert "披露不可外发" in str(aud.get("evidence") or ""), aud.get("evidence")


def test_g5_chain_authorization_package_exports_license_only(tmp_path, monkeypatch):
    """★ 端到端：授权组包里**只有**执照类交付件，受限类被拦并记账。"""
    from cangjie_fos.services import dd_v1_package_service as pkg
    db = _g5_library(tmp_path, monkeypatch)
    rev = pkg.build_review_pack("lib-g5", institution="合成机构", db_path=db)
    pkg.approve(rev["review_id"], approved_by="波总", db_path=db)
    res = pkg.package_approved(rev["review_id"], db_path=db)
    assert res["status"] == pkg.ST_PACKAGED, res
    blocked_rel = " ".join(str(b.get("rel_path") or "") for b in res["blocked_detail"])
    assert "审计报告" in blocked_rel, res["blocked_detail"]
    exported_rel = " ".join(str(e.get("rel_path") or "") for e in res.get("exported_detail") or [])
    assert "审计报告" not in exported_rel, res.get("exported_detail")
