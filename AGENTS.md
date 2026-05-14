# AGENTS.md — 仓颉 FOS AI 接手手册

> **所有 AI Agent（Claude、Cursor、Codex 等）进入本仓库前必读。**  
> 权威操作规范，优先级高于任何其他文档。  
> 工作流：`git clone` → 读本文件 → 读 CLAUDE.md → 开始工作

---

## 当前状态（最后更新：2026-05-14）

| 项目 | 状态 |
|------|------|
| 版本 | **v0.5.4** |
| 测试基线 | **502 passed**（命令见下） |
| 前端构建 | **零错误**（`cd frontend && npm run build`） |
| 详细变更历史 | 见 `CHANGELOG.md` |

---

## 这个项目是什么

**仓颉 FOS（融资作战操作系统）** — 帮 VC/FA 管理融资流程的内部工具。

```
cangjie-fos/（本仓库）
├── backend/                FastAPI + SQLite + LangGraph 后端
│   └── src/cangjie_fos/
│       ├── api/routes/     HTTP 路由
│       ├── services/       业务逻辑 + DB 操作
│       ├── engine/         ASR转写 / LLM评估（从 AI_Pitch_Coach 迁入的子包）
│       └── main.py         FastAPI app 入口
├── frontend/               React + TypeScript + Vite 前端
│   └── src/
│       ├── components/     UI 组件（RoadshowWizard / PitchJobHistory 等）
│       └── pages/          ReviewWorkbench / WarRoomMap 等页面
├── tools/                  doctor.py 诊断脚本、build_release_zip.ps1 打包
├── CLAUDE.md               开发规范（测试标准 + 架构约定详细版）
├── AGENTS.md               本文件（AI 接手手册）
└── CHANGELOG.md            版本历史

【外部依赖 — 兄弟目录，独立仓库】
../AI_Pitch_Coach/          LLM 评估引擎原始仓库
                            测试时通过 mock 绕过，502 个测试无需它存在
                            生产运行需要，向王波索取访问权限
```

---

## 克隆后第一步：验证环境

```bash
# 1. 克隆主仓库
git clone https://github.com/bog5d/cangjie-fos.git
cd cangjie-fos

# 2. 安装后端依赖（用 uv，不用 pip）
cd backend
uv sync --extra dev

# 3. 跑测试确认基线（不需要 AI_Pitch_Coach，全 mock）
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
# 期望：502 passed，0 failed

# 4. 前端构建验证（可选）
cd ../frontend && npm install && npm run build
# 期望：zero errors，built in ~4s
```

---

## 最近做了什么（v0.5.3 → v0.5.4）

### v0.5.4（2026-05-14）— 同事反馈 Bug 修复

同事 zt001 测试后提了 13 个问题，本版修复其中 3 个「纯 Bug」：

| Bug | 现象 | 根因文件 | 修复 |
|-----|------|---------|------|
| #11 | 路演报告第5步字段全undefined/空白 | `frontend/src/components/RoadshowWizard.tsx` | TypeScript 接口与后端 schema 字段名不符，全部对齐 |
| #7 | 删除风险点后总分不更新 | `frontend/src/pages/ReviewWorkbench.tsx` | `handleRiskDelete` 补加 `total_score` 重算逻辑 |
| #5 | 历史列表没有机构名 | `schemas/pitch_upload.py` + `routes/pitch.py` + `PitchJobHistory.tsx` | `PitchJobSummary` 加 `institution_id` 字段并全链路回填 |

**⏳ 待处理（剩余 10 个问题）：**
- 已知 #1：录音片段不完整（ASR 相关）
- 其余 9 个：优先级待王波确认（向王波索取原始反馈截图）

### v0.5.3（2026-05-12）— Chrome 叠层 Bug + 路演数据打通

- Chrome 登录后整页被透明膜覆盖无法点击 → 5 个 Modal 组件 + ExpHud 加 `pointer-events-none`
- 路演完成后 Pipeline CRM 不更新 → `pitch_upload_pipeline.py` 完成后调 `upsert_institution()`
- 引入 Playwright 浏览器烟雾测试（`tests/test_ui_smoke.py`，6 个测试）

---

## 关键架构约定（踩过坑的教训）

### RoadshowIntelReport 字段名（v0.5.4 已修正，别再改错）

| 接口/字段 | ❌ 错的（前端曾用过） | ✅ 对的（`engine/schema.py` 权威） |
|---------|-------------------|--------------------------------|
| `key_verbatim_moments` | `KeyVerbatim[]` 对象数组 | `string[]` 纯字符串列表 |
| `IntelQuestion` 字段 | `question / theme / asked_by` | `verbatim / underlying_concern / speaker_id` |
| `IntelSignal` 字段 | `signal / sentiment` | `verbatim / signal_type / interpretation` |
| `IntelAction` 字段 | `owner / deadline` | `actor / action / priority`（无 deadline） |

### 数据层约定

- `pitch_jobs.institution_id` 存的是**机构名字符串**，不是 UUID（历史命名问题，勿混淆）
- Review API 读 SQLite（`db_job_get`），不读内存 store
- 所有 pipeline 必须同时写内存（`job_update`）和 SQLite（`db_job_update`）
- `engine/schema.py` 是所有报告 schema 的权威来源，前端接口必须与之对齐

---

## 开发铁律

### 改完代码必须跑测试

```bash
cd backend
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
# 502+ passed，0 failed 才算完成
```

### 提交规范

```bash
git pull origin master          # 先拉最新
# ...改代码...
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q  # 必须全绿
git add <具体文件>              # 禁止 git add -A（防止提交 .env）
git commit -m "fix(wizard): 修复路演报告字段名"
git push origin master
```

提交格式：`type(scope): 描述`  
type：`feat` | `fix` | `docs` | `refactor` | `test` | `chore`

### 禁止行为

| 禁止 | 原因 |
|------|------|
| 改完说「应该好了你试试」 | 必须先跑测试证明 |
| `git add -A` 或 `git add .` | 可能提交 `.env`（API Key 泄露） |
| 只 mock 外部服务不验证 DB 写入 | DB 才是审查台的数据源 |
| 新增 pipeline 步骤不同步更新 E2E 测试 | 覆盖缺失 = 没有测试 |

---

## 测试分层速查

| 层级 | 命令 | 覆盖范围 | 前提 |
|------|------|---------|------|
| API + E2E（主力） | `pytest tests/ -q --ignore=tests/test_doctor_script.py` | 全后端逻辑 + DB | 无（全 mock） |
| 浏览器烟雾 | `pytest tests/test_ui_smoke.py -v` | Chrome 渲染 + 点击 | 服务需在 8000 端口运行 |

---

## 关键文件速查

| 文件 | 作用 |
|------|------|
| `CHANGELOG.md` | 版本历史，每次提交前必须更新 |
| `CLAUDE.md` | 测试标准 + 开发规范详细版 |
| `backend/src/cangjie_fos/main.py` | FastAPI app 入口 + lifespan |
| `backend/src/cangjie_fos/engine/schema.py` | **所有报告 schema（字段名权威来源）** |
| `backend/src/cangjie_fos/services/pitch_upload_pipeline.py` | 上传→ASR→评估主流水线 |
| `backend/src/cangjie_fos/services/pitch_job_db.py` | SQLite 持久化层（单一真相源） |
| `backend/src/cangjie_fos/api/routes/roadshow.py` | 路演分析专属 5 个端点 |
| `frontend/src/components/RoadshowWizard.tsx` | 路演分析 5 步向导（Step5 刚修过） |
| `frontend/src/pages/ReviewWorkbench.tsx` | 全屏审查台 |
| `backend/tests/test_pipeline_e2e.py` | Pipeline 核心 E2E 测试 |
| `backend/tests/test_roadshow_e2e.py` | 路演分析 E2E 测试（17 个） |
