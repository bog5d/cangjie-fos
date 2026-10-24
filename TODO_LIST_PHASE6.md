# CangJie_FOS Phase 6 施工任务单 (TODO_LIST)

【执行协议：全自动循环模式】
1. 读取任务 -> 2. 编码实现 -> 3. 运行 `pytest` 及 UI 校验 -> 4. 成功则标记 [x] 并自动下一项。

- [x] **任务 6.1：** 在 `schemas/` 下定义 `InstitutionProfile` 和 `PipelineStage` 枚举。在 `core/` 或 `services/` 中实现基础的持久化 CRUD 逻辑（按 `tenant_id` 隔离）。
- [x] **任务 6.2：** 开发 `api/routes/pipeline.py`。提供 `/api/v1/pipeline/institutions` 路由（获取机构列表）和 `/api/v1/pipeline/status` 路由（聚合计算漏斗数量，以替换旧的 Dashboard 漏斗 API）。
- [x] **任务 6.3：** 升级 `pitch_graph_service.py`。在原有图中增加 `extract_institution_intel` 节点：利用 LLM 从 transcript 中抽取投资人特征（如：偏好、疑虑、温度），并调用任务 6.1 的逻辑落盘。
- [x] **任务 6.4：** 增强 NPC 聊天上下文。在聊天路由中注入一个极简的 Tool/Function Calling，允许大模型在检测到用户询问特定机构时，自动检索对应的 `InstitutionProfile` 加入 Prompt。
- [x] **任务 6.5：** 前端升级。修改 `WarRoomMap` 对接全新的 Pipeline 聚合 API；并在下方新增 `InstitutionList` 组件，以卡片形式展示“红杉、高瓴”等具体机构的当前进度和 AI 标签。
- [x] **任务 6.6：** 全局回归。确保 `pytest` 在 `backend/` 下全绿（目标 725+），并执行 `npm run build`。

---

## Phase 6.1–6.3 上传 / NPC / UX（与上表 6.1–6.6 编号不同轨）

本段为 **Pitch 上传向导、Task Rail、NPC、错误呈现、Coach 环境合并** 等施工脉络；任务单原文在 `docs/PHASE6_UPLOAD_PLAN.md` 与 `docs/PHASE6_3_UX_PLAN.md`。

- [x] 身份贯通：默认 NPC「豆豆」、`user_name` 穿透上传与聊天（见上传方案 §一）。
- [x] 两阶段向导、`commit` / `job_ids`、WS `upload_job_started` 与轮询列表对齐 Coach 行为（见 `PHASE6_UPLOAD_PLAN.md`）。
- [x] 文件名魔法（TS + Vitest）、Task Rail、报告预览 L1、音频试听与必填校验（见 `PHASE6_3_UX_PLAN.md`）。
- [x] 错误分层：`error_summary` / `error_detail`、`pitch_failure_present`、前端安全展示；`has_report` 与「查看报告」竞态修复。
- [x] `ensure_pitch_coach_runtime` + `hydrate_pitch_coach_env`（Coach 与 `backend/.env` 只填空合并；pytest/CI 跳过 hydrate）。
- [x] 豆豆头像：抽象光核 + `frontend/public/doudou-core.png`。

**新 AI 单页入口：** [`docs/AI_HANDOFF_PHASE6.md`](./docs/AI_HANDOFF_PHASE6.md)（含待优化 backlog §6）。
