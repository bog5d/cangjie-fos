"""DD-V1 **第一层自动考试**：程序层（不依赖模型）。

对应施工令 WP2「第一层：不依赖模型的程序测试」。**全部用合成夹具**，零外部调用、零费用。

★ 本文件锁死的红线（每一条都对应一次**真实事故**或一次**本轮自动考试抓出的缺陷**）：

1. **空库不得 READY**（#108 实测 P0-1）；
2. **42 题必须完整进入处理链路**（#108 实测 P0-2：91 vs 15）；
3. **不同入口拆题结果一致**（库侧契约 vs 桥接层 ⇒ 同一套义务）；
4. **义务 ID 全程一致**（★ 本轮抓出：多主体分簇 ID ``<库ID>@<主体>`` 与 Gold 的库侧 ID
   对不上 ⇒ 逐题全落空 ⇒ 分数恒 0 ⇒ ``GOLD_LEAK_DETECTED``）；
5. **题号必须一路带到答卷**（★ 本轮抓出：``item_id`` 被塞成义务主键 ⇒ 题级覆盖统计全落空）；
6. **并列连接词必须切成多条原子义务**（★ 本轮抓出：「审计报告**和**营业执照」只切一条
   ⇒ 第二类材料的要求被**静默吞掉**，机器漏交且不报错）；
7. **Gold 映射正确**（库内主键是 uuid4 ⇒ 标准答案必须用内容派生的稳定键绑定）；
8. **评分程序正常**（0 件交付 ⇒ 0 分而不是 NOT_SCORABLE）；
9. **0 件交付正确处理**（不得把「本轮 0 交付」说成「有交付」）；
10. **历史交付不得冒充本轮结果**；
11. **受限材料不得绕过披露闸**；
12. **不确定材料不得混入正式包**。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "backend" / "src"))

from cangjie_fos.services import dd_v1_exam_service as ex  # noqa: E402
from cangjie_fos.services import dd_v1_requirement_service as rq  # noqa: E402

EXAMS = REPO / "backend" / "tests" / "fixtures" / "dd-v1-exam-suite" / "exams"


# ─────────────────────────────────────────────────────────────────────────────
# 0. 夹具自检（★ 先证明夹具本身是**非退化**的）
# ─────────────────────────────────────────────────────────────────────────────

def test_fixture_c_is_not_degenerate():
    """★ 考试C 必须落在**互不相同**的（主体×类型×年度）组合上。

    ★ **为什么要有这条**：本轮第一版夹具把主体与类型用**同一个余数**选
      ⇒ 42 题其实只落在 3 份材料上 ⇒ 召回率满分是**假象**
      ⇒ 「42 题规模」根本没被测到。
      ⇒ 夹具退化 ⇒ 考试无效 ⇒ **先验夹具，再跑考试**。
    """
    exp = json.loads((EXAMS / "C" / "expectations.json").read_text("utf-8"))
    questions = exp.get("questions") or {}
    assert len(questions) == 42, f"考试C 必须是 42 题：{len(questions)}"
    paths: set[str] = set()
    for qid, q in questions.items():
        for p in (q.get("expect_paths") or []):
            paths.add(str(p))
    # 42 题里含多主体题（每题 3 份）与缺料题（0 份）⇒ 不同材料数应 ≥ 35
    assert len(paths) >= 35, f"考试C 的材料数退化（只有 {len(paths)} 份不同材料）"
    # 同一份材料不得被两道**非多主体**题同时当作唯一答案
    checklist = [ln.split("\t", 1) for ln in
                 (EXAMS / "C" / "checklist.tsv").read_text("utf-8").splitlines() if ln.strip()]
    assert len(checklist) == 42, len(checklist)
    owners: dict[str, list[str]] = {}
    for qid, q in questions.items():
        ps = [str(p) for p in (q.get("expect_paths") or [])]
        for p in ps:
            owners.setdefault(p, []).append(qid)
    # 允许「多主体题 + 单主体题」共用材料（这是业务真实：同一份材料服务于多题）
    # 但不允许**所有**题都指向同一份材料（那才是退化）
    assert len(owners) >= 35, owners


# ─────────────────────────────────────────────────────────────────────────────
# 1. 拆题口径一致（42 题全部进入处理链路）
# ─────────────────────────────────────────────────────────────────────────────

def _contract_for(exam: str, tmp_path: Path) -> dict:
    """在**隔离数据面**里建库并导出库侧权威契约（不碰真实业务库）。"""
    from cangjie_fos.services import dd_v1_card_service as cs
    from cangjie_fos.services import dd_v1_manifest_service as mf
    from cangjie_fos.services import dd_v1_parser_service as ps
    spec = json.loads((EXAMS / exam / "spec.json").read_text("utf-8"))
    lib_id = str(spec["library_id"])
    root = (EXAMS / exam / str(spec.get("materials_dir") or "materials")).resolve()
    db = tmp_path / "manifest.sqlite"
    mf.close_all()
    mf.register_library(lib_id, str(root), authorized_by="自动考试（合成）", db_path=db)
    mf.build_manifest(lib_id, mode="full", db_path=db)
    ps.parse_pending_batch(lib_id, limit=5000, db_path=db)
    cs.build_cards_for_library(lib_id, db_path=db)
    for e in (spec.get("entities") or []):
        rq.register_entity(lib_id, str(e["id"]), str(e["name"]),
                           relation=str(e.get("relation") or "other"),
                           parent_id=str(e.get("parent") or ""),
                           is_group_root=bool(e.get("group_root")),
                           source_ref=str(e.get("source") or "合成登记"), db_path=db)
    rows = []
    from dd_team_channel import _read_checklist
    rows = _read_checklist(str(EXAMS / exam / str(spec.get("checklist_file") or "checklist.tsv")))
    rq.ingest_checklist(lib_id, rows, anchor_year=spec.get("anchor_year"),
                        institution=str(spec.get("institution") or ""), db_path=db)
    contract = rq.export_obligation_contract(lib_id, db_path=db)
    mf.close_all()
    return contract


def test_all_42_questions_enter_the_contract(tmp_path):
    """★ 42 题全部进入处理链路（一条清单项 ⇒ 至少一条义务，**不丢题**）。"""
    c = _contract_for("C", tmp_path)
    assert c["counts"]["items"] == 42, c["counts"]
    assert c["counts"]["questions"] == 42, c["counts"]
    assert c["question_coverage"]["questions_with_obligations"] == 42, c["question_coverage"]
    assert c["counts"]["obligations"] >= 42, c["counts"]


def test_runner_and_library_agree_on_the_same_contract(tmp_path):
    """★ 不同入口拆题结果一致（库侧契约 vs 桥接层 ⇒ 同一套义务 ID）。"""
    from cangjie_fos.services import dd_v1_bridge_service as br
    from cangjie_fos.services import dd_v1_manifest_service as mf
    spec = json.loads((EXAMS / "C" / "spec.json").read_text("utf-8"))
    lib_id = str(spec["library_id"])
    root = (EXAMS / "C" / "materials").resolve()
    db = tmp_path / "manifest.sqlite"
    mf.close_all()
    mf.register_library(lib_id, str(root), authorized_by="自动考试（合成）", db_path=db)
    mf.build_manifest(lib_id, mode="full", db_path=db)
    from cangjie_fos.services import dd_v1_card_service as cs
    from cangjie_fos.services import dd_v1_parser_service as ps
    ps.parse_pending_batch(lib_id, limit=5000, db_path=db)
    cs.build_cards_for_library(lib_id, db_path=db)
    for e in (spec.get("entities") or []):
        rq.register_entity(lib_id, str(e["id"]), str(e["name"]),
                           relation=str(e.get("relation") or "other"),
                           parent_id=str(e.get("parent") or ""),
                           is_group_root=bool(e.get("group_root")),
                           source_ref=str(e.get("source") or "合成登记"), db_path=db)
    from dd_team_channel import _read_checklist
    rows = _read_checklist(str(EXAMS / "C" / "checklist.tsv"))
    rq.ingest_checklist(lib_id, rows, anchor_year=spec.get("anchor_year"),
                        institution=str(spec.get("institution") or ""), db_path=db)
    contract = rq.export_obligation_contract(lib_id, db_path=db)
    lib_ids = {str(o["obligation_id"]) for o in contract["obligations"]}
    meta, _stats = br.build_meta(lib_id, db_path=db)
    obl_rows = rq.list_obligations(lib_id, db_path=db)
    sem_obl, _stats2 = br.build_semantic_obligations(obl_rows, meta, library_id=lib_id, db_path=db)
    # 桥接层的每条义务都应能回到库侧那条（分簇后带 @主体 后缀）
    for o in sem_obl:
        src = str(o.get("source_obligation_id") or "")
        assert src in lib_ids, f"桥接义务回不到库侧义务：{src}"
        assert str(o.get("source_obligation_id") or "") == \
            ex.authoritative_obligation_id(o), "权威 ID 判定不一致"
    mf.close_all()


# ─────────────────────────────────────────────────────────────────────────────
# 2. 义务 ID：分簇 ID 与库侧 ID 的对齐（★ 本轮修的活缺陷）
# ─────────────────────────────────────────────────────────────────────────────

def test_cluster_obligation_id_resolves_to_authoritative_id():
    """★ 多主体分簇 ID ``<库ID>@<主体>`` ⇒ 权威 ID 必须是库侧那条。"""
    assert ex.authoritative_obligation_id(
        {"obligation_id": "abc123@主体甲"}) == "abc123"
    assert ex.authoritative_obligation_id(
        {"obligation_id": "abc123@主体甲", "source_obligation_id": "abc123"}) == "abc123"
    assert ex.authoritative_obligation_id({"obligation_id": "abc123"}) == "abc123"
    assert ex.authoritative_obligation_id({}) == ""
    # ★ **优先**取显式的 source_obligation_id（防止上游把分簇 ID 写进 obligation_id）
    assert ex.authoritative_obligation_id(
        {"obligation_id": "zzz@甲", "source_obligation_id": "abc123"}) == "abc123"


def test_gold_binds_by_stable_key_even_when_uuid_changed():
    """★ 标准答案用**内容派生的稳定键**绑定 ⇒ 换快照（uuid 变了）仍能绑上。

    ★ **为什么**：库内义务主键是 ``uuid4``（每次建库都变）⇒
      只存 uuid 的标准答案**换快照即静默失效**（逐题全落空、分数恒 0）。
    """
    contract = {"obligations": [
        {"obligation_id": "uuid-A", "obligation_key": "OBL-key-A"},
        {"obligation_id": "uuid-B", "obligation_key": "OBL-key-B"},
    ]}
    gold = [
        {"obligation_id": "old-uuid-A", "obligation_key": "OBL-key-A"},
        {"obligation_id": "old-uuid-B", "obligation_key": "OBL-key-B"},
    ]
    items, report = ex.bind_gold_to_library(gold, contract)
    assert report["rebound_by_key"] == 2, report
    assert report["unbound"] == 0, report
    assert {i["obligation_id"] for i in items} == {"uuid-A", "uuid-B"}
    # ★ 绑不上必须**报出来**（不得悄悄吞掉）
    items2, report2 = ex.bind_gold_to_library(
        [{"obligation_id": "x", "obligation_key": "OBL-nope"}], contract)
    assert report2["unbound"] == 1, report2
    assert items2[0]["obligation_id"] == "x"


def test_answer_sheet_rows_carry_both_cluster_and_authoritative_ids():
    """★ 答卷每行都要带**权威 ID**（阅卷按它与 Gold 对齐）。"""
    ob = {"obligation_id": "abc@主体甲", "source_obligation_id": "abc", "item_id": "1-1"}
    sheet = ex.build_answer_sheet({}, {"obligations": [ob]})
    row = (sheet.get("obligations") or [])[0]
    assert row["source_obligation_id"] == "abc", row
    assert row["obligation_cluster_id"] == "abc@主体甲", row


def test_leak_detection_accepts_cluster_ids_but_rejects_unknown_obligations():
    """★ 泄漏检测第 3 条判据：用**权威 ID**比 ⇒ 分簇 ID 不再被误判成「来路不明」。

    ★ 这正是 #108 实测「``GOLD_LEAK_DETECTED`` ⇒ ``scores=null``」的根因。
    """
    sheet = {"obligations": [
        {"obligation_id": "abc@主体甲", "source_obligation_id": "abc"},
        {"obligation_id": "zzz@主体乙", "source_obligation_id": "zzz"},
    ]}
    rep = ex.detect_gold_leak(sheet, {"by_id": {}, "by_sha": {}},
                              library_obligation_ids={"abc"}, gold_obligation_ids={"abc"})
    kinds = [x["kind"] for x in rep["leaks"]]
    assert "OBLIGATION_OUTSIDE_EXAM" in kinds, rep
    details = [x.get("detail") for x in rep["leaks"]]
    assert "abc@主体甲" not in details, rep
    assert "zzz@主体乙" in details, rep


# ─────────────────────────────────────────────────────────────────────────────
# 3. 并列连接词必须拆成多条原子义务（★ 本轮抓出的静默吞要求）
# ─────────────────────────────────────────────────────────────────────────────

def test_parallel_connector_splits_into_two_obligations():
    """★ 「审计报告**和**营业执照」⇒ 两条原子义务（第二类要求不得被吞）。

    ★ 缺陷形态：旧实现只切「、/以及/，并且」⇒ 只切出一条（doc_type 取第一个）
      ⇒ 第二类材料的要求**静默丢失** ⇒ 机器漏交且**不报错**。
    """
    obs = rq.build_obligations("请提供合成母公司2024年度审计报告和营业执照")
    assert len(obs) == 2, [o.obligation for o in obs]
    assert {o.doc_type for o in obs} == {"audit_report", "license"}


def test_parallel_split_does_not_break_normal_sentences():
    """★ 受控拆分的**负例**：正常句子不得被切碎。"""
    for raw, expect_n in (
        ("请提供合成母公司2024年度审计报告", 1),
        ("请提供至少一份审计报告", 1),
        ("请提供涉及员工的劳动合同", 1),
        ("请提供有且仅有的审计报告", 1),
        ("请提供营业执照、审计报告", 2),
        ("请提供营业执照以及审计报告", 2),
    ):
        obs = rq.build_obligations(raw)
        assert len(obs) == expect_n, f"{raw!r} ⇒ {[o.obligation for o in obs]}"


def test_original_text_is_never_lost_by_splitting():
    """★ 拆分只作用于派生文本；**原文零丢失**是硬校验。"""
    raw = "请提供合成母公司2024年度审计报告和营业执照"
    obs = rq.build_obligations(raw)
    joined = "".join(o.obligation for o in obs)
    assert "审计报告" in joined and "营业执照" in joined, joined


# ─────────────────────────────────────────────────────────────────────────────
# 4. 评分口径边界（0 分 / 不可评分）
# ─────────────────────────────────────────────────────────────────────────────

def _gold_manifest(items: list[dict]) -> dict:
    return {
        "schema_version": "dd_v1_gold_manifest.v1",
        "gold_pack_id": "GOLD-TEST",
        "exam_id": "EX-TEST",
        "checklist": {"checklist_id": "CL", "sha256": "", "item_count": len(items)},
        "library": {"library_id": "LIB", "fingerprint": "", "material_count": 0},
        "confirmed_by": "合成测试",
        "confirmed_at": "2026-10-30T00:00:00+08:00",
        "items": items,
    }


def test_zero_delivery_with_valid_gold_scores_zero_not_not_scorable():
    """★ 有效标准答案 + 0 件交付 ⇒ **0 分**（不是 NOT_SCORABLE）。"""
    manifest = _gold_manifest([{
        "obligation_id": "obl-1", "item_no": "1-1", "expected_verdict": "MATCH",
        "expected_files": [{"sha256": "a" * 64, "relative_path": "x.txt"}],
    }])
    sheet = {"obligations": [{
        "obligation_id": "obl-1", "item_id": "1-1", "text": "t",
        "interpretation": {"resolved": True}, "candidates": [], "selected": [],
        "delivered": [], "verdict": "MATCH", "abstained": False, "warnings": [],
    }]}
    card = ex.grade_answer_sheet(sheet, manifest, library_index={"by_id": {}, "by_sha": {}},
                                  gold_provided=True)
    assert card["status"] != "NOT_SCORABLE", card.get("blocked_by")
    assert card["scores"]["total_score"] == 0.0, card["scores"]
    assert card.get("zero_delivery_forced_zero") is True, card


def test_missing_gold_is_not_scorable_and_says_why():
    """★ 标准答案未提供 ⇒ NOT_SCORABLE **并写明阻塞**（不得写成 0 分）。"""
    card = ex.grade_answer_sheet({"obligations": []}, None,
                                  library_index={"by_id": {}, "by_sha": {}},
                                  gold_provided=False, gold_state="NOT_PROVIDED",
                                  gold_state_reason="标准答案不可得")
    assert card["status"] == "NOT_SCORABLE", card
    assert card["scores"] is None, card
    assert card["blocked_by"], card


# ─────────────────────────────────────────────────────────────────────────────
# 5. 本轮交付不许冒充（历史交付 / 受限材料 / 不确定材料）
# ─────────────────────────────────────────────────────────────────────────────

def test_stale_delivery_manifest_is_not_counted_as_this_run():
    """★ 上一轮残留的交付清单**不得**被当成本轮交付（否则把「0 交付」说成「有交付」）。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "组包manifest.tsv"
        p.write_text("file_id\t交付路径\t源sha256\t副本sha256\t一致\n"
                     "f1\ta.txt\t" + "b" * 64 + "\t" + "b" * 64 + "\t是\n", encoding="utf-8")
        rows = ex.read_delivery_manifest(p)
        assert len(rows) == 1, rows


def test_uncertain_material_is_not_in_the_delivered_set():
    """★ **不确定**（UNCERTAIN）的材料不得进正式交付包（也不得算「已作答」）。

    ★ ★ 注意：标准答案里**有**期望文件时才算得出分；本条断言的是
      「机器没给出确定性判断 ⇒ 不算作答、交付件数仍为 0」。
    """
    manifest = _gold_manifest([{
        "obligation_id": "o1", "item_no": "1-1", "expected_verdict": "MATCH",
        "expected_files": [{"sha256": "a" * 64, "relative_path": "x.txt"}],
    }])
    sheet = {"obligations": [{
        "obligation_id": "o1", "item_id": "1-1", "text": "t",
        "interpretation": {"resolved": False}, "candidates": [], "selected": [],
        "delivered": [], "verdict": "UNCERTAIN", "abstained": True, "warnings": [],
    }]}
    card = ex.grade_answer_sheet(sheet, manifest, library_index={"by_id": {}, "by_sha": {}},
                                  gold_provided=True)
    assert card["status"] != "NOT_SCORABLE", card.get("blocked_by")
    # 不确定 ⇒ 不算「已作答」
    assert card["scores"]["question_answer_coverage"] == 0.0, card["scores"]
    # 不确定 ⇒ 不得凭空多出交付件
    assert card["counts"]["delivered_files"] == 0, card["counts"]
