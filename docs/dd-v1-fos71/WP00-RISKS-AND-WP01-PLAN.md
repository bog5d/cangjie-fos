# WP00 · 风险、Runtime Takeover Verdict、WP01 计划

## 风险
| 风险 | 级别 | 对策 / Gate |
|---|---|---|
| 敏感资料经 CLI 发到云端模型 | P0 | WP01 只用合成 fixture；Task Packet 只放最小片段；真实资料要另行授权 |
| Prompt Injection（材料正文里夹带指令） | P0 | 材料正文当不可信数据；Agent 只读、`-s read-only`；输出必须重新过 match_service.judge 和 policy |
| Gold Set 泄漏给考生 | P0 | Gold 不进仓库、不进 Agent 工作目录；WP00/WP01 不读也不建 Gold |
| 双执行器 / 双写 | P0 | 单 writer 登记（GM #214）；本次 13:20 发现定时任务重复拉起 → 核查后只剩 1 个（EVIDENCE） |
| 额度 / 平台 529 / CLI 挂起 | P1 | 每次调用设硬超时，`stdin=/dev/null`；失败就降级 RULE_ONLY/UNCERTAIN 并记原因（R5） |
| DeepSeek Harness 不可用 | P1 | 考生 3 判 BLOCKED，报董事长/业务方另行决定，不偷换 API |
| Windows 兼容 | P1 | WP06 真人在 Windows 跑；WP01 只记 UNKNOWN |
| 规则模式退化 | P1 | 每个 PR 跑 `tests/test_dd_v1_*.py`，基线 160 passed（docling 环境假失败单独列出） |

## Runtime Takeover Verdict
**PASS（单 writer）**。#71 的写入权：MiniMax pi/minimax-cn @ `/Users/mac/dd-v1-71-wt`（13:12 交接，GM #214 commit 03ec5fd）→ 该路径 13:33 判 HUNG（运行 14 分 25 秒，CPU 0，无输出），kill 后按授权回退到 Grok（司仓）。WP00 由 Grok 在独立 clone 写，推到 `feat/71-wp00`。旧会话 mvs_575c 已让出；监工只读。

## WP01 计划（环境/模型调用 Spike）
- target_goal_ids: FOS71-G01、G02、G05
- 输入：`fixtures/dd-v1-fos71/`，2–3 个**合成**样例（虚构主体「示例科技有限公司」、2 年期间、含 1 个错主体文件 + 1 个伪造路径 + 1 段注入文本）
- 输出 Schema：Issue #71 R4 字段（agent_id/provider/model_id_or_unknown、prompt_version、source_snapshot_id、candidate_files[{file_id,relative_path,sha256,locator,entity,period,match_reason}]、proposed_verdict、confidence_or_uncertain、abstain_reason、warnings、elapsed、token_usage_or_UNKNOWN）→ `schemas/agent_result.v1.json`
- 步骤：① 写 schema + fixture + 校验器（确定性，不调模型）；② Codex 选项 A 跑 1 次；③ 人工交接选项 C 跑 1 次；④ DeepSeek 选项 B：只确认可用性，不可用就写 BLOCKED
- Gate：真实模型的输入/输出都留证；伪造路径和错主体被校验器拒绝；RULE_ONLY 回归不退化；没有新增 API key、没有花费
- 退出条件：A 和 C 至少一条闭环 PASS；否则写 FAIL/BLOCKED 和备选方案，报司仓，不扩大施工
- expected_capability_change: 证明「不买 API 也能让模型语义参与一次，并被 FOS 硬校验」
- verified_capability_change: none（未开始）
- next_action: 本 PR 独立复核 OK → 开 WP01 分支

## WP00 自身
- target_goal_ids: FOS71-G07、G08（事实底座 + 双账）
- expected_capability_change: 有可复核的基线、复用清单和调用选项
- verified_capability_change: 文档交付；没有代码或能力变化（用户可观察能力 +0）
- Evidence: EVIDENCE-WP00.md
- next_action: 独立 Reviewer 复核
