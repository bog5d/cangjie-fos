# 仓颉 FOS · 融资作战操作系统

> **AI 驱动的路演复盘与机构漏斗管理系统**  
> 为早期创业者设计，从一次路演录音到完整风险诊断报告，全程 AI 辅助。

---

## 核心功能

| 模块 | 说明 |
|------|------|
| 🎙️ **路演复盘** | 上传路演录音 → ASR 转写 → LangGraph 多 Agent 评估 → 结构化风险报告 |
| 🔬 **审查台** | 风险点卡片式复盘，可逐条标注/删除/修改，实时生成 HTML 报告 |
| 🏛️ **机构漏斗（War Room Map）** | 追踪各机构从 Teaser → DD → 签约 的全流程阶段 |
| 🤖 **豆豆顾问（NPC）** | 内嵌融资 AI 顾问，可诊断系统状态、给出实战建议 |
| 📋 **Task Rail** | 实时任务进度追踪，8 个细粒度 substatus 节点，附已等待秒表 |
| 📁 **资料库** | FSS（融资素材站）资产管理与上下文注入 |

---

## 技术栈

```
后端                          前端
────────────────────          ────────────────────
FastAPI + uvicorn             React 18 + TypeScript
LangGraph（评估引擎）          Vite + Tailwind CSS
SQLite（持久化）               react-router-dom
DashScope ASR（阿里云）        Radix UI 组件
硅基流动 LLM                   
Python 3.12 + uv             
```

---

## 快速开始

### 系统要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.10+ | 推荐 3.12 |
| uv | 任意 | Python 包管理器 |
| Node.js | 18+ | 仅构建前端需要 |
| FFmpeg | 任意 | 可选，语音转写功能需要 |
| OS | Windows 10 / macOS 12+ / Ubuntu 20.04+ | 跨平台支持 |

### 3 步启动

**Step 1：** 解压 zip 包到纯英文路径（如 `C:\FOS`）

**Step 2：** 一键诊断与修复
```bash
python tools/doctor.py --fix
```
脚本会自动检查并修复：依赖缺失、data/ 目录、.env 配置、端口占用等问题。

**Step 3：** 启动系统并访问
```bash
# Windows
诊断_打不开请运行我.bat

# macOS / Linux
./start.sh
```
浏览器访问：`http://localhost:8000`

### 遇到问题？

```bash
python tools/doctor.py        # 查看诊断报告
python tools/doctor.py --fix  # 自动修复可修复项
```

或在系统界面右上角点击 **🔧 系统诊断** 查看实时状态。

---

## 项目结构

```
cangjie-fos/
├── backend/                    # FastAPI 后端
│   ├── src/cangjie_fos/
│   │   ├── api/routes/         # REST API 路由
│   │   ├── core/               # 限制/就绪检查/路径管理
│   │   ├── services/           # 业务逻辑
│   │   │   ├── pitch_upload_pipeline.py   # 上传→转写→评估流水线
│   │   │   ├── pitch_graph_service.py     # LangGraph 评估引擎
│   │   │   ├── npc_chat_graph.py          # 豆豆 NPC 对话图
│   │   │   ├── pitch_job_db.py            # SQLite 持久化层
│   │   │   └── report_post_process.py     # 报告后处理
│   │   └── schemas/            # Pydantic 数据模型
│   ├── tests/                  # 228 个自动化测试
│   └── data/                   # 运行时数据（.gitignore，自动创建）
│       ├── audio/              # 上传的音频文件
│       ├── html_reports/       # 生成的 HTML 报告
│       └── *.sqlite            # SQLite 数据库
├── frontend/                   # React 前端
│   └── src/
│       ├── components/
│       │   ├── workbench/      # 审查台组件
│       │   ├── TaskRail.tsx    # 任务进度组件
│       │   ├── NPCPanel.tsx    # 豆豆顾问面板
│       │   └── WarRoomMap.tsx  # 机构漏斗看板
│       └── pages/
│           └── ReviewWorkbench.tsx  # 完整审查台页面
├── tools/                      # 运维脚本（备份/CI/发布）
├── docs/                       # 文档
├── docker-compose.yml
└── Dockerfile
```

---

## 测试

```bash
cd backend
uv run --extra dev pytest tests/ -q   # 228 tests，全绿才算通
```

测试覆盖：
- Pipeline E2E（上传→ASR→LLM→报告完整链路，mock 外部服务）
- API 路由（200/404/422 场景）
- SQLite 持久化（job 状态、substatus、warnings 字段）
- NPC 上下文注入（系统健康快照）
- 报告后处理（原文重建、风险点扩展）

---

## 环境变量说明

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `SILICONFLOW_API_KEY` | 硅基流动 LLM API Key | ✅ |
| `DASHSCOPE_API_KEY` | 阿里云灵积 ASR Key | ✅ |
| `CANGJIE_MAX_UPLOAD_MB` | 最大上传限制（默认 500MB） | 可选 |
| `CANGJIE_DRY_RUN` | 设为 `true` 跳过真实 API 调用 | 可选 |

---

## 开发说明

- **改了后端代码** → 必须跑 `pytest tests/ -q` 全套，不依赖人工点 UI 验证
- **改了 pipeline 链路** → 额外确认 `test_pipeline_e2e.py` 和 `test_wizard_pipeline_e2e.py` 全过
- **新增 API 端点** → 必须同步补测试（200/404/422 场景）
- **运行时数据** → `backend/data/` 在 `.gitignore` 中，不入库；首次启动自动创建

详见 [CLAUDE.md](./CLAUDE.md)

---

## License

Private — 保留所有权利  
© 2025 其烁智能科技 · 仓颉 FOS
