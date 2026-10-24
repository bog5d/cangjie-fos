# Phase 6.3 修订方案：错误降级架构 & NPC 视觉重构

**文档性质：** 架构与 UX 设计说明（**不含实现代码**）。  
**触发原因：** 实战打样暴露两类底线问题——（一）Task Rail 将底层转写失败 Raw JSON 直接暴露在主界面；（二）当前豆豆头像具象化、破坏「高端融资指挥舱」质感。  
**目标：** 本文定义**契约、分层与视觉红线**；对应实现与文件锚点见 **`docs/AI_HANDOFF_PHASE6.md`**。

**落地状态（摘要）：** 后端已收敛 `error_summary` / `error_detail` / `error_code` 与失败写入辅助；前端主界面消费摘要；豆豆组件为 **光核 + 轨道** 并可挂载 **`frontend/public/doudou-core.png`**（加载失败回退字标）。Task Rail「查看报告」与 `has_report` 语义已收紧以避免竞态。

**新 AI 请先读：** [`AI_HANDOFF_PHASE6.md`](./AI_HANDOFF_PHASE6.md)

---

## 第一部分：全局错误降级与展示机制（Graceful Degradation）

### 1.1 问题定性（为何是架构问题而非「改一行 UI」）

- **根因**：前端把「持久化/展示用的 `error` 字段」与「人类可读摘要」混为一谈；后端或中间层在失败时把**供应商原始响应体**（如阿里云 ASR 的 `request_id` / `output` 结构）原样写入 `job.error` 或等价字段，前端**无清洗层**即渲染。
- **后果**：商业级 SaaS 中，主界面出现 JSON 块 = **信任破产** + **合规风险**（可能含内部 URL、Token 片段、堆栈路径）。
- **结论**：必须在**数据平面**与**表现平面**之间插入**「错误呈现策略层」**（Error Presentation Layer），与具体业务（转写 / LangGraph）解耦。

### 1.2 分层模型（推荐）

| 层级 | 职责 | 产出物 |
|------|------|--------|
| **L0 来源** | 各 Runner / HTTP 客户端捕获异常 | 结构化 `FailureRecord`（见下） |
| **L1 规范化（后端）** | 将任意 `Exception`、HTTP body、云厂商 JSON **收敛**为统一 schema | `user_message`（短）、`detail`（可选，供调试）、`error_code`、`provider`（可选枚举） |
| **L2 前端安全渲染** | **永不**对未知字符串做 `JSON.stringify` 直出；仅消费 `user_message` + 受控 `detail` | `ErrorViewModel` |
| **L3 UI 组件** | Task Rail、Toast、Modal 只绑定 `ErrorViewModel` | 红底摘要标签 + Hover/展开看详情 |

**原则**：主界面只出现 **L2 的 `summary`（≤80 字级）**；完整原始体仅出现在 **需主动操作才可见** 的区域（Hover 浮层、复制到剪贴板、下载诊断包——若产品允许）。

### 1.3 后端契约建议（`PitchJob` / 任务 API）

新增或约束字段语义（命名可微调，**语义不可缺**）：

- **`error_summary`（string，必填于 failed 态）**  
  - 人类可读、**无 JSON 花括号**、无多行堆栈默认。  
  - 例：「语音转写服务暂时不可用，请稍后重试」而非整段 Raw JSON。
- **`error_detail`（string | null，可选）**  
  - 供「技术支持 / 高级用户」查看；可为**脱敏后**的供应商响应摘要（截断 + 移除疑似密钥模式）。
- **`error_code`（string，可选）**  
  - 稳定枚举：`ASR_TIMEOUT`、`ASR_VENDOR_REJECT`、`GRAPH_EVAL_FAILED` 等，便于前端映射图标与帮助链接。
- **`raw_ref_id`（string，可选）**  
  - 若必须保留 `request_id` 用于工单，仅展示「工单号：xxx」，**不把整段 JSON 当 UI 文案**。

**拦截与提取流程（逻辑描述）**：

1. **捕获点**：`run_pitch_wizard_track_job` / `run_pitch_upload_job` 等单一出口 `except` 中，不直接 `str(e)` 写入对外字段。
2. **分类器**：根据异常类型 / HTTP status / 云 SDK 错误码 → 映射到 `error_code` + 本地化 `error_summary`（中文产品句）。
3. **原始体处理**：若需落库排障，写入**日志或内部对象存储**；API 仅返回 `error_summary` + 可选 `error_detail`（已脱敏）。
4. **兜底**：无法分类时，`error_summary` = 「处理失败，请重试或联系管理员」，`error_detail` 可为 null 或极简 `trace_id`，**禁止**把未知 `dict` 转字符串塞进 `error_summary`。

### 1.4 前端 `ErrorViewModel`（概念）

从 `GET /api/pitch/jobs` / 单 job 响应构造：

- `summary`：优先 `error_summary`；若后端尚未升级，则走 **客户端兜底清洗**（见 1.5）——**过渡期**使用，最终应以后端为准。
- `detailSafe`：仅当存在 `error_detail` 或经清洗的调试片段。
- `hasTechnicalDetail`：布尔，控制是否显示「详情」 affordance。

**Task Rail 专用规则**：

- Chip **失败态**仅展示 **一行 `summary`**（或截断到 24～32 字 +「…」）。
- **禁止**在 Chip 正文内渲染 `error` 原始字符串若其以 `{` 开头或可被解析为 JSON——一律走清洗为 `summary`。

### 1.5 过渡期：客户端「防呕吐」清洗（仅作防线，不替代后端）

当 `error` 字段仍为历史形态（整段 JSON）时：

- **检测**：`trimStart()` 是否为 `{`/`[` 或 `includes('"request_id"')` 等启发式。
- **提取**：尝试解析 JSON，优先读取常见键（如 `message`、`Message`、`error_msg`、`code`）拼接一句人话；若无，则 **丢弃内容**，展示固定兜底句 + `job_id` 后六位。
- **日志**：完整原始体可 `console.debug` 或上报（若已有遥测），**不**上主 UI。

### 1.6 UI 交互：状态标签 + Hover 详情（你指定的模式）

**Task Rail 失败 Chip**

- **常态**：红底（或深红半透明底）+ **白字或浅字**的 **短标签**，文案仅为 `summary` 截断版，例如：「转写失败 · 服务繁忙」。
- **Hover（桌面）**：`title` **不足以**承载多行堆栈；使用 **受控 Tooltip / Popover**（200～320px 宽，最大高度可滚动），内部分区：  
  - **「说明」**：`summary` 全文；  
  - **「技术详情」**（可折叠默认收起）：`detailSafe` 等宽字体、可选「复制」按钮；  
  - **禁止**在 Tooltip 内自动播放动画或闪烁，避免干扰。
- **触控（无 Hover）**：Chip 点击展开同一 Popover；再次点击或失焦关闭。
- **可访问性**：`aria-expanded`、键盘 Esc 关闭、焦点陷阱按设计规范。

**全局扩展（同一套 ViewModel）**

- 聊天内系统消息、Toast、向导提交错误，**共用**同一套摘要生成与 Tooltip 组件变体，避免「Task Rail 一套、别处又吐 JSON」。

### 1.7 验收标准（错误域）

- 任意复现阿里云类 Raw JSON 失败时，**主界面不可见**完整 JSON；仅 Tooltip/详情内可见**脱敏**片段。  
- 失败 Chip 首屏信息 **≤1 行**，用户无需滚动即可理解「失败了、大致哪类问题」。  
- 后端升级后，客户端兜底路径触发率 **趋近于 0**。

---

## 第二部分：DoudouAvatar 视觉重构（抽象 · 极简 · 有机互动）

### 2.1 设计红线（必须遵守）

- **禁止**：具象五官（眼、嘴、鼻等）、Emoji 化圆脸、卡通生物拟人。  
- **禁止**：高饱和「塑料渐变球 + 五官」类素材（当前 SVG 方向属于此列，整体废弃）。  
- **允许**：抽象几何、光晕、粒子感边缘、**文字标**（「豆」或品牌字标的几何变体）、极细线框与玻璃拟态（需克制，避免廉价毛玻璃堆叠）。

### 2.2 参考气质（非像素级抄袭）

- **OpenAI / 现代 AI 产品**：深色底上的 **柔和多色光晕核**、边缘模糊、**无脸**；状态靠 **光强与节奏** 变化。  
- **Siri 抽象态**：**有机形体**可简化为 **不规则圆角blob + 内部渐变漂移**（仍无五官），或简化为 **同心环相位动画**。  
- **指挥舱语境**：偏 **青紫 + 极低噪点**、细线 HUD 圈（orbit ring）而非卡通角色。

### 2.3 推荐方案：**「能量核 + 轨道环」双层级 DOM**（纯 CSS 为主）

**结构构思（逻辑层级）**

1. **外层 `Orbit`**（可选）：`1px` 或 `0.5px` 细线圆/圆角矩形，**极低不透明度**；`listening` 时几乎静止，`thinking` 时缓慢旋转或 dash-offset 流动（**≤360°/8～12s**，避免眩晕）。  
2. **中层 `Halo`**：`filter: blur` + 多层 `box-shadow` 或伪元素叠放，形成 **弥散光球**；颜色用 **cyan / plasma 两色在暗底上的低对比混合**，避免荧光塑料感。  
3. **内核 `Core`**：  
   - **方案 A（默认）**：极小半径的实心圆或圆角正方形，**单色或双色对角渐变**，`thinking` 时 **scale 1 → 1.06 → 1** 呼吸（周期 2～2.5s，`ease-in-out`）。  
   - **方案 B（文字核）**：几何化「豆」字——**无衬线粗体 + 字间距压缩 + 轻微剪切 skew**，外圈光晕替代「脸」；状态仅靠光晕强度与字重微动（**禁止**字变形为表情）。

**状态映射（与现有 `NpcUiState` 对齐）**

| 状态 | 视觉语言（描述） |
|------|------------------|
| **listening** | 外环静态或极慢「相位漂移」；内核 **低亮度**；光晕半径小、opacity 低（「待命但在线」）。 |
| **thinking** | 光晕 **呼吸**：`opacity` + `blur` 半径同步起伏（1.8～2.2s）；内核 **scale 微呼吸**；外环 dash **中速流动**（暗示「运算中」）。 |
| **proactive_push** | **短促两次**外环 **ember 色脉冲**（总时长 <1.5s），随后回到 listening 基态；**不**循环快速闪，避免焦躁。 |
| **idle**（若有） | 整体压暗 10～15%，外环几乎不可见。 |

**CSS 动效实现要点（构思级）**

- 使用 **`@keyframes`** 分离：**`haloBreathe`**（opacity + shadow spread）、**`corePulse`**（transform scale）、**`orbitDrift`**（rotate 或 stroke-dashoffset）。  
- **性能**：优先 `transform` 与 `opacity`；`blur` 大半径仅用于中层且可考虑 `will-change: transform` **仅在 thinking 期间** 打开，避免全局 GPU 占满。  
- **降级**：`prefers-reduced-motion: reduce` 时关闭旋转与 scale，仅保留 **单色静态光核 + 文案状态**（符合无障碍）。

### 2.4 资源策略

- **默认无外部图片**：纯 CSS + 可选 **内联 SVG「无脸」几何**（仅渐变圆与模糊，无眼嘴路径）。  
- **若未来有品牌 IP 图**：单独 `doudou-mark.png`，仍需 **暗色底 + 小尺寸**，且 **状态动效仍由外层 Halo/Core 承担**，避免静态脸与动态光打架。

### 2.5 与消息列表小头像的关系

- **列表左侧缩略**：**同一视觉 DNA** 的缩小版——仅 **Core + 弱 Halo**，**无外环轨道**（信息密度）；`thinking` 时可用 **单参数 opacity 呼吸** 省略旋转以省性能。  
- **用户侧头像**：保持 **几何首字**或 **极简楔形**，与豆豆的「光核」形成 **材质对比**（字标 vs 光），而非同一套卡通脸。

### 2.6 验收标准（视觉域）

- 任意截图中 **不存在** 可识别为「眼睛+嘴」的面部符号。  
- 深色主题下 **无廉价高饱和塑料球**；光晕 **边缘柔和、层次 ≤3**。  
- `thinking` 状态 **3 米外可辨认「在工作」**，**1 米内不刺眼、不眩晕**。

---

## 第三部分：实施顺序建议（待你点头后执行）

1. **后端**：统一失败出口 → `error_summary` / `error_detail` / `error_code`；历史任务迁移策略（可选：读时清洗）。  
2. **前端 Error 管道**：`ErrorViewModel` 工厂 + Task Rail 消费改造 + Tooltip 组件。  
3. **视觉**：移除具象 SVG 路径；实现「能量核 + 轨道环」DOM/CSS；接入 `prefers-reduced-motion`。  
4. **回归**：人工注入类阿里云 JSON 失败用例，确认主界面 **零 Raw JSON**；动效与性能在低端机抽样。

---

## 第四部分：非目标（本修订轮不做）

- 不讨论具体云厂商 SDK 版本与签名校验细节（仅要求**不直出 Raw**）。  
- 不在本文承诺具体文案标点级字串（由产品句库表驱动即可）。

---

**结语：**  
（一）是**数据契约 + 呈现策略**问题，必须用 **summary / detail 分层** 与 **Rail 专用渲染规则** 根治；（二）是**品牌与情绪设计**问题，必须用 **无脸抽象光核** 替换具象球体。上述方向已在主分支按第三节顺序 **分阶段落地**；若需二次优化（文案库、`prefers-reduced-motion`、诊断包导出等），以 **`docs/AI_HANDOFF_PHASE6.md` §6** 为 backlog 入口。
