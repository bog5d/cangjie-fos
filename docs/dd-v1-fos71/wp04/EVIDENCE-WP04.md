# EVIDENCE · WP04 语义理解 + 检索判断（cangjie-fos#71，L1）

- writer：司仓（Grok），#71 唯一登记 writer；分支 `feat/71-wp04` 叠在 `feat/71-wp03`（`8635d39`）上
- target_goal_ids：G02（模型介入的匿名 fixture 闭环）、G04（主体/年度/版本/附件/路径/hash 不被 LLM 跳过）、G05（失败降级）、G08（双账）
- 默认前提（OQ-1/OQ-2 未裁定）：考生 3 = DeepSeek Harness，BLOCKED；MiniMax 只做辅助；没有 Gold → NOT_SCORABLE；只用合成材料
- 时间均为 CST（UTC+8）

## 是否依赖 OQ-1/OQ-2
WP04 的交付（拆条目、检索、语义校验）是确定性代码，用合成 fixture 就能验证，**不依赖** Gold 或真实材料。依赖它们的两处做成 BLOCKED 桩：
| 桩 | 行为 | 阻塞原因 |
|---|---|---|
| `score_against_gold()` | 固定返回 `NOT_SCORABLE`、`scores=None` | OQ-2：Gold Set 未提供 |
| `load_real_material()` | 抛 `Blocked` | OQ-3：真实材料送外部模型未授权 |
| 考生 3 | `DeepSeekHarnessAdapter` 仍是 UNAVAILABLE，不起进程 | OQ-1 |

## 交付（代码 `3209240`，测试/fixture `fa13114`/`bed0107`/`0d67b55`）
| 能力（#71 WP04） | 实现 | 位置 |
|---|---|---|
| 拆条目 | 按「及/和/、/；」拆成原子义务；从文本识别文档类型（7 类字典 + 别名）、期间（`20xx年`；营业执照/章程/「最新」→ CURRENT）、「（含附注）」→ `required_parts=[正文,附注]`。**拆不出文档类型的条目不猜**，标 `NEEDS_HUMAN_SPLIT`；同一段出现两种文档类型也不猜 | `split_item / split_items` |
| 只读最小证据检索（承接 WP03 复核 N4） | 每条义务只取**同主体 + 同文档类型**文件（≤6 个），按「同期间、有效版本优先」稳定排序；每个文件只给命中行摘录（≤300 字）+ 行号 locator + sha256 + part/version_status。`rb` 只读打开，`resolve()` 后必须在快照目录内，否则 `PermissionError`。别的主体、别的文档类型（含注入备忘 G008）模型**根本看不到** | `retrieve_minimal_evidence` |
| 主体/年/版本/多文件附件判定 + 解释 + 弃答 | 语义包要求：草稿/被取代只能 OUTDATED；附件不全只能 PARTIAL；locator 照抄证据；match_reason 写依据；空证据 MISSING/UNCERTAIN + abstain_reason | `build_semantic_packet`（prompt `fos71-wp04-p1`） |
| 确定性语义校验（R4 校验之后再加一层） | `NOT_IN_RETRIEVED_EVIDENCE`（越权）、`DOC_TYPE_MISMATCH`、`NON_EFFECTIVE_VERSION_AS_MATCH/PARTIAL`、`ATTACHMENT_INCOMPLETE_FOR_MATCH`、`LOCATOR_NOT_IN_EVIDENCE`（编造定位）、`CONFIDENT_WITHOUT_LOCATOR`（confidence≥0.8 且 locator=UNKNOWN，模糊自信错配）、`NO_EXPLANATION`（空或套话理由）、`ABSTAIN_WITHOUT_REASON`、`CONFIDENT_MATCH_WITHOUT_EVIDENCE` | `validate_semantic` |
| 规则提示（对照用，**不是 Gold**） | 纯元数据给 MATCH/PARTIAL/OUTDATED/MISSING 提示；模型和提示不一致只记 warning `DIFFERS_FROM_RULE_HINT`，不拒绝（模型可以比规则对） | `rule_hint` |
| 接入 WP03 Adapter | `run_agent(..., packet=)`；`run_semantic` 在 run_record 里同时留 R4 层（`validation`）和语义层（`semantic_validation`，以它为准）、`unsplit_items`、`rule_hints` | `run_semantic`；CLI `tools/dd_v1_agent_probe.py semantic` |
| R4 层的一处调整 | 同期间但为草稿/被取代版本（`non_effective_files`）允许 OUTDATED；其余 WP02 N3 规则不变（默认参数为空集，WP01–03 行为不变） | `dd_v1_agent_result_service._check_result` |

合成 fixture `backend/tests/fixtures/dd_v1_fos71_wp04/`：8 个文件（2024 审计正文 + 附注、2024 草稿、2023 正文、别的主体 2024、章程 2024 现行 / 2021 被取代、注入备忘），4 条原始清单（含附注、两种文档合一条、含糊条目、要求 2022 但只有 2023/2024）。

## 单 writer 核查
- 开工前 `git branch -r | grep 71`：只有 wp00–wp03，没有 wp04；`origin/feat/71-wp03` = 我的 `7418ad5`
- Mac `ps` 无 codex/pi/hermes 残留进程（14:45、14:52、15:16 三次）

## 确定性测试（box）
| 命令 | 结果 |
|---|---|
| `pytest tests/test_dd_v1_semantic_retrieval.py` | **31 passed** |
| `pytest tests/test_dd_v1_*.py`（DD-V1 全部） | **261 passed** |
| `pytest tests/`（后端全量） | 1389 passed / 30 skipped / **1 failed**：`test_doctor_script_exits_zero`，原因是 box 没有 `backend/.env` 和前端 `node_modules`。在不含本 PR 改动的 `feat/71-wp03` 上同样失败（`git stash` 对照），属于环境问题，不是回归 |

## Mac 合成实跑（代码 = `git archive 0d67b55`）
Mac 到 github.com:443 超时（75s），改为 box `git archive 0d67b55` → CopyFromBox → `/tmp/fos71-wp04-run`；tgz sha256 `cbcb5383…863c`。Python 复用 WP03 重跑的 venv（工具把本树 `backend/src` 放在 sys.path 最前）。脚本 `/tmp/fos71-wp04-run.sh`，`</dev/null`，timeout 240s，开始 2026-10-16 15:16:01 CST。日志在 `runs/`。

| Adapter | exit | 墙钟 | 状态 | 模型 | 费用 | 语义层 | 结果（义务: 判定 [文件] 置信度） |
|---|---|---|---|---|---|---|---|
| codex（考生 2 跑道） | 0 | 130s（CLI 129.45s） | OK | UNKNOWN | UNKNOWN(订阅) | AGENT_SUGGESTION 4/0 | R1-O1 MATCH [G001,G002] 0.99；R2-O1 MATCH [G006] 0.99；R2-O2 MISSING 1.0；R4-O1 MISSING 0.99 |
| minimax-pi（AUX，不计分） | 0 | 26s（26.18s） | OK | MiniMax-M3.1-Flash-Preview | 0 | AGENT_SUGGESTION 4/0 | 同上（R2-O2 0.99） |
| deepseek-harness（考生 3） | 2 | 1s | UNAVAILABLE / BLOCKED，未起进程 | — | — | RULE_ONLY | — |

- 两个模型的 4 条判定都和规则提示一致，没有 warning。**这只说明管道通了，不是准确率**：规则提示不是 Gold，4 条义务 < 30，按合同属于 NOT_SCORABLE / LOW_CONFIDENCE。
- R3「其他相关材料等」没有送给模型，按 `NEEDS_HUMAN_SPLIT` 留给人工。
- 观察：Codex 在 3 条结果里写了 `PROMPT_INJECTION` warning，但注入文件 G008 并没有进入它的证据（检索层已排除），属于误报；只是 warning，不影响校验。
- Mac `pytest tests/test_dd_v1_semantic_retrieval.py tests/test_dd_v1_agent_adapters.py`：**55 passed**。

## 没做的事
- 没有 Gold、没有评分、没有真实材料；没有新 key、没有花钱；没有动生产控制器 / work_items.json / main。
- Windows 仍未实跑（Bog 机器离线，OQ-4）。
- 拆条目只覆盖字典里的 7 类文档；字典外的条目一律 NEEDS_HUMAN_SPLIT，不让模型拆（模型拆分建议放到 WP05/WP06 再评估）。

## 双账
- 工程：WP00–WP03 已经独立复核（均为 PASS_WITH_NOTES，Notes 已修）= 4/8 = 50%；WP04 待复核，不计。（WP02 合同里冻结的 25% 是 WP02 当时的快照，没有改。）
- 效果：G01–G08 真实验证 0 项。本 WP 只有合成 fixture，不计业务分。
