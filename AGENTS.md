# AGENTS.md — 仓颉 FOS · AI 协作操作手册

> **所有 AI Agent（Claude、Cursor、Hermes、Codex 等）进入本仓库前必读。**  
> 本文档是权威操作规范，优先级高于任何其他文档。

---

## 当前版本状态（最后更新：2026-04-27）

| 项目 | 状态 |
|------|------|
| 版本 | v0.4.0 |
| 测试基线 | **258 passed**（`cd backend && uv run --extra dev pytest tests/ -q`） |
| 前端构建 | **零错误**（`cd frontend && npm run build`） |
| 当前 Phase | **Phase 7.0 阶段2完成（v0.4.0）→ Phase 7.0 阶段3待开始** |
| 详细变更历史 | 见 `CHANGELOG.md` |

---

## 读代码前必须知道的架构事实

### 1. 双系统架构
本仓库（FOS）是**前端 + 后端 + 业务编排**。  
**AI Pitch Coach（FSS）** 是独立的 LLM/ASR 评估引擎，不在本仓库内。

```
cangjie-fos（本仓库）
    ├── 负责：UI、API路由、任务管理、报告生成、豆豆NPC
    └── 依赖：AI Pitch Coach（FSS）提供 LLM 评估能力
              └── 位置：PITCH_COACH_ROOT 环境变量指定
                        （本地开发通常是 D:\AI_Workspaces\AI_Pitch_Coach）
```

**重要**：没有 FSS 也能运行大部分功能。FSS 只在以下操作时才需要：
- 实际 ASR 转写（测试用 mock 替代）
- LangGraph Coach 评估（测试用 mock 替代）
- 机构数据同步（Adapters）

### 2. 测试在无 FSS 环境下全部通过

所有测试已 mock FSS 依赖。设置环境变量即可：
```bash
export PITCH_COACH_ROOT=/tmp/mock_pitch_coach
mkdir -p /tmp/mock_pitch_coach/src
cd backend && uv run --extra dev pytest tests/ -q
# 期望：228 passed
```

### 3. 数据目录不在 git 里

`backend/data/`（SQLite + 音频文件）已 gitignore。首次运行会自动创建。

---

## 强制操作规范

### 改代码前
```bash
git pull origin master          # 拉最新
cd backend && uv run --extra dev pytest tests/ -q  # 确认基线
```

### 改完代码后（缺一不可）

```bash
# 1. 跑全套测试
cd backend && uv run --extra dev pytest tests/ -q
# 期望：≥228 passed，0 failed

# 2. 前端构建检查
cd frontend && npm run build
# 期望：✓ built in X.XXs，零 TS 错误

# 3. 更新 CHANGELOG.md
# 在 [Unreleased] 下添加你的变更条目

# 4. 提交
git add <具体文件>    # 禁止 git add -A（防止误提交 .env）
git commit -m "type(scope): 简短描述"

# 5. 推送（CI 会自动验证）
git push origin <分支名>
```

### 提 PR 必须
- PR 描述填写 `.github/pull_request_template.md` 模板
- CI（GitHub Actions）全绿才能合并
- 更新 `CHANGELOG.md`

---

## 禁止行为

| 禁止 | 原因 |
|------|------|
| `git add -A` 或 `git add .` | 可能误提交 `.env`（API Key）或 SQLite 文件 |
| 改完说"应该好了你试试" | 必须先跑测试证明 |
| 只 mock 外部服务不验证 DB 写入 | DB 才是审查台的数据源 |
| 新增 pipeline 步骤不更新 E2E 测试 | 会导致测试不覆盖真实链路 |
| 提交 `.env` / `*.sqlite` / `*.zip` | 已 gitignore，不应强制添加 |
| 删除/跳过现有测试来让数量达标 | CI 验证数量 ≥200，但测试必须真实有效 |

---

## 关键文件速查

| 文件 | 作用 |
|------|------|
| `CHANGELOG.md` | 版本历史，**每次提交前必须更新** |
| `CLAUDE.md` | Claude 专用规范（测试标准、架构约定） |
| `backend/src/cangjie_fos/services/pitch_upload_pipeline.py` | 上传→ASR→评估主流水线 |
| `backend/src/cangjie_fos/services/pitch_job_db.py` | SQLite 持久化层（单一真相源） |
| `backend/src/cangjie_fos/services/npc_chat_graph.py` | 豆豆 NPC 对话图 |
| `backend/src/cangjie_fos/core/readiness.py` | 系统就绪检查（Doctor 模块） |
| `backend/tests/test_pipeline_e2e.py` | Pipeline 核心 E2E 测试 |
| `frontend/src/components/TaskRail.tsx` | 任务进度组件 |
| `frontend/src/pages/ReviewWorkbench.tsx` | 全屏审查台 |

---

## 战略方向（已对齐，新 AI 必读）

**FSS（AI Pitch Coach）将完全吸收进 FOS，不是外部依赖，是子模块。**

五阶段合并计划：
| 阶段 | 内容 | 状态 |
|------|------|------|
| 阶段0 | R3：LLM重试 + 重跑评估按钮 | ✅ 完成（v0.2.1） |
| 阶段1 | FSS代码移入 `engine/` 子包，消灭 sys.path 注入 | ✅ 完成（v0.3.0） |
| 阶段2 | FSS JSON数据 → FOS SQLite统一（贡献度/素材匹配表） | ✅ 完成（v0.4.0，258 passed） |
| 阶段3 | APScheduler夜间自动进化任务 | ⏳ 待开始 |
| 阶段4 | 全数据关联（路演→素材→机构→贡献者） | ⏳ 待开始 |
| 阶段5 | Doctor强化（外发版自愈） | ⏳ 待开始 |

FSS 路径：`D:\AI_Workspaces\AI_Pitch_Coach`（阶段1完成后归档）

## 立即要做（阶段3 — APScheduler 夜间自动进化）

**阶段2已完工（v0.4.0）**：4张新表 + 3个新API + 分页 + structlog + 前端懒加载，258 passed。

**阶段3核心目标**：系统每晚自动消化数据，次日早晨向豆豆注入更新建议

### Task 1 — APScheduler 接入 FastAPI lifespan
文件：`backend/src/cangjie_fos/main.py`
```python
# pyproject.toml 新增：apscheduler>=3.10
from apscheduler.schedulers.asyncio import AsyncIOScheduler
# lifespan 内：scheduler.add_job(nightly_settle_all_tenants, "cron", hour=2, minute=0)
```

### Task 2 — nightly_settle.py（夜间结算服务）
文件：`backend/src/cangjie_fos/services/nightly_settle.py`
- `nightly_settle_all_tenants()` — 从 DB 查所有活跃 tenant_id，逐个调用
- `nightly_settle_for_tenant(tenant_id)` — 执行3步：
  1. 提取 pending review_diffs → 写入 investor_prefs（调用已有 `run_preference_extraction`）
  2. 分析近期 pitch + 素材库 → 生成建议（`_generate_material_suggestions`）
  3. 写入 `nightly_suggestions` 表

### Task 3 — nightly_suggestions 表
文件：`backend/src/cangjie_fos/services/pitch_job_db.py`
```sql
CREATE TABLE IF NOT EXISTS nightly_suggestions (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    created_at  REAL NOT NULL,
    consumed_at REAL,
    type        TEXT NOT NULL,  -- "material_update" | "risk_pattern" | "institution_insight"
    content     TEXT NOT NULL,  -- 自然语言建议
    asset_id    TEXT,
    priority    INTEGER DEFAULT 5
);
```
CRUD：`db_nightly_suggestion_insert / list_pending / mark_consumed`

### Task 4 — 豆豆注入建议
文件：`backend/src/cangjie_fos/services/npc_chat_graph.py`（`inject_system_health` 节点）
- 在现有 readiness + 失败任务注入之后，追加：读取未消费的 `nightly_suggestions`（priority≤5，最多3条），格式化后拼入系统提示
- 豆豆回答后调用 `db_nightly_suggestion_mark_consumed`

### Task 5 — 手动触发端点（调试用）
`POST /api/v1/admin/nightly-settle?tenant_id=X` — 立即执行单租户结算，返回生成的建议数量

### Task 6 — 测试
`tests/test_nightly_settle.py`（≥8个测试）：
- 表创建验证
- CRUD 基础操作
- nightly_settle_for_tenant mock 调用链
- 手动触发端点 200/422

**CI 验证：258+ passed（当前基线），无需环境变量，commit + push**

---

## 提交消息格式

```
type(scope): 简短描述（中英文均可）

type: feat | fix | docs | chore | refactor | test
scope: backend | frontend | pipeline | npc | db | ci

示例：
feat(pipeline): 新增 substatus 8节点进度追踪
fix(api): 修复 warnings JSON 反序列化 500 错误
docs: 更新 CHANGELOG Phase 7.0 进度
```
