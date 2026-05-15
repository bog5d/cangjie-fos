# AGENTS.md — 仓颉 FOS AI 接手手册

> **所有 AI Agent（Claude、Cursor、Codex、Hermes 等）进入本仓库前必读。**
> 权威操作规范，优先级高于任何其他文档。
> 工作流：`git clone` → 读本文件 → 读 CLAUDE.md → 开始工作

---

## 项目结构（最重要：单仓库，无外部依赖）

cangjie-fos/（GitHub: bog5d/cangjie-fos）
  backend/src/cangjie_fos/     ← FastAPI + SQLite + LangGraph
  backend/src/cangjie_fos/engine/  ← 分析引擎（已内置，不是外部库）
  frontend/src/                ← React + TypeScript + Vite

**重要纠正**：老文档里有"需要 AI_Pitch_Coach 外部仓库"的描述，那是 v0.5.4 之前的历史。从 v0.5.5 开始，引擎代码已经全部迁入 engine/ 子包，**单仓库 clone 就完整**，不需要任何外部依赖。

---

## 当前状态（v0.6.8，2026-05-15）

| 项目 | 状态 |
|------|------|
| 版本 | **v0.6.8** |
| 测试基线 | **605 passed**，0 skipped，0 failed |
| 前端 | 已预编译在 `frontend/dist/`，后端启动时自动 serve |
| 启动命令 | `cd backend && uv run uvicorn cangjie_fos.main:app --reload --port 8000` |
| 测试命令 | `cd backend && uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q` |
| DB fixture | `_isolate_db_per_test` autouse：每测试独立 SQLite。用 `@pytest.mark.real_db` 声明豁免 |
| Push hook | `.git/hooks/pre-push` 自动跑 DB fixture 测试 |

---

## v0.6.0 刚做完的事（你拿到的仓库已包含这些）

同事（zt001）反馈了13个问题，已修其中10个。v0.6.0 修了7个，v0.6.1 修了1个：

| 改了哪里 | 做了什么 |
|---------|---------|
| frontend/.../AddRiskPointForm.tsx | 新增风险点时有「问题简述」输入框（problem_summary 字段） |
| frontend/.../RiskPointCard.tsx | 风险点卡片显示「口述实录」原文，非锁定状态可编辑 |
| backend/api/routes/pitch.py | 新增 DELETE /api/v1/pitch/jobs/{job_id}/review-lock 解锁端点 |
| frontend/.../WorkbenchHeader.tsx | 报告锁定后显示「🔓 解锁编辑」按钮 |
| frontend/.../ReviewWorkbench.tsx | handleCommit 接受 reportOverride 参数，路演报告也能保存 |
| backend/schemas/institution.py | 新增 InstitutionProfileUpdate schema |
| backend/services/institution_store.py | 新增 update_institution() 函数 |
| backend/api/routes/pipeline.py | 新增 PATCH /api/v1/pipeline/institutions/{id} |
| frontend/.../InstitutionList.tsx | 完全重写：卡片可点击，弹出编辑 Modal，支持画像/疑虑/偏好/阶段编辑，空卡片有提示文字 |
| frontend/.../RoadshowIntelView.tsx | 新增「✏️ 编辑摘要」按钮，atmosphere_summary / hidden_concerns / institution_update 可编辑保存 |
| 安装并启动.ps1 | 启动失败自动在桌面生成「诊断报告_请发给AI_时间戳.txt」 |
| v0.5.5 | 移除 AI_Pitch_Coach 外部依赖 → 单仓库自包含 |
| v0.6.1 | Bug #1 修复：录音片段不完整 — `_map_aliyun_paraformer_to_schema` 缺词级时间戳时用句子级兜底，不再静默丢弃整句 |

**13个问题全貌：**

| # | 问题描述 | 状态 | 版本 |
|---|---------|------|------|
| 1 | 录音片段不完整（ASR 截取有误） | ✅ 已修复 | v0.6.1 |
| 2 | 新增风险点缺「问题简述」字段 | ✅ 已修复 | v0.6.0 |
| 3 | 尽调匹配不准 + 缺打包下载功能 | ✅ 已修复 | v0.6.3 |
| 4 | 口述实录不可编辑 | ✅ 已修复 | v0.6.0 |
| 5 | 历史记录缺机构名 | ✅ 已修复 | v0.5.4 |
| 6 | 锁定后无法解锁编辑 | ✅ 已修复 | v0.6.0 |
| 7 | 删除风险点总分不变 | ✅ 已修复 | v0.5.4 |
| 8 | Pipeline卡片不可编辑 | ✅ 已修复 | v0.6.0 |
| 9 | Pipeline阶段不可手动改 | ✅ 已修复 | v0.6.0 |
| 10 | 资产台账搜索不到内容 | ✅ 已修复 | v0.6.3 |
| 11 | 路演报告Step5 undefined | ✅ 已修复 | v0.5.4 |
| 12 | 路演情报报告无编辑入口 | ✅ 已修复 | v0.6.0 |
| 13 | Pipeline卡片内容为空 | ✅ 已修复 | v0.6.0 |

**13/13 全部已修复** 🎉

---

## v0.6.8 刚做的事（2026-05-15）

| 改了哪里 | 做了什么 |
|---------|---------|
| `core/paths.py` | 新增 `get_audio_dir()`，支持 `CANGJIE_AUDIO_DIR` 环境变量，测试可隔离音频目录 |
| 5 个文件 | 7 处硬编码 `get_backend_root()/"data"/"audio"` → `get_audio_dir()` |
| `tests/conftest.py` | `_isolate_db_per_test` autouse：每测试独立 SQLite；用 `@pytest.mark.real_db` 声明豁免 |
| 5 个测试文件 | 加 `pytestmark = [pytest.mark.real_db]`（替代中央豁免列表） |
| `_evaluation.py` | 6 个裸 `except Exception` 收敛；`report_builder.py` 4 个 |
| `.git/hooks/pre-push` | 自动跑 DB fixture 测试，防止 scope mismatch 打红 |
| `CHANGELOG.md` | 补 v0.6.6 / v0.6.7 / v0.6.8 三版条目 |
| `test_p1b_html_report_service.py` | 移除 2 个 skip，补齐 mock 链，修跨平台路径 |

测试基线：**605 passed，0 skipped，0 failed**

---

## 不能推翻的架构约定

- `pitch_jobs.institution_id` 存的是**机构名字符串**，不是 UUID（历史遗留命名，不要改）
- Review API 只读 SQLite（`db_job_get`），不读内存 store
- 所有 pipeline 步骤必须同时写内存（`job_update`）和 SQLite（`db_job_update`）
- 字段名权威来源：`backend/src/cangjie_fos/engine/schema.py`，前端 TS 接口必须与之对齐
- `RoadshowIntelReport.key_verbatim_moments` 是 `List[str]`，不是对象列表

### RoadshowIntelReport 字段名对照（踩坑备忘）

| 接口 | ❌ 错的 | ✅ 对的 |
|------|--------|--------|
| key_verbatim_moments | KeyVerbatim[] 对象数组 | string[] 纯字符串列表 |
| IntelQuestion 字段 | question / theme / asked_by | verbatim / underlying_concern / speaker_id |
| IntelSignal 字段 | signal / sentiment | verbatim / signal_type / interpretation |
| IntelAction 字段 | owner / deadline | actor / action / priority（无 deadline） |

---

## 改代码的铁律

- 改完必须先跑 `pytest tests/ -q --ignore=tests/test_doctor_script.py` 全绿再报告，不说「应该好了你去试」
- 新增后端 API → 必须同步写对应测试（200正常流 + 404异常 + 字段结构）
- 新增全屏 Modal/Wizard → 必须配套 `tests/test_ui_smoke.py` 浏览器测试（无叠层断言）
- 缺包用 `uv add <package>`，不用 pip；新增依赖后重启 uvicorn

### 提交规范

```bash
git pull origin master              # 先拉最新
# ...改代码 + 更新本文档 + 更新 CHANGELOG.md ...
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q  # 必须全绿
git add <具体文件列表>              # 禁止 git add -A
git commit -m "type(scope): 描述"
git push origin master
```

type：`feat` | `fix` | `docs` | `refactor` | `test` | `chore`

---

## 多 AI 协作规范（多人同时开发时强制执行）

> 本仓库允许多个 AI 并行开发，以下规则防止互相踩坑。

### ❌ 绝对禁止：用 `@pytest.mark.skip` 当垃圾桶

**错误做法**：测试写了一半跑不通，加个 `@pytest.mark.skip` 先提交。  
**正确做法**：要么测试写完跑通再提交；要么完全不提交该测试文件。

- `@pytest.mark.skip` 只允许用于**已知的、有 GitHub Issue 追踪的外部限制**（如"需要真实 ASR 服务"）
- commit message 里写了 `X passed, Y skipped`，Y > 0 必须在 AGENTS.md 「待处理」节说明原因
- **绝不允许**：把原本通过的测试改写成新行为、跑不通、再 skip 掉——这比没有测试更危险

### 🔍 同类问题必须横向扫描

修复某个代码 pattern（bare `except`、硬编码路径、编码问题）时，**必须扫全仓库**，一次性修完同类问题。

```bash
# 例：修 bare except 前先扫存量
grep -rn "except:" backend/src/ --include="*.py"
grep -rn "except Exception:" backend/src/ --include="*.py"

# 例：修 encoding 前先扫
grep -rn 'read_text(encoding="utf-8")' backend/src/ --include="*.py"

# 例：修硬编码路径前先扫
grep -rn '"data"/"audio"' backend/src/ --include="*.py"
```

**不允许**：修了 A 文件的 pattern，留着 B 文件的同类问题等下一次。

### 📋 提交前 self-check 清单（每次 push 前逐项确认）

```
□ pytest 全套跑完，输出了 "NNN passed, 0 failed"（不是"应该能过"）
□ 本次改动没有引入新的 @pytest.mark.skip
□ 如果修了某个 pattern，已用 grep 确认全仓库同类问题都处理了
□ 新增测试文件：若使用 TestClient 或 module/class-scope fixture，已加 @pytest.mark.real_db
□ commit message 包含实际测试数字（如 "605 passed"），不写估算值
□ AGENTS.md 顶部版本号 + 测试基线已更新
```

### 🧪 测试文件分类规则

新建或修改测试文件时，按以下判断决定是否加 `pytestmark = [pytest.mark.real_db]`：

| 测试特征 | 是否加 real_db |
|---------|--------------|
| 使用 module/class-scope fixture 预写 DB 数据 | ✅ 必须加 |
| 使用 `TestClient(global_app)` 发真实 HTTP | ✅ 必须加 |
| 已有自己的 `isolated_db` fixture | ✅ 必须加（防双重 monkeypatch）|
| 纯函数单元测试，不碰 DB | ❌ 不需要 |
| 用 `patch.object` 全 mock，不发真实请求 | ❌ 不需要 |

原理：`_isolate_db_per_test` 是 autouse fixture，会给每个测试注入独立的 SQLite 临时文件。  
`real_db` 标记 = "我自己管 DB，不要 autouse 干预"。

---

## 文档更新规则（每次 push 前强制执行）

> 你完成任何代码改动并 push 之前，必须更新本文档和 CHANGELOG.md。
> 不更新文档 = 工作未完成。

| 改动类型 | 版本号变化 | 必须更新的文件 |
|---------|-----------|--------------|
| Bug 修复 | patch +1（0.6.0 → 0.6.1） | AGENTS.md + CHANGELOG.md |
| 新功能上线 | minor +1（0.6.x → 0.7.0） | AGENTS.md + CHANGELOG.md + 同事上手指南.md |
| 纯文档/注释/测试调整 | 不变 | AGENTS.md（仅更新日期和测试基线） |

更新 AGENTS.md 时修改：
1. 顶部「当前状态」表格：版本号、测试基线（实际 passed 数）、日期
2. 「最近做了什么」区块：顶部插入新版本段落
3. 架构/字段名有变化时更新对应表格

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
| `CHANGELOG.md` | 版本历史 |
| `CLAUDE.md` | 测试标准 + 开发规范详细版 |
| `backend/src/cangjie_fos/engine/schema.py` | **所有报告 schema（字段名权威来源）** |
| `backend/src/cangjie_fos/main.py` | FastAPI app 入口 + lifespan |
| `backend/src/cangjie_fos/services/pitch_upload_pipeline.py` | 上传→ASR→评估主流水线 |
| `backend/src/cangjie_fos/services/pitch_job_db.py` | SQLite 持久化层（单一真相源） |
| `backend/src/cangjie_fos/api/routes/roadshow.py` | 路演分析专属 5 个端点 |
| `frontend/src/components/RoadshowWizard.tsx` | 路演分析 5 步向导 |
| `frontend/src/pages/ReviewWorkbench.tsx` | 全屏审查台 |
| `backend/tests/test_pipeline_e2e.py` | Pipeline 核心 E2E 测试 |
| `backend/tests/test_roadshow_e2e.py` | 路演分析 E2E 测试（17 个） |
