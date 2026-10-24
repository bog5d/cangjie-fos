# DD-V1 本地运行手册（DeepSeek Harness 版，全团队通用）

> 适用对象：投融资团队成员（刘江先跑，之后各团队照做）。不需要会编程，照着复制命令即可。
> 原则：**材料和 Gold 答案都只在你自己的电脑上，我们的程序不上传、不外发任何文件。**
> 主力模型 = DeepSeek Harness（国产，自己安装、自己充值）。Codex 只是刘江的备用方案，其他人不用装。

---

## 0. 先弄清三件事

1. **会把什么发给 DeepSeek？** 我们的程序本身不联网。DeepSeek Harness 答题时，会把下面这些内容发给 DeepSeek 模型（董事长已批准这种用法）：
   - 清单原文（如「提供××公司2024年度审计报告」）
   - 被选中的每个文件的**文件名和相对路径**、主体全称、年度、文档类型、正文/附注、正式/草稿
   - 每个文件最多 300 字的正文摘录（只有文本文件，或你提供了文本版的文件才有）
   - 文件的 sha256 指纹

   如果某个文件连**文件名**都不能外发，就先改名或者不放进材料目录；如果连摘录都不能外发，就不要给它提供文本版。
2. **模型的结论算数吗？** 不算。模型只给「建议」，每一条都标着「需人工复核」。程序还会自动拦掉错主体、错年度、用了草稿、附件不全、编造文件或页码这几类错误。
3. **Gold（标准答案）放哪？——硬性规定**
   - **模型运行期间，这台电脑上不能有 Gold 文件。** 等第 3 步全部跑完、确认没有 dsh 进程在运行之后，再从 U 盘或别处把 Gold 拷进来评分；评完就移走。
   - Gold 必须放在材料目录、文本目录和输出目录以外。程序会检查，放错位置会拒绝评分。
   - 原因：DeepSeek Harness 是一个「智能体」，如果它的 profile 允许读文件，它理论上能读到这台电脑上的任何文件。程序默认通过标准输入把任务交给它，**不需要**它有读文件的能力。建议使用不能读写文件、不能执行命令的 profile（具体怎么设置请看 dsh 官方说明），这样最安全。

---

## 1. 安装（一次性，约 20 分钟）

### 1.1 需要的软件
| 软件 | Windows | Mac | 检查命令 |
|---|---|---|---|
| Git | https://git-scm.com 下载安装 | 自带或 `xcode-select --install` | `git --version` |
| Python 3.11+ 和 uv | 安装 uv：PowerShell 运行 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `uv --version` |
| Node.js 20+（装 dsh 用） | https://nodejs.org 下载 LTS | 同左 | `node --version` |

### 1.2 下载 DD-V1 代码
```bash
git clone https://github.com/bog5d/cangjie-fos.git
cd cangjie-fos
git checkout master
git log -1 --oneline      # 记下这一行，回传结果时要写上
cd backend
uv sync
cd ..
```
以 master 最新提交为准，至少要到 `a58d865`（见第 7 节「版本记录」）。

### 1.3 安装 DeepSeek Harness（dsh）
```bash
npm install -g @deepseek-ai/dsh
dsh --version
dsh headless --help       # 能看到 "Answer one task and exit" 就说明装好了
```
具体安装和登录方式**以 dsh 官方说明为准**；本手册写的是 0.1.7 版的用法。

### 1.4 充值和密钥（每人用自己的账户）
1. 在 DeepSeek 开放平台注册、实名、**自己充值**（建议先充一小笔试跑）。
2. 生成 API Key，**放进你自己电脑的环境变量**（变量名按 dsh 官方说明，常见的是 `DEEPSEEK_API_KEY`）：
   - Windows：开始菜单搜「环境变量」→「编辑系统环境变量」→「环境变量」→ 新建用户变量，然后**重开终端**
   - Mac：在 `~/.zshrc` 里加一行 `export DEEPSEEK_API_KEY=你的key`，然后执行 `source ~/.zshrc`
3. 验证：`dsh headless "只回复 OK"`，能回 OK 就说明可用。
4. **不要**把 Key 写进任何文件、配置或聊天里。程序会自动把日志里出现的 Key 替换成 `<REDACTED:…>`；配置文件里一旦出现 key/token 字段，程序会直接拒绝运行。

### 1.5（可选）dsh 配置文件
默认不需要。如果 dsh 不在 PATH 里，或者要换 profile、加参数，就新建 `dsh.json`（**不要写密钥**）：
```json
{"binary": "C:/Users/你/AppData/Roaming/npm/dsh.cmd", "profile": "headless", "extra_args": [], "mode": "stdin"}
```
- `mode` 保持 `"stdin"`（默认）：任务内容从标准输入交给 dsh，命令行里只有固定参数。这样 Windows 上不会出现命令注入，也没有命令行长度限制，dsh 也不需要读文件的权限。
- `"file"` 模式会让 dsh 自己去读 PROMPT.txt，需要它有读文件的能力，**不推荐**。

---

## 1.6 必做的第一步：先用合成样例试跑一次，回传结果后再碰真实材料

这一步只用仓库自带的**虚构材料**（`backend/tests/fixtures/dd_v1_fos71_wp04`），可以放心回传。目的是确认你电脑上的 dsh 能被程序正确调用。程序用的写法是 `dsh --profile headless -`（任务从标准输入读入），**这个写法还没有在 dsh 0.1.7 上实测过**，所以必须先试。

在 `cangjie-fos` 文件夹里运行下面这一行（PowerShell、cmd、Mac 终端都用这一行）：
```
uv run --project backend python tools/dd_v1_local_run.py run --material-root backend/tests/fixtures/dd_v1_fos71_wp04/snapshot --meta backend/tests/fixtures/dd_v1_fos71_wp04/meta.json --items backend/tests/fixtures/dd_v1_fos71_wp04/raw_items.json --out ../dd-first-run --allow-local-dsh --max-total-calls 10
```
（这是仓库内的合成样例，所以不需要 `--allow-real-material`。）

**成功的样子**：屏幕上 R1、R2、R4 三行都显示 `"adapter_status": "OK"`；R3 显示 `NEEDS_HUMAN_SPLIT`，这是正常的。

**把下面这些发回给开发**（全部是虚构数据，可以整体发）：
- `../dd-first-run/run_summary.json`
- `../dd-first-run/run-R1/run_record.json`、`answer.txt`、`stderr.log`（R2、R4 也一起发）
- `dsh --version` 的输出和 `git log -1 --oneline` 的输出

**如果失败**（状态是 CALL_FAILED、INVALID_JSON，或者 dsh 一直在等输入）：
1. 先手动试一下 stdin 写法。PowerShell 运行 `"只回复 OK" | dsh --profile headless -`，Mac 运行 `echo 只回复 OK | dsh --profile headless -`。
2. 如果第 1 步不回 OK，说明 stdin 写法不可用，改用文件模式：在 `cangjie-fos` 文件夹里新建 `dsh.json`，内容是
   ```json
   {"mode": "file"}
   ```
   然后在上面那条命令末尾加上 ` --dsh-config dsh.json`，再换一个 `--out`（例如 `../dd-first-run-file`）重跑。文件模式要求 dsh 能读当前目录里的文件。只在合成样例试跑时这样用没问题；跑真实材料前请和开发确认。
3. 两种都失败的话，把 stderr.log 和屏幕输出发回，**先不要跑真实材料**。

**收到开发确认之前，不要开始第 2 节以后的真实材料步骤。**

## 2. 准备材料（每个项目一次）

文件夹结构建议如下（**Gold 单独放，先不要拷进来**）：
```
D:\DD\项目A\
   材料\          ← 原始材料，程序只读，不会改动
   清单.csv       ← 尽调清单
   meta.json      ← 材料目录说明（下一步自动生成，再人工核对）
   输出\          ← 运行结果（程序会自动建）
D:\DD\Gold\项目A-gold.json   ← 最后一步才放
```

### 2.1 清单 `清单.csv`（UTF-8，三列）
```
item_id,entity,text
R1,示例科技有限公司,提供示例科技有限公司2024年度审计报告（含附注）
R2,示例科技有限公司,提供最新公司章程及2024年社保缴纳证明
```

### 2.2 生成材料目录说明 meta.json
```bash
uv run --project backend python tools/dd_v1_local_run.py scaffold --material-root "D:\DD\项目A\材料" --entity "示例科技有限公司" --out "D:\DD\项目A\meta.json"
```
屏幕会显示 `need_manual_fill`：有多少个文件的主体、年度或文档类型没猜出来。用记事本或 VS Code 打开 meta.json，逐个补齐：
- `entity` 主体全称；`period` 年度（如 2024；营业执照、章程这类填 CURRENT）
- `doc_type` 只能填：审计报告 / 营业执照 / 公司章程 / 社保缴纳证明 / 财务报表 / 验资报告 / 纳税证明
- `part` 填 正文 或 附注；`version_status` 填 EFFECTIVE（正式）/ DRAFT（草稿）/ SUPERSEDED（已被取代）
- 没填 entity 或 doc_type 的文件不会给模型看。

**PDF / Word 怎么办？** 程序不直接读二进制文件，只把元数据给模型（摘录显示为 `NO_TEXT_LAYER`）。想让模型看到正文，把文字版另存到一个「文本」文件夹，在 meta 里加 `"text_path": "相对文本文件夹的路径.txt"`，运行时加 `--text-root "D:\DD\项目A\文本"`。

### 2.3 查看清单拆分（不调用模型，也是做 Gold 的底稿）
```bash
uv run --project backend python tools/dd_v1_local_run.py split --items "D:\DD\项目A\清单.csv" --out "D:\DD\项目A\obligations.json"
```
- 一条清单会拆成几条「义务」（例如 R2-O1 章程、R2-O2 社保）。**Gold 按这里的 obligation_id 写。**
- `needs_human_split` 列出的条目程序拆不了（比如「其他相关材料」），需要自己在 obligations.json 里补写，运行时加 `--obligations obligations.json`。

---

## 3. 运行（DeepSeek Harness，主力）

程序默认**按清单条目逐条跑**，每条一个小包，这样不容易超时。只有很小的清单才加 `--single-pack` 合成一个包。

先打开终端，在 `cangjie-fos` 文件夹里执行。**整条命令只有一行，原样复制即可。** 先确认你打开的是哪种窗口，再复制对应版本：

**Windows · PowerShell**（开始菜单搜 PowerShell；提示符以 `PS` 开头）：
```powershell
uv run --project backend python tools/dd_v1_local_run.py run --material-root "D:\DD\项目A\材料" --meta "D:\DD\项目A\meta.json" --items "D:\DD\项目A\清单.csv" --out "D:\DD\项目A\输出" --allow-real-material --allow-local-dsh --timeout 600 --max-total-calls 200
```

**Windows · 命令提示符 cmd**（开始菜单搜 cmd；提示符类似 `C:\>`）：
```bat
uv run --project backend python tools/dd_v1_local_run.py run --material-root "D:\DD\项目A\材料" --meta "D:\DD\项目A\meta.json" --items "D:\DD\项目A\清单.csv" --out "D:\DD\项目A\输出" --allow-real-material --allow-local-dsh --timeout 600 --max-total-calls 200
```

**Mac · 终端**：
```bash
uv run --project backend python tools/dd_v1_local_run.py run --material-root "$HOME/DD/项目A/材料" --meta "$HOME/DD/项目A/meta.json" --items "$HOME/DD/项目A/清单.csv" --out "$HOME/DD/项目A/输出" --allow-real-material --allow-local-dsh --timeout 600 --max-total-calls 200
```

两个版本内容一样，区别只在于你粘贴到哪个窗口。用了自定义配置，就在行尾加上 ` --dsh-config dsh.json`。

`--allow-real-material` 和 `--allow-local-dsh` 两个开关缺一不可。前者表示「我确认这是本机材料」，后者表示「我确认用自己的 DeepSeek 账户」。缺了任何一个，程序都会拒绝运行（退出码 3）。

**花费怎么控制（请如实理解）**
- dsh **不会告诉程序每次花了多少钱**，所以程序**没办法按金额限额**。屏幕第一行会显示 `"cost_cap": "不限额…"`。给 `--cost-cap` 会被直接拒绝。
- 程序能真正执行的上限是**调用次数**：`--max-total-calls 200` 表示整次运行最多调用模型 200 次（含自动重试），到了就停，剩下的条目标 `STOPPED_MAX_TOTAL_CALLS`。不写这个参数就是「不限」。
- 金额请在 DeepSeek 平台控制：只充你愿意花的金额，并设置余额预警。
- 拆不出义务的条目（`NEEDS_HUMAN_SPLIT`）不会调用模型，也不花钱。

### 屏幕上会看到什么
第一行是限额说明，之后每跑完一条输出一行，例如：
```
{"group": "R1", "adapter_status": "OK", "elapsed_s": 41.2, "mode": "AGENT_SUGGESTION", "accepted": 1, "rejected": 0, ...}
```
| 字段 | 含义 |
|---|---|
| adapter_status | OK 正常；TIMEOUT 超时；CALL_FAILED 调用失败（看 stderr.log） |
| mode | AGENT_SUGGESTION = 有被接受的建议；RULE_ONLY = 模型结果全部作废，只剩规则结果 |
| accepted / rejected | 被接受 / 被拦下的条数（被拦原因写在 run_record.json 的 rejected.errors 里） |

退出码：0 = 至少一条有建议；2 = 全部降级为纯规则；3 = 参数或安全检查不通过。

中断了也不要紧：加 `--resume` 重跑，已经完成的条目会跳过。

### 输出目录
```
输出\run-R1\run_record.json   ← 完整记录（含摘录！不要外发）
输出\run-R1\answer.txt / stderr.log
输出\run_summary.json          ← 汇总
```

---

## 4. 评分（等所有运行结束后）

1. 把 Gold 拷到**材料和输出目录以外**的文件夹，例如 `D:\DD\Gold\项目A-gold.json`。格式如下（只写 file_id，不写路径）：
```json
[
 {"obligation_id": "R1-O1", "expected_verdict": "MATCH", "expected_files": ["F00001", "F00002"]},
 {"obligation_id": "R2-O2", "expected_verdict": "MISSING", "expected_files": []}
]
```
   expected_verdict 只能取：MATCH / PARTIAL / OUTDATED / CONFLICT / MISSING / UNCERTAIN
2. 运行评分（一行；PowerShell、cmd 都可以用这一行，Mac 把路径换成 `$HOME/...`）：
```
uv run --project backend python tools/dd_v1_local_run.py score --run-dir "D:\DD\项目A\输出" --gold "D:\DD\Gold\项目A-gold.json" --material-root "D:\DD\项目A\材料" --out "D:\DD\项目A\score.json"
```
   用了文本目录，就再加 `--text-root "D:\DD\项目A\文本"`。Gold 放在材料、文本或输出目录里面时，程序会拒绝评分（`GOLD_INSIDE_FORBIDDEN_DIR`）。
3. 评完就把 Gold 移出这台电脑。
4. 结果说明：
   - `status`：义务少于 30 条时显示 LOW_CONFIDENCE（样本太少，仅供参考），达到 30 条显示 SCORED
   - `agent.accuracy` 是模型准确率，`rule_only_baseline.accuracy` 是纯规则准确率，两者对照看
   - `confident_mismatch`：模型自信（置信度 ≥0.8）却答错的条数，这是最危险的错误
   - `score.csv` 可以用 Excel 打开逐条看，`error_category` 一列请人工填写错误类型：规则缺陷 / 模型推理缺陷 / 召回缺陷 / 资料缺失

---

## 5. 回传什么（只传这些）

| 回传 ✅ | 不要回传 ❌ |
|---|---|
| `score.json`、`score.csv`（只含编号和判定） | 原始材料、文本文件夹 |
| `输出\run_summary.json` | `run_record.json`、`answer.txt`（里面有材料摘录） |
| `git log -1 --oneline` 那一行、dsh 版本号 | meta.json（含文件名，可能敏感） |
| 填好 error_category 的 csv、主观评价（省了多少时间、哪类错最多） | Gold 原件、API Key |

---

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| `拒绝：真实材料需要… --allow-real-material` / 退出码 3 | 补上两个 `--allow-…` 开关 |
| `dsh: command not found` / `SPAWN_FAILED` | 没装好或不在 PATH 里：重开终端；或者在 dsh.json 里写 binary 的完整路径（Windows 一般是 `...\npm\dsh.cmd`） |
| `dsh: profile "headless" does not exist` | 升级 dsh，或者按官方说明创建 headless profile，再在 dsh.json 里写 profile 名 |
| CALL_FAILED，stderr 里有余额、额度、401 | 去 DeepSeek 平台充值，或检查环境变量里的 Key（改完要重开终端） |
| **TIMEOUT / 408 / 卡很久** | ① 不要加 `--single-pack`（默认就是逐条跑）；② `--timeout 900`；③ 某一条特别大时，把它在清单里拆成几条；④ 用 `--resume` 续跑；⑤ 程序默认对超时和调用失败自动重试 1 次（`--max-calls 2`），每次重试都要花钱，不要调大 |
| 命令粘贴后报错、参数不全 | 检查窗口类型：PowerShell 用 PowerShell 版本，cmd 用 cmd 版本；命令必须是完整的一行 |
| 映射的网络盘（如 Z:） | 程序认不出它是网络路径。请把材料复制到本机硬盘再跑 |
| mode 全是 RULE_ONLY，degrade_reason 是 INVALID_JSON / NO_RESULTS_ARRAY | 模型没按格式回答。重跑一次；还不行，把 stderr.log 的**最后几行**（先确认里面没有材料内容）发给开发 |
| 大量 `NOT_IN_RETRIEVED_EVIDENCE` / 某些文件从来不出现 | 多半是 meta.json 里的 entity 或 doc_type 填错或空着 |
| `PATH_OUTSIDE_SNAPSHOT` | meta 里的路径跑到材料目录外面去了，请改正 |
| 想看程序会给模型看什么 | 打开 `输出\run-R1\packet.json`（在本机看，不要外发） |

### 刘江专用：Codex 备用（其他人不用）
DeepSeek 不可用时才用。前提是已装 Codex CLI 并登录：
```bash
uv run --project backend python tools/dd_v1_local_run.py run （同第 3 节的参数，--out 换一个目录） --adapter codex --timeout 900 --max-total-calls 200
```
Codex 出现 **408 / 超时**是已知情况（服务端排队）：保持默认的逐条模式，超时设到 900，失败的条目用 `--resume` 续跑。Codex 的结果和 DeepSeek 的结果请放在**不同的输出目录**，分开评分。

---

## 7. 版本记录
| 日期 | master 提交 | 说明 |
|---|---|---|
| 2026-10-16 | `a58d865`（`git checkout a58d865` 或更新的 master） | 首版：DeepSeek Harness 本地 opt-in、真实材料 opt-in、按条目拆分、本地 Gold 评分 |
