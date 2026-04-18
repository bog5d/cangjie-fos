# Phase 6.x 交接：给新 AI / 协作者

**用途：** 单页入口，串联「机构沙盘（6.0）」与「上传/NPC/UX（6.1–6.3）」的**已落地事实**、目录锚点、契约与**建议优化方向**。阅读顺序：本文 → 按需打开下方链接的专项方案。

**工作区根目录：** 建议将 Cursor 工作区设为 `CangJie_FOS/`，以加载 `.cursor/rules/`。

---

## 1. 文档地图（人类与 AI 共用）

| 文档 | 内容 |
|------|------|
| `docs/MASTER_PRD.md` | 产品灵魂、红线、飞轮 |
| `docs/PHASE6_SPEC.md` | Phase 6.0：机构画像 + 漏斗 API + NPC 简报（验收项） |
| `docs/PHASE6_UPLOAD_PLAN.md` | Phase 6.1/6.2：身份贯通、与 `AI_Pitch_Coach` 上传对齐（长文事实摘要） |
| `docs/PHASE6_3_UX_PLAN.md` | Phase 6.3：文件名魔法、Task Rail、报告预览、试听、防呆等 UX 方案 |
| `docs/PHASE6_3_REVISION_PLAN.md` | 6.3 修订：错误 summary/detail 分层、豆豆「抽象光核」视觉红线 |
| `TODO_LIST_PHASE6.md` | Phase 6.0 施工任务单（机构模块） |
| `AGENTS.md` | 仓库速览、如何跑测试 |

**说明：** `PHASE6_3_*` 正文仍以「设计/修订」为主；**与代码是否一致**以本文 **§4–§6** 与仓库内测试为准。

---

## 2. Monorepo 与外部依赖

| 路径 | 职责 |
|------|------|
| `CangJie_FOS/backend/` | FastAPI、LangGraph、Pitch job、NPC |
| `CangJie_FOS/frontend/` | React + Vite（`npm run build` / `npm run test`） |
| `AI_Workspaces/AI_Pitch_Coach/` | 默认通过 `CANGJIE_PITCH_COACH_ROOT` 或相对路径解析；**转写/评估**大量逻辑在此 `src/` |

Pitch 热路径在调用 Coach 前会执行 **`ensure_pitch_coach_runtime()`**（`backend/src/cangjie_fos/core/paths.py`）：`sys.path` 注入 Coach + **`hydrate_pitch_coach_env()`**。

### 2.1 环境变量与「只填空」合并

- **问题背景：** Coach 侧 `transcriber` 等默认只读 Coach 根目录 `.env`；FOS 常在 **`backend/.env`** 配 `DASHSCOPE_API_KEY` 等，若不合并会出现「本机有 key 仍转写失败」。
- **策略：** `hydrate_pitch_coach_env()` 读取 **Coach 根 `.env` 与 `backend/.env`** 合并进内存字典后，对 **`os.environ` 中仍为空的键**才写入（不覆盖已有环境变量）。
- **测试隔离：** 若存在 `PYTEST_CURRENT_TEST` 或 CI 常见标记，**跳过 hydrate**，避免破坏 `monkeypatch.delenv` 的离线用例。

---

## 3. 用户路径速记（上传 → 任务 → 报告）

1. 前端 **`PitchUploadWizard`**（抽屉 + Stepper）提交 → 后端创建 job → 可能经 **`pitch_upload_pipeline` / `pitch_wizard_runner`** 调 Coach 转写与图评估。
2. **`TaskRail`** 轮询 `GET /api/pitch/jobs`（或相关列表接口），展示多轨道任务。
3. **「查看报告」**：仅当 **`status === 'completed'` 且 `has_report === true`** 时展示，避免「评估尚未结束却已可点报告」的竞态（历史上曾由 WS 过早挂 `reportJobId` + 过宽的 `has_report` 导致）。
4. **NPC `NPCPanel`**：`upload_job_started` 等 WS **不应**在报告未就绪时绑定可跳转的 `reportJobId`；失败文案优先 **`error_summary`**，兼容 legacy 的 `error` 字段。

---

## 4. 后端契约（与优化入口）

### 4.1 Job 状态与 `has_report`

- API 层 **`has_report`** 语义：**存在 `report` 且状态为 `completed`**，避免半完成态被当成可消费报告。
- 相关实现：`backend/src/cangjie_fos/api/routes/pitch.py`（及 schema）。

### 4.2 错误呈现（失败 job）

- 统一辅助：`backend/src/cangjie_fos/services/pitch_failure_present.py`（如 `normalize_pitch_failure`、`job_failure_update_kwargs`、`resolve_stored_job_errors`）。
- Schema：`PitchJobSummary` / `PitchJobStatusResponse` 含 **`error_summary`、`error_detail`、`error_code`**；`error` 与 summary 对齐以兼容旧客户端。
- 写入失败状态时优先用人话 **summary**，原始/供应商信息进 **detail**（前端主界面不直出 Raw JSON）。

### 4.3 测试锚点

- `backend/tests/test_pitch_failure_present.py`
- `backend/tests/test_pitch_job_has_report_contract.py`
- 全量：`cd backend` → `python -m pytest`（须保证相对路径与依赖已安装，见 `AGENTS.md`）。

---

## 5. 前端锚点

| 主题 | 文件（典型） |
|------|----------------|
| Task Rail 与报告按钮条件 | `frontend/src/components/TaskRail.tsx` |
| NPC、WS、错误展示 | `frontend/src/components/NPCPanel.tsx` |
| 错误摘要降级（含 legacy JSON） | `frontend/src/lib/pitchJobErrorDisplay.ts` + 对应测试 |
| 报告预览 Modal | `frontend/src/components/PitchReportPreviewModal.tsx` |
| 豆豆头像（光核 + 资源图） | `frontend/src/components/DoudouAvatar.tsx`，静态资源 **`frontend/public/doudou-core.png`**（`onError` 回退「豆」字） |

---

## 6. 已知「方案里写了但可继续优化」的条目

以下来自 `PHASE6_3_UX_PLAN.md` §7.5 / §8，**不必一次做完**，适合新 AI 分 PR 消化：

- **Readiness 门禁：** 对齐旧版 `env_all_ok`——向导提交前聚合密钥/依赖检测，灰化主按钮。
- **QA 截断 / 敏感词 / logical_conflict：** `commit` 回传 warnings 或独立预检 API。
- **「仅提取文字稿」快速预览：** 独立 API 与计费策略需产品确认。
- **机构名 fuzzy caption：** Step 0 debounce 对接 institutions 或专用接口。
- **取消任务、WS `job_status`：** 见原方案 §7.4。
- **视觉：** `prefers-reduced-motion`、列表小头像与光核 DNA 完全一致化（见修订方案）。

---

## 7. 本地命令备忘

```powershell
# 后端测试（在 backend 目录）
Set-Location .\backend
python -m pip install -e ".[dev]"
python -m pytest

# 前端
Set-Location .\frontend
npm run test
npm run build
```

根目录脚本：`build_frontend.ps1`、`run_dev.ps1`（见 `AGENTS.md`）。

---

## 8. 给「下一轮优化」AI 的一句话

优先读 **`paths.py` 的 `ensure_pitch_coach_runtime` / `hydrate_pitch_coach_env`** 与 **`pitch.py` 的 `has_report`**，再改 UI；任何全进程级别的 `load_dotenv` 或 hydrate 容易破坏 pytest，**仅放在 Pitch 热路径或显式 CLI 入口**。

---

**维护约定：** 大功能合并后，在本文件 **§4–§6** 更新「事实」一行即可；长篇设计仍写在 `PHASE6_3_*` / `PHASE6_UPLOAD_PLAN.md`，避免重复粘贴大段方案正文。
