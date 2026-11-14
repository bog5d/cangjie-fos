# TEST · 验收证据（cangjie-fos#71 考生2 P0 修复）

全部用例**零外部调用 / 零费用 / 零真实材料**：合成件在 pytest 临时目录现场生成，
模型侧用 `manual` 适配器 + 预置合成回放（零进程零费用，回贴由规则提示现场生成）。

---

## 0. 新增用例清单（`backend/tests/test_dd_v1_fos71_player2_p0.py`，23 条）

| # | 用例 | 对应判据 | 断言要点 |
|---|---|---|---|
| 1 | `test_scaffold_doc_type_equals_resolve_doc_type` | ② | 逐份材料：`meta[].doc_type == resolve_doc_type(file_name=f.name).key`；`doc_type_provenance` 一致；doc_type ∉ 中文；不以扩展名结尾 |
| 2 | `test_scaffold_ignores_directory_name_pollution` | ② | `1.审计报告/营业执照2024.txt` 的类型 **= license**（不是 audit_report） |
| 3 | `test_scaffold_covers_all_ten_canonical_types` | ①/WP1 | 10 类全部被入口 B 认出（旧实现只有 7 类） |
| 4 | `test_multi_entity_evidence_never_crosses_legal_persons` | ③ | 甲义务的证据池 entity 全为甲；乙义务的证据池 entity 全为乙；两个 file_id 集合无交集 |
| 5 | `test_multi_year_materials_do_not_substitute_each_other` | ③ | 2022 与 2024 的「可用候选」集合**不相交**；草稿不进可用候选 |
| 6 | `test_wrong_year_candidate_is_rejected_by_semantic_gate` | ③ | 拿 2024 的材料 MATCH 2022 的义务 ⇒ 被确定性闸拒（`PERIOD_MISMATCH`），accepted 为空 |
| 7 | `test_multi_type_segment_splits_into_atomic_obligations_with_separate_pools` | WP1(a) 正例 | 一段两类 ⇒ 拆 2 条原子义务 + `AMBIGUOUS_SPLIT`；两条义务的证据池**类型互不串** |
| 8 | `test_compound_words_are_not_split_into_two_obligations` | WP1(a) 反例 | 「员工合同」「劳动合同」⇒ 只 1 条义务（误匹配率不升） |
| 9 | `test_multi_type_with_year_in_between_is_split` | WP1(a) 边界 | 间隔含**年份**（「审计报告2024年营业执照」）⇒ 两类 ⇒ 拆（独立复核席指出后补） |
| 10 | `test_han_only_connector_is_treated_as_compound` | WP1(a) 反例 | 纯汉字连接（「甲公司营业执照」）⇒ 判复合词 ⇒ 不拆 |
| 11 | `test_all_ten_types_are_recognized_on_the_obligation_side` | WP1 | 义务侧 10 类全覆盖（缺的那 3 类正是「拆不出义务」的来源） |
| 12 | `test_no_candidate_reason_distinguishes_six_states` | WP3 | 六态**逐个**构造并断言（含 `diagnostics` 计数） |
| 13 | `test_empty_candidate_reason_is_carried_into_rule_hint_and_packet` | WP3 | 空候选原因落进 `evidence_status` 与 `rule_hint`（不再只有一个 MISSING） |
| 14 | `test_legacy_chinese_doc_type_meta_still_matches` | 兼容 | 旧 fixture（**中文** doc_type 的 meta）与英文 key 的义务照样命中（证据池不再恒空） |
| 15 | `test_public_release_list_is_still_license_only` | ⑤ | `sendable_doc_types == ["license"]`；其余 9 类 + 中文名/扩展名/空 ⇒ 一律不可外发且 `RESTRICTED` |
| 16 | `test_full_synthetic_chain_to_authorized_package` | ④ | 语义链（`scaffold`→`split`→`run`）+ 组包链（清单→匹配→审核包→人工批准→授权组包）全通（**本用例是单类型段**：可外发类材料被导出）；**独立复算**：读回交付目录里的组包清单 tsv（由 `dd_v1_package_service.package_approved` 在用例临时目录内生成，**不是仓内文件**），逐行比对「副本 sha256」＝「源 sha256」＝`hashlib.sha256(交付件字节).hexdigest()`，三者逐位相等；受限的审计报告被拦（`blocked ≥ 1`）且不进交付目录。**多类型段的对应缺口见 `EVIDENCE-PLAYER2-P0.md` §8-G5** |
| 17 | `test_split_stage_output_faces_have_no_plaintext_pii` | B1 | split 阶段的**对外落盘面**（obligations / split_flags / untrusted_excerpt / run_record）不得出现明文手机号 / 身份证：`pii.contains_pii` 为假、原文串不出现在产物里 |
| 18 | `test_period_or_version_mismatch_is_not_reported_as_no_material` | B2 | 材料**存在**、只是期间 / 版本不可用 ⇒ `no_candidate_reason is None` 且 `candidate_status == "PERIOD_OR_VERSION_MISMATCH"`，`diagnostics` 逐项计数（按期间拒 1 / 按版本拒 1）；材料确实没有时才 `NO_MATERIAL` + `NO_CANDIDATE` |
| 19 | `test_current_doc_types_is_a_subset_of_the_authoritative_ten_keys` | A1 | `CURRENT_DOC_TYPES ⊆ 权威 10 key`，且等于 `("license", "charter")`；桥接层 `_CURRENT_DOC_TYPES` 与之同一对象（**不另抄一份**） |
| 20 | `test_license_obligation_never_inherits_the_segment_year` | C-1 | 一段同时含「2024 年度审计报告」与「营业执照」⇒ 审计报告义务期间 `2024`、**执照义务期间 `CURRENT`**（不继承段年份）；执照义务能召回执照材料（无假缺口） |
| 21 | `test_scaffold_does_not_treat_index_artifact_as_material` | C-4 | 索引 / 目录件**不是材料** ⇒ `doc_type == ""` 且 `doc_type_provenance == "UNKNOWN"`；真审计报告仍被认成 `audit_report`，同主体同类型只落 1 份（不产生假 CONFLICT） |
| 22 | `test_bridge_period_space_for_current_doc_types_is_current_only` | C-1 | 桥接层两侧同源：材料侧执照 / 章程 ⇒ `CURRENT`（即使卡片 fiscal_period 为 2022），义务侧执照 / 章程 ⇒ `CURRENT`；审计报告两侧仍保 `2022` |
| 23 | `test_license_obligation_end_to_end_has_no_false_gap` | C-1 | 端到端（材料侧 `CURRENT` ＋ 义务侧 `CURRENT`）⇒ 执照义务召回到证据、`candidate_status == "OK"`、`diagnostics.rejected_by_period == 0`、规则提示**不是** `MISSING` |

★ **用例 12 的诚实说明**：`PERMISSION_BLOCKED` 这一态证明的是**分支逻辑**成立；
仓内两个 meta 生产者（桥接链 `build_meta`、入口 B `scaffold`）**都不写** `access` / `restricted`
⇒ **生产路径下该状态不可达**（**留出的扩展点**，见 `EVIDENCE-PLAYER2-P0.md` §8-C7/G1）。

## 1. 既有测试文件里的改动（改判 2 处 + 新增 1 条反例）

| 位置 | 改动 | 理由（详见 `EVIDENCE-PLAYER2-P0.md` §5） |
|---|---|---|
| `tests/test_dd_v1_semantic_retrieval.py:80` | `("公司章程","CURRENT")` → `("charter","CURRENT")` | 类型取值空间统一到权威 10 个英文 key |
| `tests/test_dd_v1_semantic_retrieval.py:81` | `("社保缴纳证明","2024")` → `("labor","2024")` | 同上 |
| `tests/test_dd_v1_semantic_retrieval.py:94`（整条重写） | 「一段含两类 ⇒ 整条丢弃」→ 「按类拆成多条原子义务 + `AMBIGUOUS_SPLIT`」 | WP1(a) 令：默认按类拆；**判据未削弱**（新增反例锁住「复合词不拆」） |
| `tests/test_dd_v1_semantic_retrieval.py`（新增用例） | `test_compound_doc_type_is_not_split_into_two_obligations` | 反例：复合词（员工合同/劳动合同）不拆 |

★ **没有为了让测试变绿而弱化判据**：其余既有断言**一字未改**仍通过，其中包括
`h["R1-O1"] == {"verdict": "MATCH", "files": ["G001", "G002"]}` 这种**整字典相等**的断言
（`rule_hint` 只在**证据为空**时才附 `no_candidate_reason`，非空时逐位不变）。

---

## 2. 命令与退出码（串行单进程，含 ps 证）

★ 全部读数在**同一 checkout 内串行单进程**下取得；pytest 版本 **9.1.1**；
命令＝**复核席同款**（`PYTHONPATH=src .venv/bin/python -m pytest <路径>`）——
仓内 `uv run --extra dev <子命令>` 在本沙箱因包索引不可达而不可执行（见 `EVIDENCE-PLAYER2-P0.md` §6.1-3）。

| # | 树 / 轮次 | 命令 | 退出码 | 失败 | 失败 ID 全集 | 取数时刻(UTC) | ps 证 |
|---|---|---|---|---|---|---|---|
| T1 | **改动后** · 本分支工作树 | `cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/ --ignore=tests/test_doctor_script.py -q` | **0** | **0** | **（空集）** | 04:46:49Z → 04:55:46Z | 开跑前 `ps`＝0；采样 107 次，pytest 主进程恒为 1 |
| T2 | **改动前** · 独立 checkout（HEAD＝`d9bd8e89c1a35aa7f27893bfcd84be4713cf27d2`，自带独立 `backend/data`） | 同上 | **0** | **0** | **（空集）** | 04:56:11Z → 05:03:44Z | 开跑前 `ps`＝0；采样 91 次，pytest 主进程恒为 1 |
| T3 | 改动后 · 六个相关文件 | `cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/test_dd_v1_fos71_player2_p0.py tests/test_dd_v1_semantic_retrieval.py tests/test_dd_v1_local_run.py tests/test_dd_v1_bridge.py tests/test_dd_v1_packaging.py tests/test_dd_v1_policy_and_entry.py -q` | **0** | **0** | **（空集）** | 05:05:57Z → 05:07:23Z | 开跑前 `ps`＝0；采样 29 次，pytest 主进程恒为 1 |
| T4 | 改动后 · 本 PR 新增文件 | `cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/test_dd_v1_fos71_player2_p0.py -q` | **0** | **0** | **（空集）** | 05:07:23Z → 05:07:34Z | 开跑前 `ps`＝0；采样 4 次，pytest 主进程恒为 1 |

★ **失败 ID 集合差集 ＝ 空集**（T1 与 T2 两侧都是空集）⇒ **新增失败 0 条**。
★ **用例条数不登记**（pytest 9.1.1 的 `-q` 不打印末尾计数行；自报数在别的环境不可复现）⇒
`AGENTS.md` 同步不登记该数；权威值以独立复核席在交卷 SHA 上的复跑为准。
本 PR 新增文件内 `def test_` 计数 ＝ **23**（源级事实，grep 可复算）。
★ 早前读数（含 doctor 的对照）：改动前 `pytest tests/ -q` → 退出码 1、失败 1 条
（`tests/test_doctor_script.py::test_doctor_script_exits_zero`，环境型既有失败：本机缺 `backend/.env` 与前端 `node_modules`；
仓内标准命令本就 `--ignore` 它）；改动后同命令 → 退出码 1、**同一条** ⇒ 失败数未新增。

---

## 3. 复算脚本（同口径 before/after）

| 脚本 | 位置 | 退出码 | 用途 |
|---|---|---|---|
| `repro.py` | `/workspace/work/fos-repro/repro.py`（**仓外**，不落进仓） | 0 | 修复前基线（自跑取数，不引用既有输出） |
| `repro_after.py` | `/workspace/work/fos-repro/repro_after.py`（**仓外**） | 0 | 修复后同口径复算 |

两脚本用**同一批**合成义务（14 条）与**同一批**合成材料（8 份，多级目录布局）。数字对照见
`EVIDENCE-PLAYER2-P0.md` §2（拆解 12→17 条义务、整条丢弃 4→0、材料侧类型不一致 5→0、
canonical 配对丢失 7→3、空候选有原因 False→`NO_MATERIAL`）。

---

## 4. 安全负例（判据 ⑤）的具体断言

| 断言 | 位置 |
|---|---|
| `pol.sendable_doc_types == ["license"]` | `test_public_release_list_is_still_license_only` |
| 其余 9 类 `evaluate(pol, "PUBLIC", doc_type=key, entity=合成法人甲).externally_sendable is False` 且 `level == "RESTRICTED"` | 同上 |
| 中文类型名 / `pdf` / `not_a_real_key` / 空 ⇒ 一律不可外发 | 同上 |
| 组包链里：受限的审计报告被**拦下并记账**（`res["blocked"] ≥ 1`，明细落在交付目录里的《被拦截清单.json》——该文件由 `dd_v1_package_service.package_approved` 在用例临时目录内写出，**不是仓内文件**），**不进交付目录** | `test_full_synthetic_chain_to_authorized_package` |
| **单类型段**里只有可外发类材料被导出，且交付件 sha256 与源哈希逐位相等（多类型段另有缺口，见 `EVIDENCE-PLAYER2-P0.md` §8-G5） | 同上 |
| 越界路径仍是**抛异常**（不静默跳过） | `tests/test_dd_v1_semantic_retrieval.py::test_retrieval_refuses_path_outside_snapshot`（既有，未改） |

---

## 5. 改动过的每个服务的既有测试（判据 ⑥）

| 改过的文件 | 既有测试文件 | 结果 |
|---|---|---|
| `dd_v1_semantic_retrieval_service.py` | `tests/test_dd_v1_semantic_retrieval.py`（40）、`tests/test_dd_v1_local_run.py`（23） | 全部通过（2 处断言按 §5 改判并写明理由） |
| `dd_v1_requirement_service.py` | `tests/test_dd_v1_bridge.py`（9）、`tests/test_dd_v1_policy_and_entry.py`（19）、`tests/test_dd_v1_uniqueness.py`、`tests/test_dd_v1_period_and_type_coverage.py` 等 | 全部通过（**只新增公开 API，未改既有函数语义**：`parse_doc_type` 逐字未动） |
| `dd_v1_doc_type_service.py` | `tests/test_dd_v1_uniqueness.py`、`tests/test_dd_v1_bridge.py` | 全部通过（**只新增 `normalize_doc_type`**，既有 `resolve_doc_type` / `is_canonical` 逐字未动） |
| `dd_v1_bridge_service.py` | `tests/test_dd_v1_bridge.py` | 全部通过（`_CURRENT_DOC_TYPES` 改为引用 `rq.CURRENT_DOC_TYPES`，取值不变） |
| `tools/dd_v1_local_run.py` | `tests/test_dd_v1_local_run.py` | 全部通过（`scaffold`/`split` 的输出字段有增项，测试未受影响） |
| 新增 `tests/test_dd_v1_fos71_player2_p0.py` | — | 见 §2 的 T4 行（文件内 `def test_` 计数 ＝ 23，源级事实） |
