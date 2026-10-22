# F2 · 主体指名范围 —— 前缀抽取失败时回落查权威名单（MAJOR 修正包）

> **分支**：`feat/71-a3-f2-subject-scope`（基线 `feat/71-a3-closeout` @ `90b1676`）
> **白名单**：本包**只改** `backend/src/cangjie_fos/services/dd_v1_requirement_service.py` + 新增 1 个测试文件。
> **判据条文**：零改动（A2/A3 判据一字未碰）。
> **纪律**：全部合成材料 · 零外部模型 · 零付费 · 未读 Gold · 未读真实材料库 · 未改披露策略。

---

## 1. 病：主体指名只认一种形态

`dd_v1_requirement_service.parse_entity_scope()` 的主体指名靠两样东西：

| 口径 | 规则 | 来源 |
|---|---|---|
| 文本前缀 | `^\s*([^：:]{2,12})\s*[：:]` 取冒号前缀，且前缀**必须含**标记词 | `_SUBJECT_HINT_RE` / `_SUBJECT_HINT_MARKERS` |
| FACT 范围 | 「集团及下属公司 / 各全资子公司 / 母公司 / 自身」 | `_SCOPE_*` 正则 |

⇒ **两种常见形态都抽不出** ⇒ `entity_scope` 为空 ⇒ 主体维度**永久不可判定** ⇒ 判 `UNCERTAIN`：

| # | 形态 | 例子 | 谁先发现的 |
|---|---|---|---|
| ① | **主体在句中、原文无冒号** | 「提供甲科技有限公司 2024 年度审计报告」 | ★ **司仓用本仓合成 fixture 独立复现**（不是监工提的） |
| ② | **有冒号但主体名不含标记词** | 「甲科技：提供营业执照」 | ★ 独立监工第 35 轮已独立复现 |

★ **主体名再规范也救不了形态 ①**：「有限公司」在标记词表里，但抽取器**先要冒号**。
★ **别名登记救不了**：失败发生在**抽取阶段**，压根没进查表路径 ⇒ 「登记了别名也没用」。

## 2. 复现（司仓自己跑的，真实产品入口）

`/Users/mac/.minimax/sessions/.../workspace/gm_a3c_seven_item_bundle.py`
（走 `tools/dd_v1_manifest.py` 的真实 7 步链，材料取自**本仓**
`backend/tests/fixtures/dd_v1_fos71/`，隔离数据目录 `/tmp/a3c_7item/data`）。

| 义务原文 | 修复前 `entity_scope` | 修复前判定 | 修复后 `entity_scope` | 修复后判定 |
|---|---|---|---|---|
| S1 提供示例科技有限公司 2024 年度审计报告 | `""`（空） | **UNCERTAIN** | `entity_hint:示例科技有限公司` | **RESTRICTED** |
| S2 提供示例科技有限公司营业执照副本 | `""`（空） | **UNCERTAIN** | `entity_hint:示例科技有限公司` | **MATCHED** |
| S3 提供示例科技有限公司 2024 年社保缴纳证明 | `""`（空） | **UNCERTAIN** | `entity_hint:示例科技有限公司` | **PARTIAL** |

★ 修复后审核包 Excel 的「主体范围」列仍是**脱敏代号** `主体-1`（H-3 不受影响），
「主体覆盖」= 1.00，缺口明细**逐维指名**（「材料类型缺 1/1 份（维度：材料类型）」）。

## 3. 治法（口径：不猜不退化）

前缀口径与 FACT 范围口径**都落空**时，**回落查权威名单/别名表**：

| 规则 | 内容 |
|---|---|
| 词表来源 | 本库登记的**主体全称**（`dd_v1_entities.display_name`）+ **库内别名**（`dd_v1_entity_aliases.alias`） |
| 排除 | **DIRECTORY 型别名**（材料分类目录）—— 分类目录是分类维度，不是主体标识（与 F1 产品侧守卫同一口径） |
| 排除 | 配置文件别名 —— 不是**本库**的权威名单 |
| 匹配 | 只认**逐字出现** ⇒ 认不出还是认不出（不模糊、不语义猜） |
| 择一 | **最长匹配**且唯一才取；同等长度指向**不同主体** ⇒ **不猜**（仍 UNKNOWN） |
| 落库 | 复用 `entity_hint:` 前缀 ⇒ 对外仍是**脱敏标签**，原文不落任何交付面 |
| 顺序 | **文本前缀命中 > FACT 范围 > 名单回落** ⇒ 既有口径**不被削弱** |

★ **不扩标记词表**：标记词是**开放集合**（科技/控股/医药/投资/实业…）⇒ 扩它＝猜。
★ **命中别名时，判定层照常用别名表归一** ⇒ **别名从此才有机会生效**（正是形态 ② 的病根）。

## 4. 改动清单

| 文件 | 改动 | 白名单 |
|---|---|---|
| `backend/src/cangjie_fos/services/dd_v1_requirement_service.py` | 新增 `entity_registry_tokens()` / `entity_scope_from_registry()`；`parse_entity_scope()` 增 `registry` 参数并在**最后**回落；`build_obligations()` 增 `registry` 参数并传递；`ingest_checklist()` 取一次名单并传入（+108 / −4） | ✅ 本修正包授权 |
| `backend/tests/test_dd_v1_f2_subject_scope.py` | **新建**（12 条） | ✅ 可新建 |

★ **未改动**：`_SUBJECT_HINT_RE` / `_SUBJECT_HINT_MARKERS` / `_SCOPE_*` / `entity_scope_value()` /
`entity_scope_label()` / `resolve_entities()` / 判定层任何逻辑 / 披露策略 / 任何既有字段语义。

## 5. 判别力（12 条用例 + 探针 6/6）

`/Users/mac/.minimax/sessions/.../workspace/gm_probe_f2_subject_scope.py`

| 检查 | 结果 |
|---|---|
| BASE（现状）12 条全绿 | ✅ |
| BASE 确实从**本变体副本**加载（pytest 进程内断言） | ✅ |
| OLD（**回退**回落段）必须转红 | ✅ **5 条转红** |
| OLD 确实从副本加载 | ✅ |
| 回退后 SHA256 确实变了 | ✅（`d82aa59c…` → `54c14e28…`） |
| 转红用例覆盖回落路径 | ✅ |

★ 转红的 5 条：`test_inline_subject_without_colon_resolves_via_registry`、
`test_alias_without_marker_word_resolves_via_registry`、
`test_registry_fallback_picks_longest_registration`、
`test_inline_subject_resolves_without_registering_alias`、
`test_fallback_scope_label_is_desensitized`。
★ 回退方式是**删掉回落那一段**（不是改断言）⇒ 严格性未松。
★ 已知坑已避开：`pyproject.toml` 的 `pythonpath=["src"]` 用 `-o pythonpath=` 覆盖；
「模块确实从副本加载」的断言写在 **pytest 进程内**（`pytest_configure` 插件）。

## 5.5 ★ 独立 Reviewer 裁定：第一轮 **FAIL（F-1）** → 修正 → 复裁

<!-- gm-fix-f2-doc-disclose-f1 -->

> **披露口径**：本包**第一轮**经独立 Reviewer 裁定为 **`VERDICT: FAIL`**（F-1 · MAJOR）。
> 下面是**那一版的原文问题**与修正，**不得**只登记修正后的读数。

### F-1（假 MATCHED）：名单回落口径**跨片段继承**

**病**：A2（G-A2-11 11d）的「前缀传播」机制把**第 0 片段**的主体口径继承给同项其它片段。
我给 `parse_entity_scope()` 加了名单回落之后，第 0 片段**也可能**产出 `entity_hint:`
⇒ **回落口径被跨片段继承** ⇒ 覆盖其它片段**自己的 FACT 范围**：

| 输入（清单项） | 基线 | 第一版修正包（**被判 FAIL**） |
|---|---|---|
| `甲公司提供营业执照、各全资子公司提供审计报告` | 片段2 = `subsidiaries`/**FACT** | 片段2 = `entity_hint:甲公司`/**INFERRED** ❌ |

**端到端后果**（Reviewer 实测，真实产品管线 + 合成材料）：
`甲公司提供2024年度审计报告、各全资子公司分别提供2024年度审计报告`
（库内只有母公司的审计报告）⇒ 基线 `need_entities=2`、判 **PARTIAL**；
第一版修正包 `need_entities=1`、判 **MATCHED**
⇒ 两条子公司的缺失报告**不再被要求** ⇒ **假 MATCHED**。

★ 我第一版的用例 `test_fact_scope_wins_over_registry_fallback` **只覆盖单片段**
  ⇒ 发现不了这个问题（Reviewer 原话：「该用例无法发现此问题」）。

### 修正（恢复 A2 原义，不新增口径）

前缀继承**只继承「文本主体前缀」**：`subject_hint_prefix(parts[0])`，
**不再**用 `parse_entity_scope(parts[0])` 的结果去判断「是不是前缀口径」。

| 口径 | 修正后行为 |
|---|---|
| 文本前缀形态（`<主体>：<要求>`） | 跨片段继承**与 A2 逐字一致**（Reviewer 已实测基线同形） |
| 名单回落 | **逐片段独立**判定，**不跨片段继承** |
| 片段自己的 FACT 范围 | **永远不被覆盖**（回落只在 FACT 之后才生效） |

### 补的守卫（3 条，判别力已实测）

| 用例 | 锁住什么 |
|---|---|
| `test_parallel_fragment_keeps_its_own_fact_scope` | 并列片段自己的 FACT 范围不被回落口径覆盖 |
| `test_prefix_hint_still_propagates_to_parallel_fragments` | A2 的前缀传播行为**一字不变** |
| `test_parallel_fallback_does_not_shrink_subject_dimension` | 端到端：主体维度**不得**被收窄（登记 3 个 subsidiary ⇒ 断言展开成 **3** 个，收窄成 1 就转红） |

★ **判别力实测**：`gm_probe_f1_guard_discriminative.py` —— 回退 F-1 修正 ⇒
**2 条守卫转红**，且「模块确实从副本加载」的断言写在 **pytest 进程内** ⇒ 非假绿。
★ **实测踩到的一个环境坑**：源码副本放 `/tmp` 时，副本会在子进程启动前**被清掉**
  ⇒ pytest 静默回落到基线树 ⇒ **验证无效**（假绿）。
  ⇒ 副本改放**会话工作区**，且加载路径在进程内断言 —— 这条坑已写进探针注释。

---

## 6. 零新增回归（两树全量对跑）

| 树 | commit | 用例总数 | passed | skipped | **failed** |
|---|---|---|---|---|---|
| 基线 | `feat/71-a3-closeout` @ `90b1676` | 1641 | 1629 | 5 | **7** |
| 修正包 | `feat/71-a3-f2-subject-scope` | 1653（**+12** = 本包新用例） | 1641 | 5 | **7** |

★ **失败集合逐字相同**（机器比对）：7 条**全部**是环境性既红
（6 条 LLM-refine 代理缺 `socksio` + 1 条 `test_doctor_script` 缺 `.env`/`node_modules`）
⇒ **新增失败 0 / 消失失败 0**。

## 7. 残留与边界（如实登记）

| # | 事项 | 性质 |
|---|---|---|
| 1 | 回落只认**逐字**出现 ⇒ 义务里写的是**简称**且**没登记成别名**时，仍然抽不出 | 口径边界（**不猜**的代价，已知且可接受：登记别名即可解） |
| 2 | 回落依赖**本库已登记**权威主体 ⇒ 库里没主体时行为与修复前**完全一致** | 设计前提（用例 `test_empty_library_registry_does_not_degrade` 锁死） |
| 3 | 词表**每次摄取取一次**（不是每条义务取一次） | 性能与一致性取舍 |
| 4 | 配置文件别名**不进**回落词表 | 口径边界（配置文件不是本库权威名单） |
| 5 | 本包**不含** A4b 真机盲考证据 | 范围外（HG-08 前置未就绪） |

★ **本包不含任何真实客户标识**：用例一律用「甲公司 / 乙公司 / 丙公司 / 甲科技」等虚构简称。
