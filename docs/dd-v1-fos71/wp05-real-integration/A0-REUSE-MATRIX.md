# A0 · Reuse Matrix 与最小 Adapter 契约（FOS #71 DD-V1 实引擎集成）

- code base `a7a7e24977eeb40b62e1b34d39d9d4a58dadd28d` ｜本矩阵只写**本轮真实验证过**的行；未验证的列写 UNKNOWN/未验
- 成熟度证据=本轮 pytest 基线（1419 passed 含 dd_v1 系列）+ trace 实调；活跃度=git log -1 日期（2026-10-21 实测）
- License：本仓**无 LICENSE 文件**（私有单仓）；「迁移性」按仓内模块耦合度评估，出仓复用一律 UNKNOWN（License 未定义）

## 1. Reuse Matrix

| 候选能力 | 位置 | 成熟度 | 活跃度 | License | 依赖 | 迁移性 | 接入成本 | 风险 | 复用方式 | 取舍证据 |
|---|---|---|---|---|---|---|---|---|---|---|
| Manifest（库登记/快照/file_id+sha256） | services/dd_v1_manifest_service.py（700 行）+ tools/dd_v1_manifest.py | 已合入，本轮 pytest 含其回归 | 2026-10-15 | 仓库无 LICENSE（私有） | sqlite + core/paths 数据面 env | 仓内低耦合（db_path 可注入）；出仓 UNKNOWN | 低 | Data Plane 越界有显式异常类（DataPlaneViolation） | **原样复用**：A1 直接调 register_library/build_manifest @cmd 层 | 入口 A trace 第1-2步实调；DataPlaneViolation 实证 |
| 解析/正文 | services/dd_v1_parser_service.py（276 行）+ dd_file_parser + dd_content_extractor | 已合入 | 2026-10-15 | 同上 | Docling 可选（缺失自动降级，本轮日志实证） | 同上 | 低 | 二进制无正文→不自动交付（缺口如实报） | **原样复用** | 入口 A trace 第3步：8/8 ok，Docling 缺失降级提示 |
| 认知卡/FTS | services/dd_v1_card_service.py（702 行） | 已合入 | 2026-10-15 | 同上 | sqlite FTS | 同上 | 低 | 召回上限（cap 可调） | **原样复用**：A1 用其 search 产出受控候选 | 入口 A trace 第4步：8 卡+出处分布 46/16/74 |
| 需求拆解 | services/dd_v1_requirement_service.py（609 行） | 已合入 | 2026-10-15 | 同上 | 无外部 | 同上 | 低 | 规则覆盖不足（R3 含糊→NEEDS_HUMAN_SPLIT，本轮实证） | **原样复用**：规则结果=Agent 先验 + RULE_ONLY 控制组 | 入口 A 第5步 4 原文→4 义务零丢失；入口 B R3 NEEDS_HUMAN_SPLIT |
| 匹配/判定 judge | services/dd_v1_match_service.py（681 行），judge @428 | 已合入 | 2026-10-15 | 同上 | 无外部 | 同上 | 中 | 签章维恒不满足（:174-177 自认已知缺口）；数量权威不存在 | **硬校验层复用**：Agent 建议必须重过 evaluate_file/judge | 入口 A trace：judge×4；CONFLICT/MISSING 行为与 fixture 负例一致 |
| 披露策略 | services/dd_v1_policy_service.py（249 行） | 已合入（WP7 修过二值漏洞） | 2026-10-15 | 同上 | config 文件可选 | 同上 | 低 | 未配置=全部不可外发（fail-closed，本轮实证） | **原样复用**：外发 Gate | 入口 A 输出「未生效→按最严处理」；结果 JSON externally_sendable=[] |
| 审核/组包 | services/dd_v1_package_service.py（495 行），package_approved @385 | 已合入 | 2026-10-15 | 同上 | 依赖 ms.get_status/list_matches | 同上 | 低 | 模型不能置 approved（闸先于复制） | **原样复用**：A1 组包唯一合法路径 | 代码实读 :385-440；本轮未实跑组包（dry-run 纪律）→ 运行级证据 UNKNOWN |
| Agent 结果校验 | services/dd_v1_agent_result_service.py（255 行），validate_agent_output @212 | 已合入 | 2026-10-16 | 同上 | jsonschema | 同上 | 低 | 任何失败显式降级（_rule_only）不冒充成功 | **原样复用**：A1 语义建议的验收层 | 入口 B trace：validate_agent_output×6 + _rule_only×6 |
| 语义包/最小证据检索 | services/dd_v1_semantic_retrieval_service.py（399 行）：retrieve_minimal_evidence @136 / build_semantic_packet @174 / validate_semantic @257 / run_semantic @280；常量 MAX_FILES_PER_OBLIGATION=6(:34) / DOC_TYPES 7 类(:27) / MAX_EXCERPT_CHARS=300(:35) | 已合入 | 2026-10-16 | 同上 | 无外部 | 同上 | 低 | 候选≤6、摘录≤300 字为**设计截断**（A2 要处理的召回边界，不是缺陷） | **原样复用**：A1 包构造唯一入口 | 入口 B trace 全链实调；≤6/≤300 截断行为随包生成实证 |
| Agent 适配层 | services/dd_v1_agent_adapters.py（397 行）：Budget/run_agent @350/ADAPTERS @344（codex/minimax-pi/manual/deepseek-harness） | 已合入 | 2026-10-16 | 同上 | subprocess | 同上 | 低 | dsh 路径未实测（本轮禁用付费） | **原样复用**：A1 的模型调用层；本轮已实证 manual 降级契约 | 入口 B trace：run_agent×3、ManualExchangeAdapter.run×3、PENDING_MANUAL、exit 2 |
| **dd_llm_client.py** | services/dd_llm_client.py（106 行） | 旧 FOS 在用 | 2026-05-16 | 同上 | openai SDK；DEEPSEEK_API_KEY/OPENAI_API_KEY | — | 低（技术上） | **排除** | **排除**。理由=违反 #71 P0-2/G02：这是独立 API 路径不是 Harness，需 key 且产生费用；本轮零费用纪律下不可用。仅可复用其 call_with_retry 的指数退避**思路**（:66-106） | 源码实读 :39-63（base_url=api.deepseek.com 直连）；WP00-REUSE-MATRIX 同判 |
| 旧 dd_match_service | services/dd_match_service.py（1635 行），run_matching @93 | 旧 Web 链在用 | 2026-08-19 | 同上 | dd_llm_client（LLM 直连） | 深耦合 dd_response API | 高 | prompt 未版本化；候选上限只是 prompt 文本 | **不接入 #71 考生路径**；仅作历史对照 | 三入口 trace 0 命中；引用面仅 dd_response.py/assets.py/package_gap/synthesis（grep 实证） |
| 入口 A CLI | tools/dd_team_channel.py（326 行） | 已合入，仓库内端到端测试在（test_dd_v1_policy_and_entry.py:152） | 2026-10-15 | 同上 | 依赖五服务 | — | 低 | 无组包子命令（docstring 的 --package 是死文档，argparse 无此项） | **A1 接线首选入口**（Team Channel 语义最贴合，纯规则链无需 key） | 本轮 exit 0 全链实跑 |
| 入口 B CLI | tools/dd_v1_local_run.py（207 行） | 已合入，仓库内测试在（test_dd_v1_local_run.py） | 2026-10-16 | 同上 | adapters | — | 低 | 无模型时 exit 2（设计信号，需 A1 文档化避免误报故障） | **A1 语义建议入口**（manual/dsh 可插拔） | 本轮 exit 2 + RULE_ONLY 实跑 |
| miniMAX 监工/AUX | dd_v1_agent_adapters.MiniMaxPiAdapter | 已合入 | 2026-10-16 | 同上 | pi CLI | — | — | 董事长批准前不计考生（scored=false） | 本轮未验证运行 | 代码级存在性证据（UNVERIFIED 运行） |

Matrix 外显式排除（有成本/密钥风险的候选必须显式排除并留理由——样板即 dd_llm_client）：
- 付费 OCR：未验证、未授权、A0 禁止 → 排除。
- 任何外部 API：同上 → 排除。
- 第二个 GM/调度器：任务书禁止 → 排除。

## 2. 最小 Adapter 契约（A1 接线目标；不写实现代码）

**定位**：A1 = 「Team Channel 语义建议」薄桥。把入口 B 的语义建议链（split→packet→adapter→两层校验）接到 Team Channel 的材料库/清单流程上，复用 A0 已验证的 FOS 既有函数，不自造检索/组包。

**最薄接口（输入）**
1. `library`（已登记材料库）+ `material_root|snapshot`（经 manifest 校验的只读快照；真实材料必须 `--allow-real-material` 且仅本机；仓库内 fixture 自动豁免——`local_material_snapshot @309` + `_inside @336`）。
2. 机构清单条目（`item_id + raw_text`，原文零丢失）。拆解先行：`split_items @82`；拆不出的条目**不得**送模型（本轮 R3 实证 NEEDS_HUMAN_SPLIT 状态直传人工）。
3. `adapter` 选择 + `Budget(timeout_s, max_calls)`；付费路径（dsh/codex/minimax）必须显式 opt-in 开关，且 cost 未知时 fail-closed（`run_agent @385-386` COST_UNKNOWN_BUT_REQUIRED 已有）。

**最薄接口（输出）**
1. `run_id`（audit 链）+ `source_snapshot_id`（本轮实测样例 `snap-ec8e949e8d0531dc`）+ FOS commit/SHA（A1 起写入）。
2. packet 指纹（packet.json sha256）+ 每文件 sha256（`sha256_file` 实证）。
3. 模型实际使用标识：`adapter.adapter_id/vendor/role/model_id_or_UNKNOWN/cost_usd_or_UNKNOWN` + attempts（重试序列）。
4. 唯一权威结果层：`authoritative_validation=semantic_validation`（结构层 R4 只是中间结果——本轮实测字段语义，A1 不得读错层）。

**DS_AGENT_SUGGESTION vs RULE_ONLY 区分（硬契约）**
- `mode=AGENT_SUGGESTION`：模型输出通过 R4 结构校验 + 语义校验（主体/期间/版本/locator/禁判 deliverable 等全部通过）。只有此 mode 可标记「模型已参与语义判断」。
- `mode=RULE_ONLY` + `degrade_reason`：模型未参与（调用失败/空输出/坏 JSON/非结构化/工作区污染）。降级原因**必须**原样落 run_record（本轮实测 `AGENT_CALL_FAILED:PENDING_MANUAL:...`）。
- CLI 不存在/超时：`run_cli` → CALL_FAILED/TIMEOUT → RETRYABLE 内按 `budget.max_calls` 真重试（@377），耗尽后降级 RULE_ONLY。
- 耗额：`BUDGET_EXCEEDED`（cost 超 cap 或 cost 未知且 require_known_cost）→ 同样显式降级。
- 全程禁止把 RULE_ONLY 写成模型参与；无模型轮次的退出码 2 是**设计信号**不是故障（本轮实证）。

**FOS 侧硬校验归属**
- 来源/路径/hash：`load_snapshot`/`sha256_file`/`PATH_OUTSIDE_SNAPSHOT`（agent_result_service + semantic service）——FOS 负责，模型输出里的 file_id/path/sha 全部回对快照，伪造即拒（CANDIDATE_NOT_IN_SNAPSHOT/PATH_MISMATCH/SHA_MISMATCH）。
- 主体/期间/版本：`validate_semantic @257` + non_effective 集合（DRAFT/SUPERSEDED 不得 MATCH/PARTIAL）。
- 披露/外发：dd_v1_policy_service（未配置=全部不可外发）。
- 人工批准/复制：package_approved @385（闸先于复制、按义务编号建目录、blocked 显式列出）——模型永远不能置 approved/deliverable（FORBIDDEN_VERDICT）。

**A1 范围红线（从 A0 证据直接导出）**
- 不改五服务的判定/检索算法；只做调用编排与结果透传。
- 签章维（seal_status 恒 UNKNOWN）与数量权威缺口**不在 A1 修**——如实透传为缺口/UNCERTAIN，等待 A2/A3 需求驱动补齐。
- 任何时刻不使用 dd_llm_client 直连路径；不读取 Gold；不向 packet 注入清单答案。

## 3. A1 需要司仓/独立 Reviewer 先裁决的点
1. dsh 真实降级证据是否必须实跑一次（涉余额）→ A0 未跑，待授权。
2. A1 接线宿主：建议=Team Channel 命令包装（入口 A 编排 + 入口 B 语义建议子链），避免改 cangjie-teams-channel 产品仓（其 PR-Gate 另行办理）。
3. `minimax-pi`/`codex` 适配器在 A1 是否纳入真实验证（都涉外部 CLI 与账号）。
