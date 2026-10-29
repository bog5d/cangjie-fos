# CangJie FOS — AI 开发标准

---

## 🟢 接手速览（新 AI / 新人第一眼看这里）

> 最后更新：2026-05-29 | 当前版本：**v1.1.2** | 测试基线：**660+ passed** | 单仓库可运行：✅

### 项目是什么
仓颉 FOS（融资作战操作系统）= 一个帮 VC/FA 管理融资流程的内部工具。
- **后端**：`backend/` — FastAPI + SQLite + LangGraph
- **前端**：`frontend/` — React + TypeScript + Vite
- **分析引擎**：`backend/src/cangjie_fos/engine/` — 路演评分/路演情报（从 AI_Pitch_Coach 迁入）
- **进入点**：`backend/src/cangjie_fos/main.py` — FastAPI app + lifespan
- **外部依赖**：无 — `engine/` 子包已包含所有核心模块，AI_Pitch_Coach 是可选的历史归档

### 最近做了什么（v0.5.3 → v1.1.0）

| 版本 | 日期 | 主要内容 |
|------|------|---------|
| v0.5.3 | 05-12 | Chrome叠层Bug（5个Modal + ExpHud）+ 路演数据打通Pipeline CRM + Playwright浏览器测试 |
| v0.5.4 | 05-14 | 3个Bug修复：路演报告Step5字段undefined / 删风险点评分不重算 / 历史列表缺机构名 |
| v0.5.5 | 05-14 | **单仓库自包含**：移除 AI_Pitch_Coach 外部依赖，clone 一个仓库即完整 |
| v0.6.0 | 05-15 | 7个Bug修复（#2/#4/#6/#8/#9/#12/#13）+ 启动失败自动诊断 + Pipeline卡片编辑 |
| v0.6.1 | 05-15 | 修复向导轨道任务完成后不同步 GitHub 的 Bug（pitch_wizard_runner 补加 push_pitch_job）|
| v0.6.2 | 05-15 | 预埋默认配置（Token/Key/账号）— 外发包开箱即用，无需同事手动填 .env |
| v0.6.3 | 05-15 | Bug #3 + Bug #10：尽调匹配子串化 + 打包下载 + 资产搜索增强 |
| v0.6.4 | 05-15 | npc_chat_graph 测试(23个) + 残留代码清理 |
| v0.6.5 | 05-15 | 收敛20个裸 except Exception 为具体异常类型，测试基线 596 passed |
| v0.6.6 | 05-15 | **根治启动脚本编码崩溃**：PS1 here-string → 数组；bat 全部 UTF-8 重写；JSON读取 GBK 兜底 |
| v0.6.7 | 05-15 | Bug 3.5/3.6：data/audio 目录自动创建；HTML报告缺音频优雅降级（不再崩溃） |
| v0.6.8 | 05-15 | _isolate_db_per_test autouse DB 隔离；get_audio_dir() 抽象；bare except 全面收敛；605 passed |
| v0.6.9 | 05-15 | **外发版**：build_release_zip.ps1 排除 .claude 目录；发版文档更新为开箱即用说明 |
| v0.7.0 | 05-15 | **尽调响应台**：清单解析 + AI 批量匹配 + 表格审核 + 导出文件夹；20个新测试（625 passed）|
| v0.7.1 | 05-15 | **红队加固**：修复7个尽调响应台崩溃点（临时文件泄漏/空结果404级联/session永不完成/fetch无错误处理/轮询无超时/空结果强跳Step3/interval内存泄漏）|
| v0.7.2 | 05-16 | **稳定性加固**：统一 LLM 客户端 + 重试/显式NULL标记/服务重启DB fallback/导出大小上限 |
| v0.8.0 | 05-16 | **尽调响应台全面升级**：分块解析/文件预筛/Session历史/批量确认/手动替换/机构联动/GitHub同步 |
| v0.9.0 | 05-16 | **Bug修复**：Bug #10 资产搜索中文回归测试 + utcnow deprecation修复 |
| v1.0.0 | 05-18 | **尽调响应台体验升级**：原生文件夹/文件选取框（tkinter），三处路径输入均支持 |
| v1.1.0 | 05-21 | **5个同事Bug修复**：扫描超时+进度/向导白字/匹配全无效/路演全字段编辑/路演HTML导出 |
| v1.1.1 | 05-21 | **同事支持**：load_dotenv()修复重启Token丢失；GitHub Token设置UI；tkinter弹窗置顶修复；EXP HUD移除 |
| v1.1.2 | 05-29 | **SettingsPanel白字修复**：4个输入框 text-white→text-gray-800；venv重建；CHANGELOG补全 |

### 同事反馈的13个问题——当前处理状态

同事（zt001）测试 v0.5.3 后提了13个问题，按「纯Bug」优先级分类处理：

**✅ 已修复（v0.5.4 + v0.6.0，共10个）：**
- Bug #2：新增风险点「问题简述」字段（AddRiskPointForm 新增 problem_summary 输入）
- Bug #4：口述实录可编辑（RiskPointCard 展示并可编辑 original_text）
- Bug #5：历史记录显示机构名（PitchJobSummary + institution_id）
- Bug #6：锁定后可解锁编辑（WorkbenchHeader 🔓按钮 + DELETE /review-lock）
- Bug #7：删风险点总分自动重算（handleRiskDelete 补加重算逻辑）
- Bug #8：Pipeline卡片可点击编辑（InstitutionList 点击开 EditModal）
- Bug #9：Pipeline阶段可手动切换（EditModal stage 下拉菜单）
- Bug #11：路演报告Step5字段对齐（RoadshowWizard TS接口与schema一致）
- Bug #12：路演情报报告有编辑入口（RoadshowIntelView 编辑摘要模式）
- Bug #13：Pipeline卡片内容为空时提示并可点击填充

**⏳ 待处理（剩余3个）：**
- #1：录音片段不完整（ASR片段截取，ASR核心逻辑改动，风险高）
- #3：尽调匹配不准 + 无打包下载（两个独立复杂功能）
- #10：资产台账搜索不到（扫描逻辑需深入调查）

### 启动开发环境

```bash
# 后端（克隆后）
cd backend
uv run uvicorn cangjie_fos.main:app --reload --port 8000

# 前端热更新（可选）
cd frontend && npm run dev
```

### 跑测试

```bash
cd backend
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
- **字段名权威来源**：`backend/src/cangjie_fos/engine/schema.py`，前端接口必须与之对齐
- **DD 物料架构（v1.9.0，不要推翻）**：
  - 内容层 `dd_asset_index.content_text`（全文）只用来「懂/匹配/精判」，**绝不替换原件**；交付永远走原始文件（审过的），不重新生成。
  - 匹配生产线：粗筛(关键词) → 全文精判(`_refine_session_matches` 看正文) → 机器验证(`verdict` 红/黄/绿 + `evidence`)。
  - 跨机构学习用 `dd_decision_memory`（记忆化 + 历史检索，**不是 fine-tune**）；材料库共享 → 需求→文件 映射机构无关全局复用。
  - 人工闸**不需要 LangGraph**：DB 落库 + Web 接口即 checkpoint。
  - 详见 `AGENTS.md`「DD 物料架构」节，含**下一步「写材料」场景**的钩子。

---

## 核心原则：代码改动必须有测试覆盖，不依赖人工点 UI 验证

### 测试运行命令
```bash
cd backend
uv run --extra dev pytest tests/ -q   # 全套，502+ passed 才算通
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

## 🔴 强制约定：模拟人工测试（带截图 PDF 报告）

> **这是 Claude / Codex 每次涉及前端开发后的不可跳过动作。**
> 起因：vitest 跑在 jsdom 里，看不到真实 Chrome 渲染、CSS 可见性、叠层阻塞、
> 真实点击跳转——约 30% 的真实人工场景测不到。「vitest 全绿」≠「用户能用」。

### 规则（写任务给 Codex 时必须照此交代）

1. **凡是改了任何前端组件（`.tsx`/`.ts`），必须写/更新 Playwright 浏览器冒烟测试**，
   不能只靠 vitest。两者都必须通过。
2. **每个被测功能给出逐步「人工点击指引」**：从哪个入口进、点哪个按钮、
   期望看到什么、在哪一步截图。指引直接写进 `test_ui_smoke.py` 的测试方法里
   （每一步 `ui_reporter.capture(page, "步骤名", status=...)`）。
3. **测试过程产出带截图的 PDF 报告**：用 `ui_reporter` fixture（见
   `backend/tests/ui_report.py`）。每个关键步骤截一帧，顶部中文横幅标
   PASS/FAIL + 备注。任一步 FAIL → PDF 文件名自动带 `FAILED_` 前缀。
4. **PDF 回传给 Claude 审核**：报告落在 `backend/data/ui_reports/`，
   Codex 跑完后把 PDF 路径/文件回传，由 Claude（或人）逐帧审 UI 真实渲染。
5. **不得靠 skip 蒙混**：服务未启动会自动 skip，但 Codex 必须先起前后端服务
   再跑——全部 skip 视为「未完成」，不算通过。

### 怎么用（标准片段）

```python
def test_xxx(self, page, fos_server_url, fos_login_credentials, ui_reporter):
    _login(page, fos_server_url, fos_login_credentials)
    page.locator("button:has-text('入口名')").click()
    page.wait_for_timeout(800)
    try:
        expect(page.get_by_text("期望文字")).to_be_visible(timeout=6_000)
        ui_reporter.capture(page, "步骤名 — 期望达成", status="ok", note="说明")
    except AssertionError:
        ui_reporter.fail(page, "步骤名 — 失败", note="实际现象")
        raise
```

```bash
# 跑法（先起服务）：
cd backend && uv run uvicorn cangjie_fos.main:app --port 8000   # 终端1
cd frontend && npm run dev                                       # 终端2
cd backend && uv run --extra dev pytest tests/test_ui_smoke.py -v -s  # 终端3
# -s 让 PDF 路径打印到 stdout；报告在 backend/data/ui_reports/
```

### 工具文件

| 文件 | 作用 |
|------|------|
| `backend/tests/ui_report.py` | `UIReporter`：截图 + 中文标注 → 合成多页 PDF（仅用 Pillow，零新依赖） |
| `backend/tests/conftest.py` | `ui_reporter` session fixture：跑完自动 finalize PDF 并打印路径 |
| `backend/tests/test_ui_smoke.py` | 浏览器冒烟测试集（含 `TestDueDiligenceWizardSmoke` 参考实现） |
| `backend/data/ui_reports/` | PDF 报告输出目录（gitignored，回传给 Claude） |

---

## 新增功能时的标准流程

1. 写代码
2. 写测试（参照现有 E2E 测试的 mock 模式）
3. `pytest tests/ -q` 全绿
4. **改了前端 → 写/更新 `test_ui_smoke.py` 的 Playwright 浏览器测试 + `ui_reporter` 截图**
5. 起前后端服务跑 `pytest tests/test_ui_smoke.py -v -s`，产出带截图 PDF（`backend/data/ui_reports/`）
6. 报告：`X passed` + PDF 路径，不说"可以了你试试"

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

---

## v0.6.0 改动文件清单（接手必读，2026-05-15）

> 以下是本版本所有改动过的文件，接手 AI 在改相关功能前先读这些文件。

### 启动体验（Group A）

| 文件 | 改了什么 |
|------|---------|
| `安装并启动.ps1` | 完全重写：启动过程写日志到 `backend/logs/startup_*.log`；任何步骤失败自动在桌面生成「诊断报告_请发给AI_时间戳.txt」并用记事本打开 |
| `tools/doctor.py` | `--fix` 模式增加日志文件（`backend/logs/doctor_fixes.log`），每条修复操作有时间戳记录 |
| `backend/logs/.gitkeep` | 新建：让 `backend/logs/` 目录被 git 追踪 |
| `.gitignore` | `logs/` 改为 `/logs/`（只排除根目录 logs，不排除 backend/logs） |
| `backend/.gitignore` | 新增 `logs/*.log` + `!logs/.gitkeep` |

### Bug #2 — 新增风险点「问题简述」字段

| 文件 | 改了什么 |
|------|---------|
| `frontend/src/components/workbench/left/AddRiskPointForm.tsx` | 在改进建议前新增 `problem_summary` 输入框（30字内，一句话概括） |

### Bug #4 — 口述实录可编辑

| 文件 | 改了什么 |
|------|---------|
| `frontend/src/components/workbench/left/RiskPointCard.tsx` | 风险点卡片新增「口述实录」区块，显示 `original_text`；非锁定状态下为可编辑 textarea |

### Bug #6 — 锁定后可解锁编辑

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/api/routes/pitch.py` | 新增 `DELETE /api/v1/pitch/jobs/{job_id}/review-lock`，清除 `committed_at` 字段 |
| `frontend/src/components/workbench/WorkbenchHeader.tsx` | 新增 `onUnlock` / `unlocking` props；锁定状态下显示「🔓 解锁编辑」琥珀色按钮 |
| `frontend/src/pages/ReviewWorkbench.tsx` | 新增 `unlocking` state 和 `handleUnlock` 回调；`handleCommit` 接受可选 `reportOverride` 参数（支持路演报告保存） |

### Bug #8 / #9 / #13 — Pipeline 卡片编辑

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/schemas/institution.py` | 新增 `InstitutionProfileUpdate` Pydantic schema（name/stage/thermal/preferences/concerns/ai_summary 均可选） |
| `backend/src/cangjie_fos/services/institution_store.py` | 新增 `update_institution(institution_id, update)` 函数，参数化 UPDATE + 重新 SELECT 返回最新行 |
| `backend/src/cangjie_fos/api/routes/pipeline.py` | 新增 `PATCH /api/v1/pipeline/institutions/{institution_id}` 端点 |
| `frontend/src/components/InstitutionList.tsx` | 完全重写：卡片可点击（cursor-pointer），点击弹出内联 `EditModal`；支持 ai_summary/concerns/preferences/stage/thermal 编辑；空卡片显示「暂无摘要 · 点击编辑机构画像」；保存后乐观更新 `localItems` state |

### Bug #12 — 路演情报报告编辑入口

| 文件 | 改了什么 |
|------|---------|
| `frontend/src/components/workbench/RoadshowIntelView.tsx` | 新增 `onSave` / `saving` props；内部新增 `editMode` 和 `draft` state；顶部「✏️ 编辑摘要」/ 「取消」/ 「💾 保存」按钮；可编辑字段：`atmosphere_summary`、`hidden_concerns`（换行分隔）、`institution_update` |

### 文档更新

| 文件 | 改了什么 |
|------|---------|
| `CHANGELOG.md` | 新增完整 `[0.6.0] — 2026-05-15` 版本块 |
| `CLAUDE.md`（本文件） | 版本号、测试基线、版本历史表、13问题状态、本文件清单 |
| `AGENTS.md` | 版本号、状态表、v0.6.0 节、13问题完整追踪表 |
| `packaging/本次更新说明.md` | 完全重写为 v0.6.0 内容（7个修复 + 验收清单） |
| `同事上手指南.md` | 版本号 + 功能一览新增 v0.6.0 改进节 + 测试清单新增 v0.6.0 验收 + 已知问题新增 v0.6.0 修复记录 |

### v0.6.2 改动文件清单（2026-05-15）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/core/_embedded.py` | **新建（gitignored，仅在外发 zip 里）**：Base64 编码存储 Token/Key/账号，开箱即用 |
| `backend/src/cangjie_fos/main.py` | lifespan 最开始调用 `inject_defaults()`，注入内置配置（.env 里有值时不覆盖） |
| `backend/.gitignore` | 新增 `_embedded.py` 排除规则，防止 Token 被推送到公开 GitHub 仓库 |

> ⚠️ `_embedded.py` 不在 git 里，只在 zip 里。更新 Token/Key 需重新生成此文件再打包。

### v0.6.1 改动文件清单（2026-05-15）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/services/pitch_wizard_runner.py` | 向导轨道任务完成后新增 `push_pitch_job(job_id)` 调用，修复数据不同步到 `coach_data` 的 Bug |
| `backend/src/cangjie_fos/services/github_sync.py` | `push_match_session` 中加 TODO 注释（tenant 硬编码问题，待 match_sessions 表加 tenant_id 列后修）|

---

### v0.6.6 改动文件清单（2026-05-15）

| 文件 | 改了什么 |
|------|---------|
| `安装并启动.ps1` | 顶部加 UTF8 编码声明；here-string 改为字符串数组，彻底消除 PS5.1 GBK 解析崩溃；报告文件名改 ASCII；`uv sync --extra dev` 改为 `uv sync`；uv sync 失败后自动清理 .venv 重试 |
| `填写API密钥_双击我.bat` | 完全重写（UTF-8 + chcp 65001）；简化为可选覆盖模式（_embedded.py 已内置默认值，不再强制要求填写） |
| `诊断_打不开请运行我.bat` | 完全重写（UTF-8 + chcp 65001）；保留 `doctor.py --fix` 核心逻辑，界面更简洁 |
| `backend/src/cangjie_fos/engine/asset_bridge.py` | `load_asset_index()` 读 JSON 时增加编码回退链（utf-8 → gbk → utf-8-sig），修复中文 Windows GBK 文件导致的 UnicodeDecodeError |
| `backend/src/cangjie_fos/engine/investor_matcher.py` | `_load_analytics_by_institution()` 同上，编码回退链 |

---

### v0.6.7–v0.6.8 改动文件清单（2026-05-15，另一个 AI + 本 AI 联合完成）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/main.py` | 启动时创建 `data/audio` 目录（Bug 3.5）；`get_audio_dir()` 替换硬编码路径 |
| `backend/src/cangjie_fos/core/paths.py` | 新增 `get_audio_dir()`，支持 `CANGJIE_AUDIO_DIR` 环境变量覆盖（测试可隔离音频目录） |
| `backend/src/cangjie_fos/engine/report_builder.py` | 缺音频不再 raise FileNotFoundError，改为 warning + 降级生成纯文本报告（Bug 3.6）；bare except → 具体异常 |
| `backend/src/cangjie_fos/services/html_report_service.py` | 同上，service 层也优雅降级；更新 docstring |
| `backend/src/cangjie_fos/api/routes/pitch.py` | 7处硬编码音频路径 → `get_audio_dir()` |
| `backend/src/cangjie_fos/api/routes/roadshow.py` | 同上 |
| `backend/src/cangjie_fos/services/pitch_upload_pipeline.py` | 同上 |
| `backend/src/cangjie_fos/services/pitch_wizard_runner.py` | 同上 |
| `backend/src/cangjie_fos/engine/coach/llm_judge/_evaluation.py` | bare except → 具体异常 |
| `backend/tests/conftest.py` | 新增 `_isolate_db_per_test` autouse（每测试独立 SQLite）；豁免列表加 `test_wiki_display`（避免双重 monkeypatch） |
| `backend/tests/test_report_builder.py` | **新建**：desensitize/han_initials/apply_masks + 缺音频降级场景（10个测试） |
| `backend/tests/test_p1b_html_report_service.py` | 移除2个 `@pytest.mark.skip`；补齐完整 mock 链；修复 Win32 路径问题 |

### v0.7.0 改动文件清单（2026-05-15）

| 文件 | 改了什么 |
|------|---------|
| `backend/pyproject.toml` + `uv.lock` | 新增 pdfplumber、openpyxl 依赖 |
| `backend/src/cangjie_fos/services/db_base.py` | `_init_db()` 末尾新增3张表 DDL：`dd_asset_index`、`dd_match_sessions`、`dd_match_items` |
| `backend/src/cangjie_fos/services/dd_file_parser.py` | **新建**：从 PDF/Word/Excel/txt 提取文字（`extract_text(path) → (text, readable)`） |
| `backend/src/cangjie_fos/services/dd_index_service.py` | **新建**：扫描文件夹建索引（`scan_and_index_folder` + `_llm_summarize` + `get_index_by_folder`） |
| `backend/src/cangjie_fos/services/dd_checklist_parser.py` | **新建**：清单解析（代码读格式 → 纯文字；AI 只提取语义需求项）|
| `backend/src/cangjie_fos/services/dd_match_service.py` | **新建**：批量 LLM 匹配（`create_match_session`、`run_matching`、`_llm_batch_match`，每批30条） |
| `backend/src/cangjie_fos/services/dd_export_service.py` | **新建**：导出文件夹 + 缺失清单.txt（`export_to_folder`） |
| `backend/src/cangjie_fos/api/routes/dd_response.py` | **新建**：7个 API 端点（索引/session创建/触发匹配/获取items/更新item/导出） |
| `backend/src/cangjie_fos/api/router.py` | 注册 dd_router |
| `backend/tests/test_dd_file_parser.py` | **新建**：6个测试（parser 4 + index_service 2） |
| `backend/tests/test_dd_checklist_parser.py` | **新建**：7个测试（parser 4 + match_service 2 + export_service 1） |
| `backend/tests/test_dd_e2e.py` | **新建**：7个 E2E 测试（全套 LLM mock） |
| `frontend/src/components/DueDiligenceWizard.tsx` | **新建**：3步向导组件（扫描 → 清单 → 审核导出） |
| `frontend/src/App.tsx` | 新增 `ddOpen` state + `📋 尽调响应` 按钮 + `<DueDiligenceWizard>` 实例 |
| `CHANGELOG.md` | 新增 v0.7.0 版本块 |

---

### v0.6.9 改动文件清单（2026-05-15）

| 文件 | 改了什么 |
|------|---------|
| `tools/build_release_zip.ps1` | 排除目录新增 `.claude`，防止 Claude Code worktree 文件泄漏进发版包 |
| `packaging/本次更新说明.md` | 更新为 v0.6.9：开箱即用说明，账号密码已内置 |
| `同事上手指南.md` | 版本号 → v0.6.9；准备工作简化（不再要求手动填 API Key） |
| `CHANGELOG.md` | 新增 v0.6.9 版本块 |

---

### v0.7.1 改动文件清单（2026-05-15，红队加固）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/api/routes/dd_response.py` | 临时文件 try/finally 清理；LLM返回0条需求时提前 HTTP 400，防止后续 404 级联崩溃 |
| `backend/src/cangjie_fos/services/dd_match_service.py` | `run_matching` 用 try/finally 包裹，保证任何情况下都调用 `_mark_session_done`，防止前端永久轮询 |
| `frontend/src/components/DueDiligenceWizard.tsx` | 全面补 try/catch（fetch 错误 → 用户可见提示）；扫描轮询加120次上限（3分钟）；匹配轮询0条时显示错误而非跳转空表；useEffect cleanup 清理所有 interval |

---

### v0.8.0 改动文件清单（2026-05-16，尽调响应台全面升级）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/services/db_base.py` | migration 12：`dd_match_sessions` 新增 `institution_name` 列；DDL同步更新 |
| `backend/src/cangjie_fos/services/dd_checklist_parser.py` | `_llm_extract_items` 改为分块（4000字/块，300字重叠，去重合并）；新增 `_split_into_chunks` + `_llm_extract_chunk`（可 monkeypatch）；整合 dd_llm_client 重试 |
| `backend/src/cangjie_fos/services/dd_match_service.py` | 新增 `_prefilter_files_for_batch`（汉字二元组预筛，top_n=50）；`_llm_batch_match` 每批调用预筛；`create_match_session` 新增 `institution_name` 参数 |
| `backend/src/cangjie_fos/services/institution_store.py` | 新增 `update_stage_by_name(tenant_id, name, stage)` |
| `backend/src/cangjie_fos/services/github_sync.py` | 新增 `push_dd_session(session_id)` — 推送到 `analytics/{tenant}/dd/` |
| `backend/src/cangjie_fos/api/routes/dd_response.py` | `create_session` 新增 `institution_name` Form参数 + 机构阶段联动；新增 `GET /sessions` + `POST /sessions/{id}/items/bulk-confirm`；`export_session` 新增 BackgroundTasks 触发 GitHub 同步 |
| `backend/tests/test_dd_checklist_parser.py` | 新增4个测试：分块/去重/预筛（100→50）/预筛直通（30） |
| `backend/tests/test_dd_e2e.py` | 新增4个测试：Session历史列表/批量确认/机构阶段联动/GitHub同步 |
| `frontend/src/components/DueDiligenceWizard.tsx` | 全面升级（380→600行）：Session历史面板/机构名称字段/批量确认按钮/手动文件替换内联输入 |

---

### v1.0.0 改动文件清单（2026-05-18）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/api/routes/dd_response.py` | 新增 `GET /pick-folder` 和 `GET /pick-file`，调用 `tkinter.filedialog` 弹出系统原生对话框并返回路径 |
| `frontend/src/components/DueDiligenceWizard.tsx` | 新增 `pickFolder()` / `pickFile()` 工具函数；Step1 材料库路径、Step3 导出路径、手动指定文件三处加「📁 选择」按钮 |
| `packaging/本次更新说明.md` | 版本号 → v1.0.0，更新内容说明 |
| `CHANGELOG.md` | 新增 v1.0.0 版本块 |

---

### v0.9.0 改动文件清单（2026-05-16）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/services/github_sync.py` | `push_roadshow_report` 中 `datetime.utcnow()` → `datetime.now(timezone.utc)`（修复 deprecation 警告） |
| `backend/tests/test_assets_api.py` | 新增 `test_search_sqlite_chinese_filename` + `test_search_sqlite_chinese_tag`（Bug #10 回归测试） |
| `CHANGELOG.md` | 新增 v0.9.0 版本块 |
| `CLAUDE.md`（本文件） | 版本号 v0.9.0、测试基线 643+、版本历史表新增行、改动文件清单 |

---

### v1.1.0 改动文件清单（2026-05-21）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/services/dd_index_service.py` | Bug1：`MAX_LLM_SUMMARIZE_FILES=200`（超量跳过LLM仅记文件名）；`progress_callback` 每50文件触发；timeout从120s→600s |
| `backend/src/cangjie_fos/services/dd_match_service.py` | Bug3：删除 `readable=1` 过滤条件，所有文件（含图片PDF/加密文件）参与匹配 |
| `backend/src/cangjie_fos/api/routes/dd_response.py` | Bug1：`scan_folder` 端点新增 progress 轮询支持；实时返回 scanned/total |
| `frontend/src/components/DueDiligenceWizard.tsx` | Bug2：所有输入框 text 颜色改为 `text-gray-800`（修复白字看不清）；Bug1：扫描进度实时展示 |
| `backend/src/cangjie_fos/api/routes/roadshow.py` | Bug4（路演）：新增 `_build_roadshow_html()` + `POST /jobs/{id}/html-report` + `GET /jobs/{id}/html-report` |
| `frontend/src/pages/ReviewWorkbench.tsx` | Bug4（路演）：新增 `RoadshowHtmlExport` 组件（生成→下载/预览） |
| `frontend/src/components/workbench/RoadshowIntelView.tsx` | Bug5（路演）：`key_questions` / `interest_signals` / `next_actions` 三组卡片接入 `editMode` + `onChange` 实现全字段内联编辑 |
| `backend/tests/test_dd_file_parser.py` | 新增4个测试：大文件夹跳过LLM/小文件夹调用LLM/进度回调/unreadable文件参与匹配 |
| `backend/tests/test_roadshow_api.py` | 新增6个测试：HTML报告生成200/文件写磁盘/无报告404/未知job404/生成前GET404/6节内容完整 |
| `CHANGELOG.md` | 新增 v1.1.0 版本块 |
| `packaging/本次更新说明.md` | 完全重写为 v1.1.0：5个修复说明 + 验收清单 |

---

### v1.1.1–v1.1.2 改动文件清单（2026-05-21 ~ 05-29）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/main.py` | lifespan 开头加 `load_dotenv(override=False)`，修复重启后 .env Token 丢失 |
| `backend/src/cangjie_fos/api/routes/settings.py` | 新增 `COACH_DATA_GITHUB_TOKEN` 到 `_KEY_NAMES`；新增 `POST /api-keys/test-github` 端点 |
| `backend/src/cangjie_fos/api/routes/dd_response.py` | `pick_folder` / `pick_file`：tkinter root 添加 `lift()` + `attributes("-topmost", True)` + `focus_force()`，修复弹窗被遮挡问题 |
| `frontend/src/components/SettingsPanel.tsx` | 新增 GitHub Token 配置区块；4个输入框 `text-white bg-black/40` → `text-gray-800 bg-white`（修复白字不可读） |
| `frontend/src/App.tsx` | 移除 `<ExpHud>` 导入和 JSX 实例（EXP 130 徽章遮挡按钮） |

---

### 待处理问题（v1.1.0 之后）

| 类型 | 现象/目标 | 难度 | 建议入手文件 |
|-----|------|------|------------|
| ~~Bug #1~~ | ✅ **已修复**（commit `46c7f79`，2026-05-15）：缺词级时间戳时用句子级兜底+线性插值，`test_transcriber.py` 10个测试覆盖 | — | — |

**尽调响应台现状（v0.8.0 全面升级后）**：
- ✅ 3步向导：扫描材料库 → 上传清单（Excel/Word/PDF/文字）→ AI 匹配 → 表格审核 → 导出
- ✅ 11个 API 端点：索引/session创建/触发匹配/获取items/更新item/导出/Session历史/批量确认 等
- ✅ 清单分块解析（4000字/块）、大材料库预筛（top-50）、Session历史恢复、批量确认、手动文件替换
- ✅ 机构名联动：创建Session时自动推进机构Pipeline阶段到"DD"
- ✅ GitHub自动同步：导出后推送到 `analytics/{tenant}/dd/`

---

## DD-V1 第 5 轮（2026-10-29 接线轮）改动文件清单（接手必读）

> 交办单：`cangjie-fos#85` ＋ `cangjie-teams-channel#108`。
> 分支 `feat/71-ddv1-exam-v1-20261028`；本轮字节 `fd9bb2174337ee39124aaf8f391de62f2df03449`（＋ 缺陷修复 `b011b2e…`）。
> ★ 上一版的三个模块（entity_resolution / candidate_expansion / agent 选材）**生产链路零调用方** ⇒ 本轮**接进真实组包链**。
> ★ 本轮**没有改动任何既有测试断言**；★ **也没有**改考试/阅卷/评分/预检的判定逻辑（只做接线与口径分离）。

### 改动（服务层）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/services/dd_v1_match_service.py` | ① `resolve_subject_multi_source()`：**多源主体识别接入真实组包链**（只在主口径判 `SUBJECT_UNREGISTERED` 时**补位**；主口径已判命中/他法人的**一律不动**；认不出仍认不出）＋ 形状翻译（manifest 的 `rel_path`/`file_name`/`content_hash` → 模块的 `relative_path`/`sha256`，不翻译则「文件名命中」「人工确认映射」两档永不触发）＋ 留痕 `subject_matched_by`/`subject_multi_source` 落 `dd_v1_matches.evidence`；② `_expand_capped_obligations()`：**候选分批扩展接入实际检索流程**（步长从 cap 之上起步 ⇒ 不重复第一窗；扩展后的结论**替换**原结论、库级判定分布按新结论重算；读数落库级 `candidate_expansion`） |
| `backend/src/cangjie_fos/services/dd_v1_bridge_service.py` | ① `adapter_provenance()`（**id 级旁证**）＋ ★★ `adapter_participation_class()`（**权威：按适配器实现类判定**）＋ `KNOWN_HARNESS_ADAPTERS`（补 `prebaked-result`）；② `_discrimination_readings()`：排除式选择凭据（PASS/WEAK；★ **只证明「不是照抄第一个候选」，不证明出自模型**）；③ 桥接产出 `agent_receipt` / `model_participation` / 每义务 `model_selection`；④ ★ 修**本轮自己引入**的缺陷：`agent_receipt`/`model_sel` 初始化写在 `else` 分支内 ⇒ 空库时 `UnboundLocalError`（既有测试当场抓住） |
| `backend/src/cangjie_fos/services/dd_v1_agent_adapters.py` | 新增 `PrebakedResultAdapter`（贴进来的回执 ⇒ 类别恒 `PREBAKED_RESULT`，**不是** Harness 运行）＋ `build_adapter()` |
| `backend/src/cangjie_fos/services/dd_v1_agent_result_service.py` | `rejected_alternatives`（排除式选择凭据）**硬校验**：排除项须在快照内、**不得**是自己选中的那件、理由非空（`REJECTED_ALT_*`） |
| `backend/src/cangjie_fos/services/dd_v1_agent_result.v1.schema.json` | 新增可选字段 `rejected_alternatives`（file_id + reason） |
| `backend/src/cangjie_fos/services/dd_v1_entity_resolution_service.py` | 人工确认映射**认 `file_id`**；BODY_TEXT 档补 `entity_id`；★ 查表键**归一**（`_confirmed_index()`：原样／去空白小写／归一文件名）⇒ 大写 `file_id` 也能命中 |
| `backend/src/cangjie_fos/services/dd_v1_exam_service.py` | `examinee.mode` 改为**按参与类别**（6 档）＋ `model_selection_obligations`/`rule_selection_obligations`；模型选材进机器答卷（`selection_source=MODEL`） |

### ★ 第 5 轮独立复核（CONDITIONAL）的修复（2026-10-29）

★ Reviewer 第 5 轮（锚点 `5dfaa4f`）裁定 **CONDITIONAL**；**3 条重要缺陷 ＋ 1 条条件项 ＋ 1 条文档计数错误**已逐条修复
（详见 `docs/dd-v1-fos71/ddv1-exam-v1/EVIDENCE.md §9` 与 `最终报告.md §5.2`）：

| # | 缺陷 | 修法 | 文件 |
|---|---|---|---|
| ① | 候选扩展路径**丢掉人工确认映射** | 两层都透传 `confirmed_map` ⇒ 扩展结论与第一遍**同一套口径** | `dd_v1_candidate_expansion_service.py`、`dd_v1_match_service.py` |
| ② | 参与身份**只按自填 `adapter_id`** | 判定入口改为**按实现类**（`ADAPTER_PARTICIPATION_CLASSES` 精确类型匹配，子类也不认）⇒ id 级降级为旁证 `declared_provenance` ＋ 新增 `provenance_mismatch` ＋ **运行痕迹**（`executable`/`argv_digest`/`workdir_digest`） | `dd_v1_agent_adapters.py`、`dd_v1_bridge_service.py` |
| ③ | `PREBAKED_RESULT` **不可达** | 白名单补 `prebaked-result` ＋ 实现类注册表登记（**仍不是** `HARNESS_MODEL`） | `dd_v1_bridge_service.py`、`dd_v1_agent_adapters.py` |
| ④ | **大写 `file_id` 查表键静默不命中** | `_confirmed_index()` 表内键三种写法归一 | `dd_v1_entity_resolution_service.py` |
| ⑤ | 用例条数写错（26→23、36→35） | 全部改正 | `最终报告.md`、`EVIDENCE.md`、`GOAL-CONTRACT.json`、`CLAUDE.md` |

★ **负向回归**：把新测试拷到**缺陷前字节** `a0324a9` 上跑 ⇒ **8 failed / 27 passed** ⇒ 这 8 条确实打到点上。
★ **M03 判词仍为 `PARTIAL`**（第 6 轮复裁进行中 ⇒ 不预告 PASS）。


### ★ 第 12 轮复核：F30（假凭据方向）／F31／F32（印章值逐字相等）· 已修（2026-10-29）

★ 第 12 轮独立复核（head `69240a539610`）判词 **CONDITIONAL**：F28／F29 **复验闭合**（M5／M15／M8 重打**都必红**）；
★ 复核方跑 **10 个变异探针**，抓住 7 个、**零红 3 个**（N1／N5／N6）⇒ 三条**只需补断言**的缺口。

- **F30（重要·假凭据方向）**：CLI「**从回执重新盖章**」这个锚点的**值**（`rec["adapter"]["participated"]`）**没人管**
  ⇒ 变异 N1（写死 `True`）⇒ 零红 ⇒ 旧格式桥接 JSON（回执明确 `participated: false`）⇒ `mode='HARNESS_MODEL'`。
  ⇒ **已修**：`test_cli_restamp_from_receipt_must_not_claim_participation` —— 回执说没跑出回执 ⇒ **不得**自称参与
  ⇒ ★ 本席自测 **N1 RED** ✔。（根因：既有的旧形状兼容用例**只覆盖 `True` 那一档**。）
- **F31／F32（条件项）**：消费侧「印章值**逐字相等**」**至今没有任何用例钉** ⇒ 变异 N5／N6（放宽成「任何非空 `provenance_source`」）⇒ 零红
  ⇒ 伪造产物可**自称「有本机 Harness 参与」**（这两处守的正是 **F3 纪律**的全部内容）。
  ⇒ **已修**：`test_forged_provenance_source_is_never_trusted` —— 伪造印章值 ⇒ 不采信参与标记／不采信身份／产物**不得谎称**已盖章
  ⇒ ★ 本席自测 **N5／N6 RED** ✔。

★ **PR 评论文案**：复核方逐句列出 **11 处要改**（含一处**事实错误**：「#74 暂停」应为 **2026-10-22**）⇒ **全部采纳**。

### ★★ 同族自查：另两个锚点也补掉（`participation_class_of`／`declared_class_of`）（2026-10-29）

★ 第 11 轮复核点名的族是「**不变体没有测试守护**」⇒ **本席在同一轮里自己又 grep 了一遍**：
`grep -rn "participation_class_of\|declared_class_of" backend/tests/` ⇒ **0 命中** ⇒ **两个锚点都是零守护** ⇒ **一并补掉**：

- `ad.participation_class_of()` ＝ **参与身份在判词层的唯一判定入口**（只看实现类）
  ⇒ 新增 `test_participation_class_of_is_exact_type_matched`：精确类型｜**子类不认**｜**自填 id 不认**｜认不出 ⇒ `UNKNOWN_ADAPTER`
  ⇒ ★ 突变复现：**变异 A（子类也认）RED**｜**变异 B（回退 id 表）RED**（连同另外 3 条既有用例共 4 red）。
- `ad.declared_class_of()` ＝ id 级**旁证**（`declared_provenance`）
  ⇒ 新增 `test_declared_class_of_is_only_a_side_evidence`：钉住「**旁证 ≠ 权威判定**」（同一自填 id：旁证 `HARNESS_MODEL`、权威 `UNKNOWN_ADAPTER`）。

★ 这一族已是本项目最反复的缺口类型（第 6／9／10／11 轮各一次）⇒ **纪律**：凡「只此一处可信」的锚点，
必须有**专属断言**，且该断言必须写在「被区分的两种取值**不同**」的场景里。

### ★ 第 11 轮复核：F28（唯一信任锚点零守护）／F29（假凭据方向）· 已修（2026-10-29）

★ 第 11 轮独立复核（head `94ba4adb6f4e`）判词 **CONDITIONAL**：F27／F26／口径收窄**全部复验闭合**；
★ 复核方跑 **13 个变异探针**，抓住 8 个、**又挑出 3 个零红**（M5／M15／M8）⇒ 两条新的重要项，**都是「不变体没有测试守护」的缺口**。

- **F28（重要）**：`run_semantic` 写的 `rec["model_participation"]` 是 **`--run-dir` 路径唯一**的信任锚点
  ⇒ 它的 `participated_scope`／`provenance_source` 一旦失守 ⇒ 整条路径 fail-closed，**而零用例会发现**。
  ⇒ **已修（只补断言）**：新增 `test_run_semantic_stamp_carries_receipt_scope_contract`
  —— 场景用「**回执口径 True ＋ 选材口径 False**」（`accepted == []`）⇒ **有判别力**；
  并把 `accepted == []` **写成前置断言** ⇒ 场景一改、护栏静默失效**这件事被挡住**。
- **F29（重要·方向是假凭据）**：`ad.participated_flag()`（产出侧原语）**零用例** ⇒ M8 零红
  ⇒ 真实 CLI 上**空回执文件** ⇒ 自称「贴进来的回执」⇒ `PREBAKED_RESULT`。
  ⇒ **已修（只补断言）**：① `test_participated_flag_requires_non_empty_receipt`（空／缺键／None／跑失败 ⇒ 一律不算参与）；
  ② `test_empty_receipt_file_must_not_claim_participation`（**端到端**：空回执文件 ⇒ 答卷**不得**自称参与）。
  ★ 这条条件**承重**：5 个真适配器里 **4 个**能出现「`status=OK` 但 `raw_text` 为空」。

★ 本席**自测**的突变复现（不引述复核方）：**M5 RED**｜**M15 RED**｜**M8 RED** ✔
★ ★ **纪律再推进一步**：第 10 轮立的「**断言要有判别力**」还不够 ⇒ 还要「**守护点覆盖全部信任锚点**」——
★ 凡「**只此一处可信**」的锚点，必须有**专属的产出侧断言**（否则它一改，整条路径静默 fail-closed，而没有用例会发现）。

### ★ 第 10 轮复核：F27（重要·护栏不咬人）／F26（审计标签）· 已修（2026-10-29）

★ 第 10 轮独立复核（head `5feaecd57143…`）判词 **CONDITIONAL**：F24 三小条、F25 闭合，第 6～9 轮的重要项仍闭合、无回归。
★ 复核方做了 **7 个变异探针**：M3（bridge 的 `run_participated` 换成**选材口径**）⇒ **0 red** ⇒ 抓出本席栽的跟头。

- **F27（重要）**：本席第 9 轮新增的产出侧断言 `run_participated == bool(回执.participated)`
  **在自己��场景里不具判别力** —— 场景里模型选材**被接受** ⇒ 两个口径取值**相同**
  ⇒ 把 `run_participated` 换成选材口径也照样全绿，**而真实 CLI 读数会错**（`prebaked` ⇒ `RULE_ONLY`）。
  ⇒ **已修**：场景换成「**跑出了回执、但建议全被确定性闸拒了**」（新增 `_RejectedSuggestionAdapter`：改候选 `locator`
  ⇒ 触发 `CANDIDATE_i_LOCATOR_NOT_IN_EVIDENCE`）⇒ 两个口径取值不同 ⇒ **断言立刻有判别力**
  ⇒ ★ 本席**自己**做了突变测试（M3）确认新断言 **RED** ✔。
  ⇒ ★★ **本轮最重要的一条纪律**：**断言的「判别力」与断言的「存在」是两件事** ——
  一个断言若在它自己的场景里区分不开它要区分的两条路径，它就是**「假守」**（零红）⇒
  **新写护栏断言时，必须先确认「要区分的两个取值在本场景里不同」，并把它写成前置断言**。
- **F26（条件项）**：`participated_scope` 对「有盖章但无口径标记」的源改记 **`UNMARKED`**（不再谎称 `SELECTION_ONLY`）；
  判词本身不变（fail-closed 照旧）⇒ 新增 `test_unmarked_source_is_labelled_unmarked_not_selection`。
- ★ **口径收窄（复核方指出本席措辞过宽）**：**旧桥接 JSON 不误判**（CLI 从回执重新盖章 ⇒ 仍 `HARNESS_MODEL`）；
  **旧 `run_record.json` 会被判 `RULE_ONLY`（安全侧，§9.9 早已如实披露）**。

### ★ 第 9 轮复核：只剩 2 条条件项（F24／F25）· 已修（2026-10-29）

★ 第 9 轮独立复核（head `e304bb6a6253`）判词 **CONDITIONAL**，★ **本轮没有未闭的重要项**、无假凭据、无数据错、无回归失败。
★ 复核方独立实跑：全量 **2017/2016/1/0**、12 文件子集 **230**、负向回归 **17／9／5／3／并集 17** ⇒ **与本席逐位一致**。
★ ★ 复核方**做了变异测试**证明「被更新过的 4 条既有用例**没有**被削弱」：把 F1 缺陷重新塞回 ⇒ 更新后的用例**照样变红**。

- **F24（条件项·测试护栏 ＋ 文档与代码一致）**：
  ① F14 端到端用例**换成新契约形状**（口径标记齐）＋ **另留一条「旧形状」兼容用例**（旧 JSON ⇒ CLI 从回执重新盖章 ⇒ 仍判 `HARNESS_MODEL`）；
  ② **新增产出侧断言**（`test_bridge_emits_participation_scope_contract`：bridge 必须写 `participated_scope`／`run_participated_scope`，且 `run_participated == bool(回执.participated)`）—— 修的是复核方突变测试发现的「**零测试保护**」；
  ③ **删掉**「裸 `run_participated` 键也采信」的兼容逃逸 ⇒ **只认带口径标记的源** ⇒ **文档规则与代码逐字一致**（新增 `test_unmarked_participated_key_is_not_trusted` 守住）。
- **F25（条件项·一句措辞）**：`participated_scope` **外露**为 `examinee.participated_scope`（`RECEIPT`／`SELECTION_ONLY`／`NONE`）＋
  `degrade_reason` **分两种情形**：「**回执口径的参与标记为假**（回执明确说：这次没跑出回执）」／「**拿不到可采信的回执口径参与标记**（可能是：…）」。
  ⇒ 既有 2 条用例按新契约更新，**断言更强**（已知成因 ⇒ 必须直说且不得带猜测清单；未知成因 ⇒ 必须带猜测清单且不得说「没跑出回执」）。

★ **本轮 3 条新/改用例在缺陷前字节 `cf81685` 上真红**（3 red）。

### ★ 第 8 轮复核：新抓到并已修的三条（F21／F22／F23）＋ F17 口径更正（2026-10-29）

★ 第 8 轮独立复核（head `1d3916953d4b`）**复验闭合 F14／F15／F16／F18／F20**，并确认 F1–F4、F19 未回归。
★ **F17** 由本席**在同轮内认领**并已修（负向回归必须写清**作用域 ＋ 测试文件版本**：两文件 50 条 ⇒ 23／15／9／7、累计 23）。
★ **本轮新抓到 3 条**：

- **F21（重要）**：**「选材口径」冒充「回执口径」**。机读产物里有两个 `participated` 味的字段、**含义不同**：
  `model_participation.participated`＝「有义务用了模型选材」（**选材口径**）；
  `agent_receipt.participated` ／ `run_participated`＝「这次真的跑出了回执」（**回执口径**）。
  ★ 旧版在「盖章块缺 `run_participated`」时**退回选材口径** ⇒ 在「回执说跑过、但选材口径是 False」时
  **误判成「没跑出回执」**，还写出**不实的**理由。
  ⇒ **修法**：① 产出侧统一加**口径标记**（`participated_scope` = `RECEIPT`／`SELECTION`、`run_participated_scope` = `RECEIPT`）；
  ② 答卷层**只采信标了 `RECEIPT` 的源**；③ 只有选材口径 ⇒ **fail-closed**（当作没有参与）；
  ④ `degrade_reason` **不再无条件断言**具体成因（不写「这次没跑出回执」这种可能不成立的话），
  改为只陈述**确实知道**的事（拿不到可采信的回执口径参与标记）＋ 成因列为**可能**。
  ⇒ 既有 4 条用例按新契约更新（补口径标记 ＋ 措辞断言）⇒ **口径从隐含约定变成显式契约**。
- **F22（文档·计数陈旧）**：「12 文件子集 226 passed」⇒ 改为 **233 passed / 0 failed / 0 errors**（三处统一；★ 复核方第 10 轮实测 232 ＝ 同一作用域、测试文件版本少 1 条 ⇒ 互相印证），并把**作用域（哪 12 个文件）**写在数字旁。
- **F23（文档·缺口）**：`WINDOWS-HANDOFF.md` 补「**两个 `participated` 字段含义不同**」的口径对照表
  ⇒ 操作员知道该看 `agent_receipt.participated`（回执口径），**别拿 `model_participation.participated` 判断参与**。

★ **F21 的负向回归**在缺陷前字节 `cf81685` 上**真红**（情形 A：回执说跑过、选材口径是 False ⇒ 旧版误判 `RULE_ONLY`）。
★ ★ **口径纪律（再强调一次）**：凡报计数必带「**作用域 ＋ 口径 ＋ 时刻**」——
第 8 轮复核方当面指出「12／6／2」是**单文件作用域**下的数，与复核方的 13／5 并列会被误读成少算。

### ★ 第 7 轮复核（CONDITIONAL）的处置：F14／F15／F16／F17／F18（2026-10-29）

★ 复核方第 7 轮**复验闭合 F1–F4、F19**（自跑子集 885 passed / 1 failed，唯一红＝沙箱 doctor 环境项）
⇒ **仍开的唯一重要项 ＝ F14** ＋ F15／F16／F17／F18 四条。**已逐条修完**：

- **F14（重要）**：`--bridge-json` 路径上「真跑了的模型参与」被记成 `RULE_ONLY`，理由还写着**不实**的「这次没跑出回执」。
  ★ 根因：答卷层**只认带盖章的源**（第 6 轮 F3 的纪律）⇒
  ① `dd_v1_bridge_service` 的 `model_participation` 块**没带** `provenance_source`、
  ② `tools/dd_team_channel.py` 的 `rec["adapter"]` **没带** `participated`
  ⇒ 两处都被循环跳过 ⇒ 落到 `bool(None)` ⇒ **永远 False**。
  ⇒ **修法（两处都补）**：bridge 块补盖章（`provenance_source` ＋ `run_participated` ＋ `declared_provenance`）；CLI 的 `rec["adapter"]` 补 `participated`。
- **F15（文档）**：AB 报告的 `fd9bb21` 在远端**查无此 commit** ⇒ 改为标注「本地历史 sha、未上远端」＋ 写明**可核的是产物文件本身**。
- **F16（重要·可致命）**：`dd_v1_agent_adapters.py` 的 `UNKNOWN_ADAPTER` 定义在推导式**之后** ⇒
  再加一个没有 `participation_class` 属性的适配器类 ⇒ **`NameError at import`** ⇒ 整个 backend 起不来
  ⇒ 常量**上移**到推导式之前（已验证 `import OK`）。
- **F17（文档·口径）**：负向回归红数**必须带「作用域 ＋ 测试文件版本」**：
  ★ **负向回归口径（★ 作用域 ＋ 文件版本，两个都要写清）**：
  ★ **作用域 ＝ `test_dd_v1_model_participation.py`（37）＋ `test_dd_v1_wiring_entity_expansion.py`（13）＝ 当前 50 条**
（测试文件取自 head，拷到各缺陷前字节跑），`--junitxml` 确数：
  ★ `a0324a9` ⇒ **23 red**｜`fe939b6` ⇒ **15 red**｜`2d42995` ⇒ **9 red**｜`cf81685`（第 8 轮被复核的 head）⇒ **7 red**；
  ★ **累计（并集）＝ 23**；包含关系（**机器验过**）：`cf81685` ⊂ `2d42995` ⊂ `fe939b6` ⊂ `a0324a9`。
  ★ ★ **口径纪律**：复核方第 11 轮实测 **20／12／8／6**（**作用域相同、但测试文件版本少 3 条 F28／F29 用例**）
⇒ 差值恰为新增条数 ⇒ **同一把尺子、互相印证**（不是「两把尺子」）。
⇒ ★ **凡报红数必带「作用域（哪几个文件／多少条）＋ 测试文件版本」** —— 同一个字节、换个文件版本，读数就会变。
  ★ ★ **一条「契约变更导致的红」要单独说清**：`test_failed_harness_run_must_not_claim_model_participation`
在 `2d42995`／`cf81685` 上红，**不是**它自己坏了，而是**它断言的措辞随契约变了**
（旧字节写的正是 F21 指出的那句**不实**的话）⇒ 它同时**就是 F21 的证据**。
- **F18（重要）**：答卷层未读盖章块自带的 `declared_provenance` ⇒ 人工贴回执路径记 `UNDECLARED` ⇒ **审计信息丢失**
  ⇒ 改为：自填值**非合法类别**时回落**盖章块**的 `declared_provenance`（只认盖章块；合法值照旧保留）。

★ **负向回归**：F14／F18 两条在缺陷前字节 `2d42995` 上 **2 red**（`mode=RULE_ONLY` ＋ 不实理由／`UNDECLARED`），当前字节全绿。
★ ★ **坑（值得记住）**：F14 的负向回归**第一版是「绿的但测不到东西」** —— 场景里带了模型选材
⇒ bridge 块的「选材口径」`participated=True` **恰好**把缺陷掩盖 ⇒ 连缺陷都复现不出来
⇒ 正解：负向场景必须是「**跑过、但建议全被确定性闸拒了**」（accepted=0 ⇒ 无模型选材）。

### ★ 第 6 轮复核（复裁）新抓到并已修的两处（2026-10-29）

| # | 缺陷 | 修法 | 文件 |
|---|---|---|---|
| ① | **答卷层仍采信适配器自填的 `provenance`** ⇒ 自填即可冒充「模型参与」 | **只认「盖章」**（`provenance_source=ADAPTER_IMPLEMENTATION`）；盖章由**实现侧**产生并随回执落盘；自填那档只记 `declared_provenance`（留痕、不作数） | `dd_v1_exam_service.py`、`dd_v1_semantic_retrieval_service.py`、`dd_v1_bridge_service.py`、`tools/dd_team_channel.py` |
| ② | **查表键归一造成误命中**（人工确认反了） | **两级查表**：精确档只放**原样键**（各归各的）＋ 大小写不敏感档只作兜底 | `dd_v1_entity_resolution_service.py` |
| ③ | 措辞 | 参与类别判定**不是安全边界**（进程内能替换实现）⇒ 挡的是「自填字段冒充」 | `dd_v1_agent_adapters.py` |
| ④ | id 级声明表 | 搬进**实现侧**（`ad.KNOWN_ADAPTER_ID_CLASSES` ＋ `ad.declared_class_of`），bridge 侧改为引用（API 不变） | `dd_v1_agent_adapters.py`、`dd_v1_bridge_service.py` |

★ **负向回归**：3 条新测试跑在修复前字节 `fe939b6` 上 ⇒ **3 red**（确实打到点上）。
★ 第 6 轮复核**新抓到**的两处（同族），也已修：
| # | 缺陷 | 修法 |
|---|---|---|
| ③ | **Harness 没跑出回执却自称 `HARNESS_MODEL`**（假凭据） | 类别与「真的跑出回执」**拆成两件事**：新增 `participated`（`ad.participated_flag()`）⇒ 没跑出回执 ⇒ `examinee.mode` 记 `RULE_ONLY` |
| ④ | **`--run-dir` 路径机读产物里出现 Python dict repr** | 非法类别值的 `declared_provenance` 一律记 `UNDECLARED` |

★ 修复后 12 文件子集 **233 passed / 0 failed / 0 errors**（★ 复核方第 10 轮实测 232 ＝ 同一作用域、测试文件版本少 1 条 ⇒ 互相印证）。


### 改动（工具层 / 测试 / 夹具）

| 文件 | 改了什么 |
|------|---------|
| `tools/dd_team_channel.py` | 新增 4 个开关：`--agent`（`codex`/`pi`/`dsh`/`manual`/`prebaked`）、`--agent-result`、`--confirmed-entity-map`、`--no-expand-candidates`；读数外显到终端、人看报告独立小节、**机读 JSON 顶层** |
| `backend/tests/test_dd_v1_wiring_entity_expansion.py` | **新增 12 条**：多源补位正例（文件名/正文命中）、反例（认不出仍认不出）、**判别力**（关掉接线 ⇒ 正例必须回到认不出）、扩展找到窗口外那份、读数到最外层容器、未看数如实报、可关闭 |
| `backend/tests/test_dd_v1_model_participation.py` | **新增 23 条**：参与身份只认适配器实现、预置回执不算 Harness、R4 排除项硬校验、排除式读数 PASS/WEAK、答卷层 MODEL vs RULE_ONLY、「有模型选材但没回执」必须被标出、端到端 |
| `backend/tests/fixtures/dd-v1-fos71-a5/` | **新增合成夹具**：a4 ＋ 24 份硬负样本（候选池 32 份 > 上限 20）；★ `gold.json`/`raw_items.json`/`replies/` 与 a4 **逐位相同**（只加材料、不动标准答案） |
| `docs/dd-v1-fos71/ddv1-exam-v1/run_sim_exam.py` | 新增三个环境变量：`DDV1_SIM_FIXTURE` / `DDV1_SIM_OUT` / `DDV1_SIM_CAP`（**不改默认行为**）⇒ 修复前/后两侧用**同一份**夹具跑同一脚本 |

## DD-V1 考场 V1 改动文件清单（接手必读，2026-10-28/29）

> 交办单：`cangjie-fos#85`（永久验收红线）＋ `cangjie-teams-channel#108`（正式交办）。
> 分支 `feat/71-ddv1-exam-v1-20261028`，基线 `abc462747e99171415dc405e735773fd9d1335d1`。
> ★ 本版**没有改动任何既有测试断言**；既有 `dd_v1_*` 既有测试全部保持绿。

### 新增（服务层）

| 文件 | 干什么 |
|------|--------|
| `backend/src/cangjie_fos/services/dd_v1_gold_service.py` | 标准答案包（`dd_v1_gold_manifest.v1`）解析、**SHA256 内容寻址**解析、五态（`NOT_PROVIDED`/`NOT_MAPPED`/`NOT_CONFIRMED`/`BROKEN`/`FOUND`）、**隔离闸**（仓内 Gold 一律拒） |
| `backend/src/cangjie_fos/services/dd_v1_exam_service.py` | 机器答卷构建、**Gold 泄漏检测**、评分口径加载与**指纹**、逐题评分、7 项指标 + 0—100 总分、硬规则 HR-0/HR-1、版本对比 |
| `backend/src/cangjie_fos/services/dd_v1_exam_preflight_service.py` | 考场契约（`dd_v1_exam_contract.v1`）、**开考前 Gate**（考卷/图书馆/标准答案/主体范围）、预检报告 |
| `backend/src/cangjie_fos/services/dd_v1_entity_resolution_service.py` | 主体识别**多源分级**（人工确认 > 路径/文件名 > 别名 > 正文 > 元数据 > 认不出），7 档 `MATCHED_BY` 证据 |
| `backend/src/cangjie_fos/services/dd_v1_entity_scope_service.py` | 契约声明的主体范围（`contract_single:` / `contract_group:`）、集团成员展开 |
| `backend/src/cangjie_fos/services/dd_v1_candidate_expansion_service.py` | 候选分批扩展、**停止条件**（「结论稳定 **且** 候选池已穷尽」）、四态停止原因 |
| `backend/config/dd_v1_exam_scoring_spec.v1.json` | **冻结**评分口径：权重 10/30/25/25/10、HR-0 零命中零分、HR-1 零交付零分、HR-2 不可评分、HR-3 泄漏失败、安全闸封顶 59 |

### 新增（测试）

| 文件 | 覆盖 |
|------|------|
| `backend/tests/test_dd_v1_exam_scoring.py` | 20 条：权重/HR-0/HR-1/HR-2/HR-3/泄漏/内容寻址/版本对比/**安全闸「交付 vs 选中」两条** |
| `backend/tests/test_dd_v1_exam_preflight.py` | 13 条：契约校验/四类阻塞/指纹不符/主体范围 |
| `backend/tests/test_dd_v1_doc_type_resolution.py` | 13 条：必须提出 `proposed_doc_type` 且与所选文件类型**自洽**（★ **只验自洽性，不证伪『这是规则脚本』** —— Reviewer 构造的纯规则脚本能过） |
| `backend/tests/test_dd_v1_entity_resolution.py` ＋ `test_dd_v1_candidate_expansion.py` | 29 条：多源分级/三态/停止条件（★ 这两个模块**本版未接线** ⇒ M03 判 PARTIAL） |
| `backend/tests/test_dd_v1_exam_e2e.py` | 9 条：合成考场端到端（组包 → 答卷 → 阅卷 → 对比） |

### 改动（既有文件，**加法式**）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/services/dd_v1_requirement_service.py` | 新增 `CONTRACT_SINGLE_PREFIX`/`CONTRACT_GROUP_PREFIX` 两种 `resolve_entities` 分支、`_group_members`、`checklist_digest`、`CURRENT_DOC_TYPE_KEYS`（权威 10 类，**全仓唯一一份**） |
| `backend/src/cangjie_fos/services/dd_v1_semantic_retrieval_service.py` | 新增**独立分区** `doc_type_resolution`（类型待判定）、`resolve_doc_type` 开关（**默认关**）、类型提案校验（`DOC_TYPE_PROPOSAL_*`）；**主分区的六态口径一字未改** |
| `backend/src/cangjie_fos/services/dd_v1_bridge_service.py` | `build_meta` **补 `sha256` 内容指纹**（取 Manifest 的 `content_hash`，＝完整 64 位，**不重算**）；新增 `doc_type_unresolved` **标记**（分簇口径未动）、`resolve_doc_type` 开关 |
| `backend/src/cangjie_fos/services/dd_v1_agent_result_service.py` | `proposed_doc_type` 改成**可选**字段（`OPTIONAL_RESULT_FIELDS`），不在 `required` 里 |
| `backend/src/cangjie_fos/services/dd_v1_agent_result.v1.schema.json` | `proposed_doc_type` 进 `properties`（限权威 10 类）、**不在 `required`** |
| `tools/dd_team_channel.py` | 新增 5 个子命令：`preflight` / `answer` / `grade` / `compare` / `contract-template`；`run` 加 `--resolve-doc-type` 与 **`--contract`（把契约声明的主体范围落到未指名主体的义务上）**；`answer` 的 `--bridge-json` **支持目录/通配**（PowerShell 不做通配展开）；`main(argv)` 可测 |
| `tools/dd_v1_local_run.py` | 新增 `--resolve-doc-type` |
| `tools/dd_v1_manifest.py` | `main(argv)` 可测（**只改签名，不改行为**） |
| `tools/doctor.py` | 修 npm 裸名崩溃；端口 8000 被**本仓后端**占用时判 OK（不再误杀用户进程） |
| `安装并启动.ps1` / `点击开始-仓颉FOS.bat` | 编码修正（PS1 加 UTF-8 BOM；bat 由 GBK 转 UTF-8） |

### 新增（文档与证据）

| 路径 | 内容 |
|------|------|
| `docs/dd-v1-fos71/ddv1-exam-v1/WINDOWS-HANDOFF.md` | 刘江侧 Windows 交接（**一页操作指南** + 三个实测坑） |
| `docs/dd-v1-fos71/ddv1-exam-v1/GOAL-CONTRACT.json` | 目标契约（`check_gccseg.py --require-v3-8` = PASS） |
| `docs/dd-v1-fos71/ddv1-exam-v1/SKILLS-REVIEW.md` | 技能复用复盘（检索 478｜命中 3｜复用 2｜候选 1） |
| `docs/dd-v1-fos71/ddv1-exam-v1/run_sim_exam.py` | **合成考场**完整模拟考试（零外部调用、零费用） |
| `docs/dd-v1-fos71/ddv1-exam-v1/证据/` | 模拟考场的实跑产物（成绩单/逐题明细/机器答卷/版本对比/预检报告） |
