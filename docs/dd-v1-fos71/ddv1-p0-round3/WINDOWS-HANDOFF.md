# DD-V1 第三轮 P0 · Windows 交接包（刘江侧）

- **适用分支**：`feat/71-player2-p0-fix-20261023`
- **本包对应 sha**：见本文件末尾「§6 版本与可复核信息」
- **读者**：刘江（Windows 授权环境）｜**本包不含任何真实业务材料**
- **纪律**：本包**只描述怎么跑、怎么看、怎么反馈**；**不假设你已经装了任何新组件**
  （凡是新东西，命令里都给了「怎么装」和「装完怎么自检」）。

---

## 0. 一页中文操作指南（打印这页就够）

| 步骤 | 做什么 | 在哪里看 | 怎么判断成功 |
|---|---|---|---|
| ① 打开 | 双击仓库根目录的 **`安装并启动.ps1`**（或 `点击开始-仓颉FOS.bat`） | 黑色窗口 | 窗口不闪退、能看到「后端已启动」和 `http://127.0.0.1:8000` |
| ② 自检 | 在仓库根目录开一个 PowerShell，跑 `python backend\tools\doctor_check.py`（或双击 `诊断_打不开请运行我.bat`） | 终端输出 | 末尾没有红色 `FAIL`；`DD-V1` 相关项是 `OK` |
| ③ 登记主体 | `python backend\tools\dd_v1_manifest.py entity --library <库名> --id S1 --name <公司全称> --relation target --source "<权威依据>"` | 终端输出 | 打印「已登记」；**不登记 ⇒ 主体维度判「无法判定」，不会拿目录名凑数** |
| ④ 跑组包 | `python backend\tools\dd_team_channel.py run --library <库名> --root "<材料目录>" --checklist "<清单.tsv>" --institution "<机构名>" --by "<你>" --anchor-year 2024 --package --approved-by "<批准人>" --package-out "<交付目录>" --out "<报告目录>"` | 终端 + `<报告目录>` | 终端出现「✓ 交付包已生成」**且**「复制原件数 N」；若显示「⚠️ 已达候选上限」说明候选被截断（**不是**失败，照 §3 处理） |
| ⑤ 看结果 | ① 交付目录：`<交付目录>`（正式交付包）<br>② 候选包：`<数据目录>\reviews\<review_id>\`（**非正式**，只读零复制）<br>③ 报告目录：`尽调报告-*.md` / `尽调结果-*.json` | 见左 | 交付目录里有 `01-输入需求清单.tsv` … `07-文件完整性校验结果.tsv` ＋ `组包manifest.tsv` ＋ `SHA256SUMS` ＋ `正式交付包-说明.md` |
| ⑥ 核完整性 | `cd "<交付目录>" && certutil -hashfile "<某个交付文件>" SHA256`（或 `Get-FileHash`） | 终端 | 与 `组包manifest.tsv` 的「副本sha256」列**逐位相同**；`07-文件完整性校验结果.tsv` 里「结论」列全是「是」 |
| ⑦ 反馈失败 | 把**终端完整输出**＋ `<报告目录>\尽调结果-*.json` ＋ `<交付目录>\组包manifest.tsv` 打包发回 | — | 不用截图；直接贴文本，便于逐字核对 |

★ **安全语义**：`dd_team_channel.py` **不联网、不上传、不外发**；真实材料必须显式
`--allow-real-material`；DSH 必须显式 `--allow-local-dsh`；`run` **不接受** Gold 参数。

---

## 1. 运行环境与依赖检查（不假设你装过新东西）

### 1.1 你**已有**的东西（仓库自带，不需要装）

| 东西 | 位置 | 说明 |
|---|---|---|
| 一键安装/启动 | `安装并启动.ps1`、`点击开始-仓颉FOS.bat` | 起后端 `127.0.0.1:8000` |
| 诊断脚本 | `诊断_打不开请运行我.bat` | 环境自检 |
| API 密钥填写 | `填写API密钥_双击我.bat` | 写 `backend\.env` |
| DSH | `C:\npm\dsh.cmd` 或 `C:\npm\DSH.BAT` | 仓内测试 `test_dd_v1_local_run.py` 就是按这两个路径参数化的 |

### 1.2 本轮**新用到**、但**不新增**的东西

本轮**没有引入任何新的外部依赖**。用到的 Python 包与上一轮**完全相同**
（`pytest` / `pytest-asyncio` / `pydantic` / `langchain-core` / `langgraph` / `openai` /
`fastapi` / `httpx` / `python-dotenv` / `structlog` / `python-multipart` / `openpyxl`）。

**自检命令**（在 `backend` 目录，PowerShell）：

```powershell
cd backend
.\.venv\Scripts\python.exe -c "import pytest,pydantic,langchain_core,langgraph,openai,fastapi,openpyxl;print('DEPS_OK')"
```

若报 `ModuleNotFoundError`，按下面装（**不要**改 `uv.lock`）：

```powershell
cd backend
$env:UV_DEFAULT_INDEX="https://mirrors.cloud.tencent.com/pypi/simple/"
$env:UV_HTTP_TIMEOUT="60"
uv pip install --python .\.venv\Scripts\python.exe pytest pytest-asyncio pydantic langchain-core langgraph openai fastapi httpx python-dotenv structlog python-multipart openpyxl
```

> ★ `uv sync --frozen` **不会**改 `uv.lock`（要「不触网跑测试」用
> `PYTHONPATH=src .venv\Scripts\python.exe -m pytest`）。

### 1.3 本轮**改了行为**的地方（跑之前要知道）

| 变化 | 影响 | 你要做什么 |
|---|---|---|
| 主体判定改成**归一后逐字相等**（不再用路径子串兜底） | 材料目录名**必须**能对上登记的主体名或已登记别名 | **先登记主体（§0 ③）**，否则主体维度判「无法判定」 |
| 期间改成**四态**（MATCH / MISMATCH / UNVERIFIABLE / NOT_A_CONSTRAINT） | 材料**自身无年度标注**时，期间判「不可判定」⇒ 该条义务**不判完成** | 想要明确结论，就在材料正文里带「20XX年度」标签 |
| 候选窗口触顶**显式报数** | 终端会多一行「⚠️ 已达候选上限 X，还有 N 份候选未看」 | 照 §3 处理（**不是**失败） |
| 正式交付包**换了默认目录** | 交付包现在落在 `<数据目录>\deliveries\<review_id>\`（**与候选包平级**） | 无需操作；**别**再从候选包目录里找交付件 |
| 材料在审核后被改过 ⇒ **审核失效** | 组包会被拒绝，提示「审核失效」 | 重新核对、重新批准后再组包 |

---

## 2. DSH 调用方式（本轮**没有**改 DSH 接线）

### 2.1 两条入口的分工

| 入口 | 用途 | 关键点 |
|---|---|---|
| `tools/dd_team_channel.py run` | **组包 / 交付**（人用得起来的那个） | `--package` **且** `--approved-by` 才走复制路径；不给批准人 ⇒ 拒绝且**复制零个原件** |
| `tools/dd_v1_local_run.py run` | **语义层证据包**（DSH 跑的那条） | 子命令 `scaffold` / `split` / `run` / `score`；**没有** `package` 子命令（组包走上一条） |

### 2.2 `dsh.json` 的安全姿势（**禁写密钥**）

```json
{
  "binary": "dsh",
  "profile": "headless",
  "extra_args": [],
  "mode": "stdin"
}
```

- `load_dsh_config` 会**校验**：`binary` / `profile` / `extra_args` / `mode` 四个键，
  **写别的键会被拒**（防止把密钥写进配置）。
- `mode="stdin"` 是 **Windows 专用安全姿势**：材料文字只进 **stdin**，
  **命令行里没有任何材料文字**；`.cmd` 经 `cmd.exe` 启动**不会被解释**
  （无注入、无 8191 长度限制）。
- `mode="file"`（让 dsh 自己读 `PROMPT.txt`）**不推荐**。
- 实际 argv 形态 ≈ `dsh --profile headless <extra_args> headless -`（末尾 `-` ＝ 任务包走 stdin）。

### 2.3 本轮对**候选窗口**的影响（语义层）

`MAX_FILES_PER_OBLIGATION = 6`（`dd_v1_semantic_retrieval_service.py`）**本轮不变**，
但**触顶现在会显式报数**：

- 桥接层 `warnings` 多一条：「N 条义务的候选窗口已达上限，合计还有 M 份候选未看
  （MAX_FILES_PER_OBLIGATION=6）；未看部分**不得**当作「不存在」，如实记账」；
- `evidence_status` 多四个字段：`candidate_cap` / `candidates_total` /
  `candidates_used` / `candidate_truncated` / `truncated_candidate_count` / `candidate_cap_note`。

★ 「已达上限」**不是**失败信号：它表示**候选比窗口多**，结论只覆盖已进窗口的部分。

---

## 3. 候选窗口触顶怎么办（可解释的扩展与停止条件）

| 现象 | 含义 | 你该做什么 |
|---|---|---|
| 「⚠️ 已达候选上限 20，还有 N 份候选未看」（规则路径） | 每条义务的候选窗口（`--cap`，默认 20）打满了 | **提高上限重跑**：`--cap 60`；或用 §2.3 的读数确认是不是真的需要更多 |
| 「N 条义务的候选窗口已达上限…」（语义层/DSH 路径） | 证据窗口（6）打满 | 换更精确的清单表述（让 `doc_type` 解析得出来），或分批跑 |

★ **停止条件（写死的、可解释的）**：候选池先按「同主体 ＋ 同材料类型」过滤，
再按「期间对得上 → 依据不足 → 已知冲突 → 现行有效 → `file_id` 升序」排序，
取前 N 份。⇒ 触顶时**丢的是排序靠后的**，不是随机丢的。

---

## 4. 8 条专项测试：输入与预期结果

> ★ 下列材料**全部是合成样例**，**不是**真实业务材料。
> ★ 真材料仍由**刘江在授权的 Windows 环境**里用（`--allow-real-material`）。
> ★ 本地跑测试的命令：
> ```powershell
> cd backend
> $env:PYTHONPATH="src"
> .\.venv\Scripts\python.exe -m pytest tests\test_dd_v1_ddv1_p0_round3.py -p no:cacheprovider -q
> ```

| # | 用例 | 输入（合成材料 + 清单） | 预期结果（**逐条可核**） |
|---|---|---|---|
| ① | 单主体单文件 | `合成甲控股母公司/营业执照2024.txt` ＋ 清单「请提供合成甲控股母公司2024年度营业执照」 | 判定 `MATCHED`；交付 **1** 件；manifest 逐行带「类型/主体/期间匹配＝是」＋匹配证据；`07-文件完整性校验结果.tsv` 结论全「是」；7 项交付链产出齐备 |
| ② | 多主体混合 | 母公司与子公司各一份营业执照 ＋ 两条清单各指名一个法人 | 两条义务各自 `MATCHED`；**交付的两行不得互换**（母公司的义务 ⇒ 母公司的材料） |
| ②b | 母子错配 | **只有**子公司材料，清单要母公司 | 判定**不得**是 `MATCHED`；交付 **0** 件；缺口明细里指得出「主体」这一维 |
| ③ | 跨年度材料 | 2023 与 2024 两份审计报告，清单要 2023 | 2024 那份**不得**被选中（期间对不上） |
| ③b | 无年度标注 | 一份**文件名与正文都没有年度**的执照，清单要 2024 | 判定**不得**是 `MATCHED`；缺口明细里出现「期间不可判定」（**不得臆造年份**） |
| ④ | 一条需求多份 | 两份执照，清单明文「3 份」 | 显示 **「应交 3 / 找到 2 / 缺 1」**；判定**不得**是 `MATCHED`（找到 2 份**不等于**完成） |
| ④b | 多 part 需求 | 一份审计报告（**无附注**），清单「审计报告（含附注）」 | 显示 **「应交 2 / 找到 1 / 缺 1」**；判定**不得**是 `MATCHED` |
| ⑤ | 缺失材料 | 库里没有那一类材料 | 判定 `MISSING`；缺口清单写出「缺口：缺…」**并列出实际候选池** |
| ⑤b | 同类但年份不对 | 2023 审计报告，清单要 2024 审计报告 | 判定 `STALE`（**不是** `MISSING`——库里**有**这一类） |
| ⑥ | 错误匹配 | 执照 + 纳税证明，清单要执照 | 纳税证明**不得**进选中集合；「未选用清单」里写明**哪一维对不上** |
| ⑦ | 审核不确定 | 审计报告（按设计收紧） | 交付 **0** 件；组包manifest **无**该行 |
| ⑦b | 候选包/正式包隔离 | 同上 | 候选包目录里有「非正式交付-候选包说明.md」且**零原件**；正式交付包在**另一个平级目录**（`<data_dir>\deliveries\<review_id>\`） |
| ⑧ | 不同披露等级混合 | 执照（可外发）＋ 审计报告（受限） | 只交付执照那一行；审计报告进「被拦截清单.json」且带 `blocked_by` ＋ `blocked_kind`（**按设计被拦**）；放行行也带 `披露_策略版本` / `披露_可外发类型` |

---

## 5. 交付链的 7 项产出（**缺一不可**）

| # | 文件 | 内容 |
|---|---|---|
| ① | `01-输入需求清单.tsv` | 每条原子义务：机构编号 / 原文 / 义务ID / 主体 / 期间 / 类型 / 应交 / 找到 / 缺 / 交付闸 |
| ② | `02-检索材料清单.tsv` | 每份候选：file_id / 原始路径 / 文件名 / SHA256 / 主体 / 期间 / 材料类型 / 全部类型 / 敏感等级 / 被几条义务引用 |
| ③ | `03-匹配结果及理由.tsv` | 每条义务 × 每份候选：判定 / 三维匹配 / 匹配证据 / 选中与否 / 理由 / 审核结论 / 交付位置 |
| ④ | `04-缺失冲突不确定清单.tsv` | 缺失 / 冲突 / 不确定 / 不完整 / 过期 / 受限，逐条带缺口明细与候选数 |
| ⑤ | `05-人工审核记录.tsv` | 单据批准人 / 逐条确认（谁 + 理由）/ 修改留痕 |
| ⑥ | `06-实际交付文件目录.tsv` | 每个交付文件的相对路径 / 字节数 / SHA256 / 源 SHA256 / 一致与否 / 对应义务ID |
| ⑦ | `07-文件完整性校验结果.tsv` | **逐件复制后读回复算**的 SHA256 与源 SHA256 比对 |

**外加**：`组包manifest.tsv`（**原始材料 → 匹配义务 → 审核结论 → 交付位置** 的追溯链，
每行带 file_id / 义务ID / 原始路径 / 两侧 SHA256 / 披露归因）、
`SHA256SUMS`（可 `sha256sum -c` 直接核）、`正式交付包-说明.md`、
`未过闸清单.tsv` / `未过闸明细.json` / `未选用清单.tsv` / `被拦截清单.json`。

★ **未获得有效审核授权时**：只产出 ①–⑤ ＋ 候选验证信息（在候选包目录里），
**不生成正式交付件**，**不复制任何原件**。

---

## 6. 版本与可复核信息

| 项 | 值 |
|---|---|
| 分支 | `feat/71-player2-p0-fix-20261023` |
| 基座 | `7dd66b00149883efe1abdb63d647012211531800` |
| 本轮 sha | 见同目录 `SHA256SUMS` 与 `EVIDENCE.md`（**以交卷件 PR comment 为准**） |
| 专项测试 | `backend/tests/test_dd_v1_ddv1_p0_round3.py`（18 条） |
| 复跑命令 | `cd backend` → `$env:PYTHONPATH="src"` → `.\.venv\Scripts\python.exe -m pytest tests\test_dd_v1_ddv1_p0_round3.py -p no:cacheprovider -q` |
| 全量命令 | `cd backend` → `$env:PYTHONPATH="src"` → `.\.venv\Scripts\python.exe -m pytest tests\ --ignore=tests\test_doctor_script.py -p no:cacheprovider -q` |

★ `tests\test_doctor_script.py` 按**仓规**排除（需本机 `.env` 与前端 `node_modules`），
**不算作「通过」**。
