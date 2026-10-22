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
