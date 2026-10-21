# DD-V1 · 真实引擎接线修复｜INTENT / CONVERGE / SPEC / ARCHITECTURE (2026-10-21)

> **本文件状态：候选施工规格（docs-only），不是代码已实现、GM已ACK或生产部署。** 原需求 FOS [#71](https://github.com/bog5d/cangjie-fos/issues/71)，司仓唯一控制面 cangjie-gm；产品仓 FOS master a7a7e24977e。优先核实现场最新版本。关联源：刘江《DD-V1 Team Channel真实组包全链路审计与开发建议｜2026-10-21》（本会话PDF，未传GitHub）。

## 0. 人话北极星（冻结）

**一次让员工在Windows通过DeepSeek Harness加载Team Channel，把机构尽调清单交给真正的FOS，取得有来源、有缺口、有正确原件且需人工审批的材料建议和精确组包；用独立Gold盲测与独立Reviewer证明效果。**

坏例子：临时4个脚本完成检索/组包/打分，在旁边考试，不能代表FOS上线或准确率。刘江报告称54条清单/42条计分、24严格正确/13部分/5未匹配，历史报告的57.14%**NON_BLIND**，不能作为新FOS产品有效准确率；报告缺逐题CSV和真实本机脚本副本，尚未独立复现。报告另称路径含Gold题号。**不允许只去掉15条正确题就宣称真正21.43%盲测准确率。**

## 1. Converge：已知P0 / 显式未知 / 非目标

### P0 已知，无需再次请董事长重复批准普通开发决策
1. **正式对象**：DSH通过Team Channel调用**FOS现存实现**；模型参与真实语义判断；FOS负责受控检索、快照、结构校验、权限、人工审核与交付。不得考试时临时重写完整BM25/组包/评分器。
2. **事实源**：FOS #71 当前master、TEAM CHANNEL main的入口规则、GM main唯一任务/lease；不得在Team Channel冒充组包算法真源。
3. **结构**：复用 dd_v1_manifest/parser/card/requirement/match/package、dd_index/prefetch及 dd_v1_semantic_retrieval/agent_adapters；对现有组件做调用链映射和兼容适配。候选上限6、类型字典7项只是**某一代码路径**的已知限制，不应认定Windows考试真实走了它。
4. **不让Gold给模型**：需求齐套基于机构清单、可信权威主体/期间/附件清单推导，绝不让模型拿Gold文件数当完成条件；无法推导应报告UNKNOWN/UNCERTAIN，需要人工提供范围。
5. **考试公平**：同一冻结输入、授权资料、快照+基准模型/版本、Gold**不在执行主机可读区域**；评分在运行完成后独立主机/阶段。可用匿名稳定file_id映射，但**不可有考题编号、标准答案标签或路径泄漏**。
6. **数据**：真实材料本地Data Plane，GitHub只保存源码、合成fixture、脱敏证据。外部DSH发送文件名、目录、摘录，须先取得相应敏感数据发送授权；未获授权仅合成测试。OCR若走DashScope/API可能额外费用，未经授权不得启用。
7. **单主三角色**：司仓唯一Planner/调度，唯一有效Lease的Executor写业务代码，MiniMax独立监工观察/催动，独立Reviewer只评Gate；独立监工不写代码不启第二GM，不从另一终端抢Lease。
8. **硬判据**：文件缺项不能MATCH；更不能以非正式临时脚本的成绩冒充FOS的成绩；PR提交/CI/心跳≠真实业务验收。
9. 继续使用已经收敛的#71/R1-R9，**不新建重复产品需求体系**。新阶段只填实际断链的工程差异，旧FOS WP1–WP7工程进度**不并入本WP分母**。

### P1 待现场实证后再定
- DSH在刘江Windows上的CLI版本、profile、订阅额度和允许的受限工具；Team Channel真实调用/脚本、FOS旧代码与新DD-V1服务之间的 schema 合法映射；各格式正文解析和可靠file_id映射。
- Mac mini实时GM Lease、已存在Cron唤醒/独立监工跨会话通信能力；任何GitHub Actions计费/权限障碍的当前状态。
- 42题每条真实当轮可用材料数/Gold有效性、15题泄漏方式；在未知时**不编造真实性指标**。

### P2 Backlog
前端Web、GraphRAG、复杂多租户、全公司同步、微调、自动外发、新增独立调度器及重建OCR大框架。

## 2. 业务要求（可观察的输入-输出）
- **输入**：尽调清单原文件/本地授权解析JSON、合法机构编号、主体范围与期间/版本/签章/附件要求；受控material_root、可选既存md_text_root；一个冻结不可变snapshot_id；选定Adapter（DSH/Codex）及限制次数。
- **处理**：明确正式入口及工具调用契约 → FOS读取/建立Manifest（路径、hash、元数据、权限）→ FOS已有解析/预热+索引/FTS → 高召回分层候选池（可扩大候选总量但不一次给模型全部）→ 模型受控选择附有file_id、hash、locator、原因的建议 → FOS确定性四维/更多完整性判断及安全Gate → 人工确认 → FOS组包，只复制审核通过的精确文件列表。
- **输出**：每题：原编号+原文、拆解义务、需满足的实体×期间×材料类型×必备附件/数量（来源/未知）、检索证据与召回记录、被选候选、错配/缺口/版本/披露状态、人工审核状态；实际包的清单及逐件SHA；评分只在独立Gold阶段产出。
- **失败**：没法解析→UNPARSEABLE，不推断不存在；没检索/索引异常→UNSEARCHED/UNKNOWN，不伪称MISSING；不能确认所需数量→UNCERTAIN，不假MATCH；模型失效→RULE_ONLY并明确原因；材质受限→RESTRICTED；费用不足→BLOCKED并继续做不花费的合成测试。
- **非目标**：自动向投资机构外发、由AI自行批准敏感材料、以Gold训练/推理、依赖大模型逐文件遍历22GB、重复开发已验收功能。

## 3. 工程架构与模块复用边界

```text
Windows: 刘江/Team Channel(员工交互壳、只负责选择正确入口)
        │ 只调用版本化FOS CLI/API薄Adapter；保留原清单编号、approved root、snapshot
        ▼
FOS Kernel: Manifest + Parser/Prefetch/MD映射 + FTS索引/卡片
        │   按Entity/Period/DocType/Version结构过滤 + 高召回/分批读取正文证据
        ▼
FOS Agent Adapter: DSH/Codex（只做语义建议、按 Schema 输出）
        ▼
FOS Judge: 现有dd_v1_match_service.judge为优先核查对象
           + Agent Result/semantic validation + disclosure policy
           + 需求驱动多件齐套（未知时UNCERTAIN）
        ▼
Human Gate: 审批后FOS package_approved（精确副本集+SHA，不顺带同目录）
        ▼
Windows Deliverables: review.csv/json, missing_report, approved_package_manifest
        │
独立评分主机/阶段：盲Gold → verdict/file_id全集比较 → 分层误差+时间+费用
        └→ FOS #71 Evidence/Regression（脱敏）
GM Mac: 唯一工作包/租约/执行/恢复；MiniMax 独立监工/Reviewer观察（非第二GM）
```

**注意**：代码里已有 `dd_v1_agent_result_service.validate_agent_output` 负责引用/hash/主体/期间，`dd_v1_semantic_retrieval_service.validate_semantic` 有parts检查，但它们并非“拥有31份权威数量的金标齐套器”。需从原清单提炼规范义务/可信主体清单或人工补充清单，而非读取Gold猜数量。旧 `dd_match_service.run_matching` 与 `dd_v1_match_service.judge` 是不同路径，应先对比再复用，禁止靠函数名硬连。

### Kernel / Pack / Extension
- Kernel：Manifest、来源/hash校验、受控检索、Agent schema、Gate、抽象材料证据及组包契约，不写泽天/机构特例。
- Department Pack：尽调类型词表、主体/期间/签章/附件拆解、财务材料业务规则。
- Company Extension：具体公司材料库路径、别名映射、权限策略、文件命名、机构模板；配置化，不写进Kernel。
- Team Channel：入口Router + 进度显示 + 审核入口；DD核心不迁入TeamChannel。

## 4. 已有能力 / 必查入口（先做reuse matrix，不可简化为“全部可复用”）
| 模块 | 已有迹象 | 必验接线与限制 |
|---|---|---|
| `tools/dd_team_channel.py` | FOS DD-V1确定性6步入口 | 是否真的带模型Adapter；当前主要规则型 |
| `tools/dd_v1_local_run.py` | DSH/Codex + score分离 | 默认仅CSV/JSON，不是完整文件组包；借助FOS整体路径 |
| `dd_v1_semantic_retrieval_service.py` | 7种类型、每义务6文件、300字文本片段 | 不能直接替代全库召回；分层检索、分页/多附件需改 |
| `dd_v1_match_service.py` | 候选召回、覆盖 judge | 实体×年份×类型×附件是否足以证明“一题31份”；检索分支权限 |
| `dd_v1_package_service.py` | 审核闸和文件SHA | 精确选择集/完整源hash/不会复制同目录多余文件 |
| `dd_prefetch_service.py` | 文字层预热、MD缓存 | 扫描件OCR不是无成本；已有缓存能否映射原件 |
| `dd_v1_agent_adapters.py` | CLI模型适配/回执 | 真机 CLI 命令和订阅可靠性，失败回退是否显式 |
| `dd_v1_experience_service.py` | 经验候选记录 | 仅在人审后留纠正反馈，不自动污染规则 |

## 5. 安全/权益
- 代码/修复PR只在FOS隔离分支，由GM单一调度；未经允许不触碰Team Channel生产入口、Mac live controller、Windows原件。
- 密钥不写日志。不要使用历史Skill里的token-in-URL片段，使用操作系统合法凭据管理器。
- 合成单测可在云端；Mac负责GM持久调度、隔离开发及复核；刘江Windows负责真实运行验收。云端不能访问Windows真实Data Plane，不要声称完成真实验收。
- FOS #71以Codex独立、Codex+FOS、DSH+FOS定义三个考生；刘江历史“考生二”应标`DSH-TEMP-BASELINE`，不得污染正式编号。

## 6. What counts as shipped
- 开发Spec/PR合并=工程产物；合成测试通过=隔离功能；Windows盲测+真实FOS调用+人工确认+hash+独立Reviewer=业务证据；GM真正会话外恢复/下一WP=持续性证据。
- 任何 P0 缺口 (Gold隔离、数据安全、伪MATCH、无FOS真实调用、单写者冲突) 未通过，项目不封箱。
- 计划、验收矩阵、进度双账、状态快照、两套启动指令与Skills回执见同目录其他文件。
