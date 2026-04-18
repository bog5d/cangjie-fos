# CangJie_FOS Phase 4 施工任务单 (TODO_LIST)

【执行协议：全自动循环模式】
1. 读取任务 -> 2. 编码实现 -> 3. 运行 `pytest` 及前端联调测试 -> 4. 成功则标记 [x] 并自动下一项。

- [x] **任务 4.1：** 在 `backend/src/cangjie_fos/core/` 引入数据库机制（推荐简单的 SQLite 作为过渡），为 LangGraph 配置持久化的 Checkpointer。
- [x] **任务 4.2：** 改造 `api/pitch/chat` 接口，要求前端传入 `thread_id` 或 `tenant_id`，后端基于此 ID 恢复历史对话状态，并支持前端拉取历史会话列表。
- [x] **任务 4.3：** 在 `services/` 中打通 `AI_CangJie_FSS` 的资产读取逻辑。改造 `api/dashboard/status` 接口，使其能扫描本地真实的文件树或索引，返回真实的资料健康度百分比。
- [x] **任务 4.4：** 升级 `npc_chat_graph.py` 的系统提示词 (System Prompt) 节点，使其在生成回答前，先读取 `tenant_id` 对应的真实资产清单和历史错题本，作为上下文喂给大模型。
- [x] **任务 4.5：** 实现 `reflection_service.py` 的核心逻辑。编写一个内部接口或后台任务，消费所有的 `pending_reflection`，用大模型提炼为 `Evolution Guidelines`。
- [x] **任务 4.6：** 全局回归：运行 `pytest` 确保 698+ 全绿，运行 `npm run build` 确保前端构建无误。
