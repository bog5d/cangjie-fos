# WP00 · Reuse Matrix（SCP v3.8 §1）

collected_at 2026-10-16 13:40 CST｜code_version `a6bf515`｜路径前缀 `backend/src/cangjie_fos/services/`

| 候选 | 位置 | 成熟度 | 是否用 LLM | 接入成本 | 风险 | 复用方式 | 证据 |
|---|---|---|---|---|---|---|---|
| Manifest | dd_v1_manifest_service.py（700 行）+ tools/dd_v1_manifest.py | 已合入 + 回归 | 否 | 低 | 低 | 原样复用：source_snapshot_id 和 file_id/sha256 的来源 | #66；test_dd_v1_recovery/attachments |
| 解析 | dd_v1_parser_service.py（276 行） | 已合入 | 否 | 低 | Docling 可选依赖导致测试环境敏感 | 原样复用：给 Agent 提供 locator 片段 | test_dd_v1_docling_adapter |
| 认知卡 / FTS | dd_v1_card_service.py（702 行） | 已合入 | 否 | 低 | 召回上限 | 复用 `search_materials` 生成「受控候选」，交给 Agent 读 | test_dd_v1_cards/recall |
| 需求拆解 | dd_v1_requirement_service.py（609 行） | 已合入 | 否 | 中 | 规则覆盖不足，正是要模型补的地方 | 规则结果作为 Agent 的先验 + RULE_ONLY 控制组 | test_dd_v1_matching |
| 匹配 / judge | dd_v1_match_service.py（681 行） | 已合入 | 否 | 中 | — | **硬校验层**：Agent 建议必须重新过 evaluate_file/judge（主体/期间/附件/敏感度） | test_dd_v1_matching |
| 披露策略 | dd_v1_policy_service.py（249 行） | 已合入（WP7 修了二值判定漏洞） | 否 | 低 | 正式政策等 #75 | 原样作为外发 Gate | test_dd_v1_policy_and_entry |
| 审核 / 组包 | dd_v1_package_service.py（495 行） | 已合入 | 否 | 低 | — | 原样：模型不能置 approved | test_dd_v1_packaging |
| 经验 / 回归 / 评分 | dd_v1_experience_service.py（554 行） | 已合入 | 否 | 低 | — | R8 经验沉淀 + R7 评分接口 | test_dd_v1_experience |
| Team Channel 入口 | tools/dd_team_channel.py（326 行） | 已合入 | 否 | 低 | — | 以后的触发入口（不阻断 PoC） | #68 |
| **dd_llm_client.py** | dd_llm_client.py | 旧 FOS 在用 | **是：OpenAI SDK 直连**，`DEEPSEEK_API_KEY`（base_url api.deepseek.com）或 `OPENAI_API_KEY`；函数 `get_dd_llm_client`、`call_with_retry` | 低（技术上） | **违反 #71 P0-2/G02**：这是独立 API 路径，不是 Harness；需要 key 和花费 | **不作为考生 2/3 的路径**。只复用它的 retry/降级思路（`call_with_retry`）；如果要用直连 API，必须另行授权 | 第 6、40–66 行 |
| 旧 FOS LLM 匹配 | dd_match_service.py（`model="deepseek-chat"`，第 945、1078 行）以及 dd_checklist_parser、dd_clarify、dd_qa、package_gap/synthesis、consistency 等，共 16 个模块引用该 client | 旧 Web 尽调在用 | 是（同一 client） | 中 | 同上；prompt 没有版本化；「候选上限只是 prompt 文本」（dd_v1_match_service 文件头 D3 的批评） | **只复用 prompt 思路和失败样例**作为 WP04 输入；不复用调用路径 | `rg -l dd_llm_client` |
| GM 执行器适配 | cangjie-gm `gm/runtime_watchdog/transport.py`（codex exec -C / pi -p / hermes -z） | GM 生产 | — | 中 | 不能复制第二套 GM | 参考 argv 契约设计 FOS Agent Adapter（只引用，不复制） | GM `529e99a` |
