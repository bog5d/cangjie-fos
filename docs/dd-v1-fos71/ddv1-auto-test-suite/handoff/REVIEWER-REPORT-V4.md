# 独立复核报告 V4（Reviewer 第 4 轮 · 复验第 3 轮 findings 的闭环）

> **复核对象**：`cangjie-fos` 分支 `feat/dd-v1-auto-test-harness-20261030`，HEAD=`934ec95`
> **复核区间**：`cb03b51`（第 3 轮 findings 的修复）→ `934ec95`（证据重生成 + 第 3 轮报告入库）
> **复核人**：独立 Reviewer（未参与施工；**本轮未修改仓库任何文件**，实验产物全在 `/tmp/ddv1-review4/`）
> **环境口径**：`ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897`；Python 一律 `backend/.venv/bin/python`；数据面 `/tmp/ddv1-review4/plane*`（**未碰**施工者的 `~/.cangjie-ddv1-exams`）
> ★ **代理口径说明（任务书要求写明）**：本机 `all_proxy` 是 SOCKS 而 `httpx` 未装 `socksio` ⇒ 不改写会有 **6 条假红**。本轮**全程**按任务书口径把 `ALL_PROXY`/`all_proxy` 都改写成 `http://127.0.0.1:7897`，我的全量 pytest **exit=0 / 2174 total / 0 failed / 6 skipped / 2168 passed**，与入库 `g1_pytest.json` **逐项相同** ⇒ 无假红。
> ★ **交叉核对口径**：Skills 仓以 **d04632a** 为准（并检查了 ff62b42 内容是否被破坏）。

---

## 复核结论：**CONDITIONAL**

**为什么不是 PASS（两条硬理由）**

1. **C7 实现比口径松，且已发作在交付物里（我自己的新 finding，MINOR-1）**：门禁 G6 的实现把 `verdict ∈ {PASS, CONDITIONAL}` 都判 **PASS**（`tools/dd_v1_exam_suite.py:794-796`）。**这不是"故意设计"**——冻结门禁规格里 G6 的 title 明写「独立 Reviewer **PASS**」（`backend/config/dd_v1_delivery_gate.v1.json` → `gates.G6.title`），而交接包 README 第 88 行自己写「**第 3 轮＝CONDITIONAL** … ⇒ **现在不算 PASS**」。⇒ **同一套交付包里，机器门禁报告说「G6 PASS」、人读文档说「G6 不算 PASS」，两份产物互相打架**，且 `.audit/gate-runs/门禁报告.json` 里那行 `G6 PASS reviewer verdict=CONDITIONAL` 正是施工者**本轮亲手生成并入库**的产物。
   - **降为 MINOR 而非 MAJOR 的两个客观理由**（不替施工者开脱，也不夸大）：① G6 **不在 `key_gates`**（`key_gates = [G1,G2,G3,G4,G5,G8]`）⇒ 即使把它改成 FAIL，**整体门禁 status 也不会变** ⇒ 这是"逐门读数/表述"层的问题，不是"放行"层的问题；② reason 串 `reviewer verdict=CONDITIONAL` **如实披露**了 verdict，**没有隐瞒**。
   - **触发条件**：任何一轮复核给出 CONDITIONAL 且 MAJOR 未闭环时。**我实测**：第 3 轮报告入库后重跑门禁，`G6` 仍判 PASS。
   - **证据**：`tools/dd_v1_exam_suite.py:794-796`；`.audit/gate-runs/门禁报告.json` → `gates.G6 = {status: "PASS", reason: "reviewer verdict=CONDITIONAL"}`；`docs/dd-v1-fos71/ddv1-auto-test-suite/handoff/README.md:88`。
   - **建议修法（二选一，必须留痕）**：① 把 G6 收紧为 `verdict == "PASS"` 才 PASS（**加严**，符合 A3/A4/A5 方向）；② 或**改规格 title**（「独立 Reviewer 报告已出（PASS/CONDITIONAL）」）＋ 在门禁报告里加机器可读字段 `reviewer_verdict`，并在 `key_gates` 里明确 G6 的角色。**不改口径也不改实现 ⇒ 交付包里两份产物继续互相矛盾。**

2. **C5「AI 成绩存在方差」这个最终表述：结论方向站得住，但它的证据没有被归档（我的新 finding，MINOR-2）**：施工者的第三次"再更正"（干净树 commit `0b1ec84`、`git_dirty=false` 打出 **77.5**）**本身是真的**——我在 `/tmp/regen_evidence.log` 里逐字读到了那一次的现场输出（`run_id=20261030T143443Z`、`git_sha=0b1ec84…`、`execution_path=REAL_MODEL`、`actual_model=deepseek-flash`、`total_score=77.5`），同一批次里 RULE_ONLY/pi/codex 都是 96.67。**但**：这一次运行**没有留下任何可交付的运行清单**——仓内 19 份 `.audit/**/运行清单.json` 无一份 `git_sha=0b1ec84`；我在 `/tmp` 全盘扫了 **112 份** `运行清单.json`，`sha=0b1ec84` 的只有 1 份（`/tmp/ddv1-fixcheck-out/C`，**`git_dirty=true`**、分数 100.0），**77.5 那次一行都没有**。⇒ **BLOCKED-8 这条要交给业务方的结论，其唯一支撑是一份自己写的汇总 JSON（`.audit/variance/dsh-variance-v3.json`）＋ 一份仓外 stdout 日志**，形态上与第 3 轮被抓掉的那三次「脏树 77.5」**同类**（区别只在于这次**确实是**干净树）。按项目自己的规则（"证据必须逐份自证干净"），**这一条现在还不满足"可作为交付证据"的标准**。

**为什么不是 FAIL**：第 3 轮的两条 MAJOR **真闭环**（我复跑第 3 轮原探针 + 自造反例 + 自己重跑三场考试全部复现）；门禁阈值**逐位未动**（我自己 flatten 比对 7 个版本，数值差异 = 0）；A5/A6 **没有越权**（`gates` 段相对首版逐字相同）；MINOR-1..5 / NIT-1/2 **九条全部可复验地闭环**；我独立复跑真实 dsh/pi/codex 三家全部通过并**各自用官方来源核实了身份**；RULE_ONLY / AGENT_REQUIRED / AUTO 三模式语义逐条实测正确；假绿反例（含第 3 轮那一条被漏掉的 fg5）**全部被拦**；覆盖率我**自己从 JUnit XML 重建索引重算**逐位一致；Skills 升级 5 个 + 候选 1 个，**内容属实、候选仍是候选、本轮未混入客户材料/密钥**。

**R10（Windows 真机）＝ NOT_VERIFIED**（本机 macOS darwin 25.6.0 / arm64；按任务书要求，**不替刘江判 PASS**）。

---

## 逐项结论表（R1—R10 ＋ C1—C8）

| # | 结论 | 我跑的命令（摘要） | 实际读数 |
|---|---|---|---|
| **R1** DSH 真实调用 | **PASS** | `DDV1_EXAM_PLANE=/tmp/ddv1-review4/plane-var$i tools/dd_v1_exam_suite.py run --exam A --run-mode AGENT_REQUIRED --agent dsh --allow-local-dsh`（×5） | 5/5 **exit=0**；`total_score=96.67`（5/5 恒定）；`execution_path=REAL_MODEL`；`actual_model=deepseek-flash`；`provider=deepseek-official`；`source=DSH_PROFILE_CONFIG`；`verified=true`；`git_sha=934ec95c`、`git_dirty=false`；`score_split.score_name=AI_SYSTEM_SCORE` |
| **R2** Codex+Pi 真实调用 | **PASS** | 同上，`--agent pi` / `--agent codex --codex-persist-session` | **pi**：exit=0、96.67、`MiniMax-M3.1-Flash-Preview`、`source=AGENT_EVENT`、`binding={"event":"message_end"}`；**codex**：exit=0、96.67、`gpt-5.6-sol`、`source=CODEX_EXECUTION_RECORD`、`thread_id=01a18d59-0ec2-7f32-8915-9125c8f1bfd9`、`binding.rollout_cwd` 与我自读 rollout 的 `cwd` **逐字相同** |
| **R3** 模型身份可信 | **PASS** | ① `dsh --profile headless --dump-config` ② `pi -p --provider minimax-cn --no-session --no-tools --mode json` ③ 自读 codex rollout jsonl | ① `agent-default-model → provider: deepseek-official / model: deepseek-flash`；② `message_end → model=MiniMax-M3.1-Flash-Preview / provider=minimax-cn`；③ `session_meta{provider:openai, cwd:…fos71-agent-bkbxbye2}` + `turn_context{model: gpt-5.6-sol, cwd:…fos71-agent-bkbxbye2}` ⇒ **三个来源各走各的官方通道**，且 codex 的 cwd 绑定**硬**（不符即 fail-closed 记 UNKNOWN） |
| **R4** RULE_ONLY 独立计分 | **PASS** | `--run-mode RULE_ONLY`（×3） | 3/3 **exit=0**、**96.67**；`score_name=RULE_BASELINE_SCORE`、`ai_system_score=null`、`ai_system_score_status=NOT_SCORED`、`rule_baseline_score=96.67`、`model_identity_acceptable=false` ⇒ **规则分与 AI 分严格分列** |
| **R5** AGENT_REQUIRED 严格 | **PASS** | ① 不给 `--agent`；② `env PATH=（无 dsh）… --agent dsh` | ① **exit=1**、stderr「`不允许在 AGENT_REQUIRED 下静默跑成规则考试`」、**输出目录未创建**（未开考）；② **exit=1**、`status=FAIL`、`execution_path=FAILED`、`score_name/ai_system_score/rule_baseline_score` **全为 null**（**不是 0**） |
| **R6** AUTO 降级标注 | **PASS** | `env PATH=（无 dsh）… --run-mode AUTO --agent dsh` | `requested_mode=**AUTO**` 与 `execution_path=**DEGRADED**` **分列**；`score_name=RULE_BASELINE_SCORE`、`ai_system_score=null`、`ai_system_score_status=NOT_SCORED` ⇒ **降级结果未被记为 AI 成绩**；`results.status=LOW_CONFIDENCE` |
| **R7** 假绿反例被拦截 | **PASS** | ① `pytest tests/test_dd_v1_false_green_regressions.py test_dd_v1_safety_gate_spec_alignment.py test_dd_v1_evidence_selfproof.py test_dd_v1_gate_binding_determinism.py`；② 自造 fg5（1×REAL_MODEL + 1×MODEL_ID_UNKNOWN）喂 `gate --runs` | ① **54 项全绿**；② **fg5（第 3 轮此场景 G8 是 PASS）⇒ 现在 `G8 FAIL`，reason=`MODEL_ID_UNKNOWN_NOT_ACCEPTED=['B:…']`** ⇒ 第 3 轮 NIT-1 真的被堵住了 |
| **R8** Gold 评分可信 | **PASS** | 第 3 轮原探针 `probe_gold.py` 复跑 | 探针 A：有效 Gold + 0 交付 ⇒ `total=0.0`、`status=SCORED_PARTIAL`（**0 分不是 NOT_SCORABLE**）；探针 B：Gold 未提供 ⇒ `status=NOT_SCORABLE`、`total=None`、`blocked_by=['GOLD_NOT_PROVIDED:…']`；探针 C：考生侧沾 Gold ⇒ `leaked=true` ⇒ `NOT_SCORABLE` + leak_report；探针 D：**分母固定**（考生交 0 条 / 交 1 条，明细条数均为 0，分母 `questions_total=3` 不随考生输出变） |
| **R9** 安全披露保持 | **PASS** | 第 3 轮 `probe_policy.py` / `probe_safety.py` 复跑 + 我自己的披露探针 + `git diff master...HEAD -- backend/config/dd_v1_disclosure_policy.json` | **fail-closed**：策略缺失/损坏/`default_level=PUBLIC` 三种坏情形全部 `load_error` ＋ `default_level=RESTRICTED`（危险默认**拒绝加载**）；**我的考试 A**：`disclosure={blocked_materials: 4, violations: 0, status: PASS}`（拦 4 件、零违规）；**错主体 ⇒ FAIL+59**、**哈希不一致 ⇒ FAIL+59**、**错年度 ⇒ FAIL+59**（我自造）；**生产策略 diff = 0 行**（该文件早于本分支，本分支只增不删） |
| **R10** Windows 真机 | **NOT_VERIFIED** | — | 本机 macOS（darwin 25.6.0 / arm64）；仓内**无任何 Windows 机器产出的证据**；交接包自述「Windows 真机未验（BLOCKED-4）」，责任人=刘江。**按任务书要求不替刘江判定 PASS** |
| **C1** MAJOR-1 真闭环？ | **PASS（已闭环）** | ① 复跑第 3 轮原探针 `probe_safety2.py`（未改一字）② 我自造 5 组探针 ③ 自己重跑考试 A/B/C | ① 探针 C（错年度）⇒ **由第 3 轮的 `PASS/100.0` 变为 `FAIL / total=59.0`**，探针 A（错主体+多交件）⇒ `FAIL/59.0`，探针 B（哈希不一致）⇒ `FAIL/59.0`；② **护栏有效**：`CURRENT`/`当前`/`未知` 交付 ⇒ `safety=PASS, viol=0`（**不冤枉机器**）；**「选中但未交付」的错年度 ⇒ 只 `selection_mismatch_by_kind={WRONG_PERIOD:1}`、`safety=PASS`、不封顶**；**真多交件错年度 ⇒ 仍 `FAIL+59`**（**假阳性防线没有把真阳性一起放过**）；③ **我自己的 A/B/C = 96.67 / 95.67 / 100.0，`safety=PASS`、`violations=0`**（与入库读数逐项一致） |
| **C2** MAJOR-2 真闭环？ | **PASS（已闭环）** | ① 逐份读 `.audit/gate-runs/**` 的 `git_sha`+`git_dirty` ② 读 README 新旧两版 ③ 用自己的重算脚本从 JUnit XML 重建索引 | ① **6 份运行清单 + `g1_pytest.json` + `门禁报告.json` + `覆盖率报告.json` 全部 `git_sha=a1fb96b…`、`git_dirty=false`**（第 3 轮抓到的那份 `true` 已消失）；② README 第 73 行原句「**本轮这批证据均为 `git_dirty=false`**」**已被改写**为「★ **必须逐份读，不能看总印象**——第 3 轮独立复核就查出一处 `git_dirty=true` … 那一份**已作废**，并在**干净树**上重生成」；③ **我重算 = 54/51/50/50/50、覆盖率 0.9804、通过率 1.0、JUnit 索引 2174、逐项状态不一致条目 = 0** ⇒ 与报告**逐位一致** |
| **C3** 阈值仍零改动？ | **PASS** | 我自己 flatten 比对 `6a702ad→b97ce20→0f34ff4→cb03b51→0b1ec84→a1fb96b→HEAD` | **数值阈值差异 = 0**（7 个版本两两比对，`numeric-changed: []`）；`gates` 段相对首版 **REMOVED=0 / CHANGED=0 / ADDED 仅 G8**；`key_gates` 由 `[G1..G5]` 变 `[G1..G5,G8]`（**只加严**） |
| **C4** A5/A6 是否越权？ | **PASS** | 同上 flatten + 读 amendments 全文 | **A5 = 只加严**（安全闸纳入 `WRONG_PERIOD`；G8 对 `MODEL_ID_UNKNOWN` 由「计数不拦」改「FAIL」）；**A6 = 纯说明**（`gates` 段相对 `0f34ff4`/`cb03b51`/`0b1ec84`/`a1fb96b` **逐字未动**，仅新增 `amendments[5]` 文本）；封顶值 59 仍取自冻结规范，**未新增或修改任何数值** |
| **C5** 证伪更正是否如实？ | **PARTIAL** | ① 读全部交付文档的 77.5/方差措辞 ② **自己复跑 5 次 dsh + 3 次 RULE_ONLY**（同一 commit、干净树）③ 在 `/tmp` 全盘搜该次运行的产物 | ① 文档措辞**一致**（README §4.1 / BLOCKED-8 / 交付物对照表 / 提交说明 934ec95 / `.audit/variance/dsh-variance-v3.json` 都是「存在方差」）；② **我的 5 次干净 dsh 全部 96.67（我这边零方差）**，3 次 RULE_ONLY 全部 96.67；生产者的 7 次 `a1fb96b` 也全部 96.67 ⇒ **已归档的干净读数合计 12 次全 96.67**；③ **77.5 那次在 `/tmp/regen_evidence.log` 里逐字可查**（`run_id=20261030T143443Z`、`git_sha=0b1ec84`、`git_dirty=false`）⇒ **现象是真的**，但**该次运行清单从未归档**（仓内 19 份 + `/tmp` 112 份均无）。⇒ **「存在方差」站得住（保守方向，可接受）；「分数会在 96.67 与 77.5 之间跳」作为分布描述站不住（n=1 vs n=12）**；且**该条证据尚未满足项目自己的"可作交付证据"标准** |
| **C6** MINOR/NIT 真闭环？ | **PASS（9 条全闭环）** | 见下节闭环核对表 | MINOR-1 ✓ / MINOR-2 ✓ / MINOR-3 ✓ / MINOR-4 ✓ / MINOR-5 ✓ / NIT-1 ✓ / NIT-2 ✓（逐条证据见下节） |
| **C7** G6 把 CONDITIONAL 判 PASS | **★ 我的新 finding（MINOR-1）** | `tools/dd_v1_exam_suite.py:794-796` + 重跑 `gate --runs .audit/gate-runs` + 读 README/复跑命令 | **是「实现比口径松」的口子**（详见开头第 1 条理由 + 下节详析）；**不是**故意设计：规格 title 写的是「独立 Reviewer **PASS**」，人读文档写的是「现在**不算** PASS」；实现自 `6a702ad` 起**从未改过**、**也没有任何测试守护**。**降级理由**：G6 不在 `key_gates` ⇒ 不影响整体放行；reason 串如实披露 verdict |
| **C8** Skills 升级名副其实？ | **PASS** | `cd bog-global-skills && git show d04632a` + 逐个 Skill 读新增内容 + 全库敏感形态扫描 + 检索口径重算 | **① 内容属实**：`ai-auto-exam-gate v1.3.0` §5.2 写的「131 条假违规」「按归属判定」「最正常的那一档（42 题完整卷）」我**逐条独立复现**；§5.4 写的「当天干净树又打出 77.5」我**在 `/tmp/regen_evidence.log` 里逐字查到了** ⇒ **无夸大、无编造**；`goal-alignment-gate-ops v0.2.0-candidate` §3.7「撤回也要留痕」属实。**② 候选仍是候选**：`version: 0.2.0-candidate` ＋ 文件头「未经独立 Reviewer 验证与批准前，**不得发布为正式全局规范**」⇒ **未进入正式发布态**。**③ 红线（客户材料/密钥/原始敏感数据）**：本分支两个 commit（`ff62b42`/`d04632a`）**零命中**；全库扫到的 2 处真形态 key 串（`social-media/pub2gg-local/SKILL.md:127`、`devops/gbrain-installation/SKILL.md:142`）**来自 2026-09-07 的 `4bc7369`（历史重建），本分支 0 处改动** ⇒ **本轮未引入红线内容**。**④ 检索口径可复现**：`SKILL.md` 总数 **587** ＋ `.archive` 107 ＋ `.disabled_archive` 1 = **108 归档 ⇒ 在用 479** ⇒ 与任务书口径**逐位一致**；版本号逐个核对：`ai-auto-exam-gate 1.3.0` / `real-env-gate-ops 1.2.0` / `python-test-fixture-portability 1.2.0` / `model-provider-onboarding 1.1.0` / `model-provider-key-rotation-ops 1.1.0` ＋ 候选 `goal-alignment-gate-ops 0.2.0-candidate`；**`d04632a` 只动了 2 个文件 ⇒ `ff62b42` 的内容未被破坏** |

---

## 第 3 轮 findings 闭环核对表

| 第 3 轮 finding | closed? | 我怎么验的 | 证据 |
|---|---|---|---|
| **MAJOR-1** 安全闸比冻结尺子松（错年度不封顶、可拿 100 分且 `safety=PASS`） | ✅ **closed** | ① 复跑第 3 轮**原探针** `probe_safety2.py`（一字未改）② 自造 5 组新探针 ③ 自己重跑 A/B/C | ① 探针 C ⇒ **FAIL / viol=1 / total=59.0**（第 3 轮是 PASS/100.0）；探针 A ⇒ FAIL/59.0；探针 B ⇒ FAIL/59.0；② `CURRENT`/`当前`/`未知` ⇒ PASS/0；「选中未交付」⇒ 只单列、不封顶；「真多交件错年度」⇒ 仍 FAIL+59；③ A/B/C = 96.67/95.67/100.0，`safety=PASS`、`violations=0` |
| **MAJOR-2** 覆盖率报告 `git_dirty=true`；README「均为 false」被产物证伪 | ✅ **closed** | ① 逐份读 `git_sha`+`git_dirty` ② 比对 README 新旧文本 ③ 自己重算覆盖率 | ① **逐份全部 `false`**（`a1fb96b`）；② 旧句「本轮这批证据均为 `git_dirty=false`」**已删除**，改为「必须逐份读，不能看总印象」并点名作废那一份；③ 我的重算 **54/51/50/50/50 / 0.9804 / 1.0 / 2174**，逐项差异 **0** |
| **MINOR-1** `model.degrade_reason` 恒为空 | ✅ **closed** | 自跑 AUTO 降级 | `model.degrade_reason` 现在有**完整说明文本**（与答卷 `examinee.degrade_reason` 一致）；RULE_ONLY / REAL_MODEL 时为 `""`（**语义正确**：未降级不该有原因） |
| **MINOR-2** `gold_fingerprint` 每次都变（拿 uuid4 求指纹） | ✅ **closed** | ① 读 19 份运行清单的 `gold_version.fingerprint` ② 自建两份 Gold 比指纹 | ① **同一场考试的 19 份运行清单共享同一个指纹**（A=`068e181a…`、B=`6ef9d45d…`、C=`8996e278…`）；② 同内容不同 uuid ⇒ **指纹相同 True**；`obligation_key` 不同 ⇒ 指纹**必须变** True；内容不同 ⇒ **必须变** True |
| **MINOR-3** dsh 身份「绑定」是装饰性的 | ✅ **closed（含残留）** | 读代码 diff + 读我自己的运行清单 | 代码：`dsh --dump-config` 现在**带 `cwd=expected_cwd`** 执行；binding 新增 `config_cwd_source=process_cwd_of_dump`＋`binding_strength=profile-config-resolved-at-cwd`；note **明写「能证明／不能证明」**。运行时：我的 dsh 运行 `binding.config_cwd=/private/var/folders/…/fos71-agent-44jyyudv`（**真实工作目录**）、`config_cwd_source` 如实、`verified=true`。★ **残留**：仍**不能排除**本次请求被路由到别的模型（dsh 无逐请求回执）——但**这一点已写进产物**，不再是"隐瞒" |
| **MINOR-4** G3 的 reason 只列 dsh 一条 | ✅ **closed** | 读入库门禁报告 | `G3 reason="real_model_runs=['20261030T144559Z'] \| 另有真实模型考生 ['codex:20261030T144728Z', 'pi:20261030T144652Z']（见 all_runs / G8）"` ⇒ **判定口径一字未改，只是 reason 如实补列** |
| **MINOR-5** `frozen_at` 首评估后被回改（git 不可核验） | ✅ **closed（书面处置）** | 读 `amendments[5]`（A6） | A6 **明文**：「接受为已知限制，**不做追溯改写**」＋ 客观补偿「阈值逐字段 0 差异」＋ 登记残余风险「时间戳本身不可由 git 独立核验」。★ 我独立复核：flatten 比对证实**数值阈值差异 = 0**（这一补偿事实成立）；**时间戳本身仍不可核验**（A6 已如实登记，不假装已消除） |
| **NIT-1** AUTO + `MODEL_ID_UNKNOWN` 不单独判 G8 FAIL | ✅ **closed（且是加严）** | 复现第 3 轮 fg5 场景喂 `gate --runs` | 第 3 轮场景（1×REAL_MODEL + 1×MODEL_ID_UNKNOWN）⇒ **G8 FAIL**，`reason=MODEL_ID_UNKNOWN_NOT_ACCEPTED=['B:20261030T144556Z']（真模型参与但身份核实不出来 ⇒ 不得通过模型身份门禁）`；整体 `failed_key_gates=['G8']` |
| **NIT-2** `pytest -q` 末行汇总在 stdout 捕获里丢失 | ✅ **closed（书面处置）** | 读 A6 ＋ 我的 JUnit XML | A6 明写：权威产物是 **JUnit XML**（门禁判定读的就是 XML 计数）⇒ 不影响判定。我自己的 XML：**2174/0/6/2168**，与入库 `g1_pytest.json` **逐项相同** ⇒ 结论不受影响 |

**结论：第 3 轮 9 条 findings（2 MAJOR + 5 MINOR + 2 NIT）全部可复验地闭环，未发现"靠放松口径糊过去"的迹象。**

---

## 证伪清单（我推翻的施工者/前轮结论）

### ① 我**推翻**了"第 3 轮的『AI 成绩存在方差』这个最终表述已经可交付"这一部分 ⇒ 见 C5 / MINOR-2
- **被推翻的部分**：把「**AI 成绩存在方差**」当作**已可交付、已归档**的结论。
- **我的证据**：仓内 19 份运行清单**无一份** `git_sha=0b1ec84`；`/tmp` 全盘 **112 份**运行清单中 `sha=0b1ec84` 的只有 1 份（`git_dirty=**true**`、分数 100.0）⇒ **77.5 那一次没有任何可交付的运行清单**。按项目自己的规则「`git_dirty=false` ＋ 逐份自证」与「证据必须逐份读」，**这一条目前不满足"可作交付证据"**。
- **我要说清楚的公平点**：**现象是真的**（`/tmp/regen_evidence.log` 里 `run_id=20261030T143443Z` 的 77.5 逐字可查，sha=0b1ec84、dirty=false）⇒ **我不是说它编造**，而是说**它的证据链没闭合**；且**我的 5 次独立干净复跑全部 96.67**，⇒ 已归档样本 **12×96.67 vs 1×77.5**，分布描述「会在 96.67 与 77.5 之间跳」**超出样本支持**。

### ② 我**保留（未推翻）**第 3 轮对「不可复现（±19.17）」的证伪 —— 并把它**加强**
- **未被证伪**：第 3 轮说"19.17 存在但三次 77.5 全在脏树 ⇒ 『不可复现』不成立"。我独立核实：仓内所有 77.5 产物（`A-dsh-r3` / `A-agent` / `P5-codex`）**确实全部 `git_sha=275641ff`、`git_dirty=true`** ⇒ **第 3 轮的证伪成立**。
- **加强**：我把搜索范围扩到 `/tmp` 全盘（112 份运行清单）⇒ 脏树 77.5 共 **3 份**，**再无第 4 份**；干净树 77.5 **1 份**（未归档）。

### ③ 我**预设**Skills v1.3.0 §5.2 的「131 条」可能是夸大 —— **该预设被推翻**（但加一条限定）
- **保留**：Skills v1.3.0 §5.2 的「131 条假违规、100.0 误封顶 59、门禁从 PASS 变 FAIL」**属实**（见提交 `a1fb96b` 的说明 + 我实测修复后考试 C 恢复 100.0/PASS/0 违规）。
- **限定**：131 这个数字**我无法独立复现**（那 131 条是**修复前**代码的产物，HEAD 上不复现；我只能验证"修复后不再出现"）⇒ **该数字属于施工者自报、我未独立复现**。

### ④ 我**保留**施工者对 dsh/codex/pi 身份可核实性的结论（且**自己重新取证**）
- 我**独立**跑 `dsh --profile headless --dump-config`、`pi -p --mode json`、并**自己读 codex 的 rollout jsonl**（不是看施工者的清单）⇒ 三条来源各自自洽，且 codex 的 `rollout_cwd` 与 rollout 里的 `cwd` **逐字相同**。

---

## 我发现的新问题

### ★ MINOR-1（C7）：G6 把 `verdict=CONDITIONAL` 判成 PASS —— 实现比口径松，且已发作在交付物里
- **触发条件**：任一轮独立复核给出 CONDITIONAL（且 MAJOR 未闭环）⇒ 门禁 G6 仍输出 PASS。
- **我实测**：`.audit/gate-runs/门禁报告.json` 的 `G6 = {status:"PASS", reason:"reviewer verdict=CONDITIONAL"}`；我用当前代码对入库证据重跑门禁，**得到逐字相同的 G6 PASS**。
- **与口径的冲突**（两条，都是产物级）：
  1. 冻结门禁规格 `backend/config/dd_v1_delivery_gate.v1.json` → `gates.G6.title = "独立 Reviewer PASS（可复跑关键测试的复核报告）"`；
  2. 交接包 `handoff/README.md:88` → 「**G6 独立 Reviewer PASS** … **第 3 轮＝CONDITIONAL** … ⇒ **现在不算 PASS**」。
  ⇒ **同一交付包里，机器说 PASS、人说不算 PASS。** 验收方（刘江）拿到 `门禁报告.json` 极易读成"八道门禁全 PASS ⇒ 独立复核已 PASS"。
- **为什么不是 MAJOR**：① G6 **不在 `key_gates`** ⇒ 改成 FAIL 也**不改变整体 status**；② reason 串**如实披露** verdict ⇒ 不是隐瞒；③ 该行为自 `6a702ad`（首次建门禁）起**从未改动**，**不是本轮引入的回归**。
- **为什么不是"故意设计"**：规格 title 与人读文档都把 G6 定义为"Reviewer **PASS**"；且实现**没有任何测试守护**这个语义（`grep CONDITIONAL backend/tests/` 只命中一处无关注释）⇒ 我**不认为**这是有意的"复核做了就算数"设计。
- **建议**：见开头（改实现＝加严，或改 title ＋ 加机器可读 `reviewer_verdict` 字段 ＋ 明确 G6 在 `key_gates` 里的角色）。

### ★ MINOR-2（C5）：方差实验的"干净树 77.5"一次**没有归档运行清单** ⇒ BLOCKED-8 的证据链未闭合
- **触发条件**：任何人按 BLOCKED-8「AI 成绩存在方差（已实测到 96.67 与 77.5 两档，**干净树上两者都出现过**）」去复核该条。
- **影响**：仓内找不到 `git_sha=0b1ec84` 的运行清单；`.audit/variance/dsh-variance-v3.json` 只是一份**汇总**（`the_77_5_observation` 段），**不含**原始清单/答卷/成绩单 ⇒ 这条要交给业务方的结论**目前不可复核**，且与第 3 轮被抓掉的"脏树 77.5"**形态同类**。
- **证据**：`.audit/variance/dsh-variance-v3.json:155-165`；仓内 19 份 + `/tmp` 112 份运行清单的 sha 扫描；唯一佐证是仓外 `/tmp/regen_evidence.log`（run_id `20261030T143443Z`）。
- **建议**：把那次运行的**运行清单 + 成绩单 + 机器答卷**一并归档进 `.audit/variance/`（或 `.audit/gate-runs/` 下一个带轮次名的目录），并把「n=1 vs n=12」的样本量写进 `final_statement`（现在的措辞把 n=1 写成了分布）。

### ★ MINOR-3：交接包 `复跑命令.md` 的复核报告指针**陈旧**（验收方按它复跑会拿错文件）
- **触发条件**：验收方照 `handoff/复跑命令.md` 第 226 行去核对 G6。
- **实测**：第 226 行写「`.audit/gate-runs/g6_reviewer.json`（**第 2 轮 PASS**）＋ `g6_reviewer_round1.json`（第 1 轮 CONDITIONAL）」；**实际** `g6_reviewer.json` 现在装的是**第 3 轮**（`verdict=CONDITIONAL`，`round=3`），**第 2 轮的 PASS 在 `g6_reviewer_round2.json`**（`verdict=PASS`）⇒ 指针**错了一轮**，且该文件**根本没提 `g6_reviewer_round2.json`**。
- **影响**：验收方会以为"当前复核报告是第 2 轮 PASS" ⇒ 直接构成一次**误读 PASS** 的机会（与 MINOR-1 叠加）。
- **证据**：`docs/dd-v1-fos71/ddv1-auto-test-suite/handoff/复跑命令.md:226`；`.audit/gate-runs/g6_reviewer.json`（round=3, verdict=CONDITIONAL）、`g6_reviewer_round2.json`（round=2, verdict=PASS）。
- **注**：`934ec95` 更新了 `handoff/README.md`，但**没有同步更新 `复跑命令.md`**。

### ★ NIT-1：`_git_dirty()` 豁免整个 `docs/dd-v1-fos71/ddv1-auto-test-suite/` ⇒ 交接包内容变了也不会翻红
- **实测**：`tools/dd_v1_exam_suite.py:73-95` 明确 `continue` 掉 `.audit/` 与 `docs/dd-v1-fos71/ddv1-auto-test-suite/` ⇒ **交接包（含 `SHA256SUMS`）可以在证据自证期间被改写，而所有运行清单仍报 `git_dirty=false`**。
- **实证**：本次复核期间（23:02:34）施工者改写了 `handoff/README.md` ＋ 重新生成了 `handoff/SHA256SUMS`（**未提交**）；我之后跑的考试仍然记录 `git_dirty=false`（因为该目录被豁免）。
- **影响**：**设计上是合理的**（"只看被测代码"，文档不是代码），但**交接包正是验收方拿到的那一份** ⇒ 它落在证据自证之外。已提交版本的自核是好的（**5/5 OK**），但**工作区版本已与提交版不一致**。
- **建议**：把 `docs/.../handoff/` 纳入一个单独的 `handoff_sha256_selfcheck` 字段，或在证据里记交接包的 SHA256 快照。

### ★ NIT-2：README 与机器门禁对"交付门禁整体状态"的表述不一致（同源于 MINOR-1，单独记账）
- README:21「**交付门禁** = **G1—G5、G7、G8 PASS**；G6＝独立 Reviewer（第 3 轮复核中）」 vs `门禁报告.json` 的 `status="PASS"` ＋ G1—G8 **全部 PASS**（含 G6）⇒ 同一批产物里对"门禁整体"的读数不一致。

### ★ NIT-3：方差实验的分布措辞超出样本
- `.audit/variance/dsh-variance-v3.json` 的 `final_statement` 写「同卷同模型，**分数会在 96.67 与 77.5 之间跳**」；已归档样本是 **12×96.67 vs 1×77.5** ⇒ 「会跳」暗示双峰分布，**未测出**。
- 公平地说，README §4.1 与 BLOCKED-8 的措辞**相对诚实**（明写「1 次 77.5」），⇒ 主要是**汇总 JSON 那一句**偏强。

---

## 我无法在本机验证的项

| 项 | 为什么验不了 | 需要谁做什么 |
|---|---|---|
| **R10 Windows 真机** | 本机 macOS（darwin 25.6.0 / arm64）；仓内**零** Windows 机器产出的证据；本体系大量 Windows 专属分支（`taskkill /T /F`、`.cmd` 经 cmd.exe 注入、8191 长度限制、`creationflags=CREATE_NEW_PROCESS_GROUP`、dsh 的 http 代理差异）**在 macOS 上根本不会走到** | **刘江**在 Windows 真机按 `handoff/复跑命令.md` 全量复跑，产出带 `platform=Windows` 的运行清单；在此之前该项一律 **NOT_VERIFIED** |
| **真实 42 题的业务 Gold / 披露分级 / 合格线** | 业务方尚未冻结；本体系按设计**不判**真实业务成绩 | 业务方（波总/刘江）冻结后另行验收（BLOCKED-2/3） |
| **真实 42 题的端到端业务准确率** | 需要真实材料 + 真实披露授权 | 同上（BLOCKED-4） |
| **dsh 凭证「轮换」的管理事实** | 我只能证明「**现在**能用」；无法核验"谁在何时换的 key" | 账号持有人提供轮换记录（BLOCKED-7 的主动探测缺口仍在） |
| **131 条假违规这个具体数字** | 它是**修复前**代码的产物，HEAD 上不复现；我只能验证"修复后不再出现" | 若要独立复现该数字，需在 `cb03b51`（修复前）上跑考试 C —— **本轮我未做**（会污染当前干净树口径） |
| **G6 的"故意设计"意图** | 仓内**没有任何**文档/注释说明"CONDITIONAL 也算 G6 PASS"的设计意图；`git log -S` 显示该行为自首次建门禁起未变 | 需施工者/产品负责人明确表态：这到底是设计还是疏漏 |

---

## 复跑命令清单（粘贴即用）

> 口径：`ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897`；Python=`backend/.venv/bin/python`；数据面 `/tmp/ddv1-review4/plane*`（不碰 `~/.cangjie-ddv1-exams`）。

```bash
cd /Users/mac/.minimax/sessions/mvs_b44860ec1e1b4eb081ffa519f250ea3f/workspace/cangjie-fos

# 0) 版本与干净树
git rev-parse HEAD; git status --short; git log --oneline -6

# 1) X1 全量 pytest（独立 JUnit XML）
cd backend && ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897 \
  .venv/bin/python -m pytest -q --deselect tests/test_doctor_script.py \
  --junitxml /tmp/ddv1-review4/reviewer_pytest.xml ; echo "EXIT=$?"
python3 - <<'PY'
import xml.etree.ElementTree as ET
r=ET.parse('/tmp/ddv1-review4/reviewer_pytest.xml').getroot(); t=list(r.iter('testcase'))
f=sum(1 for x in t if x.findall('failure') or x.findall('error')); s=sum(1 for x in t if x.findall('skipped'))
print('total',len(t),'failed',f,'skipped',s,'passed',len(t)-f-s)
PY

# 2) C1：复跑第 3 轮原探针（错年度必须 FAIL + 59）+ 我的新探针
backend/.venv/bin/python /tmp/ddv1-review/probe_safety2.py
backend/.venv/bin/python /tmp/ddv1-review4/probe_safety_v4b.py

# 3) C1④：自己重跑三场考试（读数必须 96.67 / 95.67 / 100.0，violations=0）
for E in A B C; do
  DDV1_EXAM_PLANE=/tmp/ddv1-review4/plane-exam$E ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897 \
  backend/.venv/bin/python tools/dd_v1_exam_suite.py run --exam $E --run-mode RULE_ONLY --out /tmp/ddv1-review4/exams/$E
done

# 4) R1/R2/R3：三家真实模型（dsh 需 --allow-local-dsh；codex 需 --codex-persist-session）
for A in "dsh --allow-local-dsh" "pi" "codex --codex-persist-session"; do
  DDV1_EXAM_PLANE=/tmp/ddv1-review4/plane-$(echo $A|cut -d' ' -f1) \
  ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897 \
  backend/.venv/bin/python tools/dd_v1_exam_suite.py run --exam A --run-mode AGENT_REQUIRED --agent $A \
  --out /tmp/ddv1-review4/agents/$(echo $A|cut -d' ' -f1) ; echo "EXIT=$?"
done
dsh --profile headless --dump-config | grep -A 4 "agent-default-model"
python3 - <<'PY'
import json,glob
for p in sorted(glob.glob('/Users/mac/.codex/sessions/**/rollout-*.jsonl',recursive=True))[-2:]:
    print('---',p)
    for l in open(p,encoding='utf-8',errors='replace'):
        try: e=json.loads(l)
        except: continue
        pl=e.get('payload') or {}
        if e.get('type') in ('session_meta','turn_context'):
            print('  ',e['type'],'model=',pl.get('model'),'provider=',pl.get('model_provider'),'cwd=',pl.get('cwd'))
PY

# 5) C5：同 commit、干净树重复采样（≥3 次 dsh ＋ 3 次 RULE_ONLY）
for i in 1 2 3; do
  DDV1_EXAM_PLANE=/tmp/ddv1-review4/plane-var$i ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897 \
  backend/.venv/bin/python tools/dd_v1_exam_suite.py run --exam A --run-mode AGENT_REQUIRED --agent dsh \
  --allow-local-dsh --out /tmp/ddv1-review4/variance/A-dsh-var$i
done

# 6) C7（★ 我的新 finding）：G6 对 CONDITIONAL 判 PASS
sed -n '785,800p' tools/dd_v1_exam_suite.py
backend/.venv/bin/python tools/dd_v1_exam_suite.py gate --runs .audit/gate-runs --out /tmp/ddv1-review4/gate_reproduced.json
python3 -c "import json;g=json.load(open('/tmp/ddv1-review4/gate_reproduced.json'));print(g['gates']['G6'])"

# 7) NIT-1（fg5 复现）：1×REAL_MODEL ＋ 1×MODEL_ID_UNKNOWN ⇒ G8 必须 FAIL
D=/tmp/ddv1-review4/fg5v4; mkdir -p $D
cp -R .audit/gate-runs/A .audit/gate-runs/B .audit/gate-runs/C .audit/gate-runs/A-dsh $D/
cp .audit/gate-runs/g1_pytest.json .audit/gate-runs/g1_pytest.xml .audit/gate-runs/g6_reviewer.json $D/
python3 -c "
import json;p='$D/B/运行清单.json';m=json.load(open(p));m.setdefault('model',{})['execution_path']='MODEL_ID_UNKNOWN'
json.dump(m,open(p,'w'),ensure_ascii=False,indent=1)"
backend/.venv/bin/python tools/dd_v1_exam_suite.py gate --runs $D --out $D/gate.json
python3 -c "import json;g=json.load(open('$D/gate.json'));print(g['status'],g['failed_key_gates']);print(g['gates']['G8'])"

# 8) C2③：自己从 JUnit XML 重建索引重算覆盖率
backend/.venv/bin/python /tmp/ddv1-review/recompute_coverage.py

# 9) C2①：逐份读证据的 git_sha + git_dirty
python3 - <<'PY'
import json,glob
for p in ['.audit/gate-runs/门禁报告.json','.audit/gate-runs/覆盖率报告.json','.audit/gate-runs/g1_pytest.json']+sorted(glob.glob('.audit/gate-runs/*/运行清单.json')):
    d=json.load(open(p)); print(p,'| sha=',str(d.get('git_sha'))[:12],'| dirty=',d.get('git_dirty'))
PY

# 10) C3/C4：阈值零改动（7 版 flatten 比对）
backend/.venv/bin/python /tmp/ddv1-review4/gates_only.py
git log --format='%h %ad %s' --date=iso -- backend/config/dd_v1_delivery_gate.v1.json

# 11) R7/R8/R9：回归套件 + 第 3 轮原探针
cd backend && ALL_PROXY=http://127.0.0.1:7897 all_proxy=http://127.0.0.1:7897 \
  .venv/bin/python -m pytest tests/test_dd_v1_false_green_regressions.py \
  tests/test_dd_v1_safety_gate_spec_alignment.py tests/test_dd_v1_evidence_selfproof.py \
  tests/test_dd_v1_gate_binding_determinism.py -q
cd .. && backend/.venv/bin/python /tmp/ddv1-review/probe_gold.py
backend/.venv/bin/python /tmp/ddv1-review/probe_policy.py
git diff master...HEAD --stat -- backend/config/dd_v1_disclosure_policy.json   # 期望：空

# 12) MINOR-2：gold_fingerprint 稳定性
backend/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0,'backend/src')
from cangjie_fos.services import dd_v1_gold_service as g
def mk(u,k,s): return {"gold_pack_id":"G","items":[{"obligation_id":u,"obligation_key":k,"item_no":"1",
    "expected_verdict":"MATCH","expected_files":[{"file_id":"F1","sha256":s}]}],"confirmed_by":"r","confirmed_at":"2026-10-30T00:00:00+08:00"}
print('同内容不同uuid 相同?', g.gold_fingerprint(mk("u1","K","a"*64))==g.gold_fingerprint(mk("u2","K","a"*64)))
print('key不同 必须变?', g.gold_fingerprint(mk("u1","K","a"*64))!=g.gold_fingerprint(mk("u1","K2","a"*64)))
PY

# 13) C8：Skills（以 d04632a 为准）
cd /Users/mac/.minimax/sessions/mvs_b44860ec1e1b4eb081ffa519f250ea3f/workspace/bog-global-skills
git log --oneline -3; git show --stat d04632a
find . -path ./.git -prune -o -name SKILL.md -print | wc -l          # 587
find ./.archive -name SKILL.md | wc -l                              # 107
find ./.disabled_archive -name SKILL.md | wc -l                     # 1  ⇒ 587−108=479
for S in devops/ai-auto-exam-gate devops/real-env-gate-ops \
         software-development/python-test-fixture-portability \
         devops/model-provider-onboarding model-provider-key-rotation-ops \
         devops/goal-alignment-gate-ops; do grep -m1 '^version:' $S/SKILL.md; done
grep -rnE "sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}" --include=*.md . | grep -v '^./.git/'
git diff 2d980cc d04632a | grep -nE "sk-|ghp_|secret|password|子公司|波总|刘江"   # 本轮新增：应为空
```

---

## 附：我本轮实际验到的读数速查（可逐条复核）

| 项 | 我实测的读数 |
|---|---|
| 我的全量 pytest | exit 0；**2174 total / 0 failed / 6 skipped / 2168 passed**（与入库 `g1_pytest.json` 逐项相同） |
| 我的考试 A/B/C | **96.67 / 95.67 / 100.0**；`safety=PASS`、`violations=0`、`单列=0`；`git_sha=934ec95c`、`git_dirty=false` |
| 我的 dsh 复跑（×5） | exit 0；**96.67 ×5**（零方差）；`deepseek-flash`；`verified=true`；`source=DSH_PROFILE_CONFIG` |
| 我的 RULE_ONLY（×3） | exit 0；**96.67 ×3**；`RULE_BASELINE_SCORE`；`ai_system_score=null`；`NOT_SCORED` |
| 我的 pi / codex | exit 0；96.67 / 96.67；`MiniMax-M3.1-Flash-Preview`(AGENT_EVENT) / `gpt-5.6-sol`(CODEX_EXECUTION_RECORD)；codex `rollout_cwd` 与我自读 rollout 的 `cwd` **逐字相同** |
| 我验的安全闸 | 错年度 ⇒ **FAIL+59**；错主体 ⇒ **FAIL+59**；哈希不一致 ⇒ **FAIL+59**；`CURRENT`/`当前`/`未知` ⇒ PASS/0；选中未交付错年度 ⇒ 只单列、不封顶；真多交件错年度 ⇒ 仍 FAIL+59 |
| 我的覆盖率重算 | 54 / 51 / 50 / 50 / 50、0.9804、1.0、索引 2174；逐项差异 **0** |
| 我的门禁重跑 | G1—G8 与入库报告**逐条一致**；**G6 = PASS（reason: reviewer verdict=CONDITIONAL）** |
| 我的假绿反例 | fg5（第 3 轮此场景 PASS）⇒ **现在 G8 FAIL / `MODEL_ID_UNKNOWN_NOT_ACCEPTED`** |
| 我的阈值比对 | 7 版 flatten：**数值差异 = 0**；`gates` 段相对首版**只增 G8**；`key_gates` 增 G8 |
| 我的 Skills 核对 | 587 总 / 108 归档 / **479 在用**；5 升级 + 1 候选（`0.2.0-candidate`）；本轮新增内容**零**密钥/客户材料命中 |
| 我扫到的 77.5 产物 | 仓内 3 份（**全 `git_dirty=true`**）+ 仓外 1 份（`regen_evidence.log`，run_id `20261030T143443Z`，`sha=0b1ec84`/`dirty=false`，**清单未归档**） |

---

## ★ 复核过程附注（诚实交代）

1. **本轮我未修改仓库任何文件**；所有实验产物在 `/tmp/ddv1-review4/`（数据面 `/tmp/ddv1-review4/plane*`）。复核期间（23:02:34）工作区出现 2 个未提交改动（`handoff/README.md`、`handoff/SHA256SUMS`），**是施工者的编辑，不是我**——已核对 `tools/dd_v1_exam_suite.py` 对该目录**只读不写**（`gate` 的 `artifact_exists` 只解析路径），且改动内容是施工者文风的中文散文，与我跑的命令无关。
2. **`_git_dirty()` 的豁免**（`.audit/`、`docs/dd-v1-fos71/ddv1-auto-test-suite/`）意味着上述改动**不会**让运行清单翻红——这正是 NIT-1 记录的问题。
3. **已提交版本**的 `handoff/SHA256SUMS` 自核 **5/5 OK**；**工作区版本**与提交版**不一致**（README 已被改写）。
4. 我复用了第 3 轮 Reviewer 留在 `/tmp/ddv1-review/` 的 5 个探针与重算脚本（`probe_safety2.py` / `probe_gold.py` / `probe_policy.py` / `probe_safety.py` / `recompute_coverage.py`）——**这是刻意的**：任务书要求"原探针必须仍然把错年度判为 FAIL+59"，用同一份探针才有可比性。我另外写了 `probe_safety_v4b.py` / `gates_only.py` 做**新**的独立探针。

**VERDICT: CONDITIONAL**
