# WP00 · BASELINE（cangjie-fos#71 接管与事实底座）

- contract_version: 3.8｜task_level: L1（L2 仅适用于执行器互斥）｜work_id: DD-V1-FOS71｜CURRENT_CHILD: WP00
- collected_at: 2026-10-16 13:40 CST｜code_version: master `a6bf515`｜作者：司仓（Grok 替补执行器，见 EVIDENCE-WP00.md §执行器）
- 标记规则：CURRENT = 本次实测；HISTORICAL = 历史记录；INFERRED = 推断；UNKNOWN = 证据不足

## G · Goal（引用 Issue #71 §0，这里不复述）
北极星：Codex / DeepSeek Harness 的大模型做语义判断，FOS 负责索引、权限、硬校验、人工审核和留痕。WP00 本身不改变用户可观察能力，只建立事实底座。

## C · Context
| # | 事实 | 标记 | 来源 |
|---|---|---|---|
| 1 | FOS master = `a6bf515`（#70），open PR = 0 | CURRENT | `git log -1`（box clone，13:15 CST） |
| 2 | 旧 DD-V1 WP0–WP5 已合入 `1bd2383`（#66），WP7 已合入 `c0cb7a4`（#68），台账修复 #69 `8b5a878`、#70 `a6bf515` | CURRENT | `git log --oneline -3`；GM 状态卡 12:40 |
| 3 | 旧 WP6 BLOCKED_ON_INPUT：等 teams-channel #74 Gold Set、#75 披露政策（都是 open） | HISTORICAL（12:40 采集） | STATUS-CARD-20261016 |
| 4 | GM 里没有 live work item；#71 只有文档登记（cangjie-gm PR #214，MANUAL_ONLY） | CURRENT | cangjie-gm main `529e99a` work_items 搜索 0 命中；PR #214 |
| 5 | DD-V1 回归：`pytest tests/test_dd_v1_*.py` → **160 passed / 1 failed**。失败的是 `test_absent_docling_is_detected`，原因是本次环境用 `uv sync --all-extras` 装了 docling，属于环境假失败，不是代码回归 | CURRENT | EVIDENCE-WP00.md §命令 |
| 6 | 业务效果分：NOT_SCORABLE（没有 Gold Set） | CURRENT | Issue #71 G03 |

## C · Capability：DD-V1 流水线（代码核实）
| 阶段 | 模块 / 关键函数 | 是否用 LLM | 证据 |
|---|---|---|---|
| WP1 材料 Manifest | `dd_v1_manifest_service.register_library / iter_version_hints`；CLI `tools/dd_v1_manifest.py` | 零 LLM | 文件头第 21 行「本层零 LLM 调用」 |
| WP2 解析 | `dd_v1_parser_service.extract_content / parse_pending_batch`（可选 Docling） | 零 LLM | `rg -n "openai|dd_llm_client|deepseek|anthropic|chat\.completions|httpx|requests|LLM|llm" backend/src/cangjie_fos/services/dd_v1_parser_service.py` → exit 1（0 命中） |
| WP2 认知卡 + FTS | `dd_v1_card_service.build_card / search_materials`（FTS5 + bigram） | 零 LLM | 第 332、505–506 行 |
| WP3 需求拆解 | `dd_v1_requirement_service.parse_entity_scope / parse_period / parse_doc_type` | 零 LLM | 第 24 行「纯确定性，零 LLM」 |
| WP3 匹配 | `dd_v1_match_service.evaluate_file / match_obligation / judge / match_library` | 零 LLM | 第 145 行「确定性，不含 LLM」 |
| WP7 披露策略 | `dd_v1_policy_service.load_policy / evaluate` | 零 LLM | `rg -n "openai|dd_llm_client|deepseek|anthropic|chat\.completions|httpx|requests|LLM|llm" backend/src/cangjie_fos/services/dd_v1_policy_service.py` → exit 1（0 命中） |
| WP4 审核与组包 | `dd_v1_package_service.build_review_pack / approve / assert_approval / package_approved`（HG1：没有人工批准就不复制） | 零 LLM | `rg -n "openai|dd_llm_client|deepseek|anthropic|chat\.completions|httpx|requests|LLM|llm" backend/src/cangjie_fos/services/dd_v1_package_service.py` → exit 1（0 命中） |
| WP5 经验与评分 | `dd_v1_experience_service.record_feedback / promote / recall_experience / add_regression_case` | 零 LLM（「不接受 LLM 自评」第 406 行） | 文件头 |
| 团队入口 | `tools/dd_team_channel.py` | 不依赖 LLM key（第 10 行） | — |

**结论（CURRENT）**：新版 DD-V1 整条链都是确定性的，**没有任何模型语义参与**。#71 要加的是模型语义层，不是替换掉这些确定性模块。

## C · 补充核对（独立复核 N1，2026-10-16 CST）
| # | 核对项 | 结果 | 标记 | 来源 |
|---|---|---|---|---|
| 7 | cangjie-gm main HEAD | `529e99a` | CURRENT | `git fetch && git log -1 origin/main`（box clone） |
| 8 | ADR-0009（GM Loop V1）D1：唯一状态源 `data/work_items.json`；D3/D4：inbox `data/inbox/<task_id>/task.json / question / decision / result.json` 契约 | #71 **未**写入 work_items.json、**未**建 inbox task（生产控制器 557/8395 会派发 READY 包 → 双主风险）；登记以文档形式落在 GM PR #214（dispatch_marker=MANUAL_ONLY / NOT_IN_LIVE_WORK_ITEMS）。与 ADR-0009「不另建第二真相源」一致：本登记不是状态源，只是交接证据 | CURRENT | `git show origin/main:adr/ADR-0009-gm-loop-v1.md`；GM #214 |
| 9 | ADR-0010（运行态所有权）D1/D2：运行态字段只能由代码派生、AI 不得手写 | 本 PR 没有手写任何 GM 运行态字段（current_state / current_wp / evidence）；#71 状态只在 FOS PR 与 GM 文档里叙述 | CURRENT | `git show origin/main:adr/ADR-0010-runtime-state-ownership.md` |
| 10 | Lease / ACK | GM 没有 #71 的 live lease（未进 work_items），因此**没有机器 lease**；替代的互斥证据：① GM #214 登记 v2 + 替补记录（commit `a1aaf2f`）；② #71 comment 6208928483 登记 Grok（司仓）为唯一 writer；③ 每次执行器运行前 `ps` 核查同分支无其他 writer（cangjie-gm#215 教训）；④ runtime-state.sqlite 只读核查 mvs_575c idle、locks=0。ACK = 上述 comment，**不是**机器 ACK。机器 lease = UNKNOWN/NOT_APPLICABLE，作为 G07 已知缺口 | CURRENT（机器 lease：UNKNOWN） | EVIDENCE-WP00.md；GM #214 |
| 11 | FOS CI（PR #72 head `ffb7870`） | GitHub Actions：push + pull_request 两次运行均 `completed/success`（Backend Tests 440+、Backend Tests 228、Frontend Build Check 全绿）；master `a6bf515` 同为 success | CURRENT | `curl api.github.com/repos/bog5d/cangjie-fos/commits/ffb7870/check-runs`、`/actions/runs?branch=feat/71-wp00` |
| 12 | docling 非封闭测试 | 已开 cangjie-fos#73 跟踪（只改测试夹具，不在 #71 范围） | CURRENT | — |

## S · State
- 工程账：WP00 文档已交付（本 PR）；WP01–WP07 = 0/7。
- 效果账：G01–G08 已验证 = 0；G07 部分有证据（单 writer 交接，见 GM #214）。
- next_action：WP01 Spike（见 WP00-RISKS-AND-WP01-PLAN.md）。

## E / G
证据见 `EVIDENCE-WP00.md`。Gate：独立 Reviewer 复核本 PR，不自报 PASS。
