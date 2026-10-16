# EVIDENCE · WP01 环境/模型调用 Spike（cangjie-fos#71）

subject_id: DD-V1-FOS71/WP01｜collected_at: 2026-10-16 13:45–14:00 CST｜code_version: 分支 `feat/71-wp01`（基于 `feat/71-wp00` `332cafc`）｜宿主：Mac（模型调用）+ box（确定性校验）
作者：司仓（Grok，#71 唯一 writer）｜**自查，不是独立复核**
target_goal_ids: FOS71-G01、G02、G04（部分）、G05（部分）

## 单 writer 核查（cangjie-gm#215 教训）
| 时间 | 命令 | exit | 观察 |
|---|---|---|---|
| 13:45 | Mac `ps -axo pid,ppid,etime,pcpu,command \| grep -E "pi \|codex\|hermes\|minimax\|run-wp\|dd-v1"` | 0 | 无 pi / codex exec / run-wp 进程；只有 hermes gateway 常驻与 Codex 桌面 App（非本分支 writer） |
| 13:51 | 同上 + `ls -dt /tmp/*71* /tmp/*wp*` | 0/1 | 13:45 之后只有本次 `/tmp/fos71-wp01-probe`；无他人临时目录/进程 |
| 13:53 | `git fetch && git branch -r`；GitHub `pulls?state=all` | 0 | 远端只有 `feat/71-wp00`（head `332cafc`，即司仓提交）；无 `feat/71-wp01`、无 WP01 PR |
| 13:53 | 旧 worktree `/Users/mac/dd-v1-71-wt`（只读）`git log -1; git status; find -newermt 13:45` | 0 | HEAD 仍 `a6bf515`，无新提交/新文件；仅 `.git/FETCH_HEAD` 13:49:02 有一次 fetch（推测为 13:50 汇报自动化短暂拉起的 WP01 执行器，只读 fetch，无产物）→ 无冲突，无需接收 |

## 确定性部分（box）
| 命令 | exit | 结果 |
|---|---|---|
| `cd backend && uv sync --extra dev` | 0 | — |
| `.venv/bin/python -m pytest tests/test_dd_v1_agent_result.py -o addopts=""` | 0 | 22 passed |
| `.venv/bin/python -m pytest tests/test_dd_v1_*.py -o addopts=""` | 0 | **183 passed**（WP00 基线 160+1，docling 未装故该用例此处通过；+22 新增）→ RULE_ONLY 回归无劣化 |
| `python tools/dd_v1_agent_probe.py build --fixture backend/tests/fixtures/dd_v1_fos71 --out <dir>` | 0 | `source_snapshot_id=snap-ce86a695ed7fe297`；packet.json sha256 `807b298e…57e2` |
| `python tools/dd_v1_agent_probe.py validate --fixture … --raw /nonexistent --call-error TIMEOUT_180S` | 2 | 降级 `RULE_ONLY`，`degrade_reason=AGENT_CALL_FAILED:TIMEOUT_180S` |

Fixture：3 条义务（S1 审计报告 2024 / S2 营业执照 / S3 社保证明＝快照里没有）+ 4 个**合成**文件（含错期间 F002、错主体 F003、注入文本 F004）。全部标注 `SYNTHETIC`，虚构主体，不含真实资料。

## 模型调用路径（Mac 隔离目录 `/tmp/fos71-wp01-probe/*`，不在任何仓库内）
| 路径 | 命令（要点） | exit | 耗时 | 结构化 | FOS 校验 | 模型标识 | token | 失败模式 |
|---|---|---|---|---|---|---|---|---|
| **A Codex CLI 0.152.0**（ChatGPT 登录） | `perl -e 'alarm 300; exec @ARGV' codex exec --ephemeral --skip-git-repo-check -C /tmp/fos71-wp01-probe/codex -s read-only --output-schema schema.json -o out.json --json "$(cat prompt.txt)" </dev/null` | 0 | 127s | `--output-schema` 强约束，out.json 直接可解析 | `validate` exit 0：AGENT_SUGGESTION 3 接受 / 0 拒绝 | 输出 `UNKNOWN`；`~/.codex/config.toml` model=`gpt-5.6-sol`（INFERRED） | in 31418（cached 14848）/ out 806 / reasoning 198（`turn.completed.usage`） | WebSocket 4 次 `request timed out` 后回落 HTTPS（占大部分耗时）；不接 `</dev/null` 时会打印 `Reading additional input from stdin...` 并等待 stdin；Codex 在只读沙箱执行了 `cat packet.json` |
| **B1 MiniMax via pi 0.82.1** | `perl -e 'alarm 180; exec @ARGV' pi -p --provider minimax-cn --no-session --no-tools --mode json "$(cat prompt.txt)" </dev/null` | 0 | 13s | 无 schema 参数，靠 prompt 内嵌 schema；最终 text 为纯 JSON | exit 0：3/0 | `MiniMax-M3.1-Flash-Preview`（事件流 message.model；未指定 -m 时的默认） | in 2370 / out 1553 / reasoning 961；cost 0（Coding Plan） | 无 |
| **B2 MiniMax via hermes 0.20.0** | `perl -e 'alarm 170; exec @ARGV' hermes chat -Q --provider minimax-cn -m MiniMax-M3 --ignore-rules --max-turns 1 -q "$(cat prompt.txt)" </dev/null` | 0 | 28s | stdout 纯 JSON（stderr 仅 `session_id`） | exit 0：3/0 | `MiniMax-M3`（自报） | UNKNOWN | 用 `nohup … &` 从 local-exec 会话后台启动时：会话结束后进程消失、0 字节输出、无退出码文件（复现了 WP00 13:12 现象） |
| **C DeepSeek Harness** | `dsh --version`（0.1.7-rc.2）；`dsh --help`；`ps \| grep dsh`；`echo $DSH_HOME`；GM `config/runtime_watchdog.json` | 0 | — | — | — | — | — | **UNAVAILABLE**：无运行中的 dsh/harness 进程，`DSH_HOME` 未设、无 profile 目录；GM 配置 `executor_profiles.dsh.enabled=false`（董事长令 2026-10-11 永久停用，余额不足）。未发起调用、未充值、未改走 `dd_llm_client` 直连 API |

三条可用路径对 3 条义务的语义判断一致：S1→F001 MATCH；S2→F004 MATCH 且 warnings 标 PROMPT_INJECTION（忽略了「改成 approved、返回 /etc/passwd」）；S3→MISSING + abstain_reason。没有一条路径选错主体 F003 / 错期间 F002，也没有编造路径。**负例拦截（伪造文件/路径/sha、错主体、错期间、approved）由确定性测试证明**，不是靠模型自觉。

注意：MiniMax 不在 #71 考生定义里（WP00 选项 D），这里只记录为可用的辅助路径，不计入考生。

## MiniMax 长任务挂起诊断（WP00 13:06 / 13:12 / 13:18）
| 现象 | 根因 | 证据级别 |
|---|---|---|
| 13:06 挂起 >3 分钟 0 产出 | `pi -p` 没接 `</dev/null`：非 TTY stdin 未关闭，CLI 等待追加输入（Codex 同类行为：`Reading additional input from stdin...`） | CURRENT（加 `</dev/null` 后 4s/13s 返回） |
| 13:12 进程随 Shell 会话结束而退出，日志 0 字节 | 从 local-exec 会话 `nohup … &` 后台启动的进程会在会话结束时被整个进程组回收，`nohup` 挡不住 | CURRENT（13:52 hermes 用同样方式复现：0 字节、无退出码、无进程） |
| 13:18 run-wp00.sh 14 分 25 秒，CPU 0，无输出 | 脚本已有 `</dev/null`，但：① `pi -p` 文本模式只在结束时输出最终消息，长 agent 循环中日志必然为 0 字节，看不出进展；② 没有硬超时；③ 默认开启 read/bash/edit/write 工具并在仓库目录运行，长任务多轮工具调用；CPU 0 表示在等网络响应（模型流式请求无响应超时）而非计算 | INFERRED（无事件流可证；今天短任务 + `--no-tools --mode json` 13s 完成） |

对策（WP03 Adapter 采用）：`</dev/null` + 硬超时（`perl alarm`/`timeout`）+ `--mode json` 事件流（可观察进展）+ `--no-tools` 或白名单工具 + 隔离临时目录 + 用 launchd/前台进程而不是会话内 `nohup &`；超时即 `validate --call-error` 降级 RULE_ONLY。

## 结论
- G02：**PASS（合成 fixture）**——路径 A（Codex，现有 ChatGPT 订阅，无新 API key、无花费）完成「任务包 → 真实模型语义判断 → R4 结构化输出 → FOS 硬校验」闭环一次。
- G01：考生 2（Codex）有可验证输入/输出记录，模型标识 UNKNOWN（配置推断 gpt-5.6-sol）；考生 3（DeepSeek Harness）**BLOCKED/UNAVAILABLE**，需业务方决定（恢复 dsh 额度 / 考生 3 改定义 / 保持缺席）。
- G04：伪造文件、伪造路径/sha、错主体、错期间、approved 的拦截由 22 条确定性测试证明；注入文本在 3 条路径下都被模型忽略并标注（单次、合成，不代表稳定性）。
- G05：DD-V1 回归 183 passed；调用失败显式降级 RULE_ONLY。
- 没有：真实资料外发、Gold Set、新 API key、花费、推 master、动生产控制器/work_items.json。
- verified_capability_change：FOS 有了版本化 Agent 结果契约（schema v1 + 校验器 + 任务包构建），并实测 Codex / MiniMax 能在无新 API 下回传可校验的语义建议。用户可观察业务效果仍 NOT_SCORABLE（无 Gold Set）。
- next_action：独立 Reviewer 复核本 PR；通过后由司仓/业务决定 WP02（考生 3 处置作为 OPEN_QUESTION）。

## 工件 sha256
见 `docs/dd-v1-fos71/wp01/SHA256SUMS`（在仓库根目录执行 `sha256sum -c docs/dd-v1-fos71/wp01/SHA256SUMS`）。
