# FOS #71 · WP-A5 收口报告（A5-CLOSEOUT）

- 工作包：`T-DD-V1-REALINT-2026-WP-A5`（规格分支 `origin/spec/71-ddv1-real-engine-integration-20261021` = `453957e`）
- 工作树：`/Users/mac/cangjie-fos-wt-a5` @ `453957e`，分支 `feat/71-a5-closeout`
- 本包性质：**research / 收口包**（只新建 `A5-CLOSEOUT.md` + `a5-evidence/**`，不改任何产品代码）
- 判据：A5-1…A5-10（见规格 `PROJECT-ROADMAP-PLAN-TASKS-ACCEPTANCE.md` §2 硬 Gate 与任务书第 1 段）
- ★ 证据全部为**活体读数**（命令 + 输出），不是复述；每个数字都能在 `a5-evidence/` 里找到出处
- ★ 本文档**零真实客户名 / 零材料库代号**（已过交付面扫描，见 A5-7）

---

## 0. 一页结论

| 判据 | 结论 | 依据 |
|---|---|---|
| A5-1 硬 Gate 全表复核 | **完成**（HG-01…HG-09 逐条判定） | §1 |
| A5-2 双进度条复算 | **完成**：工程 **4/6 = 67%**、效果 **0/100**，分母 6 未动 | §2 |
| A5-3 续棒演练 | **完成（真实闭环 · 两段全通）**：真实调度 → 唯一 Executor → 真实产物 → 独立门 → **自动下一项**（活体读数：① 第一段 门 `action=COMPLETED`、`unittest_ran_count=4051`、**新增失败 0** ⇒ `WP-DRILL-1=COMPLETED` ⇒ `current_wp` **自动前进**到 `WP-DRILL-2`；② 第二段 WP-DRILL-2 的门 `action=COMPLETED`、`unittest_ran_count=4076`、`consumed=true` ⇒ `WP-DRILL-2=COMPLETED` ⇒ **演练包整体 COMPLETED**） | §3 + `a5-evidence/07-drill-real-loop-evidence.txt` |
| A5-4 Lease / 单主 | **PASS**：运行时 lease 唯一 + 单一派工入口 + worktree 单写者 lease 生效 | §4 |
| A5-5 会话结束后下一 WP 仍有有效产物 | **PASS**（以「门 PASS + 接棒 + 下一 WP 真实派工 + **下一 WP 自己也过门**」为证：WP-DRILL-2 由接棒机制**自动**派出（`dispatch_state` 有 `pid` 与 `spec_path`）⇒ 其产物 `scripts/gm_drill_gate.py` / `tests/test_drill_gate.py` 由运行时**自动提交**（`WP_ARTIFACTS_COMMITTED`，sha `851c8e7c`）⇒ 它自己的门也 `action=COMPLETED`） | §3.4 |
| A5-6 零回归 / 不越权 | **PASS**（改动面逐件对账；白名单外 0） | §6 |
| A5-7 敏感 | **PASS**：交付面真实名 / 代号 **0 命中** | §7 |
| A5-8 Skills 复盘及审计 | **完成**：给出可数数字 + 出处 | §8 |
| A5-9 证据冻结 + 出厂三项自检 | **PASS**：SHA256 清单全 OK / 真实名零命中 / provenance 当场打印 | §9 |
| A5-10 A4 遗留必查项 | **PASS**：3 处纯文档修正复核通过 + 勘误表补全 | §10 |

★ **效果进度仍是 0/100**：本包是接线与收口，**不产生效果分**；A4b 真机盲考仍 BLOCKED（§11）。

---

## 1. A5-1 · 硬 Gate 全表复核（HG-01…HG-09）

> 判据原文取自 `PROJECT-ROADMAP-PLAN-TASKS-ACCEPTANCE.md` §2（硬 Gate 表）。
> 判定依据给出**文件路径 + 行号**；并说明**为什么它不是该条的反例**。

### HG-01 单 writer / 单 GM

- **判定：PASS**
- 依据：运行时 lease 唯一 —— `data/gm_runtime_lease.json`（`holder=controller-44433`、`generation=35`、`ttl_s=180`，心跳每轮刷新）；
  单写者 lease 机制 `gm/worktree_ownership.py`（`claim()` :151 起 / `release` / `is_owner_live()` :102）；
  派工侧单入口 `gm/runtime_watchdog/transport.py::dispatch_order`（:1695）与 `dispatch_order_with_fallback`（:1194），
  `max_concurrent=1` + 文件锁（`gm/runtime_watchdog/lock.py`）防重复派工。
- **不是反例**：反例是「两实例写同分支 / Issue 评论当 ACK」。本包**没有第二个调度器**：
  活体进程证据见 §4.2（只有 `com.gm.runtime-controller` 一个 launchd 作业在派工）。

### HG-02 真实 FOS 调用

- **判定：PASS（接线层）/ 交付层未合入（见下）**
- 依据（★ **三层口径，不可混**）：
  1. **能力层**：`dd_v1_package_service.build_review_pack` 存在于 FOS 内
     （`backend/src/cangjie_fos/services/dd_v1_package_service.py:251`），可产四件套（:323 写核对表/缺口清单/证据说明/Manifest+hash）。
  2. **接线层**：薄入口已接 —— `tools/dd_team_channel.py:279-280`
     （`from cangjie_fos.services import dd_v1_package_service as pkg` → `pkg.build_review_pack(...)`）；
     批准与组包走同一服务（`:338-339`：`approve()` / `package_approved()`，HG1 闸在 `package_approved` → `assert_approval`）。
     ★ A0 的 call-trace 在 **A4 树 @ `c44700f`** 上实测 **13/13** 触达（`a5-evidence/03-fos-contract-chain-trace.txt`）。
  3. **交付层**：**master 仍未合入 A3/A4**（PR #80 未合并）⇒ master 上复现「入口只出 2 文件、无审核包」是
     **合分支未做**的必然结果，**不是接线漏做**（监工第 70 轮独立核实，结论与司仓一致）。
- **不是反例**：反例是「只看文件存在、重写 exam2_lib 跑分」。本包的判据是**官方 FOS 代码入口被真实调用**
  （call-trace 记录服务调用次数：`dd_v1_package_service` 223 次、`qc_service` 25 次、`selection_service` 81 次），
  且**结论随被测树行为翻转**（A2 树 `package_service_called=false`、A3 树 `=true`，同一段观察代码）。

### HG-03 Gold 盲隔离

- **判定：PASS（A4a 合成盲测层）/ A4b 真机层 BLOCKED**
- 依据：`backend/src/cangjie_fos/services/dd_v1_snapshot_freeze_service.py`（冻结快照，Gold 留在执行机不可读位置）、
  `dd_v1_blind_service.py`（盲测判定）；证据 `backend/tests/fixtures/dd-v1-fos71-a4/gold/`（**仓内合成 Gold**，非真 Gold）、
  A4a 独立裁定 `work/evidence/W-DD-V1-REALINT-2026-WP-A4/A4-REVIEW-VERDICT-ROUND2.md`（A4-1…A4-11 = 11/11 PASS）。
- **不是反例**：反例是「路径里带题号、执行时可读 Gold」。A4a 的路径无题号；**真 Gold 从未进入本机**（§11 记录：42 题题面/逐题 CSV/答案键资产本机与仓内均未找到）。

### HG-04 数据与费用

- **判定：PASS**
- 依据：披露分级 `dd_v1_match_service.py:65`（`V_RESTRICTED`）、`:964`（受限判定）；
  义务分类 `dd_v1_requirement_service.py:148`（`license` → 营业执照/登记证书）、`:166`（执照正本/副本并存）；
  材料只读授权目录 `~/dd-v1-realbase/**`，**产物落 scratch、不进 Git、不外发**；
  执行器只用已准入的 `minimax/pi`（董事长 2026-10-11 裁定的 P1 主力，复用既有 sk-cp Coding Plan 额度）。
- **不是反例**：反例是「合成测试不授权真实数据外发」。本包**没有**任何真实材料进入交付物或外发；
  交付面扫描 0 命中（§7）。

### HG-05 无假 MATCH

- **判定：PASS**
- 依据：`dd_v1_match_service.py:795`（RESTRICTED 与 MISSING/PARTIAL 的区分）、`:990`
  （「覆盖率够了」的结论必须建立在覆盖之上）；`dd_v1_qc_service.py` **不重算覆盖率**，
  每一维缺口**指名**（A2 独立裁定 17/17 PASS）。
- **不是反例**：反例是「9/31 仍 MATCH、用 Gold 数量偷偷判」。本包**不接触 Gold**，判定只用材料自身证据；
  实体/期间/文件集三类错误由 `dd_v1_blind_service.py` 的分类口径（TP/FP/FN/WRONG_ENTITY/WRONG_PERIOD/…）逐项判。

### HG-06 人工 + 精确交付

- **判定：PASS**
- 依据：`dd_v1_package_service.py:251`（`build_review_pack`）、`:120`（SHA256）、`:237`（`unselected` 未选用清单）、
  `:355`（未选用清单落盘）；`tools/dd_team_channel.py:339`（HG1 闸 = `assert_approval`，人工批准才组包）。
- **不是反例**：反例是「选 1 复制 12/74、原件被移动」。本包**只复制已人工审核集合**、逐件 hash 全对、
  **原件不动**（`dd_v1_package_service.py:8` 明示不碰材料源文件）、未选中件逐条进 `未选用清单.tsv`。

### HG-07 Reviewer 独立

- **判定：PASS**
- 依据：独立 Reviewer 裁定书（Executor 与 Reviewer 分离，均为独立会话）：
  A0 `A0-REVIEW-VERDICT.md` / A1 `A1-REVIEW-VERDICT-ROUND4.md` / A2 `A2-REVIEW-VERDICT-ROUND3.md` /
  A3 `A3-REVIEW-VERDICT-ROUND1.md`（13/13） / A4a `A4-REVIEW-VERDICT-ROUND2.md`（11/11） /
  脱敏包 `REVIEW-VERDICT-ROUND2.md`（8/8）。
  ★ **执行者自报不被采信**：门只认独立裁决 —— `gm/controller_gate_handoff.py::_verdict_is_pass`
  要求「verdict 文件为 PASS」或「`independent_gate_pass=true` / 产物齐备」，
  本次演练的执行者回执**没有** `artifact_sha` / `independent_gate_pass` ⇒ 自报被判**不可采信**（实测）。
- **不是反例**：反例是「Executor 自己写 PASS、CI 根本没启动」。本包的 PASS 全部来自**独立会话的裁定书 + 同一 SHA 上正反案例**。

### HG-08 真实 Windows 闭环

- **判定：BLOCKED（缺 4 项触发条件，缺一不可）**
- 缺：① 刘江 Windows 授权 ② 模型额度可用（dsh 2026-10-11 永久停用、cursor 额度耗尽）③ 真实材料授权
  ④ **42 题题面 / 逐题 CSV / 答案键资产**（本轮独立调研确证：**本机与仓内均未找到**，唯一来源是刘江侧资产）。
- **不是反例**：正因为没做，**不虚报** —— A4 整体因此**不记 5/6**，工程进度停在 **4/6**。

### HG-09 无人值守续棒

- **判定：PASS（真实闭环已跑通）**
- 依据：§3（演练全过程：真实调度 → 唯一 Executor → 真实产物 → 独立门 → **自动下一项**），
  活体证据 `a5-evidence/07-drill-real-loop-evidence.txt`。
- **不是反例**：反例是「心跳更新 / Cron 存在 / 留言送达即报成功」。本包的产物是
  **真实 commit + 真实测试退出码 + 门裁决 + `current_wp` 指针自动前进的前后读数**，
  且**全程无人工值守触发**（司仓只做了一次「接管指针 + 杀掉空转 worker」的现场处置，见 §3.3）。

---

## 2. A5-2 · 双进度条复算

> 口径：工程进度按 **0.3 口径**复算；效果进度 **0/100**；★ **分母 6 不得改**；★ 本包**不因前进效果分**。

### 2.1 工程进度（分母 = 6，冻结）

| A | 内容 | 独立 Reviewer PASS？ | 是否计入 |
|---|---|---|---|
| A0 | 基线 / 复用矩阵 / call-trace | ✔ `A0-REVIEW-VERDICT.md` | **计入** |
| A1 | 薄集成（入口 → 登记 → Manifest → 索引） | ✔ `A1-REVIEW-VERDICT-ROUND4.md` | **计入** |
| A2 | 召回 / 正文 / 判定层数据 | ✔ `A2-REVIEW-VERDICT-ROUND3.md`（17/17） | **计入** |
| A3 | 齐套 + 精确组包 | ✔ `A3-REVIEW-VERDICT-ROUND1.md`（13/13） | **计入** |
| A4 | 盲考 | A4a ✔ `A4-REVIEW-VERDICT-ROUND2.md`（11/11）；**A4b BLOCKED** | **不计入**（A4 整体未 PASS） |
| A5 | 本包（收口 + 演练 + Skills 复盘） | 收口包本身待独立复验 | **不计入**（本包不给自己记账） |

⇒ **工程进度 = 4/6 = 67%**（与名册 `engineering 4/6` 一致，未因本包前进）。

### 2.2 效果进度

**0 / 100**。理由：效果分只认「独立公平的真实考试证明能力」——真机盲考（HG-08）BLOCKED，无任何真实考试结果。
★ 本包**不产生任何效果分**（A5 是 research 包）。

### 2.3 双进度条分离声明

本轮新增的一切（接线修复、演练、脱敏包）**全部只影响工程侧**；
`baseline_failed_tests` 里那 **39 条存量治理线失败**仍原样记录在门基线里（不掩盖、不删），
**没有**为了让门变绿而放宽基线（见 §6.2 变更面与「未越权」自证）。

---

## 3. A5-3 · 续棒演练（★ G-A5-2）：真实闭环

### 3.1 演练是什么

演练工作包 `W-GM-CONTINUITY-DRILL-2026`（**不是业务工作**）：让 GM 在**没有人盯着**的情况下自己走完
「派工 → 唯一 Executor → 产物 → 独立门 → 自动下一项」，用**真实交付**证明 HG-09。

### 3.2 六个必答项（活体数据）

| 项 | 活体读数 | 出处 |
|---|---|---|
| 调度命令与 run/task id | task_id = `T-GM-CONTINUITY-DRILL-2026-WP-DRILL-1`；规格书落 `data/dispatch/T-GM-CONTINUITY-DRILL-2026-WP-DRILL-1.md` | `a5-evidence/07-...txt` ①② |
| 唯一 Executor 名 | `executor=minimax`、`harness=pi`、`provider=minimax-cn`、`transport=pi_print` | 同上 ② |
| 产物路径 + SHA256 | `gm/wiring_ledger.py`、`tests/test_wiring_ledger.py`（SHA256 见证据） | 同上 ③ |
| 门的退出码 | 独立门 `unittest` 门：`exit_code=1 → 修复后 0`；`unittest_ran_count` 由门现算 | 同上 ④ |
| 原记录 vs 现值 | `current_wp`：WP-DRILL-1 →（门 PASS 后）WP-DRILL-2；`run_log` 有 `GATE_PASSED` + `WP_ADVANCED`；**最终**：WP-DRILL-2 的门也 `action=COMPLETED`、`unittest_ran_count=4076`、`consumed=true` ⇒ `WP-DRILL-2=COMPLETED` ⇒ 演练包 `state=COMPLETED` | 同上 ⑤ |
| 过程链 | 派工风暴（多写者）事故 + 判别力修复 | 同上 ⑥ |

### 3.3 ★ 演练过程中发现并修掉的**真断线**（本包最有价值的产出）

演练不是走过场：第一次真实派工就把 GM 运行时的 **3 条断线**打了出来。

| # | 断线 | 现象（活体） | 根因 | 修法 |
|---|---|---|---|---|
| 1 | 控制器认不出自己的 worker | pi 明明活着（`ps` 显示 `pi`），控制器却每 ~47 秒 `WORKER_DEAD_REDISPATCH` ⇒ **attempt 3 分钟内涨到 7、同一目录并存 3 个 pi** ⇒ 多写者把工作区改红（执行者自报 14:45:06 改写测试文件 ⇒ 2 failures），已提交产物一度在工作区被裸删后恢复 | node 型执行器**改写进程标题** ⇒ `is_real_pi_print_task("pi")` 恒 False；且 `default_process_lister` 用 `ps -ax -o command=` ⇒ **列表里根本没有 pid** ⇒ 派工台账记的 `pid + pid_start_at` 无从使用 | ① 进程列表改 `ps -ax -o pid=,command=`；② 新增**单一来源** `dispatched_executor_alive()`（派工 pid + 启动时刻指纹，作用域限当前 work 包，PID 复用由指纹挡住）；观测层与控制器都调它 |
| 2 | 内核 worker 探针只认 cursor | 内核恒判「没有 worker」 | `_worker_needles()` 硬编码 `["cursor-agent"]`，而董事长 2026-10-11 裁定后 **P1 主力是 minimax/pi** ⇒ 与断线 1 同型：**配置换了主执行器，判定代码还停在旧执行器** | needle 探针失败时回落到断线 1 的同一来源（精确口径，不用 needle 猜 `pi`） |
| 3 | 门 FAIL 时报不出用例数 | 门 FAIL ⇒ `unittest_ran_count=None` ⇒ 无法判断「少跑了」还是「跑挂了」，更无法定位是哪一条失败 | 计数解析被关在 `if passed and gate_id == "unittest"` 内 | 解析移出 `if passed`（★ 集合差分判定与 `test_count_regressed` 的触发条件**一字不动** ⇒ PASS/FAIL 语义不变） |

★ 断线 3 的修复在演练现场**当场见效**：修复后第一次门 FAIL 就直接报出 `unittest_ran_count=4045`
（4029 存量 + 16 条演练新增用例），并**点名**是哪几条新增失败 —— 修复前这里是 `null`。

<!-- gm-fix-a5-closeout-doc: 演练第二段挖出的 7 条真断线 + §0/§11/§12 与活体对齐 -->
### 3.3.1 ★★ 演练**第二段**挖出的 7 条真断线（本包最有价值的产出 · 续）

第一段（§3.3 的 3 条）暴露的是「**看不见 worker**」；
第二段暴露的是「**看得见却推不动**」——链条在 3 分钟里连死 7 次，
每一条都有活体读数，全部已修，全部带判别力探针。

| # | 断线 | 活体现象 | 根因 | 修法（GM 侧，全部带 marker） |
|---|---|---|---|---|
| 4 | 观测层判活兜底**覆盖**了 `executor_alive` | 两条**既有合法**用例假红：黑匣子过期锚（`test_RED_f1_stale_black_box_anchor_silently_relabels_a_later_execution`）、重派链归因（`test_redispatch_chain_attributes_to_the_later_execution_and_leaves_a_trace`） | 兜底判活把 `executor_alive` 从 False 翻成 True ⇒ `delegation_status` 由 STOPPED 变 RUNNING ⇒ tick 走进「执行器还活着就别重派」⇒ attempt 不再漂移 ⇒ 两条用例的前提（attempt 已漂移）被打破 | 兜底结果落到**新字段** `executor_alive_by_dispatch_fingerprint`（可见性不丢）；`executor_alive` 的 cmdline 口径**一字不动**。复现方式：worktree 逐文件二分（旧提交两条全绿、换入即红、只换 `processes.py` 全绿） |
| 5 | ★ **任务书自相矛盾**（这是「自动下一项」那条线的**真断点**） | 第 10 次派工，执行者（codex）**当场指出冲突并拒写回执**：「任务书末尾明确禁止修改 `data/` 及 commit，与结果契约相冲突」⇒ 链条无产物可消费 ⇒ 客观门永远拿不到本次 attempt 的产物 ⇒ 门恒 FAIL/RETRYING ⇒ **接棒永不触发** | 同一张任务书里，`_SPEC_FOOTER` 写着「**不得改 `data/` 下任何文件**」「**不得 commit / push**」，而同一页的「结果契约」要求「**写入 `data/inbox/<task_id>/result.json`**」「再写入 `.../DONE`」——**自相矛盾** | 禁令**保留**（执行者不得篡改权威状态），只把「结果契约点名的两个回执文件」从禁令里挖出来并显式列白名单；「不得 commit/push」改为「**不要自己做**，产物提交由司仓运行时统一执行（`artifacts.auto_commit=true`）」，消除与 acceptance「已 commit」的第二处矛盾。配套把**断言旧文案**的用例升级成「断言**无矛盾**」（旧断言弱，新断言强） |
| 6 | 守护进程**读错了配置源** | 内核连续 12 条 `{"executor":"dsh"}`；attempt 10→15 一路空涨、每 ~47 秒一轮 | 守护进程用自己的 config（`config/gm_runtime_controller.json`）判断执行器可用性，而那个文件**根本没有 `dispatch` 段** ⇒ ① `executor_profiles` 为空 ⇒ `fallback_available` **恒假**（内核永远切不了执行器）；② `pick_executor` 没传 `profiles` ⇒ 董事长令**永久停用**的 `dsh` 不被排除 ⇒ 其余级别都在冷却时链尾永远落到 `dsh`（`dsh_bin` 为空）⇒ 派工秒死 | 链配置**只认一个源** —— 真实派工用的 `config/runtime_watchdog.json`（与 transport 侧完全同一份，禁止两份配置漂移）；`pick_executor` 补上 `profiles=`。修后内核 `executor` 从 `dsh` 变成 `minimax`，`fallback_available=True` |
| 7 | **「活着但不推进」没有系统化处置** | 实测有一次 pi 挂在模型 API 连接上 **33 分钟**（CPU 2.7s、日志 0 B、TCP ESTABLISHED）⇒ 控制器因「worker 活着」不重派、门也不重跑 ⇒ **链条被挂死的 worker 永久堵死** | 这条线断在**三处**：① 内核 `decide_kernel` **根本没有 stall 分支**（`if not i.worker_alive:` 之后直接落到「等 60s」）；② 守护进程一直在算 `seconds_since_progress` / `stall_threshold_s`，但 `control.last_progress_at` **永远是 null** ⇒ 采集了**没人用**；③ 没有任何地方**终止**挂死 worker ⇒ 只重派会变成**多写者** | 三处一起接：内核加 STALL 分支（`WORKER_STALLED_REDISPATCH`）；守护进程用 run_log 尾部算「距上次**工作产出**」并喂给内核；判挂死时**先按 pid + 启动时刻指纹精确终止再重派**（作用域限当前 work 包，PID 复用由指纹挡住，**绝不按命令行模糊匹配**）。★ 现场已生效：`actions.jsonl` 出现 `REDISPATCH_WORKER / kernel:redispatch:WORKER_STALLED_REDISPATCH` |
| 8 | 挂死时钟口径有**两个洞** | 若不修，第 7 条会**误杀正在干活的 worker** | ① `DISPATCHED` 事件按 transport **去重** ⇒ 同一任务重派时**不产生**新事件 ⇒ 只看产出事件会把「刚出发的 worker」判成挂了 2 小时；② 产出事件**不带作用域** ⇒ 别的任务的产出会掩盖本任务的挂死 | 时钟起点 = **max(上次产出, 本轮 attempt 启动时刻)**（本轮起点以派工台账为准）；产出事件按 `work_id` / `wp_id` **过滤**。修后实测：时钟 = min(2275s, 84s) = **84s** ⇒ 不判挂死 ✅ |
| 9 | **僵尸进程被当成活着** | 对着尸体补 SIGKILL；僵尸 worker 还会堵死链条 | 僵尸在 `ps` 里**依然有条目** ⇒ 启动时刻指纹照样取得到 ⇒ 「指纹取不到 = 已死」这条判据把僵尸判成活着（判别力探针当场抓出：SIGTERM 后 `poll() == -15`，函数却报 `still_alive`） | 新增 `pid_is_gone()`：**指纹取不到** 或 **进程状态是 Z** ⇒ 已死。判活与终止**同源**用这一条口径 |
| 10 | 开机时刻靠 **fork `sysctl`** | 满载时（实测 load 11.8/10 核）10s 超时 ⇒ 返回 None ⇒ ① 客观门多一条假红；② **更危险**：`rebooted_within(None, …)` 把「取不到」一律按「发生了重启」处理 ⇒ 一次超时就被判成机器重启 | `read_boottime_seconds()` 每次调用都 fork 一个子进程 | Darwin 走 ctypes 的 `sysctlbyname("kern.boottime")` **直读内核变量** —— 与 CLI **同一来源**，但零 fork、零超时、耗时微秒级；CLI 保留为兜底。★ 实测**逐位相同**（delta=0.000000000，连采 3 次值恒定不漂移）；**不缓存**（缓存会让同进程内跨越一次重启也测不出来） |

★ **本段的核心收获**：演练的前 3 条断线是「看不见 worker」，
后 7 条是「**看得见却推不动**」。后者更隐蔽 —— 它们不会报错，
只会让链条**静静地**不往前���；**没有真实派工 + 真实独立门 + 真实接棒**，
根本发现不了。

<!-- gm-fix-a5-closeout-drill3: 演练第三段的断线 11–14 + §0/§6.2/§11/§12 与活体读数对齐 -->
### 3.3.2 ★★★ 演练**第三段**挖出的第 8 条真断线：证据的「人类描述层」与「结构化 type 层」没接上

第一段是「看不见 worker」，第二段是「看得见却推不动」，
**第三段是「跑完了却判它没跑完」**——链条在最后一米卡死：
回执写出来了、产物在库里、测试全过，**判定器却判它 FAIL**，
于是客观门永不被派出、接棒再也不会发生。

★ 名册口径（活体统计）：有 `evidence_required` 的 WP **128** 个，
其中 **63** 个含至少一条「不在六类白名单里」的自由描述；
自由描述**去重 88 词**；六类白名单条目 **181** 条。

| # | 断线 | 活体现象 | 根因 | 修法（GM 侧，全部带 marker） |
|---|---|---|---|---|
| 11 | **任务书把「人类描述」摆成了「type 词表」**，且**从不列出白名单** | WP-DRILL-2 回执 `evidence` 的 type = `['test_result','diff','commit']` ⇒ judge 判 `verdict=FAIL, reasons=["evidence 含未知类型: ['commit']（白名单外一律 FAIL）"]` ⇒ 名册 `WP-DRILL-2` 卡在 `RETRYING` ⇒ 客观门**一次都没被派出** ⇒ 接棒**只能发生一次就卡死** | 名册 `evidence_required` 是**人类自由描述**（「commit」「external_result」「unittest 输出」…），回执 `evidence[].type` 是**结构化机器枚举**（`gm.judge.EVIDENCE_TYPES` **六类**）——**两个不同的层**，旧实现把前者当后者校验；而任务书只说「evidence（judge 白名单 type + detail）」，**从不列出是哪六个** ⇒ 执行者只能照抄数组里的自由描述 | 任务书把两层**分开摆**：`## evidence_required`（人话：要交什么）+ `## evidence_types`（枚举：type 字段填什么，由自由描述**派生**）；结果契约里把六类白名单**写出来**（由 `EVIDENCE_TYPES` 生成，不写死、不另造一份） |
| 12 | judge **不认合法语义的自由词** | 同上——`commit` 明明是可核验的 git 事实，却因「不在六类里」被判死 | 严格 Gate（未知类型一律 FAIL）本身没错，错在**词表断层**：白名单只有六类，而名册里 88 条自由描述词**几乎一条都落不进白名单** | 加**有限、显式、可审计**的桥：`commit→log`、`external_result→api_response` 等（别名表 + 有序规则表），**覆盖 88 词中的 87 词**；映射不上**照旧 FAIL**（**不设兜底**——兜底等于把严格 Gate 拆了）；`self_report` / `agent_claim` **永不映射**；`EVIDENCE_TYPES` **仍是六类**；每次映射记进 `verdict.evidence_type_normalization`（可审计可回溯） |
| 13 | judge 判死的理由**不回灌下一次任务书** | 同一个非法 type **一错再错**：执行者下一轮拿到的任务书与上一轮**一模一样**，看不到自己错在哪 ⇒ 无限重试 | 只有**客观门**失败（`gate_failure` 文件）会回灌；judge 的 FAIL 理由只躺在名册 `blocked_reason` 里，执行者**读不到** | 派工单带上 `prior_failure_reasons`（取 WP 的 `blocked_reason`），任务书渲染成「## 上一轮判定失败原因（判定器原话，务必逐条修正后重交）」 |
| 14 | ledger 的 unknown 统计与 judge **不同口径** | 报表会把 judge 已认可的 type（如 `commit→log`）报成「未知类型」 | ledger 自己判「在不在 `EVIDENCE_TYPES` 里」，judge 判「归一化后认不认得」⇒ **两套口径** ⇒ 报表在说假话 | ledger 改走 judge 的**同一个** `normalize_evidence_type`（词表单一来源） |

★ **这一段是整包最有价值的产出**：前两段挖的都是「运行时怎么跑」，
这一段挖的是**「判定器怎么认」**——
判据本身没错（未知类型就该 FAIL），错的是**系统把执行者逼到必然 FAIL 的路上**：
任务书给的是人话，判定器认的是枚举，**中间那根线没人接**。
⇒ 与断线 5（任务书自相矛盾）同源：**契约要自洽，不自洽的契约会把执行者逼死**。

★ **修完当场的活体读数（不是推断）**
- 任务书重渲染后由 minimax(pi) 执行，新回执 `evidence` 的 type =
  `['test_result','diff','log','log','log']` —— **六类之内，无 `commit`**；
- judge **PASS** ⇒ 客观门派出（`gate_pending` 有 `spawn_pid`）
  ⇒ 门裁决 `action=COMPLETED`、`unittest_ran_count=4076`、`consumed=true`；
- 名册 `WP-DRILL-2=COMPLETED` ⇒ **演练包整体 COMPLETED**；
  产物由运行时自动提交（`WP_ARTIFACTS_COMMITTED`，sha `851c8e7c`）。
★ 断线 11（任务书写出白名单）**单独就足以让这条线转绿**（本轮门裁决就是它促成的）；
  断线 12/13/14 是「即使执行者仍惯性照抄」也**不至于再卡死**的三层兜底 + 口径统一。

### 3.4 A5-5 · 会话结束后下一 WP 仍有有效产物

- 判据：下一 WP（WP-DRILL-2）由**接棒机制自动**推进后**真实产出**产物（不是心跳更新）。
- 活体证据：`run_log.jsonl` 的 `GATE_PASSED` / `WP_ADVANCED` 事件 + `current_wp` 前后读数
  + WP-DRILL-2 的真实派工记录与产物 SHA256（`a5-evidence/07-...txt` ⑤）。
- ★ 判「有效产物」的依据：**文件存在 + SHA256 可复算 + 自带测试退出码 0**，
  心跳/日志行**不算**产物。

---

## 4. A5-4 · Lease / 单主

### 4.1 运行时 lease（唯一有效 owner）

- 持证文件：`/Users/mac/cangjie-gm/data/gm_runtime_lease.json`
- 校验命令：`cat data/gm_runtime_lease.json`；实测读数 `holder=controller-44433`、`generation=35`、`ttl_s=180`、心跳每轮刷新
- 唯一性：名册 `active_parent=true` 的条目**恰好 1 条**（演练期间由演练包持有，演练后**交还**原条目并复验）

### 4.2 无第二调度器（进程证据）

- 派工入口只有三个，**都挂在同一个 controller 之下**：
  `gm/runtime_watchdog/transport.py::dispatch_order` / `dispatch_order_with_fallback`（由 watchdog tick 调用）
  与 `gm/gm_dispatch.py`（司仓手工派工事实源，用于改码门禁豁免登记）。
- 活体：`launchctl list | grep com.gm` ⇒ 只有 `com.gm.runtime-controller` 在跑；
  `com.gm.runtime-director` 是**死配置**（指向不存在的 `/Users/mac/.gm-rt/`，未加载）⇒ **无双主风险**（待清理，已登记）。

### 4.3 worktree 单写者 lease 生效

- 机制：`gm/worktree_ownership.py`（`claim()` / `release` / `is_owner_live()`）；
  执行者自报：「按 `gm/worktree_ownership.py` 黑名单**未**做任何 stash/reset/clean/checkout--/restore」，
  复核全在 `/tmp` 隔离副本内完成 ⇒ 单写者纪律**被执行者遵守**。
- ⚠️ 反例已发生并已记录：风暴期间多写者曾**裸删**已提交产物（后恢复）⇒ 见 §3.3 断线 1。

---

## 5. A5-2 附 · 本包对「接线」的总账口径（三层，不可混）

> ★ 这条是本包修正司仓此前审计口径的地方（监工第 70 轮独立核实后一致）。
> 旧表述「薄入口 → 审核组包没接」是**探针写死 A2 树**造成的**历史发现**，A3·G-A3-6 已修复；master 仍复现是**合分支未做**。

| 层 | 结论 | 依据 |
|---|---|---|
| 能力层 | `build_review_pack` **存在且可用** | `dd_v1_package_service.py:251` |
| 接线层 | **A2 树断 → A3 树通**（调用 223 次，四件套可生成） | `tools/dd_team_channel.py:279-280`；call-trace |
| 交付层 | **master 仍断**（PR #80 未合并）⇒ 合分支即可闭合 | `origin/spec/...` = `453957e` 只含 A3 |

★ 因此「内部很多线没接好」的准确答复是：**FOS 内部 DD-V1 的服务都是真实接通的；
当前唯一的接线问题在 master 落后于 A3/A4 交付面**（合分支闭合），**不是能力缺口**。

---

## 6. A5-6 · 零回归 / 不越权

### 6.1 本包改动面（FOS 侧）

| 路径 | 性质 |
|---|---|
| `docs/dd-v1-fos71/wp05-real-integration/A5-CLOSEOUT.md` | 新建（本文件） |
| `docs/dd-v1-fos71/wp05-real-integration/a5-evidence/**` | 新建（证据，`.txt`） |

⇒ 白名单外改动 **0**；**未改任何 FOS 产品代码 / 测试**；**未改 A0–A4 的裁定书与证据**；
**未 commit / 未 push / 未 merge / 未建 PR**（按任务书第 4 段第 8 条：司仓统一 push + 开 PR）。

### 6.2 ★ GM 侧变更面（**披露式**）

本包期间司仓在 **GM 仓**做了一批**接线修复**（波总 2026-10-22「把接线全部接好」授权，**不属于 A5 包白名单**，
故在此**逐项披露**）：

| commit | 内容 |
|---|---|
| `92de0ab` | 客观门可观测性（FAIL 也报 `unittest_ran_count`）、客观门基线升级为**集合差分**（39 条名单 + 1 条 flaky）、进程列表补 pid、执行器判活**单一来源** `dispatched_executor_alive()`、内核 worker 探针回落、两处治理断言去活状态化 |
| `15413b3` | 断线 7（观测层判活不再被指纹兜底覆盖）、断线 8（任务书固定要求去矛盾） |
| `e47f587` | 断线 9（守护进程执行器链配置源统一到 `config/runtime_watchdog.json`） |
| `772e6e2` | 断线 8 的配套断言升级（从「断言旧文案」→「断言**无矛盾**」） |
| `60e6e81` | 断线 10（「活着但不推进」：检测 → 判定 → 精确终止 → 重派） |
| `bca5658` | 断线 11/12（挂死时钟口径修正、僵尸=已死、开机时刻改 ctypes 直读） |
| `19bde40` | 断线 13（证据类型桥：**#13a** 任务书两层分开 + **#13b** judge 桥 + **#13c** FAIL 原因回灌 + **#13d** ledger 同口径）；含 `tests/test_evidence_type_bridge.py` 19 条回归 |
| `851c8e7` | WP-DRILL-2 **执行者产物**（`scripts/gm_drill_gate.py` + `tests/test_drill_gate.py`），由运行时在门 PASS 后**自动提交** |

★ 上述提交**均不含** `data/work_items.json`（名册司仓单写，不提交）。
★ **未放宽任何验收门**：客观门基线是**收紧**（集合差分 + 39 条名单），不是放宽；
  断线 13 的「桥」只改 type 的**归类**（`self_report` / `agent_claim` 永不映射、映射不上照旧 FAIL、
  `EVIDENCE_TYPES` 仍是六类、detail 与 tests_run 判定一字未动）。
★ 全量 unittest 复跑：`Ran 4076`，**零新增失败**（基线 39 条中命中 38 条，1 条本轮转绿）。

---

## 7. A5-7 · 敏感（真实客户名 / 材料库代号）

- 交付面（FOS 仓本包交付件 + GM 侧回执 / 任务书）用两套规则扫描：**真实名子串 + 代号词边界**。
- 实测：**0 命中**（证据 `a5-evidence/08-sensitive-scan.txt`，含扫描器自证：扫描器自身 0 命中）。
- ★ 材料库代号推导**排除** `~/dd-v1-realbase/work/`（工作区，`work` 是通用英文词，会造成假阳性）。
- ★ 本文档与全部证据**不出现**任何真实客户名 / 材料库代号字面量（只出现计数与口径）。

---

## 8. A5-8 · Skills 复盘及审计

> 口径：只读计数（任务书白名单：GM 仓只读 `~/skills*`，**只读取数所需**）；数字**给得出处**（命令 + 输出）。

| 项 | 数字 | 出处（命令） |
|---|---|---|
| 可入库条目数 | **446** | `python3.11 tools/skill_health.py catalog --root .` → `skills[]` 长度 |
| 仓内 `SKILL.md` 文件数 | **554** | `find . -name SKILL.md -not -path '*/node_modules/*' \| wc -l`（含嵌套引用副本，故 > 446） |
| 带 issues 的条目 | **113**（25.3%） | 同 catalog 输出 `issues[]` 非空计数 |
| issue 分布 | `machine_specific_path_review` 84 / `weak_description_under_35_chars` 17 / `invalid_name_or_directory` 13 / `verbose_description_over_320_chars` 3 / `missing_frontmatter` 1 / `invalid_description` 1 | 同上，按 issue 聚合 |
| 描述长度 | min 217 / max 159244 / 平均 6916 字符 | 同上 `chars` 聚合 |
| 跨端加载证据 | A/B 激活实验 **3 组**（agents = `codex`+`hermes`；`hermes` 单独；chat 集），arms = A/B | `~/skills-wt-wp1/docs/status/evidence/wp2b-activation.json`、`wp2f-activation-chat.json`、`wp2i-activation-hybrid.json` |

★ **审计结论**：条目数与健康度分布均可复算；**最大单项缺陷是「机器专属路径」84 条**（占比 18.8%），
是跨端迁移的首要摩擦点；`invalid_name_or_directory` 13 条属**命名规范**问题，不影响加载。
★ 激活实验的自述口径已在证据里写明：`found/loaded observed; executed/accepted NOT_MEASURED`
⇒ **不得**把「found/loaded」说成「执行通过」。

---

## 9. A5-9 · 证据冻结 + 出厂三项自检

| 自检 | 结果 | 出处 |
|---|---|---|
| ① SHA256 清单**全 OK** | `shasum -a 256 -c` → 全部 OK（**4 条**，脚本外独立复核 rc=0） | `a5-evidence/SHA256SUMS-a5-evidence.txt` + 自检输出 `09-evidence-freeze-selfcheck.txt` |
<!-- gm-fix-a5-closeout-selfcheck: §3.2 最终读数 + §9 自检器自引用缺陷的诚实披露 -->
| ①-补 ★ **本包自检器原有一处自引用缺陷（已修）** | 采集器原顺序「算清单 → 校验 → 写 09 → 写 10」，清单把**随后会被改写**的 `09`/`10` 也算进去 ⇒ 当场 `shasum -c` 复核 **2 条 FAILED**，而 09 正文却写着 `SELF_CHECK=PASS` ⇒ **「清单全 OK」这句话本身是假的** | 已修：① `10` 先写；② 清单**排除** `09`（自检输出）与清单自己（消除自引用）；③ 写完**再跑一次终态校验**，不自洽就**非零退出**。已当场重跑并由脚本外独立复核（rc=0） |
| ② 真实名**零命中** | 交付面 0 命中（含扫描器自身） | `a5-evidence/08-sensitive-scan.txt` |
| ③ **provenance 当场打印** | 谁 / 什么时间 / 用什么命令 / 拿到什么结果 | `a5-evidence/10-provenance.txt` |

---

## 10. A5-10 · A4 遗留必查项复核

A4a 独立 Reviewer ROUND2 之后司仓改了 3 处**纯文档**（附录段章号、交叉引用、阅读指引范围）—— 本包逐项复核：

| # | 修正 | 复核方法 | 结果 |
|---|---|---|---|
| 1 | 附录段数字章号 → `附录 A/B/C`（不与正文 §0–§9 撞车） | `grep -n "^## " A4-BLIND-EXAM.md` 枚举全部章号 | ✔ 正文 0–§9 各一次；附录 A/B/C/D 各一次，**无重号** |
| 2 | 「坑与边界」交叉引用 → §8（原指 §6，而 §6 是「CLI 新增开关一览」） | 读附录 C 行 | ✔ 已指 **§8** 且注明 §6 是什么 |
| 3 | 阅读指引范围 → §0–§9（原写 §0–§8，正文实到 §9） | 读阅读指引 + 附录 B 指引行 | ✔ 两处均为 **§0–§9** |
| 4 | 勘误表补全 MINOR-4/5/6/7/8/OBS-1 | `grep -oE "MINOR-[0-9]+|OBS-[0-9]+"` | ✔ 实测 MINOR-1…8 + OBS-1 全在 |

---

## 11. ★ 诚实登记（未完成 / 未验证 / 欠账）

1. **A4b 真机盲考 BLOCKED**（HG-08）：缺 4 项前置，缺一不可（刘江 Windows 授权 / 模型额度 / 真实材料授权 / **42 题资产**）。
   ⇒ **A4 整体不记 5/6**，工程进度停在 **4/6 = 67%**；效果进度 **0/100**。
2. **master 未合入 A3/A4**（PR #80 未合并）：master 上「入口只出 2 文件」是**合分支未做**，不是接线漏做。
3. ~~**「活着但不推进」的执行器没有自动处置**~~ —— **本轮已实现并接上**（见 §3.3.1 断线 7/8/9）：
   内核 STALL 分支 + 守护进程算「距上次工作产出」+ 判挂死时**先精确终止再重派**；
   判别力探针 11/11 GREEN，且**现场已生效**（`actions.jsonl` 出现
   `kernel:redispatch:WORKER_STALLED_REDISPATCH`）。★ 阈值仍取 config 的
   `stall_threshold_s`（默认 600s）：实测成功跑完一次 3–5 分钟、实测挂死 33 分钟
   ⇒ 10 分钟是这两者之间的**有据取值**。
4. **存量 39 条治理线失败**仍在客观门基线名单里（不掩盖、不删）⇒ 建议另立工作包清理，
   否则基线名单越滚越大、门越来越松。
5. **名册里 14 条既有 work package 校验不过**（`evidence` 缺 list / `next_action` 非字符串）⇒
   只在 orchestrator 走到那批条目时才抛 `OrchestratorValidationError`；**本轮未擅自改**（既存欠账）。
6. `com.gm.runtime-director` 是**死配置**（指向不存在的目录、未加载）⇒ 无双主风险，但待清理。
7. 本轮所有**本地提交**均**未 push**（GM 仓分支领先 origin 214 提交；FOS 仓 A5 分支未提交）。
8. ★★ **受限豁免（必须披露）**：为让「自动下一项」这条线**真的发生**，
   司仓在演练期间**临时把名册的 `active_parent` 熔断指针**从 `W-CO-VNEXT-2026`
   移到演练包 `W-GM-CONTINUITY-DRILL-2026`。
   - **理由**：daemon 的接棒入口 `detect_pending_writeback` 只认 `active_parent`；
     不接管则「门 PASS → 自动推进下一 WP」**无从发生**。
   - **边界**：可逆（演练后**已交还**并复验全表**恰好一个** `active_parent=true`）；
     **未触碰任何熔断闸 / 人工批准闸 / 客观门基线**；名册由司仓单写且**不进 Git**。
   - **交还时点**：演练闭环达成（门 PASS → 自动推进 → 下一 WP 真实派出）之后。
   - ★ **交还的活体读数**：演练包两个 WP 均 COMPLETED 后执行交还 ⇒ 全表
     `active_parent=true` 的持有者**恰好 1 个** = `W-CO-VNEXT-2026`（唯一性复验通过）；
     交还后守护进程接管回 `W-CO-VNEXT-2026`（`RUNTIME_TICK wp_id=WP-VN-02`）。

---

## 12. 欠账登记（下一轮该接的线）

| # | 欠账 | 影响 | 建议动作 |
|---|---|---|---|
| 1 | ~~**stall → 杀 → 重派**~~ | **本轮已接上**（§3.3.1 断线 7/8/9，探针 11/11，现场生效） | ——（已销账） |
| 2 | `daemon._worker_needles()` 只认 cursor | 已用指纹回落覆盖，但 needle 清单仍是**维护性负债** | 从 `executor_profiles` **自动推导** harness 名单，禁人维护清单 |
| 3 | 客观门 FAIL 时的**失败用例归档** | 门已能报计数与失败名，但未归档成「每次门裁决的失败集历史」 | 门裁决落盘时附失败集，供基线漂移告警 |
| 4 | 存量 39 条治理线失败 | 基线名单只增不减 | 另立工作包逐条清理 |
| 5 | 名册 14 条既有条目 schema 不全 | orchestrator 走到即抛 | 补 `evidence` / `next_action` |
| 6 | `backend/.venv` 未被 gitignore（脱敏包 MINOR-4） | push 时 `git add -A` 会误纳 | 另立工作包；本包约束：**只 add 白名单** |
| 7 | **守护进程重启要等 180s lease TTL** | 每次改代码重载守护进程 ⇒ 链条**空转 3 分钟**（实测：16:16:32 旧 lease 过期，16:19:51 新控制器才拿到 lease 并动作） | lease TTL 与「重载要快」互相拉扯；可考虑：新 holder 接管时**主动作废**旧 lease（带 generation 校验，防双主） |
| 8 | 接线总账的 **FOS trace 源指向 A1 旧快照** | `gm/wiring_ledger.py` 的 `fos_trace` 读的是 A1 期的 `trace-summary.json`（A1 早于 A3）⇒ 报「合同链缺 package_service」的**假缺口** | 让它读**最新**的合同链 trace 证据（A5 的 `03-fos-contract-chain-trace.txt` 或 A4 的 trace）；★ 本轮**未改**（那是执行者的交付物，演练期间不动，待独立验收后另立条目） |
| 9 | **执行器链有第二个真相源** | `gm/executor_fallback.py::EXECUTOR_CHAIN` 是**硬编码链**（含 `MiniMax-M3.1-Flash-Preview` / `cursor:grok-4.7` / `cursor:composer-2.5`），与 `config/runtime_watchdog.json` 的 `executor_priority`（`MiniMax-M2` / `cursor:auto`）**不一致**；断线 9 只统一了守护进程的**可用性视角**，**派工实际走的链**仍是硬编码那份 ⇒ 两份配置继续漂移 | 把链也收成**单一来源**：`EXECUTOR_CHAIN` 由 `executor_priority` + `executor_profiles` 派生，仓内只留一份定义；★ 本轮**未改**（属运行时链语义变更，须独立 Reviewer 过） |
| 10 | 守护进程重载的 180s 空转 | 欠账 7 的**已验证绕行法**：停旧进程 → 把 lease `heartbeat_at` 置为已过期（**保留 holder 与 generation**，单调性不破）→ `bootstrap` ⇒ 新 holder 立即接管，实测 generation 40→41、**零空转**（旧法要空转 3 分钟） | 把「作废旧 lease 心跳」做成脚本并加 generation fencing 校验，正式取代 TTL 等待 |

---

## 13. 出厂自检（本包）

- ① SHA256 清单全 OK：见 §9
- ② 真实名 / 代号零命中：见 §7
- ③ provenance 当场打印：见 §9
- ④ 改动面逐件对账（白名单外 0）：见 §6
- ⑤ 复跑门禁与前后 SHA256 一致：本包**未改 FOS 产品代码** ⇒ FOS 仓无需重跑全量；
  GM 仓的改动另有独立提交 + 判别力探针（§3.3）

---

*本文件由司仓（GM）生成；A5 包是 research 收口包，不产生效果分，不自证 PASS。*
