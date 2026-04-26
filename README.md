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

### 前置要求
- Python 3.12+（推荐用 [uv](https://github.com/astral-sh/uv) 管理）
- Node.js 18+
- FFmpeg（音频压缩，可选）

### 1. 配置 API Key

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入以下 Key：
# SILICONFLOW_API_KEY=   # 硅基流动 LLM（必填）
# DASHSCOPE_API_KEY=     # 阿里云 ASR 转写（必填）
```

或直接双击 `填写API密钥_双击我.bat`（Windows）

### 2. 启动系统

**Python 版（推荐开发环境）：**
```bash
# Windows
一键启动_Python版.bat

# macOS / Linux
./start.sh
```

**Docker 版（推荐生产/分发）：**
```bash
docker compose up
```

系统启动后访问：`http://localhost:8000`

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
