# CangJie_FOS Phase 3 SPEC：神经接驳（前端与 LangGraph 真机联调）

## A. 核心验收项 (Acceptance Criteria)

- **A1. 真实对话接驳：** 右侧 NPC 对话框接入真实的后端 API（如 `/api/pitch/chat` 或类似路由）。用户在前端输入文字，必须能触发后端的 LLM 调用并返回结果展示在界面上。
- **A2. 音频上传与状态流转：** 前端「模拟上传录音」按钮变为真实的文件上传组件。上传后：
  1. 调用后端的 `/api/pitch/upload`（对接已剥离的 AudioService）。
  2. 触发 LangGraph 评估流程（PitchGraphService）。
  3. 前端能接收到「处理中 -> 完成复盘」的状态变更。
- **A3. 真实大盘数据映射（雏形）：** 左侧的「战局大盘」和「资料健康度」不再是纯写死的数据。需通过 API `GET /api/dashboard/status` 获取（哪怕后端目前返回的是硬编码的 JSON，也必须走通 HTTP 链路）。
- **A4. 错题本（EvolutionRecord）触发：** 当用户在聊天框中对 AI 的复盘提出修正（如：「不对，红杉问的是产能」），前端需调用特定的 Feedback API，并在后端生成一条 `pending_reflection` 的日志/记录（验证 Phase 1 建好的进化地基）。

## B. 自动化测试策略

- 必须包含针对前端 API 调用的 Mock 测试。
- 后端新增的联调接口必须有对应的 `pytest` 用例。
- 全局测试用例保持 **687+ Passed**，绝不允许核心状态机回退。
