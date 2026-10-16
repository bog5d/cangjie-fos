# WP02 · Goal Contract / Spec 冻结（cangjie-fos#71）

contract_version 3.8｜task_level L1｜机读合同：`GOAL-CONTRACT-WP02.json`（`check_gccseg.py --require-v3-8` → PASS）
作者：司仓（#71 唯一 writer）｜2026-10-16 CST｜基于 `feat/71-wp01` `9c1f9bc`｜**待独立复核**
target_goal_ids：FOS71-G08（双账）、为 G01/G03/G04 冻结量纲

## INTENT
北极星见合同 `goal_alignment.north_star`。一句话：模型负责语义判断，FOS 负责索引、权限和硬校验，人负责审核；用同一份人工 Gold Set 给几个考生打分。

## REQUIREMENTS（引用 #71 R1–R9，不复述；本 WP 冻结的增量）
| # | 冻结内容 |
|---|---|
| R2 | Adapter 契约 = `dd_v1_agent_result.v1`（schema 文件 + `dd_v1_agent_result_service`）。一个 Adapter 只负责「任务包 → 原始文本 → `validate_agent_output`」，不得绕过校验器写结果 |
| R4 | 字段集冻结为 `RESULT_FIELDS` / `CANDIDATE_FIELDS`（代码常量 = schema `required`，有测试锁定）。改字段 → 升 `v2`，旧版继续可读 |
| R5 | 降级码冻结：`AGENT_CALL_FAILED:*`、`EMPTY_OUTPUT`、`INVALID_JSON:*`、`NO_RESULTS_ARRAY`、`UNKNOWN_TOP_LEVEL_FIELDS:*`、`ALL_RESULTS_REJECTED`；部分覆盖 = `INCOMPLETE_COVERAGE:*` |
| R6 | 考生定义见下表；**不改 #71 的考生定义** |

## 考生与候选（R6）
| ID | 定义 | 运行器 | 状态 | 是否出分 |
|---|---|---|---|---|
| CONTROL_RULE_ONLY | 现有确定性 DD-V1 | `tools/dd_team_channel.py` | CURRENT | 是（对照组） |
| EXAMINEE_1 | Codex 不用 DD-V1，独立组包 | `codex exec -s read-only` | CLI_READY（WP01 跑的是考生2 形态，考生1 形态未跑） | 是 |
| EXAMINEE_2 | Codex 语义驱动 DD-V1 | `codex exec --output-schema` | TASK_EXECUTED（合成） | 是 |
| EXAMINEE_3 | DeepSeek Harness 语义驱动 DD-V1 | dsh | **UNAVAILABLE / BLOCKED_ON_CHAIRMAN**；不购买 | 否，报告写 BLOCKED |
| AUX_MINIMAX | MiniMax 语义驱动 DD-V1 | `pi -p --no-tools --mode json` / `hermes chat -Q` | TASK_EXECUTED（合成） | **辅助路径**，也是考生3 的候选替补；合同字段 `scored:false, ranked:false`；董事长批准前单列，不算考生3 |

## NON_GOALS
见合同 `goal.non_goals`。另：WP02 不写 Adapter 代码、不跑任何模型、不建 Gold。

## OPEN_QUESTIONS（需要董事长/业务方裁决）
| # | 问题 | 选项 | 默认 |
|---|---|---|---|
| OQ-1 | 考生3 | a 恢复 dsh 额度（花钱，需批准）；b 用 AUX_MINIMAX 正式替补考生3（改定义，需批准）；c 考生3 缺席，报告写 BLOCKED | **c**，直到裁决 |
| OQ-2 | Gold Set 由谁、用哪批历史清单+资料快照建立；访问控制 | 业务 Owner 指定 | 没有 Gold Set 就 NOT_SCORABLE |
| OQ-3 | 能否把脱敏后的真实材料送 Codex/MiniMax 云端 | 需业务/安全书面授权 | 只用合成/授权脱敏 fixture |
| OQ-4 | Windows 实跑人选与时间 | 业务指定 | WP06 前 UNKNOWN |

## SPEC
1. **任务包**：`build_task_packet`，包含快照 id、义务、文件元数据和不可信摘录（默认 400 字）。版本由 `schema_version` + `prompt_version` 标识。
2. **受控 Prompt 版本**：`fos71-wp01-p1`（`dd_v1_agent_result_service.PROMPT_VERSION`，正文在 `build_task_packet.instructions`）。改任何措辞都要升 `-p2`，旧答卷保留原版本号，评分时按版本分组。runner 包装语（WP01 `raw/codex-prompt.txt`、MiniMax 内嵌 schema 版）在 WP03 收进 Adapter，用同一版本号管理。
3. **受控 Schema 版本**：`dd_v1_agent_result.v1`（`dd_v1_agent_result.v1.schema.json`）。Codex 用 `--output-schema` 强约束；MiniMax 把 schema 内嵌在 prompt 里。两者都必须过 Python 校验器。
4. **校验（硬 Gate，确定性）**：快照成员、路径、sha256；主体/期间与判定一致；未知字段；弃答不能带候选；不能有重复义务；item_id 必须一致；覆盖率；禁止 approved/deliverable；接受的条目一律 `review_required`。
5. **后续接入**：被接受的建议交给既有 `match_service.judge` → `policy.evaluate` → `package`（HG1 人工批准）。WP03/04 只追加，不修改这些模块。
6. **执行约束**（来自 WP01 挂起诊断）：`stdin=/dev/null`、硬超时、事件流日志、无工具或白名单工具、隔离目录、不在会话里用 `nohup &`。

## ACCEPTANCE / HARD GATES（评估量纲，WP05 使用）
| Gate | 指标 | 判定 |
|---|---|---|
| HG-SCORE | 逐原始条目/原子义务：TP/FP/FN；precision/recall（分母适用时）；按主体/期间/有效版本/附件/**证明原件**/真正缺失/**无法核实**七个维度拆分；错主体、错年度、自信错配（confidence ≥0.8 且错误）单列；「有附件覆盖」与「正确匹配」分开统计；每个错误归类为 RULE_DEFECT / MODEL_REASONING_DEFECT / RECALL_DEFECT / MATERIAL_MISSING，并链接证据 | 没有 Gold Set → NOT_SCORABLE；n<30 条义务 → LOW_CONFIDENCE。**所有数值以合同 `scoring_rules`（fos71-scoring-v1）为准** |
| HG-COST | 耗时（timing.json）、token（事件流或 UNKNOWN）、实际费用（订阅内记 0 或 UNKNOWN）、人工审核/修正分钟 | 必须有日志支撑，不接受自报 |
| HG-STAB | 同卷重跑 ≥3 次（`scoring_rules.min_reruns`），判定一致率 | Gold 出现前只报告、不设阈值；**阈值是 WP05 开工前必须定的事项（open_items WP05-PRE-1，复核 N5）** |
| HG-NEG（G04） | 错主体、伪造文件/路径/hash、prompt injection、未授权外发 4 类负例 | 每类至少 1 条确定性测试和 1 次真实模型演练；任何一条漏过 = FAIL |
| HG-RULE（G05） | `pytest tests/test_dd_v1_*.py` 全绿；模型失败时降级码正确 | 回归减少 = FAIL |
| HG-ISOL（G03） | Gold 不进仓库、不进考生工作目录，**也不得放在执行器主机任何可读位置**（`-s read-only` 只限制写，模型仍能读整台主机；复核 WP03 N4）；三考生用同一快照 id；人工交换回贴不计为考生答卷 | 违反 = 成绩作废 |
| HG-WRITER（G07） | 每个 WP 开工前做 ps/分支核查 | 有双写 = PAUSE |
| HG-DUAL（G08） | 每个报告都列工程%和效果分 | 混报 = FAIL |

## ARCHITECTURE
沿用 #71 §4。新增位置：Kernel = `dd_v1_agent_result_service`（契约和校验）；Adapter（WP03）= `services/dd_v1_agent_adapters/{codex,minimax,manual}.py`，都输出原始文本，供应商名只出现在 Adapter 里；Department Pack = 义务模板（WP04）。

## PROJECT_ROADMAP / PLAN / TASKS
| WP | target | 交付 | 依赖 |
|---|---|---|---|
| WP03 | G01、G05 | Codex / MiniMax（候选）/ 人工交换三个 Adapter + 超时/降级 + 日志，都用合成 fixture | WP02 复核 |
| WP04 | G04 | 义务拆分 + FTS 候选 → 任务包；4 类负例真实演练 | WP03 |
| WP05 | G03 | 同卷考试 runner + 评分器（Gold 文件路径由外部注入，运行器读不到）+ 报告 | WP04；Gold = OQ-2 |
| WP06 | G06、G04 | 对抗复核 + Windows 真人实跑 | WP05；OQ-4 |
| WP07 | G05、G08 | 经验沉淀与交接 | WP06 |

## 双账
- 工程：WP00、WP01 已完成并经独立复核 = 2/8 = 25%（WP02 本身待复核，不计）。与合同 `progress.completed_reviewed_wps` 一致，有测试锁定
- 效果：0/100。WP01 只在合成 fixture 上验证，不计业务分；baseline 为 UNKNOWN
