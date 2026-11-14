# EVIDENCE · DD-V1 第三轮 P0（WP3 匹配不完整 ＋ WP5 真实交付链）

- **subject_id**：DD-V1-FOS71/R3-P0
- **分支**：`feat/71-player2-p0-fix-20261023`（**快进**，非 force；未推 master、未合并任何分支）
- **基座**：`7dd66b00149883efe1abdb63d647012211531800`（第三轮 P0-3 落点）
- **作者**：云端 MiniMax Executor（**唯一 Writer**）｜**自查，不是独立验收**（验收由独立 Reviewer 做）
- **纪律**：0 读 Gold Set（`gold.json` / `frozen/grader/`）、0 引入真实业务材料、
  0 改尺子（`GOAL-CONTRACT.v3.8.json` / `MINIMAX-INDEPENDENT-SUPERVISOR.md`）、
  0 改 Issue #71 的 AC、0 改既有测试文件、0 force push / amend / rebase。

---

## 0. 一句话

第三轮把「**匹配不完整**」的四个登记缺口（主体匹配错误 / 期间判断 UNKNOWN /
多文件候选数量受限 / MISSING 与实际候选池口径不一致）**真正修掉了**，
把「**真实交付链**」的 7 项产出**真正产出**了，
并修掉了独立 Reviewer 实测复现的 P0-3 缺陷（机器重算的等级被记成「事实」
⇒ 第二次类型纠正不再重算 ⇒ 章程这类**按设计收紧**的类型会带着 PUBLIC 被外发）。

---

## 1. 本轮改了什么（按 WP 归位）

### WP3-a 主体（四川母公司 vs 子公司不能混桶）

| 改点 | 文件 | 说明 |
|---|---|---|
| 主体归一取代**路径子串兜底** | `dd_v1_match_service.py`（`resolve_card_subject` / `_subject_clues`） | 旧实现拿 `card.entity + rel_path + title` 拼 blob 再看登记全称 `in blob` ⇒ **子公司目录名里含母公司名就命中**。现在主体一律走 `dd_v1_entity_service.match_entity`（**归一后逐字相等** / 已登记别名），**不做子串匹配** |
| 主体线索按**具体度**排序 | 同上（`_subject_clues`） | ① 认知卡 `entity`（父目录名）② 相对路径各级目录名（**从深到浅**）③ 文件名。多级布局「法人/类型/文件」时，认知卡取到的是**类型目录**，主体要从更浅的一级找（否则主体永远判「未登记」） |
| 主体四态 | 同上（`SUBJECT_MATCHED` / `OTHER_LEGAL` / `UNREGISTERED` / `NO_CONSTRAINT`） | 「**另一个已登记法人**」与「**认不出**」分开：前者是**主体不一致**，后者是**不可判定** |
| 主体不一致 ⇒ 不得 MATCHED | 同上（`judge`） | 仅当**本义务要求的主体本身没被覆盖**（`ent_cov < 1`）且候选里那些别的法人的材料**类型/期间都对得上**时改判 `UNCERTAIN`；主体已覆盖时**只留痕**（不得把已齐备的义务打成 UNCERTAIN） |

★ **没有新造主体表**：口径全部走 `dd_v1_entity_service`（登记全称 + 库内别名 + 配置文件别名）。

### WP3-b 期间（2024 不得顶替 2025；无期间不得臆造年份）

| 改点 | 文件 | 说明 |
|---|---|---|
| 判定层接进**期间四态** | `dd_v1_match_service.py`（`evaluate_file` → `ps.compatibility`） | 旧实现是 `y_from <= int(pv) <= y_to`（**字符串比字符串**）：材料**自身无年度标注**时 `per_ok=0` ⇒ 被当成「不满足」；`int(pv)` 还有**非数字即崩**的风险。现在走 `dd_v1_period_service.compatibility`（`MATCH` / `MISMATCH` / `UNVERIFIABLE` / `NOT_A_CONSTRAINT`） |
| 期间**不可判定** ⇒ UNCERTAIN | 同上（`judge`） | 义务锚定了期间、候选的主体/类型都对得上、但材料**自身无年度标注** ⇒ **不得**说「不满足」（那是猜），**不得**说「它就是那一年的」（那是臆造年份）⇒ 判 `UNCERTAIN` |
| 锚点来源 | `dd_v1_period_service`（**未改**） | 显式配置 > 原文声明 > 材料自身年度；**禁系统时间**（模块自带 `assert_no_system_clock` 自证） |

### WP3-c 多文件（应交 3 / 找到 2 / 缺 1）

| 改点 | 文件 | 说明 |
|---|---|---|
| 必备 **part**（正文之外的组成部分） | `dd_v1_requirement_service.py`（`parse_required_parts` / `required_parts_of`）＋ `dd_v1_card_service.py`（`derive_part` / `card_part`） | 「审计报告（含附注）」⇒ 要求 `附注` 这一 part ⇒ 应交 **正文 ＋ 附注**两件。part 与**份数**是**两条轴**（份数＝一式几份；part＝一件里几部分） |
| part 口径**全仓一份** | `dd_v1_bridge_service.py` 改为复用 `dd_v1_card_service.derive_part` | 桥接层不再自己写一份 part 规则 |
| **应交 / 找到 / 缺** 显式三段式 | `dd_v1_package_service.py`（`_count_reading`）＋ 核对表新增四列 | 「找到」的口径＝ **对得上**（主体/期间/类型都对得上）的件数，**不是**「已选中」——两者混在一起会得出「齐备」却一件都交不出去的自相矛盾结论；「可交付」**单独报** |
| 找到 1 份**不得**判完成 | `dd_v1_match_service.judge`（`qc.count_dimension` 已是门槛语义）＋ 份数维缺口指名 | 「应交 3 / 找到 2 / 缺 1」时判定**不得**是 `MATCHED` |
| 缺 part ⇒ 不得 MATCHED | `dd_v1_match_service.judge` | 找到正文**不等于**这条完成 |

### WP3-d 候选截断（**不静默漏检**）

| 改点 | 文件 | 说明 |
|---|---|---|
| 规则路径显式报数 | `dd_v1_match_service.py`（`_recall_candidates` 返回截断**真数**；`judge` / `match_library` 透出）＋ `tools/dd_team_channel.py` | 终端多一行「实际考察候选 N 份｜触顶义务 M 条｜被上限挡掉 K 份」；触顶时每条义务的 `missing_detail` 里写「**已达候选上限 X，还有 N 份候选未看**」 |
| 语义层（DSH 路径）显式报数 | `dd_v1_semantic_retrieval_service.py`（顶层 `candidate_cap` / `candidate_truncated` / `truncated_candidate_count` / `candidate_cap_note`）＋ `dd_v1_bridge_service.py`（`evidence_status` 透出 ＋ `warnings` 告警） | 旧实现把截断数**只**记在 `diagnostics` 里、且候选 ≥ 上限时 `candidate_status` 仍报 `OK` ⇒ **用户侧看不到**「已达上限」 |
| 组包返回值截断**必须报数** | `dd_v1_package_service.py`（`blocked_total` / `blocked_shown` / `blocked_truncated` / `blocked_truncation_note`，`gate_blocked_*` 同构） | 完整明细**本来就落盘**（`被拦截清单.json` / `未过闸明细.json`），返回值只给前 20 条预览，但**必须**说清还有多少没显示 |

★ **停止条件（可解释）**：候选池先按「同主体 ＋ 同材料类型」过滤，
再按「期间对得上 → 依据不足 → 已知冲突 → 现行有效 → `file_id` 升序」排序，取前 N 份
⇒ 触顶时丢的是**排序靠后**的，不是随机丢的。

### WP5 真实交付链（7 项产出，缺一不可）

| # | 产出 | 实现 |
|---|---|---|
| ① | `01-输入需求清单.tsv` | 每条原子义务：机构编号 / 原文 / **义务稳定ID** / 主体 / 期间 / 类型 / 应交 / 找到 / 缺 / 交付闸 |
| ② | `02-检索材料清单.tsv` | 每份候选：file_id / **原始路径 / 文件名 / SHA256 / 主体 / 期间 / 类型**（WP1 六件套）/ 被几条义务引用 |
| ③ | `03-匹配结果及理由.tsv` | 每条义务 × 每份候选：判定 / 三维匹配 / 匹配证据 / 选中与否 / 理由 / 审核结论 / 交付位置 |
| ④ | `04-缺失冲突不确定清单.tsv` | 缺失 / 冲突 / 不确定 / 不完整 / 过期 / 受限，逐条带缺口明细与候选数 |
| ⑤ | `05-人工审核记录.tsv` | 单据批准人 / 逐条确认（谁 + 理由）/ 修改留痕 |
| ⑥ | `06-实际交付文件目录.tsv` | 每个交付文件：相对路径 / 字节数 / SHA256 / 源 SHA256 / 一致与否 / 对应义务ID |
| ⑦ | `07-文件完整性校验结果.tsv` | **逐件复制后读回复算**的 SHA256 vs 源 SHA256 |

**追溯链**：`组包manifest.tsv` 每行给出
**原始材料（路径 + file_id + 源 SHA256）→ 匹配义务（义务ID + 原子义务）→ 审核结论（判定 + 交付闸）→ 交付位置（交付路径 + 副本 SHA256）**。

★ **未获有效审核授权时**：只产出 ①–⑤ ＋ 候选验证信息（在**候选包**目录），
**不生成正式交付件**、**零复制**（`build_review_pack` 不碰材料源文件）。

### WP1 剩余

| 改点 | 说明 |
|---|---|
| 义务**稳定 ID**（`obligation_key`） | `rq.obligation_key(library, institution, item_no, raw_text, seq, obligation)` —— **由内容算出**、可复算、不随排序变。独立 Reviewer 拿到 (库/机构/编号/原文/段序) 就能复算同一条义务的 key（原来 `obligation_id` 是随机 uuid ⇒ 追溯链断在第一环） |
| 候选材料**六件套** | 原始路径 / 文件名 / SHA256 / 主体 / 期间 / 类型（`02-检索材料清单.tsv`、`交付清单与hash核验.tsv`、`组包manifest.tsv` 三处都带） |
| **复制后逐件复算** SHA256 | `package_approved` 里 `dest_sha256 = _sha256(dest)`（**读回副本重算**）＋ `07-文件完整性校验结果.tsv` 独立一列；`SHA256SUMS` 可 `sha256sum -c` 直接核 |

### WP2 剩余

| 改点 | 说明 |
|---|---|
| **审核失效**（材料在审核后被改过） | `package_approved` 复制**之前**先跑 `_stale_materials` 预检：此刻重算源文件 SHA256，与扫描时记在 manifest 的 `content_hash` 比对 ⇒ 不等 ⇒ **审核失效**：本单打回 `reviewed`、**零复制**、**不产出正式交付件**、写「审核失效清单.tsv」 |
| 候选包与正式交付包**物理隔离** | 候选包 `<data_dir>/reviews/<review_id>/`；正式交付包 `<data_dir>/deliveries/<review_id>/`（**平级**，不是父子）。显式传入落在候选包目录内的输出目录 ⇒ **拒绝组包** |
| 各自**明确标识** | 候选包：`非正式交付-候选包说明.md`；正式包：`正式交付包-说明.md` |

### WP4 剩余（P0-3 缺陷 · 独立 Reviewer 实测复现）

| 改点 | 说明 |
|---|---|
| 机器重算的等级 provenance ＝ **INFERRED** | 旧实现写 `FACT` ⇒ 第二次类型纠正被当成「人工自定」⇒ **不重算** ⇒ 陈旧等级存活 |
| 重算触发条件 ＝ **类型一变就重算** | 判据从「`provenance == FACT`」改成 **`_human_override()`**（provenance=FACT **且**证据带 `human_override`）——「人工自定」的定义只有这一处 |
| 重建认知卡时按**生效类型**重算 | `build_card` 的等级计算改用「机器命中的类型 ∪ **人工改写的类型**」；人工的**多值** `doc_types` 也一并恢复（否则类型闸在重建后又变回机器认错的那一类） |
| 每次放行/拦截都留**规则依据** | 放行侧也记披露四方归因（`披露归因_谁拦的` / `拦的性质` / `理由` / `敏感等级` / `策略版本` / `可外发类型` / `逐份授权`） |

★ **明确没有做的事**：`sendable_doc_types` **仍只有 license**、章程**仍** RESTRICTED、
敏感等级不明确**继续**默认拒绝、**没有**新增第二套类型表 / 尺子 / 主体表。

---

## 2. 红绿对照（修前 = `7dd66b00`，修后 = 本轮 sha）

### 2.1 本轮新增的 8 条专项测试（`backend/tests/test_dd_v1_ddv1_p0_round3.py`，18 条）

| 侧 | 命令 | 读数 |
|---|---|---|
| **修前**（`7dd66b00`，git worktree 独立检出） | `cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/test_dd_v1_ddv1_p0_round3.py -p no:cacheprovider -q` | **12 failed / 6 passed**，exit=1 |
| **修后**（本轮工作树） | 同上 | **18 passed / 0 failed**，exit=0 |

**修前红的 12 条（逐条 ID）**：

```
test_01_single_entity_single_file_end_to_end
test_02_multi_entity_must_not_cross_mix
test_04_multi_file_requirement_shows_expected_found_missing
test_04b_requirement_with_attachment_part_shows_two_pieces
test_05_missing_material_is_reported_as_missing
test_07b_candidate_pack_and_official_pack_are_physically_isolated
test_08_mixed_disclosure_levels_block_by_design_with_rule_trace
test_09_material_changed_after_review_invalidates_it
test_10_obligation_key_is_stable_and_recomputable
test_11_candidate_keeps_six_pieces_of_identity
test_12_repeated_type_correction_recomputes_level_again
test_13_machine_recomputed_level_is_inferred_not_fact
```

★ 其中 `test_12` / `test_13` 是**独立 Reviewer 的放行条件②**要求的
（「连续两次类型纠正 ⇒ 等级随最新类型重算」＋「机器重算的等级 provenance 必须是 INFERRED」）
⇒ **修前必红、修后必绿**（修前红的断言消息见 §2.3）。

### 2.2 上一轮三个 P0 测试文件（**未改动任何一个字节**）

```
tests/test_dd_v1_p0_delivery_gate.py
tests/test_dd_v1_p0_match_evidence.py
tests/test_dd_v1_p0_disclosure.py
```

修后：**35 passed / 0 failed**（与基座读数一致）⇒ 本轮**没有**动上一轮的三道闸。

### 2.3 修前红的**断言消息**（可逐字复核）

- `test_12`：修前 `node2.value` ＝ `"PUBLIC"`（第二次纠正**没有**重算）
  ⇒ 断言消息「第二次类型纠正没有重算等级（陈旧等级存活）」；
- `test_13`：修前 `node.provenance` ＝ `"FACT"`
  ⇒ 断言消息「机器重算的等级被记成 'FACT'（应为 INFERRED）」。

---

## 3. 全量回归读数

| 侧 | sha | 命令 | 读数 |
|---|---|---|---|
| 修前（基座） | `7dd66b00` | `cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/ --ignore=tests/test_doctor_script.py -p no:cacheprovider -q` | 6 failed / 1857 passed / 5 skipped / ERROR=0（父席与独立 Reviewer **各自独立**跑出，**逐位相同**） |
| 修后 | 本轮 sha | 同上 | 见 `PR comment`（**失败用例 ID 集合与修前逐字相同** ⇒ **零新增回归失败**） |

★ `tests/test_doctor_script.py` 按**仓规**排除（需本机 `.env` 与前端 `node_modules`）
⇒ **不算作「通过」**，如实登记。
★ 那 6 条失败**全部**是「缺 `OPENAI_API_KEY`」的**既有环境失败**
（`test_dd_material_architecture` ×4 ＋ `test_dd_redteam` ×2），
**不是代码缺陷、不是本轮引入**。

---

## 4. 合成交付包（本目录 `交付包-合成样例/`）

- **素材**：仓内 **A4 合成集**（`backend/tests/fixtures/dd-v1-fos71-a4/material`，8 份材料）
  ＋ `raw_items.json` 的 8 条清单 —— **零真实材料**；
  ★ **未读** `gold.json` / `frozen/grader/`（禁读 Gold Set）；
- **跑法**：`tools/dd_team_channel.py run --library 合成库R3 --root <A4 material>
  --checklist <清单.tsv> --institution 案例甲机构 --anchor-year 2024
  --package --approved-by <批准人> --package-out <交付目录>`；
- **判定分布**：`CONFLICT 6 / MATCHED 2`；**复制原件 1 件**；**逐件复算 1/1 通过**；
- **独立复算**：`sha256sum -c SHA256SUMS` ⇒ `OK`；
  Python 独立复算读回副本字节 ⇒ 与 `SHA256SUMS` **逐位相同**。

★ **一条操作坑（如实登记）**：清单摄取是**幂等**的（同一份清单重复摄取**不产生**重复义务）
⇒ **主体登记必须发生在清单首次摄取之前**；事后再登记主体，**已入库的义务不会重解析**
（`entity_scope` 仍是空 ⇒ 主体维度判「无法判定」）。
⇒ 刘江侧的正确顺序：**登记主体 → 再摄取清单**（见 `WINDOWS-HANDOFF.md` §0 的 ③④）。

---

## 5. Skills 栏

见 `PR comment`（**不自动合入**个人技能库；可复用经验先写成交卷件里的候选）。
