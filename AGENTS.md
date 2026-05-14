# AGENTS.md — 仓颉 FOS AI 接手手册

> **所有 AI Agent（Claude、Cursor、Codex 等）进入本仓库前必读。**  
> 权威操作规范，优先级高于任何其他文档。  
> 工作流：`git clone` → 读本文件 → 读 CLAUDE.md → 开始工作

---

## 当前状态（最后更新：2026-05-14）

| 项目 | 状态 |
|------|------|
| 版本 | **v0.5.5** |
| 测试基线 | **502 passed** |
| 前端构建 | **零错误** |
| 单仓库可运行 | **✅ 是** — clone cangjie-fos 即可，无需 AI_Pitch_Coach |
| 详细变更历史 | 见 `CHANGELOG.md` |
| 最后更新 | 2026-05-14 |

> ⚠️ **你接手后完成任何代码改动，必须按本文「文档更新规则」一节更新上面这个表格。**

---

## 这个项目是什么

**仓颉 FOS（融资作战操作系统）** — 帮 VC/FA 管理融资流程的内部工具。

```
cangjie-fos/（本仓库，完全自包含）
├── backend/                FastAPI + SQLite + LangGraph 后端
│   └── src/cangjie_fos/
│       ├── api/routes/     HTTP 路由
│       ├── services/       业务逻辑 + DB 操作
│       ├── engine/         所有核心模块（ASR / LLM评估 / 投资人匹配等，已从 AI_Pitch_Coach 迁入）
│       └── main.py         FastAPI app 入口
├── frontend/               React + TypeScript + Vite 前端
│   └── src/
│       ├── components/     UI 组件（RoadshowWizard / PitchJobHistory 等）
│       └── pages/          ReviewWorkbench / WarRoomMap 等页面
├── tools/                  doctor.py 诊断脚本、build_release_zip.ps1 打包
├── CLAUDE.md               开发规范（测试标准 + 架构约定详细版）
├── AGENTS.md               本文件（AI 接手手册，每次改动后必须更新）
└── CHANGELOG.md            版本历史（每次改动后必须更新）

【AI_Pitch_Coach 说明】
../AI_Pitch_Coach/ 是原始来源仓库，现已归档（只读参考）。
所有运行所需的代码已迁入 engine/ 子包。
克隆 cangjie-fos 无需 AI_Pitch_Coach 即可完整运行和测试。
```

---

## 克隆后第一步：验证环境

```bash
git clone https://github.com/bog5d/cangjie-fos.git   # 只需要这一个仓库
cd cangjie-fos/backend
uv sync --extra dev
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
# 期望：502 passed，0 failed — 不对就停下来先修测试
```

---

## 最近做了什么（v0.5.3 → v0.5.4）

### v0.5.5（2026-05-14）— 单仓库自包含（移除 AI_Pitch_Coach 外部依赖）

- `pyproject.toml` 移除 `testpaths` 中的 `../../AI_Pitch_Coach/tests`
  → clone 单仓库即可跑全部 502 个测试，无需兄弟目录
- `core/paths.py` `ensure_pitch_coach_import_path()` 改为警告而非崩溃
  → AI_Pitch_Coach 不存在时记录日志并返回 None，不影响启动
- `core/readiness.py` AI_Pitch_Coach 缺失从「错误」降级为「静默通过」
  → engine/ 已包含所有核心模块，兄弟目录是可选的历史依赖

### v0.5.4（2026-05-14）— 同事反馈 Bug 修复（13个问题中修复3个）

同事 zt001 测试 v0.5.3 后反馈 13 个问题，完整清单及处理状态如下：

| # | 问题描述 | 状态 | 备注 |
|---|---------|------|------|
| 1 | 录音片段不完整，前后缺 5-10 秒上下文 | ❌ 待处理 | ASR 片段截取逻辑 |
| 2 | 新增风险点缺少"问题简述"字段，只能填改进建议和扣分原因 | ❌ 待处理 | ReviewWorkbench 新增风险点表单 |
| 3 | 尽调响应台匹配不准（营业执照18%）+ 无打包下载功能 | ❌ 待处理 | matchmaker 算法 + 打包 API |
| 4 | 口述实录无法编辑且语序错误 | ❌ 待处理 | ReviewWorkbench 口述实录编辑入口 |
| 5 | 历史记录缺机构名称列 | ✅ v0.5.4 | `PitchJobSummary` 加 `institution_id`，历史列表显示 🏢 机构名 |
| 6 | 报告锁定后无法解锁编辑 | ❌ 待处理 | ReviewWorkbench 解锁按钮 |
| 7 | 删除风险点后总分不重算 | ✅ v0.5.4 | `handleRiskDelete` 补加 `total_score = 100 - Σdeductions` |
| 8 | Pipeline 看板机构卡片无法点开详情/编辑阶段 | ❌ 待处理 | InstitutionList 卡片交互 |
| 9 | Pipeline 漏斗阶段计数无法手动修改 | ❌ 待处理 | 阶段切换下拉菜单 |
| 10 | 资产台账搜索不到已有文件 | ❌ 待处理 | 扫描逻辑 + 重新扫描按钮 |
| 11 | 路演情报报告第5步字段 undefined/空白 | ✅ v0.5.4 | RoadshowWizard TS 接口与 schema 字段名全面对齐 |
| 12 | 路演情报报告无编辑入口 | ❌ 待处理 | RoadshowWizard Step5 或新建编辑页面 |
| 13 | Pipeline 看板机构卡片内容为空（即使有路演记录） | ❌ 待处理 | 卡片数据渲染，与 v0.5.3 CRM打通是不同问题 |

**进度：3/13 已修复，10/13 待处理**

### v0.5.3（2026-05-12）— Chrome 叠层 Bug + 路演数据打通

- Chrome 登录后整页被透明膜覆盖无法点击 → 5 个 Modal 组件 + ExpHud 加 `pointer-events-none`
- 路演完成后 Pipeline CRM 不更新 → `pitch_upload_pipeline.py` 完成后调 `upsert_institution()`
- 引入 Playwright 浏览器烟雾测试（`tests/test_ui_smoke.py`，6 个测试）

---

## ══════════════════════════════════════════
## 文档更新规则（每次 push 前强制执行）
## ══════════════════════════════════════════

> **这是本文件最重要的一节。**  
> 你完成任何代码改动并 push 之前，必须按下列规则更新对应文档。  
> 不更新文档 = 工作未完成。下一个 AI 会因为状态过期而重复踩坑。

---

### 规则 0：判断本次改动的类型

先判断你做了什么，再对号入座执行对应规则：

| 改动类型 | 版本号变化 | 必须更新的文件 |
|---------|-----------|--------------|
| Bug 修复（行为修正，无新功能） | patch +1（0.5.4 → 0.5.5） | AGENTS.md + CHANGELOG.md |
| 新功能上线 | minor +1（0.5.x → 0.6.0） | AGENTS.md + CHANGELOG.md + 同事上手指南.md |
| 纯文档/注释/测试调整 | 不变 | AGENTS.md（仅更新日期和测试基线） |
| 架构重构（接口变化/字段改名） | minor +1 | AGENTS.md + CHANGELOG.md + 关键架构约定表格 |

版本号规则：`v主版本.功能版本.修复版本`，主版本目前锁定为 0。

---

### 规则 1：更新 AGENTS.md 本文件（每次必做）

**第一步：更新顶部「当前状态」表格**

```
修改这个表格中的三个字段：
- 版本：改为新版本号
- 测试基线：改为实际 passed 数（跑完测试后的数字）
- 最后更新日期：改为今天日期（YYYY-MM-DD）
```

示例（修复了一个 bug，测试从 502 → 505）：
```markdown
| 版本 | **v0.5.5** |
| 测试基线 | **505 passed** |
| 最后更新 | 2026-05-20 |
```

**第二步：更新「最近做了什么」区块**

在该区块顶部插入新版本段落，旧版本往下推（保留最近 2 个版本，更早的靠 CHANGELOG.md）。

新版本段落模板：
```markdown
### vX.Y.Z（YYYY-MM-DD）— 一句话说明本次主题

[本次改了什么，用 1-3 条要点说明：现象 → 根因 → 修复文件]

**⏳ 待处理（若有）：**
- 列出已知但本次未处理的问题
```

**第三步：若改动涉及字段名 / 接口名 / 架构约定**

更新「关键架构约定」区块中对应的表格行。  
原则：任何踩过的坑都要记录在这里，防止下一个 AI 重蹈。

---

### 规则 2：更新 CHANGELOG.md（每次必做）

在文件顶部 `## [Unreleased]` 下方插入新版本块。格式严格如下：

```markdown
## [X.Y.Z] — YYYY-MM-DD  本次主题（一句话）

### Fixed（有 bug 修复时填）
- **现象描述**（用户感知角度）
  - 根因：`具体文件:行号区域` — 一句话说根因
  - 修复：做了什么改动

### Added（有新功能时填）
- **功能名称**：一句话描述
  - 新增文件：`路径`
  - 修改文件：`路径`

### Changed
- 测试基线：旧数 → **新数 passed**（+delta）
```

**必须遵守：**
- `Fixed` / `Added` / `Changed` 三个块按需选用，没有就省略，不要留空块
- 根因说明必须包含具体文件路径，不能只说「前端有 bug」
- 测试基线变化必须写，哪怕没变也写「N passed（不变）」

---

### 规则 3：更新同事上手指南.md（新功能上线时才做）

触发条件：新增了用户可见的功能（新按钮、新页面、新流程）。

必须更新的位置：
1. 顶部版本号行 → 改为新版本 + 今天日期
2. 第三节「功能一览」→ 新增功能描述
3. 第四节「怎么测试」→ 新增验收清单（格式：`- [ ] 操作步骤 → 预期结果`）
4. 第五节「已知问题与修复记录」→ 在顶部新增本版修复内容

Bug 修复不需要更新测试验收清单，只在第五节加修复说明。

---

### 规则 4：push 前的最终检查清单

每次 push 之前，在脑中过一遍这个清单，全部 ✓ 才能 push：

```
[ ] 跑过 pytest 且全绿（502+ passed，0 failed）
[ ] 前端有改动时跑过 npm run build（零错误）
[ ] AGENTS.md 顶部「当前状态」表格已更新（版本/测试数/日期）
[ ] AGENTS.md「最近做了什么」已插入本次版本段落
[ ] CHANGELOG.md 已插入新版本块（格式符合规则 2）
[ ] 若有新功能：同事上手指南.md 已更新
[ ] 若有架构/字段名变化：AGENTS.md 架构约定表格已更新
[ ] git add 时只 add 具体文件，没有 git add -A
[ ] commit message 格式正确：type(scope): 描述
```

---

### 规则 5：本次未完成的工作怎么交接

若因 context 不足或任务中断，无法完成所有工作，push 前必须在 AGENTS.md「最近做了什么」段落末尾加：

```markdown
**🚧 本次未完成，下一个 AI 接着做：**
- 具体描述做到哪一步了
- 下一步需要做什么（越具体越好，包括文件路径）
- 已知的障碍或注意事项
```

---

## 关键架构约定（踩过坑的教训）

### RoadshowIntelReport 字段名（v0.5.4 已修正，别再改错）

| 接口/字段 | ❌ 错的（前端曾用过） | ✅ 对的（`engine/schema.py` 权威） |
|---------|-------------------|--------------------------------|
| `key_verbatim_moments` | `KeyVerbatim[]` 对象数组 | `string[]` 纯字符串列表 |
| `IntelQuestion` 字段 | `question / theme / asked_by` | `verbatim / underlying_concern / speaker_id` |
| `IntelSignal` 字段 | `signal / sentiment` | `verbatim / signal_type / interpretation` |
| `IntelAction` 字段 | `owner / deadline` | `actor / action / priority`（无 deadline） |

> 新增报告类型时：**先读 `engine/schema.py` 确认字段名，再写前端接口**，不要凭记忆猜。

### 数据层约定

- `pitch_jobs.institution_id` 存的是**机构名字符串**，不是 UUID（历史命名问题，勿混淆）
- Review API 读 SQLite（`db_job_get`），不读内存 store
- 所有 pipeline 必须同时写内存（`job_update`）和 SQLite（`db_job_update`）
- `engine/schema.py` 是所有报告 schema 的权威来源，前端接口必须与之对齐

---

## 开发铁律

### 改完代码必须跑测试

```bash
cd backend
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
# 502+ passed，0 failed 才算完成
```

### 提交规范

```bash
git pull origin master              # 先拉最新
# ...改代码 + 更新文档（见上方规则）...
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
git add <具体文件列表>              # 禁止 git add -A
git commit -m "fix(scope): 描述"
git push origin master
```

type：`feat` | `fix` | `docs` | `refactor` | `test` | `chore`

### 禁止行为

| 禁止 | 原因 |
|------|------|
| 改完说「应该好了你试试」 | 必须先跑测试证明 |
| push 前不更新 AGENTS.md / CHANGELOG | 下一个 AI 会基于过期状态做出错误判断 |
| `git add -A` 或 `git add .` | 可能提交 `.env`（API Key 泄露） |
| 只 mock 外部服务不验证 DB 写入 | DB 才是审查台的数据源 |
| 新增 pipeline 步骤不同步更新 E2E 测试 | 覆盖缺失 = 没有测试 |
| 新增报告字段时前端凭记忆写接口 | 必须先读 `engine/schema.py` 确认字段名 |

---

## 测试分层速查

| 层级 | 命令 | 覆盖范围 | 前提 |
|------|------|---------|------|
| API + E2E（主力） | `pytest tests/ -q --ignore=tests/test_doctor_script.py` | 全后端逻辑 + DB | 无（全 mock） |
| 浏览器烟雾 | `pytest tests/test_ui_smoke.py -v` | Chrome 渲染 + 点击 | 服务需在 8000 端口运行 |

---

## 关键文件速查

| 文件 | 作用 |
|------|------|
| `CHANGELOG.md` | 版本历史，每次 push 前必须更新 |
| `CLAUDE.md` | 测试标准 + 开发规范详细版 |
| `backend/src/cangjie_fos/engine/schema.py` | **所有报告 schema（字段名权威来源）** |
| `backend/src/cangjie_fos/main.py` | FastAPI app 入口 + lifespan |
| `backend/src/cangjie_fos/services/pitch_upload_pipeline.py` | 上传→ASR→评估主流水线 |
| `backend/src/cangjie_fos/services/pitch_job_db.py` | SQLite 持久化层（单一真相源） |
| `backend/src/cangjie_fos/api/routes/roadshow.py` | 路演分析专属 5 个端点 |
| `frontend/src/components/RoadshowWizard.tsx` | 路演分析 5 步向导（Step5 刚修过） |
| `frontend/src/pages/ReviewWorkbench.tsx` | 全屏审查台 |
| `backend/tests/test_pipeline_e2e.py` | Pipeline 核心 E2E 测试 |
| `backend/tests/test_roadshow_e2e.py` | 路演分析 E2E 测试（17 个） |
