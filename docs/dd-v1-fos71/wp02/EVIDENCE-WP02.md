# EVIDENCE · WP02（cangjie-fos#71）

subject_id: DD-V1-FOS71/WP02｜collected_at 2026-10-16 14:20–14:30 CST｜base `feat/71-wp01` `9c1f9bc`｜作者：司仓（#71 唯一 writer）｜**自查，不是独立复核**
target_goal_ids: FOS71-G08（主），并为 G01/G03/G04 冻结量纲

## 单 writer 核查
| 时间 | 命令 | exit | 观察 |
|---|---|---|---|
| 14:13 / 14:22 | Mac `ps -axo pid,etime,command \| grep -E "(pi\|codex exec\|hermes chat\|run-wp)"` | 0 | 0 个匹配进程 |
| 14:22 | `git fetch && git branch -r` | 0 | 只有 `feat/71-wp00`、`feat/71-wp01`（head `9c1f9bc`，司仓提交）；`feat/71-wp02` 不存在 |

## 命令与退出码
| 命令 | exit | 结果 |
|---|---|---|
| `git clone --depth 1 https://github.com/bog5d/grill-to-spec.git`（main `d14327c`） | 0 | — |
| `python3 <grill-to-spec>/scripts/check_gccseg.py --require-v3-8 docs/dd-v1-fos71/wp02/GOAL-CONTRACT-WP02.json` | 0 | `PASS: GCCSEG structural + goal alignment contract`（只是结构检查，不代表语义验收） |
| `cd backend && .venv/bin/python -m pytest tests/test_dd_v1_*.py -o addopts=""` | 0 | **200 passed**（WP01 196 + 合同一致性 4） |

## 本 WP 没做的事
没有调用任何模型，没有写 Adapter，没有读或建 Gold Set，没有花费，没有新 key，没有动 master、生产控制器或 work_items.json。考生3 保持 UNAVAILABLE；MiniMax 只登记为辅助路径和替补候选（OQ-1 待董事长裁决）。

## 工件
`GOAL-CONTRACT-WP02.json`、`SPEC-WP02.md`、`backend/tests/test_dd_v1_fos71_contract.py`；sha256 见 `SHA256SUMS`（在仓库根目录执行 `sha256sum -c docs/dd-v1-fos71/wp02/SHA256SUMS`）。

## 独立复核修正（REVIEW-WP02 PASS_WITH_NOTES，2026-10-16 14:28–14:35 CST）
单 writer 核查：14:27 Mac `ps` 没有 pi/codex exec/hermes chat/run-wp 进程；远端 `feat/71-wp02` head `38c1e03`（司仓提交）。

| Note | 修正 | 测试 |
|---|---|---|
| N1 | 合同新增 `scoring_rules`（fos71-scoring-v1）：`low_confidence_min_obligations=30`、`min_reruns=3`、`high_confidence_threshold=0.8`、NOT_SCORABLE、单列项、覆盖与正确分开统计；`gate.acceptance_criteria` 规定 WP05 评分器必须引用它 | `test_n1_scoring_rules_are_machine_readable` |
| N2 | `progress.completed_reviewed_wps=[WP00,WP01]`、`total_wps=8`，测试锁定 `engineering_percent = round(100*2/8)`；JSON note 与 SPEC 措辞统一为「WP00、WP01 已完成并经独立复核 = 2/8 = 25%」 | `test_n2_engineering_percent_locked_to_reviewed_wps`（把百分比改成 90 会失败） |
| N3 | 七个维度（含 proof_original、unverifiable）和四类错误（RULE_DEFECT / MODEL_REASONING_DEFECT / RECALL_DEFECT / MATERIAL_MISSING）写进 `scoring_rules`、user_visible_acceptance 和 SPEC HG-SCORE | `test_n3_r7_dimensions_and_error_categories` |
| N4 | 每个候选增加结构化字段 `vendor / uses_dd_v1 / scored / ranked`；AUX_MINIMAX 为 `scored:false, ranked:false`；EXAMINEE_3 `score_status=BLOCKED` | `test_n4_structured_examinee_fields`（同时断言考生 1、2） |
| N5 | 记为 `open_items` WP05-PRE-1（WP05 开工前确定重跑一致率阈值），`rerun_agreement_threshold=null` | `test_n5_rerun_threshold_is_open_item_not_silently_set` |

| 命令 | exit | 结果 |
|---|---|---|
| `check_gccseg.py --require-v3-8 GOAL-CONTRACT-WP02.json` | 0 | PASS |
| `pytest tests/test_dd_v1_*.py -o addopts=""` | 0 | **205 passed** |
