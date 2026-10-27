"""DD-V1 · P0-3「披露规则与正确材料冲突」的回归测试（四方归因 + 合规放行通道）。

## 症状

营业执照、章程等**正确候选**被披露策略拦下。

## 四方归因（本文件的第一判据）

被拦必须能说出**是哪一方**拦的、**为什么**拦：

| 维度 | 读数来源 |
|---|---|
| ① 材料类型 | 认知卡的 ``doc_types``（材料**自己**命中的全部规范类型） |
| ② 敏感等级 | 认知卡的 ``sensitivity``（机器默认 or 人工补定） |
| ③ 读取状态 | manifest 的 ``parse_status`` |
| ④ 披露规则 | 版本化策略文件（级别闸 / 规则闸 / 类型闸） |

⇒ ``ms.diagnose_disclosure()`` 输出这四方的读数 + ``blocked_by``（谁拦的）
+ ``blocked_kind``（**按设计被拦** vs **误分类被拦**）。

## 修法（**不放宽**安全限制）

- 敏感等级**不明确** ⇒ 继续**默认拒绝**正式交付（fail-closed 不变）；
- 但**支持人工补定**：① 人工纠正**类型**（分类错）⇒ 机器推断的等级随策略重算；
  ② 人工**补定级别**；③ 业务负责人**逐份书面授权**（= 策略文件里登记的
  「豁免需业务负责人逐份书面授权」这条业务规则的落地，此前**只在纸面上**）；
- ★ 授权**只覆盖这一份材料**、**不放宽**别的闸（等级闸 / 规则闸 /
  ``requires_review`` / 逐件复核 / 最终人工批准 HG1 全部照旧）；
- ★ **不放行清单本身一字不改**（``sendable_doc_types`` 仍只有 ``license``）、
  ``charter`` 按现行收紧设计**仍**是 RESTRICTED。

★ 全部材料都是**现场合成**的（tmp_path），零真实材料 / 零模型 / 零费用。
"""
from __future__ import annotations

import json as _json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_policy_service as pol
from cangjie_fos.services import dd_v1_requirement_service as rq

JIA = "合成法人甲"

#: 本文件用**仓内真实策略**（``backend/config/dd_v1_disclosure_policy.json``）：
#: 放行清单只有 ``license``、``charter`` 按收紧设计是 RESTRICTED
#: ⇒ 「按设计被拦」与「误分类被误拦」才有可分辨的读数。
REAL_POLICY = Path(__file__).resolve().parents[1] / "config" / "dd_v1_disclosure_policy.json"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.delenv("CANGJIE_DD_V1_POLICY", raising=False)
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_dp" / "manifest.sqlite"


def _setup(tmp_path, files: dict[str, str]):
    lib = "lib-p0-3"
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    mf.register_library(lib, str(root), authorized_by="复核人甲", db_path=_db(tmp_path))
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib, root


def _card_of(lib, db, rel):
    fid = mf.get_manifest_entry(lib, rel, db_path=db)["file_id"]
    return fid, cs.get_card(fid, db_path=db)


def _diag(lib, db, rel):
    fid, card = _card_of(lib, db, rel)
    conn = mf._connect(db)
    mrow = conn.execute("SELECT * FROM dd_v1_manifest WHERE file_id=?",
                         (fid,)).fetchone()
    return ms.diagnose_disclosure(card, dict(mrow) if mrow else None)


# ── 前提：仓内真实策略的口径 ──────────────────────────────────────────────
def test_real_policy_release_list_is_license_only_and_untouched():
    """★ 前提：放行清单**仍只有 license**、``charter`` 仍 RESTRICTED。

    （P0-3 **不得**靠改授权清单来「让候选不漏」。）
    """
    p = pol.load_policy()
    assert p.loaded, p.load_error
    assert p.sendable_doc_types == ["license"], p.sendable_doc_types
    assert p.sensitivity_defaults["charter"] == "RESTRICTED"
    assert p.sensitivity_defaults["license"] == "PUBLIC"


# ── 四方归因 ──────────────────────────────────────────────────────────────
def test_license_material_is_not_blocked_by_the_disclosure_gate(tmp_path):
    """★ 营业执照（分类正确、策略已授权）⇒ **不得**被披露闸拦下。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/营业执照2024.txt": f"营业执照\n{JIA}\n经营范围：合成样例。\n"})
    d = _diag(lib, _db(tmp_path), f"{JIA}/营业执照2024.txt")
    assert d["blocked_by"] == "", d
    assert d["deliverable"] is True, d
    assert d["four_dimensions"]["doc_type"]["types"] == ["license"], d
    assert d["four_dimensions"]["sensitivity"]["level"] == "PUBLIC", d


def test_charter_is_blocked_by_design_and_that_is_registered_as_such(tmp_path):
    """★ 章程按现行收紧设计被拦 ⇒ **如实登记为「按设计被拦」**。

    ★ 不是「误分类」⇒ 不该去动放行清单、也不该改类型规则。
    """
    lib, _root = _setup(tmp_path, {
        f"{JIA}/公司章程.txt": f"公司章程\n{JIA}\n第一条 总则：合成样例条款。\n"})
    d = _diag(lib, _db(tmp_path), f"{JIA}/公司章程.txt")
    assert d["blocked_by"] == "policy", d
    assert d["blocked_kind"] == ms.BLOCK_KIND_AS_DESIGNED, d
    assert d["deliverable"] is False, d
    assert d["four_dimensions"]["doc_type"]["types"] == ["charter"], d
    assert d["four_dimensions"]["sensitivity"]["level"] == "RESTRICTED", d


def test_unknown_type_material_is_registered_as_misclassified(tmp_path):
    """★ 类型**认不出** ⇒ 登记为「误分类被拦」⇒ 正解是补类型/补授权，**不是**放宽。"""
    body = "合成样例正文段落（不含任何规范材料类型关键词）。" * 200 + "\n深处提到审计报告。\n"
    lib, _root = _setup(tmp_path, {"资料001.txt": body})
    d = _diag(lib, _db(tmp_path), "资料001.txt")
    assert d["four_dimensions"]["doc_type"]["types"] == [], d
    assert d["blocked_kind"] == ms.BLOCK_KIND_MISCLASSIFIED, d
    assert d["blocked_by"] == "doc_type", d


def test_unreadable_material_is_registered_as_read_failure(tmp_path):
    """★ 读取状态这一方也要能单独归因。"""
    lib, _root = _setup(tmp_path, {f"{JIA}/营业执照2024.txt": "营业执照\n"})
    fid, _card = _card_of(lib, _db(tmp_path), f"{JIA}/营业执照2024.txt")
    conn = mf._connect(_db(tmp_path))
    conn.execute("UPDATE dd_v1_manifest SET parse_status='FAILED' WHERE file_id=?",
                 (fid,))
    conn.commit()
    d = _diag(lib, _db(tmp_path), f"{JIA}/营业执照2024.txt")
    assert d["blocked_by"] == "parse_status", d
    assert d["blocked_kind"] == ms.BLOCK_KIND_UNREADABLE, d


def test_diagnosis_exposes_exactly_the_four_dimensions(tmp_path):
    """★ 归因**只**在这四方里选（不新增第五个维度）。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/营业执照2024.txt": f"营业执照\n{JIA}\n经营范围：合成样例。\n"})
    d = _diag(lib, _db(tmp_path), f"{JIA}/营业执照2024.txt")
    assert set(d["four_dimensions"]) == set(ms.DISCLOSURE_DIMENSIONS), d
    assert set(ms.DISCLOSURE_DIMENSIONS) == {"doc_type", "sensitivity",
                                             "parse_status", "policy"}


# ── 人工补定：类型（分类错）──────────────────────────────────────────────
def test_human_type_correction_flows_into_the_type_gate(tmp_path):
    """★ 核心红测：人工把材料类型改对 ⇒ **类型闸必须看到**这个裁定。

    修前：``set_human_override(doc_type=...)`` 只改单值列，**多值字段
    ``doc_types`` 不动** ⇒ 类型闸仍按旧类型判 ⇒ 人工改类型**形同虚设**。
    """
    lib, _root = _setup(tmp_path, {
        f"{JIA}/资料001.txt": f"登记材料\n{JIA}\n合成样例。\n"})
    fid, _card = _card_of(lib, _db(tmp_path), f"{JIA}/资料001.txt")

    # 人工认定：这就是营业执照（分类错）
    cs.set_human_override(fid, "doc_type", "license", db_path=_db(tmp_path))
    card = cs.get_card(fid, db_path=_db(tmp_path))
    assert cs.doc_types_key(card) == ["license"], (
        f"多值字段没跟着人工的裁定走 ⇒ 类型闸看不到：{cs.doc_types_key(card)}")

    d = _diag(lib, _db(tmp_path), f"{JIA}/资料001.txt")
    assert d["four_dimensions"]["doc_type"]["types"] == ["license"], d
    assert d["blocked_by"] == "", d
    assert d["deliverable"] is True, d


def test_human_type_correction_recomputes_the_machine_inferred_level(tmp_path):
    """★ 类型纠正后，**机器推断**的等级要按策略重算（否则改了类型仍被等级闸拦）。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/资料001.txt": f"登记材料\n{JIA}\n合成样例。\n"})
    fid, _card = _card_of(lib, _db(tmp_path), f"{JIA}/资料001.txt")
    cs.set_human_override(fid, "doc_type", "license", db_path=_db(tmp_path))
    card = cs.get_card(fid, db_path=_db(tmp_path))
    assert (card.get("sensitivity") or "") == "PUBLIC", (
        f"机器推断的等级没随人工的分类裁定重算：{card.get('sensitivity')}")


def test_human_decided_level_is_never_overwritten_by_type_correction(tmp_path):
    """★ 人的决定优先：人工**自己**定过的等级，人工再改类型时**不动**。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/资料001.txt": f"登记材料\n{JIA}\n合成样例。\n"})
    fid, _card = _card_of(lib, _db(tmp_path), f"{JIA}/资料001.txt")
    cs.set_human_override(fid, "sensitivity", "INTERNAL", db_path=_db(tmp_path))
    cs.set_human_override(fid, "doc_type", "license", db_path=_db(tmp_path))
    card = cs.get_card(fid, db_path=_db(tmp_path))
    assert (card.get("sensitivity") or "") == "INTERNAL", card.get("sensitivity")


# ── 人工补定：逐份书面授权（业务授权）────────────────────────────────────
def test_written_authorization_releases_only_that_one_material(tmp_path):
    """★ 业务负责人的**逐份书面授权**只覆盖**这一份**材料。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/公司章程A.txt": f"公司章程\n{JIA}\n第一条：合成样例。\n",
        f"{JIA}/公司章程B.txt": f"公司章程\n{JIA}\n第一条：合成样例。\n",
    })
    fid_a, _ = _card_of(lib, _db(tmp_path), f"{JIA}/公司章程A.txt")
    cs.grant_external_send(fid_a, granted_by="业务负责人甲",
                           reason="已取得该份章程的书面使用授权（合成样例）",
                           db_path=_db(tmp_path))
    # 人工把这一份的等级也补定（授权**只**替代类型闸，**不放宽**等级闸）
    cs.set_human_override(fid_a, "sensitivity", "PUBLIC", db_path=_db(tmp_path))

    d_a = _diag(lib, _db(tmp_path), f"{JIA}/公司章程A.txt")
    d_b = _diag(lib, _db(tmp_path), f"{JIA}/公司章程B.txt")
    assert d_a["blocked_by"] == "", d_a
    assert d_a["external_send_authorized"] is True, d_a
    assert d_b["blocked_by"] == "policy", d_b
    assert d_b["deliverable"] is False, d_b


def test_authorization_alone_does_not_bypass_the_level_gate(tmp_path):
    """★ 授权**不放宽**等级闸：等级仍不可外发 ⇒ 仍然默认拒绝（fail-closed 不变）。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/公司章程.txt": f"公司章程\n{JIA}\n第一条：合成样例。\n"})
    fid, _ = _card_of(lib, _db(tmp_path), f"{JIA}/公司章程.txt")
    cs.grant_external_send(fid, granted_by="业务负责人甲",
                           reason="已取得书面授权（合成样例）", db_path=_db(tmp_path))
    d = _diag(lib, _db(tmp_path), f"{JIA}/公司章程.txt")
    assert d["deliverable"] is False, d
    assert d["external_send_authorized"] is True, d
    # 等级仍是策略默认的 RESTRICTED（人工**没有**补定级别）⇒ 等级闸仍然拦
    assert d["four_dimensions"]["sensitivity"]["level"] == "RESTRICTED", d
    # ★ 归因：等级是**机器从类型推出来的**（INFERRED）⇒ 根因在「按类型收紧」那一层
    assert d["four_dimensions"]["sensitivity"]["basis"] == "INFERRED", d
    assert d["blocked_by"] == "policy", d
    assert d["blocked_kind"] == ms.BLOCK_KIND_AS_DESIGNED, d


def test_authorization_requires_a_named_granter_and_a_reason(tmp_path):
    """授权**必须**可追责（授权人 + 依据）。"""
    lib, _root = _setup(tmp_path, {f"{JIA}/资料001.txt": "登记材料\n"})
    fid, _ = _card_of(lib, _db(tmp_path), f"{JIA}/资料001.txt")
    with pytest.raises(ValueError, match="reason"):
        cs.grant_external_send(fid, granted_by="业务负责人甲", reason="",
                               db_path=_db(tmp_path))


def test_authorization_can_be_revoked(tmp_path):
    """授权**可撤销**（合规豁免必须能收回）。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/资料001.txt": f"登记材料\n{JIA}\n合成样例。\n"})
    fid, _ = _card_of(lib, _db(tmp_path), f"{JIA}/资料001.txt")
    cs.grant_external_send(fid, granted_by="业务负责人甲", reason="书面授权（合成样例）",
                           db_path=_db(tmp_path))
    cs.set_human_override(fid, "sensitivity", "PUBLIC", db_path=_db(tmp_path))
    assert _diag(lib, _db(tmp_path), f"{JIA}/资料001.txt")["deliverable"] is True
    cs.grant_external_send(fid, granted_by="", reason="", db_path=_db(tmp_path))
    d = _diag(lib, _db(tmp_path), f"{JIA}/资料001.txt")
    assert d["external_send_authorized"] is False, d
    assert d["deliverable"] is False, d


# ── 策略是数据不是代码 ───────────────────────────────────────────────────
def test_policy_file_release_list_is_not_modified_by_the_fix():
    """★ 放行清单**一字未改**（P0-3 **不得**靠改授权清单放行）。"""
    data = _json.loads(REAL_POLICY.read_text(encoding="utf-8"))
    assert data["sendable_doc_types"] == ["license"], data["sendable_doc_types"]
    assert data["public_defaults_authorized"] == ["license"], data
    assert data["sensitivity_defaults"]["charter"] == "RESTRICTED", data
    assert data["levels"]["PUBLIC"]["requires_review"] is True, data
    assert data["levels"]["RESTRICTED"]["externally_sendable"] is False, data


def test_requires_review_and_manual_approval_still_apply_after_authorization(tmp_path):
    """★ 授权**不**取代 ``requires_review`` 与最终人工批准（HG1 两道闸照旧）。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/资料001.txt": f"登记材料\n{JIA}\n合成样例。\n"})
    fid, _ = _card_of(lib, _db(tmp_path), f"{JIA}/资料001.txt")
    cs.grant_external_send(fid, granted_by="业务负责人甲", reason="书面授权（合成样例）",
                           db_path=_db(tmp_path))
    cs.set_human_override(fid, "sensitivity", "PUBLIC", db_path=_db(tmp_path))
    d = _diag(lib, _db(tmp_path), f"{JIA}/资料001.txt")
    assert d["four_dimensions"]["policy"]["requires_review"] is True, d
