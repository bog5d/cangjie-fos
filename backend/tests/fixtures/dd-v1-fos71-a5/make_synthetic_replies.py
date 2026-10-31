#!/usr/bin/env python3
"""合成盲测的**预置回贴生成器**（A4a · G-A4a-5）。

为什么需要生成器：回贴必须携带 ``source_snapshot_id`` / ``candidate_files[].sha256`` /
``candidate_files[].locator``，这些值取决于**盲化 + 冻结之后**的那一份快照 ⇒ 纯手写的静态
文件无法凭空写死。本脚本用与运行器**完全同源**的服务把链路先跑一遍（盲化 → 冻结 → 拆分 →
取证据），再把回贴落盘 ⇒ 回贴与材料永远自洽（材料一改，重新生成本目录即可）。

★ 本脚本**不调用任何模型**：回贴是合成的（``model_id_or_unknown=UNKNOWN``、
  ``independent_examinee_answer=false``、``synthetic_replay=true``）。
★ 它的作用只是让「盲化 → 冻结 → 拆分 → 跑 → 评分」这条链路能**零成本**跑通（**链路自检**），
  **不代表任何模型能力被验证过**，也**不是**「盲考通过」。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from cangjie_fos.services import dd_v1_agent_result_service as ar  # noqa: E402
from cangjie_fos.services import dd_v1_blind_service as bl  # noqa: E402
from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem  # noqa: E402
from cangjie_fos.services import dd_v1_snapshot_freeze_service as fz  # noqa: E402

FIXTURE = Path(__file__).resolve().parent
MATERIAL = FIXTURE / "material"
#: 泄漏词表（题号 / 机构名 / 项目名）——**必须**与说明书里的命令一致，否则 snapshot_id 对不上
LEAK_WORDS = ["Q-2024-07", "案例甲机构", "案例乙机构", "星海项目"]

#: 每条义务的**合成回贴**设计：故意覆盖 TP / FP / FN / 错主体 / 错年度 / 自信错配 + 1 例 UNCERTAIN
PLAN = {
    "R1": {"verdict": "MATCH", "files": ["F00001", "F00002"], "conf": 0.9},
    "R2": {"verdict": "MATCH", "files": ["F00001", "F00002"], "conf": 0.5},
    "R3": {"verdict": "OUTDATED", "files": ["F00004"], "conf": 0.9},
    "R4": {"verdict": "OUTDATED", "files": ["F00004"], "conf": 0.5},
    "R5": {"verdict": "MISSING", "files": [], "conf": 0.4,
           "abstain": "合成样本：在快照里找不到与该义务同主体同期间的件"},
    "R6": {"verdict": "UNCERTAIN", "files": [], "conf": "UNCERTAIN",
           "abstain": "合成样本：证据不足以判定该义务是否满足"},
    "R7": {"verdict": "MATCH", "files": ["F00001"], "conf": 0.7},
    "R8": {"verdict": "MATCH", "files": ["F00001", "F00003"], "conf": 0.5},
}
MATCH_REASON = "合成样本：证据正文的主体与期间同义务一致，且为现行有效版本"


def build(work: Path) -> dict:
    """盲化 → 冻结 → 拆分 → 取证据 ⇒ 回贴（每条义务一条 result）。"""
    meta = json.loads((MATERIAL / "meta.json").read_text("utf-8"))
    blind_dir = work / "blind"
    res = bl.blind_material(MATERIAL, meta, leak_words=LEAK_WORDS, blind_dir=blind_dir,
                            mapping_out=work / "blind-mapping.json",
                            meta_file=MATERIAL / "meta.json")
    blind_meta = res["meta"]
    frozen = work / "frozen"
    fz.freeze_snapshot(blind_dir, blind_meta, frozen)
    snap = ar.load_snapshot(frozen, blind_meta)
    snapshot_id = ar.snapshot_id(snap)
    table = bl.build_substitution_table(LEAK_WORDS)
    items = json.loads((FIXTURE / "raw_items.json").read_text("utf-8"))
    blinded_items = [
        {**it, "entity": bl.blind_text(str(it.get("entity") or ""), table),
         "text": bl.blind_text(str(it.get("text") or ""), table)}
        for it in items
    ]
    obligations, flags = sem.split_items(blinded_items)
    if flags:
        raise SystemExit(f"合成条目拆不出义务：{flags}")
    results = []
    for ob in obligations:
        plan = PLAN[ob["item_id"]]
        evidence = sem.retrieve_minimal_evidence(frozen, blind_meta, ob)
        candidates = []
        for fid in plan["files"]:
            hit = next((e for e in evidence if e["file_id"] == fid), None)
            if hit is None:
                raise SystemExit(f"回贴引用了证据外的文件：{ob['obligation_id']} / {fid}")
            candidates.append({
                "file_id": hit["file_id"], "relative_path": hit["relative_path"],
                "sha256": hit["sha256"], "locator": hit["locator"],
                "entity": hit["entity"], "period": hit["period"],
                "match_reason": MATCH_REASON,
            })
        results.append({
            "item_id": ob["item_id"],
            "obligation_id": ob["obligation_id"],
            "agent_id": "synthetic-replay",
            "provider": "SYNTHETIC",
            "model_id_or_unknown": "UNKNOWN",
            "prompt_version": sem.SEMANTIC_PROMPT_VERSION,
            "source_snapshot_id": snapshot_id,
            "candidate_files": candidates,
            "proposed_verdict": plan["verdict"],
            "confidence_or_uncertain": plan["conf"],
            "abstain_reason": plan.get("abstain", ""),
            "warnings": [],
            "elapsed": 0,
            "token_usage_or_UNKNOWN": "UNKNOWN",
        })
    return {"snapshot_id": snapshot_id, "results": results}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", default=None, help="准备目录（默认临时目录；产物不落仓）")
    ap.add_argument("--replies-out", default=str(FIXTURE / "replies"), help="预置回贴落盘目录")
    args = ap.parse_args(argv)
    work = Path(args.work).resolve() if args.work else Path(tempfile.mkdtemp(prefix="a4a-prep-"))
    work.mkdir(parents=True, exist_ok=True)
    built = build(work)
    out = Path(args.replies_out)
    out.mkdir(parents=True, exist_ok=True)
    by_item: dict[str, list[dict]] = {}
    for r in built["results"]:
        by_item.setdefault(r["item_id"], []).append(r)
    for item_id, rows in sorted(by_item.items()):
        (out / f"run-{item_id}.json").write_text(
            json.dumps({"results": rows}, ensure_ascii=False, indent=1), "utf-8")
        (out / f"run-{item_id}.provenance.json").write_text(json.dumps({
            "reply_source": "SYNTHETIC_REPLAY",
            "declared_by": "司仓合成盲测自检",
            "model_id_or_unknown": "UNKNOWN",
            "independent_examinee_answer": False,
            "synthetic_replay": True,
        }, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"snapshot_id": built["snapshot_id"], "replies": len(by_item),
                      "replies_out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
