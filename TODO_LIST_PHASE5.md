# CangJie_FOS Phase 5 施工任务单 (TODO_LIST)

【执行协议：全自动循环模式】
1. 读取任务 -> 2. 编码实现 -> 3. 运行 `pytest` 及 UI 校验 -> 4. 成功则标记 [x] 并自动下一项。

- [x] **任务 5.1：** 激活 `file_watchdog.py`。实现对特定 `data_room/incoming` 目录的监听，触发任务后将状态更新至 `JobService`，并推送到前端。
- [x] **任务 5.2：** 完善 `webhook_routes.py`。实现一个标准的接收规范，确保外部消息能正确路由到对应的 `tenant_id` 和 `thread_id` 触发 LangGraph。
- [x] **任务 5.3：** 修改 `npc_chat_graph.py`。增加一个“知识预加载”节点，读取 `evolution_guidelines.jsonl`。如果存在针对当前场景的优化建议，则动态拼入 System Prompt。
- [x] **任务 5.4：** 前端 UI 抛光。引入动画库（如 `framer-motion`），为 Exp 增长、健康度条变色实现丝滑的动态效果。
- [x] **任务 5.5：** 在 War Room 右上角增加“结算进化”按钮。前端调用后端的 `/api/v1/reflection/nightly-settle`，后端返回今日进化的金句或避坑指南，前端以精美弹窗展示。
- [x] **任务 5.6：** 全局回归：运行 `pytest` 确保 710+ 全绿，运行 `npm run build` 确保前端构建无误。
