# CangJie_FOS Phase 4 SPEC：记忆觉醒与真实资产注水

## A. 核心验收项 (Acceptance Criteria)

- **A1. 聊天持久化 (Thread Checkpointing)：** 右侧 NPC 必须拥有长记忆。接入 LangGraph 的 Checkpointer（如 `SqliteSaver` 或类似持久化机制）。用户刷新页面后，历史聊天记录必须在前端重现。
- **A2. 大盘数据注水 (Real Dashboard Data)：** 左侧大盘的 `docs_health_pct` 和 `data_room_completeness_pct` 不能再是 Mock。后端需读取真实的 `asset_index.json` 或本地资料室文件夹结构，计算出真实的百分比返回给前端。
- **A3. NPC 私有知识挂载 (RAG/Memory Injection)：** NPC 在回答前，必须隐式加载两样东西：当前公司的「资料室清单摘要」和「历史错题本 (Executive Memory)」。如果用户问「我们准备好见红杉了吗？」，NPC 能根据真实缺失的文件做出回答。
- **A4. 反思飞轮闭环 (Reflection Engine 激活)：** Phase 3 留下的 `pending_reflection` 错题记录，现在需要一个触发点（可以是手动点击 UI 上的「夜间结算」按钮，或后端的定时任务）。触发后，调用 `ReflectionService` 生成一条通用防坑建议，并落盘。

## B. 自动化测试策略

- 针对 LangGraph 的 `Thread ID` 恢复能力编写测试用例。
- 针对真实资产扫描（Asset Reader）编写 Mock 目录结构的测试。
- 全量测试必须稳在 **698+ Passed**。
