"""DD-V1 盲化测试（A4a · G-A4a-1 盲化 + G-A4a-5 合成盲测链路自检）。

判据对应
--------
- **A4-1**：盲化目录里 grep 不到题号 / 机构名 / 项目名；映射表与材料分离；
  还原后 sha256 逐件一致。
- **A4-5**：合成盲测 exit 0，产出 score.json / score.csv / 错误分类表，
  6 类错误各 ≥1 例（TP / FP / FN / 错主体 / 错年度 / 自信错配）+ ≥1 例 UNCERTAIN（不进 FN）。

红线：合成盲测只是**链路自检**——没有任何模型参与，也不是「盲考通过」。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_blind_service as bl
from cangjie_fos.services import dd_v1_doc_type_service as dt

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_v1_local_run as lr  # noqa: E402

FIXTURE = REPO / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4"
MATERIAL = FIXTURE / "material"
LEAK_WORDS = "Q-2024-07,案例甲机构,案例乙机构,星海项目"
LEAK_LIST = LEAK_WORDS.split(",")


def _meta():
    return json.loads((MATERIAL / "meta.json").read_text("utf-8"))


def _blind(tmp_path, leak_words=None):
    return bl.blind_material(MATERIAL, _meta(), leak_words=leak_words or LEAK_LIST,
                             blind_dir=tmp_path / "blind",
                             mapping_out=tmp_path / "mapping.json",
                             meta_file=MATERIAL / "meta.json")


# ---------------- G-A4a-1 盲化

def test_blind_removes_leak_words_from_paths_and_content(tmp_path):
    res = _blind(tmp_path)
    check = bl.verify_blind(res["blind_dir"], LEAK_LIST)
    assert check["ok"] is True and check["hits"] == []
    # 原始目录里确实有泄漏词（否则这条用例没有判别力）
    assert bl.verify_blind(MATERIAL, LEAK_LIST)["ok"] is False


def test_blind_keeps_file_id_and_material_semantics(tmp_path):
    res = _blind(tmp_path)
    old = {m["file_id"]: m for m in _meta()}
    new = {m["file_id"]: m for m in res["meta"]}
    assert set(old) == set(new)                       # file_id 集合不变
    for fid, m in new.items():
        assert m["file_id"] == fid                     # file_id 本身不变
        assert m["entity"] == old[fid]["entity"]       # 主体语义不变
        assert m["period"] == old[fid]["period"]       # 期间语义不变
        assert m["doc_type"] == old[fid]["doc_type"]   # 材料类型语义不变
        assert m["relative_path"] != old[fid]["relative_path"] or "案例" not in old[fid]["relative_path"]


def test_blind_mapping_must_not_live_inside_material_dir(tmp_path):
    with pytest.raises(bl.BlindError, match="BLIND_MAPPING_INSIDE_MATERIAL"):
        bl.blind_material(MATERIAL, _meta(), leak_words=LEAK_LIST,
                          blind_dir=tmp_path / "blind", mapping_out=tmp_path / "blind" / "m.json",
                          meta_file=MATERIAL / "meta.json")


def test_blind_refuses_blind_dir_inside_source(tmp_path):
    with pytest.raises(bl.BlindError, match="BLIND_DIR_INSIDE_SOURCE"):
        bl.blind_material(MATERIAL, _meta(), leak_words=LEAK_LIST,
                          blind_dir=MATERIAL / "blind", mapping_out=tmp_path / "m.json",
                          meta_file=MATERIAL / "meta.json")


def test_restore_round_trip_is_sha256_identical(tmp_path):
    res = _blind(tmp_path)
    out = bl.restore_material(res["blind_dir"], res["mapping"], restore_dir=tmp_path / "restored")
    import hashlib
    def sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    src_files = sorted(p for p in MATERIAL.rglob("*") if p.is_file())
    assert len(src_files) == 9                        # 8 件材料 + meta.json
    for p in src_files:
        rel = p.relative_to(MATERIAL)
        assert (out / rel).is_file()
        assert sha(out / rel) == sha(p)               # 逐件 sha256 一致


def test_restore_detects_tampered_blind_copy(tmp_path):
    res = _blind(tmp_path)
    victim = sorted(Path(res["blind_dir"]).rglob("*.txt"))[0]
    victim.write_text(victim.read_text("utf-8") + "tampered\n", "utf-8")
    with pytest.raises(bl.BlindError, match="BLIND_RESTORE_SHA_MISMATCH"):
        bl.restore_material(res["blind_dir"], res["mapping"], restore_dir=tmp_path / "restored")


def test_verify_blind_reports_leak_hits(tmp_path):
    res = _blind(tmp_path)
    out = bl.verify_blind(res["blind_dir"], LEAK_LIST + ["审计报告"])
    assert out["ok"] is False
    assert any(h["kind"] == "CONTENT" for h in out["hits"])


def test_blinded_names_are_not_index_artifacts(tmp_path):
    res = _blind(tmp_path)
    for p in Path(res["blind_dir"]).rglob("*.txt"):
        assert dt.is_index_artifact(p.name) is False   # 不得命中「数字 + 分隔符」前缀


def test_substitution_table_is_deterministic():
    t1 = bl.build_substitution_table(["B", "AAA", "AA"])
    t2 = bl.build_substitution_table(["AA", "AAA", "B"])
    assert t1 == t2
    assert all(p.startswith("BLIND-") for p in t1.values())


def test_placeholder_collision_fails_closed(tmp_path):
    src = tmp_path / "m"
    src.mkdir()
    (src / "a.txt").write_text("原文含 BLIND-0001 占位符\n", "utf-8")
    meta = [{"file_id": "X1", "relative_path": "a.txt", "entity": "主体甲", "period": "2024",
             "doc_type": "审计报告", "part": "正文", "version_status": "EFFECTIVE"}]
    (src / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    with pytest.raises(bl.BlindError, match="BLIND_PLACEHOLDER_COLLISION"):
        bl.blind_material(src, meta, leak_words=["原文"], blind_dir=tmp_path / "b",
                          mapping_out=tmp_path / "m.json", meta_file=src / "meta.json")


# ---------------- G-A4a-5 合成盲测（链路自检；零模型、零费用）

def test_cli_synthetic_blind_exam_end_to_end(tmp_path):
    """盲化 → 冻结 → 拆分 → 跑（预置回贴）→ 评分 ⇒ run 退出码 0，分类覆盖 6 类 + UNCERTAIN。"""
    # gm-fix-a4a-minors:freeze-target-to-tmp
    # ★ 冻结目标必须指向 tmp_path：仓内 frozen/ 是**交付物**（只读 0555），
    #   早前版本把它当冻结目标并在 finally 里 rmtree ⇒ 每跑一次全量 pytest
    #   就毁掉 A4a 的交付证据（与 A3 MINOR-4「doctor 用例改写 uv.lock」同型）。
    #   freeze_snapshot() 自己会 mkdir ⇒ 目标**不必**预先存在。
    freeze_dir = tmp_path / "frozen" / "examiner"
    obl = tmp_path / "obligations.json"
    items = tmp_path / "blinded_items.json"
    try:
        assert lr.main(["split", "--items", str(FIXTURE / "raw_items.json"), "--out", str(obl),
                        "--blind-leak-words", LEAK_WORDS, "--blind-items-out", str(items)]) == 0
        assert len(json.loads(obl.read_text("utf-8"))) == 8
        assert lr.main(["run",
                        "--material-root", str(MATERIAL), "--meta", str(MATERIAL / "meta.json"),
                        "--items", str(items), "--obligations", str(obl),
                        "--blind-material-out", str(tmp_path / "blind"),
                        "--blind-leak-words", LEAK_WORDS,
                        "--blind-mapping-out", str(tmp_path / "mapping.json"),
                        "--snapshot-freeze-dir", str(freeze_dir),
                        "--adapter", "manual", "--synthetic-replies", str(FIXTURE / "replies"),
                        "--out", str(tmp_path / "run")]) == 0
        # Gold 必须落在任何 Git 工作树之外 ⇒ 复制到临时目录再用
        gold = tmp_path / "gold" / "gold.json"
        gold.parent.mkdir(parents=True)
        shutil.copy(FIXTURE / "gold.json", gold)
        score_dir = tmp_path / "score"
        score_dir.mkdir()
        assert lr.main(["score", "--run-dir", str(tmp_path / "run"), "--gold", str(gold),
                        "--material-root", str(freeze_dir), "--classify",
                        "--classify-meta", str(freeze_dir / "meta.json"),
                        "--out", str(score_dir / "score.json"),
                        "--classify-out", str(score_dir / "errors.csv")]) == 0
        res = json.loads((score_dir / "score.json").read_text("utf-8"))
        counts = res["classification"]["counts"]
        for cat in ("TP", "FP", "FN", "WRONG_ENTITY", "WRONG_PERIOD", "CONFIDENT_MISMATCH"):
            assert counts[cat] >= 1, (cat, counts)          # 6 类各 ≥1 例
        assert counts["UNCERTAIN"] >= 1                       # UNCERTAIN 单列
        assert counts["FN"] == 1                             # UNCERTAIN **不进 FN**
        assert res["provenance"]["synthetic_replay"] is True
        assert res["provenance"]["independent_examinee_answer"] is False
        assert res["provenance"]["model_id_or_unknown"] == "UNKNOWN"
        # 盲化有效 + 映射表与材料分离
        assert bl.verify_blind(tmp_path / "blind", LEAK_LIST)["ok"] is True
        assert not (tmp_path / "blind" / "mapping.json").exists()
        # 错误能回指 run_record + file_id + locator
        for row in res["classification"]["rows"]:
            assert row["run_record_path"].startswith("run-R")
            assert row["file_id"] and row["locator"]
            assert row["locator_source"] in ("ANSWER_CANDIDATE", "RULE_ONLY_DERIVED")
        # 错误分类表落盘
        assert (score_dir / "errors.csv").is_file()
    finally:
        from cangjie_fos.services import dd_v1_snapshot_freeze_service as fz
        if freeze_dir.exists():
            fz.make_writable(freeze_dir)
            shutil.rmtree(freeze_dir, ignore_errors=True)


def test_run_record_declares_synthetic_provenance(tmp_path):
    """产物上必须标 model_id_or_unknown=UNKNOWN / independent_examinee_answer=false。"""
    # gm-fix-a4a-minors:freeze-target-to-tmp
    # ★ 冻结目标必须指向 tmp_path：仓内 frozen/ 是**交付物**（只读 0555），
    #   早前版本把它当冻结目标并在 finally 里 rmtree ⇒ 每跑一次全量 pytest
    #   就毁掉 A4a 的交付证据（与 A3 MINOR-4「doctor 用例改写 uv.lock」同型）。
    #   freeze_snapshot() 自己会 mkdir ⇒ 目标**不必**预先存在。
    freeze_dir = tmp_path / "frozen" / "examiner"
    try:
        assert lr.main(["run", "--material-root", str(MATERIAL), "--meta", str(MATERIAL / "meta.json"),
                        "--items", str(FIXTURE / "raw_items.json"),
                        "--blind-material-out", str(tmp_path / "blind"),
                        "--blind-leak-words", LEAK_WORDS,
                        "--blind-mapping-out", str(tmp_path / "mapping.json"),
                        "--snapshot-freeze-dir", str(freeze_dir),
                        "--adapter", "manual", "--synthetic-replies", str(FIXTURE / "replies"),
                        "--out", str(tmp_path / "run")]) == 0
    finally:
        from cangjie_fos.services import dd_v1_snapshot_freeze_service as fz
        if freeze_dir.exists():
            fz.make_writable(freeze_dir)
            shutil.rmtree(freeze_dir, ignore_errors=True)
    rec = json.loads((tmp_path / "run" / "run-R1" / "run_record.json").read_text("utf-8"))
    assert rec["adapter"]["model_id_or_unknown"] == "UNKNOWN"
    assert rec["adapter"]["provenance"]["independent_examinee_answer"] is False
    assert rec["adapter"]["provenance"]["reply_source"] == "SYNTHETIC_REPLAY"
