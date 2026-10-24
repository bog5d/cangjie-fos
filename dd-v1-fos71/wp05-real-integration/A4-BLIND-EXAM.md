# A4 盲考接线说明书（cangjie-fos#71 · WP-A4a）
<!-- GM:A4A:DOC:BEGIN -->

# A4 盲考接线说明书（cangjie-fos#71 · WP-A4a）

> **边界声明（先读）**
> 本包只把**链路**接通并做**零成本自检**：合成材料 → 盲化 → 冻结 → 拆分 → 跑 → 评分 → 错误分类。
> **没有任何模型参与**（回贴是预置的合成回放，`model_id_or_unknown=UNKNOWN`、
> `independent_examinee_answer=false`、`synthetic_replay=true`），
> **没有读取任何真实标准答案包**，真实 Gold **未提供**。
> ⇒ 本包的结论是「**链路自检通过**」，**不是**「盲考通过」，也**不是**「模型能力被验证」。
> 真实材料 + 真机真模型段（A4b）见第 9 节，状态 `BLOCKED`。

---

## 0. 五条线一览

| 线 | 实现位置 | 判据 | PASS 口径（本包实测） | 证据 |
|---|---|---|---|---|
| G-A4a-1 补料盲化 | `backend/src/cangjie_fos/services/dd_v1_blind_service.py` | A4-1 | 盲化目录 grep 不到 4 个泄漏词（路径 + 正文，0 命中）；映射表落在材料目录之外；还原后逐件 sha256 与原件一致 | `a4-evidence/a4-blind-exam-run.txt`、`a4-evidence/a4-discriminative.txt` |
| G-A4a-2 快照冻结 | `backend/src/cangjie_fos/services/dd_v1_snapshot_freeze_service.py` | A4-2 | 两侧（被考侧/被评侧）逐件 sha256 相等且 `snapshot_id` 相同；`snapshot.json` 记 `snapshot_id`/`frozen_at`/逐件 sha256；改动（改/删/加）都能检出 | 同上 |
| G-A4a-3 Gold 隔离 | `backend/src/cangjie_fos/services/dd_v1_score_service.py`（新增 Git 工作树检测） | A4-3 | 每条 Gold 有 `confirmed_by`+`confirmed_at`（缺失 ⇒ `NOT_SCORABLE`）；材料/运行目录隔离沿用 `sem.assert_gold_isolated`；**新增**「向上找 `.git`」检测（仓内 Gold 被拒，退出码 3） | 同上 |
| G-A4a-4 错误分类 | `backend/src/cangjie_fos/services/dd_v1_score_service.py`（包装 `sem.score_against_gold`） | A4-4 | 输出含 TP/FP/FN/错主体/错年度/自信错配（各 ≥1）+ UNCERTAIN 单列（**不进 FN**）；每错回指 `run_record_path`+`obligation_id`+`file_id`+`locator` | `a4-evidence/a4-blind-exam-errors.csv` |
| G-A4a-5 合成盲测 | `backend/tests/fixtures/dd-v1-fos71-a4/**` + `tools/dd_v1_local_run.py` 新增开关 | A4-5 | `run` 退出码 **0**；产出 `score.json` + `score.csv` + 错误分类表；6 类错误各 ≥1 例 | `a4-evidence/a4-blind-exam-run.txt` |

**零回归（A4-7）**：全量 `1678 tests / 1673 passed / 0 failures / 0 errors / 5 skipped`（A3 封版基线
1634 passed + 本包新增 39）⇒ **1673 ≥ 1634 + 39** ✔。

---

## 1. G-A4a-1 补料盲化

### 1.1 接口

```python
from cangjie_fos.services import dd_v1_blind_service as bl

res = bl.blind_material(
    material_dir, meta,                 # 材料目录 + 逐件 meta
    leak_words=["Q-2024-07", "案例甲机构", "案例乙机构", "星海项目"],
    blind_dir=...,                      # ① 盲化材料目录
    mapping_out=...,                    # ③ 映射表（★ 必须落在材料目录之外）
    meta_file=material_dir / "meta.json",
)
res["meta"]        # ② 新 meta.json 的内容（file_id 不变）
res["mapping"]     # 映射表（泄漏词 ⇄ 占位符、原路径 ⇄ 盲化路径、逐件 sha256）

bl.verify_blind(blind_dir, leak_words)      # {"ok", "hits"}：盲化目录 grep 不到泄漏词
bl.restore_material(blind_dir, mapping, restore_dir=...)   # → 原目录，逐件 sha256 校验
```

### 1.2 口径（照任务书，不自创）

- **盲化对象** = 材料目录内的**相对路径**（目录名 + 文件名）+ **正文**里出现的泄漏串；
  `meta.json` 的字符串字段里的泄漏串同样替换。
- **`file_id` 保持不变**；`doc_type` / `entity` / `period` 的**类型语义不变**
  （只有字段里含泄漏串时才替换该串）⇒ 盲化**不改变**材料本身的类型语义。
- **映射表**：单独文件，`--blind-mapping-out` 指定；服务**强制**它不得落在材料目录或盲化目录内
  （否则 `BLIND_MAPPING_INSIDE_MATERIAL` 抛错）。
- **还原**：`restore_material()` 按映射表反替换，**逐件 sha256 与原件一致**才返回；
  任一件不一致 ⇒ `BLIND_RESTORE_SHA_MISMATCH` 抛错（fail closed）。
- **占位符** = `BLIND-0001`…（**不以数字 + 分隔符开头** ⇒ 不会命中
  `dd_v1_doc_type_service.is_index_artifact` 的索引件判定）。
- **确定性**：同一份泄漏词表 ⇒ 同一张映射表 ⇒ 拆分步与运行步各自盲化时口径一致。

### 1.3 怎么算 PASS（A4-1）

1. `verify_blind(blind_dir, leak_words)` → `ok == true`（**路径 + 正文**都查，0 命中）；
   对照组：原始材料目录上同一检查 **必须命中**（否则这条判据没有判别力）。
2. 映射表路径不在 `blind_dir` / `material_dir` 内，且**不在 Git 仓**（运行时不落仓）。
3. `restore_material()` 后逐件 sha256 == 原件 sha256（含 `meta.json` 本身）。

### 1.4 坑

- **泄漏词表必须和运行命令一致**：回贴里的 `source_snapshot_id` 取决于**盲化之后**的快照 ⇒
  泄漏词改了，冻结目录的 `snapshot_id` 就变 ⇒ 预置回贴会被 R4 校验拒收（`run` 退出码 2）。
  改了泄漏词 ⇒ 重新生成回贴（`make_synthetic_replies.py`）。
- **长词优先**：短泄漏词不得先吃掉长泄漏词的一部分（`build_substitution_table` 按长度降序编号）。
- **占位符碰撞**：原件里若已含 `BLIND-0001` 这类文本 ⇒ 还原不可逆 ⇒ `BLIND_PLACEHOLDER_COLLISION` 抛错。
- **主体也要盲**时，**条目（obligations 来源）必须用同一张表盲化**，否则义务里的主体与 `meta` 对不上
  ⇒ 证据检索池为空 ⇒ 全部 `NO_ANSWER`。CLI 的 `split` / `run` 都带 `--blind-leak-words`，口径一致。

---

## 2. G-A4a-2 快照冻结

### 2.1 接口

```python
from cangjie_fos.services import dd_v1_snapshot_freeze_service as fz

man = fz.freeze_snapshot(source_dir, meta, freeze_dir)   # 复制 + 逐件 sha256 + snapshot.json + 只读
fz.verify_frozen(freeze_dir, man)                        # {"ok", "changed":[...]}：改动可检出
fz.compare_snapshots(examiner_dir, grader_dir, meta)     # 两侧逐件 sha256 相等？
```

### 2.2 口径

- **sha256 一律现场算**：复用 `dd_v1_agent_result_service.load_snapshot()`（**不重写 sha 计算**，
  不信任元数据指纹）；`snapshot_id` 一律取 `ar.snapshot_id()`（**同一份口径，不另造**）。
- **冻结产物** `snapshot.json` = `{schema_version, snapshot_id, frozen_at, source_dir,
  meta_relative_path, files:[{file_id, relative_path, sha256}]}`。
- **只读**：冻结后目录 `0555` / 文件 `0444`。只读是**兜底**（owner 仍可改）；
  **改动检出靠 sha256 比对**：`verify_frozen()` 报 `MISSING` / `MODIFIED` / `EXTRA`。
- **两侧**：被考侧与被评侧各一份拷贝；逐件 sha256 相等（且 `snapshot_id` 相同）才算「同一份快照」。

### 2.3 怎么算 PASS（A4-2）

`compare_snapshots(examiner, grader, meta)` → `ok == true` 且 `snapshot_id_a == snapshot_id_b`；
`snapshot.json` 里 `snapshot_id` 与 `frozen_at` 非空、逐件 sha256 与现场重算一致；
改一个字节 / 删一个文件 / 加一个文件 ⇒ `verify_frozen().ok == false` 且 `changed` 非空。

### 2.4 坑

- 冻结目录**只读** ⇒ 重新冻结前必须 `make_writable()`（服务内已做）。
  pytest 的 `tmp_path` 清理遇到只读目录会报错 ⇒ 测试里要先放开权限。
- `compare_snapshots` 的 `meta` 必须是**与该目录匹配的那份 meta**（盲化目录要用盲化后的 meta）。

---

## 3. G-A4a-3 Gold 隔离

### 3.1 三道闸

| 闸 | 实现 | 失败表现 |
|---|---|---|
| 材料目录 / 运行目录隔离 | **复用** `sem.assert_gold_isolated`（语义未改） | `PermissionError: GOLD_INSIDE_FORBIDDEN_DIR` |
| **Git 工作树隔离**（新增） | `sc.assert_gold_not_in_git_worktree()`：**向上找 `.git`**（目录或文件，worktree/submodule 的 `.git` 是文件） | `GoldIsolationError: GOLD_INSIDE_GIT_WORKTREE` ⇒ CLI 退出码 **3** |
| 人工确认 | `sc.missing_confirmations()`：每条 Gold 必须有 `confirmed_by` + `confirmed_at` | `status=NOT_SCORABLE`（`blocked_by=GOLD_NOT_HUMAN_CONFIRMED:...`）⇒ CLI 退出码 **3** |

★ `sem.assert_gold_isolated` **只查 forbidden_dirs、不查 Git 仓** ⇒ 第三道闸是本包**新增**的
（任务书 R4）。**缺失确认 ⇒ NOT_SCORABLE**，不是「空值当已确认」。

### 3.2 合成 Gold 与真实 Gold

- **合成 Gold**（fixture）每条写 `confirmed_by="司仓机械核对（非人工批准）"` + `confirmed_at`（ISO8601 带时区）
  ⇒ 可用于证明机制；**它不是人工批准**。
- **真实 Gold 当前未提供** ⇒ A4-3 对真实 Gold 的部分 **BLOCKED**（见第 9 节）。
  本包**未读取任何真实标准答案包**。
- fixture 里的 `gold.json` 是**模板**；**评分时必须复制到任何 Git 工作树之外**再用
  （本包的做法：复制到 `/tmp/...`）。否则工具会按第三道闸拒绝（退出码 3）。

### 3.3 怎么算 PASS（A4-3）

仓内 Gold ⇒ `score --classify` 退出码 3 且报 `GOLD_INSIDE_GIT_WORKTREE`；
把 Gold 复制到 `/tmp` 且补齐 `confirmed_by`/`confirmed_at` ⇒ 可评分；
删掉 `confirmed_by` ⇒ `NOT_SCORABLE` 且退出码 3。

---

## 4. G-A4a-4 错误分类

### 4.1 位置与边界

`backend/src/cangjie_fos/services/dd_v1_score_service.py`：**包装** `sem.score_against_gold` 的输出
（`base` 字段是它的**原样输出**），**不改**它的隔离与评分语义。分类层只加三样东西：
① Gold 的 Git 工作树隔离；② 人工确认校验；③ 分类 + 错误回指。

### 4.2 判定顺序（照任务书表格，不自创口径）

| 顺序 | 条件 | 类别 |
|---|---|---|
| 1 | 答卷 `verdict == UNCERTAIN` | `UNCERTAIN`（**单列**：不计入 FN，也不计入 TP） |
| 2 | 期望有货 且 答卷 `MISSING`/`NO_ANSWER` | `FN` |
| 3 | 答卷报了有货 且 期望是 `MISSING`/`UNCERTAIN` | `FP` |
| 4 | `verdict` 对 且 文件集相等 | `TP` |
| 5 | 双方都报有货 且 答卷件 `entity` ≠ 期望主体 | `WRONG_ENTITY` |
| 6 | 双方都报有货 且 答卷件 `period` ≠ 期望期间 | `WRONG_PERIOD` |
| 7 | 双方都报有货 且 `verdict`/主体/期间对 且 文件集**既多又缺** | `WRONG_FILE_SET` |
| 8 | 双方都报有货 且 文件集**只多不缺** | `FP`（文件集多出非期望件） |
| 9 | 双方都报有货 且 `verdict`/主体/期间对 且 文件集**只缺不多** | `WRONG_FILE_SET` |
| 10 | 其余（`verdict` 不一致且主体/期间无差异等） | `UNDETERMINED`（不强行归类） |

- **期望主体/期间来源优先级**：Gold 的 `expected_entity`/`expected_period` →
  由 `expected_files` 对应件的 entity/period **唯一值**推出 → 否则 `UNDETERMINED`
  （输出里带 `expected_entity_source` 标明来源）。
- **自信错配**：`confidence_or_uncertain ≥ 0.8` 且该行**判错** ⇒ `flags` 里加 `CONFIDENT_MISMATCH`
  （TP / UNCERTAIN 不算判错）。它是**标记**，与主类别并存（R3 行同时是 `WRONG_PERIOD` + `CONFIDENT_MISMATCH`）。
- **错误回指**：每条错误给 `run_record_path`（相对运行目录，如 `run-R3/run_record.json`）
  + `obligation_id` + `file_id` + `locator`。
  `locator` 取 `candidate_files[].locator`；该字段为空 ⇒ 由 meta 的 `relative_path` 派生并标
  `locator_source=RULE_ONLY_DERIVED`（否则标 `ANSWER_CANDIDATE`）。
  答卷没给件（`MISSING`/`UNCERTAIN`）⇒ 回指**期望件**，locator 标 `RULE_ONLY_DERIVED`。

### 4.3 红线（必须守住）

- **不得**把 UNCERTAIN 计入 FN（单列）。既有基线 `score_against_gold` 把它计入 `wrong`
  ⇒ 分类层专门把它拆出来（`uncertain_count`）。
- **不得**把「没查」算成「查了没有」：`NO_ANSWER` 与 `MISSING` 分开记（`NO_ANSWER` 也算 FN，
  但基线的 `no_answer` 计数保持独立）。

### 4.4 怎么算 PASS（A4-4）

合成 Gold 上跑出 `classification.counts`：`TP/FP/FN/WRONG_ENTITY/WRONG_PERIOD/CONFIDENT_MISMATCH`
各 ≥1、`UNCERTAIN ≥1` 且 `fn_count == 1`（不含 UNCERTAIN 那条）；
每行都有 `run_record_path` + `file_id` + `locator`（`locator_source` ∈ 两个取值）。

---

## 5. G-A4a-5 合成盲测（零成本）

### 5.1 合成 fixture 形态

- 目录：`backend/tests/fixtures/dd-v1-fos71-a4/`
- `material/meta.json`：**手写**（不用 `cmd_scaffold`）⇒ **≥2 个 entity（主体甲 / 主体乙）**
  + **≥2 个 period（2024 / 2023）**；`file_id` = `F00001…F00008`（稳定 ⇒ 盲化改路径不影响 Gold 对表）。
- 材料文件**故意**带题号 / 机构名 / 项目名（目录名 + 文件名 + 正文）⇒ 用来证明盲化有效。
- 文件名**不以「数字 + 分隔符」开头**（避开 `is_index_artifact` 的索引件判定）。
- 一件 `version_status=DRAFT`（不可被 MATCH/PARTIAL 引用 ⇒ 语义层当场拒收）。
- `replies/run-<tag>.json` + `run-<tag>.provenance.json`：**预置回贴**
  （`reply_source=SYNTHETIC_REPLAY`、`declared_by=司仓合成盲测自检`、
  `model_id_or_unknown=UNKNOWN`、`independent_examinee_answer=false`、`synthetic_replay=true`）。
- `make_synthetic_replies.py`：**回贴生成器**（盲化 → 冻结 → 拆分 → 取证据 ⇒ 回贴）。
  回贴必须带 `source_snapshot_id` / `sha256` / `locator`，这些值取决于盲化+冻结之后的那份快照 ⇒
  不能凭空手写；生成器与运行器**同源**，材料一改就重新生成。

### 5.2 回贴设计（6 类错误 + 1 例 UNCERTAIN）

| 条目 | 合成答卷 | 期望 | 分类 |
|---|---|---|---|
| R1 | MATCH `[F00001,F00002]` | MATCH `[F00001,F00002]` | `TP` |
| R2 | MATCH `[F00001,F00002]`（多出 F00002） | MATCH `[F00001]` | `FP` |
| R3 | OUTDATED `[F00004]`（2023 的件），confidence 0.9 | MATCH `[F00001]`（2024） | `WRONG_PERIOD` + `CONFIDENT_MISMATCH` |
| R4 | OUTDATED `[F00004]`，confidence 0.5 | MATCH `[F00001]` | `WRONG_PERIOD` |
| R5 | MISSING | MATCH `[F00005]` | `FN` |
| R6 | UNCERTAIN | MATCH `[F00006]` | `UNCERTAIN`（**不进 FN**） |
| R7 | MATCH `[F00001]`（主体甲的件） | MATCH `[F00008]`（主体乙） | `WRONG_ENTITY` |
| R8 | MATCH `[F00001,F00003]` | MATCH `[F00001,F00002]` | `WRONG_FILE_SET` |

### 5.3 可复制执行的命令（逐字可跑，退出码 0）

```bash
WT=/Users/mac/cangjie-fos-wt-a4
FIX=$WT/backend/tests/fixtures/dd-v1-fos71-a4
LEAK="Q-2024-07,案例甲机构,案例乙机构,星海项目"
S=/tmp/a4a-demo
mkdir -p $S/gold $S/score

# ① 拆分义务（零模型；条目按同一张映射表盲化）
$WT/backend/.venv/bin/python $WT/tools/dd_v1_local_run.py split \
  --items $FIX/raw_items.json --out $S/obligations.json \
  --blind-leak-words "$LEAK" --blind-items-out $S/blinded_items.json

# ② 盲化 + 冻结（两侧各一份）+ 跑（manual adapter + 预置回贴 ⇒ 零进程零费用 ⇒ 退出码 0）
$WT/backend/.venv/bin/python $WT/tools/dd_v1_local_run.py run \
  --material-root $FIX/material --meta $FIX/material/meta.json \
  --items $S/blinded_items.json --obligations $S/obligations.json \
  --blind-material-out $S/blind --blind-leak-words "$LEAK" \
  --blind-mapping-out $S/blind-mapping.json \
  --snapshot-freeze-dir $FIX/frozen/examiner --snapshot-evaluate-dir $FIX/frozen/grader \
  --adapter manual --synthetic-replies $FIX/replies --out $S/run
echo "run exit=$?"          # ⇒ 0

# ③ 评分（★ Gold 必须复制到任何 Git 工作树之外）
cp $FIX/gold.json $S/gold/gold.json
$WT/backend/.venv/bin/python $WT/tools/dd_v1_local_run.py score \
  --run-dir $S/run --gold $S/gold/gold.json \
  --material-root $FIX/frozen/examiner --classify \
  --classify-meta $FIX/frozen/examiner/meta.json \
  --out $S/score/score.json --classify-out $S/score/errors.csv
echo "score exit=$?"        # ⇒ 0
```

★ 第 ② 步的 `--snapshot-freeze-dir` 必须落在 `backend/tests/fixtures/` 之内
（`cmd_run` 的 fixture 闸：材料目录不在 `backend/tests/fixtures` 之下就要 `--allow-real-material`，
而那是**真实材料**开关 ⇒ 合成材料**不得**用它）。`--out` 与 `--gold` 同样不得落在材料目录里。

### 5.4 怎么算 PASS（A4-5）

`run` 退出码 0（`mode == "AGENT_SUGGESTION"` 的组 ≥1）；产出 `score.json` + `score.csv` +
错误分类表（`errors.csv`）；`classification.counts` 里 6 类各 ≥1。

---

## 6. CLI 新增开关一览（**只新增**，既有 run/score 语义与退出码未改）

| 子命令 | 新开关 | 作用 |
|---|---|---|
| `split` | `--blind-leak-words` / `--blind-items-out` | 条目按同一张映射表盲化；盲化后的条目落盘 |
| `run` | `--blind-material-out` | 盲化材料目录（相对路径 + 正文） |
| `run` | `--blind-leak-words` | 泄漏词表（逗号分隔） |
| `run` | `--blind-mapping-out` | 映射表落盘（★ 必须落在材料目录之外，且不得进 Git） |
| `run` | `--blind-items-out` | 盲化后的条目落盘 |
| `run` | `--snapshot-freeze-dir` | 冻结快照（被考侧） |
| `run` | `--snapshot-evaluate-dir` | 冻结快照（被评侧） |
| `run` | `--synthetic-replies` | 预置回贴目录（`<dir>/run-<tag>.json`）⇒ 零进程零费用 |
| `score` | `--classify` | 启用分类层（同时启用 Gold 的 Git 工作树闸 + 人工确认校验） |
| `score` | `--classify-out` | 错误分类表（CSV）落盘路径 |
| `score` | `--classify-meta` | meta 路径（locator 派生 + 期望主体/期间推导） |

**既有语义未动的部分**：`score` 不带 `--classify` 时输出结构与退出码**逐字未变**；
`run` 不带新开关时行为**逐字未变**；`--classify` 路径在 `NOT_SCORABLE` / Gold 落在 Git 仓内时
返回退出码 **3**（新路径的新语义，不影响既有路径）。

---

## 7. 判别力（A4-10）

探针：`gm_probe_a4_discriminative.py`（工作区，不进 Git）。

- **/tmp 源码副本（符号链接农场）**：`backend/src` 全部是指向工作树的符号链接，
  **只有被回退的那一个源文件**是实体副本；`backend/tests`、`tools` 是实体副本 ⇒ 探针的写入只落 `/tmp`，
  **工作树零副作用**；农场自身 `git init` ⇒ 「Gold 不在 Git 仓内」这条判据在农场里同样可测。
- **worktree SHA256 指纹自证**：逐件打印并核对（a）工作树原文件 sha256、
  （b）农场里被回退文件的 sha256（**必须不同**）、（c）农场里其余 190 个源文件 sha256
  （**必须与工作树逐件相同**）、（d）农场里用例文件的 sha256（**必须与工作树逐件相同**）。
- **起止标记型锚代码结构**：回退锚是**代码里的字符串常量**
  （`BLIND_IMPL_BEGIN = "GM:A4A:BLIND:IMPL:BEGIN"` 等），**不是注释**；
  探针把两个标记**行之间**的正文整体换成桩实现 ⇒ 回退是真实的代码变更。
- **对照跑**：同一农场、**不**回退 ⇒ 用例必须全绿。只有「对照绿 + 回退红」同时成立才算判别力成立。

实测（control 退出码 0 / reverted 退出码 1）：

| 回退处 | 转红用例 | 说明 |
|---|---|---|
| 盲化 `dd_v1_blind_service.py` | **12 / 12** | 盲化文件全红 |
| 冻结 `dd_v1_snapshot_freeze_service.py` | **11 / 11** | 冻结文件全红 |
| 分类 `dd_v1_score_service.py` | **15 / 16** | ★ 唯一**保持绿**的是 `test_cli_score_without_classify_keeps_legacy_behaviour`——它断言的正是「**既有 score 路径不被新分类层影响**」⇒ 回退新层它本来就该绿（否则才是回归） |

⇒ 判别力 PASS（证据：`a4-evidence/a4-discriminative.txt`）。

---

## 8. 坑与边界（施工时踩过的）

1. **回贴不能手工写死**：`source_snapshot_id` / `sha256` / `locator` 都取决于盲化+冻结后的快照 ⇒ 必须生成。
2. **`cmd_run` 的工作目录非空闸**：工作目录里有文件就 `exit 3` ⇒ 预置回贴必须**在
   `wd.mkdir()` 之后、`run_semantic()` 之前**装进去（`reply.json` / `reply.provenance.json`
   都在 `MANUAL_ALLOWED` 白名单里）。
3. **`--out` / `--gold` 不得落在材料目录里**（`cmd_run` / `cmd_score` 都有闸）。
4. **fixture 闸**：材料目录不在 `backend/tests/fixtures` 之下 ⇒ 要 `--allow-real-material`
   （真实材料开关）⇒ 合成盲测的冻结目录**必须**放在 `backend/tests/fixtures/dd-v1-fos71-a4/` 之下。
5. **只读目录**：冻结后 `0555` ⇒ 重新冻结、pytest 清理都要先放开权限。
6. **`is_index_artifact`**：盲化名不要以「数字 + 分隔符」开头（`1_`、`01-`、`02.`），否则盲化后反被判成索引件。
7. **`cmd_scaffold` 表达不了多主体**（一个 `--entity` 给全部文件）⇒ 造「错主体」必须**手写 meta**。
8. **`version_status=DRAFT`** 的件不可被 MATCH/PARTIAL 引用（语义层当场拒收）⇒ 想让某件「不可用」就用 DRAFT。
9. **`score` 的 `status=LOW_CONFIDENCE`**：既有基线在义务数 < `min_obligations`（默认 30）时给这个状态；
   合成盲测只有 8 条义务 ⇒ `LOW_CONFIDENCE` **不是失败**（退出码仍是 0），本包**不改**这条既有语义。
10. **UNCERTAIN 的可观测形态**：在现有检索层里，被考侧引用别的主体件会被 R4/语义层**当场拒收**
    ⇒ 落到 `NO_ANSWER`（⇒ `FN`）。因此「错主体」在**评分层**的可观测形态是
    「**期望主体 ≠ 答卷件主体**」（合成盲测用「Gold 期望主体乙 / 答卷件主体甲」这一组覆盖该分类）。

---

## 9. A4b 段（真机真模型）：`BLOCKED`

- **触发条件**（全部满足才跑）：刘江 Windows 授权 + 模型额度可用 + 真实材料授权
  + **真实题面资产**（题面 / 逐题 CSV / 答案键）到位。
- **当前事实**：dsh 永久停用（2026-10-11 董事长令）；真实 Gold 未提供；
  真实材料授权目录已有但评分需人工确认 Gold；**题面资产在本机与仓内均未找到**
  （唯一来源是刘江 2026-10-21 审计报告与其 Windows 侧资产）⇒ A4b 除授权与额度外**还缺题面资产**。
- **本包不做**：不跑真模型、不花一分钱、不读真实标准答案包 ⇒ A4b 段标 `status: BLOCKED`，
  **不影响 A4a 的 PASS**。
- **硬 Gate**：`WINDOWS_REAL_E2E` 只在 A4b 真机段实际完成后才可推进；否则保持 `UNKNOWN`。
<!-- GM:A4A:DOC:END -->

> **阅读指引**：本文档**正文在 §0–§9**（本页前半部分，末尾有 `<!-- GM:A4A:DOC:END -->` 标记）。
> 下面这段是**附录：索引与勘误记录**，方便按判据回查；**不重复正文、不灌水**。
<!-- gm-fix-a4a-minors-batch2: appendix-numbering -->
> **本包只做「链路自检」**：合成盲测验证的是**盲化 → 冻结 → 拆分 → 跑 → 评分**这条链路通不通，
> **不是**「盲考通过」，也**没有任何模型参与**。

<!-- gm-fix-a4a-minors:doc-skeleton-replaced -->

## 附录 A · 五条线与实现位置（索引）

| 线 | 实现位置 | 判据 | 证据 |
|---|---|---|---|
| G-A4a-1 补料盲化 | `backend/src/cangjie_fos/services/dd_v1_blind_service.py` | A4-1 | `a4-evidence/a4-blind-exam-*.{json,csv}` |
| G-A4a-2 快照冻结 | `backend/src/cangjie_fos/services/dd_v1_snapshot_freeze_service.py` | A4-2 | `a4-evidence/a4-blind-exam-run.txt` |
| G-A4a-3 Gold 隔离 | `dd_v1_score_service.py`（隔离侧）＋复用 `sem.assert_gold_isolated` | A4-3 | `a4-evidence/a4-provenance.txt` |
| G-A4a-4 错误分类 | `dd_v1_score_service.py`（分类侧）＋包装 `sem.score_against_gold` | A4-4 | `a4-evidence/a4-blind-exam-errors.csv` |
| G-A4a-5 合成盲测 | `tools/dd_v1_local_run.py` 的 `--blind-*` / `--snapshot-freeze-dir` / `--synthetic-replies` / `--classify*` 开关 | A4-5 | `a4-evidence/a4-blind-exam-run.txt` |

## 附录 B · 各线正文位置（见上文 §0–§9）

## 附录 C · 坑与边界

见上文 **§8**「坑与边界（施工时踩过的）」（§6 是「CLI 新增开关一览」）。

## 附录 D · 本包勘误记录（A4a 独立 Reviewer ROUND1 裁定 PASS 后，司仓执行；含 ROUND2 复验结论）
<!-- gm-fix-a4a-errata-table: round2-rows -->

| # | Reviewer 判据发现 | 司仓处置 | 状态 |
|---|---|---|---|
| MINOR-1 | 交付的测试把 `--snapshot-freeze-dir` 指向**仓内** `frozen/examiner` 并在 `finally` 里 `rmtree` ⇒ **每跑一次全量 pytest 就毁掉交付证据**（与 A3 MINOR-4「doctor 用例改写 uv.lock」同型：测试写/删仓库文件） | 冻结目标改指 `tmp_path`（`freeze_snapshot()` 自己 mkdir，目标不必预先存在）⇒ **只改 2 行**；`finally` 的 `rmtree` 保留，但此时只清 `tmp_path` | **已修** |
| MINOR-2 | 文档尾部残留 7 处「（待补）」骨架（与正文 §0–§6 章节号重复） | 骨架段替换为本「索引 + 勘误记录」，不复制正文 | **已修** |
| MINOR-3 | 冻结变更检出的**进程内** mtime 盲区（同进程改文件后可能检不出；`ar.sha256_file` 带 (path,size,mtime) 缓存） | **不修**：任务书强制复用 `ar.load_snapshot`/`ar.sha256_file`（不重写 sha 口径），缓存是其既有行为；**跨进程检出正常**（MODIFIED/MISSING/EXTRA 三类均已实测检出）。规避写法：**在独立进程里验冻结变更**，不要在同一进程内改完立刻验 | 接受该 MINOR，如实登记 |
| **MINOR-4** | ★ **由 MINOR-1 的修复暴露出来的产品代码真缺陷**：`tools/dd_v1_local_run.py::cmd_run` 的「仓内合成 fixture 免 `--allow-real-material`」豁免，原按**盲化/冻结之后**的 `material_root` 判定；而 `_prepare_material` 会把材料搬到 `--blind-material-out` / `--snapshot-freeze-dir` ⇒ 冻结到**仓外**（`/tmp`）时豁免**不可达** ⇒ **合法的仓内合成 fixture 被误判为「真实材料」而拒绝（退出码 3）**。第一轮全量 1673 passed 没发现，是因为交付的测试恰好把冻结目标指回仓内，让豁免恰好可达 —— 交付物把自己的缺陷盖住了 | 捕获 `orig_material_root`，豁免判定改为「原始材料根 **或** 冻结后材料根，任一落在仓内 `backend/tests/fixtures` 下即豁免」。★ **不放宽真实材料**：原始材料根在仓外时仍必须 `--allow-real-material`（4 场景 × 2 版本矩阵实测：修复前后逐格相同） | **已修** |
| **MINOR-5** | ROUND2 复核发现：附录段沿用**数字章号** `## 0. / ## 6. / ## 7.`，与正文已占的 §0–§9 **章号撞车**（同一篇里两套同名章号） | 附录段三个标题改为**附录编号** `附录 A/B/C`（与正文 `## ` 章号物理不可能撞车） | **已修** |
| **MINOR-6** | 附录段写「见上文 §6「坑与边界」」，但正文的「坑与边界」是 **§8**（§6 是「CLI 新增开关一览」）⇒ 指错节 | 改指 **§8**，并注明 §6 是什么 | **已修** |
| **MINOR-7** | 阅读指引写「正文在 §0–§8」，正文实际到 **§9**（§9 = A4b 段）⇒ 范围说错 | 改为 **§0–§9**（两处：阅读指引 + 附录 B 指引行） | **已修** |
| **MINOR-8** | 权威模式串文件实为 **8 条**（今天为补齐短名口径追加 1 条），而 A3 证据文件里记的是 7 条 | **非缺陷**：扫描器 `a3_realname_scan.py` **运行时动态读**该文件，今天实为 8 条；A4a 独立复验已用 8 条口径重扫 ⇒ **0 命中**，不影响结论。只作记录口径差的登记 | **如实登记，非缺陷** |
| **OBS-1** | 冻结目标指向仓内 fixtures 时，仓外材料可绕过真实材料闸 | **既有行为、非本轮引入**（回退版行为完全相同）⇒ 不在本包改，只登记 | **如实登记** |

> 修完后的验收口径：**全量 pytest 跑完，仓内 fixture 逐件零改动**（工作树与会话开始状态逐行一致）。
>
> **ROUND2 独立复验结论**：`A4-REVIEW-VERDICT-ROUND2.md` —— **VERDICT: PASS**，判据 **A4-1…A4-11 = 11/11 全通过**，
> 0 BLOCKER / 0 MAJOR / 3 MINOR + 1 观察项。独立复跑全量 **1678 tests / 1673 passed / 0 failures / 0 errors / 5 skipped**（exit 0），
> 仓内 fixture **49/49 与开跑前 SHA256 逐字节一致**；MINOR-4 判别力（/tmp 副本回退 ⇒ exit 1 转红、带改动 ⇒ exit 0 转绿）、
> MINOR-3 跨进程三类检出（MODIFIED/MISSING/EXTRA）均已实测。
> ★ 另用**未归一化 AST** 口径复核：基线函数/模块级绑定/函数体标识符**无一消失** ⇒ **无任何既有标识符被改名**；
> 只读复用件 `dd_v1_semantic_retrieval_service.py` 对 HEAD **diff 为空**。
