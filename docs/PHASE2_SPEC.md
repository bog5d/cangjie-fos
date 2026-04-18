# CangJie_FOS Phase 2 SPEC：游戏化界面与 API 深度融合

## A. 核心验收项 (Acceptance Criteria)

- **A1. 前端脚手架：** 在 `/frontend` 初始化 Vite + React + TailwindCSS，并能通过 `npm run dev` 看到基础框架。
- **A2. 静态伺服：** `/backend/main.py` 成功挂载 `dist` 目录，访问 `http://localhost:8000/` 直接显示前端页面。
- **A3. 战局地图 (War Room Map)：** 实现左侧主视口，以「融资漏斗」形式展示 A 轮进度（支持从 API 读取 Mock 数据）。
- **A4. 主动 NPC 视窗：** 实现右侧常驻对话框，具备「主动发问」的 UI 状态切换。
- **A5. LangGraph REST 桥接：** 后端提供 `/api/pitch/run` 接口，完整封装旧有的逻辑，支持前端传入 Body 触发。
- **A6. 进化数值反馈：** UI 界面需具备「积分变动」提示动画（如：资料补齐 +10 分）。

## B. 自动化测试策略

- 每项功能开发后，必须在 `backend/tests/` 下新增集成测试用例。
- 全量测试必须维持在 **687+ Passed**，禁止任何回退。
