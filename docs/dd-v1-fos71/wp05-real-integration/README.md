# DD-V1真实引擎集成 · 可执行开发包（FOS #71）

**目的**：改变DeepSeek Harness/Team Channel之前用临时检索/组包/评分脚本考试的情况，让其真正调用FOS已开发能力，再由刘江Windows在Gold独立隔离下评分；对外材料始终人审。历史42题24严格正确/13部分/5未匹配（57.14%，NON_BLIND）只能作旧临时脚本观察值，不能当FOS有效基线。

**项目状态**：仅Spec/Goal Contract/开发与监工指令通过PR提交。尚无GM本机ACK/Lease、Mac代码执行、独立Reviewer PASS或Windows真实考试。仓库Spec可被执行器读取，不等于执行器已经开始。

## 两套独立指令，不能混用
1. [EXECUTOR-MAC-GM-INSTRUCTION.md](EXECUTOR-MAC-GM-INSTRUCTION.md)：交给**Mac mini上现有司仓负责的唯一代码执行器**。它负责核实唯一控制权、取得真实ACK/Lease、按A0→A5推进、代码PR/真实测试/技能复盘。**不是给刘江跑考试的指令**。
2. [MINIMAX-INDEPENDENT-SUPERVISOR.md](MINIMAX-INDEPENDENT-SUPERVISOR.md)：交给**已有MiniMax独立监工窗口**。只读检查状态/审核Gate/合法催动，不改代码、不充当第二GM，周期优先用已存在的20分钟授权Cron；Cron未验证就不能承诺24h活跃。

## 冻结施工依据
- [INTENT-SPEC-ARCHITECTURE.md](INTENT-SPEC-ARCHITECTURE.md)：业务北极星、P0/P1/P2、两仓接口边界、Reuse Matrix与安全。
- [PROJECT-ROADMAP-PLAN-TASKS-ACCEPTANCE.md](PROJECT-ROADMAP-PLAN-TASKS-ACCEPTANCE.md)：A0–A5详细步骤、合成/真实测试、9项Hard Gate、工程/效果双进度条、每轮状态卡。
- [GOAL-CONTRACT.v3.8.json](GOAL-CONTRACT.v3.8.json)：SCP v3.8 L2 GCCSEG机读合同；请在现场用中央权威checker真实验证。
- [BASELINE-EVIDENCE-REUSE.md](BASELINE-EVIDENCE-REUSE.md)：已验证源码与待验证刘江报告分层、Skills扫描及复用记录。

## 施工场所裁决
- **Mac mini**：选为控制权、持久化派工、唯一Executor、独立Reviewer与外部唤醒的主要环境。先现场确认GM只有一个发号施令的主人；不在此PR中动live进程。
- **云端**：可在隔离checkout上写低风险纯代码、合成夹具并独立测试；但不能冒充Windows真实材料试验，不得自己创建另一个GM调度器。
- **刘江Windows**：在新代码Gate通过后，负责真正的DSH+Team Channel+FOS闭环与盲考，必须有本地数据边界和敏感外发许可。其在此之前只需保存报告、Gold、运行脚本/日志（本地，不传公开GitHub）。
- 最高效策略：**Mac司仓统一派工，云端可作为受控Executor算力，Mac独立审计/持续性，Windows真实效果验收**。若Mac控制权未证明，先合成只读研究与文档等待合法接入。

## 进度口径（不是旧FOS总完成率）
- 工程：新6个A0–A5全部需独立Reviewer PASS；初始0/6=0%。
- 终局：真实FOS调用25、正文召回25、齐套/组包20、Windows盲考20、会话外接棒10 = 100分。初始**已验证0/100，各项UNKNOWN**。
- 硬门槛共9项，均需按验收文档逐条有证据且全部PASS。AI聊天总结/heartbeats/GitHub PR都不能代替。

## 真实开工门槛
仅当**GM唯一调度现场已验证 + 本PR Spec经独立审查 + 持久工作登记/ACK + 现有Executor真实Lease**，才称 `EXECUTING`。当前docs-only PR属于 `SPEC_READY`，不越级。
