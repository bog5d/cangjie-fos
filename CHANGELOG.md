# Changelog — 仓颉 FOS

所有重要变更按版本记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased] — 开发中

### 生产热修复（2026-04-28）

#### Fixed
- **`request_context.py`：413 大文件上传失败** — `RequestContextMiddleware` 对 `multipart/form-data` 请求错误地应用了 JSON 8MB body 上限，导致 172MB+ 音频无法上传。修复：检测 content-type，文件上传跳过 body size 检查。
- **`asr_polish.py` / `memory_engine.py`：`No module named 'llm_judge'`** — Phase 1 engine/ 迁移遗漏函数体内懒导入（`from llm_judge` / `from retry_policy`），测试因 mock 层次较高未发现。修复：改为 `cangjie_fos.engine.*` 完整路径。
- **`安装并启动.ps1`：FFmpeg 首次下载失败** — `imageio_ffmpeg` 首次调用时联网下载二进制，慢网/断网机器无提示失败。修复：启动脚本新增 `[3/4]` 预下载步骤（`imageio_ffmpeg.get_ffmpeg_exe()`），失败时打印警告而非阻断启动。
- **测试基线**：289 passed（不变，修复不影响测试覆盖层）

---

### Phase 7.0 阶段5（2026-04-28 完成）

#### Added
- **`tools/doctor.py`**：跨平台诊断修复脚本，9 项检查（Python/uv/依赖/端口/data目录/FFmpeg/SQLite/env/node_modules），`--fix` 模式自动修复可修复项，Windows UTF-8 输出
- **`GET /api/v1/doctor`**：HTTP 版诊断探针，返回 `python_version/ffmpeg_available/data_dir_writable/db_writable/env_exists/issues/fix_suggestions`，供前端「系统诊断」面板使用
- **`DoctorPanel.tsx`**：前端系统诊断弹窗，调用 `/api/v1/doctor`，展示各项状态（✅/❌）、问题列表及修复建议，导航栏右上角「🔧 系统诊断」入口
- **`诊断_打不开请运行我.bat` 增强**：调用 `doctor.py --fix` 自动诊断修复后再启动 uvicorn，启动失败分情况输出中文错误说明
- **README.md 快速启动更新**：3步启动指引、系统需求表格、遇到问题诊断入口
- **测试覆盖**：新增 `tests/test_doctor_probe.py`（9个测试）和 `tests/test_doctor_script.py`（2个测试）

#### Changed
- **测试基线**：278 → **289 passed**

### Phase 7.0 阶段4（2026-04-28 完成）

#### Added
- **`db_job_list_risk_keywords(tenant_id, limit)`**：查询某租户最近N条已完成路演的风险点列表，用于素材匹配分析
- **`db_assets_search_by_keywords(tenant_id, keywords)`**：基于 material_contributions 表 tags/filename 字段做关键词匹配
- **`db_material_contribution_bulk_upsert(tenant_id, asset_ids, action)`**：批量 upsert 素材贡献度（ON CONFLICT 累加 usage_count）
- **`capture_review_diff` 全链路数据关联**：审查员提交修改后自动触发 → 提取风险关键词 → 匹配素材 → 更新 material_contributions + 写入 material_match_history
- **`_generate_material_suggestions` 真实 TF-IDF 计算**：替换占位实现，基于最近10条路演风险关键词计算素材覆盖率（<30%触发 material_update 建议）+ 识别零贡献高引用素材（institution_insight 建议）
- **`ContributionBoard.tsx` 前端组件**：调用 `GET /api/contributions` 显示贡献度排行榜（名次/贡献者/得分/路演数），嵌入 AssetLibrary 页底部
- **`GET /api/v1/admin/association-log?tenant_id=X&limit=N`**：返回 material_match_history 按机构聚合记录，用于调试确认关联链路真实触发
- **测试覆盖**：新增 `tests/test_phase4_association.py`（12个测试）：DB查询格式/过滤、关键词匹配、bulk_upsert累加、capture_review_diff关联触发、nightly_settle真实计算、API端点200/422

#### Changed
- **测试基线**：266 → **278 passed**

### Phase 7.0 阶段3（2026-04-28 完成）

#### Added
- **`nightly_suggestions` SQLite 表**：夜间进化建议持久化，含 `id/tenant_id/type/content/asset_id/priority/consumed_at`（`db_nightly_suggestion_insert / list_pending / mark_consumed`）
- **`nightly_settle.py` 夜间结算服务**：`nightly_settle_all_tenants()` / `nightly_settle_for_tenant(tenant_id)`，3步流水线：偏好提取 → 素材建议生成 → 写入 nightly_suggestions
- **APScheduler 3.11.2 接入 FastAPI lifespan**：每晚2:00自动触发 `nightly_settle_all_tenants`，lifespan 启动/关闭生命周期管理
- **`POST /api/v1/admin/nightly-settle?tenant_id=X`**：调试用手动触发端点，返回 `{tenant_id, suggested}`
- **豆豆 NPC 夜间建议注入**：`_inject_system_health` 节点追加读取未消费 `nightly_suggestions`（priority≤5，最多3条），注入后标记已消费
- **测试覆盖**：新增 `tests/test_nightly_settle.py`（8个测试）：表创建、CRUD、优先级过滤、limit、mock调用链、端点200/422

#### Changed
- **测试基线**：258 → **266 passed**

### Phase 7.0 阶段2（2026-04-28 完成）

#### Added
- **`executive_memories` SQLite 表**：高管错题本迁移，含 UUID 幂等插入、按公司/标签查询、删除（`db_exec_memory_insert / list / delete`）
- **`material_contributions` SQLite 表**：素材贡献度，ON CONFLICT 累加 `usage_count / contribution_score`（`db_material_contribution_upsert / list`）
- **`contribution_scores` SQLite 表**：贡献者汇总，ON CONFLICT 累加（`db_contribution_score_upsert / list`）
- **`material_match_history` SQLite 表**：素材-机构匹配历史（`db_material_match_insert / list`）
- **`GET /api/materials/health`**：素材健康度列表（usage_count / contribution_score / tags）
- **`POST /api/materials/match`**：为机构生成素材清单并记录匹配历史（tag/keyword 评分）
- **`GET /api/contributions`**：贡献度排行（score DESC），支持 `?limit=N`
- **分页参数**：`GET /api/pitch/jobs` 支持 `?page=1&size=20`（page>1 时走 SQLite OFFSET）
- **structlog 25.5.0**：新增结构化日志依赖，应用于 `materials` 路由

#### Changed
- **前端懒加载**：`WarRoomMap` 和 `AssetLibrary` 改为 `React.lazy()` 按需加载，bundle 拆分为独立 chunk

### 战略规划更新（2026-04-27）
- 战略计划文件已纳入 Kimi 外部评审建议：SQLite WAL 模式、LLM 多模型 fallback、文件 MIME 校验、前端懒加载、structlog、分页 API（见 `plans/adaptive-finding-valiant.md`）
- 明确拒绝：Git Submodule、aiosqlite、Celery、Prometheus、K8s、PostgreSQL 迁移

### 待做（近期）
- **阶段3**：APScheduler 夜间自动进化任务
- WebSocket 实时推送替代 Task Rail 轮询
- 路演倒计时计时器（审查台）

## [0.3.0] — 2026-04-28  Phase 7.0 阶段1 FSS 代码完全合并

### Changed
- **FSS 全部核心模块迁入 `engine/` 子包**（共 23 个模块）：
  - 第一批：`transcriber`、`memory_engine`、`asset_bridge`、`schema`、`retry_policy`、`language_detector`、`investor_matcher`、`growth_engine`
  - coach 流水线：`agent_nodes`、`agent_workflow`、`agent_runner`、`agent_state`、`agent_sanitize`、`agent_tenant`、`llm_judge`
  - 第二批（2026-04-28补完）：`asr_polish`、`audio_preprocess`、`document_reader`、`job_pipeline`、`report_builder`、`runtime_paths`、`sensitive_words`
- **全面消灭 `ensure_pitch_coach_runtime()` / `ensure_pitch_coach_import_path()` 调用**：`pitch_upload_pipeline`、`pitch_graph_service`、`audio_service`、`html_report_service`、`pitch_wizard_runner`、`tenant_context`、`api/routes/pitch.py`、`api/routes/pitch_wizard.py` 全部改为 `from cangjie_fos.engine.*` 直接导入
- **engine/ 内部 import 修正**：`asr_polish`、`report_builder`、`job_pipeline` 内部引用改为 `cangjie_fos.engine.*`
- **删除 `adapters/coach_memory_bridge.py`**：逻辑内联，使用 `engine.memory_engine` + `engine.coach.agent_tenant`
- **删除 `adapters/institution_coach_sync.py`**：依赖清除
- **测试全面更新**：`test_p0_retry_eval`、`test_p0_pipeline_persistence`、`test_p1b_html_report_service`（完全重写为 engine.* patch）、`test_pipeline_e2e`、`test_wizard_pipeline_e2e` 均更新 mock 路径

### 结果
- `ensure_pitch_coach_runtime()` 在 FOS 业务代码中**调用次数 = 0**（函数定义保留在 `core/paths.py` 以防万一）
- 测试基线：**239 passed**，无需 `CANGJIE_PITCH_COACH_ROOT` 环境变量（mock 已内化）
- FSS 仓库（`D:\AI_Workspaces\AI_Pitch_Coach`）可正式归档

---

## [0.2.1] — 2026-04-27  Phase 7.0 R3 LLM 重试 + 重跑评估

### Added
- **`pitch_graph_service.py` 指数退避重试**：LLM 调用遇到 `ConnectionError` / `TimeoutError` 自动重试3次（4次总计），间隔 2/4/8s；其他异常立即抛出不重试
- **`POST /api/pitch/jobs/{id}/retry-eval`**：读取 SQLite 中的 `words_json` 重跑 LangGraph 评估，无需重新上传音频；返回 404/409/422 校验 + 200 成功
- **`PitchJobSummary.has_words_json`**：新增布尔字段，`GET /api/pitch/jobs` 返回每条任务是否可重跑
- **TaskRail「重跑评估」按钮**：failed 卡片在 `has_words_json=true` 时显示按钮，点击调用 retry-eval 端点并刷新轨道
- **测试覆盖**：新增 `tests/test_p0_retry_eval.py`（11 个测试），228 → 239 passed

---

## [0.2.0] — 2026-04-26  Phase 6.4 第二轮补丁

### Added
- **Task Rail substatus**：流水线 8 节点细粒度进度文字（压缩→上传→ASR→转写→分析→诊断→报告→完成）
- **Task Rail 秒表**：active 任务实时显示"已等待 Xm Xs"
- **豆豆系统诊断**：`inject_system_health` 图节点，将 readiness + 最近失败任务注入 NPC 上下文
- **SQLite 重启兜底**：服务重启后 Task Rail 不再空白，自动从 SQLite 读历史任务
- `db_job_list_recent_errors()` 工具函数
- `substatus` 字段（SQLite DDL + schema + API 透传 + 前端展示）

### Changed
- **ASR 错误信息精确化**：`FILE_DOWNLOAD_FAILED` 等 8 种阿里云错误码不再显示通用兜底文案，改为具体原因和操作建议
- **审查台卡片**：移除"原文实录"显示区块（字段数据保留，后处理仍使用）；AddRiskPointForm 同步移除该输入框
- **NPCPanel 滚动修复**：外层 `max-h-[min(900px,90vh)]` + 消息区 `flex-1 overflow-y-auto`，真正实现内部滚动

### Fixed
- 服务重启后 `/api/pitch/jobs` 返回 500（SQLite fallback 路径 `warnings` JSON 字符串未反序列化）

---

## [0.1.0] — 2026-04-22  Phase 6.4 基础版本（初始 GitHub 发布）

### 系统全貌
- **FastAPI 后端** + **React 18 前端**，SQLite 持久化
- **LangGraph 多 Agent 评估引擎**：路演录音 → ASR 转写 → 风险分析 → 结构化报告
- **全屏审查台**（ReviewWorkbench）：风险点卡片、音频片段播放、HTML 报告生成
- **Task Rail**：上传任务进度追踪（pending/transcribing/evaluating/completed/failed）
- **豆豆 NPC 顾问**：LangGraph 对话图，融资知识 + 任务状态感知
- **机构漏斗（War Room Map）**：Teaser→DD→签约 全流程追踪
- **资料库（AssetLibrary）**：FSS 资产管理与上下文注入
- **进化飞轮骨架**：EvolutionCapture / Extractor / Injector 骨架已落地
- **就绪检查（Readiness）**：`preflight.py` + `readiness.py` + `诊断_打不开请运行我.bat`
- **Docker 支持**：`Dockerfile` + `docker-compose.yml`
- **228 个自动化测试**，覆盖 Pipeline E2E、API 路由、DB 持久化、NPC 上下文

### 外部依赖说明
- 本仓库（FOS）依赖 **AI Pitch Coach（FSS）** 作为 LLM/ASR 评估后端
- FSS 未公开发布；本地部署需将 FSS 路径配置至 `PITCH_COACH_ROOT` 环境变量
- 不依赖 FSS 的功能（机构漏斗、资料库、豆豆对话）可独立运行
- 测试套件通过 mock 隔离 FSS 依赖，可在无 FSS 环境下全部通过

---

## 版本号规则

`major.minor.patch`  
- major：架构级重构  
- minor：新功能 Phase  
- patch：Bug 修复 / 小改动
