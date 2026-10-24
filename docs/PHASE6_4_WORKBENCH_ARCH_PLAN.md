# Phase 6.4 — 深度审查台复刻架构图纸

> **状态**: 待施工批准  
> **起草**: Principal Architect (Claude) · 2026-04-18  
> **范围**: 四大核心断层的技术决策 + 组件/接口设计，不含实现代码

---

## 〇、现状诊断备忘

| 层次 | 当前缺陷 | 严重级别 |
|------|----------|----------|
| 数据持久化 | `pitch_job_store.py` 是纯内存 dict，重启清零；`report` 字段单一，无 original/edited 分离；`words_list` 在 pipeline 结束后随 tmp 文件被删除，词级时间戳**永久丢失** | P0 |
| UI | `PitchReportPreviewModal` max-w-lg + max-h-[85vh]，只读 L1 摘要，无 CRUD | P0 |
| 音频 | 因 words_json 丢失，任何音频切片操作都无法还原 | P0 |
| NPC 上下文 | `_base_system()` 无录音复盘能力声明；无法联动 job 状态 | P1 |

---

## 一、状态机分离与数据持久化策略

### 1.1 核心设计原则

**原始数据不可篡改（Immutable Source of Truth）**。

AI 输出的草稿报告（`original_report`）在 `COMPLETED` 时写入一次，之后后端接口**绝不覆写**它。所有人工修改写入独立字段 `edited_report`。前端 diff 功能可对比两者。

### 1.2 SQLite 表结构（替换当前内存 dict）

新增文件：`backend/src/cangjie_fos/services/pitch_job_db.py`

```sql
-- 新建 pitch_jobs 表（独立于 langgraph_npc.sqlite）
CREATE TABLE IF NOT EXISTS pitch_jobs (
    job_id        TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    REAL NOT NULL,

    -- 双版本报告字段：原始 AI 草稿（不可改）vs 人工已提交版本
    original_report  TEXT,   -- JSON string，pipeline 完成时写入，此后只读
    edited_report    TEXT,   -- JSON string，HITL 审查台 PATCH 写入，null = 未审查

    -- 音频溯源：词级时间戳与音频文件路径（两者缺一不可）
    words_json    TEXT,      -- TranscriptionWord[] JSON，pipeline 完成时持久化
    audio_path    TEXT,      -- 磁盘绝对路径（非 tmp），pipeline 完成时移动至此

    -- 审查态追踪
    committed_at  REAL,      -- 人工锁定时间戳；null = 未审查
    exp_delta     INTEGER DEFAULT 0,
    exp_reason    TEXT DEFAULT '',

    -- 错误信息
    error_summary TEXT,
    error_detail  TEXT,
    error_code    TEXT
);
CREATE INDEX IF NOT EXISTS idx_pitch_jobs_tenant ON pitch_jobs(tenant_id, created_at DESC);
```

**数据库文件路径**：`backend/data/pitch_jobs.sqlite`（与 `institutions.sqlite` 同目录）

### 1.3 Pipeline 写入时序

```
[run_pitch_upload_job]
  ↓ ASR 完成
  → 将 tmp 音频文件 mv → data/audio/{job_id}{suffix}  ← 永久存储
  → 将 words[] JSON 序列化 → db.words_json
  ↓ LangGraph 完成
  → db.original_report = report.model_dump()  ← 写入一次，后端不再碰它
  → db.status = 'completed'
```

### 1.4 人工审查 API 契约

#### 读取（不会污染原始数据）

```
GET /api/pitch/jobs/{job_id}/review
Response 200:
{
  "job_id": "...",
  "status": "completed",
  "original_report": { ... },       ← 只读，AI 草稿
  "edited_report": null | { ... },  ← 已有人工版本则返回，否则 null
  "committed_at": null | 1713456789.0,
  "words_summary": {                ← 供前端构建词索引，不返回完整 words
    "total_words": 1240,
    "duration_sec": 843.2
  }
}
```

#### 词级索引（音频联动专用）

```
GET /api/pitch/jobs/{job_id}/words
Response 200: [
  { "word_index": 0, "text": "我们", "start_time": 0.12, "end_time": 0.45, "speaker_id": "S1" },
  ...
]
```

#### 音频文件流（HTTP Range 支持）

```
GET /api/pitch/jobs/{job_id}/audio
Response 206/200: audio/mpeg 或 audio/mp4 字节流
Header: Accept-Ranges: bytes
```

#### 提交/锁定（PATCH，仅写 edited_report）

```
PATCH /api/pitch/jobs/{job_id}/review
Body:
{
  "edited_report": {
    "scene_analysis": { "scene_type": "...", "speaker_roles": "..." },
    "total_score": 72,
    "total_score_deduction_reason": "...",
    "risk_points": [
      {
        "_rid": "abc123",            ← 前端回传 rid 供 diff 对照
        "risk_level": "严重",
        "tier1_general_critique": "...",   ← 仍完整回传（后端不修改原始）
        "tier2_qa_alignment": "...",
        "improvement_suggestion": "...",
        "original_text": "...",
        "start_word_index": 42,
        "end_word_index": 67,
        "score_deduction": 10,
        "deduction_reason": "...",
        "is_manual_entry": false
      }
    ]
  }
}
Response 200:
{
  "job_id": "...",
  "committed_at": 1713456789.0,
  "diff_summary": { "risk_points_added": 0, "risk_points_removed": 1, "fields_changed": 3 }
}
```

**后端校验规则**：
- `original_report` 不变（不 touch）
- 写入 `edited_report` 前，`Pydantic AnalysisReport.model_validate(body.edited_report)` 全量校验
- 写入 `committed_at = time.time()`
- `_rid` 字段后端透传存储，不做业务校验（纯前端追踪用）

### 1.5 前端状态模型（TypeScript）

```typescript
// 审查台本地状态，不与后端 original_report 共享引用
type ReviewWorkbenchState = {
  jobId: string;
  originalReport: AnalysisReport;      // 从 GET /review 加载，不可变引用
  draftReport: AnalysisReport;         // 本地可变副本（deep clone of original）
  isDirty: boolean;                    // draftReport !== originalReport
  isCommitted: boolean;                // 是否已 PATCH 成功
  committedAt: string | null;
  wordsMap: Map<number, TranscriptionWord>;  // word_index → word，从 GET /words 懒加载
};
```

**防污染机制**：`originalReport` 对象引用在组件生命周期内只读。任何编辑操作都操作 `draftReport`（immer 或手动 deep clone）。

---

## 二、独立全屏审查台路由与 UI 架构

### 2.1 路由方案决策

**选择：安装 `react-router-dom` v6，新增真正的页面路由**

**理由**：
- 独立 URL（`/review/abc123`）支持浏览器 Back 键、刷新不丢失、可分享给团队成员
- 与主页 `/` 完全隔离，无状态泄漏风险
- 相比 100vw Drawer，路由方案在 UI 层级上更清晰，无需管理 zIndex 战争
- `react-router-dom` 已是行业标准，无额外心智负担

**替代方案（被否决）**：`?review=job_id` 查询参数方案虽然不需要 router，但会在主页 DOM 下渲染全屏覆盖层，状态管理更复杂，且无法用 Back 键自然关闭。

### 2.2 组件层级树

```
src/
├── main.tsx          ← 新增 BrowserRouter 包裹
├── App.tsx           ← 改为 Route "/"
├── pages/
│   └── ReviewWorkbench.tsx   ← 新页面，Route "/review/:job_id"
└── components/
    ├── workbench/
    │   ├── WorkbenchHeader.tsx        ← 顶栏：job_id、状态 badge、返回、锁定按钮
    │   ├── WorkbenchBody.tsx          ← 左右双栏 grid 容器
    │   ├── left/
    │   │   ├── SceneHeaderFields.tsx  ← 场景推断/角色/总分/扣分说明（可编辑）
    │   │   ├── RiskPointList.tsx      ← 风险点列表容器（虚拟滚动候选）
    │   │   ├── RiskPointCard.tsx      ← 单条风险点完整 CRUD 卡片
    │   │   │   ├── RiskLevelSelector     ← 下拉：严重/一般/轻微
    │   │   │   ├── OriginalTextEditor    ← textarea（可编辑，ASR 实录）
    │   │   │   ├── ImprovementEditor     ← textarea（可编辑，改进建议）
    │   │   │   ├── AudioSnippetPlayer    ← 音频联动播放器（见第三节）
    │   │   │   ├── AIReasoningAccordion  ← 折叠展开：Tier1/Tier2/扣分（只读）
    │   │   │   ├── RefinePanel           ← 标记需精炼 + 批示意见输入
    │   │   │   └── DeleteButton          ← 删除此条（本地 state）
    │   │   └── AddRiskPointForm.tsx   ← 手动新增遗漏痛点（is_manual_entry=true）
    │   └── right/
    │       ├── JobInfoPanel.tsx       ← 任务元数据：上传时间、转写词数、总分对比
    │       ├── WorkbenchNPCChat.tsx   ← 豆豆迷你对话框（注入 job_id 上下文）
    │       └── HtmlReportPreview.tsx  ← 最终 HTML 报告实时预览（iframe srcdoc）
    └── PitchReportPreviewModal.tsx    ← 保留但改为入口跳转，不再做只读展示
```

### 2.3 版面规格

```
┌─────────────────────────────────────────────────────────┐
│  WorkbenchHeader  [← 返回]  job:abc123  [COMPLETED]  [锁定 ▶]  │
├───────────────────────────────┬─────────────────────────┤
│  LeftPanel (60%)              │  RightPanel (40%)        │
│                               │                          │
│  SceneHeaderFields            │  JobInfoPanel            │
│  ─────────────────            │  ─────────────           │
│  RiskPointCard #1             │  WorkbenchNPCChat        │
│    [严重] [播放▶] [删除]      │  （豆豆：知道当前 job）   │
│    原文实录: ...              │  ─────────────           │
│    改进建议: [textarea]       │  HtmlReportPreview       │
│    [AI推理链 ▼]               │  （实时 HTML 预览）      │
│  RiskPointCard #2 ...         │                          │
│  ...                          │                          │
│  [➕ 新增遗漏痛点]            │                          │
└───────────────────────────────┴─────────────────────────┘
│  WorkbenchFooter  [另存草稿]  [提交锁定 ✓]                     │
└─────────────────────────────────────────────────────────┘
```

**尺寸约束**：`h-screen overflow-hidden`，左右各自独立 `overflow-y-auto`，防止整页滚动失控。

### 2.4 现有 Modal 的改造方式

`PitchReportPreviewModal.tsx` 不删除，改造为**跳转入口**：

```tsx
// 现有"查看报告"按钮的 onClick 从打开 Modal 改为：
onClick={() => window.open(`/review/${jobId}`, '_self')}
// 或使用 react-router <Link to={`/review/${jobId}`} />
```

Modal 内容改为：简化的"正在加载，跳转中..."过渡态，或直接删除 Modal 逻辑，改为在 TaskRail 里渲染 `<Link>` 按钮。

---

## 三、音频精准联动机制技术选型

### 3.1 两种方案对比

| 维度 | 方案 A：前端 currentTime 跳转 | 方案 B：后端 FFmpeg 按需切片 |
|------|-------------------------------|------------------------------|
| 延迟 | 近零（audio.currentTime 赋值即播放） | 1-3s（FFmpeg 子进程） |
| 带宽 | 全量音频一次性加载（HTTP Range 缓冲） | 每片独立请求，多次小体积传输 |
| 服务器负载 | 无额外计算 | 每次 HITL 点击触发 FFmpeg |
| 非对称缓冲 | 可在前端实现（见下方逻辑） | 天然与旧系统一致（PAD_START=1.5s, PAD_END=8.0s） |
| 依赖 | words_json（时间映射） + 静态音频 URL | words_json + 磁盘 FFmpeg |
| 最终 HTML 报告 | 仍需 FFmpeg（Base64 内嵌） | 同左 |
| 适用场景 | 交互式 HITL 审查台实时试听 | 最终报告生成 |

### 3.2 决策：方案 A（前端 currentTime）用于审查台

**理由**：

1. **审查台需要"即点即听"**：若每次点击等待 1-3s FFmpeg，HITL 体验灾难性下降
2. **音频文件已持久化存储**：pipeline 完成后音频不再删除，可作为静态资源服务
3. **非对称缓冲在前端完全可实现**：
   ```
   playStart = Math.max(0, words[start_word_index].start_time - 1.5)
   playEnd   = words[end_word_index].end_time + 8.0
   audio.currentTime = playStart
   audio.play()
   // ontimeupdate 监听到 currentTime >= playEnd 时 pause
   ```
4. **HTTP Range 支持**：浏览器对 `<audio>` 的 Range 请求是原生行为，不会全量下载

**方案 B 保留场景**：仅用于"生成最终 HTML 报告"这个操作（与旧系统 `report_builder.py` 逻辑完全一致），按需调用，不在审查台实时触发。

### 3.3 前端 AudioSnippetPlayer 组件规格

```typescript
// props
type AudioSnippetPlayerProps = {
  jobId: string;
  startWordIndex: number;
  endWordIndex: number;
  wordsMap: Map<number, { start_time: number; end_time: number }>;
  // wordsMap 由父组件 ReviewWorkbench 统一加载，避免每个 Card 各自请求
};

// 内部逻辑
// 1. 共享同一个 <audio> element（通过 Context 或 ref 传递），避免多路音频并发
// 2. 计算 playStart / playEnd
// 3. 渲染：[▶ 播放此片段]  ← 按钮
//           [00:42 — 01:23]  ← 时间标签（由 word index 换算）
//           <progress> 进度条（可选）
```

**边界处理**：
- `wordsMap` 中不存在对应 index → 显示"索引越界，无法定位"提示，不崩溃
- `is_manual_entry=true` → 不渲染播放按钮，显示"人工条目，无词级锚点"
- 音频文件 404/加载失败 → 显示降级提示

### 3.4 后端音频服务接口

```python
# 新增路由：backend/src/cangjie_fos/api/routes/pitch.py
@router.get("/jobs/{job_id}/audio")
async def stream_pitch_audio(job_id: str, request: Request) -> FileResponse:
    """HTTP Range 支持的音频流（静态文件服务）。"""
    # 从 DB 读取 audio_path
    # 若文件不存在返回 404
    # 使用 fastapi.responses.FileResponse，自动处理 Range header
```

```python
# 词级索引接口
@router.get("/jobs/{job_id}/words")
def get_pitch_words(job_id: str) -> list[PitchWordIn]:
    # 从 DB 读取 words_json，反序列化后返回
```

### 3.5 音频文件存储策略

**路径规则**：`backend/data/audio/{job_id}{.m4a|.mp3|.wav}`

`run_pitch_upload_job` 中，在 tmp 文件处理结束后，执行 `shutil.move(tmp, audio_store_path)` 而不是 `tmp.unlink()`。

---

## 四、修复 NPC 大脑的上下文隔离

### 4.1 现状问题定位

**文件**：`backend/src/cangjie_fos/services/npc_chat_graph.py`

| 问题节点 | 当前内容 | 缺陷 |
|----------|----------|------|
| `_base_system()` (L36-41) | 仅声明"融资陪练 NPC"，提到"资料室清单" | 完全不知晓系统具备录音上传、ASR 转写、LangGraph 复盘能力 |
| `_inject_narrative()` (L63-77) | 注入租户上下文、进化指南、机构会前简报、错题本 | 无当前激活 job 的状态注入 |
| `NpcGraphState` (L23-28) | `messages, tenant_id, user_name, evolution_guidelines, narrative` | 无 `active_job_id` 字段 |
| `invoke_npc_chat()` (L166-192) | 接受 `tenant_id, user_message, thread_id, user_name` | 无 `active_job_id` 参数 |

### 4.2 需要修改的节点

#### 修改 1：`_base_system()` — 注入系统能力声明

在现有 return 字符串后追加以下内容（不替换，追加）：

```python
def _base_system() -> str:
    n = _npc_display_name()
    base = (
        f"你是「仓颉 FOS」里的融资陪练 NPC「{n}」。"
        "回答简短、可执行，偏一级市场语境；不要编造私密数据。"
        "若用户问「是否准备好见红杉」等，请结合下方「资料室清单」指出明显缺口。"
    )
    # 新增：系统能力声明
    capability_block = (
        "\n\n[系统能力说明]\n"
        "本系统已具备「音轨复盘与路演打分」能力：\n"
        "1. 用户可上传路演录音（m4a/mp3/wav），系统通过阿里云 ASR 获取词级时间戳转写；\n"
        "2. LangGraph 多维评估引擎对每段对话进行双层风险诊断（Tier1 全球 VC 视角 / Tier2 QA 对齐）；\n"
        "3. 报告含总分（0-100）、风险点列表、每个风险点的词级音频锚点，供人工审查台逐条复盘；\n"
        "4. 人工审查台支持增删改风险点、锁定最终版本、生成单文件 HTML 报告（含 MP3 切片内嵌）。\n"
        "当用户询问录音评估、复盘、打分相关问题时，应主动协助解读报告内容，而非声称系统不支持。"
    )
    return base + capability_block
```

#### 修改 2：`NpcGraphState` — 新增 active_job_id 字段

```python
class NpcGraphState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    tenant_id: str
    user_name: str
    evolution_guidelines: str
    narrative: str
    active_job_id: str | None   # 新增：当前用户正在查看的 job，由前端传入
```

#### 修改 3：新增 `_inject_active_job_context` 节点

```python
def _inject_job_status(state: NpcGraphState) -> dict[str, str]:
    """将当前激活 job 的状态注入 narrative（如前端传入了 active_job_id）。"""
    job_id = (state.get("active_job_id") or "").strip()
    if not job_id:
        return {}
    # 调用 pitch_job_db.job_get(job_id)
    # 构建简洁状态块，例如：
    # [当前复盘任务]
    # job_id: abc123  状态: completed  总分: 72  风险点数: 5  已审查: 否
    # 最高风险: "过于依赖 TAM 数据，未提供 SAM 验证"
    ...
    return {"narrative": state.get("narrative", "") + job_status_block}
```

#### 修改 4：Graph 结构——插入新节点

```
现有：preload → inject → agent → END
改为：preload → inject → inject_job → agent → END
```

```python
def _build_graph(checkpointer: Any) -> Any:
    g = StateGraph(NpcGraphState)
    g.add_node("preload", _preload_evolution)
    g.add_node("inject", _inject_narrative)
    g.add_node("inject_job", _inject_job_status)   # 新增
    g.add_node("agent", _call_llm)
    g.set_entry_point("preload")
    g.add_edge("preload", "inject")
    g.add_edge("inject", "inject_job")             # 新增
    g.add_edge("inject_job", "agent")              # 新增（替换原 inject→agent）
    g.add_edge("agent", END)
    return g.compile(checkpointer=checkpointer)
```

#### 修改 5：`invoke_npc_chat()` 新增参数

```python
def invoke_npc_chat(
    *,
    tenant_id: str,
    user_message: str,
    thread_id: str | None,
    user_name: str | None = None,
    active_job_id: str | None = None,   # 新增
) -> tuple[str, str, str]:
    ...
    out = app.invoke(
        {
            "messages": [HumanMessage(content=user_message)],
            "tenant_id": tenant_id,
            "user_name": (user_name or "").strip(),
            "active_job_id": (active_job_id or "").strip() or None,   # 新增
        },
        cfg,
    )
```

#### 修改 6：`PitchChatRequest` schema 新增字段

文件：`backend/src/cangjie_fos/schemas/pitch_chat.py`

```python
class PitchChatRequest(BaseModel):
    ...
    active_job_id: str | None = None   # 新增：当前查看的复盘任务 ID
```

#### 修改 7：前端 `WorkbenchNPCChat.tsx` 传参

在审查台右侧 NPC 对话框中，每次发送消息都附带当前 `jobId`：

```typescript
// WorkbenchNPCChat.tsx
await api.post("/api/pitch/chat", {
  tenant_id: tenantId,
  message: userInput,
  thread_id: threadId,
  user_name: userName,
  active_job_id: jobId,    // 新增
});
```

---

## 五、关键前置依赖：`pitch_upload_pipeline.py` 必须修改

以上所有音频联动与报告生成能力，**有一个隐藏的 P0 前提**：当前 pipeline 在 `finally` 块中 `tmp.unlink(missing_ok=True)` 删除了音频文件，且 `words` 列表没有持久化到 DB。

**必须在 Phase 6.4 施工第一步解决**：

```
修改范围：
1. run_pitch_upload_job() 中：
   - 将 tmp 文件 move 到 data/audio/{job_id}{suffix}（非 unlink）
   - 将 words[] 序列化为 JSON 后写入 DB words_json 字段
   - 将 report.model_dump() 写入 DB original_report 字段（非覆写，一次性）

2. 现有 pitch_job_store.py（内存 dict）：
   - 作为过渡兼容层保留（不立刻删除，防止测试全红）
   - 新建 pitch_job_db.py 实现 SQLite 持久化
   - 在接口层优先读 DB，降级读内存（迁移期）
```

---

## 六、施工优先级与依赖图

```
[P0] 数据持久化层建立
  ├─ pitch_job_db.py (SQLite)
  ├─ run_pitch_upload_job 修改（音频持久化 + words_json 持久化）
  └─ GET /jobs/{id}/words + GET /jobs/{id}/audio 接口

[P1] 审查台后端接口
  ├─ GET /jobs/{id}/review（original + edited 双版本）
  ├─ PATCH /jobs/{id}/review（只写 edited_report）
  └─ POST /jobs/{id}/html-report（触发 FFmpeg 最终报告生成）

[P2] 审查台前端
  ├─ 安装 react-router-dom，改造 main.tsx
  ├─ pages/ReviewWorkbench.tsx 骨架
  ├─ 组件树（WorkbenchHeader/Body/Footer）
  ├─ AudioSnippetPlayer（currentTime 跳转）
  └─ HtmlReportPreview（iframe srcdoc）

[P3] NPC 上下文修复（独立，可并行）
  ├─ npc_chat_graph.py 修改（4 处）
  ├─ pitch_chat.py schema 修改
  └─ WorkbenchNPCChat.tsx（新组件 + active_job_id 传参）
```

---

## 七、重点风险提示

### 风险 1：SQLite 并发写（pipeline 后台线程 vs API 主线程）
`pitch_job_db.py` 必须使用 `check_same_thread=False` + `WAL 模式`（`PRAGMA journal_mode=WAL`），与现有 `institutions.sqlite` 保持一致的连接策略。

### 风险 2：音频文件磁盘占用
每个 job 的音频文件不再删除。需要在 `garbage_collector`（旧系统有此模块）中规划 TTL 策略：建议 30 天后自动清理 `audio_path` 文件（保留 DB 记录）。

### 风险 3：words_json 数据量
一场 30 分钟路演约 3000-5000 词，每词 5 字段，约 200-400KB/job。可接受，不压缩。

### 风险 4：HTML 报告生成的 FFmpeg 依赖
`report_builder.py` 依赖 `imageio_ffmpeg`。需在 FOS backend 的 `pyproject.toml` 中添加 `imageio-ffmpeg` 依赖，并参照旧系统的 `_get_ffmpeg_exe()` 做 Windows/Linux 兼容处理。

### 风险 5：前端 Audio element 多路并发
多个 RiskPointCard 同时渲染，用户快速点击多个播放按钮会导致多个音频同时播放。需要全局唯一 `<audio>` element（via React Context 或 Zustand），每次播放前先 pause 上一个。

---

## 八、接口变更一览（API Surface Delta）

| 方法 | 路径 | 状态 | 说明 |
|------|------|------|------|
| GET | `/api/pitch/jobs/{job_id}` | 保留 | 现有接口不变，兼容 TaskRail |
| GET | `/api/pitch/jobs/{job_id}/review` | **新增** | 双版本报告 + words_summary |
| GET | `/api/pitch/jobs/{job_id}/words` | **新增** | 词级时间戳索引 |
| GET | `/api/pitch/jobs/{job_id}/audio` | **新增** | 音频流（Range 支持） |
| PATCH | `/api/pitch/jobs/{job_id}/review` | **新增** | 人工锁定 edited_report |
| POST | `/api/pitch/jobs/{job_id}/html-report` | **新增** | 触发 FFmpeg 最终报告生成 |

---

*图纸版本 v1.0 · 待主理人审批后开始 Phase 6.4 施工*
