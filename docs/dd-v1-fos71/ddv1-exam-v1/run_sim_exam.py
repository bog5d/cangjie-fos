#!/usr/bin/env python3
"""DD-V1 考场 V1 · 完整模拟考试证据生成器（零外部调用、零费用）。

**干什么**：用仓内**合成** fixture（``backend/tests/fixtures/dd-v1-fos71-a4``）
走**真实团队入口**（``tools/dd_team_channel.py run --package --approved-by``）
跑一遍完整链路：

    图书馆读取 → 考卷理解 → 检索 → 组包（审核＋复制原件）→ 隔离阅卷 → 成绩单

**同时产出第四组「旧版本对照」**：同一座考场、同一份标准答案，
把**旧口径**（``score_against_gold`` 的 accuracy）与**新口径**（0—100 成绩单）
并排打出来。★ 旧口径**没有** 0—100、没有逐题明细、没有安全闸分项 ⇒
**旧版本未建立可比基线**（**禁补造历史分数**）。

**用法**（在仓库根目录）::

    python docs/dd-v1-fos71/ddv1-exam-v1/run_sim_exam.py

★ 全部材料为**合成**数据，不含任何真实业务内容；
★ 材料被复制到**仓库外**的临时目录（受控数据面），标准答案同样在仓库外
  （隔离闸会拒绝仓内的 Gold —— 这是设计，不是缺陷）。
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(REPO / "tools"))

# ★★★ 数据面隔离：**必须在 import 服务模块之前**设好环境变量 ——
#   各服务在**导入时**读 ``CANGJIE_DD_V1_DATA_DIR`` ⇒ 设晚了会写进**仓库的**
#   ``backend/data/dd_v1``（合成数据污染真实库；实测踩过）。
_SIM_TMP = Path(tempfile.mkdtemp(prefix="ddv1-sim-"))
os.environ["CANGJIE_DD_V1_DATA_DIR"] = str(_SIM_TMP / "data")

import dd_team_channel as tc            # noqa: E402
import dd_v1_manifest as dm              # noqa: E402
from cangjie_fos.services import dd_v1_agent_result_service as ar       # noqa: E402
from cangjie_fos.services import dd_v1_exam_service as ex               # noqa: E402
from cangjie_fos.services import dd_v1_gold_service as gold_svc         # noqa: E402
from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem  # noqa: E402

FX = BACKEND / "tests" / "fixtures" / "dd-v1-fos71-a4"
MATERIAL = FX / "frozen" / "examiner"   # ★ 盲化快照＝标准答案能对上内容指纹的那一份
GRADER = FX / "frozen" / "grader"
OUT = Path(__file__).resolve().parent / "证据"


def _sha256(path: Path) -> str:
    return ar.sha256_file(path)


def _library_index(library_id: str, material_root: Path) -> dict:
    """由**本库 Manifest** 建图书馆索引（内容寻址，与文件名无关）。

    ★ ``file_id`` 必须用**库里的真实 file_id**（Manifest 以内容哈希命名），
      否则考生答卷里的 file_id 会被误判成「库外文件」⇒ 误报泄漏。
    ★ ``sha256`` 取 Manifest 的 ``content_hash``（实测＝磁盘实算的**完整 64 位** sha256，
      10/10 逐件相同）⇒ 与标准答案侧**同口径**。
    """
    from cangjie_fos.services import dd_v1_bridge_service as br
    meta, _stats = br.build_meta(library_id)
    return gold_svc.index_from_snapshot(None, meta)


def _gold_manifest(tmp: Path, gold_items: list[dict]) -> Path:
    """仓内 ``gold.json``（file_id 形态）→ **内容指纹**形态的标准答案包清单（仓库外）。

    ★ 标准答案的 ``obligation_id`` 必须挂到**本次答卷的真实义务 id** 上
      （库内主键是内容哈希，不是 ``R1-O1`` 这种清单编号）⇒ 由调用方传入映射好的条目。
    ★ 期望材料只给 **SHA256 内容指纹**（禁按文件名认定）。
    """
    grader_snap = json.loads((GRADER / "snapshot.json").read_text("utf-8"))
    grader_meta = json.loads((GRADER / "meta.json").read_text("utf-8"))
    sha_by_id = {f["file_id"]: f["sha256"] for f in grader_snap["files"]}
    entity_by_id = {m["file_id"]: m.get("entity", "") for m in grader_meta}
    period_by_id = {m["file_id"]: m.get("period", "") for m in grader_meta}
    items = []
    for g in gold_items:
        items.append({
            "obligation_id": g["obligation_id"], "item_no": g["obligation_id"],
            "expected_verdict": g["expected_verdict"],
            "expected_files": [{
                "sha256": sha_by_id.get(fid, ""),
                "relative_path": next((m["relative_path"] for m in grader_meta
                                       if m["file_id"] == fid), ""),
                "entity": entity_by_id.get(fid, ""), "period": period_by_id.get(fid, ""),
            } for fid in (g.get("expected_files") or [])],
            "confirmed_by": g.get("confirmed_by", ""), "confirmed_at": g.get("confirmed_at", ""),
        })
    d = tmp / "gold_pack"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "gold_manifest.json"
    p.write_text(json.dumps({
        "schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
        "gold_pack_id": "GOLD-A4A-SYNTHETIC", "exam_id": "EX-A4A-SYNTHETIC",
        "checklist": {"checklist_id": "CL-A4A", "sha256": "", "item_count": 8},
        "library": {"library_id": "SIM-LIB", "fingerprint": "", "material_count": 8},
        "confirmed_by": "合成测试（非人工批准）",
        "confirmed_at": "2026-10-28T20:00:00+08:00",
        "items": items,
    }, ensure_ascii=False, indent=2), "utf-8")
    return p


def _checklist_tsv(tmp: Path) -> Path:
    """把 ``raw_items.json`` 转成团队入口要的清单 TSV（编号<TAB>原文）。"""
    items = json.loads((FX / "raw_items.json").read_text("utf-8"))
    p = tmp / "清单.tsv"
    p.write_text("\n".join(f"{it['item_id']}\t{it['text']}" for it in items), "utf-8")
    return p


def _delivered_from_manifest(delivery: Path) -> list[dict]:
    """从 ``组包manifest.tsv`` 读**实际交付**清单（file_id / 路径 / 源副本 SHA256）。"""
    m = delivery / "组包manifest.tsv"
    if not m.is_file():
        return []
    out: list[dict] = []
    with m.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out.append({
                "file_id": (row.get("file_id") or "").strip(),
                "delivered_path": (row.get("交付路径") or row.get("副本路径") or "").strip(),
                "source_sha256": (row.get("源sha256") or "").strip(),
                "copy_sha256": (row.get("副本sha256") or "").strip(),
                "hash_match": (row.get("一致") or "").strip() in ("是", "True", "true", "1"),
                "obligation_id": (row.get("义务ID") or row.get("原子义务") or "").strip(),
            })
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = _SIM_TMP
    try:
        material = tmp / "material"
        shutil.copytree(MATERIAL, material)
        report = tmp / "report"
        delivery = tmp / "delivery"
        checklist = _checklist_tsv(tmp)

        # ── ⓪ 登记材料库 + 登记权威主体（**必须先于首次摄取**）
        rc = dm.main(["register", "--library", "SIM-LIB", "--root", str(material),
                      "--authorized-by", "合成测试", "--name", "A4a 合成库"])
        print(f"[0/5] 登记材料库：退出码 {rc}")
        for eid, name, rel, parent, root in (
                ("E01", "主体甲", "parent", "", True),
                ("E02", "主体乙", "subsidiary", "E01", False)):
            argv = ["entity", "--library", "SIM-LIB", "--id", eid, "--name", name,
                    "--relation", rel, "--source", "合成测试登记（非真实工商登记）"]
            if parent:
                argv += ["--parent", parent]
            if root:
                argv += ["--group-root"]
            rc = dm.main(argv)
            print(f"      登记主体 {name}（{rel}）：退出码 {rc}")

        # ── ① 真实团队入口：图书馆读取 → 考卷理解 → 检索 → 组包（审核＋复制原件）
        rc = tc.main([
            "run",
            "--library", "SIM-LIB",
            "--root", str(material),
            "--checklist", str(checklist),
            "--institution", "Institution_XX",
            "--by", "合成测试",
            "--package",
            "--approved-by", "合成测试",
            "--package-out", str(delivery),
            "--out", str(report),
            "--allow-real-material",
        ])
        print(f"[1/5] 组包（真实入口）：退出码 {rc}")
        results = sorted(report.glob("尽调结果-*.json"))
        if not results:
            print("没有产出 尽调结果-*.json")
            return 1
        payload = json.loads(results[0].read_text("utf-8"))
        bridge = payload.get("semantic_bridge") or {}

        # ── ② 机器答卷（考生侧；不含标准答案）——★ 走**真实 CLI**（与刘江真机同一条链）
        idx = _library_index("SIM-LIB", material)
        delivered = _delivered_from_manifest(delivery)
        rc = tc.main(["answer", "--bridge-json", str(results[0]),
                      "--exam-id", "EX-A4A-SYNTHETIC", "--out", str(tmp / "考场")])
        print(f"[2/5] 机器答卷（CLI）：退出码 {rc}")
        sheet_files = sorted((tmp / "考场").glob("机器答卷-*.json"))
        if not sheet_files:
            print("★ 机器答卷没产出")
            return 1
        sheet = json.loads(sheet_files[-1].read_text("utf-8"))
        (OUT / "机器答卷.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=2), "utf-8")
        print(f"      义务 {sheet['summary'].get('obligations')}｜"
              f"已理解 {sheet['summary'].get('understood')}｜"
              f"已作答 {sheet['summary'].get('answered')}｜"
              f"选中 {sheet['summary'].get('selected_files')} 件｜"
              f"交付 {sheet['summary'].get('delivered_files')} 件")

        # ── 标准答案的义务 id 映射：清单编号（R1…）⇒ 本次答卷的真实义务 id
        from cangjie_fos.services import dd_v1_requirement_service as rq
        obl_rows = rq.list_obligations("SIM-LIB")
        # ★ 清单条目号 → 义务原文 → 库内义务 id（原文唯一 ⇒ 映射确定）
        text_by_no = {it["item_id"]: it["text"]
                      for it in json.loads((FX / "raw_items.json").read_text("utf-8"))}
        obl_by_text = {str(r.get("obligation") or "").strip(): str(r.get("obligation_id") or "")
                       for r in obl_rows}
        bridge_by_src = {str(ob.get("source_obligation_id") or ""): ob
                         for ob in (bridge.get("obligations") or [])}
        # ★ 组包manifest 里的「义务ID」用的是**稳定 key**（``OBL-…``）⇒
        #   要经「库内义务行」换算回本次答卷的义务 id，否则「实际交付」挂不上。
        obl_id_by_key = {str(r.get("obligation_key") or ""): str(r.get("obligation_id") or "")
                         for r in obl_rows}
        bridge_by_key = {}
        for key, oid in obl_id_by_key.items():
            ob = bridge_by_src.get(oid)
            if ob is not None:
                bridge_by_key[key] = str(ob["obligation_id"])
        for d in delivered:
            d["obligation_id"] = bridge_by_key.get(d.get("obligation_id") or "",
                                                   d.get("obligation_id") or "")
        gold_items = []
        for g in json.loads((FX / "gold.json").read_text("utf-8")):
            item_no = str(g["obligation_id"]).split("-")[0]
            src = obl_by_text.get(str(text_by_no.get(item_no, "")).strip(), "")
            if not src:
                print(f"      ★ 跳过：清单条目 {item_no} 在本次运行里没有对应义务")
                continue
            ob = bridge_by_src.get(src)
            if ob is None:
                print(f"      ★ 跳过：义务 {src} 不在桥接产物里")
                continue
            gold_items.append({**g, "obligation_id": str(ob["obligation_id"])})
        print(f"      实际交付 {len(delivered)} 件；交付目录存在={delivery.exists()}")
        # ── ③ 隔离阅卷
        gold_p = _gold_manifest(tmp, gold_items)
        manifest = gold_svc.load_gold_manifest(gold_p)
        leak = ex.detect_gold_leak(sheet, idx)
        card = ex.grade_answer_sheet(sheet, manifest, library_index=idx,
                                     exam_id="EX-A4A-SYNTHETIC", min_obligations=1,
                                     leak_report=leak)
        (OUT / "成绩单.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), "utf-8")
        (OUT / "逐题评分明细.tsv").write_text(
            "义务ID\t期望材料\t机器选中\t命中\t漏选\t多交\t结局\t机器判定\n" + "\n".join(
                f"{r['obligation_id']}\t{'、'.join(r['expected_files']) or '—'}\t"
                f"{'、'.join(r['selected_files']) or '—'}\t{'、'.join(r['hit']) or '—'}\t"
                f"{'、'.join(r['missed']) or '—'}\t{'、'.join(r['extra']) or '—'}\t"
                f"{r['outcome']}\t{r['agent_verdict'] or '—'}"
                for r in card.get("rows") or []),
            "utf-8")
        sc = card.get("scores") or {}
        if card.get("status") == "NOT_SCORABLE":
            print(f"[3/5] 阅卷：**不可评分** ⇒ {'；'.join(card.get('blocked_by') or [])}")
            print(f"      泄漏检测：{json.dumps(leak, ensure_ascii=False)[:600]}")
        print(f"[3/5] 阅卷：status={card['status']} 总分={sc.get('total_score')} "
              f"召回={sc.get('material_recall')} 准确={sc.get('selection_precision')} "
              f"安全闸={(card.get('safety_gate') or {}).get('status')}")

        # ── ④ 第四组：旧版本对照（同一考场、同一标准答案）
        old_gold = [{"obligation_id": g["obligation_id"],
                     "expected_verdict": g["expected_verdict"],
                     "expected_files": g["expected_files"]}
                    for g in json.loads((FX / "gold.json").read_text("utf-8"))]
        old = sem.score_against_gold([], old_gold)
        old_card = {"status": old.get("status"), "scores": None,
                    "note": "旧口径只给 accuracy（无 0—100、无逐题明细、无安全闸分项）"}
        (OUT / "旧版本读数.json").write_text(json.dumps(old, ensure_ascii=False, indent=2), "utf-8")
        cmp = ex.compare_scorecards(old_card, card,
                                    old_label="旧版本 abc4627（accuracy 口径）",
                                    new_label="新版本（0—100 冻结口径）")
        (OUT / "版本对比.md").write_text(ex.compare_markdown(cmp), "utf-8")
        (OUT / "版本对比.json").write_text(json.dumps(cmp, ensure_ascii=False, indent=2), "utf-8")
        print(f"[4/5] 旧版本对照：旧口径 accuracy={(old.get('agent') or {}).get('accuracy')}；"
              f"可比基线={cmp['baseline_established']}")

        # ── ⑤ 考场预检
        contract = {
            "schema_version": "dd_v1_exam_contract.v1",
            "exam_id": "EX-A4A-SYNTHETIC", "name": "A4a 合成考场",
            "institution": "Institution_XX",
            "checklist": {"checklist_id": "CL-A4A", "library_id": "SIM-LIB", "sha256": "",
                          "item_count": 8},
            "library": {"library_id": "SIM-LIB", "material_root": str(material),
                        "fingerprint": "", "material_count": 8},
            "gold": {"gold_pack_id": "GOLD-A4A-SYNTHETIC", "manifest_path": str(gold_p),
                     "provided": True},
            "entity_scope": {"scope_mode": "SINGLE_ENTITY", "group_root_id": "",
                             "entity_ids": ["E01"],
                             "declared_by": "合成测试",
                             "declared_at": "2026-10-28T20:00:00+08:00"},
        }
        cpath = tmp / "contract.json"
        cpath.write_text(json.dumps(contract, ensure_ascii=False, indent=2), "utf-8")
        rc = tc.main(["preflight", "--contract", str(cpath), "--out", str(OUT)])
        print(f"[5/5] 考场预检：退出码 {rc}（0=具备正式评分条件；非 0=有阻塞，见报告）")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
