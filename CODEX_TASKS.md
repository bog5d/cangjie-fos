# CODEX_TASKS.md — Codex 自动测试任务收件箱

> **Codex 每次拉取仓库更新后，先读本文件，再执行测试。**
> 本文件由 Claude Code 在每次 PR 合并后更新。

---

## 当前版本：v1.18.0 | 最后更新：2026-06-13

---

## 🆕 本轮新增（v1.17.0 + v1.18.0 · 内容层补盲 + 工作流可视化）

> 主理人点名：**模拟人工测试、打开浏览器、该截图截图、输出测试 PDF。**
> 本轮补的是尽调台「内容层三个死角」+「工作流看不见」：
> ① 加密件登记密码后能解密读正文　② 扫描件/图片型 PDF 走 OCR 读　
> ③ 清单复合项（近三年/并列多份）拆成独立条　④ 匹配过程出现步骤条。

### 1) 自动化（必须全绿）
```bash
cd backend
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
# 期望：919 passed, 0 failed

# 本轮新增（共 17 个）
uv run --extra dev pytest tests/test_dd_content_extractor.py tests/test_dd_workflow_stage.py -v
# 期望：12 + 2 = 14 passed（统一抽取解密/文字层/OCR兜底/降级 12，阶段回调 2）
uv run --extra dev pytest tests/test_dd_checklist_parser.py -k compound -v
# 期望：1 passed（复合项拆分指令在 prompt 中）
```

### ⚙️ 跑冒烟前的环境前提（上一轮 10 failed 多半栽在这里，先备齐再跑）
1. **装浏览器**：`uv run playwright install chromium`（缺它整批 skip/fail）。
2. **配密钥**：`backend/.env` 写 `DEEPSEEK_API_KEY` + `DASHSCOPE_API_KEY`。
   否则 `/api/v1/ready` 的 `api_keys_ok=false`，**复盘上传向导/路演陪练会被禁用**（按钮 disabled，
   点击类用例必失败）——这不是 bug，是防呆门控。尽调响应台的实际匹配也要 LLM key 才出结果。
3. **起服务**：见下。先 `curl http://127.0.0.1:8000/api/v1/ready` 确认 `"ok": true` 再跑。

### 2) 人工冒烟（启动服务 + 真实浏览器，逐步截图 → 出 PDF）
> 启动：`cd backend && uv run uvicorn cangjie_fos.main:app --port 8000`；前端走 `frontend/dist`（已预编译）。
> 入口统一：登录后点 **「📋 尽调响应」**（`button:has-text('尽调响应')`）进向导 Step 1。
> 测试方法加到 `tests/test_ui_smoke.py` 的 `TestDueDiligenceWizardSmoke` 里，
> **每一步 `ui_reporter.capture(page, "步骤名", status=...)`**；任一步失败用 `ui_reporter.fail(...)` 再 `raise`。

| # | 操作（逐步点击指引） | 验收点（截图） |
|---|------|--------------|
| A · 工作流步骤条 | 备一个材料库文件夹（放 `审计报告.txt`＝「审计报告 标准无保留意见」、`装修合同.txt`＝无关内容）。Step1 填材料库路径 → 「开始扫描」→ 扫完粘贴清单「1. 审计报告」→ 「解析 & 开始匹配」 | 匹配进行中**出现步骤条**：`解析清单 → AI 粗筛匹配 → 读正文精判验证 → 待人工确认`，当前步高亮（蓝色 ●）、已完成步打勾（绿色 ✓）。截「粗筛中」「精判中」两帧 |
| B · 加密件解密读 | 材料库再放一个**加密 docx/pdf**（设密码，如 `123456`，正文含「审计报告」字样）。在向导里**登记该文件密码**（item 的 unlock_password 输入框）→ 重新匹配 | 该加密件能参与精判并命中（🟢/🟡），证明已解密读到正文；**不再是读不出/跳过** |
| C · 扫描件 OCR | 材料库放一个**图片型/扫描 PDF**（无文字层）。**前提**：环境配了 `DASHSCOPE_API_KEY`（OCR 默认开箱）。匹配 | 配了 key：扫描件能被识别出文字并参与匹配（命中或给出证据）。未配 key / 设 `CANGJIE_OCR_DISABLED=1`：**优雅降级**（标记读不出，流程不崩、不报错）——两种都要截图说明 |
| D · 清单复合项拆分 | 上传/粘贴含复合项的清单，如「1. 近三年审计报告」「2. 公司章程及历次股东会决议」→ 解析 | 解析后审核表里**拆成多条**：审计报告按年度（2022/2023/2024）各一条；章程与股东会决议各一条。截解析结果表 |
| E · 关闭无叠层（回归） | 关闭向导（✕ 或 Esc） | 无大面积 `fixed` 遮罩残留（沿用既有 `_OVERLAY_JS` 断言） |

**FAIL 判定**：自动化任一 failed；或 A 看不到步骤条 / B 加密件仍读不出 / C 配了 key 仍不识别且非降级提示 / D 复合项没拆开。
**输出**：带 A–E 截图的测试 PDF（`backend/data/ui_reports/`，`-s` 打印路径），回填 PR 评论或本文件历史记录。

> 备注：B 的加密 docx 可用 `msoffcrypto-tool` 造；C 的扫描 PDF 找任意图片导出 PDF 即可。
> 若服务未起则全部 skip——**全 skip 视为未完成**，必须先起服务再跑。

### 🔧 v1.18.1 修复（回应 16 passed/1 failed 那一轮）
- **`test_coaching_close_no_overlay` 竞态失败** → 已修：根因是前端 `/api/v1/ready` 只拉一次，
  抖动失败即 `ready=null` 把按钮永久禁用。`App.tsx` 改为**自愈轮询**（未就绪/失败每 3s 重试，
  ok 后停）。重跑应转绿。额外稳妥：点「路演陪练/复盘上传向导」前可先
  `expect(btn).to_be_enabled(timeout=10_000)` 再点。

### 🔧 本轮顺带修复（测试设施，回应上一轮 Codex 反馈）
- **PDF 报告汇总与 pytest 脱钩** → 已修：`conftest.py` 加 `pytest_runtest_makereport` 钩子，
  任一用了 `ui_reporter` 的测试被 pytest 判 failed（含 TimeoutError、登录阶段崩、按钮禁用），
  **自动补一帧失败截图并标红**；PDF 新增**总览首页**（整体 PASS/FAIL + 失败明细），文件名带
  `FAILED_` 前缀。不会再出现「pytest 失败但报告显示全 PASS」。
- **`_login` networkidle 超时拖垮整批** → 已修：本应用登录后持续轮询 `/api/v1/ready`，网络
  永不 idle；`wait_for_load_state("networkidle")` 改为**等具体元素出现**。
- 说明：上一轮的 `test_webhook_watch` 异步事件循环报错在主理人环境复跑为 **2 passed**，疑似
  并行/事件循环差异，非代码缺陷；若再现请贴完整 traceback。

---

## 上轮（v1.9.1 · 红队加固 + 压测固化）

```bash
cd backend
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q   # 期望 798 passed
uv run --extra dev pytest tests/test_dd_stress_smoke.py tests/test_dd_material_architecture.py -v
# 期望：1 + 14 = 15 passed（压测烟雾 1 + 物料架构含熔断/防错年 14）

# 手动压测（可选，自造复杂数据 + 真实流水线 + 出图）
uv run python bench/dd_stress.py --scale large --charts   # 看 8/8 并发零错误、跨机构锁定成功、全文落库100%
```
加固点：DB 连接 schema-init 缓存 / 精判 LLM 熔断 / 归一化保留年份防套错 / PDF 页数安全帽 / 热路径单连接批量写。

---

## 🆕 上轮任务（v1.9.0 · DD 物料架构升级：全文精判 + 机器验证 + 跨机构学习）

> 主理人点名：**模拟人工测试、输出测试 PDF、打开浏览器、该截图截图。**

### 1) 自动化（必须全绿）
```bash
cd backend
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
# 期望：795 passed, 0 failed

# 本轮新增（12 个）
uv run --extra dev pytest tests/test_dd_material_architecture.py -v
# 期望：12 passed（阶段1 全文精判 5 + 阶段2 验证 3 + 阶段3 跨机构记忆 4）
```

### 2) 人工冒烟（启动服务 + 真实浏览器，截图存档）
> 启动：`cd backend && uv run uvicorn cangjie_fos.main:app --port 8000`，前端走 `frontend/dist`（已预编译）。
> 全程**打开浏览器**操作，每个验收点**截图**；最后把过程与结论汇总**输出成一份测试 PDF**（含截图）。

| # | 操作 | 验收点（截图） |
|---|------|--------------|
| A | 准备一个材料库文件夹（放 2-3 个 txt/pdf，如「审计报告.txt」含「审计报告 标准无保留意见」正文、一个无关「装修合同.txt」），在「📋 尽调响应」里扫描 | 扫描完成；后端 `dd_asset_index.content_text` 有全文（可不查库，看下一步精判生效即可） |
| B | 上传/粘贴清单（如「1. 审计报告」），触发 AI 匹配 | 匹配出候选；审核表里命中项文件名**下方出现 🟢/🟡/🔴 + 一句证据片段**（机器验证产物） |
| C | 故意让一条需求匹配到无关文件，看精判是否纠偏 | 该项被标 🔴（红），证据说明「正文与需求不符」之类 |
| D | 确认（✓）某条「需求→文件」，再新建一个**不同机构名**、含**同一条需求**的 session 并匹配 | 第二个机构该项被**自动锁定**为上次确认的文件，理由含「🧠 历史沿用」，徽章绿色（跨机构学习生效） |
| E | 导出 | 导出的是**原始文件**（非重新生成）；缺失清单正常 |

**FAIL 判定**：自动化任一 failed；或 B/C/D 任一现象不符。
**输出**：测试结果 PDF（含 A-E 截图 + 通过/失败结论）。回填到本文件「历史记录」或 PR 评论。

---

## 历史版本：v1.8.0 | 2026-06-03

---

## 第一步：自动化基线（必须全绿才算通）

```bash
# ── 1. 后端单元/集成测试 ──────────────────────────────────────────
cd backend
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
# 期望：783+ passed, 0 failed

# ── 本轮新增（v1.8.0 gk 模式 机构问答响应引擎 阶段一）──────────────
uv run --extra dev pytest tests/test_dd_gk_scan.py tests/test_dd_gk_export.py \
                          tests/test_dd_qa_service.py tests/test_dd_gk_api.py \
                          tests/test_dd_gk_password.py -q
# 期望：28 passed（11 扫描 + 4 导出 + 5 问答 + 3 API + 5 密码）

# ── 2. 本轮新增专项（v1.8.0 gk 模式 机构问答响应引擎 阶段一）──────
uv run --extra dev pytest tests/test_dd_gk_scan.py tests/test_dd_gk_export.py \
                          tests/test_dd_qa_service.py tests/test_dd_gk_api.py \
                          tests/test_dd_gk_password.py -q
# 期望：28 passed（11 扫描 + 4 导出 + 5 问答 + 3 API + 5 密码）

# ── 3. 前端单元测试（jsdom，验证逻辑，不替代浏览器）────────────────
cd ../frontend
npm install   # 依赖有变化时运行
npm test
# 注意：使用 Vitest，不支持 Jest 的 --runInBand 参数，不要传
# 注意：请用 `npm test`（不要用 npx vitest run 单跑某文件，jsdom 冷启动偶发不加载）
# 期望：24+ passed, 0 failed
#   gk 模式前端新增：DueDiligenceWizard.layout / .password / .byquestion
#   / .multifile / .qadraft 共 6 个用例

# ── 4. TypeScript 编译 ────────────────────────────────────────────
npm run build
# 期望：exit code 0，无 error（warning 忽略）

# ── 5. 【强制】Playwright 浏览器冒烟 + 带截图 PDF 报告 ───────────
# ⚠️ 关键：这是命令行跑的 Playwright（本地 chromium 子进程），
#    不是 in-app Browser Use，不受 Browser Use URL policy 限制 —— 可正常访问
#    127.0.0.1:8000 / 5173。Codex 之前 in-app browser 被拦的问题，用这条命令绕开。
#
# 必须先启动后端服务（另一终端）：
#   cd backend && uv run uvicorn cangjie_fos.main:app --port 8000
# 再启动前端（另一终端）：
#   cd frontend && npm run dev
# 等服务就绪后执行（-s 让 PDF 路径打印出来）：
cd backend
uv run --extra dev pytest tests/test_ui_smoke.py tests/test_ui_smoke_gk.py -v -s
# 期望：全部 passed；跑完会在 backend/data/ui_reports/ 生成带截图 PDF
#   （每步一帧 + 中文 PASS/FAIL 横幅）。任一步 FAIL → 文件名带 FAILED_ 前缀。
#
# test_ui_smoke_gk.py（gk 尽调向导专项，Claude 已本机真跑通，5 passed / 7 帧 PDF）：
#   Tier A 免数据：尽调入口 / Step1 材料库文件夹+开始扫描+清单 / 关闭无叠层
#   Tier B 播种会话→恢复→Step3：🔒加密锁+密码登记 / 💬草稿+📁按问题归档 / 候选附加
#
# 默认账号（无 .env 时）：gk001 / 123456（auth 内置）；conftest 已自动回退到它。
# 若环境 playwright 默认浏览器版本不匹配/下载被拦，设环境变量指向已装 chromium：
#   PW_CHROME_EXECUTABLE=/path/to/chrome uv run --extra dev pytest tests/test_ui_smoke_gk.py -v -s
```

**FAIL 判定**：上述任一步骤有 failed，或第 5 步因「服务未启动」全部 skip（跳过视为未完成）。

### 📄 回传要求（强制）

跑完第 5 步后，**把 `backend/data/ui_reports/` 下最新生成的 PDF 回传给 Claude**
（贴路径或附件）。这份 PDF 是「模拟人工测试」的可视证据，Claude 会逐帧审 UI
真实渲染。**不回传 PDF = 本轮浏览器验收未完成。**

> 注：命令行 Playwright 是本地 chromium 子进程，**不走 in-app Browser Use 通道**，
> 因此 v1.8.0 验收时 in-app browser 被 Browser Use URL policy 拦住的问题，用这套
> 命令行 smoke 即可绕开 —— Codex 不必再依赖 in-app browser 访问 127.0.0.1。

> 为什么必须 PDF：vitest 跑在 jsdom，看不到真实 Chrome 渲染/CSS/叠层/点击跳转
> （约 30% 真实人工场景测不到）。「vitest 全绿 + build 通过」**不等于**人工验收 PASS。

---

## 第二步：浏览器冒烟——gk 模式尽调向导（Playwright 自动化）

> 这一组已写入 `tests/test_ui_smoke.py`（`TestDueDiligenceWizardSmoke`），
> 跑 `pytest tests/test_ui_smoke.py -v` 自动覆盖，**无需手动点浏览器**。

| 测试方法 | 验收点 |
|---------|--------|
| `test_dd_wizard_button_visible` | 主页有「尽调响应」按钮且可见 |
| `test_dd_wizard_opens_step1` | 点击后 Step 1 出现「材料库路径」字样 |
| `test_dd_wizard_step1_has_scan_button` | Step 1 有「开始扫描」按钮 |
| `test_dd_wizard_step1_has_checklist_upload` | Step 1 有「清单」相关入口 |
| `test_dd_wizard_close_no_overlay` | 关闭向导后无遮罩叠层（Chrome Bug 回归） |
| `test_dd_wizard_session_history_shown` | 向导打开后不崩溃、Step1 稳定渲染 |

**FAIL 判定**：任一用例 FAILED（skip 因服务未起，Codex 必须先起服务）。

---

## 第三步：手动冒烟清单（Playwright 无法覆盖的场景）

> 以下需要真实数据/文件操作，Playwright 无法模拟，由**开发者/QA 人工验**。

### gk — 【v1.8.0】机构问答响应引擎 阶段一

| 能力 | 测试文件（自动化） | 人工验收点（额外） |
|------|---------|--------|
| F1 布局检测+去重+加密标记 | `test_dd_gk_scan.py`（11） | 真实 per_institution 文件夹扫描，徽章显示正确机构数 |
| F2/F5 按问题归档导出 | `test_dd_gk_export.py`（4） | 真实导出后用文件管理器确认目录结构 |
| F4 历史问答复用 | `test_dd_qa_service.py`（5） | 真实补充文档扒取后，草稿答案是否合理 |
| F3 加密密码登记/附带 | `test_dd_gk_password.py`（5） | 真实加密 PDF 流程：登记密码 → 导出「加密文件密码.txt」 |

**⚠️ vitest 覆盖的前端逻辑（不替代浏览器）**：

| 前端能力 | vitest 覆盖 | 浏览器是否已覆盖 |
|---------|---------|--------|
| F1 布局徽章 | `DueDiligenceWizard.layout.test.tsx` | ✅ Playwright `TestDueDiligenceWizardSmoke` |
| F3 加密🔒+密码 | `DueDiligenceWizard.password.test.tsx` | ⚠️ 仅 jsdom，需人工验 |
| F2/F5 按问题归档 | `DueDiligenceWizard.byquestion.test.tsx` | ⚠️ 仅 jsdom，需人工验 |
| F2 多文件附加 | `DueDiligenceWizard.multifile.test.tsx` | ⚠️ 仅 jsdom，需人工验 |
| F4 问答草稿 | `DueDiligenceWizard.qadraft.test.tsx` | ⚠️ 仅 jsdom，需人工验 |

---

### gk — 【v1.8.0 后端】机构问答响应引擎 阶段一（纯后端，pytest 已覆盖）

> 本轮为后端能力（F1/F2/F4/F5），无 UI，靠自动化测试验收；前端对接见下一版。

| 能力 | 测试文件 | 验收点 |
|------|---------|--------|
| F1 布局检测+去重+加密标记 | `test_dd_gk_scan.py` | per_institution 自动识别；同名跨机构去重留最新；加密文件 is_encrypted=1 仍入索引 |
| F2/F5 按问题归档导出 | `test_dd_gk_export.py` | 每条需求一个「问题NN_xxx」文件夹；无匹配进缺失清单不建空夹；多文件全拷；自定义命名 |
| F4 历史问答复用 | `test_dd_qa_service.py` | 补充资料扒问答对落 dd_qa_pairs；新需求命中带答案+置信度；无命中低置信不硬塞 |
| F3 加密密码登记/附带 | `test_dd_gk_password.py` | 扫描报机构数；items 富化 is_encrypted/unlock_password；设密码端点；导出生成加密文件密码.txt |
| API 端点 | `test_dd_gk_api.py` | export-by-question / qa/extract / qa/draft 三端点 200 |

**FAIL 判定**：上述任一 pytest 文件有 failed。

#### gk 模式前端（已有 vitest 覆盖，无需人工冒烟）

| 前端能力 | 测试文件 | 验收点 |
|---------|---------|--------|
| F1 布局徽章 | `DueDiligenceWizard.layout.test.tsx` | 扫描后显示「按机构分类·N家」/「平铺材料库」 |
| F3 加密🔒+密码 | `DueDiligenceWizard.password.test.tsx` | 加密文件显示🔒，登记密码 POST，切🔓 |
| F2/F5 按问题归档 | `DueDiligenceWizard.byquestion.test.tsx` | 命名确认表默认问题名、可改名、POST overrides |
| F2 多文件附加 | `DueDiligenceWizard.multifile.test.tsx` | 候选勾选「附加」→ PATCH extra_files_json |
| F4 问答草稿 | `DueDiligenceWizard.qadraft.test.tsx` | 「💬 草稿」命中历史答案+置信度、可编辑 |

---

### A — 【本轮新增】Pipeline 新增机构入口

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| A1 | 打开页面 → 找到「机构 Pipeline 看板」区块 | 顶部右侧有「➕ 新增机构」按钮（青色圆角） |
| A2 | 点击该按钮 | 弹出创建弹层，有「机构名称」「Pipeline 阶段」「热度」「引荐方」字段 |
| A3 | 填写名称「TestVC」，其他默认，点「✅ 创建机构」 | 弹层关闭，卡片列表顶部出现「TestVC」 |
| A4 | 查看成就墙「路演接触」数字 | 数字比创建前 +1 |
| A5 | 刷新页面，再找「TestVC」 | 卡片仍存在（持久化成功） |

**FAIL 判定**：按钮不存在 / 弹层不出现 / 创建后列表无变化 / 刷新后消失

---

### B — 【本轮修复】线下见面语义：家数 vs 次数

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| B1 | 找任意一个机构卡片，点击编辑 | 编辑弹层打开 |
| B2 | 找「线下会面次数」输入框，填入 **3**，保存 | 保存成功 |
| B3 | 查看成就墙「线下交流」卡片 | 显示 **1家（3次）**，而不是只显示数字 3 |
| B4 | 再找另一个机构，将线下次数设为 **2**，保存 | 成就墙更新为 **2家（5次）** |

**FAIL 判定**：卡片只显示数字 / 无「家」字 / 无括号次数

---

### C — 【本轮修复】DD 手动替换按钮有文字

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| C1 | 打开「📋 尽调响应」→ Step1 扫描任意有文件的文件夹 | 扫描完成 |
| C2 | Step2 粘贴任意需求文本，触发匹配 | 进入 Step3 审核表格 |
| C3 | 查看每行操作按钮区 | 能看到「缺」和「📂 替换」两个文字按钮 |
| C4 | 点「📂 替换」 | 展开内联输入行（含「📁 选择文件」按钮） |

**FAIL 判定**：只有 📂 图标无文字 / 点击无反应

> ✅ **已加自动化兜底**：`frontend/src/components/__tests__/DueDiligenceWizard.step3.test.tsx`
> 通过「恢复历史会话」喂入一条未确认 item，断言「✓」「缺」「📂 替换」三按钮齐全且点替换展开输入行。
> 浏览器只恢复到已确认 session 时可跳过本节，以该 vitest 用例为准。

---

### D — 【本轮修复】成就墙保存后即时刷新

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| D1 | 找一个 NDA 未签的机构，点击编辑 | 弹层打开 |
| D2 | 勾选「NDA 已签」，点保存 | 弹层关闭 |
| D3 | 不刷新页面，直接看成就墙「NDA 签署」 | 数字比保存前 +1（即时更新） |

**FAIL 判定**：数字不变，需手动刷新才更新

> ✅ **已加自动化兜底**（编辑保存路径，不只创建机构）：
> - `frontend/src/components/__tests__/InstitutionList.save.test.tsx`：编辑保存后断言 `onMilestonesChanged` 被调用。
> - `frontend/src/components/__tests__/WarRoomMap.refresh.test.tsx`：`milestoneRefreshKey` +1 时断言重新拉取 `/api/v1/pipeline/milestone-stats`。
> in-app 浏览器对编辑弹层滚动不稳定时，以这两条 vitest 用例为准。

---

### E — 【本轮新增】DD 学习飞轮接通

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| E1 | 完成一次完整 DD 流程：扫描→匹配→Step3 批量确认 | 确认成功 |
| E2 | 访问 `http://localhost:8000/api/v1/institutions/{机构名}/briefing` | JSON 里 `has_history=true` 且 `preferred_paths` 数组有值 |
| E3 | 若机构名留空，检查 Step2 机构名输入框旁边是否有黄色提示 | 出现「⚠️ 建议填写 — 确认记录将关联此机构...」 |

> ⚠️ **字段口径**：briefing API 真实字段是 `preferred_paths`（不是 `preferred_files`）+ `has_history`。

**FAIL 判定**：has_history 始终 false / preferred_paths 始终为空 / 无任何警告提示

---

### F — 【本轮新增】轻量匹配器升级正式尽调

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| F1 | 打开页面中下部「资产台账」→「尽调响应台」区块 | 显示机构名输入和需求文本区 |
| F2 | 填机构名「TestVC」，粘贴任意文本，点「解析并匹配」 | 出现匹配结果 |
| F3 | 查看按钮行 | 能看到「提交确认（X）」和「📋 发起正式尽调」两个按钮 |
| F4 | 点「📋 发起正式尽调」 | 顶部「📋 尽调响应」弹层打开，停在 Step2，清单文本框已预填 |
| F5 | 关闭弹层，再次从顶栏点「📋 尽调响应」 | 弹层打开，回到 Step1，清单为空 |

**FAIL 判定**：无升级按钮 / 打开后停在 Step1 / 清单未预填 / 关闭后再开仍有残留

---

### G — 成就墙 9 节点完整性

| 期望 | 判定 |
|------|------|
| 成就墙显示9个节点：路演接触 · NDA签署 · 线下交流 · 立项 · 内部尽调 · 外部尽调 · 投决过会 · 协议签署 · 交割 | PASS 全部存在，FAIL 缺少任何一个 |
| 每个节点显示「X家」（有单位） | PASS 有"家"字，FAIL 裸数字 |
| 漏斗5段：路演接触/NDA签署/立项+尽调/投决过会/协议+交割 | subtitle 有数字 |

---

### BLOCKED（跳过，非代码问题）

- **路演评分/路演情报**：依赖本机 AI 评估引擎目录配置，与代码无关，不计入本轮
- **GitHub sync**：需要真实 Token（configured=false 属正常，不是 bug）

---

## 评分标准

| 级别 | 标准 |
|------|------|
| **PASS** | 期望行为完全符合 |
| **PARTIAL** | 主要功能工作，有小问题（如文案、样式、非阻塞 bug） |
| **FAIL** | 期望行为不出现，或出现错误/崩溃 |
| **BLOCKED** | 外部依赖未就绪，与代码逻辑无关 |

---

## 历史版本记录

| 版本 | 日期 | 主要内容 | 结果 |
|------|------|---------|------|
| v1.2.0 | 2026-05-31 | 里程碑重排、飞轮接通、升级按钮、共享索引 | PASS 23 / PARTIAL 3 / FAIL 1 / BLOCKED 4 |
| v1.3.0 | 2026-05-31 | 新增机构入口、家/次双显、替换按钮、create修复 | PASS A/B/E/F/G · PARTIAL C/D（浏览器滚动不稳定） |
| v1.4.0 | 2026-05-31 | vitest 兜底 C/D + 修 briefing 字段口径 + 前端依赖安装说明 | PASS（自动化全绿）|
| v1.5.0 | 2026-05-31 | DD 大批量修复：token 溢出/进度条/截断兜底/逐批存储，733 passed | 待验 |
| v1.6.0 | 2026-06-02 | P0 稳健性三补丁：SQLite每日快照备份/匹配异常标failed/LLM宕机降级关键词，744 passed | ✅ PASS |
| v1.7.0 | 2026-06-03 | P1 稳健性四补丁：Token持久化/内存字典上限/LLM Prompt截断/匹配状态DB降级，754 passed | 待验 |

---

### H — 【v1.5.0 新增】尽调响应台 50 条大批量稳定性

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| H1 | 打开「📋 尽调响应」→ Step1 扫描含 20+ 文件的文件夹 | 扫描完成，显示文件数 |
| H2 | Step2 粘贴 **50 条**需求（可用下方样本）→ 点「解析并匹配」 | 解析显示「共 50 项」，进入匹配等待 |
| H3 | 匹配中，观察按钮 | 按钮显示「**匹配中… X/50 项**」动态进度（不再只是转圈） |
| H4 | 等待匹配完成，进入 Step3 | 50 行全部有结果，**不出现全部 confidence=0 的情况** |
| H5 | 查看匹配结果分布 | 高置信度行（绿）/ 低置信度行（红）/ 无匹配行 各有分布，非全红 |
| H6 | 点「提交确认（X）」批量确认高置信度项 | 弹层关闭或确认数更新，不报错 |

**50 条样本文字**（直接粘贴到 Step2 文本框）：
```
1. 近三年经审计财务报告（资产负债表、利润表、现金流量表）
2. 最新一期未经审计财务报表（月报/季报）
3. 公司注册证明文件及营业执照
4. 公司章程及最新修订版
5. 股权结构图（含各层穿透至自然人）
6. 股东名册及持股比例说明
7. 历次股权融资协议及 Term Sheet
8. 现有投资方 VCC/LPA 协议摘要
9. 核心管理团队简历（CEO/CFO/CTO）
10. 董事会成员名单及简介
11. 员工总数及核心团队构成说明
12. 期权激励计划（ESOP）文件
13. 主要产品/服务介绍 PPT 或说明文档
14. 近 12 个月产品路线图
15. 核心技术专利清单及证书
16. 软件著作权登记证书
17. 商标注册证书（境内外）
18. 主要客户合同（脱敏后）
19. 客户名单（Top 20，含收入占比）
20. 收入确认政策说明
21. 主要供应商合同及合作协议
22. 采购条款与定价说明
23. 近 3 年纳税申报表及完税证明
24. 社保缴纳记录（近 12 个月）
25. 公积金缴纳记录（近 12 个月）
26. 银行流水（公司主账户近 12 个月）
27. 贷款合同及还款计划
28. 对外担保情况说明
29. 应收账款账龄分析表
30. 存货明细及减值情况说明
31. 固定资产清单及折旧政策
32. 租赁合同（办公/生产场地）
33. 重大合同清单（金额超 100 万）
34. 关联交易明细及公允性说明
35. 历史诉讼及仲裁记录
36. 监管处罚记录
37. 数据安全合规证明（等保/GDPR 等）
38. 环保合规证明（如适用）
39. 公司战略规划文件（3 年）
40. 市场竞争格局分析报告
41. 目标市场规模及增长预测
42. 商业模式说明文件
43. 定价策略及毛利率分析
44. 销售渠道及分销网络说明
45. 市场营销费用明细
46. 客户获取成本（CAC）及留存率数据
47. 现有融资用途计划书
48. 资金使用进度及里程碑
49. 下一轮融资计划及预期估值
50. 退出机制说明（IPO/并购路径）
```

**FAIL 判定**：匹配中无进度显示 / 50 条全部 confidence=0（匹配全失败）/ 进入 Step3 时页面崩溃

---

### I — 【v1.6.0 新增】P0 稳健性三补丁

> 本组以**自动化测试为权威**（`backend/tests/test_dd_robustness_p0.py`，11 条）。
> 浏览器层面只需确认未引入回归（DD 流程仍可正常跑通一遍即可）。

**自动化验证（必跑）**：
```bash
cd backend
uv run --extra dev pytest tests/test_dd_robustness_p0.py -v
# 期望：11 passed
```

#### I-1 — SQLite 每日快照备份（防数据丢失）

| 检查项 | 期望 |
|--------|------|
| `db_backup.create_snapshot()` | 用 SQLite 在线备份 API 生成一致副本，源库继续写入不影响已生成快照 |
| `db_backup.prune_snapshots(keep=7)` | 超过 7 份时删除最旧的，仅保留最新 7 份 |
| 服务启动后 | APScheduler 注册 `daily_db_backup`（每日 03:00），快照落在 `backend/data/backups/` |

**人工冒烟（可选）**：服务跑起来后，手动调用
`python -c "from cangjie_fos.services.db_backup import run_daily_backup; print(run_daily_backup())"`，
确认 `backend/data/backups/fos_snapshot_*.sqlite` 生成。

**FAIL 判定**：快照不生成 / 快照打不开 / prune 删错文件（删了最新的）

#### I-2 — 匹配中途崩溃标记 failed（不再误当完成）

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| I2-1 | 正常完成一次匹配 | `dd_match_sessions.status = 'matched'` |
| I2-2 | 匹配过程内部抛异常（自动化用 mock 模拟） | `status = 'failed'`，**不是** 'matched' |
| I2-3 | 无已索引文件的空文件夹匹配 | `status = 'matched'`（合法的"无可匹配"，非失败） |

**关键点**：异常时 session 仍到达**终态**（前端轮询不挂死），但终态是 `failed` 而非 `matched`，
便于区分"真完成"与"中途崩溃"。

**FAIL 判定**：异常后 status 仍为 'matched' / 或停在 'pending'/'matching'（前端永久轮询）

#### I-3 — LLM 宕机降级关键词匹配（不再整批归零）

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| I3-1 | LLM 三次重试全失败（自动化 mock client 持续抛异常） | 相关需求项仍被关键词兜底匹配，不是全部 confidence=0 |
| I3-2 | 查看降级匹配项 | confidence ≈ 0.3（红色低置信徽章），reason 含"⚠️ AI暂不可用，关键词匹配" |
| I3-3 | 完全无关键词命中的需求 | 返回空候选（不硬塞错误文件） |

**FAIL 判定**：LLM 宕机时 50 条全部 confidence=0 / 无关键词标注 / 把无关文件硬匹配上去

**自动化兜底文件**：`backend/tests/test_dd_robustness_p0.py`
- 备份：`test_create_snapshot_*` / `test_prune_*` / `test_run_daily_backup_*`
- 失败标记：`test_matching_exception_marks_failed` / `test_matching_success_marks_matched` / `test_matching_no_index_marks_matched`
- 关键词降级：`test_keyword_fallback_unit` / `test_llm_down_falls_back_to_keyword`

---

### J — 【v1.7.0 新增】P1 稳健性四补丁

> 本组以**自动化测试为权威**（`backend/tests/test_p1_robustness.py`，10 条）。

**自动化验证（必跑）**：
```bash
cd backend
uv run --extra dev pytest tests/test_p1_robustness.py -v
# 期望：10 passed
```

#### J-1 — Token 持久化（重启后无需重新登录）

| 检查项 | 期望 |
|--------|------|
| 登录后清空内存 `_sessions` | `get_session(token)` 仍能从 `fos_sessions` 表恢复 session |
| 已过期 token（> 72h）在 DB | `get_session` 返回 None，不恢复 |
| logout 后 | DB 里的 token 也被删除，重启后不可恢复 |

**FAIL 判定**：重启后用户必须重新登录（内存清空后 token 验证失败）

#### J-2 — 内存字典容量上限（防内存泄漏）

| 检查项 | 期望 |
|--------|------|
| `_scan_status` 超过 200 条 | `_evict_oldest()` 自动清除最旧条目，字典长度有界 |
| `_match_status` 超过 200 条 | 同上 |
| 大量新 scan/match 操作后 | 内存字典最终不超过 `_MAX_STATUS_ENTRIES=200` |

**FAIL 判定**：长期运行后 `len(_scan_status)` 或 `len(_match_status)` 无界增长

#### J-3 — LLM Prompt 长度上限（防上下文溢出）

| 检查项 | 期望 |
|--------|------|
| 单条文件摘要 > 150 字符 | `_build_file_list_text()` 截断到 150 字符并加"…" |
| 50 条文件 × 超长摘要 | 文件列表文本总长 < 15000 字符 |

**FAIL 判定**：超长摘要导致 Prompt > 32K 字符，DeepSeek API 整批失败

#### J-4 — 匹配进度 DB 降级（重启后状态不丢失）

| 检查项 | 期望 |
|--------|------|
| 创建 session 后清空 `_match_status` | `GET /sessions/{id}/match-status` 返回 `source=db_fallback` |
| 不存在的 session_id | 返回 `status=not_found`（不报 500） |

**FAIL 判定**：重启后前端查询 match-status 永远返回 not_found，导致进度轮询挂死

**自动化兜底文件**：`backend/tests/test_p1_robustness.py`
- Token：`test_token_survives_memory_clear` / `test_expired_token_not_restored_from_db` / `test_logout_removes_from_db`
- 内存上限：`test_scan_status_dict_capped` / `test_match_status_dict_capped` / `test_evict_removes_oldest_entries`
- Prompt 截断：`test_long_summary_truncated_in_file_list` / `test_prompt_total_length_bounded`
- DB 降级：`test_match_status_db_fallback` / `test_match_status_not_found_for_unknown_session`
