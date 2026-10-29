# DD-V1 考场 V1 · Windows 交接包（刘江侧）

> **适用分支**：`feat/71-ddv1-exam-v1-20261028`
> **读者**：刘江（Windows 授权环境）｜**本包不含任何真实业务材料**
> **依据**：`cangjie-fos#85`（永久验收红线）、`cangjie-teams-channel#108`（正式交办）
> **纪律**：本包只讲**怎么跑、怎么看、怎么反馈**；凡是需要你决定的事，
> 都写成了**带默认值的命令**——不确定就先跑默认，把输出回给我。

---

## 0. 一页操作指南（打印这页就够）

★ 全部命令在**仓库根目录**的 PowerShell 窗口里跑；
★ 脚本自己会把 `backend\src` 加进导入路径，**不需要**设 `PYTHONPATH`。

| 步骤 | 做什么 | 命令 | 怎么判断成功 |
|---|---|---|---|
| ① 版本 | 确认拿的是**本包对应版本** | `git rev-parse HEAD` | 40 位 SHA 与 §6 **逐位相同**；**不一致就停测并报告** |
| ② 环境 | 诊断（**先 doctor，后起后端**） | `python tools\doctor.py` | 末尾无红色 `FAIL`；DD-V1 相关项 `OK` |
| ③ 起后端 | 起 FOS 后端 | `安装并启动.ps1` 或 `点击开始-仓颉FOS.bat` | `http://127.0.0.1:8000/health` 返回 200 |
| ⓪ **登记材料库** | ★ 登记授权材料目录（**主体登记的前提**） | `python tools\dd_v1_manifest.py register --library "<库名>" --root "<材料目录>" --authorized-by "<你>"` | 打印「已登记」 |
| ④ 登记主体 | 母/子公司登记（**必须先于首次摄取**） | 见 §0.1 | 打印「已登记」 |
| ⑤ **考场预检** | ★ 开考前 Gate：考卷/图书馆/标准答案 三者是否正确关联 | `python tools\dd_team_channel.py preflight --contract "<考场契约.json>"` | 终端打印「**具备正式评分条件**」；否则按它列的**阻塞原因**补齐，**不要硬跑** |
| ⑥ 组包 | 跑一次组包 | `python tools\dd_team_channel.py run --library <库名> --root "<材料目录>" --checklist "<清单.tsv>" --institution "<机构名>" --by "<你>" --anchor-year 2024 --contract "<考场契约.json>" --resolve-doc-type --package --approved-by "<批准人>" --package-out "<交付目录>" --out "<报告目录>"` | 终端出现「✓ 交付包已生成」＋「复制原件数 N」＋「✓ 已按考场契约声明的主体范围落到 N 条未指名主体的义务」 |
| ⑦ **机器答卷** | 产出逐题答卷（理解/候选/选中/交付/弃答原因） | `python tools\dd_team_channel.py answer --bridge-json "<报告目录>\尽调结果-*.json" --delivered "<交付目录>\组包manifest.tsv" --exam-id "<考场ID>"` | 打印「机器答卷已生成」＋义务/已理解/已作答/交付件数 |
| ⑧ **自动阅卷** | 隔离阅卷 ⇒ 0—100 成绩单 | `python tools\dd_team_channel.py grade --contract "<考场契约.json>" --answer "<机器答卷.json>"` | 打印 7 项指标 + 总分 + 安全闸结论 |
| ⑨ **版本对比** | 旧版 vs 新版 | `python tools\dd_team_channel.py compare --old "<旧成绩单.json>" --new "<新成绩单.json>"` | 打印「指标｜旧版｜新版｜变化」表 |
| ⑩ 核完整性 | 逐件复算 SHA256 | `cd "<交付目录>" && certutil -hashfile "<文件>" SHA256` | 与 `组包manifest.tsv` 的「副本sha256」**逐位相同** |
| ⑪ 反馈 | 把**文本**回给我 | 见 §7 | 不截图；直接贴文本，便于逐字核对 |

### ★ ⓪ 为什么「登记材料库」要排在「登记主体」前面

**主体登记是挂在某个库上的**（`entity --library "<库名>"`）：
库里还没有这个库名 ⇒ 登记**不生效** ⇒ 组包时那句
「⚠️ 尚未登记**权威主体名单**」照样出现 ⇒ 上轮 42 题 91 条义务**全部 UNCERTAIN、0 交付**。
⇒ **顺序必须是：登记库 → 登记主体 → 跑组包**。

### ★ ⑦ `--delivered` 为什么必须给

「**实际交付件数**」是阅卷的硬规则（HR-1：0 交付 ⇒ 强制 0 分），
它**只认**组包产出的那份 `组包manifest.tsv`（人工也是拿它逐件核哈希的那一份）。
★ 没给 `--delivered` 且机读产物里也没有交付清单 ⇒ 系统**按 0 件交付算** ⇒ 成绩单会是 0 分
——**那是「没证据」，不是「没交付」**。
⇒ **交付目录下的 `组包manifest.tsv` 必须原样传给 ⑦。**

### ★ ⑥ `--resolve-doc-type` 什么时候要加

规则层能从清单原句里读出材料类型（「审计报告」「营业执照」…）时**不需要**加。
**清单里没有类型关键词**的那些题（例如「提供主体甲 2024 年度审计报告」以外的表述、
或干脆是「说明材料」），规则层会**判不出要哪类材料** ⇒ 这类题要交给**模型**判
（模型必须给出 `proposed_doc_type`，且与自己挑的文件类型自洽，否则被拒）。

★ **本开关默认关闭**：关着时既有「六态口径」（为什么没有候选）与既有成本纪律**一字不变**。
★ **真实 42 题**里有类型待判定的题 ⇒ **⑥ 必须带 `--resolve-doc-type`**，
否则那些题**不会进模型**（模型看不到 ⇒ 永远判「没理解」）。
★ 打开后终端会多一行「类型待判定：N 条」——把那个数字**回给我**，我要核对它对不对。

### ★ ⑥′ 本版（2026-10-29 接线轮）新增的四个开关

> 上一版把三个模块写好了、也测过了，但**生产链路零调用方** ⇒ 真实组包里根本没生效。
> 本版把它们**接进真实组包链**，并加了四个开关让你**自己控制**要不要用。

| 开关 | 加在哪个命令 | 作用 | 不加会怎样 |
|---|---|---|---|
| `--agent <codex\|pi\|dsh\|manual\|prebaked>` | `run` | 让**本机**的 Harness 参与语义判断（材料**不出本机**） | 全程 `RULE_ONLY`（默认，零调用、零费用） |
| `--agent-result "<回执.json>"` | `run` | 把**别处跑出来的**回执贴进来（审阅用） | 同上 |
| `--confirmed-entity-map "<映射.json>"` | `run` | **人工确认**「某份材料属于哪个主体」的映射表 | 多源认不出 ⇒ 保持「认不出」（**不猜、不放行**） |
| `--no-expand-candidates` | `run` | 关掉「候选触顶后继续分批扩展」 | 默认**开**（会把触顶义务的候选查完并如实报「还剩多少没看」） |

★ **四个开关都默认「不改变既有行为」**：
不加 `--agent` ⇒ `examinee.mode = RULE_ONLY`（与上一版逐位一致）；
不加 `--confirmed-entity-map` ⇒ 主体维度与上一版逐位一致；
不加 `--no-expand-candidates` ⇒ 只是**多看一些候选**（不改判定逻辑、不改安全闸、不改人工批准）。

★ **`--agent` 的取值决定「参与类别」，而类别只由适配器**实现**决定、不采信自填字段**：

| `--agent` | `examinee.mode` | 含义 |
|---|---|---|
| `codex` / `dsh` / `pi` | `HARNESS_MODEL` | 本机 Harness 真的跑过 ⇒ 有回执 |
| `manual` | `HARNESS_MANUAL` | 人工换入（不是模型） |
| `prebaked` | `PREBAKED_RESULT` | 贴进来的回执 ⇒ **不是** Harness 运行 |
| 其它/替身 | `UNKNOWN_ADAPTER` | **不得**计为「模型参与」的凭据 |
| 无适配器 | `RULE_ONLY` | 全程规则 |
| 有模型选材但**没回执** | `MODEL_SELECTION_WITHOUT_RECEIPT` | 必须被标出来 |

★ **本沙箱/云端跑不出 `HARNESS_MODEL`**（没有文本生成模型）⇒ **真实 MODEL 凭据只能由你在本机跑出来**（见 §8）。

### ★ 顺序纠正（`#108` 实测 P1-3）

**旧文档写的是「先起后端，再跑 doctor」——那是错的**：
doctor 会检查「端口 8000 是否空闲」，后端起着就必然报红。

**正确顺序**：**② doctor（端口空闲时跑）→ ③ 起后端 → 之后 doctor 再跑也判 OK**
（本版 doctor 已改：8000 端口上是**本仓后端**时判 **OK**，不会误杀你的进程）。

### ★ ⑤ 考场预检为什么必须先跑

预检会**在开考前**把「必然失败」的原因顶出来，例如：

- **标准答案没接入**（`#74` 交办已暂停）⇒ 打印 `TEST_BLOCKED_GOLD_NOT_PROVIDED`。
  ★ 这**不等于**「历史上没有标准答案」——是**没拿到包**，也没**映射**到本考场。
  ⇒ 这种状态下可以跑**诊断试跑**，但结果**必须**标「**非正式评分**」，
  **不得**当成业务成绩。
- **主体范围没声明** ⇒ 打印 `ENTITY_SCOPE_UNDECLARED`。
  ★ 上轮 42 题 91 条义务**全部 UNCERTAIN、0 交付**，根因就在这里：
  库里登记了多个主体，而清单里那些**没指名主体**的要求**无法判定该问哪一家**。
  ⇒ 在考场契约的 `entity_scope` 里写清楚：
  `{"scope_mode": "GROUP", "group_root_id": "E01"}` 或
  `{"scope_mode": "SINGLE_ENTITY", "entity_ids": ["E01"]}`。
  ★ **不要**指望「没写主体就算集团所有公司都算」——那是错的，系统不会那样放行。

---

## 1. 考场契约（新增，一份 JSON）

预检、阅卷都靠它。模板：

```powershell
python tools\dd_team_channel.py contract-template --out "<输出目录>"
```

改三处：

```json
{
  "exam_id": "EX-2026-10-28-01",
  "name": "<机构> 尽调清单 <年份>",
  "institution": "Institution_XX",
  "checklist": { "checklist_id": "CL-...", "library_id": "<你的库名>",
                 "sha256": "<考卷指纹>", "item_count": 42 },
  "library":   { "library_id": "<你的库名>", "material_root": "<材料目录>",
                 "fingerprint": "<图书馆指纹>", "material_count": 1663 },
  "gold":      { "gold_pack_id": "GOLD-...", "manifest_path": "<标准答案包清单.json>",
                 "provided": true },
  "entity_scope": { "scope_mode": "GROUP", "group_root_id": "E01",
                    "declared_by": "<你>", "declared_at": "<北京时间>" }
}
```

★ **标准答案包清单**（`dd_v1_gold_manifest.v1`）长这样（**放受控 Data Plane，不进 Git**）：

```json
{
  "schema_version": "dd_v1_gold_manifest.v1",
  "gold_pack_id": "GOLD-2026-10-28-01",
  "exam_id": "EX-2026-10-28-01",
  "checklist": { "checklist_id": "CL-...", "sha256": "<考卷指纹>", "item_count": 42 },
  "library": { "library_id": "LIB-...", "fingerprint": "<图书馆指纹>", "material_count": 1663 },
  "confirmed_by": "刘江",
  "confirmed_at": "2026-10-28T18:00:00+08:00",
  "items": [
    { "obligation_id": "<义务ID>", "item_no": "1.1", "expected_verdict": "MATCH",
      "expected_files": [
        { "sha256": "<该材料正文的 SHA256>", "relative_path": "<人工交付包里的路径>",
          "entity": "<主体>", "period": "2024", "doc_type": "audit_report" }
      ] }
  ]
}
```

★ **只认 SHA256，不认文件名** —— 人工包里的文件与图书馆里的文件
**名字不同、路径不同但内容相同**，系统按内容指纹对上。
★ `confirmed_by` / `confirmed_at` **必填**（可写在清单级，逐条写更严）；
缺了 ⇒ 预检报 `TEST_BLOCKED_GOLD_NOT_CONFIRMED`，**不进正式评分**。

★ ★★ **`obligation_id` 必须和机器答卷里的义务 ID 逐字相同**（实测踩过）：
标准答案的义务 ID **不是**「1.1」「R1-O1」这种清单编号，而是**本次运行**里
那条义务的**真实 ID**（跑完 ⑥ 之后，在 `尽调结果-*.json` 的
`semantic_bridge.obligations[].obligation_id` 里能逐字抄到）。
⇒ **正确顺序**：先跑 ⑥⑦，拿到答卷里的义务 ID，**再**按那个 ID 写标准答案清单。
★ 对不上的后果**不是报错**，而是**每题都判 `NO_ANSWER`、总分 0**——
很难一眼看出是 ID 没对上，所以**先照抄**。

---

## 2. 主体登记（沿用上轮，但有一条新规矩）

上轮的硬要求全部保留（`--relation` 只认 `parent` / `subsidiary`；
别名**不得**登记成 `--kind DIRECTORY`；主体登记**必须先于首次摄取**）。

★ **本版新增**：如果材料目录**不携带法人级**（用的是
`四川及湖南、北京子公司营业执照` 这类**分类目录**），
系统会**认不出材料的主体** ⇒ 候选里会出现「主体未登记」。
这时**不要**去把分类目录登记成别名（那是分类维度）——
正确做法是：把**法人全称**登记成主体，并在**考场契约**里声明 `entity_scope`；
材料侧主体则由**文件名 / 正文 / 可信元数据**认领（认不出就如实报「认不出」，
系统**不会**拿目录名凑数）。

---

## 3. 阅卷结果怎么读（`#85` 的口径）

| 状态 | 含义 | 你该做什么 |
|---|---|---|
| `SCORED` | **有有效标准答案，已出分** | 正常看分 |
| `LOW_CONFIDENCE` | 已出分，但义务条数 < 30 | 分可参考，样本量不足 |
| `NOT_SCORABLE` | **客观不可评分** | 看 `blocked_by`：缺标准答案 / 没映射 / 没人工确认 / 对应关系冲突 / 检出泄漏 |

★ **0 分就是 0 分**：有有效标准答案而机器 **0 件交付** ⇒ 成绩单**报 0 分**
（`status` 仍是 `SCORED`），**不是** `NOT_SCORABLE`。
★ **安全闸独立计分**：错主体 / 受限资料误交 / 未经批准交付 / 哈希不一致
**单列**在 `safety_gate`，**不得**用高业务分抵消（命中时总分封顶 59）。
★ **「交付」与「选中」分开记**（★ 独立 Reviewer 增量复核后收紧，**别按旧口径理解**）：
· **实际交付**的件错了主体 ⇒ **进安全闸 ⇒ 封顶 59**（法律事实，必须拦）；
· **只是选中、没交付**的件错了主体/年份 ⇒ **单列** `selection_mismatches`、
**不封顶**（属选材质量问题；把它算成交付事故＝成绩单虚报事故并封顶）；
· **期间（年份）只影响单列指标**（`selection_mismatches`），**不进安全闸、不封顶**
  （派生元数据口径差异不算机器交错年份）；**主体**才是进安全闸封顶的那一项。

---

## 4. 产物清单

| 产物 | 位置 |
|---|---|
| 预检报告 | `<数据目录>\考场\预检-<exam_id>-<时间戳>.md` / `.json` |
| 机器答卷 | `<数据目录>\考场\机器答卷-<时间戳>.json` |
| 成绩单 | `<数据目录>\考场\成绩单-<时间戳>.json` |
| 版本对比 | `<数据目录>\考场\版本对比-<时间戳>.md` / `.json` |
| 交付链 7 个 TSV + manifest + SHA256SUMS | `<交付目录>`（沿用上轮） |

★ 全部落在**数据面**（`CANGJIE_DD_V1_DATA_DIR`，默认 `backend\data\dd_v1`），
**不进 Git**。

---

## 5. 本版相对上一版的**实测**变化

| 项 | 上一版（`abc4627`） | 本版 | 本版**是否已接线** |
|---|---|---|---|
| 真实 42 题 | 91 义务全 UNCERTAIN、**0 交付**、NOT_SCORABLE ×42 | 见 §6 的**本机实测读数** | ★ 业务成绩仍 `NOT_SCORABLE`（标准答案包未交付） |
| 标准答案状态 | 「未提供」与「未接入」**混为一谈** | **四种状态分开报**（未提供/未映射/未确认/冲突） | ✅ 已接线 |
| 考场预检 | **没有** | **有**（`preflight`），开考前就能拦 | ✅ 已接线 |
| 材料类型判不出 | 整条**丢弃**（0 义务） | 交给**模型**判定（`proposed_doc_type`）＋**自洽性**校验 | ✅ 已接线（`--resolve-doc-type` 打开）★ 只验**自洽性**，**不证伪「这是规则脚本」** |
| 主体范围 | 多主体 + 未指名 ⇒ **全盘 UNCERTAIN** | 契约**显式声明** ⇒ 可判定；未声明仍**保留不确定** | ✅ **已接线**（`run --contract`）★ **务必带上 `--contract`**，否则这条补救**不生效** |
| 主体识别 | 只认目录名 | 文件名 / 正文 / 元数据 / 人工确认 **多源分级** | ✅ **已接线**（`run` 走真实组包链；只在主口径「认不出」时**补位**，主口径已判命中/他法人的**一律不动**）★ 认不出仍认不出（**不猜、不放行**）｜人工确认映射：`--confirmed-entity-map` |
| 候选上限 20 | 触顶只报数 | 触顶**如实报数**（找到/检查/未看/为什么停） | ✅ 读数已接线｜✅ **分批扩展本版已接线**（触顶义务自动分批放大窗口；读数在机读 JSON **顶层** `candidate_expansion`；可 `--no-expand-candidates` 关） |
| 机器答卷 | **没有** | **有**（逐题来源证据 + SHA256 ＋ 交付清单） | ✅ 已接线 |
| 0—100 成绩单 | **没有** | **有**（冻结口径，含安全闸独立计分；安全闸**只对实际交付的件**封顶） | ✅ 已接线 |
| `doctor --fix` | Windows 上**崩**（npm 裸名） | **已修** | ✅ |
| `安装并启动.ps1` | 5.1 下**乱码语法错**（无 BOM） | **已修**（加 UTF-8 BOM） | ✅ |

★ ★ **「本版是否已接线」这一列是独立 Reviewer 2026-10-29 复核后加的**：
它把「**模块写了、有单测**」与「**产品路径上真的生效**」分开。
⇒ 凡标 ⚠️ 的项，**不要**在真机上指望它改变结果。

---

## 6. 版本与可复核信息

- **分支**：`feat/71-ddv1-exam-v1-20261028`
- **基线**：`abc462747e99171415dc405e735773fd9d1335d1`（上一版冻结版本）
- **本包 SHA**：见提交信息（本 PR 的 head）；**用 `git rev-parse HEAD` 逐位确认**
- **冻结评分口径**：`backend\config\dd_v1_exam_scoring_spec.v1.json`
  （公式 / 权重 / 分母 / 安全闸上限；**开考前冻结**，换尺子必须换版本）

---

## 8. 模型参与（MODEL）与规则参与（RULE_ONLY）——本版新增（2026-10-29 接线轮）

★ **本节回答一件事**：怎么才能拿到一份**真的由模型参与**的答卷，以及**别把规则跑出来的东西说成模型**。

### 8.1 本机跑出真实 MODEL 凭据（推荐路径：材料不出本机）

```powershell
# ① 用你本机已有的 Harness（Codex / DeepSeek / pi）跑一次语义判断
#    适配器会把**回执**写出来（adapter_id / vendor / calls_used / raw_digest / provenance）
# ② 把回执路径交给组包命令
python tools\dd_team_channel.py run `
  --library "<库名>" --root "<材料目录>" --checklist "<清单.tsv>" `
  --institution "<机构名>" --by "<你>" --contract "<考场契约.json>" `
  --resolve-doc-type --agent codex `
  --package --approved-by "<批准人>" `
  --package-out "<交付目录>" --out "<报告目录>"
# ③ 核参与类别（在机读结果 JSON 顶层）
#    examinee.mode 应为 HARNESS_MODEL
#    agent_receipt.provenance 应为 HARNESS_MODEL
#    agent_receipt.provenance_source 应为 ADAPTER_IMPLEMENTATION
#    agent_receipt.implementation_verified 应为 true
```

★ ★ **参与身份怎么判定的（别自填就信）**：
  `provenance`（权威）**按适配器实现类**判定，**不看** `adapter_id` 字符串
  ⇒ 自填 `adapter_id="codex-cli"` 的替身**拿不到** `HARNESS_MODEL`。
  回执里另有三处可核验字段：
  - `declared_provenance`：id 级**声明**（只是旁证，不构成参与主张）；
  - `provenance_mismatch`：声明与实现**不一致** ⇒ 会显式标出来；
  - `executable` / `argv_digest` / `workdir_digest`：**运行痕迹**（跑了什么的指纹，不含材料内容）。

★ **材料不出本机**：适配器跑的是**你本机**的 CLI ⇒ 不向未授权外部模型发送保密资料
（本版**没有**新增任何付费 API，**没有**改生产配置）。
★ 若你要**审阅**别处跑出来的结果 ⇒ `--agent-result "<回执.json>"` ⇒ 类别会是
`PREBAKED_RESULT`（**不是** Harness 运行）⇒ **不会**被当成模型凭据。

### 8.2 「排除式凭据」怎么读（**别过度解读**）

模型除了「选了哪份」，还要**说清为什么没选别的**（`rejected_alternatives`：file_id + 理由）：

| 读数 | 含义 | **不能**推出什么 |
|---|---|---|
| `PASS` | 候选池含 ≥2 种材料类型、**没取第一个**、**记录了排除理由** | ⇒ **不能**推出「这个判断出自模型」（规则脚本也能写满排除理由） |
| `WEAK` | 池里只有一种类型 / 取了第一个 / 没记录排除理由 | ⇒ 说明**排除式证据不足**（不代表判断错） |

★ 这条读数只证明「判断**不是照抄第一个候选**」；「是不是模型做的」由
`examinee.mode` ＋ `agent_receipt`（**适配器实现**说了算，**不采信自填字段**）。

### 8.3 拿不到 MODEL 时的正确说法

云端/沙箱**没有文本生成模型** ⇒ 本版在云端跑出来的永远是 `RULE_ONLY`（或 `UNKNOWN_ADAPTER`）。
⇒ **回传给我时请照实写 `examinee.mode`**；**不要**把 `RULE_ONLY` 说成「模型判的」，
也**不要**把 `PREBAKED_RESULT` 说成「Harness 跑的」。

---

## 7. 反馈格式（不要截图，贴文本）

1. `git rev-parse HEAD` 与 `git status --porcelain` 的**脱敏**输出；
2. `preflight` 的**完整终端输出**（含 `blocked_by` 全量）；
3. `grade` 的**完整终端输出** ＋ 成绩单 JSON；
4. 交付链 7 个 TSV 的**行数**、`组包manifest.tsv`、`SHA256SUMS`；
5. 任何 FAIL：贴【失败步骤、脱敏错误、版本 SHA、需要谁协助】。

★ **不要**上传真实 DOCX / 客户身份 / 机构内部材料 / 明文凭证 / 含隐私的全量终端日志到 GitHub
（`cangjie-fos` 是**公开仓**）。
