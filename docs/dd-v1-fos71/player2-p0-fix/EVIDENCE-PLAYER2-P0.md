# EVIDENCE · 考生2 P0 修复（cangjie-fos#71）

- **subject_id**：DD-V1-FOS71/PLAYER2-P0-FIX
- **授权来源**：董事长 2026-10-23 施工令「FOS考生2｜P0产品阻塞修复 云端MiniMax自主施工令 V1.1」＋司仓派工本件
- **base**：`d9bd8e89c1a35aa7f27893bfcd84be4713cf27d2`（master tip；与令中基线逐位一致）
- **分支**：`feat/71-player2-p0-fix-20261023`（第一父 = base，快进非 force，**未推 master、未合并任何分支**）
- **作者**：云端 MiniMax Executor（唯一 Writer）｜**自查，不是独立复核**（独立 Reviewer 由司仓指派）
- **零外部调用 / 零费用 / 零真实材料**：本轮未调用任何收费模型；未读 Gold；仓内未写入任何真实清单、客户材料、个人信息或密钥
  （新增材料全部是**现场合成**的 `合成法人甲 / 合成法人乙` 样例，落在 pytest 临时目录，不进仓）

---

## 1. 修复了什么（四个 WP）

| WP | 改动 | 主要落点 |
|---|---|---|
| **WP1** 材料类型统一 | 语义层删掉那张 7 类中文表，类型判定改走权威 10 类（`rq.parse_doc_type_spans`）；一段多类**不再整条丢弃**，按类拆成多条原子义务并留痕 `AMBIGUOUS_SPLIT`；旧中文 doc_type 在**比较/归一环节**兼容 | `dd_v1_requirement_service.py`、`dd_v1_doc_type_service.py`、`dd_v1_semantic_retrieval_service.py` |
| **WP2** 正式入口修复 | `tools/dd_v1_local_run.py` 的 `scaffold` 改用 `dd_v1_doc_type_service.resolve_doc_type(file_name=f.name)`（**只看文件名**、产出英文 key + provenance），期间判定同步改用英文 key；`split` 走修好的语义层 | `tools/dd_v1_local_run.py` |
| **WP3** 主体与证据过滤 | 两侧 doc_type 先归一再比（证据池不再恒空）；主体按 `dd_v1_entity_service` 同口径归一（跨法人不混桶）；候选为空时给出**六态原因** + 过滤诊断（年度/版本/附件/权限/截断逐项计数） | `dd_v1_semantic_retrieval_service.py` |
| **WP4** 全链路合成回归 | 新增 23 条验收用例：类型归一 / 多主体多年度 / 完整合成组包 / 安全负例 / 多类拆分正反例 / 六态原因 / 旧数据兼容 / 期间与版本不可用的定级 / 对外落盘面 PII 脱敏 / 索引件不当作材料 / 执照类义务不继承段年份 | `backend/tests/test_dd_v1_fos71_player2_p0.py` |

---

## 2. 修复前后（同一套合成数据的同口径复算）

复算脚本：`/workspace/work/fos-repro/repro.py`（修复前）与 `/workspace/work/fos-repro/repro_after.py`（修复后）。
两份脚本都用**同一批**合成义务（14 条）与**同一批**合成材料（8 份，刻意复刻真实材料库多级目录布局）。

| 观测项 | 修复前 | 修复后 | 判读 |
|---|---|---|---|
| A. 旧 7 类表覆盖不到权威类型 | `resolution, ip, contract`（3 类缺） | 语义层 = 权威 10 类，无缺 | 根因 A 消除 |
| B. 14 条合成义务的拆解 | **12 条义务**；整条丢弃 **4** 条（决议/知识产权/劳动合同/合同）；半拆 **2** 条 | **17 条义务**；整条丢弃 **0** 条；半拆 **1** 条（第 13 条的「2022、」年份残片，仍标 PARTIAL_SPLIT，不假装拆干净） | 拆解率从 8/14 条有产出 → 14/14 条有产出 |
| C. 权威口径可识别 | 14/14（权威表本来就能认全） | 14/14 | 缺的是**语义层没用权威表** |
| D. 材料侧类型（入口 B 判定 vs 权威判定） | **5 份不一致**：目录污染 1 份（`1.审计报告/营业执照2024.pdf` 被认成 audit_report）+ 决议/知识产权/劳动合同/合同 4 份判不出 | **0 份不一致**（8/8 与 `resolve_doc_type` 逐位相同） | 根因 B 消除 |
| E. 义务类型 ∩ 材料类型（canonical 视角） | 丢 **7** 对 | 丢 **3** 对（`capital / financial_statement / tax` —— 这批合成材料里**确实没有**这三类，属真实缺口） | 证据池恒空消除 |
| F. 空候选是否有原因 | `has_reason_field = False`（静默空列表） | `no_candidate_reason = "NO_MATERIAL"`，六态枚举齐全 + 过滤诊断 | 根因 C 消除 |

★ E 的「丢 3 对」**不是漏检**：那三类材料在这批合成材料里确实不存在 —— 修复后系统会**如实说「没有」并给出原因**，
而不是像修复前那样把「类型空间不同」也伪装成「没有材料」。

---

## 3. 根因逐条对应（司仓派工本 §2 ↔ 本 PR 的机械证）

| 派工本根因 | 机械证（可复核） | 本 PR 的处置 |
|---|---|---|
| **A** 语义层硬着 7 类中文表 | 修复前 `dd_v1_semantic_retrieval_service.py:27` `DOC_TYPES = ("审计报告","营业执照","公司章程","社保缴纳证明","财务报表","验资报告","纳税证明")`；`rq.parse_doc_type` 对这 7 个中文名的映射只覆盖 7/10（`resolution/ip/contract` 缺） | 删除该表；类型判定改走 `rq.parse_doc_type_spans`（同表） |
| **A** 命中数必须恰好为 1，否则整条丢弃 | 修复前 `_doc_type()` 第 50 行 `hits[0] if len(hits) == 1 else None` + `split_item` 第 75–77 行整条丢 | `_doc_type_spans()`：**可分离**（两次命中之间有分隔符）⇒ 拆多条原子义务 + `AMBIGUOUS_SPLIT`；**不可分离**（复合词）⇒ 退回归一类型（与 `rq.parse_doc_type` 一致） |
| **A** 期间判定用中文常量 | 修复前 `:66` `dt in ("营业执照","公司章程")` | `:176` `all(k in rq.CURRENT_DOC_TYPES for k, _s, _e in spans)` |
| **B** 入口 B 拿整条路径判类型 | 修复前 `tools/dd_v1_local_run.py:157` `next((d for d in sem.DOC_TYPES if d in rel), "")`；合成材料里 `1.审计报告/营业执照2024.pdf` 被判成 audit_report | `:179` `dts.resolve_doc_type(file_name=f.name)`（只看文件名）+ `doc_type_provenance` 留痕 |
| **B** 入口 B 期间判定用中文常量 | 修复前 `:159` `dt in ("营业执照","公司章程")` | `:182` `rq.CURRENT_DOC_TYPES` |
| **C** 证据过滤精确字符串相等 ⇒ 池恒空且静默 | 修复前 `:146` `pool = [m for m in meta if m["entity"] == ob["entity"] and m.get("doc_type") == ob["doc_type"]]`；两侧 key 空间不同 ⇒ `pool == []` 且无任何说明 | `:319 retrieve_minimal_evidence_detailed()`：两侧 `dts.normalize_doc_type()`（`:338` 义务侧 / `:357` 材料侧）归一后再比；空池返回 `no_candidate_reason`（六态）+ `diagnostics` |
| **C** 六种原因不分 | 修复前 `rule_hint` 对空证据只给 `note="NO_EVIDENCE"` | 六态枚举 `sem.NO_CANDIDATE_REASONS` + `evidence_status` 逐义务留痕 + `rule_hint` 在证据为空时附原因 |
| **D** 规则链与语义链 doc_type 空间分叉（既有事实） | `dd_v1_bridge_service.build_meta` / `build_semantic_obligations` 两侧都出英文 key（走 `rq.parse_doc_type`）；`backend/tests/test_dd_v1_policy_and_entry.py:261` 2026-10-22 已改断言为英文 key | 语义层补齐为同一 key 空间；桥接链的 `_CURRENT_DOC_TYPES` 也收归 `rq.CURRENT_DOC_TYPES`（不再另抄） |
| **E** 现有测试把旧中文行为锁死 | `backend/tests/test_dd_v1_semantic_retrieval.py:80-81` 断言 `("charter","CURRENT")`、`("labor","2024")`；`:94` 断言「一段含两类 ⇒ 按类拆」 | 逐条改判并写明理由（见 §5 改判清单）；**判据未被削弱**（新增反例用例锁住「复合词不拆」） |

---

## 4. 验收判据逐条对账

| 判据 | 落点 | 结果 |
|---|---|---|
| ① 全量测试退出码 0、失败数不新增 | §6 | 见 §6（**基线 1 失败 → 改动后 1 失败，同一条**；该失败与本 PR 无关） |
| ② 类型归一：scaffold ≡ resolve_doc_type，不含中文类型名/扩展名 | `test_scaffold_doc_type_equals_resolve_doc_type`、`test_scaffold_ignores_directory_name_pollution`、`test_scaffold_covers_all_ten_canonical_types` | 通过 |
| ③ 多主体/多年度：甲不串乙、2022 不顶 2024 | `test_multi_entity_evidence_never_crosses_legal_persons`、`test_multi_year_materials_do_not_substitute_each_other`、`test_wrong_year_candidate_is_rejected_by_semantic_gate` | 通过 |
| ④ 完整合成组包：清单 → 拆分 → 类型归一 → 候选召回 → 语义判断 → 规则校验 → 审核 → 授权组包，产物落盘且 sha256 可复算 | `test_full_synthetic_chain_to_authorized_package` | 通过（用例内**读回交付目录里的组包清单 tsv**（该 tsv 由 `dd_v1_package_service.package_approved` 在用例临时目录内生成，**不是仓内文件**），逐行把「副本 sha256」与「源 sha256」同 `hashlib.sha256(交付件字节).hexdigest()` 三方比对，逐位相等） |
| ⑤ 安全负例：受限资料披露不放宽，PUBLIC 放行清单仍只有 license | `test_public_release_list_is_still_license_only`（+ 组包用例里断言审计报告被拦；**单类型段**里可外发类材料被导出且交付件 sha256 逐位相等） | 通过（**「被导出」的适用范围＝单类型段**；多类型段的已知缺口见 §8-G5） |
| ⑥ 旧功能全量回归 + 改判清单 | §5 + §6 | 通过（改判 **2** 处断言，理由逐条写明） |
| ⑦ 零外部调用、零费用、零真实材料 | §7 | 通过 |

---

## 5. 被改判的既有断言（逐条：旧 → 新 → 为什么）

| # | 位置 | 旧断言 | 新断言 | 为什么 |
|---|---|---|---|---|
| 1 | `backend/tests/test_dd_v1_semantic_retrieval.py:80` | `assert (obs["R2-O1"]["doc_type"], obs["R2-O1"]["period"]) == ("公司章程", "CURRENT")` | `== ("charter", "CURRENT")` | **类型取值空间统一到权威 10 个英文 key**（`dd_v1_requirement_service._DOC_TYPE_RULES`）。旧断言锁的是语义层那张 7 类中文表 —— 它只覆盖 10 类中的 7 类（缺 `resolution/ip/contract`），且与桥接层的英文 key 空间分叉 ⇒ 证据池恒空。**语义不变**（仍是「公司章程」这一类材料，期间口径不变）。司仓 2026-10-22 已在 `test_dd_v1_policy_and_entry.py:261` 做过同向口径更正（注释写明「WP-A1 口径更正」），本 PR 把产品实现补齐 |
| 2 | `backend/tests/test_dd_v1_semantic_retrieval.py:81` | `assert (obs["R2-O2"]["doc_type"], obs["R2-O2"]["period"]) == ("社保缴纳证明", "2024")` | `== ("labor", "2024")` | 同上：「社保缴纳证明」在权威表里的 key 是 `labor`（`(劳动合同\|社保\|花名册\|员工)`）。**期间 2024 未变** |
| 3 | `backend/tests/test_dd_v1_semantic_retrieval.py:94`（整条用例重写） | `test_ambiguous_two_doc_types_in_one_segment_not_guessed`：`assert obs == [] and flags["status"] == "NEEDS_HUMAN_SPLIT"` | 改名 `test_ambiguous_two_doc_types_in_one_segment_split_into_atomic_obligations`：断言拆成 **2 条原子义务**（`audit_report` / `license`）+ 留痕 `AMBIGUOUS_SPLIT` + 义务 ID `X-O1/X-O2` + 共享该段期间 | **WP1(a) 明令「默认选 (a)」**：一段含多类不得整条丢弃（业务事实是 54 条只拆出 7 条，拆解率是本次核心）。**判据未被削弱**：同批新增反例 `test_compound_doc_type_is_not_split_into_two_obligations` 锁住「复合词（员工合同/劳动合同）不拆」，且新文件里 `test_multi_type_segment_splits_into_atomic_obligations_with_separate_pools` 锁住「拆出来的两条义务各自只召回自己那一类材料」（误匹配率不上升） |
| 4 | `backend/tests/test_dd_v1_semantic_retrieval.py:112`（随 #3 连带） | `flags` 是 `dict`（`flags["status"]`） | `flags` 是 `list`（`[f["status"] for f in flags] == ["AMBIGUOUS_SPLIT"]`） | 一个条目可能同时有「拆不出来的片段」与「多类拆分」两种留痕，单个 dict 装不下 ⇒ 返回留痕**列表**。**兼容性**：`split_items` 的返回结构（`(obligations, flags)`）不变，包内 `unsplit_items` 字段**仍只收** NEEDS_HUMAN_SPLIT / PARTIAL_SPLIT（既有断言 `pkt["unsplit_items"] == [{"item_id": "R3", "text": "其他相关材料等", "status": "NEEDS_HUMAN_SPLIT", "reason": "NO_KNOWN_DOC_TYPE"}]`（`:85-86`）逐字未改），新增的 `split_flags` 承载全部留痕 |
| 5 | `backend/tests/test_dd_v1_fos71_t5_six_states_entry.py`（用例改名 ＋ 场景扩充 ＋ 口径改判） | `test_production_reachable_states_measured_three_of_six`：断言 `len(observed) == 3`，docstring 写「生产路径实测可达 3/6」，并把 `NO_MATERIAL` 列为**不可达**，理由是「桥接把义务主体取自有该类型材料的主体 ⇒ 主体非空 ⇒ 候选池非空」 | 改名 `test_production_reachable_states_measured_four_of_six`：**实测**四态（`NO_MATERIAL` / `UNRESOLVED_DOC_TYPE` / `UNKNOWN_ENTITY` / `RETRIEVAL_EXHAUSTED`）并断言**逐项相等**；新增第 4 场景（登记权威主体 ⇒ 主体非空但名下只有别类材料 ⇒ `NO_MATERIAL`）＋「同一库同一清单、只差有没有登记权威主体」的**反差对照**（`UNKNOWN_ENTITY` → `NO_MATERIAL`）＋ `OTHER` 不可达的机械核对 | **旧机制理由已被同一 PR 的桥接层字节证伪**：`dd_v1_bridge_service.build_semantic_obligations` 取到**权威主体**时**不按 doc_type 过滤**（只有另一条「按 doc_type 取卡片推断主体」的路才过滤）⇒「权威主体名下只有别类材料」会走到语义层 else 分支给出 `NO_MATERIAL` ⇒ 该态**在生产路径可达**。★ 旧断言是**一条会误导后人的绿断言**：它绿，是因为它**从不跑**能证伪自己理由的那个场景（登记权威主体），**不是**因为生产路径到不了 `NO_MATERIAL`；独立 Gate 在生产入口实测为 4/6。**产品实现字节未改**（本条只改测试件的口径、机制说明与断言，并另落一个可重跑的运行探针） |

**没有为了让测试变绿而弱化的判据**：改判三处 —— 「类型字面量」「一段两类的处置方向」
与「六态生产路径可达数（3/6 → 4/6）」；前两处都补了**更强**的反向用例，第三处**由实测取代文案**
（并补了反差对照与可重跑的运行探针，判据只会更严不会更松）；其余既有断言（含 `h["R1-O1"] == {"verdict": "MATCH", "files": ["G001","G002"]}`
这种**整字典相等**的断言）**一字未改**仍通过。

---

## 6. 测试基线 → 改动后（可复核）

### 6.1 环境说明（先于代码改动处理的两件事）

1. **`pytest tests/ -q` 首次运行退出码 2（收集中断）**：`tests/test_ui_smoke_gk.py` 需要 `playwright`（仓内 `pyproject.toml` 的
   `dev` extra 声明了它，本沙箱 venv 未装）。处置：`uv pip install --python .venv/bin/python playwright pytest-playwright`
   （**只装仓内已声明的 dev extra**，未执行 `uv sync --all-extras` —— 后者会装 docling，导致 `test_absent_docling_is_detected` 必然失败）。
   装完该文件被收集、且因本机未起服务而 **skip**（不产生失败）。
2. **基线失败 1 条**：`tests/test_doctor_script.py::test_doctor_script_exits_zero`。
   它跑 `tools/doctor.py` 的「本机环境全部检查」，在本沙箱缺 `backend/.env`、前端 `node_modules`、uv 托管依赖 ⇒ 退出码非 0。
   ★ 这与本 PR 无关（**改动前就红**），且**仓内自己的测试命令就排除了它**
   （`AGENTS.md`「测试命令」与个人技能库 `cangjie-fos-project` 均为 `pytest tests/ --ignore=tests/test_doctor_script.py -q`）。
3. **仓内标准命令 `uv run --extra dev <子命令>` 在本沙箱不可执行**：包索引不可达
   （连续两次 `Connection reset by peer (os error 104)`，退出码 2）。
   ⇒ 本轮读数一律改用**复核席同款命令**（`PYTHONPATH=src .venv/bin/python -m pytest <路径>`）：
   同一解释器、同一已装好的 dev extras、**不触网、不改依赖**。
   ★ `backend/uv.lock` **0 改动**（本 PR 未引入任何依赖变化）。

### 6.2 数字（串行单进程，含 ps 证）

★ 取数口径：**同一 checkout 内串行单进程**；`ps` 采样证明除本轮自身进程外无第二个 pytest 主进程；
pytest 版本 **9.1.1**；命令＝复核席同款（§6.1-3 说明为何不用 `uv run --extra dev`）。

| # | 树 / 轮次 | 命令 | 退出码 | 失败 | 失败 ID 全集 | 取数时刻(UTC) | ps 证 |
|---|---|---|---|---|---|---|---|
| R1 | **改动后** · 本分支工作树 | `cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/ --ignore=tests/test_doctor_script.py -q` | **0** | **0** | **（空集）** | 04:46:49Z → 04:55:46Z | 开跑前 `ps`＝0；采样 107 次，pytest 主进程恒为 1 |
| R2 | **改动前** · 独立 checkout（HEAD＝`d9bd8e89c1a35aa7f27893bfcd84be4713cf27d2`，自带独立 `backend/data`） | 同上 | **0** | **0** | **（空集）** | 04:56:11Z → 05:03:44Z | 开跑前 `ps`＝0；采样 91 次，pytest 主进程恒为 1 |
| R3 | 改动后 · 六个相关文件（专项） | `cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/test_dd_v1_fos71_player2_p0.py tests/test_dd_v1_semantic_retrieval.py tests/test_dd_v1_local_run.py tests/test_dd_v1_bridge.py tests/test_dd_v1_packaging.py tests/test_dd_v1_policy_and_entry.py -q` | **0** | **0** | **（空集）** | 05:05:57Z → 05:07:23Z | 开跑前 `ps`＝0；采样 29 次，pytest 主进程恒为 1 |
| R4 | 改动后 · 本 PR 新增文件（专项） | `cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/test_dd_v1_fos71_player2_p0.py -q` | **0** | **0** | **（空集）** | 05:07:23Z → 05:07:34Z | 开跑前 `ps`＝0；采样 4 次，pytest 主进程恒为 1 |

★ **失败 ID 集合差集 ＝ 空集**：R1 与 R2 的失败 ID 集合都是空集 ⇒ **新增失败 0 条**（基线与改动后同口径、同串行条件）。
★ **用例条数（collected）不作为登记项**：pytest 9.1.1 的 `-q` stdout **不打印末尾计数行**
⇒ 按司仓 2026-10-23 口径，**`AGENTS.md` 与本包都不登记 collected 数**（自报数在别的环境不可复现）；
规模可用 `--collect-only -q` 的逐文件求和复核，**权威值以独立复核席在交卷 SHA 上的复跑为准**。
★ 本 PR 新增文件内 `def test_` 计数 ＝ **23**（源级事实，`grep -c 'def test_'` 可复算；**不是** collected 数）。
★ 早前读数（同一 checkout、串行，用于 doctor 对照）：改动前 `pytest tests/ -q` → 退出码 1、失败 1 条
（`test_doctor_script_exits_zero`，环境型既有失败，见 §6.1-2）；改动后同命令 → 退出码 1、**同一条** ⇒ 失败数未新增。
★ 一次**自曝**（并发 ⇒ 假失败）见 §6.3；本表四行全部是**串行单进程**下的读数。

### 6.3 一次**自曝**：两次全量测试并发 ⇒ 假失败（不是本 PR 的回归）

改判过程中，我在**同一个 checkout 里并发跑了两次全量测试**（一次 `pytest tests/ -q`，一次带 `--ignore`），
第二次出现了 `tests/test_p0_retry_eval.py` 的 5 条 **ERROR**（setup 阶段）；
独立复核席那次并发跑也出现了 `tests/test_pipeline_e2e.py::TestPipelineE2E::test_review_api_original_report` 失败。

**机械证**：`tests/test_p0_retry_eval.py` 的 `setup_jobs` 是 **module 级** fixture，直接写
`pitch_jobs` 真实库（`pitch_job_db._db_path()` ⇒ `backend/data/pitch_jobs.sqlite`），
**绕过了 function 级的 `_isolate_db_per_test` 临时库隔离** ⇒ 两个并发套件在**同一个真实库文件**上建同名行
⇒ 撞唯一约束 / 锁；`test_review_api_original_report` 断言 `edited_report is None`，
同样是**跨运行的状态泄漏**（上一轮写下的编辑记录留在真实库里）。

⇒ **处置**：
① 两次并发跑**作废**，改为**串行**、且**基线跑在独立 checkout**（`/workspace/work/fos-base`，自带独立 `backend/data`）；
② **本 PR 的测试数只取串行、无并发污染的那一轮**；
③ 登记为**环境事实**：`backend/tests` 里有 **module 级 fixture 直写真实库**的用例 ⇒
**同一 checkout 内不得并发跑两套全量**（这一条与本 PR 的改动无关，是仓内既有的测试隔离缺口）。

★ 这条也解释了为什么「基线失败数」必须在**同一命令、同一串行条件**下取：并发跑出来的失败集合**不可比**。

---

## 7. 零外部调用 / 零费用 / 零真实材料

- 未调用任何模型适配器：新用例走 `manual`（人工交换）适配器 + **预置合成回放**
  （`--synthetic-replies`，零进程零费用），回贴内容由**规则提示**现场生成，可复现。
- 未读 Gold：未创建、未读取任何 Gold Set 文件；`score` 子命令未参与。
- 仓内新增内容里**没有**真实清单、客户材料、个人信息、密钥：新增用例里的主体名一律是
  `合成法人甲 / 合成法人乙`，材料内容是「合成样例」短文本，且只在 pytest 临时目录生成。
- `--allow-real-material` 只是**代码闸**（材料目录不在仓内 `tests/fixtures` 下时的强制开关）；本轮喂进去的是合成件。

---

## 8. 与派工本冲突 / 需要司仓知道的取舍（以机械证为准）

| # | 派工本写法 | 实测与本 PR 的处置 | 依据 |
|---|---|---|---|
| C1 | 「`pytest tests/ -q` ⇒ 退出码 0」 | 本沙箱恒为 **1**，因为 `test_doctor_script_exits_zero` 要求「本机环境全部检查」通过（缺 `.env` 与前端 `node_modules`），**改动前就红**。仓内 AGENTS.md 与技能库的标准命令本就排除它 | 失败详情见 §6.1；该用例与本 PR 零关系 |
| C2 | 「六种原因：NO_MATERIAL / UNRESOLVED_DOC_TYPE / UNKNOWN_ENTITY / PERMISSION_BLOCKED / RETRIEVAL_EXHAUSTED / OTHER」 | 六个**全部可达并有单测覆盖**。`RETRIEVAL_EXHAUSTED` 的语义按「**没看全 ⇒ 不得断言确实没有**」实现：候选数超 `MAX_FILES_PER_OBLIGATION` 且无可用候选时给该原因（而不是谎称 NO_MATERIAL） | `test_no_candidate_reason_distinguishes_six_states` |
| C3 | 「(a) 拆出的多条义务共享该段期间与附件要求」 | **共享**，但有一条例外：段内无显式年份且该类无年度口径（执照/章程）时取 `CURRENT`。若严格共享（`UNKNOWN`），执照类义务永远匹配不到执照材料 ⇒ **假缺口**（更坏的方向） | `dd_v1_semantic_retrieval_service.py:196-204`（注释 + `ob_period` 赋值）；用例 `test_ambiguous_two_doc_types_in_one_segment_split_into_atomic_obligations` 显式断言该例外 |
| C4 | 「`scaffold` 产出英文 key 与 provenance」 | 已做（`doc_type` + `doc_type_provenance`）。**期间口径**：执照/章程取 `CURRENT`（无年度口径），文件名里的年份是**签发年**不是材料期间 ⇒ 不写入 `period`；「2022 版执照 vs 2024 版执照」的区分靠**版本维度**（`version_status`），而 `scaffold` 目前只认「草稿/征求意见」⇒ 这一点是**已知缺口**，留给 §9 | `tools/dd_v1_local_run.py:182` |
| C5 | 「必须员工走正式入口也能用上修复成果」 | 已做：`scaffold`/`split`/`run` 三个子命令全部走新的类型口径与新的拆分逻辑；新用例 `test_full_synthetic_chain_to_authorized_package` 就是**从 `scaffold` 起**跑完整链 | — |
| C6 | 「`scaffold` 主体用 `--entity`」 | 保持不变（**单主体**）。多主体库要走桥接链（认知卡 + 权威名单归一）或人工分批；本次只修类型口径，不改主体的来源。多主体隔离由**证据过滤**保证（用例覆盖） | 派工本未要求改主体来源 |
| C7 | 「六态原因：NO_MATERIAL / UNRESOLVED_DOC_TYPE / UNKNOWN_ENTITY / PERMISSION_BLOCKED / RETRIEVAL_EXHAUSTED / OTHER」 | 六态**全部可区分**（语义层六个分支都齐备），但**生产路径上只有 4/6 可达**：不可达的是 `PERMISSION_BLOCKED` 与 `OTHER` 两态。`PERMISSION_BLOCKED`：meta 的 `access` / `restricted` 是**留出的扩展点**，仓内两个 meta 生产者（桥接链 `build_meta`、入口 B `scaffold`）**都不写**这两个字段。`OTHER`：兜底分支要 `read_errors>0`，而生产路径在 `local_material_snapshot` 就把缺文件拒掉了。本 PR **不假装已接线**（代码 docstring、`NO_CANDIDATE_REASONS` 注释、测试 docstring 三处都写明）。**为什么不接敏感等级**：策略默认把 10 类里的 9 类定成 `RESTRICTED`，若按敏感等级过滤证据池 ⇒ 绝大多数材料对模型不可见 ⇒ 复核覆盖面塌陷；受限材料的**披露**闸在 `dd_v1_policy_service`（外发口径），不在证据召回口径。★ **`NO_MATERIAL` 在生产路径是可达的**（不是缺口）：桥接层取到**权威主体**时**不按 doc_type 过滤** ⇒ 主体名下只有别类材料时给出 `NO_MATERIAL`（详见 §5 第 5 条） | `_access_blocked` 的 docstring（已写明）＋ 独立复核席的机械证（两处生产者都不写该字段）＋ 六态可达性运行探针 `tools/dd_v1_six_state_reachability_probe.py`（实测 4/6） |
| C8 | 「(a) 一段多类 ⇒ 按类拆成多条原子义务」 | 拆的**触发条件**写成可复核的规则：**两次类型命中之间有间隔，且间隔不是「纯汉字连接」** ⇒ 拆；**紧挨着**（如「员工合同」）或**纯汉字连接**（如「甲公司营业执照」）⇒ 判复合词 ⇒ **不拆**。含**年份/非汉字**的间隔（如「审计报告2024年营业执照」）⇒ 拆。★ 这条规则经独立复核席指出边界后**收紧过一次**（初版只认标点分隔符 ⇒ 漏掉带年份的间隔），已补正例与反例 | 独立复核席的机械证 → 本 PR 改 `_is_separable_gap`（`backend/src/cangjie_fos/services/dd_v1_semantic_retrieval_service.py`）+ 新增 2 条用例 |

### 已知缺口（如实登记，不藏）

| # | 缺口 | 影响 | 现状 |
|---|---|---|---|
| G1 | `PERMISSION_BLOCKED` 无生产者 | 该状态在生产路径下不可达（**不可达两态之一**） | **扩展点**，已三处写明；未接线的原因见 C7 |
| G2 | `scaffold` 仍是单主体（`--entity`） | 多主体库需走桥接链或人工分批 | 派工本未要求改；证据过滤的主体隔离已覆盖 |
| G3 | `scaffold` 的 `version_status` 只认「草稿/征求意见/draft」 | 认不出「被取代版本」⇒ 同类型多版本的先后关系仍要人工/卡片补 | 已知；`rule_hint` 的 `OUTDATED` 仍能区分「非现行有效」 |
| G4 | 语义层归一后的主体与 R4 结构层的**逐字**主体比较之间有口径差 | 归一后能召回，但字面不同仍会被 R4 拦下 | **更严**的方向（双保险），未改 |
| G5 | 多类型段：组包链按**整段的类型归属**给材料定类型 ⇒ 段内**可外发类**的材料被归到同段的**另一类** ⇒ 授权组包取不到它 | 该材料被披露策略闸拦下（**fail-closed**：无越权外发 ⇒ 非安全缺陷）；该段其余材料一并受影响 | **既有缺陷、本 PR 未引入**（改动侧与基线侧跑同一条组包链，`exported` / `blocked` 逐字相同）；成因在组包链的整段定类型逻辑，**不在本 PR 改动面**（组包服务未改）；留给后续单独修 |
| G6 | `OTHER` 无生产路径触发条件 | 该状态在生产路径下不可达（**不可达两态之一**） | 兜底分支要 `read_errors>0`（读材料抛 `OSError`）；生产路径在更早的闸口就拒了（`local_material_snapshot` 先校验文件存在 ⇒ 缺文件直接 `FileNotFoundError`；`PermissionError` 又被语义层原样上抛不计数）⇒ `read_errors` 恒 0 |

★ **生产路径可达态数：实测 4/6**（`NO_MATERIAL` / `UNRESOLVED_DOC_TYPE` / `UNKNOWN_ENTITY` /
`RETRIEVAL_EXHAUSTED`），不可达 2/6（G1 + G6）。
★ 该口径由**同一 PR 的独立 Gate** 在生产入口实测复核，并落成**可重跑的运行探针**：
`tools/dd_v1_six_state_reachability_probe.py`（跑一次即自证；口径或生产接线一变就红）。
★ **口径更正留痕**：本包此前只登记 `PERMISSION_BLOCKED` 一态不可达（等于 5/6），
而测试件自称 3/6 —— 两处互相矛盾。现按实测统一为 **4/6**；
`NO_MATERIAL` **不是**缺口，它在生产路径**可达**（理由见 C7 与 §5 第 5 条）。

---

## 9. 留给刘江 Windows 复测 / 未验证 / 未合并的事项

1. **未合并、未进 master**：本 PR 只开不开合；master tip 仍是 `d9bd8e89c1a35aa7f27893bfcd84be4713cf27d2`。
2. **Windows 复测清单**（本轮全部在 Linux 沙箱跑的，Windows 上需复跑）：
   - `cd backend && uv sync --extra dev`（**不要 `--all-extras`**，会装 docling）→ `pytest tests/ --ignore=tests/test_doctor_script.py -q`
   - `uv run python tools/dd_v1_local_run.py scaffold --material-root <本地材料目录> --out meta.json --entity <法人名>`
     ⇒ 检查 `meta.json` 里 `doc_type` 是英文 key、`doc_type_provenance` 是 `INFERRED`/`UNKNOWN`；
   - `uv run python tools/dd_v1_local_run.py split --items items.json --out obligations.json`
     ⇒ 检查 `needs_human_split` 与 `ambiguous_splits` 两个字段；
   - `uv run python tools/dd_v1_local_run.py run --material-root <本地材料目录> --meta meta.json --items items.json --obligations obligations.json --out result.json`（**真实材料必须本机 `--allow-real-material`**，勿外发）。
3. **未验证的事项**：
   - **真实材料库**上的实测（目录污染、十年期归档结构、非中文文件名）—— 本轮只用合成材料；
   - **模型实际表现**（拆解率提升后，模型在多类型义务上的判准率是否变化）—— 本轮零模型调用；
   - **前端**未触碰（`frontend/` 一行未改）。
4. **已知缺口（不在本次范围）**：
   - `scaffold` 仍是**单主体**（`--entity`）；
   - `scaffold` 的 `version_status` 只认「草稿/征求意见/draft」，**认不出「被取代版本」** ⇒ 同类型多版本的先后关系仍要人工/卡片补；
   - 语义层归一后的主体与 **R4 结构层**的**逐字**比较之间存在口径差（归一后能召回，但字面不同仍会被 R4 拦下）—— 这是**更严**的方向，属双保险，未改。
   - **「义务侧主体为空 + 材料侧主体也为空」仍按旧口径池化**（两侧都空 ⇒ 相等 ⇒ 能召回）。本轮**未改**这一既有语义：改它会让桥接链里「主体未知材料」的证据变空（那是另一个口径问题）。因此 `UNKNOWN_ENTITY` 原因出现在「义务侧主体未知、且没有主体同样未知的材料」时。

---

## 10. Skills 复盘

见 `SKILLS-REVIEW.md`（含检索项数、命中项数、实际复用项数、新增候选、升级、独立验证、跨端加载成功的逐项数字）。

---

## 11. 工件（锚点表：路径 ＋ 字节数 ＋ sha256 ＋ 取数时刻；代码工件另附 git blob 全串）

本目录工件：`CALLCHAIN-BEFORE-AFTER.md`（修复前后调用链对照，含行号）、
`TEST-EVIDENCE.md`（逐条验收证据）、`SKILLS-REVIEW.md`（Skills 复盘）、
`SHA256SUMS`（本包工件的 sha256 清单，**不含自身行**；仓库根执行
`sha256sum -c docs/dd-v1-fos71/player2-p0-fix/SHA256SUMS` 逐行校验）。
代码工件：`backend/src/cangjie_fos/services/` 下的 `dd_v1_requirement_service.py`、
`dd_v1_doc_type_service.py`、`dd_v1_semantic_retrieval_service.py`、`dd_v1_bridge_service.py`，
`tools/dd_v1_local_run.py`，`backend/tests/test_dd_v1_fos71_player2_p0.py`（新增），
`backend/tests/test_dd_v1_semantic_retrieval.py`（改判 2 处断言 ＋ 新增 1 条反例用例）。

★ **取数口径**：sha256 ＝ 64 位十六进制全串；git blob ＝ 40 位（git 对象 id，与提交后 tree 内逐位一致）；
字节数与 sha256 为**本轮一次现读**的同一份字节；取数时刻为 UTC。

取数时刻(UTC)：2026-10-24T03:10:58Z
★ **本表重取说明**：本表 13 行于 2026-10-24T03:10:58Z 按现读基座 commit（`973b8eee813a386c8f52925bf6b88374424f71d0`）的树逐行重取 —— 7 行（行 4／5／6／7／9／12／13）的字节数／sha256／git blob 随 R2／T3／T5 并线而变更，其余 6 行重取后与原值逐位相同（字节自 2026-10-23T05:08:37Z 起未变）；行 13 记的是**本笔刷新后**清单的字节身份（清单不含自身行、亦不含本文件行 ⇒ 引用方向单向、无哈希环）。★ 本表口径与判据语义未改，行集合与列集合未改。
| # | 路径 | 字节数 | sha256（64 位全串） | 取数时刻(UTC) | git blob（40 位全串） |
|---|---|---|---|---|---|
| 1 | `docs/dd-v1-fos71/player2-p0-fix/CALLCHAIN-BEFORE-AFTER.md` | 7904 | `47dbf525824e01552044cd26cf16db33427e83e3416a744c4df4cccb5826b0a3` | 2026-10-24T03:10:58Z | `01306192756baa666c117dcbf21361efcd45aa74` |
| 2 | `docs/dd-v1-fos71/player2-p0-fix/TEST-EVIDENCE.md` | 12778 | `17a6129fe60868eddae45021fbb0c4ecbc6d15c9b45cac79ec9a30b2aeb56d12` | 2026-10-24T03:10:58Z | `6efd3bba842513fac1ddf308bde744a0b947a069` |
| 3 | `docs/dd-v1-fos71/player2-p0-fix/SKILLS-REVIEW.md` | 7025 | `34d60e0a50a9295f5d115ee5e68c67ad07ee8c498708176ac926de5657b8716d` | 2026-10-24T03:10:58Z | `6b43f566162b1ce57dbaaeb8cc13fe250056f25e` |
| 4 | `AGENTS.md` | 23111 | `86e3e98161b1083420644c0fe3f60e965236c0bcd7a773d80d9a6a9454c403bf` | 2026-10-24T03:10:58Z | `ab727fe27555cf9a9b2304fa233897e38aade4b0` |
| 5 | `CHANGELOG.md` | 110002 | `06e8e0de8be7f3b8506fb89b65de1d097ed135b87bc90ede9f64313fc164ed1a` | 2026-10-24T03:10:58Z | `fef918cbced0112d11864640ba2d6d3899e3b1d6` |
| 6 | `backend/src/cangjie_fos/services/dd_v1_bridge_service.py` | 24513 | `baa54531b431b8be3baa389dc1b1025fef69e11af8d2581e1db32e8be7c9a3d3` | 2026-10-24T03:10:58Z | `3d23ab078eb72f4c83b5a65d5aaafe34505afdb0` |
| 7 | `backend/src/cangjie_fos/services/dd_v1_doc_type_service.py` | 10969 | `d107573b7d9c2eeee05e0708a55a7458b36d1645b77ebd973aa2d1c4d477d0ba` | 2026-10-24T03:10:58Z | `e2847ad6d58b9a7914092f5fab1daa498a92aaea` |
| 8 | `backend/src/cangjie_fos/services/dd_v1_requirement_service.py` | 52618 | `82e6217613a1fce08f00d52284030cbde8aa8e3d373b57dd6ed6583cda23515b` | 2026-10-24T03:10:58Z | `eccb7dfe844cf96db88c125b20c786057488f92c` |
| 9 | `backend/src/cangjie_fos/services/dd_v1_semantic_retrieval_service.py` | 55724 | `020d2aec4b1529bbfe8e263b6ef65f7026440e16726ffc2889812c8e2e4e11ea` | 2026-10-24T03:10:58Z | `63d13d1f001f64520d35f5d903087e0cfdffe76b` |
| 10 | `backend/tests/test_dd_v1_fos71_player2_p0.py` | 46800 | `83069a64092c296a7e3391a07f4d1f67df18783e32d328c0cb1907fcdcb8f94e` | 2026-10-24T03:10:58Z | `4ef15e1aac72d96027cab5320ca293d8f5f4c885` |
| 11 | `backend/tests/test_dd_v1_semantic_retrieval.py` | 18657 | `29eccccc662778f4c05c15a0c1f2ed9641655926eddbaff161ab9f3d5815ff2a` | 2026-10-24T03:10:58Z | `7302447e128fa2fe537d12ba26bca132e092e1b3` |
| 12 | `tools/dd_v1_local_run.py` | 30918 | `bd4f5c10ab0e14a865de9bd4b9b4fc81da9f2ae3c0bc1888aef0d09d3b1a27aa` | 2026-10-24T03:10:58Z | `f23f89692879e093c9ffbd9db10b174040796fb1` |
| 13 | `docs/dd-v1-fos71/player2-p0-fix/SHA256SUMS` | 1969 | `a7332caf472006dc67f73800ae418becc7e18822756bc80817c68c5df06c0e5e` | 2026-10-24T03:10:58Z | `bed50588c55a073e60506a9249aec4241d62e298` |

★ **本表不列本文件（`EVIDENCE-PLAYER2-P0.md`）自己的 sha256**：写入即改变字节 ⇒ 恒自指漂移；
本文件的字节身份由**提交后的 git blob 全串**给出（见 PR 正文与交卷回执），可逐位复算。
★ `SHA256SUMS` **不含本文件行**（同一原因：两文件互列哈希会成环）⇒ 本文件由 git blob 全串自证。
