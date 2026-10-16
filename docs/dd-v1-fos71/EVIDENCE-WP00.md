# EVIDENCE · WP00（cangjie-fos#71）

subject_id: DD-V1-FOS71/WP00｜collected_at: 2026-10-16 13:05–13:45 CST｜code_version: `a6bf515`｜config_version: cangjie-gm `529e99a`（executor 配置）+ PR #214 `03ec5fd`

## 执行器（如实记录）
| 时间（CST） | 执行器 | 命令 | exit | 结果 |
|---|---|---|---|---|
| 13:06 | pi/minimax-cn | `pi -p --provider minimax-cn --no-session "<smoke>"`（没接 </dev/null） | 手动结束 | 等待 stdin 挂起 >3 分钟，0 产出 |
| 13:09 | pi/minimax-cn | 同上 + `</dev/null` | 0 | 4s，`PONG` / `a6bf515`（CLI_READY） |
| 13:12 | pi/minimax-cn（WP00 任务包 .wp00-evidence/TASK-WP00.md） | `nohup perl -e 'alarm 1500; exec @ARGV' pi -p ... </dev/null &` | — | 进程随 Shell 会话结束而退出，日志 0 字节 |
| 13:18:48 | pi/minimax-cn（定时汇报任务重复拉起，pid 19588/19605） | `.wp00-evidence/run-wp00.sh` | 143（13:33 被司仓 SIGTERM） | 14 分 25 秒，CPU 0.0%，无输出、无文件 → HUNG |
| 13:20 | 单 writer 核查 | `ps -axo pid,ppid,etime,comm` | 0 | 只有 19605 一个 writer；司仓自己的运行已不存在 → 不需要停任何进程 |
| 13:35– | **Grok（司仓）替补** | 在 box 独立 clone（a6bf515）写本目录 5 个文件，用 GitHub API 推到 `feat/71-wp00` | — | 本 PR |

**真实施工情况**：MiniMax 没有产出 WP00 内容（判 FAIL/HUNG）。本 PR 的文档由 Grok 撰写，并由 Grok 自查。**不是独立复核**：独立 Gate 还需要另一个 Reviewer（监工只读核验或人工）。

## 命令与退出码
| 命令 | exit | 观察 |
|---|---|---|
| `git clone --depth 1 https://github.com/bog5d/cangjie-fos.git && git log -1` | 0 | `a6bf515` |
| `cd backend && uv sync --all-extras && uv pip install pytest && .venv/bin/python -m pytest tests/test_dd_v1_*.py -o addopts=""` | 1 | 160 passed / 1 failed：`test_absent_docling_is_detected`，原因是 `--all-extras` 装了 docling（`python -c "import docling"` 成功）→ 环境假失败，不是代码回归 |
| `rg -n "LLM\|llm" backend/src/cangjie_fos/services/dd_v1_*.py` | 0 | 各阶段文件头都声明零 LLM |
| `rg -ln "dd_llm_client" backend/src` | 0 | 17 个文件（含 client 本身） |
| `codex --version; codex exec --help; codex login status`（Mac） | 0 | 0.152.0；有 --output-schema/--json/-o/-C/-s；Logged in using ChatGPT |
| `which dsh`（Mac） | 0 | `/Users/mac/.npm-global/bin/dsh`（GM 配置 2026-10-11 已停用） |
| `sqlite3 -readonly runtime-state.sqlite`（Mac，交接核查） | 0 | mvs_575c idle、locks=0 |

## 合规
没有 Gold Set，没有真实客户资料，没有密钥（只写了环境变量名），没有代码或测试改动，没有花费，没有推 master。
