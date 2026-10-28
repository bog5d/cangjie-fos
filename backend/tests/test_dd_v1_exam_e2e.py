"""DD-V1 第三组：完整模拟考试（端到端实跑，零外部调用、零费用）。

**判据**（施工令「五、必须通过的测试 · 第三组」）：

    图书馆读取 → 考卷理解 → 检索 → 组包 → 隔离阅卷 → 成绩单

★ **必须实际运行**，不接受「只提交代码」。
★ 本文件走的是**真实入口**（``tools/dd_v1_local_run.py`` 的 ``run`` 子命令 ＋
  ``tools/dd_team_channel.py`` 的 ``answer`` / ``grade`` 子命令），
  不是把中间结果手搓出来糊弄。
★ 全部为**合成**材料（``tests/fixtures/dd-v1-fos71-a4``）：不含任何真实业务内容。
★ 考生侧（``frozen/examiner``）与阅卷侧（``frozen/grader``）**物理分离**；
  标准答案在本测试里被复制到**仓库之外**的受控目录（隔离闸会拒绝仓内的 Gold）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_exam_service as ex
from cangjie_fos.services import dd_v1_gold_service as gold_svc
from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_v1_local_run as lr          # noqa: E402
import dd_team_channel as tc          # noqa: E402

FX = Path(__file__).parent / "fixtures" / "dd-v1-fos71-a4"
EXAMINER = FX / "frozen" / "examiner"
GRADER = FX / "frozen" / "grader"
ITEMS = json.loads((FX / "raw_items.json").read_text("utf-8"))
GOLD = json.loads((FX / "gold.json").read_text("utf-8"))
REPLIES = FX / "replies"


def _examiner_copy(tmp_path: Path) -> Path:
    """考生可见的冻结快照（盲化后）复制到临时目录（真实数据面）。"""
    dst = tmp_path / "examiner"
    if not dst.exists():
        shutil.copytree(EXAMINER, dst)
    return dst


def _grader_copy(tmp_path: Path) -> Path:
    """阅卷侧冻结快照复制到临时目录。"""
    dst = tmp_path / "grader"
    if not dst.exists():
        shutil.copytree(GRADER, dst)
    return dst


def _gold_manifest(tmp_path: Path) -> Path:
    """把仓内 ``gold.json``（file_id 形态）转成**内容指纹**形态的标准答案包清单。

    ★ 转换**只在测试内**做：仓内 ``gold.json`` 在 Git 工作树内 ⇒ 生产路径会被隔离闸拒绝；
      这里复制到仓库之外的受控目录，模拟真实部署。
    ★ 转换同时验证了「同名不同内容 / 同内容不同路径」这条：**用 SHA256 对表，不认文件名**。
    """
    grader_meta = json.loads((_grader_copy(tmp_path) / "meta.json").read_text("utf-8"))
    grader_snap = json.loads((_grader_copy(tmp_path) / "snapshot.json").read_text("utf-8"))
    sha_by_id = {f["file_id"]: f["sha256"] for f in grader_snap["files"]}
    entity_by_id = {m["file_id"]: m.get("entity", "") for m in grader_meta}
    period_by_id = {m["file_id"]: m.get("period", "") for m in grader_meta}
    items = []
    for g in GOLD:
        files = []
        for fid in g.get("expected_files") or []:
            files.append({
                "sha256": sha_by_id.get(fid, ""),
                # ★ 阅卷侧的**原名**（考生侧是盲化名）⇒ 逼着系统按内容匹配
                "relative_path": next((m["relative_path"] for m in grader_meta
                                       if m["file_id"] == fid), ""),
                "entity": entity_by_id.get(fid, ""),
                "period": period_by_id.get(fid, ""),
            })
        items.append({
            "obligation_id": g["obligation_id"],
            "item_no": g["obligation_id"],
            "expected_verdict": g["expected_verdict"],
            "expected_files": files,
            "confirmed_by": g.get("confirmed_by", ""),
            "confirmed_at": g.get("confirmed_at", ""),
        })
    d = tmp_path / "gold_pack"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "gold_manifest.json"
    p.write_text(json.dumps({
        "schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
        "gold_pack_id": "GOLD-A4A-SYNTHETIC",
        "exam_id": "EX-A4A-SYNTHETIC",
        "checklist": {"checklist_id": "CL-A4A", "sha256": "", "item_count": len(ITEMS)},
        "library": {"library_id": "LIB-A4A", "fingerprint": "", "material_count": 0},
        "confirmed_by": "合成测试（非人工批准）",
        "confirmed_at": "2026-10-28T20:00:00+08:00",
        "items": items,
    }, ensure_ascii=False, indent=2), "utf-8")
    return p


def _run_exam(tmp_path: Path):
    """跑一次完整模拟考试：图书馆读取 → 考卷理解 → 检索 → 组包（考生答卷）。"""
    examiner = _examiner_copy(tmp_path)
    out = tmp_path / "run"
    out.mkdir()
    rc = lr.main([
        "run",
        "--material-root", str(examiner),
        "--meta", str(examiner / "meta.json"),
        "--items", str(FX / "raw_items.json"),
        "--out", str(out),
        "--synthetic-replies", str(REPLIES),
        # ★ 合成回贴走 ``manual`` 适配器（读工作目录里的 reply.json）：零进程、零费用
        "--adapter", "manual",
        # ★ 合成 fixture 被复制到仓库外（真实数据面）⇒ 必须显式放行材料读取
        "--allow-real-material",
    ])
    assert rc in (0, 2), f"local_run 退出码 {rc}"
    return out


class TestFullSimulatedExam:
    """第三组：端到端实跑。"""

    def test_end_to_end_produces_a_scorable_scorecard(self, tmp_path):
        out = _run_exam(tmp_path)
        # ── 图书馆读取 + 考卷理解 + 检索 + 组包：run_record 逐条落地
        recs = sorted(out.rglob("run_record.json"))
        assert recs, "没有产出 run_record.json"
        assert (out / "run_summary.json").exists()
        summary = json.loads((out / "run_summary.json").read_text("utf-8"))
        assert summary["groups"], summary

        # ── 机器答卷（考生侧；**不含**标准答案）
        answer_dir = tmp_path / "answer"
        answer_dir.mkdir()
        rc = tc.main(["answer", "--run-dir", str(out), "--out", str(answer_dir),
                      "--exam-id", "EX-A4A-SYNTHETIC"])
        assert rc == 0
        sheets = list(answer_dir.glob("机器答卷-*.json"))
        assert len(sheets) == 1
        sheet = json.loads(sheets[0].read_text("utf-8"))
        assert sheet["obligations"], "机器答卷没有任何义务"
        # ★ 答卷里**不得**出现标准答案字段
        blob = json.dumps(sheet, ensure_ascii=False)
        for k in ("expected_files", "expected_verdict", "confirmed_by"):
            assert f'"{k}"' not in blob, f"机器答卷里出现了标准答案字段 {k}"

        # ── 隔离阅卷 ⇒ 成绩单
        gold_p = _gold_manifest(tmp_path)
        meta = json.loads((EXAMINER / "meta.json").read_text("utf-8"))
        idx = gold_svc.index_from_snapshot(
            json.loads((EXAMINER / "snapshot.json").read_text("utf-8")), meta)
        manifest = gold_svc.load_gold_manifest(gold_p)
        leak = ex.detect_gold_leak(sheet, idx)
        assert leak["leaked"] is False, leak
        card = ex.grade_answer_sheet(sheet, manifest, library_index=idx,
                                     exam_id="EX-A4A-SYNTHETIC", min_obligations=1)
        assert card["status"] in ("SCORED", "LOW_CONFIDENCE"), card
        assert card["scores"] is not None
        assert card["gold_resolution"]["summary"]["resolved"] > 0, "标准答案一件都没对上"

        # ── 逐题明细必须能逐条回指
        assert card["rows"], "没有逐题明细"
        for row in card["rows"]:
            assert row["obligation_id"]
            assert row["outcome"] in ("CORRECT", "INCOMPLETE", "OVER_DELIVERED", "MISSED",
                                      "WRONG_ONLY", "NO_ANSWER", "EXPECTED_NONE")

    def test_grade_is_blocked_when_gold_is_missing(self, tmp_path):
        """★ 标准答案缺失 ⇒ 阻塞正式评分（**不得**当成 0 分）。"""
        out = _run_exam(tmp_path)
        answer_dir = tmp_path / "answer"
        answer_dir.mkdir()
        tc.main(["answer", "--run-dir", str(out), "--out", str(answer_dir)])
        sheet = json.loads(list(answer_dir.glob("机器答卷-*.json"))[0].read_text("utf-8"))
        meta = json.loads((EXAMINER / "meta.json").read_text("utf-8"))
        idx = gold_svc.index_from_snapshot(
            json.loads((EXAMINER / "snapshot.json").read_text("utf-8")), meta)
        card = ex.grade_answer_sheet(sheet, None, library_index=idx,
                                     gold_provided=False, min_obligations=1)
        assert card["status"] == "NOT_SCORABLE"
        assert card["scores"] is None
        assert card["blocked_by"]

    def test_zero_delivery_with_valid_gold_scores_zero(self, tmp_path):
        """★ 有效标准答案 + 0 件交付 ⇒ **0 分**（不是 NOT_SCORABLE）。"""
        out = _run_exam(tmp_path)
        answer_dir = tmp_path / "answer"
        answer_dir.mkdir()
        tc.main(["answer", "--run-dir", str(out), "--out", str(answer_dir)])
        sheet = json.loads(list(answer_dir.glob("机器答卷-*.json"))[0].read_text("utf-8"))
        # 模拟「考生一件都没交」
        for row in sheet["obligations"]:
            row["delivered"] = []
            row["selected"] = []
        sheet["summary"]["delivered_files"] = 0
        meta = json.loads((EXAMINER / "meta.json").read_text("utf-8"))
        idx = gold_svc.index_from_snapshot(
            json.loads((EXAMINER / "snapshot.json").read_text("utf-8")), meta)
        card = ex.grade_answer_sheet(sheet, gold_svc.load_gold_manifest(_gold_manifest(tmp_path)),
                                     library_index=idx, min_obligations=1)
        assert card["status"] in ("SCORED", "LOW_CONFIDENCE")
        assert card["scores"]["total_score"] == 0.0
        assert card["zero_delivery_forced_zero"] is True

    def test_gold_inside_repo_is_refused(self, tmp_path):
        """★ 隔离闸：仓内的 Gold 必须被拒（考生与标准答案不同面）。"""
        from cangjie_fos.services import dd_v1_score_service as sc
        with pytest.raises(sc.GoldIsolationError):
            gold_svc.assert_gold_isolated(FX / "gold.json")


class TestExaminerGraderSeparation:
    """★ 考生侧快照是盲化的；原始材料带真名 ⇒ 靠内容指纹对上，不是靠名字。"""

    def test_examiner_snapshot_is_blinded_while_material_is_not(self):
        exam_meta = json.loads((EXAMINER / "meta.json").read_text("utf-8"))
        material_meta = json.loads((FX / "material" / "meta.json").read_text("utf-8"))
        exam_paths = {m["relative_path"] for m in exam_meta}
        material_paths = {m["relative_path"] for m in material_meta}
        assert exam_paths != material_paths
        for p in exam_paths:
            assert "BLIND-" in p, p
        for p in material_paths:
            assert "BLIND-" not in p, p
        # ★ 内容指纹必须**一致**（盲化只改名字，不改内容）
        exam_snap = json.loads((EXAMINER / "snapshot.json").read_text("utf-8"))
        grader_snap = json.loads((GRADER / "snapshot.json").read_text("utf-8"))
        exam_sha = {f["file_id"]: f["sha256"] for f in exam_snap["files"]}
        grader_sha = {f["file_id"]: f["sha256"] for f in grader_snap["files"]}
        assert exam_sha == grader_sha

    def test_gold_resolves_by_content_not_by_name(self, tmp_path):
        """★ 标准答案按 SHA256 对上**盲化名**的文件（名字对不上）。"""
        grader_meta = json.loads((GRADER / "meta.json").read_text("utf-8"))
        grader_snap = json.loads((GRADER / "snapshot.json").read_text("utf-8"))
        sha_by_id = {f["file_id"]: f["sha256"] for f in grader_snap["files"]}
        manifest = gold_svc.load_gold_manifest(_gold_manifest(tmp_path))
        # ★ 索引必须同时吃「meta」与「冻结快照」（sha256 只在快照里）
        idx = gold_svc.index_from_snapshot(
            json.loads((EXAMINER / "snapshot.json").read_text("utf-8")),
            json.loads((EXAMINER / "meta.json").read_text("utf-8")))
        resolved = gold_svc.resolve_gold_files(manifest, idx)
        assert resolved["summary"]["resolved"] == resolved["summary"]["expected_files"]
        assert resolved["summary"]["missing_in_library"] == 0

    def test_semantic_layer_can_read_the_frozen_snapshot(self):
        """考生侧快照可被语义层只读读取（链路自检）。"""
        meta = json.loads((EXAMINER / "meta.json").read_text("utf-8"))
        pkt = sem.build_semantic_packet(EXAMINER, meta, ITEMS)
        assert pkt["obligations"]
        assert pkt["evidence"]


# ────────────────────────────────────────────────────────────────────────────
# ★ 回归守卫：**上一轮残留的交付清单**不得被当成本轮交付
# ────────────────────────────────────────────────────────────────────────────

def test_stale_delivery_manifest_is_not_counted_as_this_run_delivery(tmp_path):
    """交付目录里残留**上一轮**的 ``组包manifest.tsv`` ⇒ 本轮读数必须是 **0 件**。

    ★ 场景：本次 ``--package`` 被拒（没复制任何原件），但交付目录里还留着上一轮的清单。
      若按目录读清单 ⇒ 答卷会带上**旧交付** ⇒ 阅卷时 HR-1（0 交付强制 0 分）**不触发**
      ⇒ **把「本轮 0 交付」谎报成「有交付」** ⇒ 违反 `#85` 的「0 分必须如实报 0 分」。
    """
    import os
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import dd_team_channel as tc

    delivery = tmp_path / "交付目录"
    delivery.mkdir()
    manifest = delivery / "组包manifest.tsv"
    manifest.write_text(
        "机构编号\t义务ID\t原子义务\tfile_id\t原始材料路径\t文件名\t交付路径"
        "\t源sha256\t副本sha256\t一致\t判定\t审核结论\n"
        "1\tOBL-X\t提供审计报告\tF00001\t材料/a.txt\ta.txt\t交付/a.txt"
        "\tsha-src\tsha-src\t是\tMATCHED\t通过\n", encoding="utf-8")
    # ★ 把 mtime 改成**上一轮**（早于本次运行起点）
    old = time.time() - 3600
    os.utime(manifest, (old, old))

    class _A:
        package_out = str(delivery)

    pack = {"result": {"review_id": "RV-OLD"}}
    assert tc._read_run_delivery_manifest(_A(), pack, since=time.time()) == [], \
        "上一轮残留的交付清单不得被当成本轮交付"

    # ★ 阳性对照：同一份清单，**本轮产出**（mtime 新）⇒ 必须读得到
    os.utime(manifest, None)
    rows = tc._read_run_delivery_manifest(_A(), pack, since=time.time() - 5)
    assert rows and rows[0]["file_id"] == "F00001", rows


# ────────────────────────────────────────────────────────────────────────────
# ★ 回归守卫：**考场契约声明的主体范围**必须真的落到义务上
# ────────────────────────────────────────────────────────────────────────────

def test_contract_entity_scope_reaches_the_obligations(tmp_path):
    """契约里的 ``entity_scope`` ⇒ 落进库内义务的 ``entity_scope`` 列。

    ★ `#108` 实测「91 条义务全 UNCERTAIN、0 交付」的补救入口就在这里：
      交接文档让业务方「在考场契约里声明主体范围」——**如果这条线没接线**，
      照做也**不产生任何作用**（独立 Reviewer 抓到的接线缺口）。
    ★ 判据：跑完 ``run --contract`` 后，**未指名主体**的义务的
      ``entity_scope`` 必须变成 ``contract_single:<主体编号>``。
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import dd_team_channel as tc
    import dd_v1_manifest as dm
    from cangjie_fos.services import dd_v1_requirement_service as rq

    data_dir = tmp_path / "_plane"
    os.environ["CANGJIE_DD_V1_DATA_DIR"] = str(data_dir)
    mat = tmp_path / "材料"
    (mat / "主体甲").mkdir(parents=True)
    (mat / "主体甲" / "审计报告2024.txt").write_text(
        "审计报告\n本报告为2024年度财务审计结论，由主体甲出具。\n", encoding="utf-8")
    cl = tmp_path / "清单.tsv"
    cl.write_text("1\t提供2024年度审计报告\n", encoding="utf-8")   # ★ 不指名主体
    dm.main(["register", "--library", "SCOPE-LIB", "--root", str(mat),
             "--authorized-by", "T"])
    dm.main(["entity", "--library", "SCOPE-LIB", "--id", "E01", "--name", "主体甲",
             "--relation", "parent", "--group-root", "--source", "合成登记"])
    contract = {
        "schema_version": "dd_v1_exam_contract.v1", "exam_id": "EX-SCOPE",
        "name": "接线探针", "institution": "Institution_XX",
        "checklist": {"checklist_id": "CL", "library_id": "SCOPE-LIB",
                      "sha256": "", "item_count": 1},
        "library": {"library_id": "SCOPE-LIB", "material_root": str(mat),
                    "fingerprint": "", "material_count": 1},
        "gold": {"gold_pack_id": "G", "manifest_path": "", "provided": False},
        "entity_scope": {"scope_mode": "SINGLE_ENTITY", "group_root_id": "",
                         "entity_ids": ["E01"], "declared_by": "T",
                         "declared_at": "2026-10-29T00:00:00+08:00"},
    }
    cp = tmp_path / "契约.json"
    cp.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")

    rc = tc.main(["run", "--library", "SCOPE-LIB", "--root", str(mat),
                  "--checklist", str(cl), "--institution", "Institution_XX",
                  "--by", "T", "--contract", str(cp), "--allow-real-material"])
    assert rc == 0, rc
    obl = rq.list_obligations("SCOPE-LIB")
    assert obl, "义务没产出"
    scopes = [str(o.get("entity_scope") or "") for o in obl]
    assert any(s.startswith(rq.CONTRACT_SINGLE_PREFIX) for s in scopes), \
        f"契约声明的主体范围没落到义务上：{scopes}"
