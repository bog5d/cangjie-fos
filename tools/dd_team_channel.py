#!/usr/bin/env python3
"""DD-V1 团队调用入口（WP7）——把一份尽调清单丢进来，跑出组包结果与缺口清单。

## 定位

交办件要求「最终必须让 Team Channel 中的团队成员能够实际调用该能力」，
且明确「FOS 核心引擎完成，**不代表** Team Channel 团队调用已经完成」。

WP0–WP5 造的是引擎；**WP7 造的是让人用得起来的那个入口**。
本脚本就是那个入口的最小可用形态：**一个命令 + 结构化输出**，不依赖前端、不依赖 LLM key。

## 它做什么（一次跑完 6 步 + 1 个附段）

    建库 → 扫描材料 → 抽取正文 → 建认知卡 → 拆原子义务 → 四维匹配 → 出报告

**附段（WP-A1 引入）**：语义层桥接。规则链算完缺口后，把同一批义务与材料
翻译成语义层能认的形状，取回**候选证据**（file_id + sha256 + locator）。
它是**附段**而不是第 7 步：**桥接不可用或被跳过时，上面 6 步的输出一字不变**。
桥接产物**只作建议**，不改写任何判定，也不参与交付包。

## 它不做什么（必须对使用者讲清）

- **不会向任何机构发送材料**。产出的只是本机报告与可审核的组包目录。
- **默认 dry-run**：不复制任何原件。复制必须经显式 `--package` 且必须有人工批准人。
- **不猜**：材料类型、主体、期间、附件、敏感等级拿不准就标 UNKNOWN，绝不编造。
- **缺权威名单就判 UNCERTAIN**：不会拿目录名当集团成员。

## 给非开发角色用

```bash
cd backend
python ../tools/dd_team_channel.py run \\
    --library 尽调材料库 \\
    --root /path/to/材料库 \\
    --checklist 机构清单.tsv \\
    --institution 某投资机构
```

输出：终端简明报告 + `报告.md` + `结果.json`（机读，供后续系统消费）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BACKEND = _REPO / "backend"
if str(_BACKEND / "src") not in sys.path:
    sys.path.insert(0, str(_BACKEND / "src"))

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def _hr(title: str) -> None:
    print(f"\n{'─' * 66}\n{title}\n{'─' * 66}")


def _policy_note() -> None:
    from cangjie_fos.services import dd_v1_policy_service as P
    st = P.policy_status()
    print("披露策略状态：")
    print(f"  策略版本   : {st['policy_version']}")
    print(f"  是否生效   : {'是' if st['loaded'] else '否'}")
    print(f"  可外发级别 : {st['externally_sendable_levels'] or '（无）'}")
    print(f"  当前效果   : {st['effective']}")
    if not st["loaded"]:
        print(f"  说明       : {st['load_error']}")


def _read_checklist(path: str) -> list[dict]:
    """读清单。每行「编号<TAB>原文」；无编号的行自动编号（不丢内容）。"""
    rows: list[dict] = []
    text = Path(path).read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            no, raw = line.split("\t", 1)
        else:
            no, raw = f"L{i}", line
        rows.append({"item_no": no.strip(), "raw_text": raw.strip()})
    return rows


def cmd_run(a) -> int:
    from cangjie_fos.services import (dd_v1_card_service as cs,
                                      dd_v1_match_service as ms,
                                      dd_v1_manifest_service as mf,
                                      dd_v1_parser_service as ps,
                                      dd_v1_requirement_service as rq)

    t0 = time.time()
    data_plane = os.environ.setdefault("CANGJIE_DD_V1_DATA_DIR",
                                        str(_BACKEND / "data" / "dd_v1"))

    print("=" * 66)
    print("  投资尽调自动组包 V1 · 团队调用入口")
    print("=" * 66)
    print("本工具只在**本机**处理材料，产出报告与可审核的组包目录。")
    print("**不会向任何机构发送任何材料。**")
    _policy_note()
    print(f"\n数据存放（受控，不进版本库）：{data_plane}")

    lib = a.library
    root = Path(a.root)
    if not root.is_dir():
        print(f"\n[错误] 材料库路径不存在：{root}", file=sys.stderr)
        return EXIT_USAGE
    if not Path(a.checklist).is_file():
        print(f"\n[错误] 清单文件不存在：{a.checklist}", file=sys.stderr)
        return EXIT_USAGE

    # ── 1 建库 ────────────────────────────────────────────────────────
    _hr("第 1 步 / 共 6 步：登记材料库")
    mf.register_library(lib, str(root), authorized_by=a.by,
                        display_name=a.name or "", db_path=None)
    print(f"  ✓ 材料库 {lib} 已登记（授权人：{a.by}）")
    print("  说明：只扫描**经登记授权**的目录；未登记的目录一律拒绝。")

    # ── 2 扫描 ────────────────────────────────────────────────────────
    _hr("第 2 步 / 共 6 步：扫描材料")
    pending = mf.find_resumable_run(lib)
    run_id = pending["run_id"] if pending else None
    if run_id:
        print(f"  · 发现上次中断的运行 {run_id[:8]}，自动续跑")
    scan = mf.build_manifest(lib, mode="incremental", resume_run_id=run_id)
    print(f"  ✓ 共 {scan['total']} 份｜新增 {scan['added']}｜更新 {scan['updated']}"
          f"｜未变 {scan['unchanged']}｜失败 {scan['failed']}")
    print("  说明：同名文件按**相对路径**区分，不同主体/机构下的同名材料不会被合并删除。")

    # ── 3 抽取 ────────────────────────────────────────────────────────
    _hr("第 3 步 / 共 6 步：读取正文")
    parsed = ps.parse_pending_batch(lib, limit=a.parse_limit)
    bs = parsed["by_status"]
    print(f"  ✓ 处理 {parsed['processed']} 份｜成功 {bs.get('ok', 0)}"
          f"｜截断 {bs.get('partial', 0)}｜失败 {bs.get('failed', 0)}")
    if parsed["failure_count"]:
        print(f"  · 有 {parsed['failure_count']} 份读不出正文，"
              f"它们仍会进入匹配，但**不会**被自动纳入对外交付。")
    if not parsed["docling_available"]:
        print("  · 未安装 Docling（可选增强），已降级用内置解析器，功能不受影响。")

    # ── 4 认知卡 ──────────────────────────────────────────────────────
    _hr("第 4 步 / 共 6 步：建立材料画像")
    cards = cs.build_cards_for_library(lib)
    cov = cs.card_coverage(lib)
    print(f"  ✓ 建立 {cards['built']} 张画像（其中 {cards['with_cached_text']} 份有正文）")
    print(f"  · 出处分布：确证 {cov['by_provenance']['FACT']}｜"
          f"推断 {cov['by_provenance']['INFERRED']}｜"
          f"未知 {cov['by_provenance']['UNKNOWN']}")
    print("  说明：拿不准的字段一律标「未知」并写明原因，**不会**替你猜。")

    # ── 5 拆清单 ──────────────────────────────────────────────────────
    _hr("第 5 步 / 共 6 步：拆解机构清单")
    rows = _read_checklist(a.checklist)
    ing = rq.ingest_checklist(lib, rows, anchor_year=a.anchor_year,
                              institution=a.institution)
    print(f"  ✓ 录入 {ing['items']} 条原文，拆出 {ing['obligations']} 条待办要求")
    print(f"  · 原文零丢失校验：{'通过' if ing['original_text_roundtrip_ok'] else '**未通过**'}")
    if ing["dropped"]:
        print(f"  · 有 {len(ing['dropped'])} 条原文为空被拒收（不会凭空生成要求）")
    q = rq.obligation_quality(lib)
    print(f"  · 读懂程度：主体范围已识别 {q['by_dimension']['entity_basis']['FACT']} 条，"
          f"期间已识别 {q['by_dimension']['period_basis']['FACT']} 条")
    if q["entities_registered"] == 0:
        print("  ⚠️ 尚未登记**权威主体名单**（集团成员）。"
              "凡要求「集团及下属公司」的条目将判「无法判定」，不会拿目录名凑数。")
        print("     需要时可执行："
              "  python tools/dd_v1_manifest.py entity --library <库> "
              "--id <编号> --name <主体名> --relation subsidiary --source <权威依据>")

    # ── 6 匹配 ────────────────────────────────────────────────────────
    _hr("第 6 步 / 共 6 步：逐条匹配并算完整性")
    res = ms.match_library(lib, candidate_cap=a.cap)
    print(f"  ✓ {res['obligations']} 条要求判定完成（候选上限 {res['candidate_cap']}，可调）")
    _print_verdicts(res["by_verdict"])

    # ── 附：语义层桥接（**只作建议**，不改判定）────────────────────────
    # 桥接是**附段**：失败或跳过时，上面 6 步的输出一字不变。
    bridge = _run_bridge(lib, root, a)
    if bridge.get("ok"):
        b = bridge["result"]
        c = b["counts"]
        print(f"  ✓ 语义层桥接：{c['obligations_with_evidence']}/{c['obligations_out']} "
              f"条义务取到候选证据｜共 {c['evidence_total']} 份候选材料"
              f"｜模式 {b['mode']}｜外部模型调用 {b['external_model_calls']}")
        print("  说明：**仅供参考，不改判定**；交付前仍需人工逐条核对并批准。")
        for w in b.get("warnings") or []:
            print(f"  ⚠️ {w}")
    elif bridge.get("skipped"):
        print("  · 已按 --no-bridge 跳过语义层桥接（本次输出与未接桥接时完全一致）")
    else:
        print(f"  · 语义层桥接未运行（{bridge.get('error')}）；"
              f"本次输出与未接桥接时完全一致")

    # ── 报告 ──────────────────────────────────────────────────────────
    _hr("输出")
    outdir = Path(a.out) if a.out else Path(data_plane) / "团队报告"
    outdir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    md = outdir / f"尽调报告-{lib}-{ts}.md"
    js = outdir / f"尽调结果-{lib}-{ts}.json"
    _write_reports(md, js, lib, a, res, q, cov, parsed, scan, bridge)

    print(f"  人看的报告：{md}")
    print(f"  机读结果  ：{js}")
    print()
    print("  ⚠️ 以上只是**建议**。交付前仍需人工逐条核对并明确批准；")
    print("     系统不会自动向机构发送任何材料。")
    print(f"\n用时 {time.time() - t0:.1f}s")
    return EXIT_OK


def _run_bridge(lib, root: Path, a) -> dict:
    """跑一次语义层桥接。**任何失败都不得影响入口 A 的原有输出。**

    返回：
    - ``{"ok": True, "result": <桥接产物>}``
    - ``{"ok": False, "skipped": True}``（``--no-bridge``）
    - ``{"ok": False, "error": "..."}``（桥接不可用；入口 A 输出不受影响）
    """
    if getattr(a, "no_bridge", False):
        return {"ok": False, "skipped": True}
    try:
        from cangjie_fos.services import dd_v1_bridge_service as br
        res = br.bridge_library(
            lib, material_root=root, db_path=None,
            allow_real_material=bool(getattr(a, "allow_real_material", False)))
        return {"ok": True, "result": res}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _bridge_json(bridge) -> dict:
    """桥接产物的机读形态。**只作建议**：不参与判定、不进交付包、不改结论。"""
    if not bridge:
        return {"ran": False, "reason": "NO_BRIDGE"}
    if bridge.get("skipped"):
        return {"ran": False, "reason": "SKIPPED_BY_FLAG"}
    if not bridge.get("ok"):
        return {"ran": False, "reason": "BRIDGE_UNAVAILABLE", "error": bridge.get("error", "")}
    b = bridge["result"]
    return {
        "ran": True,
        "mode": b["mode"],
        "degrade_reason": b["degrade_reason"],
        "external_model_calls": b["external_model_calls"],
        "advisory_only": True,
        "review_required": True,
        "changes_hard_verdict": False,
        "sent_to_institution": False,
        "warnings": b.get("warnings") or [],
        "counts": b["counts"],
        "obligations": [
            {
                "obligation_id": o["obligation_id"],
                "source_obligation_id": o["source_obligation_id"],
                "entity": o["entity"],
                "entity_basis": o["entity_basis"],
                "subject_verified": o["subject_verified"],
                "doc_type": o["doc_type"],
                "period": o["period"],
                "evidence_count": o["evidence_count"],
                "rule_hint": o["rule_hint"],
                "candidates": [
                    {"file_id": e["file_id"], "sha256": e["sha256"],
                     "locator": e["locator"], "relative_path": e["relative_path"],
                     "entity": e["entity"], "subject_verified": e["subject_verified"],
                     "version_status": e["version_status"], "part": e["part"]}
                    for e in o["evidence"]
                ],
            }
            for o in b["obligations"]
        ],
    }


def _print_verdicts(tally: dict) -> None:
    from cangjie_fos.services import dd_v1_match_service as ms  # noqa: PLC0415
    names = {
        ms.V_MATCHED: "已齐全", ms.V_PARTIAL: "不完整", ms.V_MISSING: "缺材料",
        ms.V_STALE: "版本过期", ms.V_CONFLICT: "内容冲突",
        ms.V_UNCERTAIN: "无法判定", ms.V_RESTRICTED: "受限不可外发",
    }
    print("  逐条结果：")
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"    {names.get(k, k):<10} {v} 条")


def _write_reports(md: Path, js: Path, lib, a, res, q, cov, parsed, scan, bridge=None) -> None:
    from cangjie_fos.services import (dd_v1_match_service as ms,
                                      dd_v1_policy_service as P,
                                      dd_v1_requirement_service as rq)
    obl = rq.list_obligations(lib)
    pol = P.policy_status()

    lines = [
        "# 尽调材料匹配报告",
        "",
        f"- 材料库：`{lib}`",
        f"- 机构：{a.institution or '（未填）'}",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 材料总数：{scan['total']}｜可读正文：{parsed['by_status'].get('ok', 0)}",
        f"- 披露策略：{'已生效 ' + pol['policy_version'] if pol['loaded'] else '**未生效，全部按最严处理**'}",
        "",
        "> 本报告是**机器建议**，不是结论。交付前必须人工逐条核对并批准。",
        "> 系统不会自动向任何机构发送材料。",
        "",
        "## 逐条结果",
        "",
    ]
    for o in obl:
        st = ms.get_status(o["obligation_id"]) or {}
        v = st.get("verdict", "未匹配")
        lines.append(f"### {o['obligation']}")
        lines.append("")
        lines.append(f"- 判定：**{v}**")
        if st.get("missing_detail"):
            lines.append(f"- 缺口：{st['missing_detail']}")
        lines.append(f"- 机构编号：{o['item_uid'][:8]}"
                     f"｜主体范围：{o['entity_scope'] or '（未识别）'}"
                     f"｜期间：{o['period_from'] or '?'}-{o['period_to'] or '?'}"
                     f"｜材料类型：{o['doc_type'] or '（未识别）'}")
        cands = ms.list_matches(o["obligation_id"])
        if cands:
            lines.append("- 候选材料：")
            for c in cands[:5]:
                lines.append(f"    - {c.get('card_rel_path') or c['file_id']}"
                             f"（匹配度 {c['score']}"
                             f"，{'可交付' if c['deliverable'] else '受限/不可外发'}）")
        else:
            lines.append("- 候选材料：（无）")
        lines.append("")

    # ── 语义层桥接（附段，**独立小节**，与规则判定分开）────────────────
    b = (bridge or {}).get("result") if (bridge or {}).get("ok") else None
    if b:
        lines2 = [
            "",
            "## 语义层建议（仅供参考，不改判定）",
            "",
            "> 本节是**语义层给出的候选提示**，与上面的规则判定**分开**。"
            "它不参与判定、不进交付包、不改变任何一条结论；"
            "每条建议都必须人工核对后才能用。",
            "",
            f"- 模式：`{b['mode']}`｜外部模型调用：{b['external_model_calls']}"
            f"｜义务 {b['counts']['obligations_with_evidence']}/"
            f"{b['counts']['obligations_out']} 条取到候选证据",
            f"- 主体口径：{b['counts']['entity_basis']}",
            "",
        ]
        for w in b.get("warnings") or []:
            lines2.append(f"> ⚠️ {w}")
            lines2.append("")
        for ob in b["obligations"]:
            if not ob["evidence_count"]:
                continue
            lines2.append(f"### {ob['text']}")
            lines2.append("")
            lines2.append(f"- 材料类型：{ob['doc_type'] or '（未识别）'}"
                          f"｜期间：{ob['period']}"
                          f"｜主体：{ob['entity'] or '（无线索）'}"
                          f"（{ob['entity_basis']}"
                          f"{'，**未经权威核验**' if not ob['subject_verified'] else ''}）")
            lines2.append(f"- 候选证据 {ob['evidence_count']} 份｜规则提示："
                          f"{ob['rule_hint'].get('verdict', '—')}")
            for e in ob["evidence"][:5]:
                lines2.append(f"    - {e['relative_path']}"
                              f"（file_id `{e['file_id'][:8]}`"
                              f"，sha256 `{e['sha256'][:12]}…`"
                              f"，定位 `{e['locator']}`"
                              f"，版本 {e['version_status']}）")
            lines2.append("")
        lines += lines2

    md.write_text("\n".join(lines), encoding="utf-8")

    js.write_text(json.dumps({
        "library": lib, "institution": a.institution,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "human_approval_required": True,
        "sent_to_institution": False,
        "disclosure_policy": pol,
        "summary": {
            "materials": scan["total"],
            "parse": parsed["by_status"],
            "obligations": res["obligations"],
            "by_verdict": res["by_verdict"],
            "candidate_cap": res["candidate_cap"],
        },
        "understanding_quality": q["by_dimension"],
        "card_provenance": cov["by_provenance"],
        "semantic_bridge": _bridge_json(bridge),
        "obligations": [
            {"obligation": o["obligation"],
             "verdict": (ms.get_status(o["obligation_id"]) or {}).get("verdict", ""),
             "missing": (ms.get_status(o["obligation_id"]) or {}).get("missing_detail", ""),
             "candidates": [c.get("card_rel_path") for c in ms.list_matches(o["obligation_id"])]}
            for o in obl
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dd_team_channel",
        description="投资尽调自动组包 V1 · 团队调用入口（WP7）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)

    r = sp.add_parser("run", help="跑一次完整流程：清单进来 → 匹配结果与缺口清单出去")
    r.add_argument("--library", required=True, help="材料库标识（自己起个名字，如 泽天材料库）")
    r.add_argument("--root", required=True, help="材料库根目录（本机路径）")
    r.add_argument("--checklist", required=True, help="机构清单文件（每行：编号<TAB>原文）")
    r.add_argument("--institution", default="", help="机构名称")
    r.add_argument("--name", default="", help="材料库显示名")
    r.add_argument("--by", default="", help="授权人（默认取当前用户名）")
    r.add_argument("--anchor-year", type=int, default=None,
                   help="「近三年」这类相对年份的锚定年；不给则不擅自假定")
    r.add_argument("--cap", type=int, default=20, help="每条要求的候选材料上限（默认 20）")
    r.add_argument("--parse-limit", type=int, default=2000, help="本次最多抽取多少份正文")
    r.add_argument("--out", default=None, help="报告输出目录")
    r.add_argument("--no-bridge", action="store_true",
                   help="跳过语义层桥接（本次输出与未接桥接时完全一致）")
    r.add_argument("--allow-real-material", action="store_true",
                   help="材料库不是仓库内合成 fixture 时必须给（=真实材料，仅限本机）")
    r.set_defaults(func=cmd_run)

    st = sp.add_parser("policy", help="查看披露策略是否生效")
    st.set_defaults(func=lambda a: (_print_policy(), EXIT_OK)[1])
    return p


def _print_policy() -> None:
    _policy_note()


def main() -> int:
    a = build_parser().parse_args()
    if not getattr(a, "by", ""):
        a.by = os.environ.get("USER") or os.environ.get("USERNAME") or "未署名"
    try:
        return a.func(a)
    except SystemExit:
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001
        print(f"\n[错误] {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
