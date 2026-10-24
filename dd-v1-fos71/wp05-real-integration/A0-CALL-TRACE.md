# A0 · Call Trace 摘要（两正式入口 × 仓库内合成 fixture）

原始证据（attempt-3 单次干净重跑，一个文件=一次运行=一个分段）：
`a0-evidence/calltrace-entryA.jsonl`（3144 行 = 1 meta + **3142 个 call 事件** + 1 done，exit 0）/
`a0-evidence/calltrace-entryB.jsonl`（521 行 = 1 meta + **519 个 call 事件** + 1 done，exit 2）。
**合计 3661 个 FOS call 事件**（3142 + 519）。
记录格式：`{"event":"call","depth":N,"module":"...cangjie_fos.services.dd_v1_match_service","func":"judge","file_line":"backend/src/.../dd_v1_match_service.py:428","caller":".../tools/dd_team_channel.py:176"}`；meta 携带 run_id + 完整 argv + head_sha，done 携带 run_id + 真实退出码（非 SystemExit 崩溃时 exit_code=1 且附 error）。
复核方法：任选一行，`git show a7a7e249:<file_line 中的文件>` 对到函数定义行；或重跑 `a0-evidence/a0-trace-runner.py`（纯 setprofile，无侵入；默认覆盖写，单文件单分段）。

## 入口 A：tools/dd_team_channel.py run（exit 0，run_id 20261021T151453-p46434）

管线（运行时打印 = 第 1/共 6 步 … 第 6/共 6 步；docstring 的「7 步」是错的）：

```
[env] CANGJIE_DD_V1_DATA_DIR 重定向（core/paths.get_dd_v1_data_dir @160，全链 115 次）
第1步 登记库   dd_v1_manifest_service.register_library(@226)
第2步 扫描     find_resumable_run → build_manifest(@361)
               └ _iter_candidate_files(×9) → dd_index_service._is_cangjie_internal/_is_excluded_dir(各×8)
               └ _upsert_file(×8) → make_file_id(×8) / compute_content_hash(×8) / iter_version_hints(×16)
               └ _soft_delete_missing / _touch / to_dict
第3步 读正文   dd_v1_parser_service.parse_pending_batch(@240)
               └ extract_and_record(×8) → extract_content(×8) → dd_file_parser.extract_full_text(×8)
                 → dd_content_extractor.extract_for_verify(×8)
               └ docling_available(×9, @dd_v1_parser_service.py:75)=False → 内置解析器降级
第4步 认知卡   dd_v1_card_service.build_cards_for_library(@624)
               └ build_card(×8) → set(×127)/_extract_labels(×8)/detect_related_files(×8)/bigram_expand(×32)
               └ card_coverage(@674)（出处 FACT 46 / INFERRED 16 / UNKNOWN 74）
第5步 拆清单   dd_v1_requirement_service.ingest_checklist
               └ build_obligations(@366, ×4) → parse_entity_scope/parse_period/parse_doc_type/
                 parse_caliber/parse_seal(@350)/parse_attachments(@360)（各×4）
               └ obligation_quality(@592) → entities_registered（=0 → 提示需权威主体名单，不拿目录名凑数）
第6步 匹配     dd_v1_match_service.match_library(@602)
               └ match_obligation(@266, ×4) → _recall_candidates(@229, ×4) → card_service.search_materials_loose(@559, ×18)
               └ judge(@428, ×4) → detect_anomalies(@356, ×4) → evaluate_file(@139, ×24) → policy evaluate(@169, ×24)
               └ _persist(@560, ×4)
报告输出       list_obligations + get_status(@624, ×12) + list_matches(@639, ×8) → 报告.md / 结果.json
```

本轮判定结果（与 `entryA-reports/尽调结果-a0evidence-20261021-231454.json` 机读逐条一致；`by_verdict = {MISSING: 1, CONFLICT: 3}`，本轮未产出 MATCHED）：
- R1 2024审计含附注 → **CONFLICT**（`同一主体/期间存在 1 组内容冲突，需人工裁定`）
- R2 章程+社保 → **CONFLICT**（同上）
- R3 「其他相关材料等」 → **MISSING**（拆不出类型/期间；candidates=[]）
- R4 2022年度审计（不存在） → **CONFLICT**（`期间缺 1/1 年; 同一主体/期间存在 1 组内容冲突，需人工裁定`）
- 机读 JSON：`human_approval_required=true`、`sent_to_institution=false`、`disclosure_policy.loaded=false → 全部按最严处理`（fail-closed 实证）

**CONFLICT 成因（真实 FOS 行为，A2/A3 必须先解决）**：认知卡 `dd_v1_material_cards.entity` 8/8 全为空串、`rel_path` 扁平无 `/` → `detect_anomalies` 主体回退 `rel_path.split("/")[0]`（`dd_v1_match_service.py:376-377`）仍为空 → 按 `("", period)` 分桶（:379）→ 2024 期 5 份（G001/G002/G003/G005/G006，跨 示例科技 与 样板贸易 两法人、两种 doc_type、含附注）落同一桶、5 个不同 hash → 1 组冲突。**G007（2021）不在该组**。不是 DRAFT/SUPERSEDED/异主体「引发」冲突，而是 entity 空导致跨法人混桶假冲突。

## 入口 B：tools/dd_v1_local_run.py run --adapter manual（exit 2 = 无 AGENT_SUGGESTION 的设计信号，run_id 20261021T151503-p46492）

```
材料门禁   dd_v1_local_run.py:87 sem._inside(@336, ×2)(material_root, backend/tests/fixtures)=True
           → local_material_snapshot(@309, ×1) → _read_only_check(@129, ×8) 全过（自动免 --allow-real-material）
拆解       split_items(@82, ×7) → split_item(×7) → _doc_type(×9)
           R3「其他相关材料等」→ 0 义务 → status=NEEDS_HUMAN_SPLIT（不调用模型，dd_v1_local_run.py:117）
逐条 R1/R2/R4（每条）:
  建包     run_semantic(@280, ×3) → build_semantic_packet(@174, ×3)
           └ load_snapshot(@dd_v1_agent_result_service.py:69, ×3) → sha256_file(@:43, ×24) → snapshot_id(×3)（snap-ec8e949e8d0531dc）
           └ retrieve_minimal_evidence(@136, ×4) → _text_for(×10) → _read_only(×10) → _excerpt(×10)
             （≤6 文件/义务 @34；≤300 字摘录 @35；同主体同类型过滤；EFFECTIVE 优先）
  调用     run_agent(@350, ×3) → ManualExchangeAdapter.run(@222, ×3)
           └ 写 PROMPT.txt/packet.json/schema.json → 无 reply.json → PENDING_MANUAL
  校验     validate_agent_output(@212, ×6) → _rule_only(@136, ×6)（call_error=PENDING_MANUAL → 显式降级）
           └ validate_semantic(@257, ×3) → rule_hint(@157, ×4)（R1-O1: MATCH G001+G002，注明「不是 Gold」）
  落盘     run_record.json（schema dd_v1_agent_result.v1，authoritative_validation=semantic_validation）
汇总       run_summary.json（calls_total=3 = 3 组 adapter 尝试 × calls_used:1；external_model_calls=0 —— 零外部模型调用、零费用）
退出       return 0 if any(mode==AGENT_SUGGESTION) else 2  → exit 2
```

关键语义（A1 必须保持的行为，本轮全部实证）：
1. 模型缺席 ≠ 崩溃：PENDING_MANUAL → RULE_ONLY + degrade_reason 原样记录 + exit 2。
2. 拆不出义务不烧模型：NEEDS_HUMAN_SPLIT 直接回人工。
3. 模型输出永远不是权威：authoritative 层=semantic_validation；结构层只是中间结果。
4. 工作区隔离：非空 workdir 拒绝（WORKDIR_NOT_EMPTY）；回贴必须带 provenance，人工回贴永远不算独立考生答卷（ManualExchangeAdapter :232-240）。

## 两入口覆盖对照（任务书要求点名函数）

| 要求可见的符号 | 入口 A trace | 入口 B trace |
|---|---|---|
| dd_v1_manifest_service.* | ✔（register/build_manifest 等） | —（B 不建 manifest） |
| dd_v1_parser_service.* | ✔（parse_pending_batch 等） | —（B 读 .txt 原文不走 parser） |
| dd_v1_card_service.* | ✔（build_cards 等） | — |
| dd_v1_requirement_service.* | ✔（ingest/build_obligations） | ✔（split_items 侧） |
| dd_v1_match_service.*（judge @428） | ✔ judge×4 | —（B 用 semantic 链） |
| dd_v1_semantic_retrieval_service.run_semantic | — | ✔ ×3 |
| dd_v1_agent_adapters.* | — | ✔ run_agent×3 + ManualExchangeAdapter |
| dd_v1_agent_result_service.validate_agent_output @212 | — | ✔ ×6 |
| dd_v1_package_service.package_approved @385 | ✘ 代码级证据（组包需人工批准，dry-run 未触发） | ✘ 同左 |
| 旧 dd_match_service.run_matching @93 | ✘ 0 命中（正确：旧模块不在新链） | ✘ 0 命中 |
