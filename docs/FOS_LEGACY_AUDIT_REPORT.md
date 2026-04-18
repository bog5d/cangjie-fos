# FOS 新旧系统功能差异与重构审计报告

**审计范围：** `AI_Pitch_Coach/src`（及关键测试）、`AI_CangJie_FSS/src`（资产桥与控制台链路）、`CangJie_FOS/backend/src/cangjie_fos`（及前端契约）。  
**审计性质：** 静态代码结构与调用链对比；**未修改业务代码**。  
**结论先验：** 新系统并非「空壳」——路演评估主链路仍通过 **进程内 import** 调用 Pitch_Coach 的 `agent_runner` / 完整 LangGraph；但大量 **业务灵魂** 仍留在旧仓库节点内，FOS 侧以 **薄封装、并行数据模型、简化启发式** 承接，存在 **可量化的能力落差**。「100% 毫无损耗」在工程上等同于 **将 Pitch_Coach/FSS 整体升格为一等依赖并统一运行时契约**，需分阶段验收，而非一次 PR。

---

## 1. 深度对比扫描（架构与调用链）

### 1.1 Pitch_Coach：路演评估主图（真实业务核心）

旧系统 `agent_runner.run_pitch_evaluation_via_langgraph_with_state` 驱动的图为（`agent_workflow.py`）：

`ingest → retrieve_memory → sanitize_inputs → prepare_eval → phase1_scan → phase2_report → finalize → memory_event_producer → feedback_telemetry → END`

节点职责（`agent_nodes.py` + `llm_judge.py` + `memory_engine.py` + `asset_bridge.py`）包括但不限于：

| 环节 | 旧系统实现要点 |
|------|----------------|
| 记忆检索 | `resolve_memory_company_id`、`load_top_executive_memories_for_prompt`、按 `explicit_context.interviewee` **tag** 拉取、`record_executive_memory_prompt_hits` |
| 资产 | `load_asset_index`、`find_related_assets` 做 **QA 关键词命中**；`_build_asset_summary_markdown` 结构化摘要 |
| 安全 | `sanitize_llm_input_text` / `sanitize_text_meta` |
| 评估 | `run_phase1_risk_scan`、`run_phase2_deep_eval_and_assemble_report`、`prepare_pitch_evaluation_context` |
| 闭环 | `node_memory_event_producer`、`node_feedback_telemetry` 与 **memory_engine 落盘规则** 联动 |

**新系统对应关系：**

- `PitchGraphService.run_evaluation_with_state` **直接调用**上述入口，并在返回后追加 FOS 的 `extract_and_persist_institution_intel`（机构 SQLite）。  
- **未复制**图中各节点逻辑到 FOS；**未改写** Phase1/Phase2 内部 Prompt 与拼装规则——它们仍在 Pitch_Coach 内。

**结论：** 路演「打分与报告」的 **灵魂仍在旧图**；FOS 是 **外壳 + 编排 + 增量特性**（上传任务、Dashboard、NPC 平行图、机构 CRM、Watchdog 等）。

### 1.2 FOS 侧 NPC 与错题本 / 进化

- NPC：`npc_chat_graph` 为 **独立** LangGraph（preload → inject → agent），System Prompt 与 Pitch 评估图 **不是同一套**。  
- 租户上下文：`tenant_context.build_executive_memory_digest` 调用 `memory_engine.list_all_executive_memories_for_company`，属于 **摘要式读取**，**不等价**于评估图里的 `retrieve_memory`（无 interviewee tag 路径、无 prompt hit 记录、无与 phase 绑定的检索策略）。  
- 进化：`EvolutionJsonStore` + `evolution_guidelines.jsonl` + `ReflectionService` 为 **FOS 平行闭环**；与旧图 `memory_event_producer` 写入 **Executive Memory** 的规则 **未在代码层统一为单一事件总线**。

### 1.3 FOS 侧资产与 FSS

- FOS：`fss_asset_scan.load_asset_index_assets` 对齐 FSS `load_asset_index_local` 的 **「读 JSON 列表」** 语义。  
- Pitch_Coach 评估路径：`asset_bridge.find_related_assets` +  richer 命中逻辑（与转写/QA 关联）。  
- FSS 另有：`document_intake`、`document_archiver`、`matchmaker_v5`、`core_agent_engine/agentic-file-search`（索引/向量/探索轨迹）等——**FOS 未接入**这些进程级能力，仅 **桥接索引文件** 与 **资料室目录扫描**。

### 1.4 机构与 Pipeline

- Pitch_Coach：`institution_registry.py`（别名、核心名归一、difflib 阈值、滚动备份）、`institution_profiler` / `partner_profiler` / `briefing_engine` 等 **深度业务模块**。  
- FOS Phase6：`institutions.sqlite` + 启发式/可选 LLM 抽取 + Dashboard 漏斗聚合——**数据模型与归并规则与旧 registry 不对齐**，**未迁移** profiler/briefing 的规则引擎。

### 1.5 仍为 Mock / 脚本 / 非持久化的 FOS 部件

| 部件 | 说明 |
|------|------|
| `GET /api/war-room/funnel` | **已对齐**：与 `GET /api/dashboard/status` 同源，均经 `build_funnel_from_institutions`（SQLite Pipeline 聚合）；`war_room_mock` 仅保留供极少数单测引用。 |
| `npc_queue` | 硬编码几句「兜底兄弟」文案，与真实业务事件无关。 |
| `pitch_job_store` | 内存 dict，**非** Pitch_Coach `job_pipeline` 级持久化/恢复语义。 |
| `POST /api/v1/webhooks/ingest` | 仅 ack，无与旧系统 Webhook/IM 业务对齐。 |

---

## 2. 技术债与遗漏项（诚实清单）

### 2.1 旧系统核心能力在新系统中 **缺失或显著弱化**

1. **评估图内的完整记忆策略**（interviewee tag、prompt hit、retrieve 元数据）在 FOS HTTP/NPC 路径 **部分缝合**：`POST /api/v1/feedback/text-diff` 经 `coach_memory_bridge` 调用 Coach `capture_and_distill_diff`；NPC 主路径注入 **`load_top_executive_memories_for_prompt` Top-N**（tag 首版恒 `default`）。与图内元数据 **完全对齐** 仍为后续项。  
2. **资产 QA 命中与摘要生成**（`find_related_assets` 与节点内 markdown 拼装）在 FOS 侧 **未迁移**；仅有索引列表 + 资料室文件数。  
3. **输入消毒与元数据**（`agent_sanitize`）在 FOS 独立对话链路 **未强制复用**。  
4. **ASR 后处理链**：Pitch_Coach 存在 `asr_polish`、`disk_asr_cache`、`audio_filename_hints` 等；FOS `pitch_upload_pipeline` 为 **压缩 → transcribe_audio → 评估**，**未挂载** polish/缓存策略（除非 transcriber 内部隐含）。  
5. **报告后链路**：`report_builder`、`annotations`、`client_dashboard`、`analytics_exporter` 等 **无 FOS 一等 API/UI**。  
6. **演练与情报子系统**：`practice_engine`、`briefing_engine`、`investor_matcher`、`outcome_predictor`、`pipeline_tracker` 等 **未进入 FOS**。  
7. **FSS 文档治理与智能检索**：`document_intake` / archiver / matchmaker / fs_explorer **未进入 FOS**；战局沙盘无法复用其「真实资料运营」逻辑。  
8. **机构注册表高级归一**：旧 `institution_registry` 与 FOS `institution_store` **并存且语义不一致**，长期会 **双写/漂移**。  
9. **Streamlit 工作台能力**（`workbench_hub`、`pages/*`）在 FOS 无对等物——若业务依赖 **人工审核与标注闭环**，当前为缺口。

### 2.2 当前为「薄封装 / 假数据 / 旁路」的接口或模块

| 位置 | 现状 |
|------|------|
| `PitchGraphService` | 薄封装 + 后置机构抽取；**未**将 Coach 状态 excerpt 全量暴露为 FOS 领域模型。 |
| `tenant_context` | 资产：**读索引 JSON**；**未**调用 `find_related_assets`。 |
| `war_room` 路由 | **已与 Dashboard 漏斗同源**（`build_funnel_from_institutions`）。 |
| `npc_queue` / WS 首包推送 | **脚本 Mock**。 |
| `webhooks/ingest` | **占位**。 |
| `pitch_job_store` | **内存**任务表。 |
| FOS `institution_intel_extract` | 与 Coach **机构注册/画像** 规则 **不统一**，属 **平行实现**。 |

### 2.3 旧 Prompt 模板与复杂业务规则 **仍留在旧仓库**

- **Phase1 / Phase2** 的具体 system/user 模板、风险扫描约束、报告字段拼装：**在 `llm_judge.py` 及关联模块**，FOS **未内联副本**。  
- **记忆写入规则**（防噪门、距离阈值、tag 文件布局）：**在 `memory_engine.py`**；FOS 纠错路径 **通过 bridge 调用**，不在 FOS 复制阈值。  
- **租户到 company_id 映射**：**在 `agent_tenant.py`**；bridge / NPC episodic 片段经 `resolve_memory_company_id` **与评估图对齐**。  
- **机构别名与归一**：**在 `institution_registry.py`**；FOS SQLite 为 **主写**，可选 **`CANGJIE_SYNC_INSTITUTION_TO_COACH`** 单向投影至 Coach registry，降低旧工具链断裂风险。

---

## 3. 重构与缝合建议（主程 TODO，待你确认后开工）

以下按 **风险收益** 排序；每一项都应配 **验收用例**（可复用 Coach 现有 tests 子集或契约测试）。

### P0 — 消除「双真相源」与假漏斗

1. ~~**废弃或转发** `GET /api/war-room/funnel`~~ **已完成**：该路由与 Dashboard 共用 `build_funnel_from_institutions`。  
2. **机构数据**：选型 **单一主存**——要么 FOS SQLite 为权威并写 **同步适配器** 读/写 Coach `institution_registry` 格式，要么 **反向** 以 Coach registry 为权威、FOS 只读 API。  
3. **任务系统**：`pitch_job_store` 替换为 SQLite/Redis 或与 Coach `job_pipeline` 对齐的最小持久化，保证 **刷新/多进程** 一致。

### P1 — 把「评估图」的状态与记忆正式纳入 FOS 领域

4. **暴露 `state_excerpt`**：`/api/pitch/run` 与上传完成回调中返回 **asset_hits、memory_retrieve_meta、memory_events** 等，前端可选展示（对齐 Coach 可观测性）。  
5. **统一记忆入口**：FOS `text-diff`/纠错 与 Coach `memory_event_producer` 写入路径 **对齐**（或建立 **Outbox 表** 双向同步），避免「错题本在 Coach、进化在 FOS」长期分裂。  
6. **NPC 注入**：在 `build_tenant_context_block` 或单独服务中复用 **`load_top_executive_memories_for_prompt(company_id, tag, limit)`**（需从用户消息或会话槽位解析 `interviewee`/tag），而不是仅 `list_all_*`。

### P2 — 资产与 FSS 深度缝合

7. **封装 `find_related_assets`**：在 FOS 增加 `AssetContextService`，对转写文本调用 Coach `asset_bridge`（或抽 **纯函数** 迁入 `cangjie_fos` 包），替换仅列文件名。  
8. **可选管道**：异步触发 FSS `document_intake` / 索引更新（队列 + 状态回写），而不是仅写 `incoming` 目录。

### P3 — ASR 与报告后链路

9. **上传管道对齐**：在 `transcribe_audio` 后插入 **`asr_polish`（可配置开关）** 与 **磁盘缓存** 策略，与 Coach 测试矩阵对齐。  
10. **报告产物 API**：最小集 `/api/v1/reports/{trace_id}` 返回 HTML/PDF 元数据，底层调用 `report_builder`（或只读文件产物路径）。

### P4 — 演练、客户看板、分析

11. **按需端口**：`practice_engine`、`client_dashboard`、`analytics_exporter` 以 **BFF 路由** 形式渐进暴露，每个子域 **单独里程碑**。

### P5 — 工程化与「零损耗」定义

12. **子模块/Monorepo**：将 Pitch_Coach 核心以 **git submodule / 内部包** 固定版本，FOS 禁止 **隐式** 跨仓库字符串补丁；CI 跑 **双仓联合测试**。  
13. **契约测试**：对 `run_pitch_evaluation_via_langgraph_with_state` 的 **输入输出 schema** 做 golden test，Coach 升级时 FOS 第一时间感知破坏。

---

## 4. 审计说明（边界）

- 未运行全量旧仓测试；结论基于 **源码树与调用关系**。  
- 「100% 毫无损耗」若定义为 **字节级复制旧代码**，不现实；若定义为 **行为等价 + 数据不丢 + 可观测一致**，上表 **P0–P2** 为必经最小集。  
- 你确认本报告中的 **P0/P1 优先级** 后，再开工可减少返工。

---

**文档版本：** 1.0  
**生成日期：** 以仓库当前开发进度为基准（请与 `docs/PHASE6_SPEC.md` 等并列存档）。
