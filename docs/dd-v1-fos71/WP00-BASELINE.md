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
| WP2 解析 | `dd_v1_parser_service.extract_content / parse_pending_batch`（可选 Docling） | 零 LLM | 文件头「复用优先…可降级」 |
| WP2 认知卡 + FTS | `dd_v1_card_service.build_card / search_materials`（FTS5 + bigram） | 零 LLM | 第 332、505–506 行 |
| WP3 需求拆解 | `dd_v1_requirement_service.parse_entity_scope / parse_period / parse_doc_type` | 零 LLM | 第 24 行「纯确定性，零 LLM」 |
| WP3 匹配 | `dd_v1_match_service.evaluate_file / match_obligation / judge / match_library` | 零 LLM | 第 145 行「确定性，不含 LLM」 |
| WP7 披露策略 | `dd_v1_policy_service.load_policy / evaluate` | 零 LLM | 文件头 |
| WP4 审核与组包 | `dd_v1_package_service.build_review_pack / approve / assert_approval / package_approved`（HG1：没有人工批准就不复制） | 零 LLM | 文件头 |
| WP5 经验与评分 | `dd_v1_experience_service.record_feedback / promote / recall_experience / add_regression_case` | 零 LLM（「不接受 LLM 自评」第 406 行） | 文件头 |
| 团队入口 | `tools/dd_team_channel.py` | 不依赖 LLM key（第 10 行） | — |

**结论（CURRENT）**：新版 DD-V1 整条链都是确定性的，**没有任何模型语义参与**。#71 要加的是模型语义层，不是替换掉这些确定性模块。

## S · State
- 工程账：WP00 文档已交付（本 PR）；WP01–WP07 = 0/7。
- 效果账：G01–G08 已验证 = 0；G07 部分有证据（单 writer 交接，见 GM #214）。
- next_action：WP01 Spike（见 WP00-RISKS-AND-WP01-PLAN.md）。

## E / G
证据见 `EVIDENCE-WP00.md`。Gate：独立 Reviewer 复核本 PR，不自报 PASS。
