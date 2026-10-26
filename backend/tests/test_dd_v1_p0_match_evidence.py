"""DD-V1 · P0-1「错误组包」的回归测试（匹配证据闸 + 逐行可核证据）。

## 症状与合成复现锚点

症状：**组包清单 10 行指向同一份无关文件**。

锚点（历史 A4 证据的形态）：检索到的材料 ``doc_type 空 / entity 空 /
fiscal_period 空`` ⇒ 下游拿不到类型与主体 ⇒ **匹配退化**
⇒ 同一份材料被反复当成多条义务的答案。

本文件**现场合成**那个退化材料：文件名与正文头部都**不含**任何规范材料
类型关键词、类型关键词只出现在正文**深处**（FTS 全文仍能召回它）、
文件放在库根目录（⇒ 主体为空）、文件名无年份（⇒ 期间为空）
⇒ 认知卡的 ``doc_type / entity / fiscal_period`` **三空**。

## 根因（已复核）

1. **错误匹配**：``dd_v1_selection_service.select_for_obligation`` 把
   「可交付（``deliverable``）」当成**唯一**的入选条件
   ⇒ 一份**认不出类型 / 主体 / 期间**的材料只要可交付就可能被选中。
   排序只决定先后，**不决定**能不能选。
2. **错误复制**：``组包manifest.tsv`` 的每行**不带**任何匹配证据
   ⇒ 复核者无法判断「这一行到底凭什么被选中」。

## 修法

- **匹配证据闸**：候选必须在义务**真正约束**的维度上对得上
  （主体 / 期间 / 类型），否则**连可选都不是**；
- **逐行可核证据**：组包清单每行带「类型匹配 / 主体匹配 / 期间匹配 / 匹配证据」；
- ★ **同一文件在多条义务下被引用是允许的**（有充分证据时），
  但**每一行**都必须各自带证据。

★ 全部材料都是**现场合成**的（tmp_path），零真实材料 / 零模型 / 零费用。
"""
from __future__ import annotations

import json as _json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_package_service as pkg
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_requirement_service as rq
from cangjie_fos.services import dd_v1_selection_service as selsvc

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

JIA = "合成法人甲"

#: ★ **退化材料**：类型关键词只出现在正文**深处**（> 4000 字）
#: ⇒ 文件名 / 正文头部（800 字）/ 卡片 purpose（前 4000 字）三处都认不出类型
#: ⇒ 认知卡 doc_type 空；同时文件在库根目录（主体空）、文件名无年份（期间空）。
_FILLER = "合成样例正文段落（不含任何规范材料类型关键词）。" * 200
_DEGENERATE_BODY = _FILLER + "\n本文件正文深处提到审计报告。\n"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    p = Path(tmp_path) / "_policy.json"
    p.write_text(_json.dumps(_TEST_POLICY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(p))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_dp" / "manifest.sqlite"


def _setup(tmp_path, files: dict[str, str]):
    lib = "lib-p0-1"
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


def _unlock(lib, db, rel, sensitivity="PUBLIC"):
    """把材料标为可外发级别（**只**为隔离「匹配维度」与「披露维度」）。"""
    fid = mf.get_manifest_entry(lib, rel, db_path=db)["file_id"]
    conn = mf._connect(db)
    conn.execute("UPDATE dd_v1_material_cards SET sensitivity=? WHERE file_id=?",
                 (sensitivity, fid))
    conn.commit()
    return fid


def _degenerate_library(tmp_path, n_obligations: int = 10):
    """退化材料 + N 条不同类型的义务（复现「N 行指向同一份无关文件」）。"""
    lib, root = _setup(tmp_path, {"资料001.txt": _DEGENERATE_BODY})
    _unlock(lib, _db(tmp_path), "资料001.txt")
    items = []
    for i in range(n_obligations):
        items.append({"item_no": str(i + 1),
                      "raw_text": f"请提供{2015 + i}年度审计报告"})
    rq.ingest_checklist(lib, items, db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    return lib, root


def _degenerate_card_is_degenerate(lib, db):
    """**前提复现**：认知卡的 doc_type / entity / fiscal_period **三空**。"""
    conn = mf._connect(db)
    row = conn.execute(
        "SELECT doc_type, entity, fiscal_period FROM dd_v1_material_cards "
        "WHERE library_id=?", (lib,)).fetchone()
    assert row is not None
    assert (row["doc_type"] or "") == "", row
    assert (row["entity"] or "") == "", row
    assert (row["fiscal_period"] or "") == "", row
    return row


# ── 前提：退化材料确实是「三空」 ──────────────────────────────────────────
def test_degenerate_material_card_has_empty_type_entity_and_period(tmp_path):
    """★ 前提复现：认知卡的类型/主体/期间**三空**（拿不到 ⇒ 匹配退化）。"""
    lib, _root = _setup(tmp_path, {"资料001.txt": _DEGENERATE_BODY})
    _degenerate_card_is_degenerate(lib, _db(tmp_path))


# ── 错误匹配：认不出类型的材料**不得**被选中 ─────────────────────────────
def test_material_with_unknown_type_is_never_selected(tmp_path):
    """★ 核心红测：退化材料**不得**成为任何一条义务的答案。

    修前：它是唯一的候选且 ``deliverable`` ⇒ 被选中（**红**）。
    修后：匹配证据闸拦住它（类型/期间对不上）⇒ 落到「未选用」并写明理由（**绿**）。
    """
    lib, _root = _degenerate_library(tmp_path, n_obligations=3)
    _degenerate_card_is_degenerate(lib, _db(tmp_path))

    rows = pkg._build_rows(lib, db_path=_db(tmp_path))
    assert rows, "应当有义务行"
    for r in rows:
        for p in r["selected"]:
            assert p["rel_path"] != "资料001.txt", (
                f"退化材料被选中了：{p}")
        # ★ 被拒的候选**必须**留在「未选用」里并写明理由（可审计）
        rejected = [u for u in r["unselected"] if u["rel_path"] == "资料001.txt"]
        assert rejected, r["unselected"]
        assert "匹配证据闸" in rejected[0]["reason"], rejected[0]


def test_selection_layer_refuses_degenerate_candidate_directly(tmp_path):
    """选中层（单测）：类型认不出 ⇒ 候选**连可选都不是**。"""
    cand = {
        "file_id": "f-degenerate", "card_rel_path": "资料001.txt",
        "card_title": "资料001", "score": 0.5, "deliverable": True,
        "entity_ok": 1, "period_ok": 0, "doctype_ok": 0, "evidence": "[]",
    }
    obl = {"expected_count": 0, "doc_type": "audit_report",
           "raw_text": "请提供2023年度审计报告",
           "period_from": 2023, "period_to": 2023}
    out = selsvc.select_for_obligation(obl, [cand], cand_types={"f-degenerate": []})
    assert out["selected"] == [], out["selected"]
    assert out["unselected"] and "匹配证据闸" in out["unselected"][0]["reason"]


def test_wrong_type_material_is_not_selected_for_a_typed_obligation(tmp_path):
    """类型**认得出但不对** ⇒ 同样不得被选中（不是只有「认不出」才拦）。"""
    cand = {
        "file_id": "f-lic", "card_rel_path": "合成法人甲/营业执照.txt",
        "card_title": "营业执照", "score": 0.9, "deliverable": True,
        "entity_ok": 1, "period_ok": 1, "doctype_ok": 0, "evidence": "[]",
    }
    obl = {"expected_count": 0, "doc_type": "audit_report",
           "raw_text": "请提供2023年度审计报告",
           "period_from": 2023, "period_to": 2023}
    out = selsvc.select_for_obligation(obl, [cand], cand_types={"f-lic": ["license"]})
    assert out["selected"] == [], out["selected"]
    assert "类型对不上" in out["unselected"][0]["reason"], out["unselected"][0]


def test_period_mismatch_candidate_is_not_selected(tmp_path):
    """期间对不上 ⇒ 不得被选中。"""
    cand = {
        "file_id": "f-old", "card_rel_path": "合成法人甲/审计报告2020.txt",
        "card_title": "审计报告2020", "score": 0.75, "deliverable": True,
        "entity_ok": 1, "period_ok": 0, "doctype_ok": 1, "evidence": "[]",
    }
    obl = {"expected_count": 0, "doc_type": "audit_report",
           "raw_text": "请提供2023年度审计报告",
           "period_from": 2023, "period_to": 2023}
    out = selsvc.select_for_obligation(obl, [cand],
                                       cand_types={"f-old": ["audit_report"]})
    assert out["selected"] == [], out["selected"]
    assert "期间对不上" in out["unselected"][0]["reason"], out["unselected"][0]


# ── G5 不回归：一段多类 ⇒ 两类都仍然可选 ──────────────────────────────────
def test_compound_obligation_keeps_both_types_selectable(tmp_path):
    """★ 反向对照（G5 不回归）：一段「营业执照与审计报告」⇒ **两类都可选**。

    若这里退化成「只认段落类型」，段内**可外发类**材料会被连坐
    （PR #81 登记缺口 G5 的成因环）。

    ★ 这条**不回归**用例在修前修后**都应通过**（它守的是「别把 G5 修坏」，
      不是「证明 P0-1 修好了」）⇒ 用**组包链**写，不依赖新参数。
    """
    lib, _root = _setup(tmp_path, {
        f"{JIA}/营业执照2024.txt": f"营业执照\n{JIA}\n经营范围：合成样例。\n",
        f"{JIA}/审计报告2024.txt":
            f"审计报告\n本报告为2024年度财务审计结论，由{JIA}出具。\n",
    })
    rq.register_entity(lib, "S1", JIA, relation="target",
                       source_ref="合成样例（测试用，非真实登记）", db_path=_db(tmp_path))
    _unlock(lib, _db(tmp_path), f"{JIA}/营业执照2024.txt")
    _unlock(lib, _db(tmp_path), f"{JIA}/审计报告2024.txt")
    rq.ingest_checklist(lib, [
        {"item_no": "1", "raw_text": f"请提供{JIA}营业执照与2024年度审计报告"}],
        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))

    rows = pkg._build_rows(lib, db_path=_db(tmp_path))
    assert len(rows) == 1, rows
    r = rows[0]
    # ★ G5 的不变式：段内**可外发类**材料**不得被连坐**
    #   ⇒ 它必须**通过**匹配证据闸（不是「类型对不上」被拒），
    #   且在判定层**可交付**（披露闸没拦它）。
    lic = f"{JIA}/营业执照2024.txt"
    rejected = [u for u in r["unselected"] if u["rel_path"] == lic
                and "匹配证据闸" in u["reason"]]
    assert not rejected, r["unselected"]
    mrows = ms.list_matches(r["obligation_id"], db_path=_db(tmp_path))
    lic_row = [m for m in mrows if (m.get("card_rel_path") or "") == lic]
    assert lic_row, mrows
    assert lic_row[0]["deliverable"] == 1, (
        f"段内可外发类材料被披露闸连坐了（G5 回归）：{lic_row[0].get('evidence')}")


# ── 错误复制：N 行指向同一份无关文件 ─────────────────────────────────────
def test_package_never_points_many_rows_at_the_same_unrelated_file(tmp_path):
    """★ 症状级红测：组包清单**不得**出现多行指向同一份无关材料。

    ★ 用**人工逐条确认**把每条义务放行（只放行**判定闸**），
      使这条用例**只**检验「匹配证据闸」——否则会被 P0-2 的判定闸顺带挡住，
      测不出 P0-1 本身。
    """
    lib, _root = _degenerate_library(tmp_path, n_obligations=10)
    _degenerate_card_is_degenerate(lib, _db(tmp_path))

    rev = pkg.build_review_pack(lib, db_path=_db(tmp_path))
    for obl in rq.list_obligations(lib, db_path=_db(tmp_path)):
        pkg.confirm_obligation(rev["review_id"], obl["obligation_id"],
                                confirmed_by="复核人甲",
                                reason="人工逐条确认该条义务",
                                db_path=_db(tmp_path))
    pkg.approve(rev["review_id"], approved_by="复核人甲", db_path=_db(tmp_path))
    res = pkg.package_approved(rev["review_id"], db_path=_db(tmp_path))

    out = Path(res["output_dir"])
    manifest = (out / "组包manifest.tsv").read_text(encoding="utf-8")
    assert "资料001.txt" not in manifest, (
        "退化材料被复制进正式交付包了：\n" + manifest)
    copied = [p for p in out.rglob("*") if p.is_file() and p.suffix == ".txt"]
    assert not copied, f"交付目录里有原件副本：{copied}"


# ── 逐行可核证据 ─────────────────────────────────────────────────────────
def test_every_package_manifest_row_carries_match_evidence(tmp_path):
    """★ 组包清单**每一行**都要带可核的匹配证据（类型/主体/期间）。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/审计报告2023.txt":
            f"审计报告\n本报告为2023年度财务审计结论，由{JIA}出具。\n",
    })
    rq.register_entity(lib, "S1", JIA, relation="target",
                       source_ref="合成样例（测试用，非真实登记）", db_path=_db(tmp_path))
    _unlock(lib, _db(tmp_path), f"{JIA}/审计报告2023.txt")
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": f"请提供{JIA}2023年度审计报告"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    rev = pkg.build_review_pack(lib, db_path=_db(tmp_path))
    pkg.approve(rev["review_id"], approved_by="复核人甲", db_path=_db(tmp_path))
    res = pkg.package_approved(rev["review_id"], db_path=_db(tmp_path))

    out = Path(res["output_dir"])
    lines = (out / "组包manifest.tsv").read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    for col in ("类型匹配", "主体匹配", "期间匹配", "匹配证据"):
        assert col in head, f"组包清单缺列：{col}"
    rows = [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln.strip()]
    assert rows, "应当至少有一行交付记录"
    for row in rows:
        assert row["类型匹配"] == "是", row
        assert row["主体匹配"] == "是", row
        assert row["期间匹配"] == "是", row
        assert row["匹配证据"].strip(), row


def test_same_file_referenced_by_several_obligations_carries_evidence_per_row(tmp_path):
    """★ 「同一文件服务多条义务」是**允许**的，但**每一行**都要各自带证据。"""
    lib, _root = _setup(tmp_path, {
        f"{JIA}/审计报告2023.txt":
            f"审计报告\n本报告为2023年度财务审计结论，由{JIA}出具。\n",
    })
    rq.register_entity(lib, "S1", JIA, relation="target",
                       source_ref="合成样例（测试用，非真实登记）", db_path=_db(tmp_path))
    _unlock(lib, _db(tmp_path), f"{JIA}/审计报告2023.txt")
    rq.ingest_checklist(lib, [
        {"item_no": "1", "raw_text": f"请提供{JIA}2023年度审计报告"},
        {"item_no": "2", "raw_text": f"请提供{JIA}2023年度审计报告（副本）"},
    ], db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    rev = pkg.build_review_pack(lib, db_path=_db(tmp_path))
    pkg.approve(rev["review_id"], approved_by="复核人甲", db_path=_db(tmp_path))
    res = pkg.package_approved(rev["review_id"], db_path=_db(tmp_path))

    out = Path(res["output_dir"])
    lines = (out / "组包manifest.tsv").read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    rows = [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln.strip()]
    assert len(rows) >= 1, rows
    for row in rows:
        assert row["匹配证据"].strip(), f"每一行都要带证据：{row}"
        assert row["机构编号"] != row["原子义务"], row
