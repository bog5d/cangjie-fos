# Phase 1 SPEC — 大一统脚手架与进化地基

遵循 **Spec 先行**：本文定义验收标准（Acceptance Criteria）；实现以本文为准，与 `docs/MASTER_PRD.md` 冲突时以 MASTER_PRD 为准。

## 0. 范围与非目标

- **迁移源事实仓库：** `AI_Workspaces/AI_Pitch_Coach`（Streamlit `app.py` + `src/`）。新后端不复制 Streamlit UI；逻辑从 **`src/`** 与既有 pipeline 下沉到 **Service**。
- **非目标（本阶段不做）：** 前端 Vite 完整页、生产级多租户 DB、真实 Red Team 模型编排。

## 1. 目录与模块边界（验收 A1）

- 存在 `CangJie_FOS/backend/`，Python 包根为 `backend/src/cangjie_fos/`。
- 子包目录存在且职责单一：`api/`、`services/`、`schemas/`、`core/`、`events/`、`reflection/`。
- **禁止**单文件合并「路由 + 全量业务 + 数据访问」；`main.py` 仅做应用组装（可 < 80 行）。

## 2. 依赖与可运行性（验收 A2）

- `pyproject.toml` 声明：FastAPI、Uvicorn、LangGraph、Pydantic v2、pytest、httpx（测 API）。
- 提供根目录一键脚本：`run_dev.ps1`（Windows）启动 API（读 `backend` 包）。

## 3. API 契约（验收 A3）

| 方法 | 路径 | 行为 |
|------|------|------|
| GET | `/health` | 200，`{"status":"ok"}` |
| POST | `/api/v1/feedback/text-diff` | 请求体含 `tenant_id`、AI 原文、用户定稿；计算 unified diff；落盘 JSON；`status=pending_reflection` |
| POST | `/api/v1/webhooks/ingest` | 占位：校验 `tenant_id`，返回 `accepted` |
| GET | `/api/v1/watch/status` | 返回 Watchdog 骨架是否已注册（布尔） |

## 4. 服务层契约（验收 A4）

- **AudioService：** 封装对 `AI_Pitch_Coach` 中 `audio_preprocess.smart_compress_media` 的调用（薄适配层，不复制算法）。
- **PitchGraphService：** 封装 `run_pitch_evaluation_via_langgraph_with_state` 的调用边界：入参为 **dict/state 片段**，出参为 **(report, state_excerpt)**；内部 import 延迟到调用时，避免无 LangGraph 时 import 失败（测试可 mock）。

## 5. 测试策略（验收 A5）— 与「620+」对齐

- **单一命令：** 在 `CangJie_FOS/backend/` 执行 `pytest`，须同时收集：
  - `backend/tests/`（本仓库原生契约测试）；
  - `../../AI_Pitch_Coach/tests/`（**不搬迁文件**，利用既有 `__file__` 推导的 `ROOT`，保证 684 条逻辑路径不被错误改写）。
- **通过标准：** 全量收集数 ≥ 620，且 **0 failed**（与 MASTER_PRD 基线一致）。当前双路径合并后约 **687** 条（`backend/tests` + `AI_Pitch_Coach/tests`；`AI_Pitch_Coach` 根目录 `test_v7_acceptance.py` 未纳入同一次 collect，如需可单独在 Pitch_Coach 根目录执行）。

## 6. 自我进化数据模型（验收 A6）

- Pydantic 模型 `EvolutionRecord`（或等价命名）字段至少包含：`tenant_id`、`trace_id`、`ai_text`、`user_text`、`diff_unified`、`status`（含 `pending_reflection`）、`created_at`。
- `reflection/reflection_service.py`：提供 `enqueue_reflection(record_id)` 骨架（可为 no-op + 日志接口），供后续异步 Worker 接入。

## 7. 事件与监听骨架（验收 A7）

- `events/` 下 Webhook 路由实现见 A3；Watchdog 提供 **可注入** 的 `start_watchdog_stub()` / `is_watchdog_running()`，默认不阻塞进程（骨架）。

## 8. 多租户红线（验收 A8）

- 上述所有 API 请求模型均含 **`tenant_id: str`**；服务层方法签名要求传入 `tenant_id`，禁止在日志中打印完整用户定稿文本（可截断或仅记录 hash）。

---

**实现顺序：** A1 → A2 → A3（health）→ A5（pytest 双路径）→ A4 → A6 → A7 → 脚本 A2。

---

## 9. Phase 1 执行清单（Spec 驱动）

- [x] A1 目录与包 `cangjie_fos` 子模块就位
- [x] A2 `pyproject.toml` + 可编辑安装 + `run_dev.ps1`
- [x] A3 `/health`、`/api/v1/feedback/text-diff`、`/api/v1/webhooks/ingest`、`/api/v1/watch/status`
- [x] A4 `AudioService`、`PitchGraphService`（延迟 import Pitch_Coach）
- [x] A5 `pytest` 在 `backend/` 下双路径收集，**687 passed，0 failed**
- [x] A6 `EvolutionRecord` + JSON 落盘 + `ReflectionService.enqueue_reflection` 桩
- [x] A7 Watchdog 显式启动骨架 + 状态查询
- [x] A8 请求体 `tenant_id` 必填；默认不落全文仅 hash 日志
