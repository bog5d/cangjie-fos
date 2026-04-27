# Changelog — 仓颉 FOS

所有重要变更按版本记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased] — 开发中

### 战略规划更新（2026-04-27）
- 战略计划文件已纳入 Kimi 外部评审建议：SQLite WAL 模式、LLM 多模型 fallback、文件 MIME 校验、前端懒加载、structlog、分页 API（见 `plans/adaptive-finding-valiant.md`）
- 明确拒绝：Git Submodule、aiosqlite、Celery、Prometheus、K8s、PostgreSQL 迁移

### 待做（近期）
- **阶段1（进行中）**：FSS 核心代码迁入 `engine/` 子包，消灭 sys.path 注入
- **阶段1附加**：文件上传 MIME 校验 + LLM 多模型 fallback
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
