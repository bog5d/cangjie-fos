# DD-V1 实引擎接线｜PROJECT_ROADMAP / PLAN / TASKS / ACCEPTANCE / PROGRESS

> 适用于 FOS #71 的**增量开发子计划**，不是覆盖FOS全项目 Roadmap，也不是新增GM任务库。若与已登记WP命名冲突，保留本目录 A0–A5 作为子工作包，不给原WP00–WP07改编号或改完成率。所有日期、Lease、PR状态以现场最新事实为准。

## 1. 生命周期（冻结）

```text
PROJECT_COMPLETE = false
CURRENT_PHASE = PHASE_A 实引擎接线（待GM正式ACK）
CURRENT_CHILD = A0 现场事实+合成断链基线
NEXT_ACTION = GM只读核实单主/租约/已有执行器 + ACK；让唯一Executor拿A0开始
BASE_CODE_FOS = a7a7e24977eeb40b62e1b34d39d9d4a58dadd28d (2026-10-16; 执行前fetch核验)
BUSINESS_BASELINE = UNKNOWN (旧57.14%是DSH临时脚本NON_BLIND)
LIFECYCLE = A0→A1→A2→A3→A4→A5；每项必须独立Gate
```

### 每阶段输入→输出→Gate

| 子WP/目标指标 | 具体任务/依赖 | 用户可观察成果 | 验收反例与证据 | 状态 |
|---|---|---|---|---|
| **A0** O1 | 读取 GM/FOS/TeamChannel当前main或master+唯一writer/Lease；用非敏感合成样例复现临时脚本不走FOS，制作函数调用图/环境与基线、当前旧FOS各模块复用矩阵；选用本机有效入口（不是GitHub导出文件推测）。依赖：GM有效现场仅用于派工；可先只读。 | 看到原临时路径和官方FOS路径差异以及要接的最薄接口；保留源证据/commit。 | ①实际 import/调用日志/trace；②相同合成输入不触碰Gold或客户原件；③独立Reviewer确认工作目录/生效配置，失败不假装FOS已接线。 | NOT_STARTED |
| **A1** O1 | 尽量只加**薄的调用Adapter/CLI组合**：Team Channel选定官方FOS入口、传清单和material_root/snapshot，FOS adapter调用DSH作语义判断，输出语义建议和调用源证明；不重做BM25/搬原件。依赖 A0。 | 由Windows形式的CLI走FOS核心代码，结果标明FOS commit/版本、模型、packet hash、run id。 | 合成3个fixture：正常、DSH不可用明确RULE_ONLY、临时脚本伪装必须失败；trace能同时看到FOS Manifest/检索/校验真实函数被调用。 | NOT_STARTED |
| **A2** O2 | 接通FOS既有Manifest/Parser/MD/全文索引与多路高召回，不强制全文件上传模型；按主体/期间过滤、分页/分批候选直到确定性范围覆盖或显式截断。先修导致实际错题的入口，OCR付费后置。依赖A1。 | 对“需31/40份”合成结构能召回/列出所有候选或真实缺项；二进制正文已提取则可用，不是只给文件名。 | 至少覆盖：同名多主体、多年度、版本、>6候选、同目录MD原件双层映射、OCR关闭时无正文明确UNKNOWN、无召回/召回耗尽不可判MISSING。检索召回真实样本改进需相同快照对照，失败不算性能提升。 | NOT_STARTED |
| **A3** O3 | 优先复用 dd_v1_match_service.judge + policy + agent/semantic validation，补缺的**需求驱动**主体/年度/附件/数量覆盖；无法求出应有份数则UNCERTAIN，人审可补权威范围；使用FOS package_approved精确副本集合，杜绝同目录顺带复制。依赖A2。 | 找到9/31不能声称找齐；推荐、批准、组包、评分数量账一致。 | 合成：需5选3→PARTIAL；应有数量UNKNOWN→UNCERTAIN；错主体、旧版、附件缺失→拒MATCH；模型故意给MATCH也被拒；无人工批准不可复制；只选1则只复制1（不顺带12/74）；SHA全一致，拒外发。 | NOT_STARTED |
| **A4** O4 | Gold与执行主机物理/权限隔离、补料路径去考题编号、冻结同一快照/人工确认Gold，三考生编号按FOS #71定义；先合成盲测，再由刘江Windows授权后真实42题同库复跑，完整评分。依赖A3，真实材料或对外模型敏感数据无授权则保持BLOCKED而非越权。 | 得到可信FOS+DSH成绩及逐项根因、误配、召回、人工分钟和费用状态；不拿旧57.14%作公平对照。 | 生成：snapshot hash、Gold隔离证明、模型真实输入输出trace、精确file_id映射、无考题编号泄漏、42题逐题得分；可同快照跑旧临时脚本对照但不能让其接触Gold；若有真正盲测合规新基线才计算Δ。 | NOT_STARTED |
| **A5** O5 | Reviewer核对A0–A4全部硬Gate、GM合法Lease/外部唤醒/续棒演练、历史会话结束后下一WP有效产物，业务操作员确认；Skills复盘及审计。依赖A4或因安全阻塞仅做不触敏步骤。 | 双账完成、可交给下一位员工复跑、单主续棒可证。 | 真实Mac在无旧聊天会话时产生新一次合法调度→唯一Executor→产物→独立Gate→自动下一项；原记录与现值对比，没真实数据不宣称无人值守；Skills数字及跨端加载证据。 | NOT_STARTED |

**WP晋级**：只认独立Reviewer PASS，代码提交/静态检查/自述通过均不等于Gate PASS。单个WP FAIL→返工；BLOCKED→写恢复动作和下个安全事项；UNKNOWN不计分，绝不假装完成或自动跳阶段。不得为赶时间把A1/A2/A3合一大包。

## 2. 全局验收硬Gate（任一未PASS禁止封箱）

| Gate | 通过条件 | 反例 |
|---|---|---|
| HG-01 单writer/单GM | 有独立验证的当前有效owner/Lease/唯一执行器工作树/真实ACK | 两实例写同分支、Issue评论当作ACK |
| HG-02 真实FOS调用 | 本轮 run_id、call_trace含官方FOS代码入口及可验证算法/校验，版本固定 | 只看文件存在、重写exam2_lib跑分 |
| HG-03 Gold盲隔离 | Gold在执行机不可读位置；评分者与考生隔离；路径无题号 | 99_补齐材料/题号、执行时可读Gold |
| HG-04 数据与费用 | 仅授权目录；无敏感外发、无额外费用或显式审批 | 合成测试不授权真实数据外发 |
| HG-05 无假MATCH | 应有材料未齐/未知时非MATCH（需来源）；wrong entity/version/part均拦 | 9/31仍MATCH、用Gold数量偷偷判 |
| HG-06 人工+精确交付 | 仅已人工审核集合复制，文件hash全对、无同目录扩张、未自动外发 | 选1复制12/74；原件被移动 |
| HG-07 Reviewer独立 | Reviewer与Executor相分离、同一SHA运行正反案例并给出命令/退出码/证据 | Executor自己写“PASS”、CI根本没启动 |
| HG-08 真实Windows闭环 | 刘江实际Windows执行正式CLI、授权资料、盲Gold再评分 | Mac合成fixture冒充Windows |
| HG-09 无人值守续棒 | GM唯一调度，聊天会话退出后真实接棒有工作产物；Cron/通信链合法 | 心跳更新、Cron存在、留言送达即报成功 |

## 3. 双进度条（首次施工前固定分母，禁止漂移）

### 工程进度
此**增量集成计划**的唯一分母：6个 A0–A5，每个独立Reviewer PASS计1，`engineering_percent=PASS_COUNT/6*100`。当前**0/6=0%（新计划尚未独立验收）**；FOS原WP00–WP04已合并单独旁栏，不加入本计划分母。PR打开/通过静态检查但未Reviewer PASS，仍计0。

### 终局效果（L2 100分）——不等于模型准确率
事前固定5项、100分，只有真实验收证据为REAL_PASS才计该项分，不能用隔离模拟证据骗取终局分：
- O1 **真实FOS调用链** 25：真实Windows FOS函数trace+DSH语义参与、版本/快照/执行器标识。
- O2 **正文索引和召回** 25：真实文件覆盖统计、同快照基线/改后关键召回不劣、缺项来源、>6候选无静默丢失。
- O3 **齐套与精确组包** 20：真实机构需求可知应有集合时0假MATCH、无法知集合显式UNKNOWN；人工批准后实物hash一致、无多复制。
- O4 **Gold盲考** 20：真实42题或有证据的可比固定集合、Gold完整隔离、冻结可比同快照、各考生计分与原因分类。
- O5 **无人值守接棒** 10：真实Mac GM离开会话后的独立唤醒、唯一Lease、真正下一个WP产物及Reviewer收口。

初始状态：`effect_points=0/100`、**各项UNKNOWN（尚未验证，不代表能力实际为零）**。若某项部分达到，先列独立案例覆盖率，直至该项REAL_PASS才得该项分，不用随意增加半分。变更权重/分母需显式版本批准和旧分数可比说明。

### 关键业务附表（非进度条替代）
`strict_accuracy=gold全部正确题数/有效Gold题总数`; `gold_recall=正确找到Gold原件数量/当轮材料库可用Gold原件数`; `false_MATCH=机器报MATCH但独立审计不齐项数`; `copy_integrity=hash一致的批准实物/应复制实物数`; `manual_minutes/100_items`; `p95_runtime`；同时分清缺材料/无索引/无召回/错选/假MATCH/组包扩张。分母为零必须N/A，不自报100%。

## 4. 监工节奏与快照格式

由 **MiniMax独立监工窗口** 使用既有授权Cron（默认约20分钟；先现场核验活性/权限，禁止盲增）。任意新进展不是按时间自动加进度。每轮在**现有GM权威事实源**存储快照或链接（不得自建第二任务库），字段：
```text
at_cst | project | gm_work_id | executor_id | lease_holder | wp |
commit_sha | pr_url | gate_status | valid_evidence_ids | effective_artefacts |
engineering_pass_wps/6 | outcome_REAL_PASS_points/100 | goal_gap |
productive_or_waiting_or_stalled_or_blocked_or_unknown | last_action |
next_action | escalations | wake_delivery | new_session | reviewer_receipt
```
微信/手机状态卡按下述完整口径：
```text
【监工 HH:MM｜DD-V1实引擎集成】
终局：刘江在Windows用DSH+真正FOS组包，并通过盲测
工程 ███░░░░░░░ 0%（0/6独立Gate，较上轮±0）
效果 ░░░░░░░░░░ 0/100（未知，关键HG：x/9 PASS）
活跃：UNKNOWN｜是否该踢：NO/YES（证据）
本轮有效成果：1–2项，无则无可验证进展
关键缺口：不超过2项
下一步：xxx（现有GM Owner）
预计剩余：UNKNOWN（无历史速度不能乱猜）
无人干预：独立Gate+X｜人工请示Y｜误唤醒Z
Skills：检索X｜命中X｜复用X｜候选X｜升级X｜独验X｜跨端X
证据：PR/Commit/Gate URL｜最新快照时间
```

## 5. 总进度与状态转移

`INTAKE→SPEC_READY→GM_ACKED→LEASED→EXECUTING→REVIEWING→{PASS|FAIL|BLOCKED}→NEXT_WP`。
文档PR/Issue评论只能到`SPEC_READY`，**不能冒充GM_ACKED、LEASED、EXECUTING**。出现双主或未能确认唯一Lease，暂停变更运行态和新派工，先观察/安全收敛；不得开启第二调度。

- 当前有实测的Mac跨会话唤醒与外部定时器才可说AUTO_RESUME_READY；没测就是UNKNOWN。
- 测试专用一次性runner不是长驻调度，不自行建立守护循环。
- GitHub Actions账单导致CI未启动：本地测试可继续，但不伪装required check；正式合并须按原Gate或经用户授权变更的正式替代Gate。
- FOS工作包的Reviewer/监工不重复执行者职责。MiniMax监工每20分钟仅观察，发现无新产物超过25分钟才核查，合法且非忙碌才唤醒原session；三次无效进入冷却。

## 6. Skills进化回执合同
开发前检索bog5d/bog-global-skills当前master active技能，以name/description匹配，最多按需读取1–3个SKILL.md；优先复用成熟的代码/流程；历史fos速查Skill中的605 passed是旧数据，**以当前仓库pytest为准**。开发过程记录踩坑→根因→修复→正反验证；只对复用价值高的经验形成candidate，不直接合入/发布。候选→Reviewer→批准→Skills PR→跨端加载验证，分阶段回执。

每个 WP 的Review回执必须有：
`Skills: 检索X项｜命中X项｜读取X项｜实际复用X项｜新增候选X项｜升级X项｜独立验证X项｜跨端加载X项`，无则填0并说明；未经证据不能报成功。
