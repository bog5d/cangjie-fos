# DD-V1 自动化覆盖率报告（施工令 WP4 · 目标 A）

> 口径声明（**先说清楚怎么算的**，避免“漂亮数字”）：
> - **分母**＝「DD-V1 交付前**必须被验证**的验收项」清单（本文件 §1 逐项列出，**共 54 项**）；
>   ★ **不是**代码行覆盖率、**不是**测试函数个数；**不得**通过删项缩分母。
> - **可自动化**＝该项的判定结果**可由机器复算**（不需要业务判断、不需要人授权、不依赖 Windows 真机）。
> - **已自动化**＝已有**自动化用例**且**可重复执行**（同样的输入 ⇒ 同样的判定）。
> - **自动化覆盖率** ＝ 已自动化项 ÷ 可自动化项；
> - **自动化测试通过率** ＝ 通过的自动化项 ÷ 本轮**实际执行**的自动化项。
> - 两个数**分开报**（覆盖率＝「有没有机器在管」，通过率＝「机器管的东西过没过」）。
> ★★ §2 的数字由 **`tools/dd_v1_exam_suite.py coverage` 机算**（清单 `backend/config/dd_v1_acceptance_items.v1.json`），
>    逐条把证据引用对到 **JUnit XML 的真实执行结果** / **运行清单** / **门禁报告** 上求值。
> - 本轮实测数据来源：`.audit/gate-runs/g1_pytest.json` ＋ `g1_pytest.xml`（JUnit）、
>   `.audit/gate-runs/门禁报告.json`（G1—G7）、三场考试的**运行清单**（含成绩与失败项）。

---

## 1. 验收项清单（54 项 · 全量列出，不省略）

图例：✅ 已自动化且本轮 PASS ｜ ⚠️ 已自动化但本轮 **BLOCKED** ｜ ❌ 可自动化但**尚未**自动化 ｜ 🧑 **人工不可替代**

### A. 拆题与义务口径（7 项）

| # | 验收项 | 可自动化 | 状态 | 证据 |
|---|---|---|---|---|
| A1 | 42 题全部进入处理链路（一条清单项⇒至少一条义务，**不丢题**） | ✅ | ✅ | `test_dd_v1_exam_suite_l1.py::test_all_42_questions_enter_the_contract` |
| A2 | 不同入口拆题结果一致（库侧契约 vs 桥接层） | ✅ | ✅ | `...::test_runner_and_library_agree_on_the_same_contract` |
| A3 | 题号全程一致（清单题号 → 义务 → 答卷 → 成绩单） | ✅ | ✅ | `...::test_zz`（D2 回归）＋考试C `已处理 42/42` |
| A4 | 义务身份唯一且可追（权威 ID ＝ 库侧 ID） | ✅ | ✅ | `...::test_cluster_obligation_id_resolves_to_authoritative_id` |
| A5 | 并列连接词切成多条原子义务（「和/且/及」） | ✅ | ✅ | `...::test_parallel_connector_splits_into_two_obligations` ＋负例 `...::test_parallel_split_does_not_break_normal_sentences` |
| A6 | 原文零丢失（拆分只作用于派生文本） | ✅ | ✅ | `...::test_original_text_is_never_lost_by_splitting` |
| A7 | 清单/题号归一（分部目录名 vs 三级编号） | ✅ | ✅ | `test_dd_v1_obligation_contract_wp2.py::TestCanonicalQuestionId` |

### B. 主体与期间（6 项）

| # | 验收项 | 可自动化 | 状态 | 证据 |
|---|---|---|---|---|
| B1 | 主体多源分级（人工确认 > 路径 > 别名 > 正文 > 元数据 > 认不出） | ✅ | ✅ | `test_dd_v1_entity_resolution.py` |
| B2 | 集团范围义务 ⇒ 多主体**分簇**且不跨法人混桶 | ✅ | ✅ | 考试B 的 2-1（`cluster_count=3`） |
| B3 | 分簇义务在阅卷时**按库侧 ID 归并**（D1 回归） | ✅ | ✅ | `..._l2.py::test_exam_b_multi_entity_obligation_is_scored_against_the_library_id` |
| B4 | 跨年度不顶替（错年份材料不被选中） | ✅ | ✅ | 考试B 的 2-2 ＋ 考试C 的跨年度题 |
| B5 | 相对期间（「近三年」）按锚点解析 | ✅ | ✅ | 考试B 的 2-6（锚定 2024） |
| B6 | 主体未登记 ⇒ 不得拿目录名凑数 | ✅ | ✅ | `test_dd_v1_fos71_player2_p0.py` |

### C. 匹配与选材（6 项）

| # | 验收项 | 可自动化 | 状态 | 证据 |
|---|---|---|---|---|
| C1 | 正确材料被选中 | ✅ | ✅ | 考试C `material_recall=1.0` |
| C2 | 错误材料不被选中（精度） | ✅ | ✅ | 考试C `selection_precision=1.0` |
| C3 | 错误主体材料不被选中 | ✅ | ✅ | 考试B 的 2-2/2-3（互为干扰项） |
| C4 | 错误年份材料不被选中 | ✅ | ✅ | 考试C 跨年度题（年份轴正交） |
| C5 | 候选触顶如实报数（「上限 X，另 N 份未看」） | ✅ | ✅ | `test_dd_v1_candidate_expansion.py` |
| C6 | 多文件要求：缺一即 `INCOMPLETE` | ✅ | ✅ | 考试B 的 2-7（修 D4 前 `INCOMPLETE` ⇒ 修后 `CORRECT`） |

### D. 审核与披露闸（7 项）

| # | 验收项 | 可自动化 | 状态 | 证据 |
|---|---|---|---|---|
| D1' | 受限材料**不得**进正式交付包（负例） | ✅ | ✅ | 考试C 的合同类题（`disclosure.violations=0`、`blocked_materials>0`） |
| D2' | 披露闸断言必须 fail-closed（找不到清单 ⇒ FAIL） | ✅ | ✅ | `tools/dd_v1_exam_suite.py: disclosure_assertions`（本轮把「假绿」改成 FAIL） |
| D3' | 未批准不得复制原件 | ✅ | ✅ | `test_dd_v1_p0_delivery_gate.py` |
| D4' | 不确定材料不得混入正式包 | ✅ | ✅ | `..._l1.py::test_uncertain_material_is_not_in_the_delivered_set` |
| D5' | 受限外发 / 越权交付安全闸独立计分 | ✅ | ✅ | `test_dd_v1_p0_disclosure.py`＋成绩单 `safety_gate` |
| D6' | 错主体/错年份/哈希不一致单列且封顶 | ✅ | ✅ | `test_dd_v1_exam_scoring.py` |
| D7' | 披露口径**按考场可配置**（生产策略不变） | ✅ | ✅ | `CANGJIE_DD_V1_POLICY`（考试台自带合成考场口径） |

### E. 组包与交付（6 项）

| # | 验收项 | 可自动化 | 状态 | 证据 |
|---|---|---|---|---|
| E1 | 7 项交付链产物齐全 | ✅ | ✅ | `test_dd_v1_packaging.py` / `test_dd_v1_packaging_exact.py` |
| E2 | 逐件 SHA256 复算一致 | ✅ | ✅ | 组包 `组包manifest.tsv` 的「源/副本 sha256 + 一致」三列 |
| E3 | 0 件交付必须如实写「未产出正式交付件」 | ✅ | ✅ | 考试A 首轮（0 交付 ⇒ 总分强制 0） |
| E4 | **历史交付不得冒充本轮**（残留 manifest） | ✅ | ✅ | `..._l1.py::test_stale_delivery_manifest_is_not_counted_as_this_run` |
| E5 | 审核后原件变更 ⇒ 停止交付（审核失效） | ✅ | ✅ | `test_dd_v1_idempotency.py` / `test_dd_v1_recovery.py` |
| E6 | 正式包与候选包物理隔离 | ✅ | ✅ | `test_dd_v1_p0_delivery_gate.py` |

### F. 答卷 / 阅卷 / 评分（8 项）

| # | 验收项 | 可自动化 | 状态 | 证据 |
|---|---|---|---|---|
| F1 | 机器答卷逐题记录（理解/候选/选中/交付/弃答原因） | ✅ | ✅ | `机器答卷-*.json` |
| F2 | **0 件交付 ⇒ 0 分**（不是 NOT_SCORABLE） | ✅ | ✅ | `..._l1.py::test_zero_delivery_with_valid_gold_scores_zero_not_not_scorable` |
| F3 | Gold 未提供 ⇒ NOT_SCORABLE **且写明阻塞** | ✅ | ✅ | `..._l1.py::test_missing_gold_is_not_scorable_and_says_why` |
| F4 | Gold 泄漏 ⇒ 不进入正式评分 | ✅ | ✅ | `..._l2.py::test_gold_leak_stops_scoring` |
| F5 | Gold **按稳定键**绑定（换快照仍能绑上） | ✅ | ✅ | `..._l1.py::test_gold_binds_by_stable_key_even_when_uuid_changed` |
| F6 | 分层成绩单（保留全卷分母 + 缺口逐件） | ✅ | ✅ | 考试B `SCORED_PARTIAL`（歧义 1 条 + 缺料 1 条） |
| F7 | 逐题明细 + 7 项指标 + 0—100 总分 | ✅ | ✅ | 成绩单 JSON |
| F8 | 安全闸封顶（命中 ⇒ ≤59） | ✅ | ✅ | `test_dd_v1_exam_scoring.py` |

### G. 模型参与（5 项）

| # | 验收项 | 可自动化 | 状态 | 证据 |
|---|---|---|---|---|
| G1' | **RULE_ONLY 不得冒充模型参与** | ✅ | ✅ | `test_dd_v1_model_participation_l3.py::test_rule_only_run_is_not_credited_as_model_participation` |
| G2' | 参与必须**回执口径 + 盖章来源** | ✅ | ✅ | `...::test_missing_stamp_means_not_participated` |
| G3' | 自造适配器 id **不得**被认成 HARNESS_MODEL | ✅ | ✅ | `...::test_spoofed_adapter_id_is_not_credited` |
| G4' | 模型失败必须报错（超时/非零退出/不存在/垃圾输出） | ✅ | ✅ | `..._l2.py` 的 4 条失败路径用例 |
| G5' | **真实 DeepSeek 参与**（进程 + 请求指纹 + 响应落盘） | ✅ | ⚠️ | 用例已写（`test_real_deepseek_harness_probe`，默认 skip）；**本机 dsh 凭证失效 ⇒ BLOCKED-1** |

### H. 安全与隔离（4 项）

| # | 验收项 | 可自动化 | 状态 | 证据 |
|---|---|---|---|---|
| H1 | Gold 与考生面**物理分离**（隔离闸拒绝仓内 Gold） | ✅ | ✅ | `test_dd_v1_exam_e2e.py::test_gold_inside_repo_is_refused` |
| H2 | 合成测试数据**不污染真实业务库**（隔离数据面） | ✅ | ✅ | 考试台数据面在仓库之外（`~/.cangjie-ddv1-exams`） |
| H3 | PII 脱敏（材料正文不进 prompt/产物） | ✅ | ✅ | `test_dd_v1_pii.py` |
| H4 | 命令行不含材料明文（Windows 注入面） | ✅ | ✅ | `dd_v1_agent_adapters._prompt_for`（stdin 通道）＋其单测 |

### I. 环境与兼容（3 项）

| # | 验收项 | 可自动化 | 状态 | 证据 |
|---|---|---|---|---|
| I1 | CI 与本机口径一致（代理变量污染、doctor 依赖） | ✅ | ✅ | 门禁报告 `env_hygiene`（两条口径**写在报告里**） |
| I2 | macOS 本机全量回归 | ✅ | ✅ | `g1_pytest.json`（本轮：2104 项，0 失败〔CI 口径〕） |
| I3 | **Windows 真机兼容**（路径/编码/cmd.exe/PowerShell 通配） | ❌ | 🧑 | **Mac 上无法验证** ⇒ 必须 Windows 真机（BLOCKED-4） |

### J. 业务判断（2 项 · 人工不可替代）

| # | 验收项 | 可自动化 | 状态 | 原因 |
|---|---|---|---|---|
| J1 | **真实 42 题的业务准确性**（选对没有、对不对业务） | ❌ | 🧑 | 机器只能算「与 Gold 一致率」；「Gold 本身对不对」要业务判断（BLOCKED-2/3） |
| J2 | **披露授权**（哪些材料可外发） | ❌ | 🧑 | 业务口径，非机器可判定（合成考场口径**不代表**真实考场） |

---

## 2. 覆盖率与通过率（**机算** · 原始分母，不缩）

> ★★ 本节数字**不是人工填的**——由 `tools/dd_v1_exam_suite.py coverage` **从实际执行产物算出**：
> 逐条把验收项的证据引用（pytest node id / 考试指标 / 门禁）拿去对
> **JUnit XML 的真实执行结果**、**三场考试的运行清单**、**门禁报告**求值。
> 清单在 `backend/config/dd_v1_acceptance_items.v1.json`（54 项全量，冻结）。
> 机读结果：`.audit/gate-runs/覆盖率报告.json` → `自动化覆盖率统计`。

| 指标 | 数值 | 算式 | 谁算的 |
|---|---|---|---|
| 验收项总数 | **54** | §1 逐项计数（**修正了旧版的 48**：旧版 §1 实际列了 54 项，§2 却按 48 算，两处自相矛盾 ⇒ **以逐项计数为准**） | 机算 |
| 人工不可替代 | **3** | I3（Windows 真机）、J1（真实业务准确性）、J2（披露授权） | 机算 |
| **可自动化项** | **51** | 54 − 3 人工不可替代 | 机算 |
| **已自动化且可重复执行** | **50** | 51 − G5'（真实模型：用例已写，但本机凭证失效 ⇒ **不可复算，不充数**） | 机算 |
| **自动化覆盖率** | **50 / 51 = 98.04%** | 已自动化 ÷ 可自动化（**≥ 90% 目标达成**） | 机算 |
| 本轮实际执行 | **50** | 证据引用在 JUnit XML 里**找到且未被 skip** 的项 | 机算 |
| 其中通过 | **50** | —— | 机算 |
| **自动化测试通过率** | **50 / 50 = 100%** | 通过 ÷ 实际执行 | 机算 |

> **口径说明（三处都按「不充数」处理）**：
> ① I3 / J1 / J2 **本质不可自动化** ⇒ 进「人工不可替代」清单，**不进可自动化分母**。
> ② G5'（真实模型参与）**技术上可自动化**（用例已写好）⇒ **留在可自动化分母里**（51），
>    但本机**凭证失效**⇒ 该用例被 **skip** ⇒ **既不计入覆盖率分子、也不计入通过率分母**
>    ⇒ 覆盖率与通过率**都如实扣了它**（**没有拿它充数**）。
> ③ 「ref 找不到」⇒ 记 `NOT_AUTOMATED`；「ref 被 skip」⇒ 记 `BLOCKED`；
>    **两者都不会被算成通过**（本轮机检就抓到过 1 处引用写错文件 ⇒ 修正后才通过）。

### ★ 与旧版数字的差异说明（**分母变大了，更保守**）

| 项 | 旧版（人工填写） | 本版（机算） | 方向 |
|---|---|---|---|
| 验收项总数 | 48（**与 §1 的 54 项矛盾**） | **54** | 分母**变大** |
| 可自动化项 | 43 | **51** | 分母**变大** |
| 自动化覆盖率 | 42/43 = 97.7% | **50/51 = 98.04%** | —— |
| 自动化测试通过率 | 41/42 = 97.6% | **50/50 = 100%** | 通过率上升是**因为口径修正**（G5' 被 skip ⇒ 不进通过率分母），**不是**因为多写了测试 |

> ★ 通过率从 97.6% 变 100% **不是**成绩变好，而是**口径修正**：
> 旧版把「被 skip 的用例」也算进了「实际执行」，再算它没通过 ⇒ 双重扣分。
> 本版按 pytest 的真实语义：`skipped` ＝ **本轮没有执行这条断言** ⇒ 不进通过率分母。
> ★ 两版**都**把 G5' 从**覆盖率分子**里剔掉了 ⇒ **覆盖率口径未放宽**。

---

## 3. 未自动化项与原因（逐条 · 机算产出）

| 验收项 | 机算状态 | 原因 | 谁能解 | 解除方式 |
|---|---|---|---|---|
| G5' 真实 DeepSeek 参与证明 | `BLOCKED` | 本机 `~/.dsh/.credentials.yaml` 的 key 被服务端判 invalid（证据 `.audit/real-model/stderr.log`） | 账号持有人 | 更新 key ⇒ `DDV1_ALLOW_REAL_MODEL=1 pytest -k real_deepseek` ⇒ 门禁 G3 自动转 PASS |

> ★ 本轮机检**没有**「引用写错导致假通过」的情况：引用全部对得上 JUnit XML 的真实节点。

---

## 4. 人工不可替代清单（**机器不接** · 机算产出）

| 验收项 | 为什么机器不能替代 | 谁来做 | 前置条件 |
|---|---|---|---|
| I3 Windows 真机兼容 | Mac 上**无法复现** Windows 路径/编码/cmd.exe 行为 | 刘江（Windows 真机） | 交接包 ＋ 冻结 SHA（本轮已产出） |
| J1 真实 42 题业务准确性 | 机器只能算「与 Gold 一致率」；**Gold 对不对**是业务判断 | 波总/业务方 | 真实 Gold ＋ 真实材料 ＋ 披露口径（BLOCKED-2/3） |
| J2 披露授权 | 「哪些材料允许外发」是业务授权，非机器判定 | 波总 | 考场披露口径书面确认 |

---

## 5. 读数出处（可复核）

| 读数 | 文件 |
|---|---|
| 验收项清单（54 项 · 冻结） | `backend/config/dd_v1_acceptance_items.v1.json` |
| pytest 机读报告（2104 项 / 0 失败〔CI 口径〕） | `.audit/gate-runs/g1_pytest.json` ＋ 同名 `.xml`（JUnit） |
| G1—G7 门禁报告 | `.audit/gate-runs/门禁报告.json` |
| 覆盖率报告（**机算**） | `.audit/gate-runs/覆盖率报告.json` → `自动化覆盖率统计` |
| 三场考试的运行清单与成绩单 | `.audit/exam-plane/{A,B,C}/runs/*/运行清单.json`、`grade/成绩单-*.json` |
| 真实模型阻塞证据 | `.audit/real-model/stderr.log`、`real-model-evidence.json` |
