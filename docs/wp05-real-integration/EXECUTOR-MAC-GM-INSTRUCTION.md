# 执行器启动指令（复制到 Mac mini 现有司仓执行端）

> **权限边界**：这份指令允许在GM完成现场单主核验且实际ACK/LEASE后，由唯一Executor开展FOS #71 **隔离分支上的合成数据功能开发、测试、建PR**。它**不是**自动变更生产GM、部署、读取真实涉密Data Plane、付费OCR/DSH、绕过GitHub必需门禁或自动合并的授权。若没有Mac实用权限，则回报不能启动，不得声称后台运行。

## 0. 理解目的（开工复述）
原来我们已建了FOS材料登记/检索/规则审核和组包能力，刘江却用DSH+Team Channel旁边重新写4个脚本考试，得到的NON_BLIND 57.14%不能评估FOS。你的任务是**接通真FOS**，先从A0/A1小WP施工，再循序推进，不为提分重造新引擎。

## 1. 接入唯一总经理，不得直接抢施工
1. 找现有Mac mini上的 cangjie-gm 真仓与生效路径，记录 git remote/branch/HEAD 和当前工作区；**路径以真机为准**。
2. 按 cangjie-gm 当前main 的 AGENTS.md 逐序读 CHARTER.md、principles/SCP.md、data/assets.json、data/job_state.json、config/scan_roots.json；执行规范允许的 `python -m gm.cli validate`。先只读核实 owner/Lease、现有任务、Cron与活跃执行器。**当前双主问题未经现场证明修复，绝不新建/启动第二控制器**。
3. 检查已有GM #214 文档登记（**未合并main，不能当实际ACK或租约**）、FOS #71及子PR、各Executor是否工作中。检查本集成SPEC PR是否已获独立Reviewer接受。若已有真实Owner/Lease→**通知既有司仓队列登记并等待合法分配**；不得覆盖别的执行器的工作。若未验证单主→停止运行态写操作，转只读开发准备/合成代码研究；把阻塞提给唯一GM。
4. 正式 ACK/Lease 后，从现有GM恢复机制合法派遣唯一Executor，留有 `gm_work_id, owner, lease_id, expires_at, wp=A0, executor_session, start_sha, next_action` 的真实可核对回执。**GitHub评论不是唤醒，也不是合法Lease**。

## 2. 读仓 + 按SCP v3.8/GCCSEG开工
中央规范：bog5d/grill-to-spec 当前main的 README、START_HERE、SCP-v3.8、HARNESS、GCCSEG、ESCALATION；按`scripts/check_gccseg.py --require-v3-8 <contract.json>`真实运行，贴完整退出码/日志。**本文件的PR并未代替此机读Gate；失败先修合同。**
FOS：bog5d/cangjie-fos master AGENTS.md、CLAUDE.md、CODEX_TASKS（若使用Codex）、#71、WP02-Goal Contract、WP00–WP04 evidence、`tools/dd_team_channel.py`、`tools/dd_v1_local_run.py`、解析/索引/匹配/包相关核心模块。
Team Channel：bog5d/cangjie-teams-channel main AGENTS.md、START_HERE、Roadmap、SPEC、ARCHITECTURE、REQUIREMENT_FLOW。
本SPEC目录内阅读：INTENT-SPEC-ARCHITECTURE、PROJECT-ROADMAP-PLAN-TASKS-ACCEPTANCE、GOAL-CONTRACT.v3.8、这份指令、监工指令。
Skills：bog5d/bog-global-skills 以实际master可用性检查，按 name/description 搜索且**最多加载1–3项**，不无差别灌全库；每个WP产出Skills回执。

## 3. 先做A0，再做A1，其他WP不得抢跑
**A0：基线+确认真实入口（不用客户原件）**
- 固定代码的完整SHA、配置、执行器CLI实际版本、测试命令与环境；现场基线同运行环境下跑当前适用的 backend tests，既有失败留记录，不随意skip。
- 用合成fixture启动**原正式入口**，记录代码堆栈/明确的call_trace：Team Channel→FOS哪条入口；检查旧 `dd_v1_match_service`、`dd_v1_semantic_retrieval` 和旧`dd_match_service`的角色、签章/附件/数量可否证明全部齐套。
- 出 reuse matrix 与最小Adapter契约，说明哪些能力有/无，哪些仅是假设。只要证据不足标UNKNOWN，不把审计PDF“全部VERIFIED”照抄为运行事实。
- 独立Reviewer验收A0：同一合成资料、真实入口调用行号及运行证据、无客户Data Plane、无新增付费；失效例包括临时BM25虽得分但FOS call_trace为空→FAIL。

**A1：薄集成补丁（合成）**
- 只实现必要的Team Channel→FOS调用薄桥/适配（或FOS已有直接入口的命令包装），可从FOS加载既有Manifest/索引/可读取的正文与受控Agent调用；别整体替换FOS检索引擎。
- 让DeepSeek Harness实际作语义判断，FOS做来源/hash/权限硬校验，明确区分 DS_AGENT_SUGGESTION 与 RULE_ONLY；CLI不存在/耗额/超时必须真实降级。
- 正常/异常/越权/临时脚本替代均写失败先行的测试，最少涵盖主体错/期错/附件缺/未授权组包/错误sha/无Gold。
- FOS出单一合法结果契约，保留审计run_id，项目源码 SHA，命令退出码、原始合成packet指纹、模型实际使用标识，没真实模型仅测试Adapter契约而非宣称模型成功。
- 只在FOS隔离worktree/branch代码修改；若TeamChannel入口需改，另按它的“同事不得开发”和 #已批准+允许作者 PR-Gate 规则交GM办理，**不能直接让刘江写产品代码**。
- 每改一个点：红测→最小绿修→同命令基线与本分支全量回归→独立Reviewer复验→证据→PR（只commit具体文件，禁git add -A）。
- A1通过独立Gate后，才按当前计划A2→A3→A4→A5继续。涉及同目录复制、Gold泄漏、未经授权OCR费用这类显著风险先加反例并独立复核。

## 4. 不可绕过的测试/验收
- 测试必须包含真调用链可观测输出，不能mock掉FOS所有核心模块导致“假接通”。
- >6份、需要31/40份、没有数量权威、同名文件跨主体、近三年年份锚点、全文缺层、扫描件OCR禁用、hash不匹配、目录同批带出、已有结果回归均为重点负例。
- 多件齐套**不可读取Gold来判断**；当机构需求不能推导出准确份数，应当返回缺证据/UNCERTAIN，寻求人工确认而不是猜31或40。
- 内部合成测试不等于Windows真机业务效果；员工真机读真实材料需单独的敏感外发/资费边界授权，CLI允许但外部模型仍可能传文件名、摘要。
- 当前GitHub Actions如被账户计费拦截，可在经批准的本地隔离Runner完成**候选测试**；不将其伪装为 required-check PASS；未经批准不得变保护规则/自动合并。

## 5. 交付与持续性
每个子WP：
```text
WP_ID, TARGET_GOAL_ID, expected_capability_change
HEAD sha / branch / PR / 代码diff
环境/入口/测试完整命令+exit
红绿测试、基线与本分支同法对照
独立Reviewer结论、具体EVIDENCE路径
工程PASS数/6 与 真实效果积分/100（不要相互抵账）
安全Hard Gate x/9、仍UNKNOWN
Skills: 检索X/命中X/读取X/复用X/新候选X/升级X/独验X/跨端X
next_action及真实GM恢复状态（不能编造已醒）
```
只要未完且有已授权安全下一步，交GM持久队列继续，不因聊天回答结束而“项目完成”。需外部定时器与Lease实测保证接棒；若不能证明自动唤醒，明确为UNKNOWN并将后继工作包**持久登记为待执行**，不说“后台会自动继续”。
