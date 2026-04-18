# AI 交接文档 — Phase 6.4 数据底座 + NPC 修复

**写于**: 2026-04-18  
**当前分支**: `feat/phase-6.4-p0-data-foundation`  
**测试基线**: 95 passed, 0 failures（`python -m pytest tests/ -q` 在 backend/ 目录执行）

---

## 已完成内容（本次 session）

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/src/cangjie_fos/services/pitch_job_db.py` | SQLite 持久层，`data/pitch_jobs.sqlite`，WAL 模式，含 `db_job_create/update/get/list_for_tenant` |
| `backend/tests/test_pitch_job_db.py` | 14 项测试，全覆盖 DB CRUD |
| `backend/tests/test_p0_pipeline_persistence.py` | 5 项测试，验证音频/words/report 落盘 |
| `backend/tests/test_p0_review_endpoints.py` | 9 项测试，验证 4 个新 API 端点 |
| `backend/tests/test_p3_npc_context.py` | 6 项测试，验证 NPC 上下文注入 |

### 修改文件

| 文件 | 改动摘要 |
|------|----------|
| `backend/src/cangjie_fos/services/pitch_upload_pipeline.py` | 音频 mv 到 `data/audio/{job_id}{suffix}`（不再 unlink）；words_json + audio_path + original_report 写入 SQLite |
| `backend/src/cangjie_fos/services/pitch_job_store.py` | `job_create` 末尾 try/except 桥接调用 `db_job_create`（best-effort） |
| `backend/src/cangjie_fos/api/routes/pitch.py` | 新增 4 个端点（见下方 API 一览）；`/chat` 端点透传 `active_job_id` |
| `backend/src/cangjie_fos/schemas/pitch_upload.py` | 新增 `PitchReviewResponse`, `PitchReviewCommitRequest`, `PitchReviewCommitResponse` |
| `backend/src/cangjie_fos/schemas/pitch_chat.py` | `PitchChatRequest` 新增 `active_job_id: str | None = None` |
| `backend/src/cangjie_fos/services/npc_chat_graph.py` | `_base_system()` 追加能力声明；`NpcGraphState` 新增 `active_job_id`；新增 `_inject_job_context` 节点；图结构 inject→inject_job→agent；`invoke_npc_chat` 接受 `active_job_id` |

### 新增 API 端点（已上线，有测试）

```
GET  /api/pitch/jobs/{job_id}/review   → PitchReviewResponse（original+edited双版本）
PATCH /api/pitch/jobs/{job_id}/review  → PitchReviewCommitResponse（只写 edited_report）
GET  /api/pitch/jobs/{job_id}/words    → list[dict]（词级时间戳）
GET  /api/pitch/jobs/{job_id}/audio    → FileResponse（HTTP Range，MIME 按后缀）
```

### SQLite 表结构（`data/pitch_jobs.sqlite`）

```sql
pitch_jobs (
    job_id TEXT PK, tenant_id TEXT, status TEXT,
    created_at REAL, original_report TEXT(JSON), edited_report TEXT(JSON),
    words_json TEXT(JSON), audio_path TEXT, committed_at REAL,
    exp_delta INTEGER, exp_reason TEXT,
    error_summary TEXT, error_detail TEXT, error_code TEXT
)
```

**关键设计**：`original_report` 一次写入不可改；`edited_report` 通过 PATCH 写入；`report` 字段是别名（edited 优先，否则 original）。

---

## 架构决策备忘（不要推翻）

1. **音频文件路径**: `backend/data/audio/{job_id}{suffix}`，通过 `get_backend_root() / "data" / "audio"` 解析
2. **音频联动方案**: 前端用 `currentTime` 跳转（非 FFmpeg 按需切片）。FFmpeg 仅用于最终 HTML 报告生成
3. **双存储并存**: 内存 `pitch_job_store` 仍是 API 读取的主数据源（`job_get`）；SQLite 是 HITL 审查台专用存储。两者通过 `job_create` 桥接保持同步
4. **NPC 能力**: `_inject_job_context` 用 lazy import 避免循环依赖，异常静默吞掉（BLE001）

---

## P1 已完成（2026-04-18 第二轮 session）

**测试基线**: 110 passed（+15 新测试）

| Commit | 内容 |
|--------|------|
| `6146b20` | `html_report_path` 列 + `imageio-ffmpeg`/`jinja2` 依赖 |
| `bf67990` | `html_report_service.py` — 桥接旧系统 `report_builder` |
| `d597879` | `POST /api/pitch/jobs/{job_id}/html-report` 端点 + `PitchHtmlReportResponse` schema |

**P1 新增端点**: `POST /api/pitch/jobs/{job_id}/html-report`  
→ 触发 FFmpeg 切片 + Jinja2 渲染，HTML 输出到 `data/html_reports/{job_id}.html`  
→ 优先使用 `edited_report`（已人工审查），否则用 `original_report`  
→ `ValueError` → 404，`FileNotFoundError` → 404，其他 → 500

---

## 待完成任务（下一 session）

### ~~P1：HTML 报告生成端点~~ ✅ 已完成

### P2（下一 session 优先）：前端全屏审查台（约 8-10 个 subagent）

**目标**: `POST /api/pitch/jobs/{job_id}/html-report`

**逻辑**:
1. 从 `db_job_get(job_id)` 取 `original_report`（或 `edited_report` 如果已审查）、`words_json`、`audio_path`
2. 调用旧系统 `report_builder.generate_html_report(audio_path, words_list, report_obj, output_path)`
3. 将生成的 HTML 文件路径存入 DB（需给 `pitch_jobs` 表加 `html_report_path TEXT` 列）
4. 返回下载链接或直接 stream HTML

**关键依赖**:
- 旧系统 `report_builder.py` 在 `AI_Pitch_Coach/AI路演教练_纯净交付版_V10.3/src/`
- `ensure_pitch_coach_runtime()` 已有，可直接用
- 需在 `pyproject.toml` 确认 `imageio-ffmpeg` 已列为依赖（当前可能缺失）

**新增响应 schema**:
```python
class PitchHtmlReportResponse(BaseModel):
    job_id: str
    html_path: str
    generated_at: float
```

### P2：前端全屏审查台（前端，约 8-10 个 subagent）

**技术栈**: 安装 `react-router-dom@6`，改造 `frontend/main.tsx` 和 `frontend/src/App.tsx`

**路由**:
- `/` → 现有 `App`（不变）
- `/review/:job_id` → 新页面 `pages/ReviewWorkbench.tsx`

**组件树**（严格按架构文档 `docs/PHASE6_4_WORKBENCH_ARCH_PLAN.md` 第二节）:

```
pages/ReviewWorkbench.tsx           ← 主容器，加载 GET /review/:id + GET /words
├── WorkbenchHeader.tsx             ← 顶栏（返回/状态badge/锁定按钮）
├── left/SceneHeaderFields.tsx      ← 场景/角色/总分/扣分（可编辑）
├── left/RiskPointList.tsx          ← 列表容器
│   └── left/RiskPointCard.tsx      ← 单条 CRUD（含音频播放、只读 AI 链、删除）
├── left/AddRiskPointForm.tsx       ← 手动新增（is_manual_entry=true）
├── right/JobInfoPanel.tsx          ← 元信息展示
├── right/WorkbenchNPCChat.tsx      ← 豆豆对话（传 active_job_id）
├── right/HtmlReportPreview.tsx     ← iframe srcdoc 实时预览
└── AudioSnippetPlayer.tsx          ← 共享 audio element + currentTime 跳转
```

**关键实现细节**:
- `wordsMap: Map<number, {start_time, end_time}>` 由 `ReviewWorkbench` 从 `GET /jobs/{id}/words` 加载，通过 Context 下传
- `AudioSnippetPlayer` 用全局单例 audio element（避免多路并发）
- 非对称缓冲：playStart = `words[start_idx].start_time - 1.5`，通过 `ontimeupdate` 在 `words[end_idx].end_time + 8.0` 时 pause
- `PATCH /jobs/{id}/review` 在"锁定"按钮 onClick 时调用
- `PitchReportPreviewModal.tsx` 改为跳转入口（`window.open(/review/${jobId}, '_self')`），不再做只读展示

**前端类型文件**（需新建）:
```typescript
// src/types/review.ts
export interface AnalysisReport { ... }
export interface RiskPoint { ... }
export interface ReviewWorkbenchState { ... }
```

---

## 运行命令速查

```bash
# 后端测试（在 CangJie_FOS/backend/ 目录）
python -m pytest tests/ -q

# 后端开发服务器
uvicorn cangjie_fos.main:app --reload --port 8000

# 前端开发服务器（在 CangJie_FOS/frontend/ 目录）
npm run dev

# git 状态
git log --oneline feat/phase-6.4-p0-data-foundation
```

---

## 接手指令（给下一个 AI）

读完本文档后，执行：
```bash
cd /d/AI_Workspaces/CangJie_FOS
git checkout feat/phase-6.4-p0-data-foundation
cd backend && python -m pytest tests/ -q   # 确认 95 passed
```

然后直接从 **P1 HTML 报告生成端点** 开始施工，参照本文档"待完成任务"章节和 `docs/PHASE6_4_WORKBENCH_ARCH_PLAN.md`。
