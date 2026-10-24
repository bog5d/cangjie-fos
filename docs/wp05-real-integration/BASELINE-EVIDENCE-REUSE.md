# 已知基线、证据分层、Skills扫描（本轮Spec的取证回执）

## 数据来源与范围
- FOS官方事实源：bog5d/cangjie-fos master `a7a7e24977eeb40b62e1b34d39d9d4a58dadd28d`，#71仍OPEN；本次读取多个核心文件，未在Mac/Windows运行程序。
- Team Channel官方入口：bog5d/cangjie-teams-channel main，员工AGENTS明确「同事只提需求、司仓统一开发」，不能把刘江业务测试视作授权产品仓开发；FOS #71有自己的集成路线。
- 工程规范：bog5d/grill-to-spec main README、START_HERE、SCP-v3.8、HARNESS、GCCSEG、ESCALATION。
- 报告：刘江《DD-V1 Team Channel真实组包全链路审计与开发建议｜2026-10-21》9页，本次聊天上传。**原始测试脚本、42行逐题CSV、当轮快照及Gold并未在GitHub检查中取得**；因此本轮只能核实报告主张与代码存在性，不可证明42题具体归因准确。
- 独立进展：Mac GM single master/Lease、MiniMax监工V0.3 Cron、实际Windows DSH调用能力均UNKNOWN，必须现场核实。

## 现状证据矩阵（可直接在工程验收填写）
| 主张 | 来源 | 验证级别 | 下一步必要证据 |
|---|---|---|---|
| FOS旧DD-V1有manifest、parser、card、match、package、prefetch等组件 | FOS master源码 | 当前代码存在 VERIFIED | 使用这些组件的真实trace / 输入输出 |
| FOS DSH单机runner有score/opt-in，候选≤6（指定语义路径） | FOS master脚本/常量 | 当前代码存在 VERIFIED | 本次Windows实际使用入口及配置 |
| 刘江42题 24/13/5 / 严格正确率57.14% | 2026-10-21报告p1,p4 | REPORT_ONLY | 原始42行CSV、Gold、实验脚本与环境 |
| 刘江所谓“考生二”用4个临时脚本而非FOS | 报告p1–p3 | REPORT_ONLY；与FOS官方考生编号冲突 | 当轮脚本源码真实调用栈、commit/hash |
| 第五轮补80份Gold并通过题号目录可能泄漏 | 报告p2,p5 | REPORT_ONLY，公允成绩不可用 | 标识泄漏样本、冻结快照、物理Gold隔离 |
| 扫描件NO_TEXT_LAYER=264份、12题受影响 | 报告p5 | REPORT_ONLY，不代表FOS解析能力为0 | 每文件读写权限、OCR离线/外部授权与真实索引 |
| 存在9条“不全仍MATCH” | 报告p5 | REPORT_ONLY | 机构原清单、所需覆盖证据来源，不得将Gold反喂推理 |
| PDF报告称WP00–WP04合并，WP05–07无目录 | 报告p6 + Github主分支 | 代码提交层 VERIFIED，独立真实业务验收UNKNOWN | 同SHA独立Review、真实Windows验收 |
| 审计报告已PR推送 | 未在当次FOS open PR观察到 | UNKNOWN/未见证明 | PR号/commit/链接；不可声明已合并 |

## 复用扫描
先检索现有内部代码/Skills/成熟方案，避免重造轮子。原则：真正*可复用性*应以兼容的接口/测试/数据安全证明，而不只是代码文件名。
| 候选 | 状态/风险 | 决策 |
|---|---|---|
| FOS dd_v1_manifest/parser/requirement/card/match/package | 已有测试与代码，接口对齐/真实调用UNKNOWN | **优先复用**，薄Adapter接线 |
| FOS dd_prefetch/dd_index/dd_match | 已有正文预热/旧匹配逻辑，可能与新DD_V1不兼容 | **先Spike对比**，按需复用 |
| FOS dd_v1_agent_adapters + result/semantic validation | 既有结构化模型校验，无权威“31份”Gold数量 | **优先复用**且补需求驱动集合约束 |
| 旧exam2_lib/package_exam2/score_exam2 | 报告称与FOS不接通；来源代码不在本轮提交 | **留作历史对照/诊断，不作为正式引擎** |
| 现有GitHub Actions / 本地受控CI runner | Actions付款可能阻塞；本地候选不是required check | 继续独立测试但正式Gate按合规规则 |
| Skills: cangjie-fos-project | README历史记录v0.6.8、605 tests，明显早于当前FOS状态 | 仅复用TDD/注意事项，**不可拿旧版本基线当事实** |
| Skills: independent-acceptance-review | 有PR逐项复核、ghost命令与工作区篡改负例 | **本次复用其独立Gate检查法** |
| Skills: continuity-audit-cangjie-gm | 有“代码存在不等于接线”、只读取证、异常状态判断 | **本次复用其监工判活与防假活思路** |

> 本轮Skills库：发现可访问`bog5d/bog-global-skills` master；遍历active技能路径约476条，按名称筛选3条并实读上述3个SKILL.md。本轮为Spec编写不是已运行Mac开发；相应技能的真实跨模型执行与独立验证尚未发生。

## 本轮回执（截至Spec PR创建）
- Skills：扫描候选约476｜命中3｜读取3｜文档层实际复用2｜新增候选0｜升级0｜独立验证0｜跨端加载0（后四项未执行/无可验证证据）。
- GCCSEG合同：生成v3.8 L2并进行了字段/权重100分的基础结构自查；中央`check_gccseg.py --require-v3-8`尚需真实执行，**目前不得报中央Gate PASS**。
- 工程进度：A0–A5独立Reviewer PASS 0/6（本新增集成计划）。结果积分：0/100已验证（全项UNKNOWN），实际能力强弱未知。初始化仅用于冻结尺子，不伪装已有代码退化。
- 当前SPEC草案/说明书仅属于Planner交付。下一步：GM真实ACK、取得唯一Lease、A0真实入口合成trace与独立Reviewer、A1最薄集成代码PR。
