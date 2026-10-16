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

## 没做的事
没有用真实材料，没有 Gold，没有 DeepSeek 调用或购买，没有新 key，没有动 master、生产控制器或 work_items.json，没有改规则模式。

## 双账
工程：已复核 WP00、WP01 = 25%（WP02、WP03 待复核，不计）。效果：0/100（NOT_SCORABLE）。
next_action：独立复核 #75 和本 PR → 董事长裁决 OQ-1/OQ-2/OQ-3 → WP04。
