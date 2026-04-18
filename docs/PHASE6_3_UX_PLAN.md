# Phase 6.3：UX 微交互与状态透明度 — 设计图纸（仅方案，不含实现代码）

**状态：** 核心条目已编码落地；本文保留 **产品/UX 意图与 Parity 清单**，细节以仓库代码与 **`docs/AI_HANDOFF_PHASE6.md`**（新 AI 单页交接）为准。  
**基线：** 当前 FOS 前端 `App.tsx` → `PitchUploadWizard`（抽屉 + Stepper）、`NPCPanel`（聊天 + 简易上传 + WS）、后端 `GET /api/pitch/jobs/{job_id}`、两阶段向导 `commit` 返回 `job_ids` + WS `upload_job_started`。

**修订说明（第二批）：** 在「文件名魔法 / Task Rail / Avatar」之上，补充 **报告闭环、音频试听、静默失败防御、任务取消、以及 app.py 级 Parity Audit**，避免只做「被动回答三点」而遗漏 **操作安全感** 与 **业务闭环**。

**新 AI 请先读：** [`AI_HANDOFF_PHASE6.md`](./AI_HANDOFF_PHASE6.md) — 含 `has_report` 竞态修复、错误 `summary/detail`、`ensure_pitch_coach_runtime`、测试文件路径与「待优化」分 PR 建议。

---

## 0. 现状与差距（与旧版 Streamlit 对照）

| 维度 | AI_Pitch_Coach（`app.py`） | 当前 FOS |
|------|---------------------------|----------|
| 文件名魔法 | `stem_from_audio_filename` + `guess_batch_fields_from_stem` + `should_autofill_iv` + `batch_autofill_filename` 勾选 | 无：用户需手填被访谈人 |
| 任务可见性 | `st.status` / `progress_bar` / 文案流式更新 | 仅静态气泡文案 +「轮询」文字，无控件 |
| NPC 陪伴感 | Streamlit 无头像但信息密度高；FOS 有赛博皮但 **豆豆无视觉锚点** | 文字角色名 + 边框色 |
| **报告闭环** | 初稿 JSON + **审查台**编辑 + **锁定**生成 HTML + 路径提示 + 可选 `st.audio` 切片试听 | Job `completed` 后 **`report` 在 API JSON 内**，UI **未提供消费入口**（黑盒感主因之一） |
| **上传后试听** | 审查台内对裁剪音频 `st.audio`；批量页依赖 **文件名 + 仅提取文字稿** 交叉验证 | 抽屉内 **无 `<audio>` 预览** |
| **QA 截断感知** | `on_notice` 写入 `v7_qa_truncation_warn`，批次结束 `st.warning` | 服务端静默截断，`commit` **未回传**截断告警 |
| **敏感词/冲突** | 「识别保密词汇」按钮 + `detect_logical_conflict` 与背景冲突 Expander | 仅原始文本框，无 **预览/预检** |
| **环境门禁** | `env_all_ok` 未绿则 **禁用**「开始生成」 | FOS 向导 **未复刻**「密钥未就绪不可提交」的硬门禁（可降级为提交时 503 友好提示） |

---

## 一、找回文件名自动解析的「魔法」

### 1.1 旧版逻辑摘要（源码锚点）

- **`audio_filename_hints.stem_from_audio_filename`**：`Path(filename).stem`。  
- **`guess_batch_fields_from_stem(stem)`**：无 `-` → 整段作被访谈人；有 `-` → 首段为机构段、剩余段；剩余段尾 **8 位数字** 用 `_DATE_TAIL` 剥离为日期，返回 `(name, notes)`，其中 `notes` 会进入狙击表首行「找茬疑点」的初始种子（与 `app.py` 中 `init_key` DataFrame 一致）。  
- **`should_autofill_iv(current_iv, last_autofilled)`**：空字段可填；用户手填且与上次自动值不同则 **保护不覆盖**；当前值等于上次自动值则 **允许随文件名更新而刷新猜测**（BUG-C）。

### 1.2 目标体验（React 抽屉内）

1. 每条轨道在 **选择音频文件后**（`onChange`），若用户开启「根据文件名自动填被访谈人/首行疑点」（默认 **开**，与旧版 `batch_autofill_filename` 对齐），则：  
   - 计算 `stem`；  
   - 得到 `(ivGuess, noteGuess)`；  
   - 若 `shouldAutofill` 为真：写入 `interviewee`，并将 `sniper[0].reason`（或首行「找茬疑点」）预填 `noteGuess`（与旧版「首行疑点」一致）。  
2. 用户 **手动改过** 被访谈人后，除非其内容再次等于「上次自动值」，否则不再覆盖（前端维护 `lastAutofilledByTrack: Record<clientTempId, string | null>`）。

### 1.3 实现路径选型

| 方案 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| **A. TypeScript 纯函数** | 新建 `frontend/src/lib/audioFilenameHints.ts`，规则与 `audio_filename_hints.py` **逐行对齐**；Vitest 用 **与 Coach `tests/test_audio_filename_hints.py` 相同用例** 做 golden | 零网络延迟、离线可用、抽屉内即时反馈 | 若未来 Python 规则变更需双端同步 |
| **B. Pre-flight API** | `POST /api/v1/pitch/filename-hint { filename }` 调 Coach 同模块 | 单一真相源、永无漂移 | 每次选文件 RTT、实现与部署耦合、弱网抖动 |
| **C. 混合** | 默认 **A**；可选环境变量开启 **B** 做 CI 对拍 | 兼顾体验与审计 | 成本略高 |

**推荐（主程默认）：方案 A + 契约测试对拍**  
- **优雅性**：解析规则是 **纯字符串/正则**，无 I/O，**最适合 TS 本地化**；旧仓库已有 **稳定单测向量**，迁到 Vitest 即可证明与 Python **行为等价**。  
- **若你极度担心漂移**：在 Phase 6.3 末尾加 **一条** CI 用例：Node 跑 TS、`pytest` 跑 Python，对同一 `fixtures/filename_stems.json` 断言输出一致（仍不必在运行时打 API）。

### 1.4 组件与数据流（抽屉内）

```
User picks File on track[i]
    → stem = stemFromAudioFilename(file.name)
    → { iv, note } = guessBatchFieldsFromStem(stem)
    → if (autofillEnabled && shouldAutofillIv(track.interviewee, lastAutofilled[i]))
          setTrack interviewee = iv
          setTrack sniper[0].reason = note (若首行 reason 空或与上次自动 note 相同则写)
    → lastAutofilled[i] = iv
```

**UI**：在 Step「逐条录音」每条卡片顶部增加 **Toggle「根据文件名自动填写」**（与旧版一致）；旁加 **灰色小字预览**：「解析自：`xxx.m4a` → 被访谈人 ~ …」增强魔法可见性。

---

## 二、打破黑盒 — 任务进度可视化

### 2.1 后端能力现状

- **已有**：`GET /api/pitch/jobs/{job_id}` → `PitchJobStatusResponse`（`status`：`pending` / `transcribing` / `evaluating` / `completed` / `failed`，含 `report` / `error`）。  
- **未有**：**按租户列举** job、**WebSocket 推送 job 状态变更**（当前仅有 `upload_job_started` 一次广播）。

### 2.2 目标：用户始终能回答三个问题

1. **有哪些任务在跑？**  
2. **每条卡在转写还是评估？**  
3. **完成后是否成功？失败原因？**

### 2.3 API 与数据模型（建议增量，不破坏现有契约）

| 新增/扩展 | 说明 |
|-----------|------|
| **`GET /api/pitch/jobs`**（Query：`tenant_id`，可选 `limit`） | 从内存 job 表筛选 `tenant_id` 匹配项，按创建时间倒序；若无全局时间戳，则在 **6.3 编码时** 为 `job_create` 增加 `created_at` 字段。 |
| **（可选）`GET /api/pitch/jobs/batch?ids=a,b,c`** | 减少轮询次数，一次拉多条快照。 |
| **（可选 Phase 6.4）WS `job_status`** | `commit` 后 runner 在 `job_update` 时 `schedule_broadcast_to_tenant`，payload 含 `job_id`、`status`、`error`；前端合并到同一状态树。 |

**首版 6.3 可只做 REST 列表 + 轮询**，WS 作为增强项写进「二期」以免范围膨胀。

### 2.4 前端 UI 架构（推荐：**双轨展示**）

**轨 A — 「全局任务条 / Task Rail」（主信息架构）**

- **位置**：`NPCPanel` **上方**或与输入区之间一条 **窄带（高度 36–44px）**，横跨右栏宽度；赛博风：细边框 + 微渐变 + 小字 monospace 状态。  
- **数据源**：`App` 或新 **`PitchJobProvider`**（React Context）：  
  - `commit` / 旧单文件上传成功返回的 `job_id` → `registerJobs({ id, label, source: 'wizard'|'quick' })`；  
  - 内部 `useEffect` + `setInterval(700–1200ms)` 调 `GET /api/pitch/jobs/:id`（与现 `NPCPanel` 轮询同量级），聚合为 `Map<jobId, JobVM>`。  
- **展示**：每条 **横向 Chip**：`迪策… · transcribing · 转写中` → `evaluating` → `completed ✓` / `failed ✗`；点击 Chip 可展开 **tooltip**（`error` 全文 / `total_score` 若 completed）。  
- **完成后**：触发已有 `onPipelineDataChanged()` + 可选 **轻 Toast**（不抢占聊天叙事）。

**轨 B — 聊天内「豆豆」气泡（辅叙事，非主进度条）**

- **保留**当前「豆豆：已收到…」作为 **锚点消息**（用户知道任务从哪开始）。  
- **不推荐**把同一条气泡 DOM 从 `pending` 改成 `success`（实现复杂且不利于消息历史审计）。**推荐**：任务条更新到 `completed` 时，**再插入一条短豆豆消息**：「`xxx.m4a` 复盘完成，总分 xx」或失败则一条错误摘要（可带「查看任务条」引导）。  
- 这样 **主进度在 Task Rail**，**叙事在聊天**，与旧版 `st.status.write` + 日志流 **认知对齐**。

### 2.5 数据流（ASCII）

```
[PitchUploadWizard] commit → job_ids[]
        ↓
[PitchJobContext.registerJobs]  ←──┐
        ↓                            │
[TaskRail] polling GET /jobs/:id ──┘
        ↓ status change
[NPCPanel optional second bubble] + onPipelineDataChanged → [WarRoomMap refresh]
```

**与旧版 `st.progress_bar` 的映射**：Task Rail 的 **横向进度** 可用「多段 Step 图标」表达 `pending→transcribing→evaluating→completed`，不必伪造百分比（后端未提供 0–100 进度时诚实展示阶段即可）。

---

## 三、强化 NPC「豆豆」的视觉形象

### 3.1 设计原则

- **不引入重依赖**（优先纯 CSS + 可选静态图），避免打包体积与授权图库成本。  
- **状态可读**：`listening` / `thinking` / `proactive_push` 与 **Avatar 动效**绑定，与现有 `NpcStateBadge` 一致。

### 3.2 组件拆分（建议）

| 组件 | 职责 |
|------|------|
| **`DoudouAvatar`** | 圆形头像区：默认 **渐变底 + 「豆」字标**；预留 `src="/doudou.png"`（未来替换为 IP 图）。 |
| **`DoudouPresence`** | 头像 + 旁注名称「豆豆」+ 状态点；置于 `NPCPanel` **标题行左侧**，与右侧 `NpcStateBadge` 对称。 |
| **`MessageAvatar`**（可选） | 每条 **AI 消息**左侧 28–32px 列，仅 AI 显示小圆点缩略版，强化「谁在说话」；用户消息可用「指」字或指挥官首字。 |

### 3.3 动效规格（赛博陪伴感）

| 状态 | 视觉 |
|------|------|
| **listening** | 头像外环 **低亮度静态描边**（cyan 15% opacity）。 |
| **thinking** | **呼吸光晕**：`box-shadow` + `@keyframes pulseGlow`（1.8s ease-in-out infinite）；可选 **轻微 rotateY**（≤3°）避免眩晕。 |
| **proactive_push** | 外环 **ember 色短促脉冲 2 次**（与现有 proactive 气泡色一致）。 |

**技术**：CSS 变量驱动（`--doudou-glow`），由 `NPCPanel` 根据 `uiState` 切换 class；**无需** Lottie 即可达到「高级助理」基底。

### 3.4 与聊天列表的布局

- **方案 L（推荐）**：消息列表改为 **两列栅格**：左列固定宽 `avatar` + 右列 `bubble`；**系统消息**无头像跨两列或左对齐小字。  
- **方案 R**：仅在 **首条 AI 回复** 或 **每条 AI** 左侧加竖线时间轴 —— 信息密度略乱，**次选**。

### 3.5 资源占位

- `public/` 下预留 **`doudou-avatar.png`（可选）**；若文件不存在则 **CSS 回退**到渐变字标，避免 404 裂图。

---

## 四、与现有 React 文件的映射（实施时工单拆分）

| 文件（现有） | Phase 6.3 改动类型 |
|--------------|-------------------|
| `PitchUploadWizard.tsx` | 接入 autofill toggle + TS 解析 + 预览文案 + **试听条** + **字段级校验 UI** + **QA 体积预估条** |
| `App.tsx` 或新 `PitchJobProvider.tsx` | Job 注册 + 轮询生命周期 + **报告抽屉/Modal 状态** |
| 新 `TaskRail.tsx`（或内联于 `NPCPanel` 顶部） | UI + 消费 Context + **完成态「查看报告」入口** + **取消占位（见 §七.4）** |
| 新 `PitchReportPreviewCard.tsx`（建议） | 只读：摘要 + 风险点数 + 总分 + 下载 JSON / 复制 Markdown |
| `NPCPanel.tsx` | `DoudouPresence` / `MessageAvatar` / thinking 动效；完成气泡内嵌 **「打开报告」** CTA |
| `api/client.ts` | 封装 `listPitchJobs` 等 |
| 后端 `pitch.py` + `pitch_job_store.py` | `GET /api/pitch/jobs` + `created_at`；**可选** `commit` 响应增加 `qa_truncation_warnings[]` |

---

## 五、验收标准（你审核用）

**第一批（原 §一～三）**

- [ ] 选文件后 **100ms 内** 可见自动填写的被访谈人/首行疑点（或明确提示「已保护手动输入」）。  
- [ ] Vitest 覆盖 **至少** `test_audio_filename_hints.py` 中已有向量。  
- [ ] 提交向导后 **3 秒内** 用户能在 UI 上看到 **至少一条**进行中的任务状态（非纯文案「去轮询」）。  
- [ ] 任务完成或失败后 **10 秒内** UI 有明确终态，且可触发大盘刷新。  
- [ ] `thinking` 时用户能 **肉眼识别** 豆豆头像处于「工作中」动效。  

**第二批（本版 §七 Parity）**

- [ ] 每条轨道选完文件后 **5 秒内** 用户能 **耳/眼确认** 是否为正确文件（`<audio controls>` 或等价）。  
- [ ] 多 QA 合计接近/超过 30000 字时，**提交前**可见 **黄色预警**；若服务端仍截断，**提交后**可见 **与旧版文案同源的明确提示**（见 §七.3）。  
- [ ] 必填项缺失时 **字段级红框/错误文案** 与 Step 逻辑一致，且 **禁止 commit**（对齐 `app.py` 的 `st.error` 阻断语义）。  
- [ ] Job `completed` 后 **30 秒内** 用户能 **不离开右栏** 打开「报告摘要」或下载 JSON（见 §七.1）。  
- [ ] 若实现「取消」：仅当 **技术可达** 时展示；否则 UI **显式禁用**并 Tooltip 说明原因（见 §七.4）。  

---

## 六、非目标与分期（修订）

| 范围 | Phase 6.3 **做** | **不做**（另立里程碑） |
|------|------------------|-------------------------|
| 报告 | **只读摘要卡片** + **下载 `report` JSON** + 可选「复制 Markdown 骨架」；Task Rail / 聊天 **深链打开预览** | 完整 **V3 审查台**（逐条 risk 编辑、`st.data_editor` 级）、**锁定后 HTML 导出**、证据链 analytics 全量 |
| 任务取消 | **产品决策 + 技术 SPIKE** 后二选一：占位按钮或诚实禁用 | 假装支持但后台仍跑满管道 |
| 审查台音频切片 | 可选仅预览 **用户上传原文件**（整段） | 与 `report_builder` 同步的 **切片 MP3 内嵌**（依赖 FFmpeg 产物路径） |

---

## 七、第二批 UX 补全计划（主程五项追问 + 主动 Parity Audit）

### 7.1 「最后一公里」闭环 — 报告呈现（痛点：任务跑完不能结束于一句「分析完成」）

**旧版事实（`app.py` + `job_pipeline`）**

- 批量生成时 `skip_html_export=True`：先落 **analysis JSON 初稿**，主界面进入 **审查台**（`_v3_render_review_workbench`），用户可编辑 risk、发言实录等；**「锁定并生成最终版 HTML」** 后才有外发 HTML 路径提示、`st.download_button` 等客户报告分支。  
- 审查台内可对 **裁剪/关联音频** 使用 **`st.audio`** 做片段确认（约 L1539 一带）。

**FOS 现状**

- `GET /api/pitch/jobs/{id}` 在 `completed` 时已含 **`report` 字典**（与初稿 JSON 同源结构），但 **无 UI 消费**，用户感知为黑盒终点。

**推荐产品方案（分两层，避免一口吃掉 V3）**

| 层级 | 交互 | 说明 |
|------|------|------|
| **L1（Phase 6.3 必做）** | **`PitchReportPreviewCard`**：从 `report` 抽取 **总分、亮点条数、风险条数、scene 一句话**；按钮 **「📥 下载 report.json」**（`Blob` 从轮询结果生成）、**「复制摘要 Markdown」**（前端拼模板，不冒充完整 HTML 报告）。 | 入口：**Task Rail  chip 展开** 或 **聊天第二条完成气泡内「查看报告」**；同一数据源，避免重复请求。 |
| **L2（Phase 6.x）** | **侧栏全屏「只读报告」Drawer**：渲染风险点折叠列表（只读 Markdown），仍 **不** 替代审查台编辑。 | 与 L1 共用 `report` 解析器。 |
| **L3（远期）** | 对齐旧版 **锁定 + HTML + analytics** | 依赖归档路径、脱敏、记忆收割链，超出 6.3。 |

**不推荐**在聊天流内直接塞 **完整** Markdown 报告（极长、破坏线程、难折叠）；**推荐**「卡片摘要 + 打开侧栏详情 + 下载」三段式，与「高级助理」心智一致。

---

### 7.2 音频试听与容错 — 防手抖（痛点：Drawer 选完文件无法确认是否传错）

**旧版事实**

- 批量区：用户依赖 **文件名 +「仅提取文字稿」** 与 **审查台 `st.audio`** 组合确认；并非在「每条上传卡片」内嵌播放器，但 **整体系统存在可听确认路径**。  
- FOS 向导当前 **无** `<audio>` 或 `URL.createObjectURL(file)` 释放策略。

**Phase 6.3 设计（每条轨道卡片内）**

1. **`File` 选中后**：生成 `objectURL`，渲染 **`<audio controls preload="metadata">`**，标签文案：「试听本段上传（未离开本机）」。  
2. **`useEffect` cleanup**：`URL.revokeObjectURL` 防泄漏；替换文件时先 revoke 再创建。  
3. **（可选）** 与 §一联动：试听条下方展示 **解析出的 stem 与被访谈人猜测**，形成「听 + 看文件名」双确认。  
4. **大文件提示**：若 `file.size` 超过与后端一致的阈值（如 10MB 网关策略），在卡片内 **黄色 caption** 提示「将走压缩网关」，对齐旧版 status 文案语义（不必真跑转写）。

---

### 7.3 极限状态防呆 — 静默失败防御（痛点：QA 30000 字截断、必填漏填）

**旧版事实**

- `extract_text_from_files(..., max_chars=30000)`；超长时 `llm_judge` 经 `on_notice` 回调 **`QA 补充材料字数超载…`**，写入 `st.session_state["v7_qa_truncation_warn"]`，批次结束 **`st.warning`**（`app.py` L4086–4088）。  
- 必填：`category` 非占位、`institution`、每条 `batch_iv_*`、OTHER 场景 `custom_roles_other` 等，**阻断提交**（`st.error` + `return`）。

**FOS Phase 6.3 设计**

| 机制 | 前端 | 后端（可选增强） |
|------|------|------------------|
| **QA 体积预警** | 对每个 QA `File` **异步读文本长度估计**：txt/md 可读 `slice` 估字符；pdf/docx/xlsx **仅显示「已选 n 个文件，精确字数提交后由服务端计算」** 或调用轻量 **`HEAD` 式预检 API**（若不想加 API，则 **粗估文件大小 × 系数 + 提交后 warning**）。 | `commit` 响应增加 **`qa_truncation_hits: { track_index, message }[]`**，由 runner 在合并 QA 时收集与 Coach **同文案**的截断提示（需在 `pitch_wizard_runner` 或 document_reader 包装层暴露 hook）。 |
| **必填红框** | Step 2 点「确认提交」时 **字段级 `aria-invalid` + 红描边 + 列表式错误汇总**；**自动滚动**到首个错误轨道。 | 保持现有 HTTP 400 `detail` 作为 **最后防线**；前端优先 **本地拦截**以对齐旧版「提交前零惊吓」。 |
| **敏感词预览** | 增加 **「解析保密词」** 按钮（纯前端调 `parse_sensitive_words` 的 TS 移植或与 **小 POST** `/api/v1/pitch/parse-sensitive` 对齐），展示 **前 N 个词**（对齐 `app.py` L3351–3361 caption）。 | 可选后端复用 Coach `parse_sensitive_words` 避免双实现。 |
| **背景 vs 狙击冲突** | 在 Step 0 填完背景与 Step 1 狙击表后，** debounce 调** `detect_logical_conflict` 的 **TS 移植**或 **轻 API**；展示 **黄色折叠面板**（对齐旧版 Expander 警告，非阻断）。 | 与旧版 `llm_judge.detect_logical_conflict` 行为一致需 **同测向量**。 |

---

### 7.4 任务阻断与后悔药 — Cancel / Abort（痛点：选错机构能否停）

**Parity 审计结论**

- 在 **`AI_Pitch_Coach` 仓库内 `grep`「cancel/abort/撤销」无命中** —— 旧版 **亦未提供**「运行中流水线一键取消」的第一公民能力；用户心智主要靠 **提交前校验** 与 **审查台不锁定** 止损。  
- FOS 当前 `BackgroundTasks` + 同步 `run_pitch_file_job` **无协作式取消点**；强行 `terminate` 线程在 Python/FastAPI 中 **不安全**。

**Phase 6.3 产品策略（诚实 + 渐进）**

| 阶段 | 行为 |
|------|------|
| **6.3a（文档与 UI）** | Task Rail 上 **「取消」** 默认 **Disabled**，Hover **Tooltip**：「评估进行中无法安全中止；请等待完成或刷新前勿重复提交」。避免虚假承诺。 |
| **6.3b（若主程强需求）** | 引入 **`job_cancel_requested: bool`**：runner 在 **长阶段边界**（转写结束 / 评估开始前）检查；若已请求则 **跳过评估** 并将 job 标为 **`cancelled`**（**不保证**已在 LLM 内飞出的请求被召回）。需 **SPIKE** 列出 `run_pitch_file_job` 可插入的检查点数。 |
| **6.3c（替代后悔药）** | **「复制本次向导 JSON」** 在 commit 前一步，便于用户 **留底**；**重复提交**时 Task Rail **堆叠多条**并高亮「新」任务，减少误操作焦虑。 |

---

### 7.5 其它遗漏的优秀体验（主动 Parity 清单）

以下条目来自 **`app.py` 主控制台与侧边栏** 与 FOS 向导对照，**上一版方案未单列**但应在 6.3/6.x 排期：

| # | 旧版体验 | FOS 建议 |
|---|----------|----------|
| 1 | **`env_all_ok`**：API/FFmpeg 未自检通过则 **禁止生成** | 向导 **提交前** 调 `GET /health` 或专用 **`GET /api/pitch/readiness`**（聚合 Key 存在性占位），未通过则 **主按钮灰化 + 文案** |
| 2 | **「仅提取文字稿」** 对 **首条** 音频快速验证 ASR（与批量解耦） | Phase 6.3 **可选**：轨道卡片上 **「快速转写预览」** 走独立 API（易计费，需主程点头）；**否则** 用 **试听 + 文件名魔法** 降级替代 |
| 3 | **`USE_LANGGRAPH_V1` toggle** | 向导已带开关；Task Rail **tooltip** 标注当前图模式，避免「为何与昨日不同」 |
| 4 | **机构名 `institution_fuzzy_match` 提示** | Step 0 输入机构后 **debounce** 调 `GET /api/v1/pipeline/institutions` 或专用 fuzzy 接口，展示 **「疑似历史 canonical」** caption（对齐 `app.py` L3483–3491） |
| 5 | **HTML 外发脱敏 / 水印 / mask_html_body** | **6.3 不做**；在报告预览 L2 中 **脚注提示**「外发脱敏在归档版开通」 |
| 6 | **录音同意方式、融资结果等锁定字段** | 仅审查台链路；**6.3** 在报告卡片 **灰色提示**「证据链字段尚未接入」 |
| 7 | **多文件时「仅提取文字稿」只处理第 1 条** 的说明 caption | 若做「快速预览」API，**必须**在 UI 写死 **「仅对轨道 1 生效」** 与旧版一致 |
| 8 | **Workspace / 归档路径可见性** | FOS 暂为临时目录时，报告卡片 **明确标注**「初稿未归档到企业盘；下载 JSON 备份」—— **操作安全感** |
| 9 | **`st.balloons` / 成功情绪** | 任务 **全部 completed** 时 **轻量 Confetti CSS 一次**（可关） |

---

## 八、实施顺序建议（修订版）

1. **文件名魔法（TS）** + **试听条** + **本地必填/红框**。  
2. **Task Rail** + **`GET /api/pitch/jobs`** + 轮询 + **完成气泡 + 报告卡片 L1**。  
3. **豆豆 Avatar + 动效** + 消息栅格。  
4. **QA 截断预警**（前端粗估 + 可选 `commit` 回传 warnings）+ **敏感词解析按钮** + **logical_conflict（API 或 TS）**。  
5. **取消任务 SPIKE** → 按 §7.4 定案是否做 6.3b。  
6. **可选 WS `job_status`**、readiness 门禁、机构 fuzzy caption。

---

**文档结束。** 路径：`docs/PHASE6_3_UX_PLAN.md`。本版已整合 **第二批 UX 补全** 与 **Parity Audit**。  
**与实现对齐备忘：** 编码阶段已完成多轮（文件名魔法 TS、Task Rail、报告预览、错误分层、豆豆光核图等）；§0 表格中部分行仍为「方案级差距」——见 **`docs/AI_HANDOFF_PHASE6.md` §6** 的后续优化列表。
