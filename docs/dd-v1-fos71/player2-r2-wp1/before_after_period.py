#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复前后同需求结果对照（全合成；同一输入集、同一口径）。

用法：python3 before_after_period.py <代码树根目录>     # 打印「需求项 → 状态」
      同一份脚本分别指向**基座树**与**改动树**各跑一次 ⇒ 两份输出逐行对照。

口径说明：
  * 输入集：8 条合成需求（覆盖四种期间语义 × 四种材料情形）；
  * 材料：现场合成（tmp 目录），主体两类、年度 2021/2022/2024、执照 CURRENT；
  * 读数：``candidate_status``（候选侧四态）＋ ``rule_hint`` 判定（规则提示）
    ＋ 期间维度结论（改动侧才有 ``period_status``）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT / "backend" / "src"))

from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem  # noqa: E402

JIA = "合成法人甲"
YI = "合成法人乙"

MATERIALS = {
    "甲/审计报告/审计报告2024.txt": "审计报告\n本报告为2024年度财务审计结论。\n",
    "甲/审计报告/审计报告2022.txt": "审计报告\n本报告为2022年度财务审计结论。\n",
    "甲/审计报告/审计报告2021.txt": "审计报告\n本报告为2021年度财务审计结论。\n",
    "甲/营业执照/营业执照.txt": "营业执照\n合成样例。\n",
    "乙/审计报告/审计报告2024.txt": "审计报告\n本报告为2024年度财务审计结论。\n",
    "甲/审计报告/审计报告无年度.txt": "审计报告\n合成样例（无年度标注）。\n",
}

ITEMS = [
    ("Q1", JIA, "请提供2024年度审计报告"),            # 明确年度
    ("Q2", JIA, "请提供近三年的审计报告"),            # 相对期间（可验证锚点：材料自身年度）
    ("Q3", JIA, "请提供营业执照"),                    # 当前有效
    ("Q4", JIA, "请提供审计报告"),                    # 期间未知
    ("Q5", JIA, "请提供2022年度审计报告"),            # 明确年度（库里只有 2021/2024 审计报告）
    ("Q6", JIA, "请提供2021年度审计报告"),            # 明确年度（库里有 2021）
    ("Q7", JIA, "请提供最新审计报告"),                # 相对期间（最新口径）
    ("Q8", JIA, "请提供2024年度审计报告（报告期截至2024-06-30）"),  # 原文自带截止日期声明
    # ★ C-1 回归行：相对期间 + 四位年份（修复前被单年 EXPLICIT 吞掉 ⇒ 自信地紧）
    ("Q9", JIA, "请提供近三年的审计报告（报告期截至2024-06-30）"),
]


def build() -> tuple[Path, list[dict]]:
    tmp = Path(tempfile.mkdtemp(prefix="period_ba_"))
    root = tmp / "material"
    meta = []
    for i, (rel, body) in enumerate(sorted(MATERIALS.items())):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        name = Path(rel).name
        year = "".join(ch for ch in name if ch.isdigit())[:4]
        is_lic = "营业执照" in name
        meta.append({
            "file_id": f"F{i + 1:05d}", "relative_path": rel,
            "entity": YI if rel.startswith("乙/") else JIA,
            "period": "CURRENT" if is_lic else (year or ""),
            "doc_type": "license" if is_lic else "audit_report",
            "part": "正文", "version_status": "EFFECTIVE",
        })
    return root, meta


def main() -> int:
    root, meta = build()
    rows = []
    for item_id, entity, text in ITEMS:
        obs, _flags = sem.split_item({"item_id": item_id, "entity": entity, "text": text})
        if not obs:
            rows.append({"item_id": item_id, "text": text, "note": "NO_OBLIGATION"})
            continue
        ob = obs[0]
        d = sem.retrieve_minimal_evidence_detailed(root, meta, ob)
        hint = sem.rule_hint(ob, d["evidence"], d["no_candidate_reason"])
        row = {
            "item_id": item_id, "text": text,
            "period_string": ob.get("period"),
            "candidate_status": d["candidate_status"],
            "no_candidate_reason": d["no_candidate_reason"],
            "rule_verdict": hint.get("verdict"),
            "rule_files": len(hint.get("files") or []),
            "evidence_count": len(d["evidence"]),
            "rejected_by_period": d["diagnostics"].get("rejected_by_period"),
        }
        if "period_status" in d["diagnostics"]:
            row["period_status"] = d["diagnostics"]["period_status"]
        rows.append(row)
    print(json.dumps({"tree": str(ROOT), "rows": rows}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
