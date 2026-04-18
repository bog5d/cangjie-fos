# Phase 6.1 / 6.2 实施方案：身份贯通 + 复盘上传全量对齐 AI_Pitch_Coach

**文档性质：** 主程审核用技术方案（**不含业务代码**）。  
**依据源码：** `AI_Pitch_Coach/app.py`（主控制台上传与批量复盘）、`AI_Pitch_Coach/src/job_pipeline.py`（`PitchFileJobParams`、`build_explicit_context`、`run_pitch_file_job`）、`AI_Pitch_Coach/src/llm_judge.py`（`_normalize_explicit_context`）、`AI_Pitch_Coach/src/document_reader.py`（`extract_text_from_files`）。  
**当前 FOS 基线：** `POST /api/pitch/upload`（`tenant_id` + 单文件）、`run_pitch_upload_job` 内固定 `explicit_context` 片段与空 `company_background` / `qa_text`。

**新 AI / 续作入口：** 请先读 **[`AI_HANDOFF_PHASE6.md`](./AI_HANDOFF_PHASE6.md)**，其中说明 **Coach 根 `.env` 与 `backend/.env` 合并**、Pitch 热路径 **`ensure_pitch_coach_runtime()`**、以及前端向导/NPC 相关路径；再回到本文核对与 `app.py` 的字段级 Parity。

---

## 一、Phase 6.1：身份贯通与 NPC 改名（极简落实）

| 项 | 落实方式 |
|----|----------|
| **默认 NPC 名「豆豆」** | 前后端展示名与 System Prompt 中的角色名统一为可配置常量（如 `NPC_DISPLAY_NAME=豆豆`），替换现有「兜底兄弟」字符串族（前端 `NPCPanel`、后端 `npc_chat_graph`、`npc_queue`、`npc` WS 首包等）。 |
| **「当前指挥官」`user_name`** | 前端全局轻量状态（Context 或顶层 `useState` + `localStorage` 可选持久化），**不设账号体系**。 |
| **穿透路径** | （1）NPC：`invoke_npc_chat` / graph state 注入「当前对话指挥官：{user_name}」；（2）上传 job：将 `user_name` 写入 job 元数据与结构化日志（`extra` 字段），便于审计与后续多用户扩展。 |

本阶段与 6.2 **可并行**：6.2 的 job 元数据字段中预留 `submitted_by: user_name` 即可。

---

## 二、Phase 6.2：旧版「复盘上传」逻辑 — 源码事实摘要

### 2.1 用户可见主路径（`app.py` `main()` 经典模式）

1. **侧边栏**：项目档案 `selected_company_id` → 加载 `CompanyProfile`，得到 **`company_background`**（`current_company_bg`）；新建项目时背景可为空。  
2. **主区 — 业务维度**：`category`（业务大类，必选，含 `SCENE_MAP` / `OTHER_SCENE_KEY`）、**投资机构名称**（必填，带 `institution_fuzzy_match` 提示）、**接待投资人姓名**（选填，键 `v103_investor_name` — **注：** 该字段进入 **审查台锁定 / analytics 上下文**（约 L1409），**不进入** `build_explicit_context`；对 **LLM 两阶段评估主 Prompt** 的核心键仍以 `explicit_context` 为准）。  
3. **项目批次**：`batch_label` → 与机构名拼出 **`batch_name` / `project_name`**（`batch_name = 机构名 or 批次备注 or "未命名批次"`）。  
4. **多文件上传**：`uploaded_list`（音频多选）。  
5. **全局（批内共用）**：  
   - **转写热词** `v80_hot_words_raw` → 解析为 `hot_words: list[str] | None`（逗号/中文逗号/分号）。  
   - **敏感词** `sensitive_words_raw` → `parse_sensitive_words` → `sensitive_words`。  
   - **错别字轻修正**：`v71_enable_polish` 仅用于 **「仅提取文字稿」** 子流程 `_v71_transcribe_upload_to_plain`；**批量「开始生成复盘报告」** 调用 `run_pitch_file_job` 时 **未传 `skip_asr_polish`**，默认 **`skip_asr_polish=False`** → **主批量路径在缓存未命中时始终执行 `polish_transcription_text`**（与 checkbox 无绑定 —— 属旧版 UI 与流水线细微差异，迁移时需 **明确产品选择**：FOS 要么 100% 复刻「批量始终 polish」，要么显式暴露「跳过 ASR 润色」与 `PitchFileJobParams.skip_asr_polish` 对齐）。  
6. **HTML 外发相关**（`filename_mask_input`、`mask_html_body`、`html_watermark`）→ `HtmlExportOptions`；FOS 首版可 **阶段 B** 再对齐（当前 FOS 无 V3 审查台 HTML 导出）。  
7. **逐录音块**（`for idx, uf in enumerate(uploaded_list)`）：  
   - **被访谈人** `batch_iv_{idx}`（必填）。  
   - **文件名自动填** `batch_autofill_filename` + `guess_batch_fields_from_stem` / `should_autofill_iv` 防覆盖手动输入。  
   - **狙击表** `data_editor`：列 **「原文引用」「找茬疑点」**（兼容旧列名「人工疑点」）→ `_batch_sniper_targets_json(idx)` 序列化为 **`[{"quote","reason"},...]` 的 JSON 字符串**。  
   - **本条参考 QA 多文件** `batch_qa_*` → `extract_text_from_files(per_files, max_chars=30000)` → `batch_qa_texts[i]`。  
8. **可选：仅提取文字稿** + **说话人映射**（`v71_plain_words`、`v71_iv_speaker_pick_0`、`session_notes` 拼接「身份映射提示：被访谈人「X」= 说话人标签」）— 仅对 **索引 0** 在 UI 中完整展示；批量主循环对 **每条** 读取 `v71_speaker_hint_{i}`（若存在）拼进 `session_notes`。  
9. **生成按钮后**：校验 → 落盘音频到 `workspace / safe_fs(category) / safe_fs(batch_name)` → 对每条调用 `run_pitch_file_job(work_audio, PitchFileJobParams(...), cached_words=...)`。  
10. **ASR 缓存**：内存 `asr_cache[md5]` + 磁盘 `load_asr_cache` / `save_asr_cache`；大文件 `smart_compress_media` 临时网关 MP3 **阅后即焚**。  
11. **机构注册**：`institution_resolve` → `institution_id` / canonical（进 draft ctx，非 `explicit_context` 字面键）。

### 2.2 `build_explicit_context`（`job_pipeline.py` L75–98）输出键（**评估图 / `_normalize_explicit_context` 消费的宇宙**）

| 键 | 来源 |
|----|------|
| `biz_type` | `category`（业务大类） |
| `exact_roles` | `SCENE_MAP[category]` 或「自定义」时 `custom_roles_other` |
| `project_name` | `project_name`（批次展示名） |
| `interviewee` | 本条 `batch_iv_i` |
| `session_notes` | 说话人映射等拼接 |
| `sniper_targets_json` | 狙击表 JSON 字符串 |
| `recording_label` | 本条文件名 |

### 2.3 `PitchFileJobParams` 与 `run_pitch_file_job` 必对齐字段

| 字段 | 含义 |
|------|------|
| `explicit_context` | 上表字典（**须由服务端调用同名 `build_explicit_context`**，禁止前端自创键名） |
| `qa_text` | 本条合并 QA 文本（≤30000 字由 `extract_text_from_files` 保证） |
| `company_background` | 公司档案背景（经 `truncate_company_background`） |
| `sensitive_words` | 脱敏词列表 |
| `hot_words` | ASR 提示词列表 |
| `model_choice` | 默认 `deepseek` |
| `memory_company_id` | 侧边栏选中公司 ID（`__new__` 时为 `""`）→ 影响记忆检索 `tenant_id` 解析链 |
| `use_langgraph_v1` | 与 `USE_LANGGRAPH_V1` 环境/会话一致 |
| `skip_asr_polish` | 默认 `False`（见 2.1 产品取舍说明） |
| `transcription_json_path` / `analysis_json_path` / `html_output_path` | Streamlit 落盘归档；FOS 可映射为 **对象存储或工作区路径策略**（见 §5 降级） |

---

## 三、全字段映射清单（Streamlit → FOS）

### 3.1 分层：哪些必须进「上传抽屉」第一期

| 优先级 | Streamlit 概念 | 目标落点 | 说明 |
|--------|------------------|----------|------|
| **P0** | 业务大类、机构名/批次、自定义双方（其他场景）、逐条被访谈人、逐条狙击表、逐条 QA 多文件、公司背景、敏感词、热词、`memory_company_id` 等价物 | `PitchFileJobParams` 对齐 | 与评估质量直接相关 |
| **P1** | 文件名自动填、说话人映射、`v71` 仅提取文字稿（预览） | React 等价交互 | 提升易用性，可与 P0 分迭代 |
| **P2** | HTML 脱敏 mask、水印、mask_html_body、审查台 stems | FOS 若暂无 V3 工作台则 **文档声明非本期** | 避免范围爆炸 |

### 3.2 `investor_name`（接待投资人）

- **旧版**：写入锁定 ctx / analytics（Partner 画像链路）。  
- **FOS 6.2 建议**：在 job 元数据与可选 **`explicit_context` 扩展** 之间二选一：  
  - **保守（零 Prompt 漂移）**：不写入 `explicit_context`，仅 `job.meta.investor_name` + 日志；或  
  - **经你签字**：在 **不修改** `build_explicit_context` 的前提下，将 `investor_name` 并入 **`session_notes` 前缀**（例如 `【接待投资人】…`），使模型可见且仍通过既有 `session_notes` 通道 —— **须对比旧版 Prompt 是否曾显式消费该字段**（`llm_judge` 内无 `investor` 字面量则并入 `session_notes` 为合理折中）。

---

## 四、前端：Drawer / Modal 与 React State 设计

### 4.1 为什么推荐 **Drawer（宽屏）为主、Modal 为辅**

- 旧版是 **纵向长表单 + 多文件 + 每文件子表单**，桌面端用 **右侧抽屉** 可保留左侧战局地图可见，符合「指挥台」心智。  
- **Modal** 适合：移动端、或「第二步确认提交」摘要（只读回显 + 确认按钮）。

### 4.2 推荐信息架构（单抽屉内分步 **Stepper**）

1. **Step A — 批次与全局**：业务大类、机构名称、批次备注、投资人姓名（元数据）、公司背景（大文本）、敏感词、热词、LangGraph 开关（若 FOS 暴露）。  
2. **Step B — 音频列表**：多文件 `File[]`，支持排序/删除；每条展开子 Accordion：**被访谈人**、狙击表（两列多行，可用简易表格组件 +「增行」）、本条 QA 多文件。  
3. **Step C — 校验与提交**：必填校验（与 `app.py` L3765–3783 同序）、可选 `detect_logical_conflict` 结果展示（需后端预检 API 或提交前轻量接口）。  
4. **（可选）** Step 0：公司选择 —— 与 FOS `tenant_id` / 未来 `company_id` 映射策略一致。

### 4.3 前端 TypeScript 状态形状（建议名：`PitchUploadWizardState`）

```typescript
// 与 job_pipeline.build_explicit_context 入参一一对应（服务端可校验）
type SceneKey = string; // 含「请先选择…」占位与 OTHER_SCENE_KEY

type SniperRow = { quote: string; reason: string };

type TrackMeta = {
  clientTempId: string;       // UI 列表 key，提交时映射顺序
  fileName: string;
  file: File;                  // 或 Step C 再统一读 ArrayBuffer
  interviewee: string;        // batch_iv
  sniperRows: SniperRow[];    // → sniper_targets_json
  qaFiles: File[];             // → extract_text_from_files 服务端
  autofillLocked?: boolean;   // 对应 should_autofill_iv 语义
  speakerHint?: string;       // v71_speaker_hint_i，并入 session_notes
};

type PitchUploadWizardState = {
  tenantId: string;
  userName: string;            // Phase 6.1

  // 对应侧边栏公司
  memoryCompanyId: string;     // 与 Coach mem_cid 对齐；无则 ""

  category: SceneKey;
  institutionName: string;    // → project_name 组成与 batch_name 规则需在服务端与 app 100% 一致
  batchLabel: string;
  investorName: string;        // 元数据，见 §3.2

  customRolesOther: string;    // 仅当 category === OTHER

  companyBackground: string;   // current_company_bg
  sensitiveWordsRaw: string;
  hotWordsRaw: string;
  skipAsrPolish: boolean;      // 显式对齐 PitchFileJobParams（产品确认后）

  useLanggraphV1: boolean;

  tracks: TrackMeta[];
};
```

**狙击表 → JSON：** 前端可直接维护 `SniperRow[]`，提交时 **由服务端** `json.dumps(rows, ensure_ascii=False)`，避免与 Python 布尔/引号差异。

**QA：** 前端只传 `File[]`；**合并与截断 30000 字必须在服务端** 调用 `document_reader.extract_text_from_files`（或抽成共享纯函数包），与旧版字节级行为一致。

---

## 五、后端契约重构（`/api/pitch/upload` 接不住的部分）

### 5.1 问题

- 浏览器 **`multipart/form-data` 对「一个请求里多文件 + 深层嵌套 JSON」** 表达力弱、服务端解析易错。  
- 单文件极简接口无法携带 `tracks[].qaFiles` 与全局字段。

### 5.2 推荐：**两阶段提交（2-Phase Commit）**

| 阶段 | 接口（示例名） | 行为 |
|------|----------------|------|
| **Phase A** | `POST /api/v1/pitch/upload-sessions` | Body：`application/json`，**不含音频二进制**，含 `PitchUploadWizardState` 的 **JSON 可序列化子集**（`tracks` 不含 `File`，仅 `fileName` + `clientTempId` + 已填元数据）。返回 `upload_session_id` + 每条 track 的 **`presigned` 或 `PUT /upload-sessions/{id}/parts/{tempId}`** 占位策略。 |
| **Phase B** | `PUT .../parts/{tempId}` **或** 保留 `multipart` **每文件一单** | 仅传 bytes + `Content-Type`；服务端将文件落临时区并与 session 关联。 |
| **Phase C** | `POST /api/v1/pitch/upload-sessions/{id}/commit` | 校验所有 part 已上传 → 为每条 track 创建 **后台 job**（等价 `run_pitch_file_job`），返回 `job_ids[]`。 |

**备选（单请求）**：`multipart` 根字段 `metadata` = **一整段 JSON 字符串** + 多个 part `audio_0`, `audio_1`, `qa_0_0`… —— 可行但 **调试与网关限制** 更差，仅作备选。

### 5.3 服务端组装 **无损** 映射到 `explicit_context`

1. **唯一合法入口**：`from job_pipeline import build_explicit_context`（确保路径为 Coach 包内同一实现，与现有 `ensure_pitch_coach_import_path` 策略一致）。  
2. **逐条 track `i`**：  
   - `per_iv = tracks[i].interviewee`  
   - `sniper_json = json.dumps([{quote,reason}...], ensure_ascii=False)`  
   - `session_notes` = 若有 `speakerHint` 则拼接与 `app.py` L3956–3958 **同文案模板**  
   - `explicit_context = build_explicit_context(category, project_name, per_iv, session_notes=..., sniper_targets_json=sniper_json, recording_label=fname, custom_roles_other=...)`  
3. **`project_name` / `batch_name`**：必须在服务端 **复刻** `app.py` 中 `batch_name` 与 `project_name` 赋值逻辑（L3506–3507、L3797），禁止前端自行拼字符串作为唯一真相源（可前端预览，**服务端再算一遍**）。  
4. **`qa_text`**：`extract_text_from_files(track_qa_files, max_chars=30000)`。  
5. **`sensitive_words` / `hot_words`**：与 `app.py` L3786–3794 相同解析。  
6. **`PitchFileJobParams`**：字段级赋值与 `app.py` L3979–3995 **同序**；`memory_company_id` 来自 JSON 中的 `memoryCompanyId`。  
7. **`tenant_id`（FOS）** 与 **`memory_company_id`（Coach）** 映射：需在方案附录中固定表（例如 `tenant_id` 即 workspace 公司 slug，或 `resolve_memory_company_id` 反查）— **避免记忆串租户**。

### 5.4 兼容与无损降级

| 场景 | 策略 |
|------|------|
| 缺 QA | `qa_text=""`，与旧版「未上传仍会生成报告」一致。 |
| 狙击表全空 | `sniper_targets_json="[]"`。 |
| `interviewee=="未指定"` | 与旧版一致会触发记忆侧警告；FOS UI 应 **禁止提交** 或显式二次确认。 |
| 无 `memory_company_id` | 与 `app.py` `__new__` 相同传 `""`；非 LangGraph 路径下记忆检索依赖 `explicit_context` 内字段。 |
| FOS 不落盘 `analysis_json_path` | 若首期不写 Coach 式目录树，**仍须**在内存/job 存储中保留 `report` JSON，且 **`explicit_context` 生成不得跳过** —— 落盘路径可指向临时目录或仅内存，但 **传入 `run_pitch_file_job` 的路径参数需非空或可改 job_pipeline 支持 Optional**（**实施前需单列技术 SPIKE**：是否 fork `run_pitch_file_job` 的写盘副作用）。 |

---

## 六、闭环体验：提交后「豆豆」自然反馈（WebSocket + 降级）

### 6.1 目标 UX

抽屉提交成功后：聊天区出现 **「收到关于 {机构/文件名} 的录音，正在分析…」**，而非静默轮询。

### 6.2 方案 A（推荐）：**服务端主动推送**

- 在 **`commit` 处理完成**、首个 job 进入队列后，由后端调用 **`npc_ws_house`**（或等价广播模块）向 `tenant_id` 维度推送一条 **结构化事件**：  
  `{ "type": "upload_job_started", "message": "…", "job_ids": [...], "labels": [...] }`  
- 前端 `NPCPanel` WebSocket `onmessage`：若 `type` 匹配，则 **`pushLine({ role: "豆豆", ... })`**（展示名随 6.1 配置）。  
- **优点**：与「指挥官」无关也能收到；多标签页一致。

### 6.3 方案 B：**HTTP 回包 + 客户端本地 pushLine**

- `commit` 的 JSON 直接带 `assistant_echo: string`；前端 `await commit()` 成功后 **立即** `pushLine`，不依赖 WS。  
- **优点**：实现最快；**缺点**：无 WS 时已覆盖 80% 场景。

### 6.4 与现网「WebSocket 暂不可用」并存

- **双写**：`commit` 响应必带 `assistant_echo`；**同时** `try` 服务端 WS 推送。  
- 前端：优先展示 WS；若无连接则用 HTTP 回显 —— **自然语言一致**，避免两条矛盾系统消息。

### 6.5 与现有 **NPC 主动队列**（`npc_queue`）关系

- **豆豆** 的「收到录音」属于 **任务型系统提示**，建议 **`proactive: false` 或新类型 `task_notice`**，与 `npc_queue` 的「外联/策略」三句 **来源分离**，避免用户误以为是 LLM 生成的闲聊。

---

## 七、验收清单（你审核「无遗漏」用）

- [ ] 业务大类 `category` 与 `OTHER_SCENE_KEY` 自定义角色必填规则一致。  
- [ ] 投资机构名称必填；`batch_name` / `project_name` 与旧版字符串规则一致。  
- [ ] 每条录音被访谈人必填。  
- [ ] 每条狙击表 → `quote`/`reason` JSON 与 `_batch_sniper_targets_json` 一致。  
- [ ] 每条 QA 多文件合并 + **30000** 截断与 `extract_text_from_files` 一致。  
- [ ] `company_background` 注入路径与 `truncate_company_background` 一致。  
- [ ] `sensitive_words` → `mask_words_for_llm` 顺序在脱敏 **之后** 送评（与 `run_pitch_file_job` 一致）。  
- [ ] `hot_words` → `transcribe_audio(..., hot_words=)` 一致。  
- [ ] `explicit_context` **仅通过** `build_explicit_context` 生成，键集合与 `llm_judge._normalize_explicit_context` 兼容。  
- [ ] `memory_company_id` 与记忆检索 / `tenant_id` 映射文档化且无串租。  
- [ ] `USE_LANGGRAPH_V1` / `use_langgraph_v1` 行为与旧版一致。  
- [ ] **ASR 润色**：已明确产品选择（批量始终 polish **或** UI 绑定 `skip_asr_polish`）。  
- [ ] 提交后用户 **10 秒内** 能在聊天区看到「收到…正在分析」（WS 或 HTTP 至少一路）。

---

## 八、非目标（本期方案不展开，避免误解为「不做」）

- Streamlit **V3 审查台**、HTML 导出、**磁盘 ASR 缓存** 与 **归档目录树** 的完整文件布局 —— 可在 **Phase 6.3** 与 FOS 持久化策略合并。  
- **`investor_name` 进入 analytics / GitHub sync** —— 属锁定后链路，6.2 可先元数据落库。  
- **FSS 深检索进评估** —— 见 `FOS_LEGACY_AUDIT_REPORT`，与上传方案 **正交**，另开里程碑。

---

## 九、行动路线（实施顺序建议，仍待你点头后写代码）

1. **SPIKE（≤1 天）**：`run_pitch_file_job` 在「无 Streamlit 落盘路径」下的最小改造点 vs 临时目录适配；确认 `build_explicit_context` 从 FOS 进程 import 的稳定性。  
2. **后端**：`upload-sessions` JSON schema + `commit` + job 执行线程池（与现 `BackgroundTasks` 行为对齐）。  
3. **前端**：Drawer + Stepper + `PitchUploadWizardState`；对接两阶段 API。  
4. **WS + HTTP 双通道** 豆豆首句反馈。  
5. **契约测试**：给定固定输入 JSON，断言生成的 `explicit_context` 与 **同输入下 Coach 单元快照** 深度相等（golden file）。  
6. **Phase 6.1**：豆豆命名 + `user_name` 注入与日志。

---

**文档结束。** 路径：`docs/PHASE6_UPLOAD_PLAN.md`。§九 所列步骤已在主分支 **多轮落地**（向导、commit、job、WS 等）；与 `app.py` 的字段级 Parity 仍以本文为对照表，增量对齐时请看 **`docs/AI_HANDOFF_PHASE6.md`**。
