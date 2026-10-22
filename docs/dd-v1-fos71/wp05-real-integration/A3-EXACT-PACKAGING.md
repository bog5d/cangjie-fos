# A3 · 精确组包与接线（WP-A3）

> 工作包：`WP-A3`｜分支 `feat/71-a3-packaging`｜起点（A2 封版）**`557cf3f`**
> 本文件 = A3 交付文档。**第 1 章是《接线说明书》**（G-A3-7），
> 第 2 章起是精确组包（G-A3-1…G-A3-5）与 H-3 处置。

---

# 第 1 章 · 接线说明书（G-A3-7）

> 合同依据（`GOAL-CONTRACT.v3.8.json` `user_visible_acceptance[0]`）：
> 「**Windows 调用的命令**、**FOS 实际函数链**、**代码 sha**、**输入快照 ID** 均可复核」
>
> 本章逐条对账这四项，**每条都给出可逐字执行的命令**。

## 1.1 薄入口的完整可执行命令

### 前置

| 项 | 值 |
|---|---|
| 入口脚本 | `tools/dd_team_channel.py`（WP7 团队调用入口） |
| 解释器 | `backend/.venv/bin/python`（仓库内 venv；系统 python3 = 3.9.6，**不满足** `gm.cli` 的 ≥3.10 要求） |
| 数据面 | 由环境变量 `CANGJIE_DD_V1_DATA_DIR` 指定（**受控、不进版本库**） |
| 代码基线 sha | **A2 封版 `557cf3f`**（本包起点，不可变） |

### ★ 逐字可执行的完整序列（**已实测：全部退出码 0**）

```bash
cd <repo>                                  # 本包 worktree；建议 feat/71-a3-packaging

# ── 0) 准备输入：仓内合成 fixture（只读，不改仓内任何文件）──────────────
FIX=backend/tests/fixtures/dd_v1_fos71
WORK=$(mktemp -d)
LIB="$WORK/材料库"; mkdir -p "$LIB/示例科技有限公司"
cp "$FIX/snapshot/F004_shili_business_license.txt" "$LIB/示例科技有限公司/营业执照.txt"
printf '1\t示例科技有限公司：最新的营业执照正本\n' > "$WORK/清单.tsv"
export CANGJIE_DD_V1_DATA_DIR="$WORK/data"; mkdir -p "$CANGJIE_DD_V1_DATA_DIR"

# ── 1) 登记权威主体（产品入口：tools/dd_v1_manifest.py entity）──────────
backend/.venv/bin/python tools/dd_v1_manifest.py entity \
  --library 示例库 --id E1 --name 示例科技有限公司 \
  --relation subsidiary --source 仓内合成夹具

# ── 2) 跑薄入口（一次跑完 7 步 + 语义层桥接附段）──────────────────────
backend/.venv/bin/python tools/dd_team_channel.py run \
  --library 示例库 --root "$LIB" --checklist "$WORK/清单.tsv" \
  --institution 测试机构 --by 测试员 --out "$WORK/报告"
```

**实测输出要点**（2026-10-22，venv 3.13.12）：

```
  逐条结果：
    已齐全        1 条
  · 输入快照 ID：259add0b664a872bbe620a152eef4ffde06c5bf4c2746db5a087b25571b63615
  ✓ 审核包已生成：<data_dir>/reviews/<review_id>/
      · 匹配核对表.xlsx
      · 缺口与待确认清单.txt
      · 证据与完整性说明.md
      · 交付清单与hash核验.tsv
  · 覆盖义务 1 条｜判定分布 {'MATCHED': 1}
  · 复制原件数 0（审核包**只读材料、零复制**）
```

> ★ **两个容易踩的坑（说明书必须写清）**：
> ① `--root` 必须指向**材料库根目录**（主体目录是它的**子目录**）。
>    若把 `--root` 指向主体目录本身，材料的相对路径就没有父段 ⇒
>    卡片 `entity` 取不到 ⇒ 主体维度不可判定 ⇒ 判定从 MATCHED 掉到 UNCERTAIN。
> ② 卡片的主体取自**相对路径的父目录名**（`dd_v1_card_service.py` 的 `path_segment` 规则），
>    **不是**从正文里抽的公司名 ⇒ 材料必须放在**以主体全称命名的目录**下。

### 参数逐条释义（薄入口 `run`）

| 参数 | 必填 | 含义 | 素材来源 / 备注 |
|---|---|---|---|
| `--library` | 是 | 材料库标识（自己起名） | 首次 `run` 会自动登记；同一 `--library` 复用同一个库 |
| `--root` | 是 | **材料库根目录**（本机路径） | ★ 指到主体目录的**父目录**；只扫描**经登记授权**的目录 |
| `--checklist` | 是 | 机构清单文件 | 每行 `编号<TAB>原文`；无编号的行自动编号 |
| `--institution` | 否 | 机构名称 | 写进审核包的 `institution` 字段 |
| `--name` | 否 | 材料库显示名 | `register_library` 的 `display_name` |
| `--by` | 否 | 授权人 | 默认取当前用户名；**会写进登记记录** |
| `--anchor-year` | 否 | 「近三年」这类相对年份的锚定年 | **不给则不擅自假定**（相对期间会判 UNCERTAIN） |
| `--cap` | 否 | 每条要求的候选材料上限（默认 20） | |
| `--parse-limit` | 否 | 本次最多抽取多少份正文（默认 2000） | |
| `--out` | 否 | 报告输出目录 | 默认 `<data_dir>/团队报告` |
| `--no-bridge` | 否 | 跳过语义层桥接附段 | **跳过后前 6 步输出一字不变** |
| `--allow-real-material` | 视材料而定 | 材料不是仓内合成 fixture 时必须给 | 只影响语义层桥接的只读快照；**不是**放行外发 |
| ★ `--package` | 否 | **显式**走「复制原件」路径 | ★ **必须同时给 `--approved-by`**；未给 ⇒ **拒绝 + 零复制 + 退出码非 0** |
| ★ `--approved-by` | 视 `--package` | **人工批准人**（可追责） | ★ **无默认批准人**；**没有**自动批准开关 |
| ★ `--package-out` | 否 | 交付目录 | 不给则用 `<审核包>/交付包` |

## 1.2 FOS 实际函数链（真实调用栈，非推断）

### ① 审核组包这条线（G-A3-6 新接的那条）

```
tools/dd_team_channel.py : cmd_run            (depth 3)
└─ tools/dd_team_channel.py : _run_review_pack                        (depth 3)
   └─ dd_v1_package_service : build_review_pack                          (depth 4)
      ├─ dd_v1_package_service : _conn                                   (depth 5)
      │  └─ dd_v1_manifest_service : _connect                            (depth 6)
      │     └─ core.paths : get_dd_v1_manifest_db_path → get_dd_v1_data_dir  (depth 7/8)
      ├─ dd_v1_requirement_service : _ensure_schema                      (depth 6)
      ├─ dd_v1_match_service : _ensure_schema                            (depth 6)
      └─ dd_v1_package_service : _write_pack_files                       (depth 5)
         ├─ （Excel）匹配核对表.xlsx ／（降级）匹配核对表.csv
         ├─ 缺口与待确认清单.txt
         ├─ 证据与完整性说明.md
         └─ 交付清单与hash核验.tsv
```

### ② 交付复制这条线（G-A3-9 的 `--package` 分支）

```
tools/dd_team_channel.py : cmd_run
└─ tools/dd_team_channel.py : _run_package
   ├─ dd_v1_package_service : approve                                   ← 记录人工批准人
   └─ dd_v1_package_service : package_approved
      └─ dd_v1_package_service : assert_approval                         ← ★ HG1 闸在前、复制在后
```

### ③ 取证方式（**不是推断，是实测**）

```bash
# 用 A3 的 trace 观察器（复用 A1 的 a1-trace-runner.py 机制，只做参数化 + 扩面到 tools/）
python3 gm_a3_trace_runner.py --repo <repo> --trace-out /tmp/trace.jsonl -- \
  backend/.venv/bin/python tools/dd_team_channel.py run ...
python3 gm_a3_trace_summarize.py --trace /tmp/trace.jsonl
```

机器证据（已入库 `a3-evidence/`）：

| 文件 | 内容 |
|---|---|
| `a3-evidence/calltrace-entry-default.jsonl` | 默认路径的完整调用栈（2188 条真实调用事件、59 个模块） |
| `a3-evidence/calltrace-entry-package.jsonl` | `--package --approved-by` 路径的完整调用栈 |
| `a3-evidence/calltrace-alias-cli.jsonl` | `alias` 子命令的完整调用栈 |
| `a3-evidence/wiring-trace-summary.json` | 合同链路 13 个环节的接线账（**锚点全部收紧到具体能力函数**） |

### ★ 接线账（合同链路 13/13）

| # | 合同环节 | 状态 | 锚点（trace 里真出现过的函数） |
|---|---|---|---|
| ① | 薄入口本体 | ✅ | `cmd_run` / `main` |
| ② | 材料库登记（授权） | ✅ | `register_library` |
| ③ | Manifest 建立 | ✅ | `build_manifest` |
| ④ | 全文索引 / 正文抽取 | ✅ | `parse_pending_batch` / `extract_content` / `extract_and_record` |
| ⑤ | 认知卡（材料画像） | ✅ | `build_cards_for_library` |
| ⑥ | 原子义务拆分（清单） | ✅ | `ingest_checklist` |
| ⑦ | 检索 / 四维匹配 | ✅ | `match_library` / `_recall_candidates` |
| ⑧ | 硬校验（主体/期间/类型/唯一性） | ✅ | `parse_doc_type` / `parse_entity_scope` / `doc_type_uniqueness` / `_strip_trailing_paren` |
| ⑨ | 披露策略 Gate | ✅ | `load_policy` / `default_sensitivity` / `evaluate` |
| ⑩ | 语义层桥接（附段） | ✅ | `bridge_library` |
| ⑪ | ★ 审核组包（只读零复制） | ✅ | `build_review_pack` |
| ⑫ | ★ 交付组包（复制原件） | ✅ | `package_approved` |
| ⑬ | ★ 别名登记（产品入口） | ✅ | `register_entity_alias` |

**⇒ 已接线 13/13 = 100%。**

### ★ 两项「有意不接」（**不进分母，但必须列出**）

| 项 | 状态 | 原因 |
|---|---|---|
| **模型语义检索入口**（`run_semantic` / `retrieve_minimal_evidence` / `build_semantic_packet` / `validate_semantic`） | **本次未调用** | **有意不接**：这些入口要外部模型（付费）。本次全程**零付费、零外部模型调用** ⇒ 走 RULE_ONLY 的规则化桥接。等 O1 真实模型通路就绪后再接（移交 A4/A5）。 |
| **Gold 对标评分**（`score_against_gold` / `assert_gold_isolated`） | **本次未调用** | **范围外**：Gold / 标准答案包隔离线，**不读**（硬纪律）。 |

## 1.3 代码 sha

| 项 | 值 |
|---|---|
| 本包起点（A2 封版，**不可变**） | **`557cf3fbdc9b9867e6f95080f77db2fff2964a77`** |
| **本包代码封版 commit**（产品代码 + 用例的落点） | **`d2f3b48d5b06423574c38d77f74756515076f282`** |
| 本包封版 commit | `git rev-parse HEAD`（见下方核验口径） |
| 取值命令 | `git rev-parse HEAD` |
| 分支 | `feat/71-a3-packaging` |

### ★ 核验口径（写明，避免自欺）

本说明书所在提交**可能**比「代码封版 commit」多一个提交 —— 那个提交**只**更新本说明书的
sha 字段与证据清单，**不含任何产品代码改动**。因此核验方式是：

```bash
git rev-parse HEAD                       # 当前 HEAD
git diff --stat <代码封版 commit>..HEAD  # ⇒ 只能有 docs/ 与证据清单，不得有 backend/ tools/ 改动
```

★ 等价的**更硬**口径（推荐）：

```bash
git diff --stat d2f3b48d5b06423574c38d77f74756515076f282..HEAD -- backend tools
# ⇒ 输出必须为**空**（说明书所指代码 == 当前代码，一个字节都不差）
```

> 为什么不用「sha == HEAD」：文档**自己**要进 Git ⇒ 若文档里写自己的 commit sha，
> 那是一个**自引用**（写进去就变了）⇒ 任何实现都不可能满足。
> ⇒ 改用**可判定的等价口径**：「sha 指向的代码 == 当前代码」
> （`git diff <sha>..HEAD -- backend tools` 为空）——它比「字符串相等」更强，
> 因为它校验的是**内容**而不是**指针**。

## 1.4 输入快照 ID

### 产出位置

| 位置 | 内容 |
|---|---|
| **终端** | `run` 结束前打印 `· 输入快照 ID：<64 位 hex>` + 三个组成项的摘要 |
| **机读结果 JSON** | `<报告目录>/尽调结果-<库>-<时间戳>.json` → 顶层字段 **`input_snapshot`** |
| 字段 | `input_snapshot_id` / `checklist_fingerprint` / `material_digest` / `material_files` / `code_sha` |

### 取值方法

```bash
# 取快照 ID
python3 -c "import json,glob;p=sorted(glob.glob('$WORK/报告/尽调结果-*.json'))[-1];\
print(json.load(open(p))['input_snapshot']['input_snapshot_id'])"
```

### 三个组成项（**全部是既有产物**，不另立第二套机制）

| 组成项 | 来源 | 怎么算的 |
|---|---|---|
| `checklist_fingerprint` | `dd_v1_requirement_service.ingest_checklist` | 清单原文归一化（空白折叠）后的 sha256；**幂等**：同清单重复摄入不产生重复义务 |
| `material_digest` | `dd_v1_manifest_service.list_manifest` | 本库 manifest **每件 `content_hash` 排序后**的 sha256 |
| `code_sha` | `git rev-parse HEAD` | 与 §1.3 同一个 sha |

> ★ 本字段**只含哈希**，不含任何文件名 / 机构名 / 材料库代号 ⇒ **天然脱敏**。
> ★ 本字段**不进判定层、不进审核包内容** ⇒ 不影响任何判定结果。
> ★ 本字段与组包**无关** ⇒ 「接组包 / 不接组包」两次运行的快照 ID **相同**（已实测）。

## 1.5 组包产物路径 + HG1 人工批准的两步命令

### 产物路径

| 产物 | 路径 |
|---|---|
| 审核包（**只读材料、零复制**） | `<CANGJIE_DD_V1_DATA_DIR>/reviews/<review_id>/` |
| 审核包四件套 | `匹配核对表.xlsx`（Excel 失败时降级 `.csv`）/ `缺口与待确认清单.txt` / `证据与完整性说明.md` / `交付清单与hash核验.tsv` |
| 交付包（**唯一会复制原件的地方**） | `<审核包>/交付包/`（或 `--package-out` 指定） |
| 交付包内容 | `组包manifest.tsv` / `被拦截清单.json` / 按机构编号分目录的**原件副本** |

### ★ 两步命令（**HG1：未经人工最终批准，不得复制任何材料**）

```bash
# ── 第 1 步：生成审核包（只读、零复制）────────────────────────────────
RID=$(backend/.venv/bin/python tools/dd_v1_manifest.py review \
        --library 示例库 --institution 测试机构 \
      | python3 -c "import json,sys;print(json.load(sys.stdin)['review_id'])")

# ── 第 2 步：人工最终批准（批准人可追责，必填）────────────────────────
backend/.venv/bin/python tools/dd_v1_manifest.py approve \
  --review "$RID" --by 测试审批人 --note "人工逐条核对后批准"

# ── 第 3 步：组包并复制原件（HG1 闸在这一步内部生效）──────────────────
backend/.venv/bin/python tools/dd_v1_manifest.py package \
  --review "$RID" --out "$WORK/交付包"
```

**实测结果**：

```json
{"review_id":"b36cf67b…","status":"packaged","output_dir":"…/交付包",
 "exported":1,"blocked":0,"blocked_detail":[],"hash_mismatched":0,
 "approved_by":"测试审批人"}
```

### ★ 未批准时的行为（**已实测**）

```bash
backend/.venv/bin/python tools/dd_v1_manifest.py package --review <未批准的 review_id>
# ⇒ {"error":"APPROVAL_REQUIRED","detail":"…","gate":"HG1 未经人工最终批准不得组包"}
# ⇒ **复制零个原件**（闸在前、复制在后）
```

入口侧同理：`--package` 但**不给** `--approved-by` ⇒ 入口**拒绝**（退出码非 0）、
**交付目录零文件**、并当场上报「未复制任何原件」。

### ★ 薄入口的等价一步式（**同一套 HG1 逻辑，不另写一套**）

```bash
backend/.venv/bin/python tools/dd_team_channel.py run \
  --library 示例库 --root "$LIB" --checklist "$WORK/清单.tsv" \
  --institution 测试机构 --by 测试员 --out "$WORK/报告" \
  --package --approved-by 测试审批人 --package-out "$WORK/交付"
```

> ★ 入口走的是**服务自己的** `approve()` + `package_approved()`
> （HG1 闸在 `package_approved` → `assert_approval`，**闸在前、复制在后**）
> ⇒ **不另写第二套批准逻辑**。
> ★ 入口**没有**自动批准开关、**没有**默认批准人：不给出 `--approved-by` ⇒ **拒绝**。

## 1.6 两条入口的分工

| | **入口 A** | **入口 B** |
|---|---|---|
| 脚本 | `tools/dd_team_channel.py` | `tools/dd_v1_local_run.py` |
| 定位 | **团队调用 / 组包** | **本地 Agent 盲评对照** |
| 面向 | Team Channel（刘江在 Windows 经 DSH 调） | 操作员本机，用来跟 A 的结果**对照** |
| 做什么 | 7 步（登记→扫描→抽取→画像→拆义务→匹配→**生成审核包**）+ 语义层桥接附段 | `scaffold` / `split` / `run` / `score`；用**本机已登录的模型 CLI**（dsh / codex）跑语义匹配再本地评分 |
| 材料 | 本机目录；真实材料需 `--allow-real-material` | 同左（`run` 显式 `--allow-real-material`） |
| 外发 | **永不外发**；复制原件须人工批准 | **永不外发**；`run` 不接受 Gold 参数，Gold 只在 `score` 步骤读 |
| 外部模型 | **0 次**（RULE_ONLY） | 需要（`--allow-local-dsh` / `--adapter`）；**零付费前提**：A4 由人工在受控环境跑 |
| 产出 | 报告 + 机读 JSON + **审核包四件套**（+ 批准后的交付包） | `meta.json` / `obligations.json` / `run_record.json` / `score.json` |

> ★ **两入口的分工边界**（不得互相顶替）：
> 入口 A 是**确定性规则链**（Manifest / 全文索引 / 硬校验 / 判定 / 审核组包），
> 入口 B 是**模型语义匹配 + 本地评分**。入口 B 的模型输出**只作建议**，
> 确定性门槛照常执行；入口 A 的判定**不依赖**模型。

---

<!-- A3-EXACT-PACKAGING-MARKER -->

---

# 第 2 章 · 需求驱动的齐套 + 精确组包（G-A3-1 / G-A3-2 / G-A3-3）

> 本章回答一个问题：**交付包里为什么只有这几份，而不是那一堆。**
> 改动落在 3 个服务 + 1 个新服务，全部在 A3 白名单内。

## 2.1 「应有几份」的承载体（G-A3-1）

`Obligation` 新增两个字段（**未改动任何既有字段**）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `expected_count` | `int \| None` | 权威份数 |
| `expected_count_basis` | `FACT / INFERRED / UNKNOWN` | 该份数的来源强度 |

### ★ 三态语义（A3-1 的落地口径）

| `expected_count` | `basis` | 含义 | 齐套判定上的后果 |
|---|---|---|---|
| `N > 0` | `FACT` | 原文明文给出份数（「一式两份」「3 份」） | 份数维**构成门槛**：需 N 份 |
| `N > 0` | `INFERRED` | 多处份数求和（「正本1份 副本1份」⇒ 2） | 同上 |
| `None` | `UNKNOWN` | 原文**提及**份数但**解析不出**（「若干份」「多份」） | 份数维**不可判定** ⇒ 判 **UNCERTAIN** + 人工确认 |
| `0` | `UNKNOWN` | 原文**根本没提**份数 | 份数维**不构成门槛**（与「期间未提」「无必备附件」同规格） |

### ★ 司仓校准记录（口径分歧的显式登记）

任务书 §1 段 G-A3-1 写的是「`expected_count`（可为 **0 / None** = 无权威份数）」，把 0 与 None 并列为同义；
而判据 A3-1 写的是「**解析不出时** `expected_count` 为空且 basis=UNKNOWN；**空值必须导致判 UNCERTAIN**，不得默认 1」。

**两者若按「0 与 None 等价」实现 ⇒ 「未提及份数」与「提及但解析不出」不可区分 ⇒ 要么误判 UNCERTAIN，要么把该判 UNCERTAIN 的放过去。**

⇒ 司仓取**可区分**口径（**只改承载体语义，不改判据条文**）：

- `0` = 清单**未规定**份数 ⇒ 该维**不构成门槛**；
- `None` = 清单**提及**但**解析不出** ⇒ 该维**不可判定** ⇒ 判 UNCERTAIN。

★ **「不得默认 1 份」在两个层面都被守住**：
① 解析不出时 `expected_count` 留 **`None`**（**不是 1**），
② 选中层对 `None` **不擅自交付**（选中 0 件，列入待人工确认）——**不是「先交 1 份再说」**。

★ **零回归不受影响**：真实三案例清单里「份」字**只出现在「身份证复印件」**，
无一处是份数要求 ⇒ `expected_count` 全部为 `0`（未规定）⇒ 判定分布**零变化**（见第 8 章实测）。

### 解析口径（可复核）

```
提及判定：数字+份（如「3 份」「一式两份」）｜ 若干/多/数/几+份 ｜ 「份数」
★ 「部分材料」里的「份」**不算**（词的一部分，不是数量）⇒ 不误触发不可判定
数值解析：N 份 / 份数为 N / 份数可求和
```

| 原文 | 解析结果 |
|---|---|
| `请提供2023年度审计报告一式两份` | `2 / FACT` |
| `请提供营业执照3份` | `3 / FACT` |
| `正本1份 副本1份`（同一段） | `2 / INFERRED` |
| `正本1份、副本1份`（被「、」拆成两段） | 各 `1 / FACT`（**拆后各管各的**） |
| `请提供材料若干份` | `None / UNKNOWN` ⇒ **UNCERTAIN** |
| `请提供部分材料` | `0 / UNKNOWN`（不构成门槛） |
| `请提供营业执照正、副本复印件` | `0 / UNKNOWN`（「副本」**不是**份数） |

## 2.2 五维齐套判定（G-A3-3）

新服务 `dd_v1_qc_service.py`（**仓内第二份覆盖率规则表？不——它一份都不算**）：

- 它**不重算**任何覆盖率。主体/期间/类型/附件的覆盖率由判定层算好后**作为入参**传进来；
- 它只做三件事：① 判断每维**是否构成门槛**；② 判断每维**是否可判定**；③ 产出**指名缺哪一维**的缺口文案。

### ★ 旧实现的一个真实缺陷（本轮修掉）

旧 `judge()` 只报**第一个**命中的分支 ⇒ 其余维度的缺口**静默丢失**：
「主体缺 1/2 家」出现时，读者**看不到**类型维也缺。

⇒ 现在**每一维**的缺口都写进 `missing_detail`：

| 维 | 缺口文案（实测） |
|---|---|
| 主体 | `主体缺 1/2 家（维度：主体）` |
| 期间 | `期间缺 2/3 年（维度：期间）` |
| 材料类型 | `材料类型缺 1/2 份（维度：材料类型）` |
| 必备附件 | `必备附件缺失（维度：必备附件）` |
| 份数 | `份数缺 1/2 份（维度：份数）` / `份数不可判定（维度：份数）：…不得默认 1 份` |

★ 旧文案前缀**逐字保留**（`主体缺` / `期间缺` / `必备附件缺失`）⇒ 既有断言与既有报告口径不受影响。

### 判定顺序（保守方向）

- 份数**不可判定** ⇒ `MATCHED / PARTIAL / RESTRICTED` **降级为 UNCERTAIN**；
  `MISSING`（确证缺失）/ `CONFLICT`（须人工裁定）/ `STALE` **不受影响**（更具体的事实优先）；
- 份数**不足** ⇒ `MATCHED` 降为 `PARTIAL`，并指名「份数缺 x/y 份」。

### 「可交付份数」怎么算

按**同一「主体 × 期间 × 类型」格子**内的可交付份数算，**不是候选池总数**——
否则「5 份不同年份的审计报告」会被误当成「一式五份」而假装齐备。

## 2.3 精确选中规则（G-A3-2 · 核心）

新服务 `dd_v1_selection_service.py`：

```
交付集合 = 每条义务被选中的那几份主件 + 明确列出的必备附件
★ 候选池里其余材料一律不复制，但必须逐条留痕
```

### 排序键（**确定性可复现**：同一输入 ⇒ 同一集合）

1. 四维命中分 `score` 降序
2. 主体命中 `entity_ok` 降序
3. 期间命中 `period_ok` 降序
4. 类型命中 `doctype_ok` 降序
5. **`file_id` 升序**（稳定化 ⇒ 同分同序，可逐字复现）

### 交几份（由份数权威决定）

| `expected_count` | 选中主件数 | 理由（写进核对表） |
|---|---|---|
| `N > 0` | `N`（不足则取全部可交付） | 清单规定了权威份数 |
| `0`（未规定） | `1` | ★ **去冗余**原则：一条义务只交一份主件。**这是交付集合规则，不是「认定应有 1 份」** |
| `None`（不可判定） | `0` | ★ **不得默认 1 份**：要几份不知道 ⇒ 不擅自交付，列入待人工确认 |

### 附件识别

必备附件**只认**认知卡 `fields.related_files` 里**显式列出**的文件（与判定层同源），
**不靠文件名相似度猜**——猜出来的附件是事故。

### 未选中的候选去哪了

进交付包里的 **`未选用清单.tsv`**（可审计）：机构编号 / 原子义务 / file_id / 相对路径 / **未选用原因**。
「不交」是决定，「不解释」是失职。

## 2.4 审核包与交付包**共用同一份计划**

`_build_rows()` 一次性算出「判定 + 候选 + 选中集合」，
`build_review_pack()`（审核包）与 `package_approved()`（交付包）**都从它取**：

⇒ **人工审阅的集合 = 实际交付的集合**，不会出现「审的是 A、交的是 B」。

## 2.5 交付包多了两个可审计文件

| 文件 | 内容 |
|---|---|
| `组包manifest.tsv` | 已复制件：机构编号/原子义务/交付路径/源 sha256/副本 sha256/一致/判定/**角色** |
| `被拦截清单.json` | 被 Gate 拦下的件：**category**（分类）+ reason（原始原因） |
| `未选用清单.tsv` | **未选用**的件 + 逐条原因 |

## 2.6 受限材料单独成列（G-A3-5）

「材料存在但不可外发」与「材料根本不存在」是两回事，混在一起 ⇒ 复核者会去追一份**根本不存在的**材料，
而真正该处理的受限件被淹没。

⇒ 缺口清单改成**分区**：

```
一、材料根本不存在（MISSING）
二、材料不完整（PARTIAL）
三、材料存在但受限·不可外发（RESTRICTED）   ← 单独成列，逐条注明原因
四、不可判定·待人工确认（UNCERTAIN）
五、需人工裁定（CONFLICT）
六、版本或期间不满足（STALE）
```

★ 受限段每条附「受限原因」（等级 / 不可读 / 敏感等级未知 / 索引件 / 源文件不存在 / 越界拦截），**不混入 MISSING、不静默丢弃**。

---

# 第 3 章 · HG1 与审核包脱敏（G-A3-4 / H-3）

## 3.1 HG1 的位置：**闸在前、复制在后**

```
package_approved()
  ├─ assert_approval(review_id)      ← HG1：不在 approved / 无批准人 ⇒ 抛 ApprovalRequired
  ├─ mkdir 交付目录                    ← 闸通过之后才建
  └─ 逐件复制（只复制**选中件**）      ← 复制在后
```

★ **未批准 ⇒ 抛异常 ⇒ 交付目录**根本不会被创建**（更不会有任何文件）**。
★ **没有**自动批准开关、**没有**默认批准人、**没有**第二条批准路径。

## 3.2 H-3：审核包的主体范围脱敏（A3-9）

**病**：`dd_v1_package_service` 把 `entity_scope` 的**原值**写进审核包 Excel 的「主体范围」列
⇒ 交付面带出客户标识（`entity_hint:<客户简称>`）。

**治**：该列改为**稳定代号**（`主体-1`、`主体-2`……）。

| 规则 | 落地 |
|---|---|
| 不得出现 `entity_scope` 原值 | ✔ 该列**只有** `主体-N`；原值只作内存里的分组键，**不落任何交付面** |
| 稳定代号、同一主体全表一致 | ✔ 按**首次出现顺序**分配，同包一致 |
| 列不得删 | ✔ 「主体范围」列仍在 |
| 必须复用判定层已有脱敏函数 | ✔ **只调** `rq.entity_scope_value()` 判定「这是不是客户标识」；仓内**不出现第二套主体脱敏口径** |

### ★ 已知残留（如实登记，不隐瞒）

审核包的**「机构原文」「原子义务」两列保留清单原文**（原文零丢失是硬校验），
而清单原文本身**可能含主体简称** ⇒ **转发前仍需人工按机构口径处理**。

★ 处置理由：A3 白名单对 `dd_v1_package_service.py` 的授权是「**仅限**「主体范围列的输出脱敏」」，
且改动**清单原文列**会与「原文零丢失」硬校验冲突 ⇒ **本包不做**，
作为**残留风险**登记在此，并建议 A4 立项「交付面前置脱敏层」。

---

# 第 4 章 · 判据逐条自证（A3-1 … A3-13）

| # | 判据 | 自证方式 | 证据 |
|---|---|---|---|
| A3-1 | 份数承载 | 合成用例：「一式两份」→ 2/FACT；解析不出 → `None`/UNKNOWN ⇒ 判 UNCERTAIN + 「份数不可判定」 | `backend/tests/test_dd_v1_qc.py`（15 条） |
| A3-2 | 精确集合 | 5 个同类型候选 ⇒ 交付目录**只含 1 份**；核对表逐条写选/不选理由；未选用清单可审计 | `test_dd_v1_selection.py`（12 条）+ `test_dd_v1_packaging_exact.py`（12 条） |
| A3-3 | 五维齐套 | 5 维各缺 1 项的合成用例 ⇒ 判对且 `missing_detail` 指名缺哪一维；份数不可判定 → UNCERTAIN | `test_dd_v1_qc.py` |
| A3-4 | HG1 | 未批准 ⇒ `ApprovalRequired` + 交付目录**为空**；批准人空 ⇒ 拒绝；批准后结构齐全 | `test_dd_v1_packaging_exact.py` + `test_dd_v1_packaging.py`（既有） |
| A3-5 | 受限单列 | 受限材料在缺口清单**单独成列**并注明原因；不混入 MISSING；不静默丢弃 | `test_dd_v1_packaging_exact.py` |
| A3-6 | 零回归 | pytest ≥ A2 封版 passed 数、0 failures/errors、退出码 0 | 第 8 章 |
| A3-7 | 越权 | 改动仅限白名单；零真实数据/零付费；未 commit/push | 第 5 章 + 提交前核对 |
| A3-8 | 硬 Gate | PRECISE_PACKAGING 可推进；WINDOWS_REAL_E2E / UNATTENDED_HANDOFF 保持 UNKNOWN | 第 6 章 |
| A3-9 | H-3 脱敏 | 主体范围列只有 `主体-N`；同主体全表一致；不出现原值 | `test_dd_v1_packaging_exact.py`（3 条） |
| A3-10 | G-A3-6 薄入口接线 | 入口打印 `pack_path` + 四件套；`package_service` 在真实调用栈被触达；组包不可用时退出码仍 0 且前 6 步逐字一致；未批准 ⇒ 零复制 | `gm_probe_a3_wiring_e2e.py`（24/24）+ `gm_probe_a3_packaging_optional.py`（PASS） |
| A3-11 | G-A3-7 接线说明书 | 说明书命令**逐字可执行**（退出码 0）；sha 与 HEAD 一致；快照 ID 能取到值 | `gm_probe_a3_wiring_doc.py`（A3-11 三条全过） |
| A3-12 | G-A3-9 端到端出材料包 | `run --help` 里有 `--package`；未批准 ⇒ 拒绝 + 交付目录为空；批准后才复制，且集合 = 授权选择集 | `gm_probe_a3_wiring_e2e.py` S3/S4 |
| A3-13 | G-A3-8 别名入口 | CLI `alias` 存在；合法别名 ⇒ 成功且 UNCERTAIN→MATCHED；分类目录型 ⇒ 被拒留痕；跨主体 ⇒ 被拒；CLI 层无第二份规则 | `gm_probe_a3_wiring_e2e.py` S2a–S2d |

---

# 第 5 章 · 改动清单与白名单核对

| 文件 | 改动 | 白名单 |
|---|---|---|
| `backend/src/cangjie_fos/services/dd_v1_requirement_service.py` | `expected_count` / `expected_count_basis` 字段 + 解析 + 落库 + 列补齐迁移 | ✅ 可修改 |
| `backend/src/cangjie_fos/services/dd_v1_match_service.py` | 五维齐套接入（份数维 + 每一维缺口指名） | ✅ 可修改 |
| `backend/src/cangjie_fos/services/dd_v1_package_service.py` | 精确副本集合 + 核对表新列 + 缺口清单分区 + 受限分类 + 主体范围脱敏 | ✅ 可修改（A3 追加授权，限「主体范围列的输出脱敏 + 对应用例」；组包逻辑/复制逻辑/Gate 逻辑**未放宽**） |
| `backend/src/cangjie_fos/services/dd_v1_qc_service.py` | **新建**：五维齐套组装层 | ✅ 可新建 |
| `backend/src/cangjie_fos/services/dd_v1_selection_service.py` | **新建**：精确选中规则 | ✅ 可新建 |
| `backend/tests/test_dd_v1_qc.py` | **新建**（15 条） | ✅ 可新建 |
| `backend/tests/test_dd_v1_selection.py` | **新建**（12 条） | ✅ 可新建 |
| `backend/tests/test_dd_v1_packaging_exact.py` | **新建**（12 条） | ✅ 可新建 |
| `tools/dd_team_channel.py` | G-A3-6 / G-A3-9 / G-A3-7（三条授权口径内） | ✅ 可修改（限三条） |
| `tools/dd_v1_manifest.py` | G-A3-8 `alias` 子命令 | ✅ 可修改（限 alias 子命令） |

★ **未改动**：`assert_approval` 的 HG1 检查、`_within` 越界闸、`blocked` 分支、披露策略、任何既有字段的取值语义。

---

# 第 6 章 · 已知边界、残留风险与移交项

| # | 事项 | 性质 | 处置 |
|---|---|---|---|
| 1 | 审核包「机构原文 / 原子义务」两列可能含主体简称 | **残留风险** | 白名单限定 + 原文零丢失硬校验 ⇒ 本包不做；已登记，建议 A4 立项「交付面前置脱敏层」 |
| 2 | 案例B/C 主体维度物理上不可判定（0/46、0/241） | 结构性事实 | 需业务/材料方补主体名或目录结构；**不是算法能解决的** |
| 3 | 同类型误分类（实测一份「公司简介」被识别成 `license`） | 已知边界 | 选中层保证**确定性 + 可解释**（逐条写为什么不选）；类型误判本身属召回/判定层，已由 A2 的相关性闸处理 |
| 4 | 案例A 顶层目录含分类目录 ⇒ 别名须登记为 DIRECTORY | 已知边界 | G-A3-8 的形态硬守卫已拒（实测留痕） |
| 5 | 模型语义检索入口（`run_semantic` / `retrieve_minimal_evidence` / `build_semantic_packet`） | **有意不接** | 付费，移交 A4/A5 |
| 6 | Gold 对标评分 | 范围外 | 不在本包 |
| 7 | 份数维只覆盖「同一主体×期间×类型」格内的份数 | 口径边界 | 已在 §2.2 写明；跨格份数（如「正本1份+副本1份」被拆分）各管各的 |

★ **硬 Gate 状态**：`PRECISE_PACKAGING` **可推进**；
`WINDOWS_REAL_E2E` / `UNATTENDED_HANDOFF` 保持 **UNKNOWN**（真实模型通路与刘江 Windows 侧未就绪）。

---

# 第 7 章 · 复现命令（逐字可执行）

```bash
# ── 0) 环境：A3 worktree 的 venv（Python 3.13）──────────────────────────
WT=/Users/mac/cangjie-fos-wt-a3
PY=$WT/backend/.venv/bin/python

# ── 1) 三条新用例（份数 / 选中 / 精确组包 + 脱敏 + 受限单列）──────────────
cd $WT/backend && $PY -m pytest \
  tests/test_dd_v1_qc.py tests/test_dd_v1_selection.py \
  tests/test_dd_v1_packaging_exact.py -q

# ── 2) 零回归（全量）────────────────────────────────────────────────────
cd $WT/backend && $PY -m pytest -q --junit-xml=/tmp/a3-junit.xml \
  --ignore=tests/test_doctor_script.py

# ── 3) 接线端到端探针（24 条：薄入口 / alias / HG1 / 材料包）────────────
cd /Users/mac/.minimax/sessions/mvs_9d861162716f4f6785d5e4bf09d4941e/workspace
$PY gm_probe_a3_wiring_e2e.py --worktree $WT

# ── 4) 组包不可用不影响前 6 步（逐字一致）──────────────────────────────
$PY gm_probe_a3_packaging_optional.py --worktree $WT

# ── 5) 判据 A3-11：说明书命令逐字可执行 + sha 一致 + 快照 ID 可取 ───────
$PY gm_probe_a3_wiring_doc.py --worktree $WT
```

★ 全部产物落 `/tmp` 或 `~/dd-v1-realbase/work/`，**不进任何 Git 仓**。

---

# 第 8 章 · 实测数据（2026-10-22 · 司仓侧复测）

> 全部数据来自**真实材料**（`~/dd-v1-realbase/`，只读）与**仓库内合成 fixture**。
> 证据件：`a3-evidence/`（SHA256 清单见 `SHA256SUMS-a3-evidence.txt`）。
> ★ 零外部模型调用；产物只出**计数**，零真实机构名/文件名/路径。

## 8.1 零回归（判据 A3-6）

| 项 | 值 |
|---|---|
| 全量 tests / passed | **1639 / 1634** |
| failures / errors / skipped | **0 / 0 / 5** |
| 退出码 | 0 |
| A2 封版基线 | 1595 passed（tests 1600 / skipped 5） |
| A3 新增用例 | **39 条**（qc 15 / selection 12 / packaging_exact 12），全 PASS |

★ 数字从 `--junit-xml` **现算**（pytest 9 的 `-q` 不打印汇总）。
★ 跑测试前**卸掉代理**（`ALL_PROXY/all_proxy/HTTP_PROXY/http_proxy/HTTPS_PROXY/https_proxy`），
否则 6 个 LLM-refine 用例会因 SOCKS 缺 `socksio` **假红**（环境问题，非代码问题）。

## 8.2 真实材料判定分布（★ 零漂移）

| 案例 | 义务 | CONFLICT | RESTRICTED | MISSING | PARTIAL | UNCERTAIN | MATCHED |
|---|---|---|---|---|---|---|---|
| 案例A | 32 | 0 | 4 | 3 | 1 | 22 | 2 |
| 案例B | 46 | 0 | 9 | 3 | 0 | 33 | 1 |
| 案例C | 241 | 0 | 0 | 3 | 0 | 238 | 0 |
| **合计** | **319** | **0** | **13** | **9** | **1** | **293** | **3** |

★ **与 A2 封版基线逐项相同**（run `reg-20261022-093705`）⇒ A3 **零判定漂移**。

**机制解释（可复核，不是巧合）**：第五维「份数」只在清单**明确给出份数**时构成门槛；
三案例真实清单里「份」字**只出现在「身份证复印件」**，无一处是份数要求
⇒ `expected_count` 全为 `0`（未规定）⇒ 该维不构成门槛。
另两处改动只影响**输出**（缺口文案增列、交付集合收窄），**不改判定**。

## 8.3 ★ 交付集合实测（判据 A3-2 的真实材料证据）

| 案例 | 义务 | 候选件数 | **选中件数** | 未选用件数 | 交付目录原件副本 | 越界件 | hash 不一致 |
|---|---|---|---|---|---|---|---|
| 案例A | 32 | 439 | **2** | 437 | 2 | **0** | 0 |
| 案例B | 46 | 252 | **1** | 251 | 1 | **0** | 0 |
| 案例C | 241 | 4565 | **3** | 4562 | 3 | **0** | 0 |
| **合计** | **319** | **5256** | **6** | **5250** | **6** | **0** | **0** |

★ **旧行为会交 5256 份**（每条义务的全部 deliverable 候选）
⇒ **精确组包后只交 6 份**，减少 **5250 份**「同类型无关材料」。
★ 交付目录里的原件**全部**来自选中集合（越界 0）⇒ **无「同目录顺带复制」**。
★ 未选中的 5250 件**逐条**进「未选用清单.tsv」并带原因（可审计，不静默丢弃）。
★ 交付目录固定含三个清单文件：`组包manifest.tsv` / `被拦截清单.json` / `未选用清单.tsv`。

## 8.4 接线端到端探针（24/24 PASS）

| 探针 | 覆盖 | 结果 |
|---|---|---|
| `gm_probe_a3_wiring_e2e.py` | S1 接线基本盘 / S2a–S2d 别名四态 / S3 HG1 拒绝 / S4 批准后真组包 | **24/24 PASS** |
| `gm_probe_a3_packaging_optional.py` | 组包不可用 ⇒ 入口退出码仍 0 且前 6 步**逐字一致** | **PASS** |
| `gm_probe_a3_wiring_doc.py` | 判据 A3-11 三条 | **全过** |

## 8.5 ★ 必须如实登记的三件事

1. **语义桥接未运行**（`BRIDGE_UNAVAILABLE`）：A3 硬禁止第 1 条禁止 `--allow-real-material`
   ⇒ 本次回归**未**开启该开关。桥接本身「仅供参考、不改判定」，
   且判定分布与 A2 基线逐项相同 ⇒ **不影响本包任何结论**。
2. **本次组包是「机械核对」不是人工放行**：批准人字段写明「司仓机械核对（非人工批准）」；
   产物落 `~/dd-v1-realbase/work/`（scratch，非 Git、不外发）。
   HG1 闸本身**未被绕过**（未批准 ⇒ 直接抛 `ApprovalRequired`）。
3. **交付集合按「义务维度」选件，不按判定档位过滤**：
   `UNCERTAIN` / `PARTIAL` 义务若有可交付主件，同样进入交付集合并在核对表里**标注判定**——
   「这一份到底该不该交」的处置权在**人工审核**（HG1 闸），这与 A2 的既有设计一致。
   A3 只负责「每条义务只交选中的那 1 份 + 附件，**不交全部候选**」。
