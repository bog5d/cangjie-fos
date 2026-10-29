#!/usr/bin/env python3
"""DD-V1 团队调用入口（WP7）——把一份尽调清单丢进来，跑出组包结果与缺口清单。

## 定位

交办件要求「最终必须让 Team Channel 中的团队成员能够实际调用该能力」，
且明确「FOS 核心引擎完成，**不代表** Team Channel 团队调用已经完成」。

WP0–WP5 造的是引擎；**WP7 造的是让人用得起来的那个入口**。
本脚本就是那个入口的最小可用形态：**一个命令 + 结构化输出**，不依赖前端、不依赖 LLM key。

## 它做什么（一次跑完 7 步 + 1 个附段）

    建库 → 扫描材料 → 抽取正文 → 建认知卡 → 拆原子义务 → 四维匹配
    → **生成审核包**（只读、零复制）→ 出报告

**第 7 步（G-A3-6）**：接 `dd_v1_package_service.build_review_pack`，
产出**可人工审核的审核包**（核对表 / 缺口与待确认清单 / 证据与完整性说明 /
交付清单与 hash 核验），落在**数据面** `<data_dir>/reviews/<review_id>/`。
它**只读材料、零复制**；**组包不可用时前 6 步的输出一字不变**。

**交付原件（`--package`）**：显式给出 `--package` 且**给出人工批准人**
`--approved-by` 时才走复制路径；**未给出批准人 ⇒ 拒绝，且复制零个原件**。
没有自动批准开关，也没有默认批准人。

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

# gm_fix_a3_g6_g9_entry_wiring: APPLIED

# gm_fix_a3_g7_snapshot_id: APPLIED

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
    if ing.get("skipped_duplicates"):
        print(f"  · 幂等：跳过 {ing['skipped_duplicates']} 条重复清单条目"
              f"（清单指纹 {ing.get('checklist_fingerprint','')}）——重复摄取不产生重复义务")
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

    # ── 5b 考场契约声明的主体范围 → 落到**未指名主体**的义务上 ──────────
    # ★ 这一步**必须**在「摄取清单」之后、「匹配」之前：
    #   义务先存在，scope 才落得上；scope 落完，匹配才解析得到主体。
    # ★ 契约没声明 ⇒ **一条都不改**（保留「不可判定」，不擅自放行）。
    # ★ 这条接线是 `#108` 实测「91 条义务全 UNCERTAIN、0 交付」的**补救入口**：
    #   没接线时，交接文档让业务方「在契约里声明主体范围」是**空话**。
    _contract_scope_applied = None
    _contract_path = str(getattr(a, "contract", "") or "").strip()
    if _contract_path:
        try:
            from cangjie_fos.services import dd_v1_entity_scope_service as esc
            _c = json.loads(Path(_contract_path).read_text(encoding="utf-8"))
            _contract_scope_applied = esc.apply_contract_scope(
                lib, _c.get("entity_scope") or {})
            _ap = _contract_scope_applied
            if _ap.get("replaced"):
                print(f"  ✓ 已按考场契约声明的主体范围（{_ap.get('scope_keyword')}）"
                      f"落到 {_ap.get('updated')} 条未指名主体的义务，"
                      f"并**替换**了 {_ap.get('replaced')} 条上一场契约留下的范围"
                      f"（{', '.join(_ap.get('stale_scopes') or [])[:120]}）")
            elif _ap.get("updated"):
                print(f"  ✓ 已按考场契约声明的主体范围（{_ap.get('scope_keyword')}）"
                      f"落到 {_ap.get('updated')} 条未指名主体的义务"
                      f"（{_ap.get('skipped_named')} 条已指名的未动）")
            else:
                # ★ 「落到 0 条」**不得**打 ✓（独立 Reviewer 增量复核）：
                #   库里的义务可能已经带着**上一场**契约的范围 ⇒ 看着像生效、实际没生效。
                _stale = _ap.get("stale_scopes") or []
                _same = int(_ap.get("skipped_named") or 0)
                if _stale:
                    print(f"  ⚠️ **本次声明未生效**：库里 {len(_stale)} 条义务仍带着"
                          f"上一场契约的范围（{', '.join(_stale)[:120]}）"
                          f"，与本次声明（{_ap.get('scope_keyword')}）不同")
                    print(f"    ⇒ 那些义务**不会**用本次声明的主体范围判定；"
                          f"如需换范围，请换一个库（或清掉那 {len(_stale)} 条的旧声明）")
                elif _same:
                    # 库里已有的范围**与本次声明一致** ⇒ 声明早已生效过（本次无需改写）
                    print(f"  ✓ 考场契约声明的主体范围（{_ap.get('scope_keyword')}）"
                          f"**已在库里生效**（{_same} 条义务带着该范围，本次无需改写）")
                else:
                    print(f"  · 考场契约未声明主体范围（或声明的主体在权威名单里不存在）"
                          f"⇒ 未指名主体的义务仍判「无法判定」（不擅自放行）")
                print(f"    {_ap.get('note')}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️ 考场契约里的主体范围没生效：{type(exc).__name__}: {exc}")

    # ── 6 匹配 ────────────────────────────────────────────────────────
    _hr("第 6 步 / 共 6 步：逐条匹配并算完整性")
    # ★ 人工确认的主体映射表（可选）—— 主体识别里证据强度最高的一档
    _confirmed_map = {}
    _cm_path = str(getattr(a, "confirmed_entity_map", "") or "").strip()
    if _cm_path:
        try:
            _cm = json.loads(Path(_cm_path).read_text(encoding="utf-8"))
            _confirmed_map = _cm.get("confirmed_map") if isinstance(_cm, dict) and "confirmed_map" in _cm else _cm
            if not isinstance(_confirmed_map, dict):
                _confirmed_map = {}
            print(f"  · 人工确认主体映射：{len(_confirmed_map)} 条已加载（{_cm_path}）")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️ 人工确认主体映射没加载：{type(exc).__name__}: {exc}")
    res = ms.match_library(lib, candidate_cap=a.cap,
                           expand_candidates=not bool(getattr(a, "no_expand_candidates", False)),
                           confirmed_map=_confirmed_map or None)
    print(f"  ✓ {res['obligations']} 条要求判定完成（候选上限 {res['candidate_cap']}，可调）")
    # ★ WP3-d：**候选上限必须显式报数**（禁静默漏检）——
    #   旧实现只印「候选上限 20，可调」⇒ 用户不知道实际查了多少、
    #   还有多少**没看** ⇒ 触顶时那段结论被当成全量结论。
    print(f"  · 实际考察候选 {res.get('candidates_seen', 0)} 份"
          f"｜触顶义务 {res.get('capped_obligations', 0)} 条"
          f"｜被上限挡掉 {res.get('truncated_candidate_count', 0)} 份")
    if res.get("capped_obligations"):
        print(f"  ⚠️ {res['candidate_cap_note']}")
    # ★ 候选分批扩展的读数（**必须外显**：扩了几条／看了多少／还剩多少没看／为什么停）
    _exp = res.get("candidate_expansion") or {}
    if _exp.get("enabled"):
        print(f"  · 候选分批扩展：{_exp.get('expanded_obligations')} 条触顶义务做了扩展"
              f"（分批 {_exp.get('steps')}）｜共检查 {_exp.get('candidates_checked_total')} 份"
              f"｜还有 {_exp.get('candidates_unchecked_total')} 份未看"
              f"｜停止原因 {_exp.get('stop_reasons')}"
              f"｜其中 {_exp.get('verdict_changed')} 条结论因扩展而改变")
        if _exp.get("candidates_unchecked_total"):
            print("    ⚠️ 还有候选**未看** ⇒ 结论只覆盖已检查部分，"
                  "未看部分**不得**当作「不存在」")
    elif _exp.get("enabled") is False:
        print("  · 候选分批扩展：**未启用**（--no-expand-candidates）"
              "⇒ 触顶义务的结论仍只覆盖窗口内的候选")
    _print_verdicts(res["by_verdict"])

    # ── 输入快照 ID（G-A3-7：让「输入快照 ID 可复核」有真字段）────────────
    snap = _input_snapshot_id(lib, ing.get("checklist_fingerprint", ""))
    print(f"  · 输入快照 ID：{snap['input_snapshot_id']}")
    print(f"    （清单指纹 {snap['checklist_fingerprint'][:16]}…｜"
          f"材料摘要 {snap['material_digest'][:16]}…｜材料 {snap['material_files']} 件｜"
          f"代码 {snap['code_sha'][:7]}）")

    # ── 附：语义层桥接（**只作建议**，不改判定）────────────────────────
    # 桥接是**附段**：失败或跳过时，上面 6 步的输出一字不变。
    # ★ **模型参与**：只有显式 `--agent` 才接适配器 ⇒ 默认全程 RULE_ONLY。
    #   适配器在**本机**跑（材料不出本机）⇒ 不向未授权模型外发保密资料。
    _adapter = None
    _agent_spec = str(getattr(a, "agent", "") or "").strip()
    _agent_result = str(getattr(a, "agent_result", "") or "").strip()
    if _agent_spec or _agent_result:
        try:
            from cangjie_fos.services import dd_v1_agent_adapters as ad
            _adapter = ad.build_adapter(
                _agent_spec or "prebaked",
                result_path=_agent_result or None,
                dsh_enabled=(_agent_spec.lower() in ("dsh", "deepseek", "deepseek-harness")))
            print(f"  · 已接模型适配器：{getattr(_adapter, 'adapter_id', '?')}"
                  f"（本机运行，材料不出本机）")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️ 模型适配器没接上：{type(exc).__name__}: {exc}"
                  f"⇒ 本次仍走**纯规则**（RULE_ONLY）")
            _adapter = None
    bridge = _run_bridge(lib, root, a, adapter=_adapter)
    if bridge.get("ok"):
        b = bridge["result"]
        c = b["counts"]
        print(f"  ✓ 语义层桥接：{c['obligations_with_evidence']}/{c['obligations_out']} "
              f"条义务取到候选证据｜共 {c['evidence_total']} 份候选材料"
              f"｜模式 {b['mode']}｜外部模型调用 {b['external_model_calls']}")
        # ★ **模型参与 vs 纯规则**：两者的读数必须**明确分开**（不许混成一句「仅供参考」）
        _mp = b.get("model_participation") or {}
        _rc = b.get("agent_receipt") or {}
        if b["mode"] == "RULE_ONLY":
            print("  · 模型参与：**无**（本次全程 RULE_ONLY，零外部调用、零费用）")
        else:
            print(f"  · 模型参与：**有**｜参与类别 `{_mp.get('provenance')}`"
                  f"｜适配器 `{_rc.get('adapter_id')}`｜厂商 `{_rc.get('vendor')}`"
                  f"｜调用 {_rc.get('calls_used')} 次"
                  f"｜被接受的模型结果 {_rc.get('accepted_results')} 条"
                  f"｜排除式凭据 PASS {_mp.get('discrimination_pass')} 条 /"
                  f" WEAK {_mp.get('discrimination_weak')} 条")
            print(f"    · 回执摘要：{_rc.get('raw_digest') or '（无）'}")
            print("    · ★ 排除式凭据只证明判断**不是照抄第一个候选**，"
                  "**不证明**判断出自模型；模型身份看适配器实现。")
        print("  说明：**仅供参考，不改判定**；交付前仍需人工逐条核对并批准。")
        for w in b.get("warnings") or []:
            print(f"  ⚠️ {w}")
    elif bridge.get("skipped"):
        print("  · 已按 --no-bridge 跳过语义层桥接（本次输出与未接桥接时完全一致）")
    else:
        print(f"  · 语义层桥接未运行（{bridge.get('error')}）；"
              f"本次输出与未接桥接时完全一致")

    # ── 7 审核包（G-A3-6：Team Channel 薄入口 → 审核组包 这条线的唯一落点）──
    # ★ 本步**只读材料、零复制**；★ 失败**不得**影响前 6 步的输出。
    pack = _run_review_pack(lib, a)
    if pack.get("ok"):
        p = pack["result"]
        print(f"  ✓ 审核包已生成：{p['pack_path']}")
        for fn in (p.get("files") or []):
            print(f"      · {fn}")
        print(f"  · 覆盖义务 {p.get('obligations')} 条｜判定分布 {p.get('by_verdict')}")
        print(f"  · 复制原件数 {p.get('copied_source_files', 0)}"
              "（审核包**只读材料、零复制**）")
        print("  说明：交付原件必须经**人工批准**；未批准时本入口拒绝复制任何原件。")
    else:
        print(f"  · 审核包未生成（{pack.get('error')}）；"
              "本次输出与未接组包时完全一致")

    # ── 8 交付原件（G-A3-9：只有显式 --package 才走这条路径）──────────────
    rc = EXIT_OK
    delivered: list[dict] = []
    if getattr(a, "package", False):
        rc = _run_package(pack, a)
        # ★★ 实际交付清单必须进机读产物：否则「机器答卷」拿不到交付件数
        #   ⇒ HR-1（0 交付强制 0 分）会**误伤**成 0 分（真机上就是「明明交了却 0 分」）。
        # ★★ **只认本轮产出的那份**：交付目录里可能残留**上一轮**的 manifest
        #   （本轮被拒、没复制任何原件时它还在）⇒ 拿旧清单当本轮交付 =
        #   **把「本轮 0 交付」谎报成「有交付」** ⇒ 必须按 mtime 过滤。
        if rc == EXIT_OK:
            delivered = _read_run_delivery_manifest(a, pack, since=t0)
        else:
            delivered = []

    # ── 报告 ──────────────────────────────────────────────────────────
    _hr("输出")
    outdir = Path(a.out) if a.out else Path(data_plane) / "团队报告"
    outdir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    md = outdir / f"尽调报告-{lib}-{ts}.md"
    js = outdir / f"尽调结果-{lib}-{ts}.json"
    _write_reports(md, js, lib, a, res, q, cov, parsed, scan, bridge, snap,
                   delivered=delivered)

    print(f"  人看的报告：{md}")
    print(f"  机读结果  ：{js}")
    print()
    print("  ⚠️ 以上只是**建议**。交付前仍需人工逐条核对并明确批准；")
    print("     系统不会自动向机构发送任何材料。")
    print(f"\n用时 {time.time() - t0:.1f}s")
    return rc


def _run_review_pack(lib, a) -> dict:
    """第 7 步：生成**审核包**（只读材料、零复制）。

    ★ G-A3-6 接线修复：本函数是「Team Channel 薄入口 → 审核组包」这条线的唯一落点。
    ★ 规格：`dd_v1_package_service.build_review_pack(library_id, institution=...)`
      —— **不接受**输出目录参数 ⇒ 包落**数据面** `<data_dir>/reviews/<review_id>/`。
    ★ **任何失败都不得影响前 6 步的输出**（与语义层桥接同规格）。

    返回：
    - ``{"ok": True, "result": <审核包产物>}``
    - ``{"ok": False, "error": "..."}``（组包不可用；前 6 步输出不受影响）
    """
    try:
        from cangjie_fos.services import dd_v1_package_service as pkg
        res = pkg.build_review_pack(
            lib, institution=getattr(a, "institution", "") or "")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "result": res}


def _input_snapshot_id(lib: str, checklist_fingerprint: str) -> dict:
    """输入快照 ID：把「清单指纹 + 材料逐件哈希 + 代码 sha」合成一个**可复核**的 ID。

    ★ 合同（``user_visible_acceptance[0]``）要求「Windows 调用的命令、FOS 实际函数链、
      **代码 sha**、**输入快照 ID** 均可复核」⇒ 必须有一个**真字段**，不能只是文档说法。
    ★ 组成项**全部是既有产物**，不另立第二套机制：
      - ``checklist_fingerprint``：清单原文归一化后的 sha256（``ingest_checklist`` 已产出）
      - ``material_digest``：本库 manifest **每件 ``content_hash`` 排序后**的 sha256（已落库）
      - ``code_sha``：当前代码 HEAD（与《接线说明书》里那个 sha 同一个）
    ★ **只含哈希**，不含任何文件名 / 机构名 / 材料库代号 ⇒ 天然脱敏。
    ★ **不影响判定**：只写进机读结果 JSON，不进判定层、不进审核包内容。
    """
    import hashlib
    from cangjie_fos.services import dd_v1_manifest_service as mf
    try:
        rows = mf.list_manifest(lib, limit=1000000)
    except Exception:  # noqa: BLE001
        rows = []
    hashes = sorted(str(r.get("content_hash") or "") for r in rows)
    material_digest = hashlib.sha256(
        "\n".join(hashes).encode("utf-8")).hexdigest()
    code_sha = ""
    try:
        code_sha = os.popen(
            f"git -C {_REPO} rev-parse HEAD").read().strip()
    except Exception:  # noqa: BLE001
        code_sha = ""
    fp = str(checklist_fingerprint or "")
    sid = hashlib.sha256(
        "\n".join([fp, material_digest, code_sha]).encode("utf-8")).hexdigest()
    return {
        "input_snapshot_id": sid,
        "checklist_fingerprint": fp,
        "material_digest": material_digest,
        "material_files": len(rows),
        "code_sha": code_sha,
    }


def _count_files(d: Path) -> int:
    """目录里的文件数（目录不存在 ⇒ 0）。用于「未批准 ⇒ 零复制」的当场自证。"""
    if not d.exists():
        return 0
    return sum(1 for p in d.rglob("*") if p.is_file())


def _run_package(pack: dict, a) -> int:
    """``--package``：走「复制原件」路径。**HG1 人工闸不许绕。**

    ★ G-A3-9：入口文档字符串早就承诺「复制必须经显式 ``--package`` 且必须有人工批准人」，
      但该参数此前**根本不存在** ⇒ 承诺的操作在产品里是空的。
    ★ 本函数**不另写一套批准逻辑**：批准与组包都走 `dd_v1_package_service` 自己的
      `approve()` / `package_approved()`；HG1 闸在 `package_approved` → `assert_approval`
      （闸在前、复制在后）。
    ★ 红线：
      - **没有任何自动批准开关**，**也没有默认批准人**
        ⇒ 不给出批准人 ⇒ **拒绝**；
      - 未批准 ⇒ **复制零个原件**，并**当场上报**交付目录文件数（必须为 0）；
      - 任一 Gate 异常 ⇒ 同上（拒绝 + 零复制 + 退出码非 0）。
    """
    if not pack.get("ok"):
        print("  ✗ 已拒绝：未生成审核包 ⇒ 无可组包对象；本次未复制任何原件。")
        return EXIT_FAIL
    p = pack["result"]
    review_id = p["review_id"]
    # ★ WP2：正式交付包默认落在**与候选包平级**的另一个目录 ⇒ 物理隔离。
    #   （旧默认是候选包目录下的「交付包」子目录 ⇒ 候选件与正式件混在一棵树里。）
    _data_plane = os.environ.get("CANGJIE_DD_V1_DATA_DIR") or str(
        _BACKEND / "data" / "dd_v1")
    out_dir = (Path(a.package_out) if getattr(a, "package_out", "")
               else Path(_data_plane) / "deliveries" / review_id)
    approver = str(getattr(a, "approved_by", "") or "").strip()
    if not approver:
        print("  ✗ 已拒绝：未提供**人工批准人**（--approved-by）。")
        print("    HG1：未经人工最终批准，不得复制任何材料。")
        print(f"    交付目录：{out_dir}（文件数 {_count_files(out_dir)}）")
        print("    本次**未复制任何原件**。")
        return EXIT_FAIL
    try:
        from cangjie_fos.services import dd_v1_package_service as pkg
        pkg.approve(review_id, approved_by=approver,
                    note="由薄入口 --package 显式发起（批准人须由人给出）")
        res = pkg.package_approved(review_id, output_dir=str(out_dir))
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 已拒绝：{type(exc).__name__}: {exc}")
        print(f"    交付目录：{out_dir}（文件数 {_count_files(out_dir)}）")
        print("    本次**未复制任何原件**。")
        return EXIT_FAIL
    # ★ WP2：审核失效（材料在审核后被改过）⇒ **不得**产出正式交付件。
    if res.get("review_invalidated"):
        print("  ✗ 已拒绝：**审核失效**（材料在审核后发生变化，SHA256 与审核时不一致）。")
        print(f"    失效材料 {res.get('stale_material_count', 0)} 份"
              f"（清单见「审核失效清单.tsv」）")
        print("    之前的审核结论已不成立 ⇒ **必须重新核对并重新批准**后才能组包。")
        print(f"    交付目录：{res.get('output_dir') or out_dir}"
              f"（文件数 {_count_files(Path(res.get('output_dir') or out_dir))}）")
        print("    本次**未复制任何原件**、**未产出正式交付件**。")
        return EXIT_FAIL
    # ★★ WP2：**0 件不得说成「已交付」**。
    #   独立 Reviewer 终局复核抓到：`package_approved` 返回后这里**无条件**印
    #   「✓ 交付包已生成」⇒ ★**即使 exported==0（一件原件都没复制）**，
    #   ★**终端仍显示「✓ 交付包已生成」** ⇒ **把「未产出正式交付件」说成了「已交付」**。
    #   ★ WP2 原话：「允许生成供人工检查的候选包，但**必须明确标注为非正式交付**。
    #     **不得把候选包冒充正式交付包。**」
    #   ★ 措辞沿用**本文件自己的词汇表**（见上方「审核失效」分支：「未复制任何原件」、
    #     「未产出正式交付件」）⇒ **不新造第二套说法**。
    _exported = int(res.get("exported", 0) or 0)
    if _exported > 0:
        print(f"  ✓ 交付包已生成：{res.get('output_dir') or out_dir}")
    else:
        print(f"  ⚠ **未产出正式交付件**（复制原件数 0）：{res.get('output_dir') or out_dir}")
        print("    本次**未复制任何原件**、**未产出正式交付件**。")
        print("    目录里的清单与台账**仅供人工检查**，**不是正式交付**；"
              "如需正式交付件，须先解决未过闸项并重新审核批准。")
    print(f"  · 复制原件数 {res.get('exported', 0)}｜受阻 {res.get('blocked', 0)}"
          f"｜hash 不一致 {res.get('hash_mismatched', 0)}")
    # ★ WP1/WP5：逐件复算的完整性校验读数
    print(f"  · 完整性校验：{res.get('hash_verified', 0)}/{res.get('hash_verified_total', 0)}"
          f" 份逐件复算通过（SHA256SUMS：{res.get('sha256sums') or '（无）'}）")
    # ★ WP3-d：截断必须显式报数
    if res.get("blocked_truncated"):
        print(f"  ⚠️ {res.get('blocked_truncation_note')}")
    if res.get("gate_blocked_truncated"):
        print(f"  ⚠️ {res.get('gate_blocked_truncation_note')}")
    print(f"  · 批准人：{approver}")
    return EXIT_OK


def _run_bridge(lib, root: Path, a, adapter=None) -> dict:
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
            adapter=adapter,
            allow_real_material=bool(getattr(a, "allow_real_material", False)),
            # ★ 类型待判定通道：**显式打开**才生效（默认关闭 ⇒ 既有六态口径一字不变）。
            resolve_doc_type=bool(getattr(a, "resolve_doc_type", False)))
        return {"ok": True, "result": res}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _config_anchor(a) -> dict | None:
    """把 ``--anchor-year`` 折成**显式配置**锚点（期间四态锚点链的第一优先档）。

    ★ ``--anchor-year`` 本来就是规则层 ``period_from/period_to`` 的锚定年度；
      这里**只读**同一个值，不改它的行为 ⇒ 两层用的是同一个操作员意图。
    ★ 没给（或不在可核验范围）⇒ ``None`` ⇒ 相对期间若没有其它可验证锚点就判「依据不足」。
    """
    y = getattr(a, "anchor_year", None)
    if y is None:
        return None
    try:
        yi = int(y)
    except (TypeError, ValueError):
        return None
    if not (1900 <= yi <= 2999):
        return None
    return {"year": yi}


def _period_spec_view(ob: dict, *, config_anchor: dict | None = None) -> dict:
    """给一条义务算**期间语义四态**（EXPLICIT / RELATIVE / CURRENT / UNKNOWN）视图。

    ★ 口径全部来自 ``dd_v1_period_service``（**不另抄一份期间表**）。
    ★ 旧字符串 ``period``（规则层口径）**一字不改** ⇒ 本函数只**附加**一份结构化视图。
    ★ 相对期间优先于单年显式（与语义层同一优先级）。
    ★ 相对期间没有可验证锚点 ⇒ **保持未锚定**（**不拿系统时间当基准**）
      ⇒ 由调用方按「依据不足」呈现（不判否、不升格）。
    """
    from cangjie_fos.services import dd_v1_period_service as ps
    text = str(ob.get("text") or "")
    legacy = str(ob.get("period") or "").strip()
    if legacy.upper() == "CURRENT":
        # ① 该类无年度口径（规则层已判 CURRENT）⇒ 期间维度不构成年度门槛。
        return ps.spec_from_obligation({"period": legacy})
    spec = ps.parse_period_spec(text)
    if spec.get("kind") == "RELATIVE":
        # ② 相对期间：锚点链 = 显式配置 > 原文声明（材料自身年度不在本入口参与锚定）。
        anchor = ps.resolve_anchor(config_anchor=config_anchor,
                                   declared_anchor=spec.get("declared_anchor"))
        if anchor:
            spec = ps.apply_anchor(spec, anchor)
        return spec
    if legacy.isdigit() and len(legacy) == 4:
        # ③ 规则层已解析出单一年份 ⇒ 以它为准（唯一退化入口，字符串口径一字不改）。
        return ps.spec_from_obligation({"period": legacy})
    # ④ 规则层没解析出年份 ⇒ 用原文口径兜底（EXPLICIT / UNKNOWN）。
    return spec


def _period_view_text(spec: dict) -> str:
    """把四态视图压成一行人话（给报告用）。"""
    kind = str(spec.get("kind") or "UNKNOWN")
    if kind == "RELATIVE":
        if spec.get("resolved"):
            years = spec.get("years") or []
            return "RELATIVE（%s → %s）" % (years[0], years[-1]) if years else "RELATIVE（已锚定）"
        return "RELATIVE（依据不足：没有可验证锚点）"
    if kind == "EXPLICIT":
        years = spec.get("years") or []
        return "EXPLICIT（%s）" % "、".join(str(y) for y in years) if years else "EXPLICIT"
    if kind == "CURRENT":
        return "CURRENT"
    return "UNKNOWN（该维度不构成门槛）"


def _bridge_json(bridge, *, config_anchor: dict | None = None) -> dict:
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
        # ★ 模型参与的凭据与读数（机读层也要有）
        "agent_receipt": b.get("agent_receipt") or {},
        "model_participation": b.get("model_participation") or {},
        "obligations": [
            {
                "obligation_id": o["obligation_id"],
                "source_obligation_id": o["source_obligation_id"],
                "entity": o["entity"],
                "entity_basis": o["entity_basis"],
                # ★ 模型选材（有才带）⇒ 答卷据此标 MODEL
                "model_selection": o.get("model_selection") or {},
                "subject_verified": o["subject_verified"],
                "doc_type": o["doc_type"],
                "period": o["period"],
                "period_spec": _period_spec_view(o, config_anchor=config_anchor),
                "evidence_count": o["evidence_count"],
                "rule_hint": o["rule_hint"],
                # ★ 追加式：候选为空时的**六态原因**与诊断随正式入口一起出去。
                #   口径全部来自语义层（桥接层只透传）⇒ 不在入口另造一套原因表。
                "evidence_status": o.get("evidence_status") or {},
                "candidate_status": (o.get("evidence_status") or {}).get("candidate_status"),
                "no_candidate_reason": (o.get("evidence_status") or {}).get("no_candidate_reason"),
                "diagnostics": (o.get("evidence_status") or {}).get("diagnostics") or {},
                "candidates": [
                    {"file_id": e["file_id"], "sha256": e["sha256"],
                     "locator": e["locator"], "relative_path": e["relative_path"],
                     "entity": e["entity"], "period": e.get("period") or "",
                     "doc_type": e.get("doc_type") or "",
                     "subject_verified": e["subject_verified"],
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


def _delivery_manifest_path(a, pack: dict) -> Path:
    """定位本次组包的 ``组包manifest.tsv``（**实际交付**的权威清单）。"""
    p = pack.get("result") or {}
    out_dir = (Path(a.package_out) if getattr(a, "package_out", "")
               else Path(_exam_data_dir()) / "deliveries" / str(p.get("review_id") or ""))
    return out_dir / "组包manifest.tsv"


def _read_run_delivery_manifest(a, pack: dict, since: float) -> list[dict]:
    """读**本轮**产出的实际交付清单（``组包manifest.tsv``）。

    ★ **只认本轮产出的那份**：交付目录里可能残留**上一轮**的 manifest
      （本轮被拒、没复制任何原件时它还在）⇒ 拿旧清单当本轮交付
      ＝ **把「本轮 0 交付」谎报成「有交付」** ⇒ 必须按 mtime 过滤。
    ★ mtime 早于 ``since``（本次运行开始时刻）⇒ 一律当「本轮没有交付」。
    """
    from cangjie_fos.services import dd_v1_exam_service as ex
    mpath = _delivery_manifest_path(a, pack)
    if not mpath.is_file():
        return []
    try:
        if mpath.stat().st_mtime < float(since) - 1:
            return []
    except OSError:
        return []
    return ex.read_delivery_manifest(mpath)


def _write_reports(md: Path, js: Path, lib, a, res, q, cov, parsed, scan, bridge=None,
                   snap=None, delivered=None) -> None:
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

    # ── 候选分批扩展（独立小节；读数必须外显）──────────────────────────
    _exp = (res or {}).get("candidate_expansion") or {}
    if _exp:
        _ex = [
            "",
            "## 候选分批扩展（触顶义务的补查）",
            "",
            "> 候选窗口触顶时，结论**只覆盖窗口内**那部分候选。"
            "本段如实报：扩了几条、检查了多少份、**还剩多少没看**、为什么停。",
            "",
            f"- 是否启用：`{_exp.get('enabled')}`｜分批计划：{_exp.get('steps')}",
            f"- 扩展义务数：**{_exp.get('expanded_obligations')}**"
            f"｜结论因此改变的：**{_exp.get('verdict_changed')}**",
            f"- 共检查候选：**{_exp.get('candidates_checked_total')}** 份"
            f"｜**还有 {_exp.get('candidates_unchecked_total')} 份未看**",
            f"- 停止原因分布：{_exp.get('stop_reasons')}",
            "",
        ]
        for _r in _exp.get("obligations") or []:
            _ex.append(f"- `{str(_r.get('obligation_id'))[:8]}`"
                       f"：判定 {_r.get('verdict_before')} → **{_r.get('verdict_after')}**"
                       f"｜可交付件 {(_r.get('files_before'))} → {(_r.get('files_after'))}"
                       f"｜检查 {_r.get('candidates_checked')} 份"
                       f"｜未看 {_r.get('candidates_unchecked')} 份"
                       f"｜停止原因 `{_r.get('stop_reason')}`")
            if _r.get("note"):
                _ex.append(f"    - {_r.get('note')}")
        _ex.append("")
        lines += _ex

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
                          f"（{_period_view_text(_period_spec_view(ob, config_anchor=_config_anchor(a)))}）"
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
        # ★ 追加式新增段：候选为空的义务在上面的既有段落里**一行都不出**（被 continue 跳过）
        #   ⇒ 这里单独补一段「为什么没有候选」：封闭六态原因 ＋ 候选状态 ＋ 过滤诊断。
        #   ★ 既有段落结构与既有输出行**一字不改**；本段全部是**新增**输出行。
        _empty = [ob for ob in b["obligations"] if not ob["evidence_count"]]
        if _empty:
            from cangjie_fos.services import dd_v1_semantic_retrieval_service as _sem
            _six = "、".join(_sem.NO_CANDIDATE_REASONS)
            lines2.append("### 候选为空的义务（为什么没有候选）")
            lines2.append("")
            lines2.append("> 下面每条都**没有**候选材料。原因**分六类**，"
                          "不合并成一个笼统的「缺材料」；"
                          f"取值域（语义层封闭枚举）：`{_six}`。"
                          "本段只透传语义层算出的结论，入口不另造一套原因表。")
            lines2.append("")
            for ob in _empty:
                _st = ob.get("evidence_status") or {}
                _dg = _st.get("diagnostics") or {}
                _hint = ob.get("rule_hint") or {}
                lines2.append(f"- {ob['text']}")
                lines2.append(f"    - 候选状态：`{_st.get('candidate_status') or '—'}`"
                              f"｜没有候选的原因：`{_st.get('no_candidate_reason') or '—'}`"
                              f"｜规则提示：{_hint.get('verdict', '—')}"
                              f"｜规则提示里带的原因：{_hint.get('no_candidate_reason') or '—'}")
                if _dg:
                    _bits = "｜".join(f"{k}={v}" for k, v in sorted(_dg.items()))
                    lines2.append(f"    - 过滤诊断：{_bits}")
                lines2.append("")
        lines += lines2

    md.write_text("\n".join(lines), encoding="utf-8")

    js.write_text(json.dumps({
        "library": lib, "institution": a.institution,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "input_snapshot": snap or {},
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
        # ★ 候选分批扩展的读数（**机读层也要有** ⇒ 事后可复核，别只在终端print）
        "candidate_expansion": res.get("candidate_expansion") or {},
        "semantic_bridge": _bridge_json(bridge, config_anchor=_config_anchor(a)),
        # ★ 实际交付清单（组包复制了哪些原件）——「机器答卷」据此判交付件数。
        "delivered": list(delivered or []),
        "obligations": [
            {"obligation": o["obligation"],
             "verdict": (ms.get_status(o["obligation_id"]) or {}).get("verdict", ""),
             "missing": (ms.get_status(o["obligation_id"]) or {}).get("missing_detail", ""),
             "candidates": [c.get("card_rel_path") for c in ms.list_matches(o["obligation_id"])]}
            for o in obl
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _exam_data_dir() -> str:
    """考场产物目录（数据面，**不进 Git**）。"""
    return os.environ.setdefault("CANGJIE_DD_V1_DATA_DIR",
                                 str(_BACKEND / "data" / "dd_v1"))


def _exam_out_dir(a) -> Path:
    out = Path(getattr(a, "out", "") or "") if getattr(a, "out", "") else \
        Path(_exam_data_dir()) / "考场"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _exam_ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _load_contract(a):
    from cangjie_fos.services import dd_v1_exam_preflight_service as pf
    return pf.load_exam_contract(a.contract)


def _library_context(library_id: str):
    """取库 + 材料 meta + 义务 + 登记主体数（预检 / 阅卷共用）。"""
    from cangjie_fos.services import (dd_v1_bridge_service as br,
                                      dd_v1_manifest_service as mf,
                                      dd_v1_requirement_service as rq)
    lib = mf.get_library(library_id) if library_id else None
    meta: list = []
    obligations: list = []
    entities = 0
    if lib:
        try:
            meta, _stats = br.build_meta(library_id)
        except Exception:  # noqa: BLE001
            meta = []
        obligations = rq.list_obligations(library_id)
        entities = rq.entities_registered(library_id)
    return lib, meta, obligations, entities


def cmd_preflight(a) -> int:
    """**开考前 Gate**：考卷 / 图书馆 / 标准答案 三者是否正确关联。"""
    from cangjie_fos.services import dd_v1_exam_preflight_service as pf

    contract = _load_contract(a)
    library_id = getattr(a, "library", "") or (contract.get("checklist") or {}).get("library_id", "")
    lib, meta, obligations, entities = _library_context(library_id)
    material_root = None
    if lib:
        material_root = Path(lib.get("root_path") or "")
    forbidden = tuple(Path(p) for p in (getattr(a, "forbid", "") or "").split(";") if p)
    rep = pf.run_preflight(contract, library=lib, meta=meta, obligations=obligations,
                           material_root=material_root, forbidden_dirs=forbidden,
                           entities_registered=entities)
    out = _exam_out_dir(a)
    stem = f"预检-{contract.get('exam_id')}-{_exam_ts()}"
    (out / f"{stem}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), "utf-8")
    md = pf.preflight_markdown(rep)
    (out / f"{stem}.md").write_text(md, "utf-8")
    print(md)
    print(f"\n[落盘] {out / (stem + '.json')}")
    print(f"[落盘] {out / (stem + '.md')}")
    if not rep.get("scoring_ready"):
        print("\n[结论] **不具备正式评分条件** —— 只能做诊断试跑，且结果必须标「非正式评分」。")
        for b in rep.get("blockers") or []:
            print(f"  - {b['code']}：{b['detail']}")
        return EXIT_FAIL
    print("\n[结论] 具备正式评分条件。")
    return EXIT_OK


def _answer_sheet_from_run_dir(run_dir: Path):
    """从 ``dd_v1_local_run`` 的 run 目录读 **全部** run_record + packet。

    ★ ``local_run run`` 默认**按清单条目逐条跑** ⇒ 一个 run 目录下有**多份**
      ``run_record.json``（每个条目一份）⇒ 只读第一份会**漏掉绝大部分题目**
      （实测：8 条条目只读到 1 条 ⇒ 成绩单全错）。
      ⇒ 这里把多份记录的 ``accepted`` **合并**成一份答卷。
    """
    rec_paths = sorted(run_dir.rglob("run_record.json"))
    if not rec_paths:
        raise FileNotFoundError(f"RUN_RECORD_NOT_FOUND:{run_dir}")
    merged: dict = {}
    accepted: list = []
    rejected: list = []
    uncovered: list = []
    mode = "RULE_ONLY"
    degrade = ""
    for p in rec_paths:
        rec = json.loads(p.read_text(encoding="utf-8"))
        if not merged:
            merged = {k: v for k, v in rec.items() if k not in ("semantic_validation",)}
        v = rec.get("semantic_validation") or {}
        accepted.extend(v.get("accepted") or [])
        rejected.extend(v.get("rejected") or [])
        uncovered.extend(v.get("uncovered_obligations") or [])
        if v.get("mode") == "AGENT_SUGGESTION":
            mode = "AGENT_SUGGESTION"
        degrade = degrade or str(v.get("degrade_reason") or "")
    merged["semantic_validation"] = {
        "mode": mode, "degrade_reason": degrade,
        "uncovered_obligations": sorted(set(uncovered)),
        "accepted": accepted, "rejected": rejected, "warnings": [],
    }
    merged["authoritative_validation"] = "semantic_validation"
    merged["_merged_run_records"] = [str(p.relative_to(run_dir)) for p in rec_paths]
    packets = sorted(run_dir.rglob("packet.json"))
    pkt = json.loads(packets[0].read_text(encoding="utf-8")) if packets else {}
    # 多份 packet 的义务与证据要**合并**（每个条目一个包）
    if len(packets) > 1:
        obs: list = []
        evidence: dict = {}
        status: dict = {}
        for p in packets:
            pk = json.loads(p.read_text(encoding="utf-8"))
            obs.extend(pk.get("obligations") or [])
            evidence.update(pk.get("evidence") or {})
            status.update(pk.get("evidence_status") or {})
        pkt = {**pkt, "obligations": obs, "evidence": evidence, "evidence_status": status}
    return merged, pkt


def _answer_sheet_from_bridge(bridge: dict):
    """从 ``dd_team_channel run`` 的桥接结果重建 packet 形状（结构一致，口径同一个）。"""
    obs = []
    evidence = {}
    ev_status = {}
    rule_hints = {}
    for o in bridge.get("obligations") or []:
        oid = str(o.get("obligation_id") or "")
        obs.append({
            "obligation_id": oid,
            "item_id": str(o.get("source_obligation_id") or oid),
            "text": str(o.get("text") or ""),
            "entity": str(o.get("entity") or ""),
            "entity_basis": str(o.get("entity_basis") or ""),
            "period": str(o.get("period") or ""),
            "doc_type": str(o.get("doc_type") or ""),
            "doc_type_unresolved": bool(o.get("doc_type_unresolved")),
            "doc_type_source": str(o.get("doc_type_source") or ""),
            "required_parts": list(o.get("required_parts") or []),
            "split_method": "REQUIREMENT_SERVICE",
        })
        # ★ 桥接 JSON 里候选的键是 **"candidates"**（不是 "evidence"）
        #   ⇒ 读错键 ⇒ 答卷的「候选」永远为空 ⇒ 考生答卷缺来源证据。
        evidence[oid] = list(o.get("candidates") or o.get("evidence") or [])
        st = o.get("evidence_status") or {}
        ev_status[oid] = st
        # ★ 规则链提示也带过来：**没接模型**时，「机器选了什么」取它（标 RULE_HINT）。
        rh = o.get("rule_hint") or {}
        if rh:
            rule_hints[oid] = rh
    # ★★ **模型选材必须进答卷**（否则「模型参与了判断」在考生答卷上根本看不见）：
    #   桥接结果里每条义务的 `model_selection` ⇒ 还原成 R4 的 accepted 形状
    #   ⇒ `build_answer_sheet` 那条既有消费路径原样可用（不改它的判定逻辑）。
    _accepted: list[dict] = []
    _ev_by_oid = evidence
    for o in bridge.get("obligations") or []:
        _ms = o.get("model_selection") or {}
        if not _ms:
            continue
        _oid = str(o.get("obligation_id") or "")
        _pool = {str(e.get("file_id") or ""): e for e in (_ev_by_oid.get(_oid) or [])}
        _cands = []
        for _fid in (_ms.get("picked_file_ids") or []):
            _e = _pool.get(str(_fid)) or {}
            _cands.append({
                "file_id": str(_fid),
                "sha256": str(_e.get("sha256") or ""),
                "relative_path": str(_e.get("relative_path") or ""),
                "locator": str(_e.get("locator") or ""),
                "entity": str(_e.get("entity") or ""),
                "period": str(_e.get("period") or ""),
                "match_reason": "MODEL_SELECTION",
            })
        _accepted.append({
            "obligation_id": _oid,
            "item_id": str(o.get("source_obligation_id") or _oid),
            "agent_id": str(_ms.get("agent_id") or ""),
            "provider": str(_ms.get("provider") or ""),
            "model_id_or_unknown": str(_ms.get("model_id_or_unknown") or "UNKNOWN"),
            "prompt_version": "",
            "source_snapshot_id": "",
            "candidate_files": _cands,
            "proposed_verdict": str(_ms.get("proposed_verdict") or ""),
            "proposed_doc_type": str(_ms.get("proposed_doc_type") or ""),
            "confidence_or_uncertain": _ms.get("confidence_or_uncertain", "UNCERTAIN"),
            "abstain_reason": "",
            "warnings": [],
            "elapsed": 0,
            "token_usage_or_UNKNOWN": "UNKNOWN",
            "rejected_alternatives": list(_ms.get("rejected_alternatives") or []),
            "discrimination": _ms.get("discrimination") or {},
        })
    return {"obligations": obs, "evidence": evidence, "evidence_status": ev_status,
            "rule_hints": rule_hints,
            # ★ 参与类别（机读）—— 答卷据此把「有没有模型参与」标清楚
            "model_participation": bridge.get("model_participation") or {},
            "agent_receipt": bridge.get("agent_receipt") or {},
            "_accepted": _accepted}


def cmd_answer(a) -> int:
    """产出**机器答卷**（逐题：理解 / 候选 / 选中 / 交付 / 弃答原因）。"""
    from cangjie_fos.services import dd_v1_exam_service as ex

    if getattr(a, "run_dir", ""):
        rec, pkt = _answer_sheet_from_run_dir(Path(a.run_dir))
        delivered = None
    elif getattr(a, "bridge_json", ""):
        # ★ 支持**目录或通配**：PowerShell 对原生命令参数**不做通配展开**，
        #   `--bridge-json "<目录>\尽调结果-*.json"` 会把 `*` 原样传进来 ⇒ FileNotFoundError。
        #   ⇒ 这里自己解析：命中 1 个用它；命中多个取**最新**那个并如实说明。
        _bj = str(a.bridge_json)
        _bj_path = Path(_bj)
        if any(ch in _bj for ch in "*?["):
            _cands = sorted(Path(_bj).parent.glob(Path(_bj).name),
                            key=lambda q: q.stat().st_mtime)
            if not _cands:
                print(f"[错误] 通配没有命中任何文件：{_bj}", file=sys.stderr)
                return EXIT_USAGE
            _bj_path = _cands[-1]
            if len(_cands) > 1:
                print(f"  · 通配命中 {len(_cands)} 个文件 ⇒ 取**最新**的那个：{_bj_path.name}")
        elif _bj_path.is_dir():
            _cands = sorted(_bj_path.glob("尽调结果-*.json"),
                            key=lambda q: q.stat().st_mtime)
            if not _cands:
                print(f"[错误] 目录里没有 尽调结果-*.json：{_bj_path}", file=sys.stderr)
                return EXIT_USAGE
            _bj_path = _cands[-1]
            if len(_cands) > 1:
                print(f"  · 目录里有 {len(_cands)} 个结果文件 ⇒ 取**最新**的那个：{_bj_path.name}")
        raw = json.loads(_bj_path.read_text(encoding="utf-8"))
        bridge = raw.get("semantic_bridge") or raw.get("bridge") or raw
        rec, pkt = {}, _answer_sheet_from_bridge(bridge)
        # ★ 把桥接里的**模型选材**与**回执**喂进 run_record
        #   ⇒ 答卷的 `selection_source=MODEL` 与 `examinee.mode` 才不是空的。
        _acc = pkt.pop("_accepted", []) or []
        if _acc:
            rec["semantic_validation"] = {"accepted": _acc, "rejected": [],
                                          "mode": "AGENT_SUGGESTION"}
        _rc = pkt.get("agent_receipt") or {}
        if _rc:
            rec["adapter"] = {"adapter_id": str(_rc.get("adapter_id") or ""),
                              "vendor": str(_rc.get("vendor") or ""),
                              "status": str(_rc.get("status") or ""),
                              "model_id_or_unknown": str(_rc.get("model_id_or_unknown") or "UNKNOWN"),
                              "provenance": str(_rc.get("provenance") or "")}
        _mp = pkt.get("model_participation") or {}
        if _mp:
            rec["model_participation"] = _mp
        delivered = raw.get("delivered")
    else:
        print("[错误] 必须给 --run-dir 或 --bridge-json", file=sys.stderr)
        return EXIT_USAGE
    # ★★ 「实际交付」以**组包 manifest** 为准（人工也是拿它逐件核哈希的那一份）。
    #   给了 --delivered 就以它为准；没给就用机读产物里那份。
    _dl = str(getattr(a, "delivered", "") or "").strip()
    if _dl:
        delivered = ex.read_delivery_manifest(_dl)
        if not delivered:
            print(f"[警告] 交付清单读不到或为空：{_dl}"
                  "（本次按「0 件交付」计 ⇒ 阅卷会按 HR-1 强制 0 分）")
    sheet = ex.build_answer_sheet(rec, pkt, exam_id=getattr(a, "exam_id", "") or "",
                                  delivered=delivered)
    out = _exam_out_dir(a)
    stem = f"机器答卷-{_exam_ts()}"
    (out / f"{stem}.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=2), "utf-8")
    s = sheet.get("summary") or {}
    print("机器答卷已生成：")
    print(f"  义务 {s.get('obligations')}｜已理解 {s.get('understood')}｜已作答 {s.get('answered')}"
          f"｜选中 {s.get('selected_files')} 件｜交付 {s.get('delivered_files')} 件"
          f"｜候选触顶 {s.get('truncated_obligations')} 条")
    print(f"[落盘] {out / (stem + '.json')}")
    return EXIT_OK


def cmd_grade(a) -> int:
    """**隔离阅卷**：机器答卷 × 历史人工标准答案 ⇒ 逐题明细 + 0—100 成绩单。"""
    from cangjie_fos.services import dd_v1_exam_service as ex
    from cangjie_fos.services import dd_v1_gold_service as gold_svc

    sheet = json.loads(Path(a.answer).read_text(encoding="utf-8"))
    contract = _load_contract(a) if getattr(a, "contract", "") else {}
    library_id = getattr(a, "library", "") or (contract.get("checklist") or {}).get("library_id", "")
    lib, meta, _obl, _ents = _library_context(library_id)
    idx = gold_svc.index_from_snapshot((lib or {}).get("snapshot") or {}, meta)

    manifest = None
    gold_path = getattr(a, "gold", "") or (contract.get("gold") or {}).get("manifest_path", "")
    if gold_path and Path(gold_path).is_file():
        manifest = gold_svc.load_gold_manifest(gold_path)
    # ★ 泄漏检测的第 3 条判据（义务 id 既不在考卷也不在 Gold）需要这两个集合
    #   ⇒ 在 CLI 路径上**必须传**，否则该判据恒不命中（独立 Reviewer 发现）。
    _lib_obl_ids: set[str] = set()
    try:
        from cangjie_fos.services import dd_v1_requirement_service as rq
        _lib_obl_ids = {str(o.get("obligation_id") or "")
                        for o in rq.list_obligations(library_id)}
    except Exception:  # noqa: BLE001
        _lib_obl_ids = set()
    _gold_obl_ids: set[str] = set()
    if manifest is not None:
        _gold_obl_ids = {str(i.get("obligation_id") or "") for i in (manifest.get("items") or [])}
    leak = ex.detect_gold_leak(sheet, idx,
                               library_obligation_ids=_lib_obl_ids or None,
                               gold_obligation_ids=_gold_obl_ids or None)
    spec = ex.load_scoring_spec(getattr(a, "scoring_spec", "") or None)
    card = ex.grade_answer_sheet(
        sheet, manifest, library_index=idx, scoring_spec=spec,
        gold_provided=manifest is not None,
        gold_state="NOT_PROVIDED" if manifest is None else "",
        gold_state_reason="未提供标准答案包" if manifest is None else "",
        exam_id=str(contract.get("exam_id") or ""),
        leak_report=leak)
    out = _exam_out_dir(a)
    stem = f"成绩单-{_exam_ts()}"
    (out / f"{stem}.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), "utf-8")
    if card.get("status") == "NOT_SCORABLE":
        print(f"[不可评分] {'；'.join(card.get('blocked_by') or [])}")
        print(f"[落盘] {out / (stem + '.json')}")
        return EXIT_FAIL
    sc = card.get("scores") or {}
    cn = card.get("counts") or {}
    print("=" * 66)
    print(f"  DD-V1 成绩单 · {card.get('exam_id') or '(未命名考场)'}")
    print("=" * 66)
    print(f"  题目理解覆盖率      : {sc.get('question_understanding_coverage')}")
    print(f"  材料召回率          : {sc.get('material_recall')}")
    print(f"  选材准确率          : {sc.get('selection_precision')}")
    print(f"  完整正确交付题目比例: {sc.get('complete_delivery_ratio')}")
    print(f"  漏交率              : {sc.get('miss_rate')}")
    print(f"  错交率              : {sc.get('wrong_rate')}")
    print(f"  ── 总成绩           : {sc.get('total_score')} / 100")
    print(f"  状态                : {card.get('status')}"
          f"｜安全闸 {((card.get('safety_gate') or {}).get('status'))}"
          f"（违规 {((card.get('safety_gate') or {}).get('violations'))}）")
    print(f"  义务 {cn.get('obligations')} 条｜期望材料 {cn.get('expected_files')} 件"
          f"｜选中 {cn.get('selected_files')} 件｜交付 {cn.get('delivered_files')} 件")
    if card.get("zero_delivery_forced_zero"):
        print("  ★ 有效标准答案 + 0 件交付 ⇒ 总分强制 0（不是 NOT_SCORABLE）")
    print(f"[落盘] {out / (stem + '.json')}")
    return EXIT_OK


def cmd_compare(a) -> int:
    """同口径版本比较（**旧版没有真实成绩 ⇒ 标「未建立可比基线」**）。"""
    from cangjie_fos.services import dd_v1_exam_service as ex
    old = json.loads(Path(a.old).read_text(encoding="utf-8")) if getattr(a, "old", "") else None
    new = json.loads(Path(a.new).read_text(encoding="utf-8")) if getattr(a, "new", "") else None
    cmp = ex.compare_scorecards(old, new,
                                old_label=getattr(a, "old_label", "") or "旧版本",
                                new_label=getattr(a, "new_label", "") or "新版本")
    md = ex.compare_markdown(cmp)
    out = _exam_out_dir(a)
    stem = f"版本对比-{_exam_ts()}"
    (out / f"{stem}.md").write_text(md, "utf-8")
    (out / f"{stem}.json").write_text(json.dumps(cmp, ensure_ascii=False, indent=2), "utf-8")
    print(md)
    print(f"\n[落盘] {out / (stem + '.md')}")
    return EXIT_OK


def cmd_contract_template(a) -> int:
    """打印考场契约模板（操作员填写用；**不含任何真实业务内容**）。"""
    from cangjie_fos.services import dd_v1_exam_preflight_service as pf
    out = _exam_out_dir(a)
    p = out / "考场契约-模板.json"
    p.write_text(json.dumps(pf.exam_contract_template(), ensure_ascii=False, indent=2), "utf-8")
    print(p.read_text(encoding="utf-8"))
    print(f"[落盘] {p}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dd_team_channel",
        description="投资尽调自动组包 V1 · 团队调用入口（WP7）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)

    r = sp.add_parser("run", help="跑一次完整流程：清单进来 → 匹配结果与缺口清单出去")
    r.add_argument("--library", required=True, help="材料库标识（自己起个名字，如 主体丙材料库）")
    r.add_argument("--root", required=True, help="材料库根目录（本机路径）")
    r.add_argument("--checklist", required=True, help="机构清单文件（每行：编号<TAB>原文）")
    r.add_argument("--institution", default="", help="机构名称")
    r.add_argument("--name", default="", help="材料库显示名")
    r.add_argument("--by", default="", help="授权人（默认取当前用户名）")
    r.add_argument("--anchor-year", type=int, default=None,
                   help="「近三年」这类相对年份的锚定年；不给则不擅自假定")
    r.add_argument("--cap", type=int, default=20, help="每条要求的候选材料上限（默认 20）")
    r.add_argument("--no-expand-candidates", action="store_true",
                   help="**不**做候选分批扩展（默认：触顶的义务自动分批放大窗口重跑，"
                        "并如实报「看了多少／还剩多少没看／为什么停」）")
    r.add_argument("--confirmed-entity-map", default="",
                   help="人工确认的主体映射表 JSON（sha256／file_id／文件名 → 主体）"
                        "—— 主体识别里证据强度最高的一档")
    r.add_argument("--agent", default="",
                   help="接**模型**做语义判断：codex｜pi｜dsh｜manual｜none（默认 none＝纯规则）")
    r.add_argument("--agent-result", default="",
                   help="Harness 回执 JSON 路径（模型在**本机**跑完后回传；"
                        "材料不出本机 ⇒ 不向未授权模型外发保密资料）")
    r.add_argument("--parse-limit", type=int, default=2000, help="本次最多抽取多少份正文")
    r.add_argument("--out", default=None, help="报告输出目录")
    r.add_argument("--no-bridge", action="store_true",
                   help="跳过语义层桥接（本次输出与未接桥接时完全一致）")
    r.add_argument("--allow-real-material", action="store_true",
                   help="材料库不是仓库内合成 fixture 时必须给（=真实材料，仅限本机）")
    r.add_argument("--contract", default="",
                   help="考场契约 JSON（把其中声明的 entity_scope 落到未指名主体的义务上；"
                        "不声明 ⇒ 一条都不改）")
    r.add_argument("--resolve-doc-type", action="store_true",
                   help="打开「规则层解析不出材料类型 ⇒ 交给模型判定」这条通道"
                        "（默认关闭：既有六态口径与既有成本纪律一字不变；"
                        "真实清单里类型待判定的题需要显式打开）")
    r.add_argument("--package", action="store_true",
                   help="显式走「复制原件」路径（必须同时给 --approved-by；"
                        "未批准 ⇒ 拒绝且零复制；无自动批准开关）")
    r.add_argument("--approved-by", default="",
                   help="人工批准人（配合 --package 使用；必填且不可留空）")
    r.add_argument("--package-out", default="",
                   help="交付目录（不给则用 <审核包>/交付包）")
    r.set_defaults(func=cmd_run)

    st = sp.add_parser("policy", help="查看披露策略是否生效")
    st.set_defaults(func=lambda a: (_print_policy(), EXIT_OK)[1])

    # ── 考场四步（#85 永久验收红线）────────────────────────────────────────
    pf = sp.add_parser("preflight", help="开考前 Gate：考卷/图书馆/标准答案 三者是否正确关联")
    pf.add_argument("--contract", required=True, help="考场契约 JSON 路径")
    pf.add_argument("--library", default="", help="材料库标识（不给则取契约里的）")
    pf.add_argument("--out", default="", help="输出目录（不给则落数据面 <data>/考场）")
    pf.add_argument("--forbid", default="",
                    help="额外禁止目录（分号分隔），用于把材料/运行目录列为 Gold 禁区")
    pf.set_defaults(func=cmd_preflight)

    an = sp.add_parser("answer", help="产出机器答卷（逐题：理解/候选/选中/交付/弃答原因）")
    an.add_argument("--run-dir", default="", help="dd_v1_local_run 的 run 目录（含 run_record.json）")
    an.add_argument("--bridge-json", default="", help="团队入口产出的 尽调结果-*.json")
    an.add_argument("--delivered", default="",
                    help="组包manifest.tsv（**实际交付**清单）；"
                         "给了它就以它为准（阅卷的「实际交付件数」只看这一份）")
    an.add_argument("--exam-id", default="", help="考场标识")
    an.add_argument("--out", default="", help="输出目录")
    an.set_defaults(func=cmd_answer)

    gr = sp.add_parser("grade", help="隔离阅卷：机器答卷 × 历史人工标准答案 ⇒ 0—100 成绩单")
    gr.add_argument("--answer", required=True, help="机器答卷 JSON 路径")
    gr.add_argument("--contract", default="", help="考场契约 JSON 路径")
    gr.add_argument("--gold", default="", help="标准答案包清单路径（不给则取契约里的）")
    gr.add_argument("--library", default="", help="材料库标识（不给则取契约里的）")
    gr.add_argument("--scoring-spec", default="", help="冻结评分口径（不给则用仓内默认）")
    gr.add_argument("--out", default="", help="输出目录")
    gr.set_defaults(func=cmd_grade)

    cp = sp.add_parser("compare", help="同口径版本比较（旧版无成绩 ⇒ 标「未建立可比基线」）")
    cp.add_argument("--old", default="", help="旧版成绩单 JSON")
    cp.add_argument("--new", default="", help="新版成绩单 JSON")
    cp.add_argument("--old-label", default="", help="旧版标签")
    cp.add_argument("--new-label", default="", help="新版标签")
    cp.add_argument("--out", default="", help="输出目录")
    cp.set_defaults(func=cmd_compare)

    ct = sp.add_parser("contract-template", help="打印考场契约模板")
    ct.add_argument("--out", default="", help="输出目录")
    ct.set_defaults(func=cmd_contract_template)
    return p


def _print_policy() -> None:
    _policy_note()


def main(argv: list[str] | None = None) -> int:
    """``argv`` 可选（默认取 ``sys.argv``）—— 便于测试**直接调用真实入口**。"""
    a = build_parser().parse_args(argv)
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
# gm-pubredact-r1b: 真实短名脱敏（替身代称）
