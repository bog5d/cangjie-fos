# 仓颉 FOS — AI 工具「一键拉取并跑起来」提示词（新同事专用）

> **给新同事**：你只需要做两件事——
> 1. 在电脑上装好你的 AI 编程工具（字节跳动的 **Trae**，或 Cursor / Claude Code 都行）；
> 2. 打开它的对话框，把下面「提示词正文」整段复制粘贴进去，回车。
>
> 它就会自动：检测你电脑上有没有装过 → 拉取最新版 → 装依赖 → 配好 → 跑起来 →
> 最后用中文告诉你「能不能用、还缺什么」。你把它最后那段汇报截图发给王波即可。
>
> 问题找王波（wangbo8805@gmail.com）。

**当前版本：v1.25.0 | 测试基线：971 passed, 5 skipped | 最后更新：2026-06-19**

---

## 提示词正文（从这一行下面的代码框开始，整段复制）

```
你是仓颉 FOS 项目的「现场部署助手」。我是第一次接触这个系统的新同事，电脑可能被前同事用过、
也可能是全新的。请你**自己探测当前状态、拉取最新代码、装好依赖、配好环境、跑起来**，
全程用中文逐步告诉我你在做什么；遇到任何报错，先尝试自己解决，解决不了就明确告诉我
「卡在哪、需要我（或王波）提供什么」。不要问我代码细节，我不懂代码。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【项目信息】
项目：仓颉 FOS（融资作战操作系统，内部融资管理工具）
仓库：https://github.com/bog5d/cangjie-fos   主分支：master（公开仓库，clone 不需密码）
技术栈：后端 Python 3.11 + FastAPI + SQLite + uv；前端 React + Vite；AI 用 DeepSeek + 阿里云 DashScope
负责人：王波（wangbo8805@gmail.com）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第 0 步：探测现状（先查再动，别重复装）】
请先判断这台电脑的情况，并告诉我结论：
  1. 有没有装 git？有没有装 Python 3.11+？有没有装 uv？有没有装 Node.js 18+？
     （缺哪个就装哪个：Python 去 python.org，安装时务必勾选 Add to PATH；
      然后 pip install uv 装 uv；Node 去 nodejs.org。）
  2. 这台电脑上是否已经有 cangjie-fos 这个文件夹（前同事可能 clone 过）？
     - 如果有：进去执行 git fetch origin && git checkout master && git pull origin master 拉到最新；
       如果它有未提交的本地改动导致 pull 失败，先 git stash 再 pull（别丢数据，告诉我你 stash 了）。
     - 如果没有：在一个合适的目录（如 D:\dev 或 ~/dev）执行
       git clone https://github.com/bog5d/cangjie-fos.git
  ⚠️ 安全红线：如果这台电脑上有公司真实材料/数据目录，绝不要对那些数据目录做任何 git 操作，
     只在代码目录里操作。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第 1 步：装后端依赖】
  cd cangjie-fos/backend
  uv sync --extra dev
  （如果 uv sync 报错，先删掉 backend/.venv 再重试一次。）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第 2 步：配环境变量 .env】
  检查 backend/.env 是否存在：
    - 不存在：从 backend/.env.example 复制一份（Windows: copy .env.example .env；Mac/Linux: cp .env.example .env）
    - 已存在（前同事配过）：保留它，但下一步要验证里面的 Key 还有没有效
  .env 里需要有这几项（Key 找王波要）：
    DEEPSEEK_API_KEY=sk-xxxxx          ← 主力 AI，没有它「解析清单/匹配/路演评分」都跑不了
    DASHSCOPE_API_KEY=sk-xxxxx         ← 语音转写用，只玩文字功能可暂时留空
    FOS_ACCOUNTS=zt001:123456:zt,gk001:123456:gk   ← 决定谁能登录，先用默认即可
  注意：.env 里有密钥，绝不要把它提交到 git，也不要发到群里。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第 3 步：自检测试（确认代码是好的）】
  cd backend
  uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q
  期望：看到约 971 passed（允许小幅波动），不能有 FAILED。把通过数量告诉我。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第 4 步：启动服务】
  后端（必开）：cd backend && uv run uvicorn cangjie_fos.main:app --reload --port 8000
    成功标志：日志出现 "Application startup complete."
  前端（可选，要热更新才开）：另开一个终端 cd frontend && npm install && npm run dev
  然后浏览器打开：http://localhost:8000
  登录账号：gk001 / 123456 （或 zt001 / 123456）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第 5 步：验证 Key 是否有效（关键！别只看"已填写"）】
  登录后，点右上角 ⚙️ 设置。面板一打开会自动验证 Key：
    - DeepSeek 那栏显示绿色/有效 → 太好了，AI 功能可用；
    - 显示红色/失效 → 说明 Key 过期或错了，**这台机器上最常见的坑就是这个**。
      请明确告诉我「DeepSeek Key 失效」，我会去找王波要一把新的。
  （只有 Key 有效，"解析尽调清单 / AI 匹配 / 路演评分 / 数据包补全"这些才真的能跑。）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【最后：给我一份中文汇报（我会截图发给王波）】
请用这个格式总结：
  1. 环境：git/Python/uv/Node 是否齐全（缺啥）
  2. 代码：是新 clone 还是已有 + git pull 到最新（当前 commit 短号）
  3. 测试：X passed / 有无 FAILED
  4. 服务：后端能否启动、能否登录进主页
  5. Key 有效性：DeepSeek 绿还是红、DashScope 绿还是红
  6. 还缺什么需要王波提供：______（如：有效的 DeepSeek Key / DashScope Key / 某账号）
```

（复制到这一行上面的代码框结束。）

---

## 给新同事的使用说明

1. **装工具**：先在电脑上装好 Trae（字节跳动）或 Cursor。装好后打开它，找到「对话/Chat」输入框。
2. **粘贴**：把上面代码框里的整段提示词复制进去，回车，然后跟着它一步步走，它问你要 Key 的时候找王波要。
3. **回传**：它最后会输出一份「中文汇报」，你把那段截图发给王波——王波据此判断你环境通没通、要补什么。
4. **遇到红色 Key**：这是最常见的卡点。看到设置里 DeepSeek 是红的，直接跟王波说「Key 失效了，要一把新的」。

> 跑通之后，怎么"上手用"这套系统、先试哪些场景——看同目录下的
> **`新同事接手指南.md`**（不需要懂代码，手把手带你体验各个功能）。

---

## 进阶：以后要改代码再看（现在可跳过）

- 改完代码必须跑测试：`cd backend && uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q`，通过数 ≥ 971、无新增 FAILED。
- 新增功能必须同步写测试；LLM 调用一律用 `services/dd_llm_client.py` 的 `get_dd_llm_client()` + `call_with_retry()`，并以 `_llm_xxx` 命名便于测试 monkeypatch。
- 数据库改动：在 `db_base.py` 的 DDL 加表/列，并在 `_MIGRATIONS` 末尾**追加**新编号（当前最高 53，只追加不改旧的）。
- 提交：从 master 切分支 `git checkout -b feature/xxx origin/master` → 改 → 测试过 → push → 通知王波合并，**不要直接 push master，不要提交 .env**。
- 字段名权威来源：`backend/src/cangjie_fos/engine/schema.py`，不要乱改。
- 详细架构与约定见仓库根目录 `CLAUDE.md` 与 `AGENTS.md`。
