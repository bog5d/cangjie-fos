# CangJie_FOS Phase 6 SPEC：机构画像与战局沙盘 (Institution Profiling & Pipeline)

**相关：** 上传/NPC/Phase 6.3 UX 与错误契约的 **落地摘要与文件锚点** 见 **[`AI_HANDOFF_PHASE6.md`](./AI_HANDOFF_PHASE6.md)**（本文聚焦 6.0 机构与漏斗）。

## A. 核心验收项 (Acceptance Criteria)
- **A1. 机构实体记忆 (Institution CRM)：** 建立 `Institution` 数据模型（存入 SQLite 或独立 JSON）。记录机构名称、当前阶段（Targeted, Pitched, DD, TermSheet）、AI 总结的机构偏好/温度（Thermal）。
- **A2. 录音/路演自动画像提取：** 改造 `PitchGraphService`。在路演复盘的最后，增加一个“情报提取”节点：大模型不仅要评价高管，还要从对方提问中提取出“该机构的投资偏好和核心疑虑”，并自动更新或创建该机构的 Profile。
- **A3. 真实漏斗驱动 (Real Funnel API)：** 左侧大盘的“融资漏斗”数据必须通过聚合底层的 `Institution` 列表计算得出（例如：Pitched 阶段有 3 家机构，DD 阶段有 1 家）。
- **A4. 战前简报 (Pre-meeting Briefing)：** 当用户在 NPC 聊天框输入“明天我要去见 [某机构名]”时，NPC 必须能命中该机构的 Profile，结合全局进化指南（Evolution Guidelines），给出针对性的避坑策略。
- **A5. 前端沙盘 UI：** 在 War Room 界面下方或侧边，增加一个轻量级的“机构看板（Kanban/List）”，展示当前跟进中的机构卡片及其阶段、AI 提炼的核心关注点。

## B. 自动化测试策略
- 针对机构 Profile 的 CRUD 接口编写单元测试。
- 模拟包含机构特征的对话文本，测试 LangGraph 是否能成功提取并落盘 `Institution` 实体。
- 全量测试基线提升至 **725+ Passed**。
