# CangJie FOS — AI 开发标准

---

## 🟢 接手速览（新 AI / 新人第一眼看这里）

> 最后更新：2026-05-16 | 当前版本：**v0.9.0** | 测试基线：**643+ passed** | 单仓库可运行：✅

### 项目是什么
仓颉 FOS（融资作战操作系统）= 一个帮 VC/FA 管理融资流程的内部工具。
- **后端**：`backend/` — FastAPI + SQLite + LangGraph
- **前端**：`frontend/` — React + TypeScript + Vite
- **分析引擎**：`backend/src/cangjie_fos/engine/` — 路演评分/路演情报（从 AI_Pitch_Coach 迁入）
- **进入点**：`backend/src/cangjie_fos/main.py` — FastAPI app + lifespan
- **外部依赖**：无 — `engine/` 子包已包含所有核心模块，AI_Pitch_Coach 是可选的历史归档

### 最近做了什么（v0.5.3 → v0.7.0）

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

### v0.9.0 改动文件清单（2026-05-16）

| 文件 | 改了什么 |
|------|---------|
| `backend/src/cangjie_fos/services/github_sync.py` | `push_roadshow_report` 中 `datetime.utcnow()` → `datetime.now(timezone.utc)`（修复 deprecation 警告） |
| `backend/tests/test_assets_api.py` | 新增 `test_search_sqlite_chinese_filename` + `test_search_sqlite_chinese_tag`（Bug #10 回归测试） |
| `CHANGELOG.md` | 新增 v0.9.0 版本块 |
| `CLAUDE.md`（本文件） | 版本号 v0.9.0、测试基线 643+、版本历史表新增行、改动文件清单 |

---

### 待处理问题（v0.9.0 之后）

| 类型 | 现象/目标 | 难度 | 建议入手文件 |
|-----|------|------|------------|
| ~~Bug #1~~ | ✅ **已修复**（commit `46c7f79`，2026-05-15）：缺词级时间戳时用句子级兜底+线性插值，`test_transcriber.py` 10个测试覆盖 | — | — |

**尽调响应台现状（v0.8.0 全面升级后）**：
- ✅ 3步向导：扫描材料库 → 上传清单（Excel/Word/PDF/文字）→ AI 匹配 → 表格审核 → 导出
- ✅ 11个 API 端点：索引/session创建/触发匹配/获取items/更新item/导出/Session历史/批量确认 等
- ✅ 清单分块解析（4000字/块）、大材料库预筛（top-50）、Session历史恢复、批量确认、手动文件替换
- ✅ 机构名联动：创建Session时自动推进机构Pipeline阶段到"DD"
- ✅ GitHub自动同步：导出后推送到 `analytics/{tenant}/dd/`
