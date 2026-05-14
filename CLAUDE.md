# CangJie FOS — AI 开发标准

---

## 🟢 接手速览（新 AI / 新人第一眼看这里）

> 最后更新：2026-05-14 | 当前版本：**v0.5.4** | 测试基线：**502 passed**

### 项目是什么
仓颉 FOS（融资作战操作系统）= 一个帮 VC/FA 管理融资流程的内部工具。
- **后端**：`D:\AI_Workspaces\CangJie_FOS\backend\` — FastAPI + SQLite + LangGraph
- **前端**：`D:\AI_Workspaces\CangJie_FOS\frontend\` — React + TypeScript + Vite
- **分析引擎**：`D:\AI_Workspaces\AI_Pitch_Coach\` — 路演评分/路演情报 LangGraph 图
- **进入点**：`backend/src/cangjie_fos/main.py` — FastAPI app + lifespan

### 最近做了什么（v0.5.3 → v0.5.4）

| 版本 | 日期 | 主要内容 |
|------|------|---------|
| v0.5.3 | 05-12 | Chrome叠层Bug（5个Modal + ExpHud）+ 路演数据打通Pipeline CRM + Playwright浏览器测试 |
| v0.5.4 | 05-14 | 3个Bug修复：路演报告Step5字段undefined / 删风险点评分不重算 / 历史列表缺机构名 |

### 同事反馈的13个问题——当前处理状态

同事（zt001）测试 v0.5.3 后提了13个问题，按「纯Bug」优先级分类处理：

**✅ 已修复（v0.5.4）：**
- Bug #11：路演报告第5步报告大量字段显示undefined/空白（TypeScript接口与后端schema不符）
- Bug #7：复盘审查台删除风险点后总分不自动重算
- Bug #5：复盘历史记录列表缺机构名列（PitchJobSummary schema未含 institution_id）

**⏳ 待处理（未分类，原始编号 #1~#13，排除已修复3个）：**
- #1：录音片段不完整（ASR相关）
- 其余9个问题含 UX改进、配置类、边缘场景 — 需要重新读同事反馈原文确认优先级
- 原始反馈截图在上个 session，可从 `C:\Users\王波\.claude\projects\D--AI-Workspaces\195c2d2c-9faa-4f3d-9a22-f349da20ac24.jsonl` 检索

### 启动开发环境

```powershell
# 后端（另开终端）
cd D:\AI_Workspaces\CangJie_FOS\backend
uv run uvicorn cangjie_fos.main:app --reload --port 8000

# 前端（另开终端）
cd D:\AI_Workspaces\CangJie_FOS\frontend
npm run dev   # 只在需要热更新时，通常直接用 backend serve 的 dist/
```

### 跑测试

```powershell
cd D:\AI_Workspaces\CangJie_FOS\backend
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
# 期望：502+ passed，0 failed
```

### 关键架构约定（不要推翻）
- `pitch_jobs.institution_id` 存的是**机构名字符串**，不是UUID（历史遗留命名）
- `RoadshowIntelReport` 字段：`key_verbatim_moments: List[str]`（纯字符串，不是对象）
- `IntelQuestion.verbatim / underlying_concern / speaker_id`（不是 question/theme/asked_by）
- `IntelSignal.verbatim / signal_type / interpretation`（不是 signal/sentiment）
- `IntelAction.actor / action / priority`（不是 owner/deadline）
- Review API 读 SQLite（`db_job_get`），不读内存 store

---

## 核心原则：代码改动必须有测试覆盖，不依赖人工点 UI 验证

### 测试运行命令
```bash
cd backend
uv run --extra dev pytest tests/ -q   # 全套，133+ passed 才算通
uv run --extra dev pytest tests/test_pipeline_e2e.py tests/test_wizard_pipeline_e2e.py -v  # 核心链路
```

---

## 强制测试标准（每次改动后必须执行）

### 1. 改了后端任何 service / route / schema
- 必须跑 `pytest tests/` 全套
- 新增功能必须同步新增对应测试，不允许"先上线后补测试"

### 2. 改了 pipeline 链路（pitch_upload_pipeline / pitch_wizard_runner）
- 必须确认 `test_pipeline_e2e.py` 和 `test_wizard_pipeline_e2e.py` 全过
- 这两个测试覆盖了「数据异常」的根因链路：DB写入 → Review API → 前端可读

### 3. 新增后台任务（BackgroundTask）
- 必须同步写 DB（`db_job_update`），不能只写内存 store
- 必须在 E2E 测试中验证 DB 状态，不能只 mock

### 4. 新增 API 端点
- 必须在对应 `test_p*_*.py` 文件中覆盖：200正常流、404异常、字段结构

---

## 禁止行为

- ❌ 改完代码说"应该好了，你去试一下" — 必须先跑测试证明
- ❌ 只 mock 外部服务而不验证 DB 写入 — DB 才是审查台的数据源
- ❌ 新增 pipeline 步骤后不同步更新 E2E 测试
- ❌ 依赖人工上传音频来验证流程 — 用 `make_wav()` 生成测试音频

---

## 测试分层架构

| 层级 | 文件 | 覆盖范围 | mock范围 | 运行命令 |
|------|------|---------|---------|---------|
| 单元/接口 | `test_pitch_job_db.py` `test_p0_review_endpoints.py` 等 | 单个函数/端点 | 全mock | `pytest tests/ -q` |
| Pipeline E2E | `test_pipeline_e2e.py` | 简单上传全链路 | mock ASR+LLM | `pytest tests/ -q` |
| Wizard E2E | `test_wizard_pipeline_e2e.py` | 向导提交全链路 | mock ASR+LLM | `pytest tests/ -q` |
| Roadshow E2E | `test_roadshow_e2e.py` | 路演分析全链路 | mock ASR+LLM | `pytest tests/ -q` |
| 浏览器烟雾 | `test_ui_smoke.py` | Chrome渲染+点击 | 无（真实浏览器） | `pytest tests/test_ui_smoke.py -v` |
| 启动检查 | preflight.py（lifespan自动跑） | 依赖包完整性 | 无mock | 自动 |

### 浏览器烟雾测试（Playwright）

**前提**：
1. `playwright install chromium`（已安装，一次性操作）
2. FOS 服务必须在运行中（`127.0.0.1:8000`），否则自动 skip

**运行**：
```bash
# 先启动服务（另一个终端）
# 然后：
uv run --extra dev pytest tests/test_ui_smoke.py -v           # 无头
uv run --extra dev pytest tests/test_ui_smoke.py -v --headed  # 有头调试
```

**新增 UI 功能必须配套浏览器烟雾测试**：
- 新增全屏 Modal / Wizard → 必须测试：关闭态无叠层 + 开启态可交互
- 测试文件：`backend/tests/test_ui_smoke.py`
- 核心断言模式：登录后检查 `fixed` 元素的 `pointer-events` 不为 `auto`（大面积叠层）

---

## 新增功能时的标准流程

1. 写代码
2. 写测试（参照现有 E2E 测试的 mock 模式）
3. `pytest tests/ -q` 全绿
4. 报告：`X passed`，不说"可以了你试试"

---

## 关键架构约定（不要推翻）

- Review API 读 SQLite（`db_job_get`），不读内存 store
- 所有 pipeline 必须同时写内存（`job_update`）和 SQLite（`db_job_update`）
- 音频文件永久路径：`backend/data/audio/{job_id}{suffix}`
- HTML报告路径：`backend/data/html_reports/{job_id}.html`，通过 `/reports/` 静态服务

## 依赖管理
- 缺包用 `uv add <package>`，不用 pip
- 新增依赖后必须重启 uvicorn（热重载不可靠）
- 启动时 preflight.py 自动检查必选依赖，缺失会阻断启动并提示安装命令
