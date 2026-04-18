# CangJie_FOS — Agent / 协作者速览

本仓库为 **仓颉 FOS 融资作战系统** 单体 Monorepo。人类与 AI 协作时，请先读 **`docs/MASTER_PRD.md`**；**Phase 1 验收**以 **`docs/PHASE1_SPEC.md`** 为准。

**Phase 6.x（机构沙盘 + 上传/NPC/UX）已落地脉络：** 新会话/新 AI 建议先读 **`docs/AI_HANDOFF_PHASE6.md`**（单页交接：路径、环境、契约、测试锚点、待优化清单），再按需打开 `docs/PHASE6_3_UX_PLAN.md` 等长文方案。

## 仓库地图（规划/落地后以此为准）

| 路径 | 职责 |
|------|------|
| `docs/AI_HANDOFF_PHASE6.md` | **新 AI 推荐入口**：Phase 6.x 事实摘要、文件锚点、环境与 pytest 注意点 |
| `backend/` | FastAPI + LangGraph；API、图编排、领域服务 |
| `backend/tests/` | 本仓库契约测试；与 `AI_Pitch_Coach/tests` **双路径**合并跑满 **620+**（见 `pyproject.toml`） |
| `docs/PHASE1_SPEC.md` | Phase 1：脚手架 + 进化地基的 **Spec 与验收** |
| `docs/PHASE3_SPEC.md` | Phase 3：NPC 真机对话、上传、大盘、错题本 **Spec** |
| `TODO_LIST_PHASE3.md` | Phase 3 **施工任务单** |
| `docs/PHASE4_SPEC.md` | Phase 4：Checkpointer、真实大盘、RAG、反思飞轮 **Spec** |
| `TODO_LIST_PHASE4.md` | Phase 4 **施工任务单** |
| `frontend/` | React + Vite；构建输出 `dist/` |
| `docs/MASTER_PRD.md` | 产品灵魂、架构、红线、交付标准 |
| `.cursor/rules/` | Cursor 规则：Monorepo/隐私/测试 + 自我进化飞轮 |

## 如何跑起来

1. **API + 静态前端（Phase 2）：** 先 `.\build_frontend.ps1`，再 `.\run_dev.ps1`（`http://127.0.0.1:8000/` 打开 React；`npm run dev` 在 `frontend/` 为 Vite 5173 开发态）。
2. **测试（须在 `backend/` 下，保证相对路径）：**
   `Set-Location .\backend` → `python -m pip install -e ".[dev]"` → `python -m pytest`。
3. **前端单测（Phase 3）：** `Set-Location .\frontend` → `npm run test`（Vitest + Axios Mock）。
4. **Pitch_Coach 根目录：** 环境变量 `CANGJIE_PITCH_COACH_ROOT` 可覆盖默认的 `…/AI_Workspaces/AI_Pitch_Coach`。
5. 前端 `dist/` 由 FastAPI 伺服（先 `build_frontend.ps1`）。

## 自我进化飞轮（实现时必须四段齐全）

**捕获 (Diff) → 反思 (Reflection，异步) → 校验 (Red Teaming) → 固化 (合并 Prompt/Skill，可版本化)**。详见 `docs/MASTER_PRD.md` 第 2 节与 `.cursor/rules/cangjie-fos-evolution-flywheel.mdc`。

## Cursor 规则生效方式

将 Cursor **工作区根目录** 设为 **`CangJie_FOS`**，以便加载 `.cursor/rules/*.mdc`。若以父级文件夹（例如整盘 `AI_Workspaces`）为工作区打开，则需在对应工作区根配置等效规则，或改为打开本文件夹为根。

## 红线速查

- 禁止「上帝文件」；按 Router / Service / Schema / Utils / Event 模块化。
- 所有子智能体与敏感业务数据 **强绑定 `tenant_id`**，禁止跨租户明文流动。
- 功能迁移须 **带测试迁移**。
