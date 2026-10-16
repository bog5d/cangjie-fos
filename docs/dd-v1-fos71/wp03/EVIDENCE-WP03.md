# EVIDENCE · WP03 Agent Adapter 与受控工具（cangjie-fos#71）

subject_id: DD-V1-FOS71/WP03｜collected_at 2026-10-16 14:28–14:45 CST｜base `feat/71-wp02` `8386068`｜作者：司仓（#71 唯一 writer）｜**自查，不是独立复核**
target_goal_ids: FOS71-G01（运行路径可区分、有日志）、G05（失败显式降级）、G04（部分：Adapter 输出必须过硬校验）
默认值（董事长尚未裁决 OQ-1/OQ-2）：考生3 = DeepSeek Harness，缺席并标 BLOCKED；MiniMax 只作 AUX；没有 Gold → NOT_SCORABLE；只用合成材料。

## 是否依赖 OQ-1/OQ-2
WP03 的交付物（Adapter、隔离目录、超时/降级、留证）**不依赖** Gold Set 或真实材料，所以开工。依赖部分做成桩并标 BLOCKED：
| 部分 | 处理 |
|---|---|
| DeepSeek Harness Adapter（考生3） | **桩**：`DeepSeekHarnessAdapter` 不启动任何进程，直接返回 `UNAVAILABLE`，reason 写明 `BLOCKED: … OQ-1 pending chairman; no purchase, no API fallback`；测试证明它不会调用 `Popen` |
| 真实材料上的 Adapter 运行 | BLOCKED（OQ-3）；本 WP 只跑合成 fixture |
| 评分 / Gold | 不属于 WP03（WP05）；没有实现，也没有伪造 |

## 交付
- `backend/src/cangjie_fos/services/dd_v1_agent_adapters.py`
  - `CodexAdapter`（考生2 路径）、`MiniMaxPiAdapter`（AUX）、`ManualExchangeAdapter`（R2 人工交换）、`DeepSeekHarnessAdapter`（桩）
  - `run_cli`：stdin=/dev/null、新进程组、超时 SIGKILL 整组、启动失败记为 CALL_FAILED(127)
  - `prepare_workdir`：隔离目录里只有 packet.json 和 schema.json
  - `run_agent`：建包 → Adapter → `validate_agent_output`（非 OK 一律降级 RULE_ONLY）→ 写 `run_record.json`
  - `Budget(timeout_s, max_calls)`
  - 供应商名只出现在本模块；Kernel 由测试保证不含供应商名
- `tools/dd_v1_agent_probe.py run --adapter {codex,minimax-pi,manual,deepseek-harness}`
- `backend/tests/test_dd_v1_agent_adapters.py`：14 个测试，全部用假 CLI，不调用真实模型。覆盖：成功、隔离、超时杀进程组（子进程标记文件不会出现）、非 0 退出、垃圾输出、CLI 不存在、pi 事件解析、人工交换 pending→完成、人工回贴伪造路径被拒、DeepSeek 桩不 spawn、预算、Kernel 无供应商名、无模型客户端 import、相对 workdir 回归
- 没有改动 match/policy/package/规则模式

## 单 writer 核查
14:27 Mac `ps` 没有 pi/codex exec/hermes chat 进程；远端只有 wp00/wp01/wp02（都是司仓提交），`feat/71-wp03` 不存在。

## 确定性测试（box）
| 命令 | exit | 结果 |
|---|---|---|
| `pytest tests/test_dd_v1_agent_adapters.py -o addopts=""` | 0 | 14 passed |
| `pytest tests/test_dd_v1_*.py -o addopts=""` | 0 | **219 passed**（WP02 205 + 14） |

## 真实 Adapter 冒烟（Mac 隔离 `/tmp/fos71-wp03-run`，代码是本分支的 tar 拷贝，`uv sync` exit 0；只用合成 fixture）
命令：`backend/.venv/bin/python tools/dd_v1_agent_probe.py run --fixture backend/tests/fixtures/dd_v1_fos71 --adapter <A> --timeout 240 --workdir runs/<A>`
| 时间 CST | adapter | CLI exit | adapter status | elapsed_s | 模型 | token | 校验 | 工具 exit |
|---|---|---|---|---|---|---|---|---|
| 14:34:29 | deepseek-harness | — | UNAVAILABLE（BLOCKED） | — | — | — | RULE_ONLY | 2 |
| 14:34:29 | manual（未回贴） | — | PENDING_MANUAL | — | — | — | RULE_ONLY | 2 |
| 14:34:29 | minimax-pi（AUX） | 0 | OK | 53.37 | MiniMax-M3.1-Flash-Preview | total 4969，cost 0 | AGENT_SUGGESTION 3/0 | 0 |
| 14:35:23 | codex（第 1 次） | 1 | CALL_FAILED | 0.12 | — | — | RULE_ONLY（`EXIT_1: No such file or directory`） | 2 |
| 14:35:57 | codex（修复后） | 0 | OK | 124.66 | UNKNOWN | in 34141 / out 730 | AGENT_SUGGESTION 3/0 | 0 |
| 14:38 | manual（操作者回贴 reply.json） | — | OK | — | — | — | AGENT_SUGGESTION 3/0 | 0 |

**实测发现的缺陷**：`--workdir` 传相对路径时，CLI 以 cwd=workdir 启动，`codex -C runs/codex` 被二次拼接 → exit 1。降级路径正确（RULE_ONLY + 原因），说明没有假装成功。修复：`run_agent` 里把 workdir `resolve()` 成绝对路径；加回归测试 `test_relative_workdir_is_resolved_to_absolute`。第 1 次失败的记录保留在 `runs/codex-attempt1-relpath-bug.run_record.json`。

人工交换的 reply.json 是操作者把 AUX 的输出贴回来演示流程用的，**不是独立的模型调用**。
修复后的 adapters.py 在 Mac 上的 sha256 `81e28b87…0c14` = 本分支文件（见 SHA256SUMS）。

## 复核修正（REVIEW-WP03 PASS_WITH_NOTES，N1–N5；代码 commit `2be4403`，合同 commit `a4d2a1c`）
| # | 修正 | 测试 |
|---|---|---|
| N1 | ManualExchangeAdapter 读 `reply.json` 时把 `reply_sha256`、`reply_source`（来自可选 `reply.provenance.json`，没写就是 `UNDECLARED_OPERATOR_PASTE`）、`declared_by`、`independent_examinee_answer=false` 写进 run_record 的 `adapter.provenance`。回贴文件已入库并进入 SHA256SUMS | `test_manual_exchange_pending_then_complete_with_provenance`、`test_manual_reply_without_provenance_is_marked_undeclared` |
| N2 | 传入的 workdir 必须为空（人工交换只允许 packet/schema/PROMPT/reply/reply.provenance/run_record），否则 `ValueError(WORKDIR_NOT_EMPTY)`；Codex/pi 每次调用前还会删掉 out.json/events/stderr，双保险 | `test_nonempty_workdir_rejected_for_cli_adapters`、`test_codex_never_reads_stale_out_json_even_in_reused_dir`、`test_manual_workdir_rejects_unexpected_files` |
| N3 | `max_calls` 生效：只有 TIMEOUT/CALL_FAILED 会重试，最多 max_calls 次，run_record 记录 `calls_used` 和 `attempts[]`。新增 `Budget.max_cost_usd`（默认 0 = 不允许付费）；Adapter 上报 `cost_usd_or_UNKNOWN`（pi 取 usage.cost.total，Codex 记 `UNKNOWN(ChatGPT subscription)`），已知费用超上限 → `BUDGET_EXCEEDED`，丢弃输出并降级 RULE_ONLY | `test_max_calls_retries_until_success`、`test_max_calls_stops_and_degrades`、`test_non_retryable_status_not_retried`、`test_cost_budget_exceeded_discards_output`、`test_cost_within_budget_ok`、`test_budget_validation` |
| N4 | 合同 `scoring_rules.gold_must_not_be_on_executor_host=true`、`manual_reply_counts_as_examinee=false`，`gate.acceptance_criteria` 加一条 WP05 HG-ISOL；SPEC HG-ISOL 同步。检索最小证据由 WP04 承接（见 WP04 PR） | `test_wp03_n4_gold_not_on_executor_host_and_manual_not_examinee` |
| N5 | 假 CLI 改成 Python 脚本，以 `[sys.executable, fake.py]` 调用，**不再整体 skip win32**；杀进程：POSIX 用 `start_new_session`+`killpg`，Windows 用 `CREATE_NEW_PROCESS_GROUP`+`taskkill /T /F`。**Windows 尚未实际执行**（Bog 机器不在线，OQ-4），这一项是 UNKNOWN，不是 PASS | box 24 passed；Mac 同 commit 24 passed |

### 同一 commit 在 Mac 上重跑全部 Adapter（复核 N5）
`git clone --branch feat/71-wp03`，HEAD = `a4d2a1c`，路径 `/tmp/fos71-wp03-rerun`，`uv sync` exit 0；脚本 `/tmp/fos71-wp03-rerun.sh`，所有调用 `</dev/null`、timeout 180s；开始 2026-10-16 14:52:31 CST。日志在 `rerun-a4d2a1c/`。

| Adapter | probe exit | 墙钟 | adapter 状态 | 模型 | 费用 | calls_used | 校验 | 接受/拒绝 |
|---|---|---|---|---|---|---|---|---|
| codex | 0 | 129s（CLI 127.6s） | OK | UNKNOWN | UNKNOWN(订阅) | 1 | AGENT_SUGGESTION | 3/0 |
| minimax-pi（AUX） | 0 | 10s（10.42s） | OK | MiniMax-M3.1-Flash-Preview | 0 | 1 | AGENT_SUGGESTION | 3/0 |
| deepseek-harness（EXAMINEE_3） | 2 | 1s | UNAVAILABLE（BLOCKED，未起进程） | — | — | 1 | RULE_ONLY | 0/0 |
| manual（贴前） | 2 | 0s | PENDING_MANUAL | — | — | 1 | RULE_ONLY | 0/0 |
| manual（贴入 minimax 回答后） | 0 | 1s | OK，provenance=`copied_from_AUX_minimax-pi_run(same-commit rerun)`，reply_sha256=`34547243e725…bbe5`，independent_examinee_answer=false | MiniMax-M3.1-Flash-Preview | UNKNOWN | 1 | AGENT_SUGGESTION | 3/0 |

Mac 上 `pytest tests/test_dd_v1_agent_adapters.py`：24 passed in 11.67s。

## 没做的事
没有用真实材料，没有 Gold，没有 DeepSeek 调用或购买，没有新 key，没有动 master、生产控制器或 work_items.json，没有改规则模式。

## 双账
工程：已复核 WP00、WP01 = 25%（WP02、WP03 待复核，不计）。效果：0/100（NOT_SCORABLE）。
next_action：独立复核 #75 和本 PR → 董事长裁决 OQ-1/OQ-2/OQ-3 → WP04。
