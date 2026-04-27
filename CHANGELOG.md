# Changelog — 仓颉 FOS

所有重要变更按版本记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased] — 开发中

### 待做
- WebSocket 实时推送替代 Task Rail 轮询
- 路演倒计时计时器（审查台）

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
