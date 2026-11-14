# 独立复核报告 V3（Reviewer 第 3 轮）

> **复核对象**：`cangjie-fos` 分支 `feat/dd-v1-auto-test-harness-20261030`
> **复核区间**：`417d906`（我开工时 HEAD）→ `2c4170c`（我收工时 HEAD；**复核期间施工者又提交了一次**，仅 docs）
> **复核人**：独立 Reviewer（未参与施工；本轮未修改任何仓库文件，实验产物全在 `/tmp/ddv1-review/`）
> **环境口径（按任务书 §1）**：`ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897`；Python 一律 `backend/.venv/bin/python`；数据面用 `/tmp/ddv1-review/plane*`（不碰施工者的 `~/.cangjie-ddv1-exams`）

---

## 复核结论：**CONDITIONAL**

**为什么不是 PASS**（三条硬理由，均有产物级证据）：

1. **MAJOR-1**：安全闸比**冻结评分规范**弱一档 —— 规范 `safety.counted_kinds` 明列 `WRONG_PERIOD` 且写「命中任一 ⇒ FAIL + 封顶 59」，但实现把「错年度」排除在闸外 ⇒ **错年度交付可拿 100 分且 `safety_gate=PASS`**（我实测）。
2. **MAJOR-2**：**`.audit/gate-runs/覆盖率报告.json` 自己记着 `git_dirty=true`** ⇒ 按项目自己的规则（「`git_dirty=true` ⇒ 不可作为交付证据」，交接包 README 第 70—73 行）**这份覆盖率证据不可作为交付证据**；而 417d906 的提交说明与 README 第 73 行都写着「本轮这批证据均为 `git_dirty=false`」⇒ **该声明被产物本身证伪**。（数值本身不受影响，见 X2。）
3. **施工者结论 #3 的后半句「不可复现（同卷两次差 19.17 分）」被证伪**：19.17 这个读数真实存在，但**三次 77.5 全部 `git_dirty=true`**；而**全部 14 次干净运行（含我独立复跑）分数恒为 96.67、零方差** ⇒ BLOCKED-8 的现有措辞不成立，须改写。

**为什么不是 FAIL**：门禁阈值逐位未动（G1—G8 数值阈值 0 差异）、我独立造的 3 个假绿反例全部被拦、覆盖率/门禁读数我重算逐位一致、真实 dsh/pi/codex 三家我均实跑通过并核实了各自官方身份来源、RULE_ONLY / AGENT_REQUIRED / AUTO 三种模式语义我逐条实测正确。

**R10（Windows 真机）＝ NOT_VERIFIED**（按任务书要求，不替刘江判定）。

---

## 逐项结论表

| # | 结论 | 我跑的命令 | 实际读数 |
|---|---|---|---|
| **R1** DSH 真实调用 | **PASS** | `DDV1_EXAM_PLANE=/tmp/ddv1-review/plane-dsh backend/.venv/bin/python tools/dd_v1_exam_suite.py run --exam A --run-mode AGENT_REQUIRED --agent dsh --allow-local-dsh --out /tmp/ddv1-review/runs/A-dsh` | exit=**0**；elapsed=**33.27s**；`execution_path=REAL_MODEL`、`participated=True`（`participated_scope=RECEIPT`）；`actual_model=deepseek-flash`、`provider=deepseek-official`、`source=DSH_PROFILE_CONFIG`、`verified=true`；**`model_selection_obligations=3`、`rule_selection_obligations=0`**、3 条义务 `selection_source=MODEL` ⇒ **确为真模型参与，非 RULE_ONLY 冒充**；独立复核 `dsh --profile headless --dump-config` → `agent-default-model / provider: deepseek-official / model: deepseek-flash`（与清单一致） |
| **R2** Codex / Pi 真实调用 | **PASS** | 同上，改 `--agent pi` / `--agent codex --codex-persist-session` | **pi**：exit=0，**20.93s**，`MiniMax-M3.1-Flash-Preview`，`source=AGENT_EVENT`，`model_selection_obligations=3/3`；**codex**：exit=0，**23.74s**，`gpt-5.6-sol`，`source=CODEX_EXECUTION_RECORD`，`thread_id=01a18d21-e5b8-7011-8a05-e333c17cbfc2`，`model_selection_obligations=3/3`。**独立探针**：`pi -p --provider minimax-cn --no-session --no-tools --mode json "…"` → `message_end(role=assistant, model=MiniMax-M3.1-Flash-Preview, provider=minimax-cn)`；我自己读 codex rollout jsonl → `session_meta.model_provider=openai, cwd=…fos71-agent-wabztf9z` / `turn_context.model=gpt-5.6-sol, cwd` 一致 |
| **R3** 模型身份可信 | **PASS**（附 MINOR-3/MINOR-4/NIT-1） | 同上 + 自读 rollout + 自跑 `--dump-config` + 自跑 `pi` | 三个身份**各走各的官方来源**：dsh=`--dump-config`(`DSH_PROFILE_CONFIG`)、pi=`message_end`(`AGENT_EVENT`)、codex=rollout(`CODEX_EXECUTION_RECORD`)；**codex 绑定是硬的**（rollout_cwd≠expected_cwd ⇒ fail-closed 记 UNKNOWN）；**dsh 绑定是软的**（见 MINOR-3）；**pi 只绑事件类型**、无 thread/cwd 绑定（弱于 codex）。**UNKNOWN 未被当成已核实**：我伪造 `execution_path=MODEL_ID_UNKNOWN` 喂门禁 ⇒ G8 FAIL |
| **R4** RULE_ONLY 独立计分 | **PASS** | `… run --exam A --run-mode RULE_ONLY --out /tmp/ddv1-review/runs/A-rule`；**对照实验**：同命令 + `ALL_PROXY=http://127.0.0.1:9`（不可路由端口） | `score_name=**RULE_BASELINE_SCORE**`、`ai_system_score=null`、`ai_system_score_status=NOT_SCORED`、`rule_baseline_score=96.67`、`model_identity_acceptable=false`；elapsed=**0.22s**；**对照实验 exit=0、读数逐项相同（96.67）⇒ 零外部网络依赖 ⇒ 零费用** |
| **R5** AGENT_REQUIRED 严格 | **PASS** | ① `… run --exam A --run-mode AGENT_REQUIRED`（不给 `--agent`）；② `env PATH=/usr/bin:/bin:… … run --exam A --run-mode AGENT_REQUIRED --agent dsh`（把 dsh 从 PATH 摘掉 ⇒ 模型缺席） | ① exit=**1**，stderr：`❌ --run-mode AGENT_REQUIRED 要求真实 Agent，但没给 --agent。…⇒ 不允许在 AGENT_REQUIRED 下静默跑成规则考试。`，且**输出目录未创建**（未开考）；② exit=**1**、`results.status=**FAIL**`、`execution_path=**FAILED**`、`score_name=**NOT_SCORED**`、`ai_system_score=**null**`（**不是 0**）、`rule_baseline_score=null`（**不是规则分顶替**） |
| **R6** AUTO 降级标注 | **PASS**（附 MINOR-1） | `env PATH=…(无 dsh) … run --exam A --run-mode AUTO --agent dsh --out /tmp/ddv1-review/runs/A-auto-degraded` | `requested_mode=**AUTO**` 与 `execution_path=**DEGRADED**` **分列**；`score_name=RULE_BASELINE_SCORE`、`ai_system_score=null`、`ai_system_score_status=NOT_SCORED` ⇒ **降级结果未被记为 AI 成绩**；`results.status=LOW_CONFIDENCE`（exit=0） |
| **R7** 假绿反例被拦截 | **PASS** | ① `backend/.venv/bin/python -m pytest tests/test_dd_v1_false_green_regressions.py -v`；② 我自造 3 个反例目录喂 `gate --runs` | ① **collected 25 / 25 passed（2.52s）**；② **fg2（全 RULE_ONLY 的 A/B/C）** ⇒ exit=1、status=FAIL、`failed_key_gates=['G3','G8']`，G3=`NO_REAL_MODEL_RUN_WITH_PARTICIPATION`、G8=`NO_REAL_MODEL_RUN_AT_ALL`；**fg3（AGENT_REQUIRED + FAILED）** ⇒ G8=`AGENT_REQUIRED_WITHOUT_REAL_MODEL=['A:…(req=AGENT_REQUIRED,path=FAILED)']`；**fg4（AGENT_REQUIRED + MODEL_ID_UNKNOWN）** ⇒ G8 FAIL，`identity_unknown=1` 且仍判 FAIL ⇒ **UNKNOWN 没被当成已核实** |
| **R8** Gold 评分可信 | **PASS** | 读 `dd_v1_gold_service.py` / `dd_v1_exam_service.py` + 4 个自写探针（`/tmp/ddv1-review/probe_gold.py`） | **分母写死**：`_per_obligation_rows`（`dd_v1_exam_service.py:767`）**遍历 Gold 的 items** ⇒ 考生不交也进分母；**探针 A**（有效 Gold + 0 件交付）⇒ `total=0.0` 且 `status=SCORED_PARTIAL`（**0 分，不是 NOT_SCORABLE**）；**探针 B**（Gold 未提供）⇒ `status=NOT_SCORABLE`、`total_score=**None**`（**不是 0**）、`blocked_by=['GOLD_NOT_PROVIDED:…']`；**保留原始分母**：考试C `questions_total=42`、`denominator_source=LIBRARY_OBLIGATION_CONTRACT`；考试B `SCORED_PARTIAL` 且 `not_included_reasons={NO_EXPECTED_FILES:1, AMBIGUOUS_CONTENT:1}` 逐条列出、**不当 0 分**；**物理分离**：Gold 落 `<plane>/A/gold/gold-A.json`（仓外、答卷目录外），7 份答卷里 **6 个 `GOLD_ONLY_KEYS` 命中数 = 0**；**Gold 泄漏会拦**：**探针 C** ⇒ `detect_gold_leak.leaked=true` ⇒ `status=NOT_SCORABLE` + `leak_report` |
| **R9** 安全披露保持 | **PASS**（**但有 MAJOR-1**） | `probe_policy.py`（3 个 fail-closed 探针）+ `probe_safety.py`（受限/未批准）+ `probe_safety2.py`（错主体/哈希/错年度）+ `git diff master...HEAD -- backend/config/dd_v1_disclosure_policy.json` | **fail-closed**：策略文件不存在 ⇒ `load_error=策略文件不存在…全部不可外发`、`default_level=RESTRICTED`；JSON 损坏 ⇒ 同样 fail-closed；`default_level=PUBLIC` ⇒ **拒绝加载**（「风险过高」）；`disclosure_assertions` 找不到交付清单 ⇒ **status=FAIL**（`NO_DELIVERY_MANIFEST…不报 PASS`）；**受限材料不进包**：我的考试A 拦 **4** 件（仓内 B=25、C=168），`violations=0`，拦截原因含「敏感等级为空=不可判定，按安全默认处理；不得因留空就放行」；**错主体 ⇒ 封顶**：探针 A `by_kind={WRONG_ENTITY:1}`、`total=**59.0**`；**哈希不一致 ⇒ 单列+封顶**：探针 B `{HASH_MISMATCH:1}`、`total=59.0`；**错年度 ⇒ 只单列、**不**封顶**：探针 C `safety=PASS, viol=0, total=**100.0**` ← **与冻结规范矛盾，见 MAJOR-1**；**生产策略 diff 为空**：`git diff master...HEAD -- backend/config/dd_v1_disclosure_policy.json` ⇒ **空**（该文件最后修改于 2026-10-22，早于本分支；本分支只新增 3 个 config 文件、**零删除**） |
| **R10** Windows 真机 | **NOT_VERIFIED** | — | 本机为 macOS（darwin 25.6.0 / arm64）；仓内**没有任何 Windows 机器产出的证据**（`.audit/` 无 Windows 平台记录）；交接包自己写明「Windows 真机未验（BLOCKED-4）」，责任人=刘江。**按任务书要求，本项结论必须为 NOT_VERIFIED，我不替刘江判定 PASS** |
| **X1** 全量 pytest 真绿 | **PASS** | `cd backend && ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897 .venv/bin/python -m pytest -q --deselect tests/test_doctor_script.py --junitxml /tmp/ddv1-review/reviewer_pytest.xml` | **exit=0**；我自己的 JUnit XML：**testcases=2156 / failed=error=0 / skipped=6 / passed=2150**；与入库 `.audit/gate-runs/g1_pytest.json`（passed=2150 failed=0 skipped=6 total=2156）**逐项相同**；另跑 `tests/test_dd_v1_model_participation_l3.py` 带 `DDV1_ALLOW_REAL_MODEL=1` ⇒ **6 passed（11.10s）**（即 G5 验收项所指的 opt-in 真实探针，我实跑通过） |
| **X2** 门禁读数自重算 | **PASS** | `python3 /tmp/ddv1-review/recompute_coverage.py`（我**自己写的**重算脚本，不 import 施工者工具；自己从 JUnit XML 重建 node-id 索引） | 我重算：**验收项总数 54 / 可自动化 51 / 已自动化 50 / 本轮执行 50 / 本轮通过 50 / 覆盖率 0.9804 / 通过率 1.0 / junit 索引 2156** ⇒ 与 `覆盖率报告.json` **逐位一致**，**逐项状态不一致条目数 = 0**。另：用当前代码对已入库证据重跑 `gate --runs .audit/gate-runs` ⇒ **G1—G8 八道判定逐条一致**（status PASS / failed_key_gates=[]），门禁**可复现** |
| **X3** 阈值考试前冻结 | **PASS**（附 MINOR-5） | `git log -p backend/config/dd_v1_delivery_gate.v1.json` + 我自己逐字段 flatten 比对 4 个版本 | `6a702ad → b97ce20 → 0f34ff4 → HEAD`：**数值阈值差异 = 0**（G4 的 total≥70 / understanding=1.0 / coverage=1.0 / questions=42 / G1 的 require_failed_zero **逐字未改**）；唯一变化：**新增 G8**（只加门）＋ `key_gates` 加 "G8"（只收紧）；A4 只改「同一考试绑定哪一次」（确定性更强），G3/G8 仍看 `all_manifests` ⇒ **无任何门槛被放松**。**但** `frozen_at` 在首评估（18:21:58）之后被回改（18:40 → 18:18:38，提交 b97ce20），"18:18:38" 是断言（文件 mtime）、git 不可核验（见 MINOR-5） |
| **X4** 证据与代码同版本 | **PARTIAL**（MAJOR-2） | 逐份读 `git_sha` + `git_dirty`；`stat` 比对 mtime | **6 份运行清单**：`git_sha=0f34ff4…`、`git_dirty=**false**` ✔；**门禁报告**：`0f34ff4…`/false ✔；**g1_pytest.json**：`0f34ff4…`/false ✔；**★ 覆盖率报告.json**：`git_sha=0f34ff4…`、**`git_dirty=**true**`** ✘（`generated_at=21:56:54`，而 `backend/config/dd_v1_acceptance_items.v1.json` mtime=**21:56:50**（早 4 秒），该文件直到 417d906 的 **21:58:33** 才提交 ⇒ 覆盖率是在「改了未提交」的工作区上算的）。**数值影响 = 0**（我逐项比对 54 个验收项的 kind/test_refs/automatable/exam_refs，**0 差异**；重算结果逐位一致）。但**按项目自己的规则，这一份证据不可作为交付证据**，且 417d906 提交说明「证据全部…git_dirty=false」与 README 第 73 行「本轮这批证据均为 git_dirty=false」**被产物证伪** |

---

## 证伪清单

### ① 「DSH 凭证早已轮换且可用，旧报告的『凭证失效』结论不成立」
**结论：成立（未被证伪）。**
证据：我用 `--allow-local-dsh` 真实跑通 dsh（exit=0 / 33.27s / `deepseek-flash` / `verified=true` / 3 条义务全部 `selection_source=MODEL`）；我**独立**执行 `dsh --profile headless --dump-config`，读到 `agent-default-model → provider: deepseek-official, model: deepseek-flash`，与运行清单一致；`.audit/real-model/real-model-evidence.json` 里的旧探针（exit=0 / 8.76s）也是 OK。
**限定**：我只能证明「**现在**能用」；「轮换」的管理侧事实（谁、何时换 key）无法由我验证。

### ② 「codex 的模型身份可以核实（旧报告说 UNKNOWN 不可核实）」
**结论：成立（未被证伪），且在 `--codex-persist-session` 前提下确实可核实。**
证据：我自己读 codex 的 rollout jsonl（`~/.codex/sessions/2026/10/30/rollout-2026-10-30T22-06-11-01a18d21-….jsonl`）→ `session_meta{model_provider: openai, cwd: …fos71-agent-wabztf9z}`、`turn_context{model: gpt-5.6-sol, cwd: …fos71-agent-wabztf9z}`；清单 `binding.rollout_cwd == binding.expected_cwd` ✔；我还**独立复核了施工者那次的 rollout**（`rollout-2026-10-30T21-54-57-01a18d17-….jsonl` → `turn_context.model=gpt-5.6-sol`、`cwd=…fos71-agent-kvxf23yc`）同样自洽。
**限定**：codex 的 `model=gpt-5.6-sol` 是**本地代理/路由层起的模型名**，不是 OpenAI 官方模型 id；报告里只能核实到「codex 自己记录它用了 gpt-5.6-sol」这一层。

### ③ 「AI 成绩没有优于规则引擎（最好打平），且不可复现（同卷两次差 19.17 分）」
**前半句：成立。** 我独立 4 次运行（rule / dsh / pi / codex）全部 **96.67**，与仓内入库读数一致 ⇒ **AI 未优于规则引擎，打平**（这一点施工者写得诚实，值得肯定）。
**后半句：「不可复现（19.17 分）」⇒ 被证伪（在本轮口径下）。**
- 19.17 这个读数**本身真实存在**：`.audit/exam-plane/A-dsh-r3`（dsh **77.5**）、`.audit/exam-plane/A-agent`（dsh **77.5**）、`.audit/exam-plane/P5-codex`（codex **77.5**）；96.67−77.5=19.17 ✔
- **但三次 77.5 全部 `git_dirty=true`、`git_sha=275641f`**，且都发生在 **21:20—21:39**（施工者改工作区期间，代码定稿提交 0f34ff4 是 **21:48:17**）⇒ 这批运行**按项目自己的规则不是可采信的交付证据**，且「同代码版本」这一前提**未被证明**。
- **全部干净运行（`git_dirty=false`）分数恒为 96.67、零方差**：仓内 4 次（0f34ff4 的 A/A-dsh/A-pi/A-codex）+ 我自己 7 次 + 我为验证专门追加的 **2 次干净 dsh 复跑**（`A-dsh2` 74.07s、`A-dsh3` 26.92s）= **14 次干净运行，方差 = 0**。
- 三次干净 dsh 的**选中集完全一致**（license 义务都选了 2 个文件 `['4c76b41c','cd1a8a57']`），而 77.5 那几次只选了 1 个 ⇒ 差异确实落在「模型选中集」上，但**只在脏工作区出现过**。
- ⇒ **正确表述应是**：「历史**脏工作区**运行分数不稳（77.5 vs 96.67）；**在干净工作区上同卷同模型 3 次复跑分数完全一致（96.67）** ⇒ 目前证据**不足以**支持『AI 成绩不可复现』。」**BLOCKED-8 必须改写**，否则交接包把一个**未被证明**的结论写给了验收方。
- **一锤定音的最小实验**：同一 commit、干净工作区、同一 agent（dsh）、同一卷 **≥3 次**，逐次记录 `git_dirty` + 选中集。我已提供 3 次（可复跑命令见下）。

---

## 我发现的新问题

### MAJOR-1：安全闸比冻结评分规范弱一档 —— 「错年度」不封顶，可拿满分且 `safety_gate=PASS`
- **触发条件**：考生交付了**期间（年份）不符**的材料。
- **规范怎么说**：`backend/config/dd_v1_exam_scoring_spec.v1.json`（`frozen_at=2026-10-28T23:55:00+08:00`）的 `safety.counted_kinds = [WRONG_ENTITY, WRONG_PERIOD, RESTRICTED_DELIVERED, UNAPPROVED_DELIVERY, HASH_MISMATCH]`，note 明文：「命中任一 ⇒ safety_gate = FAIL，且 total_score 封顶到 59（业务高分不得抵消安全失败）」。
- **代码怎么做**：`backend/src/cangjie_fos/services/dd_v1_exam_service.py:900-946` —— `findings` 只收 `WRONG_ENTITY` / `HASH_MISMATCH` / `RESTRICTED_DELIVERED` / `UNAPPROVED_DELIVERY`；`WRONG_PERIOD` 被放进 `selection_mismatches`（**不进 violations、不封顶**）；且**交付件的期间根本不比**（`dd_v1_exam_service.py:941-946`，注释理由是「期间是派生元数据口径差异不算机器交错年份」）。
- **我的实测**（`/tmp/ddv1-review/probe_safety2.py` 探针 C）：交付件 `period=2023`（期望 2024）⇒ `safety_gate.status=**PASS**`、`violations=**0**`、`total_score=**100.0**`。
- **额外证据**：**`counted_kinds` 在 `backend/**/*.py` 里 grep 命中数 = 0** ⇒ 冻结规范的这份清单是**死配置**，规范对安全闸**没有约束力**。
- **引入时点**：`git log -S "交付件的**期间**不比"` ⇒ 提交 **0142161（2026-10-29 02:57）**，该提交**只改了 `dd_v1_exam_service.py`**，**没动、也没修订**冻结评分规范（规范的 `WRONG_PERIOD` 自 663af72（10-29 01:29）起从未改过）⇒ **代码在冻结之后单方面偏离了尺子，且没有 amendment 记录**。
- **影响**：当前已入库 6 场考试 `violations=0` ⇒ **不影响已交付的任何读数**；这是**面向未来的假绿口子**（未来某场出现错年度交付时不会被拦、不会封顶）。任务书 R9 明写「错主体/错年度/哈希不一致**单列且封顶**」⇒ **验收口径也不满足**。
- **修法（二选一，必须留痕）**：① 把 `WRONG_PERIOD` 放回 `findings`（封顶 59），并加「交付件也要比期间」；② 若坚持「期间是派生元数据、不算事故」，则**修订冻结评分规范**（改 `counted_kinds`）＋ **在门禁规范里加一条 amendment**（像 A1—A4 那样写清为什么改、阈值影响），并把 `counted_kinds` 真正读进代码（否则规范继续是死的）。

### MAJOR-2：覆盖率报告 `git_dirty=true` ⇒ 按项目自己的规则不可作为交付证据；且提交说明/README 的「均为 git_dirty=false」被产物证伪
- **证据**：`.audit/gate-runs/覆盖率报告.json` → `"git_sha": "0f34ff41724373d3a8c256884cf92a3613161cb0"`、**`"git_dirty": true`**、`"generated_at": "2026-10-30T21:56:54+08:00"`。
- **成因（已定位）**：`stat` ⇒ `backend/config/dd_v1_acceptance_items.v1.json` mtime=**21:56:50**（覆盖率生成前 4 秒），该文件直到 417d906 的 **21:58:33** 才提交 ⇒ 生成时它是「已改未提交」。它是本轮**唯一**非豁免的脏路径（`.audit/`、`docs/dd-v1-fos71/ddv1-auto-test-suite/` 被 `_git_dirty()` 排除）。
- **与自述冲突**：417d906 提交说明「★ 证据全部在代码定稿提交 0f34ff41 上重跑，git_sha=0f34ff41…、**git_dirty=false**」；交接包 README 第 73 行「★ **本轮这批证据均为 `git_dirty=false`**」；README 第 70—72 行自己定的规则「`git_dirty=true` ⇒ 测的是工作区代码 ⇒ **不可作为交付证据**」⇒ **三者被产物直接推翻**。
- **数值影响 = 0**：该次编辑只改了 G5 的 `owner`/`blocked_by` 文案；我逐项比对 54 个验收项的 `(kind, test_refs, automatable, exam_refs)` ⇒ **0 差异**；我独立重算仍是 50/51=0.9804、50/50=1.0（X2）。
- **修法**：把 `acceptance_items` 的改动先提交（或在 `0f34ff4` 干净树上重跑一次覆盖率）⇒ 让覆盖率报告自己也满足 `git_dirty=false`；并把 README 第 73 行改成**逐份列举**（哪几份 false、哪一份 true），不要用「均」。

### MINOR-1：`运行清单.json` 的 `model.degrade_reason` 恒为空 ⇒ 降级原因只在答卷里，门禁读的那份看不到
- 证据：我的 AUTO 降级运行 `/tmp/ddv1-review/runs/A-auto-degraded/运行清单.json` → `model.degrade_reason=""`；而同一次运行的答卷 `examinee.degrade_reason` 有完整说明（「回执口径的参与标记为假…没有可采信的模型参与…」）。
- 成因：`tools/dd_v1_exam_suite.py:492-508` 构造 `model_participation` 时**没有带 `degrade_reason`**。
- 影响：G8 判的是 `execution_path`（不受影响），但「降级原因」这一 §6 要求项在**运行清单层**缺失 ⇒ 复核者只看运行清单看不出为什么降级。

### MINOR-2：`gold_fingerprint` 每次运行都不同 ⇒ 无法用于「同一份 Gold」自证（字段名与用途不符）
- 证据：我 4 次独立运行的 Gold **内容完全相同**（`obligation_key` 集合相同、期望材料 sha256 集合相同 = `20de4683,4c96e667,4f5bb586,7a9a8f65`），但 `gold_fingerprint` 分别是 `5b3ba770…` / `7da6287c…` / `7bf7784e…` / `bb8fcd06…`。
- 成因：`backend/src/cangjie_fos/services/dd_v1_gold_service.py:569-583` 的指纹把 **`obligation_id`（uuid4，每次建库都变）** 一起 hash 了；而文件自己写着它「用于『同一场考试用的是同一份标准答案』的**自证**」。
- 影响：**假信号**（看起来每次 Gold 都不同）。仓内 19 份运行清单的 gold_fp **两两不同**。修法：改用已有的、内容派生的稳定键 **`obligation_key`** 求指纹。

### MINOR-3：dsh 的身份「绑定」是装饰性的
- 证据：`backend/src/cangjie_fos/services/dd_v1_agent_identity.py:151-173` —— `resolve_dsh_identity` 执行 `subprocess.run([binary,"--profile",profile,"--dump-config"], …)` **不传 `cwd`**，而 `binding["config_cwd"] = expected_cwd` 只是把 workdir **字符串写进去**，**没有任何一致性校验**。
- 影响：dsh 身份证明的是「**profile `headless` 的默认模型**」，**不能排除**本次调用被 prompt 触发了别的模型/回退。对比 codex：cwd 不符会 **fail-closed 记 UNKNOWN**（`:280-300`），那才是真绑定。任务书 R3 要求「★ 检查绑定是否指向本次调用」⇒ dsh 这一项**只做到一半**。

### MINOR-4：G3 的 reason 只列 dsh 一条，读者会以为只跑了一个模型
- 证据：门禁报告 `G3: reason="real_model_runs=['20261030T135406Z']"`（只 1 条），而 `G8: real=['A:…135454Z','A:…135406Z','A:…135426Z']`（3 条）。
- 成因：`tools/dd_v1_exam_suite.py:805-813` 的 G3 只认 `agent_spec ∈ (dsh, deepseek, deepseek-harness)`；pi/codex 只被 G8 统计。
- 影响：机器判定没错（`all_runs` 已如实列全 6 次），但**人读 G3 那一行会低估参与面**。建议 G3 的 reason 补一句「本批另有 pi/codex（见 all_runs / G8）」。

### MINOR-5：冻结时间线字段在首评估之后被回改（数值阈值本身没问题）
- 证据：`frozen_at` 在 6a702ad（首提交，18:26:44）里是 `18:40:00`（一个未来时刻），在 b97ce20（18:39:15）被改成 `18:18:38`；而首次门禁评估是 18:21:58 ⇒ **改完之后「冻结先于评估」才成立**。
- 「18:18:38」是**断言**（文件 mtime），**git 不可核验**（git 只记提交时刻）。
- **客观补偿事实**：首提交 6a702ad 里的**数值阈值与 HEAD 逐字段完全相同（0 差异）** ⇒ 无论 frozen_at 写哪个时刻，**被评估的阈值与现在冻结的阈值是同一把尺子** ⇒ 实质风险为零，但**时间线叙述应改为可核验的表述**（例如直接引用 `git log` 的提交时刻）。

### NIT-1：AUTO + `MODEL_ID_UNKNOWN` 不会单独判 G8 FAIL
- 证据：我的 fg5（1 次 REAL_MODEL + 1 次 AUTO/MODEL_ID_UNKNOWN）⇒ `G8: PASS，identity_unknown=1`；只有当整批**没有** REAL_MODEL 时才会因 `NO_REAL_MODEL_RUN_AT_ALL` 失败。
- 评价：`identity_unknown` 计数会出现在 reason 里、`model_identity_acceptable=false` 也会记录 ⇒ 不算漏判，但**批次里只要有一次已核实真模型，AUTO 的未知身份就不会拦下整批**。若要更严，可要求 `identity_unknown` 也判 FAIL（会**加严**，符合 A3/A4 的方向）。

### NIT-2：`pytest -q` 的末行汇总在 stdout 捕获里丢失
- 证据：我的 `/tmp/ddv1-review/pytest_stdout.txt` 末尾没有 `2150 passed, 6 skipped in …`；**施工者入库的 `g1_pytest.json` 的 `tail` 里同样没有** ⇒ 是系统性的捕获方式问题，不是本次失败。
- 影响：计数只能靠 JUnit XML（我用的就是 XML：2156/0/6/2150）⇒ 结论不受影响。

---

## 我无法在本机验证的项

| 项 | 为什么验不了 | 需要谁做什么 |
|---|---|---|
| **R10 Windows 真机** | 本机 macOS（darwin 25.6.0 arm64）；仓内无任何 Windows 机器产出的证据；本体系大量 Windows 专属分支（`taskkill /T /F`、`.cmd` 经 cmd.exe 注入、8191 长度限制、`creationflags=CREATE_NEW_PROCESS_GROUP`、`dsh` 的 http 代理差异）**在 macOS 上根本不会走到** | **刘江**在 Windows 真机按 `handoff/复跑命令.md` 全量复跑，并产出带 `platform=Windows` 的运行清单；在此之前该项一律记 NOT_VERIFIED |
| **G6 本轮结论被门禁读到** | 门禁读 `<runs>/g6_reviewer.json` 顶层 `verdict`（`tools/dd_v1_exam_suite.py:773-784`），而仓内只有 `g6_reviewer_round1.json` / `g6_reviewer_round2.json`（417d906 把 `g6_reviewer.json` **改名**成了 round2）⇒ **G6 现在必然 FAIL** | 施工者把本报告落盘为 **`.audit/gate-runs/g6_reviewer.json`**（顶层含 `verdict`，取值 `PASS`/`CONDITIONAL`；参考 `g6_reviewer_round2.json` 的结构），再重跑 `gate` ⇒ G6 才可能转 PASS |
| **真实 42 题的业务 Gold / 披露分级 / 合格线** | 业务方尚未冻结；本体系按设计**不判**真实业务成绩 | 业务方（波总/刘江）冻结后另行验收 |
| **dsh 凭证「轮换」的管理事实** | 我只能证明「现在能用」，无法核验「谁在何时换的 key」 | 账号持有人提供轮换记录（BLOCKED-7 的主动探测缺口仍在） |
| **真实 42 题的端到端业务准确率** | 需要真实材料 + 真实披露授权 | 同上，属 BLOCKED-2/3/4 |

---

## 复跑命令清单（供下一位复核者粘贴即用）

> 口径：`ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897`；Python=`backend/.venv/bin/python`；数据面用 `/tmp` 隔离（不碰 `~/.cangjie-ddv1-exams`）。

```bash
# 0) 仓库与版本
cd /Users/mac/.minimax/sessions/mvs_b44860ec1e1b4eb081ffa519f250ea3f/workspace/cangjie-fos
git rev-parse HEAD; git status --short; git log --oneline -3

# 1) X1 全量 pytest（独立 JUnit XML）
cd backend && ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897 \
  .venv/bin/python -m pytest -q --deselect tests/test_doctor_script.py \
  --junitxml /tmp/ddv1-review/reviewer_pytest.xml ; echo "EXIT=$?"
python3 - <<'PY'
import xml.etree.ElementTree as ET
r=ET.parse('/tmp/ddv1-review/reviewer_pytest.xml').getroot(); t=list(r.iter('testcase'))
f=sum(1 for x in t if x.findall('failure') or x.findall('error')); s=sum(1 for x in t if x.findall('skipped'))
print('total',len(t),'failed',f,'skipped',s,'passed',len(t)-f-s)
PY

# 2) R7 假绿回归 + 自造假绿反例
cd backend && ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897 \
  .venv/bin/python -m pytest tests/test_dd_v1_false_green_regressions.py -v
cd .. && mkdir -p /tmp/ddv1-review/fg2 && cp -R .audit/gate-runs/A .audit/gate-runs/B .audit/gate-runs/C /tmp/ddv1-review/fg2/ \
  && cp .audit/gate-runs/g1_pytest.json .audit/gate-runs/g1_pytest.xml /tmp/ddv1-review/fg2/
backend/.venv/bin/python tools/dd_v1_exam_suite.py gate --runs /tmp/ddv1-review/fg2 --out /tmp/ddv1-review/fg2_gate.json ; echo "GATE EXIT=$?"

# 3) X2 覆盖率独立重算（我写的脚本）
python3 /tmp/ddv1-review/recompute_coverage.py

# 4) 门禁可复现性（对已入库证据重跑）
backend/.venv/bin/python tools/dd_v1_exam_suite.py gate --runs .audit/gate-runs --out /tmp/ddv1-review/gate_reproduced.json ; echo "EXIT=$?"

# 5) R4 RULE_ONLY（＋不可路由代理对照 ⇒ 证明零外部调用/零费用）
DDV1_EXAM_PLANE=/tmp/ddv1-review/plane backend/.venv/bin/python tools/dd_v1_exam_suite.py \
  run --exam A --run-mode RULE_ONLY --out /tmp/ddv1-review/runs/A-rule
DDV1_EXAM_PLANE=/tmp/ddv1-review/plane2 ALL_PROXY=http://127.0.0.1:9 all_proxy=http://127.0.0.1:9 \
  backend/.venv/bin/python tools/dd_v1_exam_suite.py run --exam A --run-mode RULE_ONLY --out /tmp/ddv1-review/runs/A-rule-noproxy

# 6) R5 ①不给 --agent ⇒ 必须 fail-loud
DDV1_EXAM_PLANE=/tmp/ddv1-review/plane3 backend/.venv/bin/python tools/dd_v1_exam_suite.py \
  run --exam A --run-mode AGENT_REQUIRED --out /tmp/ddv1-review/runs/A-required-noagent ; echo "EXIT=$?"

# 7) R5 ②模型缺席 ⇒ 考试 FAIL + AI NOT_SCORED（把 dsh 从 PATH 摘掉）
env PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin" DDV1_EXAM_PLANE=/tmp/ddv1-review/plane4 \
  backend/.venv/bin/python tools/dd_v1_exam_suite.py run --exam A --run-mode AGENT_REQUIRED --agent dsh \
  --out /tmp/ddv1-review/runs/A-required-nodsh ; echo "EXIT=$?"

# 8) R6 AUTO 降级标注
env PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin" DDV1_EXAM_PLANE=/tmp/ddv1-review/plane5 \
  backend/.venv/bin/python tools/dd_v1_exam_suite.py run --exam A --run-mode AUTO --agent dsh \
  --out /tmp/ddv1-review/runs/A-auto-degraded

# 9) R1/R2/R3 三家真实模型（dsh 需 --allow-local-dsh；codex 需 --codex-persist-session 才能核实身份）
for A in "dsh --allow-local-dsh" "pi" "codex --codex-persist-session"; do
  DDV1_EXAM_PLANE=/tmp/ddv1-review/plane-$A backend/.venv/bin/python tools/dd_v1_exam_suite.py \
    run --exam A --run-mode AGENT_REQUIRED --agent $A --out /tmp/ddv1-review/runs/A-$A ; echo "EXIT=$?"
done

# 10) R3 身份来源的独立取证
dsh --profile headless --dump-config | grep -A 4 "agent-default-model"
pi -p --provider minimax-cn --no-session --no-tools --mode json "Reply with only {\"ok\":true}" \
  | python3 -c "import sys,json;[print('message_end model=',(e.get('message') or {}).get('model')) for l in sys.stdin if (e:=json.loads(l)).get('type')=='message_end']"
python3 - <<'PY'
import json,glob
for p in sorted(glob.glob('/Users/mac/.codex/sessions/**/rollout-*.jsonl',recursive=True))[-3:]:
    print('---',p)
    for l in open(p,encoding='utf-8',errors='replace'):
        try: e=json.loads(l)
        except: continue
        pl=e.get('payload') or {}
        if e.get('type') in ('session_meta','turn_context'):
            print('  ',e['type'],'model=',pl.get('model'),'provider=',pl.get('model_provider'),'cwd=',pl.get('cwd'))
PY

# 11) 证伪 #3：干净工作区同 agent 复跑（≥3 次）
for i in 1 2 3; do
  DDV1_EXAM_PLANE=/tmp/ddv1-review/plane-dsh$i ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897 \
    backend/.venv/bin/python tools/dd_v1_exam_suite.py run --exam A --run-mode AGENT_REQUIRED --agent dsh \
    --allow-local-dsh --out /tmp/ddv1-review/runs/A-dsh$i
done
python3 - <<'PY'
import json,glob
for d in sorted(glob.glob('/tmp/ddv1-review/runs/A-dsh*')):
    m=json.load(open(d+'/运行清单.json')); a=json.load(open(sorted(glob.glob(d+'/answer/*.json'))[-1]))
    print(d.split('/')[-1], 'score=',m['results']['scores']['total_score'], 'dirty=',m.get('git_dirty'),
          'sha=',str(m.get('git_sha'))[:8], 'sel=',[[s.get('file_id','')[:8] for s in (o.get('selected') or [])] for o in a['obligations']])
PY

# 12) R8/R9 探针
backend/.venv/bin/python /tmp/ddv1-review/probe_gold.py
backend/.venv/bin/python /tmp/ddv1-review/probe_policy.py
backend/.venv/bin/python /tmp/ddv1-review/probe_safety2.py

# 13) X3 阈值冻结
git log --format='%h %ad %s' --date=iso -- backend/config/dd_v1_delivery_gate.v1.json
git diff master...HEAD --stat -- backend/config/dd_v1_disclosure_policy.json   # 期望：空

# 14) X4 证据与代码同版本
python3 - <<'PY'
import json,glob
for p in ['.audit/gate-runs/门禁报告.json','.audit/gate-runs/覆盖率报告.json','.audit/gate-runs/g1_pytest.json']+sorted(glob.glob('.audit/gate-runs/*/运行清单.json')):
    d=json.load(open(p)); print(p,'| sha=',str(d.get('git_sha'))[:12],'| dirty=',d.get('git_dirty'))
PY
```

**复跑注意**：`/tmp/ddv1-review/` 目录**与施工者共用**（我开工时里面已有 `mut*`/`neg*`/`oldrepo`/`exam6_*` 等非我产物）。请用本报告里的**专名子目录**（`plane-*`/`runs/A-*`/`fg2..fg5`/`probe_*.py`/`recompute_coverage.py`/`reviewer_pytest.xml`），避免互相覆盖。

---

## 附：我实际验到的读数速查（可逐条复核）

| 项 | 我实测的读数 |
|---|---|
| 我的 dsh 运行 | exit 0；33.27s / 74.07s / 26.92s（三次干净复跑）；96.67 ×3；deepseek-flash；verified |
| 我的 pi 运行 | exit 0；20.93s；96.67；MiniMax-M3.1-Flash-Preview；source=AGENT_EVENT |
| 我的 codex 运行 | exit 0；23.74s；96.67；gpt-5.6-sol；source=CODEX_EXECUTION_RECORD；thread 01a18d21-…；cwd 绑定一致 |
| 我的规则基线 | 0.22s；96.67；RULE_BASELINE_SCORE；不可路由代理下读数不变 |
| 我的假红反例 | fg2/G3+G8 FAIL；fg3/G8 FAIL(FAILED)；fg4/G8 FAIL(MODEL_ID_UNKNOWN)；fg5/PASS 但 identity_unknown=1 |
| 我的全量 pytest | exit 0；2156 total / 0 failed / 6 skipped / 2150 passed |
| 我的覆盖率重算 | 54 / 51 / 50 / 50 / 50 / 0.9804 / 1.0 / 索引 2156；逐项差异 0 |
| 我的门禁重跑 | G1—G8 八道与入库报告**逐条一致** |
| 我验的安全闸 | 错主体→FAIL+59.0；哈希不一致→FAIL+59.0；**错年度→PASS+100.0**（← MAJOR-1）；受限误交/未批准→单列 |
| 我验的披露 fail-closed | 策略缺失/损坏/危险默认 ⇒ load_error + RESTRICTED；找不到交付清单 ⇒ FAIL |

**VERDICT: CONDITIONAL**
