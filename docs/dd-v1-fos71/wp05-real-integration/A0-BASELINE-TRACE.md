# A0 · 基线与真实入口 Trace（FOS #71 DD-V1 实引擎集成）

- task_id: T-DD-V1-REALINT-2026-A0（attempt-3 整改版）
- work_id: W-DD-V1-REALINT-2026
- base: cangjie-fos `a7a7e24977eeb40b62e1b34d39d9d4a58dadd28d`，branch `feat/71-a0-baseline-trace`，worktree `/Users/mac/cangjie-fos-wt-a0`
- executor: hermes（Mac 本机，一次性前台命令，无守护进程）
- 性质声明：A0 只做「查清 + 举证」，**未改任何产品代码/测试/配置**，未 commit/push。产物只落在 `docs/dd-v1-fos71/wp05-real-integration/`（新目录，见 git status）。
- 规范仓只读核对：grill-to-spec main `d14327c6de89e1afa2fca081f7bf984577a7e5ca`；`scripts/check_gccseg.py --require-v3-8 GOAL-CONTRACT.v3.8.json` → exit 0 `PASS: GCCSEG structural + goal alignment contract (not semantic or real-world acceptance)`（结构检查 PASS，不等于语义/真实业务验收）。
- 本轮模型调用：**0 次**。费用：**0 元**。未调用 dsh/付费 OCR/任何外部 API。

## 0. attempt-3 整改回执（独立 Reviewer 2 MAJOR / 2 MINOR / 1 NOTE）

| 项 | 整改内容 | 证据 |
|---|---|---|
| M1-① | `a0-trace-runner.py` 重写：默认**覆盖写**（`mode="w"`，一个文件=一次运行=一个分段），meta 携带 `run_id`（UTC+pid）+ 完整 argv + `trace_mode`；**非 SystemExit 异常记录真实退出码 1** + `done.error`（异常类型+消息），runner 进程自身以真实码退出。自证：对不存在脚本试跑 → rc=1，done 事件 `{"exit_code":1,"error":"FileNotFoundError: ..."}` | 本轮 head/tail + runner 源码 `:19-26`（分段语义）、`:104-113`（退出码语义） |
| M1-② | 入口 A / 入口 B 各**单次干净重跑**，覆盖 `calltrace-entryA.jsonl` / `calltrace-entryB.jsonl`；入口 B 同步重跑（原来已是单次，为一致性重跑） | entryA=3144 行（1 meta + **3142 call** + 1 done，exit 0，run_id `20261021T151453-p46434`）；entryB=521 行（1 meta + **519 call** + 1 done，exit 2，run_id `20261021T151503-p46492`） |
| M1-③ | 全部公开计数改为真实值：**入口 A = 3142 call 事件、入口 B = 519 call 事件、合计 3661**；attempt-2 的两个错误计数（run#3 误读值与 A+B 旧合计）已从全部产物清除 | `wc -l` + 逐行 json 解析计数（3142/519/3661，meta=1、done=1 各一次） |
| M1-④ | `SHA256SUMS-a0-evidence.txt` 重算（覆盖全部证据文件），`shasum -c` 全过 | 本文 §6 末尾 |
| M2 | `:64` 判定表述改为与机读 JSON 一致：**R3（其他相关材料等）→ MISSING；R4（2022 年度审计）→ CONFLICT（期间缺 1/1 年 + 1 组内容冲突）**；成因改为「认知卡 entity 全空 + 扁平 rel_path 无 `/` → 回退 `split("/")[0]` 仍为空 → 按 `("", period)` 分桶 → 2024 期 5 份跨 示例科技/样板贸易 两法人混桶 → 5 hash ≠ → 1 组冲突」。旧表述（G003 DRAFT/G007 SUPERSEDED/G005 异主体引发冲突）作废 | 本文 §2 入口 A + `entryA-reports/尽调结果-a0evidence-20261021-231454.json`（R3=MISSING 空 candidates；R4=CONFLICT `missing="期间缺 1/1 年; 同一主体/期间存在 1 组内容冲突，需人工裁定"`）；plane-A sqlite：`dd_v1_material_cards` 8 行 entity 全空串（COUNT=8, SUM(entity='')=8, SUM(seal_status='')=8），fiscal_period 2024×5/2023×1/2021×1/空×1 |
| M3 | `calls_total=3`（= 3 组 × `calls_used:1`，run-R1/R2/R4 各 1），另起一行 `external_model_calls=0`（零外部模型调用结论不变） | `entryB-outputs/entryB/run_summary.json` `calls_total=3`；`run_record.json` `calls_used=1` ×3；本文 §2 入口 B |
| M4 | `sha256_file` 计数 **24**（= 3 次 `load_snapshot` × 8 文件，`dd_v1_agent_result_service.py:43`）；`docling_available` 归属改为 **`dd_v1_parser_service.py:75`**（×9 不变） | 新 entryB trace 逐行计数 sha256_file=24；新 entryA trace docling_available=9 且 `file_line=backend/src/cangjie_fos/services/dd_v1_parser_service.py:75` |
| N6 | 明确写入：本轮 **从未产出 MATCHED**（3 CONFLICT + 1 MISSING），「正常/MATCH 路径未被本 fixture 覆盖」，A1/A2 需另补该路径覆盖 | 本文 §2 末尾「MATCHED 缺口」段 |

M1-①同轮修正连带：两份 trace 重建后，attempt-2 文档里所有 ×N 计数（`_iter_candidate_files`×9、`judge`×4、`search_materials_loose`×18、`evaluate_file`×24、`bigram_expand`×32、`set`×127、`get_dd_v1_data_dir`×115 等）已**逐一按新 trace 重新计数**——数值全部与 attempt-2 相同（确定性复现），唯两处例外已改正：`build_obligations` def 行 **@366**（attempt-2 误写 364）、`load_policy` 实调 **×26**（attempt-2 误写 48 次）。

## 1. 固定基线（本轮实跑）

| 项 | 值 | 证据命令 |
|---|---|---|
| HEAD | `a7a7e24977eeb40b62e1b34d39d9d4a58dadd28d` | `git -C /Users/mac/cangjie-fos-wt-a0 rev-parse HEAD` |
| branch | `feat/71-a0-baseline-trace` | `git branch --show-current` |
| 远端 | origin `https://github.com/bog5d/cangjie-fos.git` | `git remote -v` |
| uv | 0.10.12 (00d72dac7) | `uv --version` |
| FOS 解释器 | backend/.venv Python **3.13.12** | `.venv/bin/python --version`（系统 python3=3.9.6，仅用于脚本辅助） |
| FOS 包版本 | cangjie_fos 0.1.0 @ `backend/src/cangjie_fos/__init__.py` | `uv run python -c "import cangjie_fos; ..."` |
| 依赖安装 | `cd backend && uv sync --extra dev` → exit 0 | 实跑输出 |
| pytest（真基线，代理 unset） | **1424 tests / 0 failures / 0 errors / 5 skipped = 1419 passed，exit 0**，222.6s | `env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q --junit-xml=/tmp/a0_pytest_clean.xml`；junit 解析（`a0-evidence/pytest-clean-junit.xml`） |
| pytest（带代理对照） | **6 failures，exit 1**，junit: tests=1424 failures=6 errors=0 skipped=5 | 同命令去掉 env -u；`a0-evidence/pytest-proxy-junit.xml` |

带代理 6 失败全部是 **httpx→socksio ImportError 型环境假红**（本机 `ALL_PROXY=socks5://127.0.0.1:7897`，httpx SOCKS 需要 socksio 包）：
- `test_dd_material_architecture.py::TestPhase1FullText::test_refine_overrides_confidence_when_not_satisfied`
- `test_dd_material_architecture.py::TestPhase1FullText::test_refine_confirms_when_satisfied`
- `test_dd_material_architecture.py::TestPhase2Verdict::test_verdict_assigned_without_content_no_llm`
- `test_dd_material_architecture.py::TestPhase2Verdict::test_refine_circuit_breaker_on_llm_down`
- `test_dd_redteam.py::TestPromptInjection::test_refine_zero_overlap_clamps_even_if_model_says_green`
- `test_dd_redteam.py::TestPromptInjection::test_refine_keeps_green_when_overlap_real`

处置：未改断言、未加 skip；真基线以代理 unset 的 1419 passed 为准。与独立 Reviewer 先前实测（1419 passed）数字一致。

本机实测坑（供 A1+ 复用）：
- pytest 9.0.3 在 `-q` 下不打印 `N passed` 汇总行——计数一律用 `--junit-xml` 解析（本轮即此法）。
- `uv sync` 在 uv 0.10.12 下会**重写 `backend/uv.lock`**（锁格式升级，1797 行变更）。A0 已 `git checkout -- backend/uv.lock` 还原；跑入口直接用 `backend/.venv/bin/python`（同一解释器），不再触发锁重算。
- shell 组合命令里 `$?` 会被管道吞掉（tail 的退出码冒充 pytest 退出码）——退出码必须落文件后单独读。
- `gm.cli validate` 未在本轮执行：A0 不动 cangjie-gm；本任务书亦未要求（司仓侧责任保留）。

## 2. 真实入口 call_trace（核心证据）

方法：`a0-evidence/a0-trace-runner.py`（纯 `sys.setprofile` C 级回调，只按 `co_filename` 前缀过滤 `cangjie_fos` 包，不打补丁/不包装产品代码；attempt-3 起默认覆盖写、单文件单分段、非 SystemExit 崩溃记录真实退出码 1 + `done.error`）。两份原始 JSONL（attempt-3 干净单次重跑）：
- `a0-evidence/calltrace-entryA.jsonl`（3144 行 = 1 meta + **3142 个 call 事件** + 1 done，exit 0）
- `a0-evidence/calltrace-entryB.jsonl`（521 行 = 1 meta + **519 个 call 事件** + 1 done，exit 2）
- **合计 3661 个 FOS call 事件**（3142 + 519）

每条记录含 module + func + file:def_line + caller(file:line) + 深度；meta 携带 run_id/argv/head_sha，done 携带 run_id/真实退出码。sha256 见 `a0-evidence/SHA256SUMS-a0-evidence.txt`（attempt-3 重算）。

### 入口 A：tools/dd_team_channel.py（Team Channel 正式入口，纯规则链，无模型）

命令（真实材料开关未使用；材料=仓库内 fixture 原路径；attempt-3 重跑前已清空 /tmp 附件区）：
```bash
cd /Users/mac/cangjie-fos-wt-a0/backend && env -u ALL_PROXY -u all_proxy ... \
  CANGJIE_DD_V1_DATA_DIR=/tmp/a0-evidence-attachment/plane-A \
  .venv/bin/python <a0-evidence>/a0-trace-runner.py --trace-out calltrace-entryA.jsonl -- \
  /Users/mac/cangjie-fos-wt-a0/tools/dd_team_channel.py run \
  --library a0evidence \
  --root /Users/mac/cangjie-fos-wt-a0/backend/tests/fixtures/dd_v1_fos71_wp04/snapshot \
  --checklist <a0-evidence>/a0-synthetic-checklist.tsv \
  --institution A0合成机构 --by a0-executor
```
- **exit 0**（stdout 原文：`entryA-run-stdout.log`；stderr 0 字节）。run_id `20261021T151453-p46434`。
- 运行时打印「第 1 步 / 共 6 步」…「第 6 步 / 共 6 步」——证实任务书已知事实：docstring 的「7 步」是错的，代码为准=6 步（`dd_team_channel.py:116-175`）。
- 结果：8 份材料登记/扫描/解析 8 ok；4 条义务 → **3 CONFLICT + 1 MISSING**（机读 `summary.by_verdict = {MISSING: 1, CONFLICT: 3}`）。
- 机读结果字段实证：`human_approval_required=true`、`sent_to_institution=false`、披露策略未配置→全部按最严不可外发（`entryA-reports/尽调结果-a0evidence-20261021-231454.json`）。
- 数据面：`CANGJIE_DD_V1_DATA_DIR` 重定向到 /tmp 附件区，**未写 `data/`**（`core/paths.py:160-163` 支持该 env）。

**逐义务判定（与机读 JSON 逐条一致，M2 整改后口径）**：

| 义务（清单原文） | verdict | 机读 `missing` 字段原文 |
|---|---|---|
| 提供示例科技有限公司2024年度审计报告（含附注）（R1） | CONFLICT | `同一主体/期间存在 1 组内容冲突，需人工裁定` |
| 提供示例科技有限公司最新公司章程及2024年社保缴纳证明（R2） | CONFLICT | `同一主体/期间存在 1 组内容冲突，需人工裁定` |
| 其他相关材料等（R3） | **MISSING** | （空；candidates=[]，拆不出类型/期间 → 候选 0） |
| 提供示例科技有限公司2022年度审计报告（R4） | **CONFLICT** | `期间缺 1/1 年; 同一主体/期间存在 1 组内容冲突，需人工裁定` |

**CONFLICT 的真实成因（M2 整改口径，FOS 行为实录）**：本轮认知卡 `dd_v1_material_cards.entity` 对 8 份材料**全为空串**（sqlite 实证：8 行 COUNT、`SUM(entity='')=8`）；`rel_path` 是扁平文件名（无 `/`），`detect_anomalies`（`dd_v1_match_service.py:356`）的主体回退 `rel_path.split("/")[0]`（:376-377）同样得空 → 按 `("", period)` 分桶（:379）→ **2024 期的 5 份材料**（G001 正文/G002 附注/G003 DRAFT/G005 样板贸易 2024 审计/G006 章程，**跨 示例科技 与 样板贸易 两个法人**、两种 doc_type、含附注关系）落进同一桶、5 个不同 content_hash → 1 组冲突。**G007（2021）不在该冲突组**。`seal_status` 同样全为空——`dd_v1_match_service.py:174-177` 自认的签章永久缺口在实测中成立。

**这是当前 FOS 的真实行为，不是本轮操作事故**：认知卡 entity 为空导致跨主体假冲突，**A2/A3 必须先解决它**（权威主体名单登记 or 主体识别增强），否则多主体场景会大面积假冲突。

trace 中实调的 FOS 官方函数（模块.函数 @ 文件:行号，行号为本轮 trace `file_line` 实录；×N 为本轮重算计数）：
| # | 函数 | file:line | 本轮计数 |
|---|---|---|---|
| 1 | dd_v1_policy_service.policy_status / load_policy / evaluate | dd_v1_policy_service.py:236 / :104 / :169 | policy_status ×2、load_policy ×26、evaluate ×24 |
| 2 | dd_v1_manifest_service.register_library → build_manifest（_iter_candidate_files/_upsert_file/make_file_id/compute_content_hash/iter_version_hints/_soft_delete_missing） | dd_v1_manifest_service.py:226 / :361 | ×1 / ×1（子调用 9/8/8/8/16/1） |
| 3 | dd_v1_parser_service.parse_pending_batch → extract_and_record/extract_content + dd_file_parser.extract_full_text + dd_content_extractor.extract_for_verify | dd_v1_parser_service.py:240 | ×1（子调用各 ×8；docling_available @:75 ×9=False→内置解析器降级） |
| 4 | dd_v1_card_service.build_cards_for_library → build_card/detect_related_files/bigram_expand + card_coverage | dd_v1_card_service.py:624 | ×1（build_card ×8、detect_related_files ×8、bigram_expand ×32、set ×127、card_coverage @:674 ×1） |
| 5 | dd_v1_requirement_service.ingest_checklist → build_obligations（parse_entity_scope/parse_period/parse_doc_type/parse_caliber/parse_seal/parse_attachments）→ obligation_quality | dd_v1_requirement_service.py:366(build_obligations), :350(parse_seal), :360(parse_attachments) | 各 ×4，obligation_quality @:592 ×1 |
| 6 | dd_v1_match_service.match_library → match_obligation → _recall_candidates → **judge @428** → detect_anomalies → evaluate_file + get_status/list_matches（报告阶段） | dd_v1_match_service.py:428,:602,:266,:229,:356,:139,:624,:639 | match ×1、obligation ×4、recall ×4、judge ×4、anomalies ×4、evaluate_file ×24、policy evaluate ×24、_persist @:560 ×4、get_status ×12、list_matches ×8；search_materials_loose（card_service @:559）×18 |

### 入口 B：tools/dd_v1_local_run.py（本地 Agent 评分入口，adapter=manual，零模型零费用）

命令（材料=仓库内 fixture 原路径；`sem._inside(material_root, backend/tests/fixtures)` 为真 → 自动免 `--allow-real-material`，trace 中 `_inside @:336` ×2 + `_read_only_check` ×8 通过即证）：
```bash
cd /Users/mac/cangjie-fos-wt-a0/backend && env -u ALL_PROXY ... \
  CANGJIE_DD_V1_DATA_DIR=/tmp/a0-evidence-attachment/plane-B \
  .venv/bin/python <a0-evidence>/a0-trace-runner.py --trace-out calltrace-entryB.jsonl -- \
  /Users/mac/cangjie-fos-wt-a0/tools/dd_v1_local_run.py run \
  --material-root /Users/mac/cangjie-fos-wt-a0/backend/tests/fixtures/dd_v1_fos71_wp04/snapshot \
  --meta /Users/mac/cangjie-fos-wt-a0/backend/tests/fixtures/dd_v1_fos71_wp04/meta.json \
  --items /Users/mac/cangjie-fos-wt-a0/backend/tests/fixtures/dd_v1_fos71_wp04/raw_items.json \
  --out /tmp/a0-evidence-attachment/entryB --adapter manual
```
- **exit 2**——这是设计信号：`dd_v1_local_run.py:146` `return 0 if any(s.get("mode") == "AGENT_SUGGESTION" ...) else 2`，即「本轮没有任何一条拿到模型建议」。**不是崩溃，是真实降级的可观测退出码。**（run_id `20261021T151503-p46492`；stderr 0 字节。）
- 逐条输出（`entryB-run-stdout.log`）：
  - R1/R2/R4：`adapter_status=PENDING_MANUAL`、`mode=RULE_ONLY`、`degrade_reason=AGENT_CALL_FAILED:PENDING_MANUAL:PASTE_MODEL_REPLY_TO:.../reply.json`
  - R3（含糊条目「其他相关材料等」）：`status=NEEDS_HUMAN_SPLIT`——**拆不出义务就不调用模型**（`dd_v1_local_run.py:117`），零浪费。
- run_record 三层证据（`entryB-outputs/entryB/run-R1/run_record.json`）：`schema_version=dd_v1_agent_result.v1`、`source_snapshot_id=snap-ec8e949e8d0531dc`、`adapter.role=MANUAL`、R4/语义两层校验 `mode=RULE_ONLY`、`authoritative_validation=semantic_validation`、`rule_hints={"R1-O1":{"verdict":"MATCH","files":["G001","G002"]}}` 且明注「规则提示不是 Gold」。
- 计数口径（M3）：`run_summary.json` 的 **`calls_total=3`** = adapter 尝试次数（3 组 × `calls_used:1`，见 run-R1/R2/R4 的 `run_record.json`）；**`external_model_calls=0`**——adapter 为 manual（人工回贴占位），模型从未被调用，零费用。
- trace 实调：`dd_v1_semantic_retrieval_service.run_semantic @280 / build_semantic_packet @174 / retrieve_minimal_evidence @136 / validate_semantic @257 / local_material_snapshot @309 / _inside @336 / split_items @82 / rule_hint @157`；`dd_v1_agent_adapters.run_agent @350 / ManualExchangeAdapter.run @222 / _prompt_for @118`；`dd_v1_agent_result_service.validate_agent_output @212 / _rule_only @136（显式降级构造器）/ sha256_file @43`（×24 = 3 次 load_snapshot × 8 文件，M4）。

### 模型真实性口径（验收第 6 条）

本轮**没有任何真实模型调用**（未跑 `--adapter deepseek-harness`，未给 `--allow-local-dsh`）。因此：
- 只声明「**Adapter 契约已测**」（manual 路径 + RULE_ONLY 降级 + NEEDS_HUMAN_SPLIT + exit 码语义）；
- **不声明**「模型已参与语义判断」；`semantic_validation.mode` 实测值为 `RULE_ONLY`（AGENT_SUGGESTION 仅在 rule_hints 对照层出现过，与模型无关）。
- 若司仓认定「dsh 真实降级（余额不足）」必须实跑一次才算证据：需先授权（涉及余额消耗尝试），A0 未自行执行——按任务书硬禁止 3 停下并在 result.json notes 请求授权。

### MATCHED 缺口（N6 补记）

本轮两入口**从未产出 MATCHED**：入口 A = 3 CONFLICT + 1 MISSING，入口 B = 3×RULE_ONLY + 1×NEEDS_HUMAN_SPLIT。「正常/MATCH 路径未被本 fixture 覆盖」——R1 的 `rule_hints` 层虽给出 `MATCH G001+G002`，但那是规则提示对照层，不是判定层输出。A1/A2 需另补 MATCH 路径的覆盖（如：单主体单版本干净 fixture 或补登记权威主体名单后重跑）。

## 3. 三个旧模块角色判定（逐条 file:line 证据，非抄审计 PDF）

| 模块 | 当前正式入口是否实际走到（证据） | 角色 | 能否证明「全部齐套」 |
|---|---|---|---|
| `dd_v1_match_service.py` | **走到**。入口 A trace：match_library→judge @428 被调 4 次（每义务 1 次）；`_print_verdicts`/`_write_reports` 直接 import（`dd_team_channel.py:88-92,199,211`） | DD-V1 规则匹配/四维判定层，Team Channel 的正式判定引擎 | 部分：四维（主体/期间/类型/附件）+STALE/CONFLICT/RESTRICTED（:487-539）。附件维可观察（needs_attachments→related_files，:473-479）。**签章维不能证明**：`evaluate_file` 注释自认「认知卡里 seal_status 恒 UNKNOWN → 必然不满足，属已知缺口」（:174-177；本轮 sqlite 实测 seal_status 8/8 空串）。**数量权威不存在**：judge 无任何「应有 N 份」输入，FULL_COVERAGE 只做覆盖比例——9/31 类齐套无从判定 |
| `dd_v1_semantic_retrieval_service.py` | **走到**（仅入口 B）。trace：run_semantic @280 全链被调；入口 A 不 import 它（`dd_team_channel.py` 的 import 清单里没有） | WP04 语义包/最小证据检索/两层校验（R4 结构层+语义层），供 Agent 适配层调用 | 部分：包内有 locator/版本/主体硬校验（`validate_semantic` @257 + `agent_result_service._check` @160-208），但同样**没有数量权威**；齐套语义是「包内证据 vs 单义务」，不是「机构清单全集」 |
| `dd_match_service.py`（旧） | **不走**。两入口均不 import；trace（A+B 全量 3661 call 事件）0 命中。引用面=旧 Web/API 链：`api/routes/dd_response.py:21,139,638,645`、`api/routes/assets.py:351`、`package_gap_service.py:22`、`package_synthesis_service.py:56` | 旧 v0.7 尽调响应台的 Web 会话匹配引擎（`run_matching` @93，`model="deepseek-chat"` @945/1078 走 `dd_llm_client`），与 #71 新链并行存在 | 不能。本轮零调用；其判定模型是 LLM 会话式（非本链），且无人工批准闸（人工闸在新链 `dd_v1_package_service`） |

「全部齐套」三态结论：**能证明**=单义务四维覆盖/冲突/过期/受限；**不能证明**=签章（已知缺口）、应有份数（无数量权威）；**仅假设**=「语义包完整性等价于清单齐套」（无任何代码支持，UNKNOWN）。

## 4. 临时脚本 vs 官方 FOS 路径差异（仅从 FOS 侧论证）

本轮**未接触** exam2 四脚本（不在本仓，硬禁止 2）。差异只以 FOS 侧可证事实陈述：

| 维度 | 官方 FOS 路径（本轮实测） | 临时脚本（按报告主张反推的必要差异） |
|---|---|---|
| 调用链 | 入口 CLI→dd_v1 五服务→判定/组包，trace 可逐帧核对（本轮 3142+519 事件） | 无 FOS import/call → call_trace 为空 |
| 检索 | dd_v1_card FTS/bigram + `retrieve_minimal_evidence`（同主体同类型过滤、EFFECTIVE 优先、≤6 份/义务、300 字摘录、只读+路径越界拒绝） | 自带检索（如 BM25），不经过 FOS 快照/权限层 |
| 校验 | 两层校验（结构 R4 + 语义）+ 披露策略 + 人工批准闸 + 降级显式记录（RULE_ONLY/degrade_reason/exit 2） | 无 FOS 校验与闸；分数直接出自脚本 |
| 组包 | `package_approved` @385：先 assert_approval 后复制，按机构编号建目录，非 deliverable 进 blocked，越界兜底 | 自带组包，无审批/hash 契约 |
| 结果 | run_id/snapshot_id/SHA256/prompt_version 全程留证 | 57.14% 无法归因到任何 FOS 能力 |

推论（HG-02 视角）：FOS call_trace 为空时，任何分数都**无法评估 FOS**——不是 FOS 得了 57 分，而是 FOS 根本没上场。旧 57.14%（NON_BLIND）只能当临时脚本观察值。

## 5. 复用检索回执（合同 §6）

- 检索：bog-global-skills（本地库）按 name/description 过滤 → 候选 3（cangjie-fos-project、independent-acceptance-review、continuity-audit-cangjie-gm）→ 实读 2（cangjie-fos-project 速查卡；independent-acceptance-review 验收法）。
- 实际复用：cangjie-fos-project 的项目结构/测试命令/坑位（其「605 passed」确认过时，本轮以实跑 1419 为准）；independent-acceptance-review 的「幽灵命令两步查证法+退出码贴原文」纪律（本轮所有退出码实贴）。
- continuity-audit-cangjie-gm 命中未读（本轮无 GM 运行态审计需求，控制在 3 项以内）。
- 新候选：本轮踩坑（uv.lock 副作用/管道吞退出码/pytest9 无计数行/manual adapter 作零费降级；attempt-3 新增：trace 观察器的追加模式与退出码陷阱）→ 见 result.json notes，供 Skills 复盘归档。

## 6. 产物清单（均未 commit，未 push）

```
docs/dd-v1-fos71/wp05-real-integration/
  A0-BASELINE-TRACE.md      ← 本文（attempt-3 整改版）
  A0-REUSE-MATRIX.md        ← 复用矩阵 + 最小 Adapter 契约
  A0-CALL-TRACE.md          ← 两入口调用图摘要（attempt-3 修正版）
  a0-evidence/
    a0-trace-runner.py      ← 纯观察 trace 工具（attempt-3 修复：分段+真实退出码；本身是本轮唯一新代码，位于 docs/，非产品代码）
    a0-synthetic-checklist.tsv（fixture R1-R4 逐字派生）
    calltrace-entryA.jsonl（3144 行 = 1 meta + 3142 call + 1 done，exit 0，单次运行）
    calltrace-entryB.jsonl（521 行 = 1 meta + 519 call + 1 done，exit 2，单次运行）
    entryA-run-stdout.log / entryA-run-stderr.log
    entryB-run-stdout.log / entryB-run-stderr.log
    entryA-reports/（报告.md + 结果.json，20261021-231454 本轮新产物）
    entryB-outputs/entryB/（run-R1/R2/R4 + run_summary.json）
    pytest-clean-junit.xml / pytest-proxy-junit.xml
    SHA256SUMS-a0-evidence.txt（attempt-3 全量重算）
```

`shasum -c a0-evidence/SHA256SUMS-a0-evidence.txt` → 全部 OK（attempt-3 重建后核验）。

## 7. 9 项硬 Gate 现状（A0 结束时如实更新，不虚标）

| Gate | 状态 | A0 相关证据/说明 |
|---|---|---|
| ONE_WRITER | UNKNOWN | 本轮在隔离 worktree 只写 docs/；GM Lease/单主现场核验不属 A0 权限（司仓侧） |
| REAL_FOS_CALL | UNKNOWN→**A0 合成证据已交**（升 PASS 需独立 Reviewer 按验收 2 判） | 两入口共 3661 个 FOS 调用事件、函数+行号+顺序+产物，全部可复核 |
| GOLD_ISOLATION | UNKNOWN（合成侧满足） | fixture `find -iname "*gold*"` 零命中；入口 B 未接 Gold 参数；未触碰任何 Gold/客户原件 |
| SENSITIVE_AUTH | UNKNOWN | 本轮零外发：`sent_to_institution=false`；零模型调用=零外传面 |
| FALSE_MATCH_GUARD | UNKNOWN（合成侧可观察） | R3 含糊→NEEDS_HUMAN_SPLIT 不硬判；R4 不存在→MISSING；DRAFT/SUPERSEDED→CONFLICT/OUTDATED 路径存在。另：**跨主体假冲突**（entity 空 → ("",period) 混桶）为本轮实测发现的 FOS 真实行为，A2/A3 必须先修 |
| PRECISE_PACKAGING | UNKNOWN | 本轮未组包（dry-run 默认）；`package_approved` 闸先于复制（:388）仅代码级证据 |
| INDEPENDENT_REVIEW | UNKNOWN | 本单自报 completed ≠ PASS；待独立 Reviewer（attempt-2 曾 FAIL，attempt-3 已按整改单逐条修订，仍待复验） |
| WINDOWS_REAL_E2E | UNKNOWN | 完全未涉及 |
| UNATTENDED_HANDOFF | UNKNOWN | 完全未涉及（本轮无 cron/守护） |

## 8. 双进度条（A0 结束时）

- 工程进度：**0/6**（A0 未被独立 Reviewer PASS 前，本单自报不改变分母）
- 终局效果：**0/100**，五项全 UNKNOWN。A0 为 O1_REAL_FOS_CHAIN 提供的是「独立案例覆盖率证据」：合成 fixture × 2 正式入口 × 3661 FOS 调用事件（REAL_PASS 前不计分）。
