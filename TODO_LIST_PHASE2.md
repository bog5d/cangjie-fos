# CangJie_FOS Phase 2 施工任务单 (TODO_LIST)

【执行协议：全自动循环模式】
1. 读取任务 -> 2. 编码实现 -> 3. 运行 `pytest` 及 `npm run build` -> 4. 成功则标记 [x] 并自动下一项。

- [x] **任务 2.1：** 在 `/frontend` 初始化 Vite+React 环境，配置 TailwindCSS 以支持游戏化 UI 开发。
- [x] **任务 2.2：** 在 `/backend` 实现 `dist` 目录的静态文件挂载逻辑，编写 `build_frontend.ps1` 脚本自动化流程。
- [x] **任务 2.3：** 在 `backend/src/cangjie_fos/api/routes/pitch.py` 中实现基于 LangGraph 的正式 API 接口（`POST /api/pitch/run`），并补齐测试用例。
- [x] **任务 2.4：** 实现前端「作战大盘」组件，定义其与后端 API 的数据契约（包含 A 轮各个阶段的状态）。
- [x] **任务 2.5：** 实现右侧对话框组件，预留 WebSocket 或长轮询接口，支持「主动推送到前端」的 UI 效果。
- [x] **任务 2.6：** 运行全量测试，确保后端 687+ 用例全绿。
