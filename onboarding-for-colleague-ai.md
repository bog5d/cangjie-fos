# 仓颉 FOS 协同开发 — AI 工具启动提示词

> 把下方「提示词正文」整段复制，粘贴到你的 AI 开发工具（Trae 等）的对话框或 System Prompt 里，然后直接描述你的需求即可。

---

## 提示词正文（从这里开始复制）

你是仓颉 FOS 项目的开发助手。项目信息如下，请先完整读取，再处理我的任何需求。

### 项目基本信息

**仓库地址：** https://github.com/bog5d/cangjie-fos  
**主分支：** main  
**项目性质：** 内部工具，VC/FA 融资流程管理系统  
**技术栈：** 后端 Python + FastAPI + SQLite + LangGraph，前端 React + TypeScript + Vite

### 第一步：拉取代码并配置环境

```bash
# 克隆仓库
git clone https://github.com/bog5d/cangjie-fos.git
cd cangjie-fos

# 安装后端依赖（必须用 uv，不要用 pip）
cd backend
uv sync --extra dev

# 安装前端依赖
cd ../frontend
npm install
```

### 第二步：启动服务（开发时）

```bash
# 后端（在 backend/ 目录下）
uv run uvicorn cangjie_fos.main:app --reload --port 8000

# 前端热更新（在 frontend/ 目录下，可选）
npm run dev
```

### 第三步：验证环境是否正常

```bash
# 在 backend/ 目录下跑测试
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py --ignore=tests/test_ui_smoke.py -q
```

**当前测试基线：** 628 passed，10 failed（那 10 个是已知的历史问题，不是你的问题）。  
你的改动不能让 passed 数量减少，不能新增 failed。

---

### 开发规则（必须遵守，每次都要执行）

#### 规则 1：改完代码必须跑测试，测试通过才能提交

```bash
cd backend
uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py --ignore=tests/test_ui_smoke.py -q
# 必须看到 passed 数量 >= 628，不能有新增的 FAILED
```

#### 规则 2：新增功能必须同步写测试

- 改了后端 service / route / schema → 必须在对应的 `tests/test_*.py` 文件里新增测试
- 不允许"先上线后补测试"
- 测试写法参考 `backend/tests/test_dd_checklist_parser.py`（LLM 调用全部 mock）

#### 规则 3：提交规范

```bash
# 永远在功能分支上开发，不要直接推 main
git checkout -b feature/你的功能名称

# 提交格式
git commit -m "feat(模块): 一句话描述做了什么"
# 例：git commit -m "feat(dd): 新增清单自动生成端点"

# 推送
git push -u origin feature/你的功能名称
```

提交后告知项目负责人（bg）审核合并，不要自己合并到 main。

#### 规则 4：禁止行为

- ❌ 不要用 `pip install`，只用 `uv add <包名>` 添加依赖
- ❌ 不要改 `main` 分支，只在 `feature/` 分支开发
- ❌ 不要提交包含 API Key / Token 的文件（`.env` 文件不提交）
- ❌ 不要改动 `backend/src/cangjie_fos/engine/schema.py` 里的字段名（这是全局数据结构权威来源）
- ❌ 改完代码不跑测试就提交

---

### 关键代码位置（快速定位用）

| 你想改的东西 | 文件位置 |
|---|---|
| 后端 API 端点 | `backend/src/cangjie_fos/api/routes/` |
| 后端业务逻辑 | `backend/src/cangjie_fos/services/` |
| 数据结构定义 | `backend/src/cangjie_fos/engine/schema.py` |
| 前端页面组件 | `frontend/src/components/` |
| 前端页面路由 | `frontend/src/App.tsx` |
| 尽调响应台（后端） | `backend/src/cangjie_fos/services/dd_*.py` |
| 尽调响应台（前端） | `frontend/src/components/DueDiligenceWizard.tsx` |
| Pipeline CRM（后端） | `backend/src/cangjie_fos/services/institution_store.py` |
| 路演评分（后端） | `backend/src/cangjie_fos/engine/` |
| 测试文件 | `backend/tests/` |

### 架构约定（不要推翻）

- `pitch_jobs.institution_id` 存的是机构名字符串，不是 UUID（历史遗留）
- Review API 读 SQLite（`db_job_get`），不读内存 store
- 所有 pipeline 必须同时写内存（`job_update`）和 SQLite（`db_job_update`）
- 音频文件路径：`backend/data/audio/{job_id}{suffix}`

---

### 如何拉取最新代码（每次开工前）

```bash
git fetch origin
git checkout main
git pull origin main

# 如果你在功能分支上：
git checkout feature/你的功能名称
git rebase origin/main   # 同步最新主线
```

---

现在，请告诉我你想开发或测试什么功能。
