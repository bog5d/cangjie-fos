# AGENTS.md — 仓颉 FOS · AI 协作操作手册

> **所有 AI Agent（Claude、Cursor、Hermes、Codex 等）进入本仓库前必读。**  
> 本文档是权威操作规范，优先级高于任何其他文档。

---

## 当前版本状态（最后更新：2026-04-28）

| 项目 | 状态 |
|------|------|
| 版本 | v0.5.1 |
| 测试基线 | **278 passed**（`cd backend && uv run --extra dev pytest tests/ -q`） |
| 前端构建 | **零错误**（`cd frontend && npm run build`） |
| 当前 Phase | **Phase 7.0 阶段4完成（v0.5.1）→ Phase 7.0 阶段5待开始** |
| 详细变更历史 | 见 `CHANGELOG.md` |

---

## 读代码前必须知道的架构事实

### 1. 双系统架构
本仓库（FOS）是**前端 + 后端 + 业务编排**。  
**AI Pitch Coach（FSS）** 是独立的 LLM/ASR 评估引擎，不在本仓库内。

```
cangjie-fos（本仓库）
    ├── 负责：UI、API路由、任务管理、报告生成、豆豆NPC
    └── 依赖：AI Pitch Coach（FSS）提供 LLM 评估能力
              └── 位置：PITCH_COACH_ROOT 环境变量指定
                        （本地开发通常是 D:\AI_Workspaces\AI_Pitch_Coach）
```

**重要**：没有 FSS 也能运行大部分功能。FSS 只在以下操作时才需要：
- 实际 ASR 转写（测试用 mock 替代）
- LangGraph Coach 评估（测试用 mock 替代）
- 机构数据同步（Adapters）

### 2. 测试在无 FSS 环境下全部通过

所有测试已 mock FSS 依赖。设置环境变量即可：
```bash
export PITCH_COACH_ROOT=/tmp/mock_pitch_coach
mkdir -p /tmp/mock_pitch_coach/src
cd backend && uv run --extra dev pytest tests/ -q
# 期望：228 passed
```

### 3. 数据目录不在 git 里

`backend/data/`（SQLite + 音频文件）已 gitignore。首次运行会自动创建。

---

## 强制操作规范

### 改代码前
```bash
git pull origin master          # 拉最新
cd backend && uv run --extra dev pytest tests/ -q  # 确认基线
```

### 改完代码后（缺一不可）

```bash
# 1. 跑全套测试
cd backend && uv run --extra dev pytest tests/ -q
# 期望：≥228 passed，0 failed

# 2. 前端构建检查
cd frontend && npm run build
# 期望：✓ built in X.XXs，零 TS 错误

# 3. 更新 CHANGELOG.md
# 在 [Unreleased] 下添加你的变更条目

# 4. 提交
git add <具体文件>    # 禁止 git add -A（防止误提交 .env）
git commit -m "type(scope): 简短描述"

# 5. 推送（CI 会自动验证）
git push origin <分支名>
```

### 提 PR 必须
- PR 描述填写 `.github/pull_request_template.md` 模板
- CI（GitHub Actions）全绿才能合并
- 更新 `CHANGELOG.md`

---

## 禁止行为

| 禁止 | 原因 |
|------|------|
| `git add -A` 或 `git add .` | 可能误提交 `.env`（API Key）或 SQLite 文件 |
| 改完说"应该好了你试试" | 必须先跑测试证明 |
| 只 mock 外部服务不验证 DB 写入 | DB 才是审查台的数据源 |
| 新增 pipeline 步骤不更新 E2E 测试 | 会导致测试不覆盖真实链路 |
| 提交 `.env` / `*.sqlite` / `*.zip` | 已 gitignore，不应强制添加 |
| 删除/跳过现有测试来让数量达标 | CI 验证数量 ≥200，但测试必须真实有效 |

---

## 关键文件速查

| 文件 | 作用 |
|------|------|
| `CHANGELOG.md` | 版本历史，**每次提交前必须更新** |
| `CLAUDE.md` | Claude 专用规范（测试标准、架构约定） |
| `backend/src/cangjie_fos/services/pitch_upload_pipeline.py` | 上传→ASR→评估主流水线 |
| `backend/src/cangjie_fos/services/pitch_job_db.py` | SQLite 持久化层（单一真相源） |
| `backend/src/cangjie_fos/services/npc_chat_graph.py` | 豆豆 NPC 对话图 |
| `backend/src/cangjie_fos/core/readiness.py` | 系统就绪检查（Doctor 模块） |
| `backend/tests/test_pipeline_e2e.py` | Pipeline 核心 E2E 测试 |
| `frontend/src/components/TaskRail.tsx` | 任务进度组件 |
| `frontend/src/pages/ReviewWorkbench.tsx` | 全屏审查台 |

---

## 战略方向（已对齐，新 AI 必读）

**FSS（AI Pitch Coach）将完全吸收进 FOS，不是外部依赖，是子模块。**

五阶段合并计划：
| 阶段 | 内容 | 状态 |
|------|------|------|
| 阶段0 | R3：LLM重试 + 重跑评估按钮 | ✅ 完成（v0.2.1） |
| 阶段1 | FSS代码移入 `engine/` 子包，消灭 sys.path 注入 | ✅ 完成（v0.3.0） |
| 阶段2 | FSS JSON数据 → FOS SQLite统一（贡献度/素材匹配表） | ✅ 完成（v0.4.0，258 passed） |
| 阶段3 | APScheduler夜间自动进化任务 | ✅ 完成（v0.5.0，266 passed） |
| 阶段4 | 全数据关联（路演→素材→机构→贡献者） | ✅ 完成（v0.5.1，278 passed） |
| 阶段5 | Doctor强化（外发版自愈） | ⏳ 待开始 |

FSS 路径：`D:\AI_Workspaces\AI_Pitch_Coach`（阶段1完成后归档）

## 立即要做（阶段5 — Doctor 强化，外发版自愈）

**阶段4已完工（v0.5.1）**：全数据关联链路打通，278 passed。

**阶段5核心目标**：同事/投资机构收到 zip 包解压后，常见问题**自动诊断+一键修复**，不需要来找王波。

### 背景（必读）
现有诊断工具：
- `backend/src/cangjie_fos/core/readiness.py` — 系统就绪检查，返回 JSON 探针结果
- `backend/src/cangjie_fos/core/preflight.py` — 启动时检查必选依赖（缺失则阻断）
- `诊断_打不开请运行我.bat` — Windows 批处理，调用 uvicorn 启动并输出错误
- `GET /api/v1/ready` — HTTP 探针，已有 `pitch_coach_ok`、`issues` 字段

缺失的：没有**自动修复**能力，诊断后只告诉用户"有问题"，不帮解决。

---

### Task 1 — tools/doctor.py（跨平台诊断修复脚本）
新建文件：`tools/doctor.py`（项目根目录）

```python
#!/usr/bin/env python3
"""
仓颉 FOS 一键诊断修复脚本。
用法：python tools/doctor.py [--fix]
不带 --fix：只诊断，输出报告
带 --fix：自动修复可修复项
"""
```

诊断项（按严重程度排序）：
| 检查项 | 诊断方法 | 自动修复 |
|--------|----------|---------|
| Python 版本 ≥ 3.10 | `sys.version_info` | ❌ 提示手动安装 |
| uv 已安装 | `shutil.which("uv")` | ❌ 输出安装命令 |
| 依赖已安装 | `import cangjie_fos` | ✅ 运行 `uv sync --extra dev` |
| 8000 端口空闲 | `socket.connect` | ✅ Windows: `netstat+taskkill`，Linux: `lsof+kill` |
| data/ 目录存在 | `Path.exists()` | ✅ `mkdir -p backend/data/audio backend/data/html_reports` |
| FFmpeg 可用 | `shutil.which("ffmpeg")` | ❌ 输出下载链接（Windows/Mac/Linux 分支） |
| SQLite 可写 | 创建临时 DB 文件 | ✅ 检查磁盘空间，输出 `df -h` |
| .env 文件存在 | `Path(".env").exists()` | ✅ 从 `.env.example` 复制（如有） |
| 前端 node_modules | `Path("frontend/node_modules").exists()` | ✅ 运行 `npm ci` |

输出格式：
```
[✅] Python 3.12.3 — OK
[✅] uv 0.4.2 — OK
[❌] 依赖未安装 — 正在修复...
    → 运行: uv sync --extra dev
    → 完成
[⚠️] FFmpeg 未找到 — 无法自动安装
    → 请下载：https://ffmpeg.org/download.html
    → Windows 推荐：winget install ffmpeg
```

### Task 2 — 诊断_打不开请运行我.bat 增强版
更新现有 `.bat` 文件（保持原位置）：
1. 调用 `python tools/doctor.py --fix` 先自动修复
2. 修复完成后再启动 uvicorn
3. 启动失败时输出**中文错误说明**（端口占用/依赖缺失/权限不足 分情况处理）
4. 新增：启动成功后自动打开浏览器 `start http://localhost:8000`

### Task 3 — GET /api/v1/doctor（HTTP 版诊断）
文件：`backend/src/cangjie_fos/api/routes/admin.py`（追加到现有 admin 路由）

```python
@router.get("/api/v1/doctor")
def run_doctor_probe() -> dict:
    """返回详细诊断报告，供前端"系统诊断"面板使用。"""
    return {
        "python_version": sys.version,
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
        "data_dir_writable": _check_data_dir(),
        "port_8000_self": True,  # 能响应说明端口OK
        "db_writable": _check_db_writable(),
        "issues": [...],  # 汇总问题列表
        "fix_suggestions": [...]  # 每个问题的修复建议（中文）
    }
```

### Task 4 — 前端：Doctor 面板（轻量弹窗）
文件：`frontend/src/components/DoctorPanel.tsx`（新建）
- 调用 `GET /api/v1/doctor`
- 显示：各项状态图标（✅/❌/⚠️）+ 问题说明 + 修复建议
- 入口：导航栏右上角"系统诊断"按钮（小图标，不占空间）
- 用 `Dialog` 组件弹出（使用已有的 Radix UI 组件库）

### Task 5 — README.md 快速启动章节
更新项目根目录 `README.md`（如无则新建）：
- 快速启动：3步（解压 → 运行 doctor.py --fix → 访问 localhost:8000）
- 遇到问题：运行 `python tools/doctor.py` 查看诊断报告
- 系统需求表格（Python/Node/FFmpeg/OS）
- 不要写超过50行，保持简洁

### Task 6 — 测试（≥8个）
`tests/test_doctor_probe.py`：
- `GET /api/v1/doctor` 返回 200 + 所有必需字段
- `python_version` 字段非空
- `ffmpeg_available` 是 bool
- `db_writable` 为 True（测试环境可写）
- `issues` 是 list
- `fix_suggestions` 是 list

`tests/test_doctor_script.py`（subprocess 测试）：
- `python tools/doctor.py` 退出码 0（不带 --fix，只读）
- 输出包含 "Python" 字样

**CI 验证：278+ passed，npm build 零错误，commit + push，CHANGELOG 更新**

---

## 提交消息格式

```
type(scope): 简短描述（中英文均可）

type: feat | fix | docs | chore | refactor | test
scope: backend | frontend | pipeline | npc | db | ci

示例：
feat(pipeline): 新增 substatus 8节点进度追踪
fix(api): 修复 warnings JSON 反序列化 500 错误
docs: 更新 CHANGELOG Phase 7.0 进度
```
