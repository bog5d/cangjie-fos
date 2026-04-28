# AGENTS.md — 仓颉 FOS · AI 协作操作手册

> **所有 AI Agent（Claude、Cursor、Hermes、Codex 等）进入本仓库前必读。**  
> 本文档是权威操作规范，优先级高于任何其他文档。

---

## 当前版本状态（最后更新：2026-04-28）

| 项目 | 状态 |
|------|------|
| 版本 | v0.5.1 |
| 测试基线 | **278 passed**（`cd backend && uv run --extra dev pytest tests/ -q`） |
| 前端构建 | **零错误**（`cd frontend && npm run build`） |
| 当前 Phase | **Phase 7.0 阶段4完成（v0.5.1）→ Phase 7.0 阶段5待开始** |
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
| 阶段3 | APScheduler夜间自动进化任务 | ✅ 完成（v0.5.0，266 passed） |
| 阶段4 | 全数据关联（路演→素材→机构→贡献者） | ✅ 完成（v0.5.1，278 passed） |
| 阶段5 | Doctor强化（外发版自愈） | ⏳ 待开始 |

FSS 路径：`D:\AI_Workspaces\AI_Pitch_Coach`（阶段1完成后归档）

## 立即要做（阶段4 — 全数据关联）

**阶段3已完工（v0.5.0）**：APScheduler每晚2点运行，nightly_suggestions表，豆豆注入，266 passed。

**阶段4核心目标**：一次路演结束后，自动触发全链路数据关联——路演→素材→机构→贡献者→进化记忆，形成完整数据图。

### 背景（必读）
现有数据孤岛：
- `pitch_jobs` 记录路演，但风险点不关联素材
- `material_contributions` 有贡献度表，但没人往里写数据
- `nightly_suggestions` 有建议表，但 `nightly_settle` 只生成文字，没有真实计算
- `evolution_capture.py` 骨架已落地，但 `capture_review_diff` 只记录 diff，不触发下游

目标：路演 commit（审查员提交修改）→ 自动触发4条关联链路

### Task 1 — pitch_job_db.py：新增关联查询函数
```python
# 查询某租户最近N条已完成路演的风险点列表（用于素材匹配分析）
def db_job_list_risk_keywords(tenant_id: str, limit: int = 10) -> list[dict]
# 查询素材库中与关键词匹配的素材（基于 assets 表 tags/title 字段）
def db_assets_search_by_keywords(tenant_id: str, keywords: list[str]) -> list[dict]
# 批量 upsert 素材贡献度（路演用到了哪些素材 → 增加 usage_count）
def db_material_contribution_bulk_upsert(tenant_id: str, asset_ids: list[str], action: str) -> None
```

### Task 2 — evolution_capture.py：扩展 capture_review_diff
文件：`backend/src/cangjie_fos/services/evolution_capture.py`
在现有 `capture_review_diff(job_id, tenant_id, original, edited)` 函数末尾追加：
1. 提取 edited 报告中的风险点关键词 → 调用 `db_assets_search_by_keywords` 找相关素材
2. 调用 `db_material_contribution_bulk_upsert`，action="review_use"，记录本次用到的素材
3. 将匹配到的素材写入 `material_match_history`（institution_id 取 job 的 tenant_id，matched_assets 为 JSON）

### Task 3 — nightly_settle.py：真实素材建议计算
替换 `_generate_material_suggestions` 的占位实现：
- 读取最近10条已完成路演的风险关键词（`db_job_list_risk_keywords`）
- 与素材库做 TF-IDF 简单相似度（纯 Python，不引入 sklearn）
- 找出覆盖率低于30%的风险点类型 → 生成 "material_update" 建议
- 找出 contribution_score 为0但被多次引用的素材 → 生成 "institution_insight" 建议

### Task 4 — 前端：贡献度排行榜组件（轻量）
文件：`frontend/src/components/ContributionBoard.tsx`（新建）
- 调用 `GET /api/contributions?tenant_id=X&limit=10`
- 显示排行：名次 + 贡献者名 + 得分 + 素材数
- 在 `AssetLibrary` 页底部嵌入（不新建页面）

### Task 5 — API 端点：关联触发日志
`GET /api/v1/admin/association-log?tenant_id=X&limit=20`
- 返回最近的 `material_match_history` 记录，字段：institution_id, matched_count, created_at
- 用于调试：确认关联链路真实触发

### Task 6 — 测试（≥10个）
`tests/test_phase4_association.py`：
- `db_job_list_risk_keywords` 返回正确格式
- `db_assets_search_by_keywords` 关键词匹配
- `db_material_contribution_bulk_upsert` ON CONFLICT 累加
- `capture_review_diff` 触发后 `material_contributions` 有新记录
- `nightly_settle_for_tenant` 真实素材建议计算（mock assets 数据）
- `/api/v1/admin/association-log` 200 + 字段结构

**CI 验证：266+ passed，npm build 零错误，commit + push**

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
