# WP00 · 模型调用选项（不购买新 API）

collected_at 2026-10-16 13:38 CST｜宿主 Mac（只读探测，没有发起任何模型调用）

| 选项 | 入口 | 凭据来源 | 结构化输出 | 隐私边界 | 状态 | WP01 怎么验证 |
|---|---|---|---|---|---|---|
| A. Codex CLI（考生 1/2） | `codex exec -C <隔离目录> -s read-only --output-schema <schema.json> -o <out.json> "<task packet>"` | 现有 ChatGPT 订阅登录（`codex login status` → "Logged in using ChatGPT"） | `--output-schema` / `--json` / `-o` 参数**存在**（codex-cli 0.152.0 `--help`） | 会把 prompt 和片段发到 OpenAI 云端：**只能用合成/脱敏 fixture** | **CLI_PRESENT**；非交互推理 + schema 回传 = UNKNOWN | 2–3 个合成 fixture，各跑 1 次：exit code、out.json 能通过 R4 Schema 校验、记录模型标识（没有就写 UNKNOWN）、耗时、订阅额度是否被拒 |
| B. DeepSeek Harness（考生 3） | `dsh` 二进制存在（`~/.npm-global/bin/dsh`） | GM `config/runtime_watchdog.json`：dsh 已于 2026-10-11 被董事长**永久停用**（余额不足，常驻服务下线） | UNKNOWN | DeepSeek 云端 | **UNKNOWN，大概率 NOT_SUPPORTED**（HISTORICAL 停用记录 + 未实测） | 先请业务方确认有没有仍可用的 Harness 会话或额度；没有就判考生 3 = BLOCKED。**不得改走 `dd_llm_client` 直连 DeepSeek API 冒充 Harness** |
| C. 人工交接模式（保底） | 操作者把 Task Packet（JSON）粘贴进现有 Codex/DeepSeek 会话，再把模型回的 JSON 粘贴回来，由 FOS 校验 | 现有会话，不需要新凭据 | 由 FOS 用 R4 Schema 校验 | 由操作者控制，只用合成材料 | 可行（INFERRED） | 1 个 fixture 跑通「导出 → 回贴 → 校验 → 拒绝伪造路径」 |
| D. MiniMax pi（仅开发执行器，不是考生） | `pi -p --provider minimax-cn --no-session` | Coding Plan | — | — | 冒烟 CLI_READY；WP00 长任务 HUNG（见 EVIDENCE） | 不在 #71 考生定义里，不加入考试 |

禁止：把「Codex/DeepSeek 执行 FOS 规则 CLI」算作模型参与（#71 P0-1）；用直连 API 冒充「无额外 API」（G02）。
