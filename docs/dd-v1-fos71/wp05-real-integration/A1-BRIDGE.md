# WP-A1 · 薄桥接线说明（A1-BRIDGE）

> 本文件是 **A1 子包**的接线说明与实测账。
> A1 的 Gate 由**独立 Reviewer** 判定（执行者自报不算验收，HG-07）。
> 配套证据在 `a1-evidence/`，SHA256 清单在 `a1-evidence/SHA256SUMS-a1-evidence.txt`。

## 0. 一句话

**入口 A（规则链）第一次真正把结果送进了语义层**，而语义层的候选证据第一次
以「并列小节」的形式回到入口 A 的报告里——**只作建议，不改任何判定**。

A0 实测的断点（真 trace 统计）：

| 模块 | A0（接线前） | A1（接线后） |
|---|---|---|
| `dd_v1_card_service` | 1828 | 1778 |
| `dd_v1_match_service` | 463 | 97 |
| `dd_v1_manifest_service` | 174 | 145 |
| `dd_v1_policy_service` | 129 | 53 |
| `dd_v1_requirement_service` | 92 | 61 |
| `dd_v1_parser_service` | 44 | 44 |
| **`dd_v1_semantic_retrieval_service`** | **0** | **177** |
| **`dd_v1_agent_result_service`** | **0** | **37** |
| **`dd_v1_agent_adapters`** | **0** | **7** |
| `dd_v1_bridge_service`（新增） | — | 287 |
| `dd_v1_pii_service`（新增） | — | 35 |

（A1 侧数字取自 `a1-evidence/calltrace-bridge.jsonl` + `trace-summary.json`，
由 `summarize_trace.py` 从 trace 里数出来，不是人工读日志。
A0 侧数字取自 A0 的两份 trace，**统计口径一致**。）

## 1. 接线图

```
入口 A  tools/dd_team_channel.py run
   │
   ├─ ① 建库 → ② 扫描 → ③ 读正文 → ④ 认知卡 → ⑤ 拆义务 → ⑥ 四维匹配   ← 原有 6 步，输出不变
   │
   └─ 附：语义层桥接（新增，**只作建议**）
         dd_v1_bridge_service.bridge_library()
            ├─ build_meta()             清单 + 认知卡 → 语义层 meta（doc_type 取**英文 key**）
            ├─ build_semantic_obligations()  requirement 义务 → 语义义务（**不重拆** + 按主体分簇）
            ├─ sem.build_semantic_packet(..., obligations=[...])   ← 显式传 obligations ⇒ 不走 SPLIT_RE
            └─ 产出：每条义务的候选证据（file_id + sha256 + locator）+ 规则提示
```

## 2. 三处 key 空间必须一致（本包存在的全部理由）

| 位置 | 取值空间 | 不一致的后果 |
|---|---|---|
| 义务 `doc_type`（requirement service） | `_DOC_TYPE_RULES` 的 10 个英文 key | — |
| 桥接产出 `meta[].doc_type` | **同一套 10 个 key** | 语义层 `m.get("doc_type") == ob["doc_type"]` 精确过滤落空 ⇒ **证据池恒空** ⇒ 桥接等于没接 |
| 披露策略 `rules[].doc_type` | **同一套 10 个 key** | 规则永不命中 ⇒ 九类材料全部可外发（**安全洞**） |

10 个 key：`audit_report / financial_statement / tax / license / charter /
capital / resolution / ip / labor / contract`
（来源：`dd_v1_requirement_service._DOC_TYPE_RULES`，**复用，未另抄一份正则**。）

## 3. 本包落地的改动（逐项可核）

### 3.1 披露策略真 key 规则集（G4）

`backend/config/dd_v1_disclosure_policy.json`：`rules` 段由 1 条中文占位串
换成 **9 条真 key 收紧规则**（`license` 故意**不**收紧——营业执照/登记证书/
资质证照/工商公开登记信息是业务口径里唯一可外发的材料类型）。

实测：`a1-evidence/check_policy_g4.py` → **29/29 通过**（license 放行、
九类逐类收紧、空等级/未知等级/空 doc_type/中文 doc_type/扩展名/未知 key/近邻串
全部拒放）。

### 3.2 新增**类型闸** `sendable_doc_types`（策略文件驱动，可选）

**发现**：规则只能「按 doc_type **相等**收紧」⇒ **非空但不在 key 空间内**的
doc_type（中文类型名、文件扩展名、拼错的 key）会**一条规则都不命中**，
直接落回声明级别 ⇒ 若声明 `PUBLIC` 就被放行。这是「不认识就放行」的老坑。

**处置**：策略文件可声明 `sendable_doc_types`（本包声明为 `["license"]`）；
声明后，**只有清单内的类型才可能外发**。

- **向后兼容**：策略文件**未声明该键 ⇒ 行为与引入前完全一致**（有专门用例锁住），
  对 A0 的 1419 条基线**零冲击**；
- **fail-closed**：该键写坏（不是列表 / 含非法元素）⇒ 策略**不生效** ⇒ 全部不可外发；
- 判定顺序：**规则先收紧、类型闸后把关** ⇒ 收紧原因与命中规则照样留痕（可追溯）。

### 3.3 冲突分桶 + `judge()` 主体未知降级（G6）

- 分桶键只用 `card.entity`，**目录名回落已移除**；主体未知的材料单入
  `unknown_bucket`，**不参与 CONFLICT / STALE 判定**；
- `judge()` 里「主体未登记」检查改到覆盖类判定之后独立执行：
  候选里有主体未知的材料 ⇒ `MATCHED / PARTIAL / RESTRICTED` **一律降为 `UNCERTAIN`**，
  并写明「主体未登记，无法判定是否同一主体」；
  `CONFLICT` **保留**（更具体、必须人工裁定的发现优先于笼统的 UNCERTAIN），两条事实都进 `missing_detail`；
- 回归：`test_dd_v1_a1_conflict_bucketing.py` 7/7，关联四件套 **77/77 零失败**。

### 3.3a ★ 冲突分桶 **v2**（第二轮 Reviewer B-3 / M-4 / R2-1 → 已改）

**v1 错在哪**：v1 把「主体未知」实现成「`card.entity` 为空」。
但认知卡的 `entity` 在**真实材料上就是父目录名**
（`dd_v1_card_service.build_card` 的 `parts[-2]`，`provenance=INFERRED`、
`evidence.kind=path_segment`，**全仓唯一写入点**）——**非空**。

⇒ 「主体未登记」被误判成「主体已知」⇒ **同目录的不同法人落进同一个桶** ⇒ 报假 CONFLICT；
且 `has_unknown_entities=False` ⇒ `judge()` 的「主体未登记 ⇒ 降级 UNCERTAIN」
**根本不触发**（「主体未登记，无法判定是否同一主体」这句话在真实数据上永不出现）。

⇒ **根因不是「改得不够」，是「主体未知」的定义被改窄了**：
任务书 G6 的定义是「**不在权威名单**」，实现却按「字段为空」判定。

**v2 三处改法**

| # | 改法 | 落点 |
|---|---|---|
| ① | **冲突桶键查权威主体名单**：`ent` 不在权威名单 ⇒ 进 `unknown_bucket`，**不参与 CONFLICT / STALE** | `dd_v1_match_service.detect_anomalies`（`registered` 集合 = 第 3 位参 `need_entities` ∪ 第 4 位参 `authority_entities`） |
| ② | **桶键纳入材料类型**：`(entity, period, doc_type_key)` ⇒ 不同材料类型不得互判冲突 | 同上；类型由 `cs.doc_type_key()` 解析 |
| ③ | **测试前提修好**：删掉「`_extract_labels` 从正文抽主体」的**错误说明**；全部改走**真实建卡管线**，不手工改 `card.entity` | `backend/tests/test_dd_v1_a1_conflict_bucketing.py`（整体重写） |

**关键口径（不要改错）**

- **权威名单的来源**：第 3 位参 `need_entities` **就是**验收脚本里的权威名单口径
  （`check_g6_indep.py` 的 G6-D/G6-F、`check_g6_strict.py` 的 G6-2/G6-5 都把它放在这个位参）；
  第 4 位参 `authority_entities` 是产品路径额外传入的**全量权威名单**（不按义务范围过滤）。
  两个来源取并集。
- **「已登记主体」以权威名单为准，不看 provenance**：目录名 `甲公司` 若**在**权威名单里 ⇒
  算已登记主体（G6 正向用例必须仍报 CONFLICT）；若**不在** ⇒ 算主体未知。
  ⇒ 因此**没有**改 `build_card` 停止写父目录名：那个值是**线索**（桥接的 `CARD_INFERRED` 档依赖它，
  A2 的 G-A2-3 也要用），改掉会波及下游；而「不得用目录名冒充主体」这条要求
  由**判定层不采信它**来满足。
- **材料类型的取值顺序必须是「文件名优先」**：卡片 `doc_type` 列存的是扩展名（不可用）；
  正文/用途在「营业执照 vs 车辆登记证」这类判别上**不可用**（两份正文可能都是「审计报告…」）；
  **文件名**才是唯一可用信号 ⇒ 顺序定为 `卡片 doc_type（已是规范 key）→ 文件名 → 标题 → 用途`，
  认不出留空标 UNKNOWN，**不拿扩展名或中文名占位**。

**验收（独立 Reviewer 的 4 支脚本 + 司仓探针，全部同口径复跑）**

| 脚本 | 修复前 | 修复后 |
|---|---|---|
| `check_g6_indep.py`（第二轮 Reviewer 自写，真实建卡管线 8 子判据） | 5 FAIL | **8/8 PASS** |
| `check_g6_e2e.py`（第二轮 Reviewer，端到端产品路径，不手工改 entity） | `verdict=CONFLICT` | **PASS**（`UNCERTAIN` + 「主体未登记」） |
| `check_g6_strict.py`（第一轮 Reviewer，8 条） | 6 FAIL | **7/8 PASS**（仅剩 G6-7，见下） |
| `gm_probe_g6_bucketing.py`（司仓探针 A–E 五段） | B/C/D FAIL | **5/5 PASS** |
| `tests/test_dd_v1_a1_conflict_bucketing.py`（新 9 条） | 6 FAIL | **9/9 PASS** |

- ⚠️ **G6-7 仍 FAIL，是设计使然、不是漏项**：它断言的是
  「唯一允许的 fixture（平铺布局）里 `card.entity` 非空者 > 0」——
  那是**关于 fixture 覆盖面**的诊断，不是关于产品行为的判据；
  平铺 fixture 的 `card.entity` 本就全空 ⇒ 该路径在 fixture 下不可达。
  第二轮 Reviewer 的重开条件只要求 G6-1 / G6-1b / G6-4 / G6-5 ⇒ **四条全 PASS**。
  真实建卡管线的覆盖已由**新测试用例**（子目录布局）补上，而不是改 fixture。

### 3.3b PII 复用整改（第一轮 Reviewer M-1 → 已改）

第一轮 Reviewer 判定：`dd_v1_pii_service.py` 的 docstring 声称「复用
`desensitize_service._IDENTITY_PATTERNS`」，**代码却从未 import 它**——
`_BUILTIN_PATTERNS` 是手抄的第二份副本，且抄时改了标签与顺序 ⇒
**文档失真 + 仓内同一套身份正则 3 份副本**（desensitize / 内置 / config JSON）。

**整改**：

1. `dd_v1_pii_service` **真正 import** `desensitize_service`，
   基线模式由 `_derive_base_patterns()` **派生**（正则本体、替换标签、**顺序**全部照搬），
   本模块**不再持有第二份正则**；
2. 名单文件 `dd_v1_pii_denylist.json` **只承载增量/覆盖**
   （本仓 genuinely 新增的「统一社会信用代码」），不再抄全量；
3. docstring 与代码对齐；
4. 新增 **3 条用例锁死复用纪律**：真 import / 名单不含基线副本 /
   与 `desensitize_service` 差分一致。

实测：与 `desensitize_service` 对同一批样本 **6/8 完全一致**，
余 2 处差异正是允许的两类（`[账号]` 标签口径 + USCC 增量项）；
仓内身份正则副本 **3 份 → 1 份**。

### 3.4 **修「卡片的用途 → 义务文档类型维度」这根断线**（原白名单外，已披露）

**实测**：修复前 `evaluate_file()` 的 `doctype_ok` 对**九类带中文关键词的材料类型恒 0**
（`contract` 例外——`_DOC_TYPE_PURPOSE_MAP["contract"]` 是**空元组**，命中 `(not keys)` 分支，
基线即为 1；这是第一轮 Reviewer 复核后**收窄**的口径）。

根因：认知卡 `purpose` **表列存的是 `json.dumps(list)` 字符串**，
而代码写成 `" ".join(card.get("purpose") or [])` ⇒ 把 JSON 字符串**逐字符**加空格拼接
⇒ `审计` / `章程` / `营业执照` 等中文关键词**永远匹配不上**。

后果：`doctype_cov` 恒 0（九类） ⇒ `judge()` 里**一票否决** ⇒ `MATCHED` 永远出不来。
这就是 A0 记的「W4 `doctype_cov` 一票否决 63–67%」的真正机制。

**处置**：在 `dd_v1_card_service` 建**唯一权威读取口** `multi_text()` / `purpose_text()`
——**优先读结构化字段** `card["fields"][name]["value"]`（与本模块 `related_files`
的既有用法一致），顶层列只作兜底且按 **JSON 解析**、不按字符迭代；
`evaluate_file` 与桥接模块**都走它**（不各写一份）。

> **为什么放进 A1 而不是留给 A2**：A2 的 G-A2-4 是「`doctype_cov` 口径」，
> 但那是一条**判据**；这根线**断在产品代码里**，不修它，判据无从谈起，
> 且 A1 的交付物（桥接取到候选证据）也会因 doc_type 判不出而空转。
> 故就地修复、**如实披露**、并补专门用例，由独立 Reviewer 一并判。

### 3.5 薄桥 `dd_v1_bridge_service.py`（G1/G2/G7，新增）

- `build_meta()`：清单 + 认知卡 → 语义层 `meta`。
  材料 doc_type 由**两个信号取并集**判定：`rq.parse_doc_type`（权威正则）
  与 `ms._DOC_TYPE_PURPOSE_MAP` 的逆映射（与规则链 `doctype_ok` 同一张表）；
  **命中多个就判不出**（不猜），返回 `""` = UNKNOWN，**不得拿扩展名或中文名占位**。
- `build_semantic_obligations()`：requirement 义务 → 语义义务。
  **显式传 obligations** ⇒ 语义层不再用 `SPLIT_RE` 二次切碎（G7）。
  一条义务**按主体分簇**，每簇一个语义义务 ⇒ 每份证据里**只含同一主体**的材料。
- 主体三档，写进输出可追溯：

  | 档 | 含义 | 来源 |
  |---|---|---|
  | `AUTHORITY` | 权威登记主体名 | `dd_v1_entities`（`rq.resolve_entities`） |
  | `CARD_INFERRED` | 卡片主体**线索** | 认知卡 `entity` 字段，来源是**目录名**（`path_segment`，INFERRED），**不是法律事实** |
  | `UNKNOWN` | 无任何主体线索 | — |

  非 `AUTHORITY` 档 ⇒ 逐条证据标 `subject_verified=false`，
  并在 `warnings` 里说清「**取到的证据可能横跨多个法人**」。
- 降级：无适配器 ⇒ `mode=RULE_ONLY` + `degrade_reason`，
  **`external_model_calls=0`**（零外部调用、零费用、确定性）；
  任何异常**不得**影响入口 A 的原有输出。

### 3.6 入口 A 接桥接（附段式，G1/T5）

`tools/dd_team_channel.py`：

- 桥接是**附段**，**不是第 7 步** ⇒ 桥接不可用或 `--no-bridge` 跳过时，
  **上面 6 步的输出一字不变**；
- 报告新增**并列小节**「语义层建议（仅供参考，不改判定）」，
  与规则判定**分开**，每条建议带 `file_id + sha256 + locator`；
- 机读 JSON 新增 `semantic_bridge` 键，恒带
  `advisory_only=true / review_required=true / changes_hard_verdict=false / sent_to_institution=false`；
- 新增 `--no-bridge`（跳过）与 `--allow-real-material`（材料库不是仓库内合成 fixture 时必须给，
  与入口 B 同一把锁）。

## 4. 诚实的边界（**没有做到什么**）

1. **真实材料上 `MATCHED` 仍然出不来。** 卡片 `sensitivity` 仍是 0/176 全空
   ⇒ 披露策略按「空等级 = 不可判定」一律不可外发 ⇒ 交付材料为空。
   这是 **A2 的 G-A2-2**（敏感等级保守默认）负责，本包**不越界**。
2. **主体维度仍不设防。** 真实材料里 `dd_v1_entities` 是空的
   ⇒ 主体只能取目录名线索 ⇒ 桥接的语义证据**必须**标 `subject_verified=false`。
   这是 **A2 的 G-A2-3** 负责。
3. **真实材料上 CONFLICT 会因本包而消失（G6 v2）。**
   v1 只去掉了「`card.entity` 为空时回落目录名」这条**假**来源，但**没有**去掉
   「`card.entity` 非空 ⇒ 视为主体已知」这条**更大的假**来源 ——
   而真实材料上 `card.entity` **就是父目录名**（INFERRED/path_segment）。
   ⇒ v1 的真实材料结果是 **CONFLICT 285/319（89%）**，即那 89% 绝大多数是**假冲突**。
   **G6 v2** 把「主体未知」的判据改成「**不在权威名单 `dd_v1_entities` 里**」
   ⇒ 真实材料上权威名单为 0 条 ⇒ 全部材料都算「主体未登记」
   ⇒ CONFLICT 归零，判定转为 **UNCERTAIN**（诚实状态：无法判定是否同一主体）。
   真正的「同主体 + 同期间 + 同材料类型 + 内容哈希不同」冲突，
   要等 **A2 的 G-A2-3** 把权威主体名单填上之后才会重新出现。
4. **本包不跑真模型**（`external_model_calls=0`）。dsh 已于 2026-10-11 按董事长令永久停用；
   真实模型通路属 **A4b**（刘江 Windows + 额度）。
5. **桥接只到「候选证据」层**。它不产最终判定，也**不进交付包**。

## 5. 证据清单（`a1-evidence/`）

| 文件 | 内容 |
|---|---|
| `calltrace-bridge.jsonl` | 入口 A + 桥接的真 trace（1 meta + N call + 1 done，真实退出码） |
| `trace-summary.json` | 从 trace 数出的**每模块调用数**（G1 的核心证据） |
| `summarize_trace.py` | 上面那个汇总器（可复现） |
| `a1-trace-runner.py` | A0 trace runner 的 A1 改造版（纯观察，不打补丁） |
| `a1-trace-checklist.tsv` | **trace 的冻结输入**（2 条清单）——§6 复现命令直接用它 ⇒ trace 数字**可复现** |
| `check_policy_g4.py` | 披露策略 29 条判据的自证脚本 |
| `provenance_plugin.py` + `provenance-check.txt` | **「被测代码来源」硬证据**（pytest session 起点打印解析到的源码树 + A1 独有标记） |
| `pytest-a1-junit.xml` | A1 全量回归（**G6 v2 + R1 整改后**重跑）的 junit：**1463 tests / 0 failures / 0 errors / 5 skipped ⇒ 1458 passed** |
| `bridge-run-stdout.txt` / `bridge-run-stderr.txt` | 入口 A + 桥接的**运行时输出**（stderr 0 字节） |
| `entryA-reports/` | 入口 A 的**实际产出**（报告 MD + 机读 JSON） |
| `real-regression-post-a1.txt` | 真实材料回归（**开**授权闸 ⇒ 桥接真跑；案例名已脱敏为 案例A/B/C） |
| `real-regression-post-a1-no-bridge.txt` | 真实材料回归（**不开**授权闸 ⇒ 桥接降级，入口 A 输出不变） |
| `SHA256SUMS-a1-evidence.txt` | 上述文件逐件 sha256（`shasum -c` 自检）——**冻结快照** |
| `../SHA256SUMS-wp05.txt` | 整个交付目录（含本文件与 `a1-evidence/` 全部文件）的 sha256 ——**冻结快照** |

> ⚠️ **两份清单都含 `bridge-run-stdout.log` / `bridge-run-stderr.log`**：
> 交付契约点名要这两个文件名，但 FOS 仓 `.gitignore:61` 有 `*.log`
> ⇒ 这两份是同名 `.txt` 的**逐字节副本**（已 `cmp` 核验一致），**提交时不入 Git**。
> 提交进仓的权威集合 = 其余 16 件 + `bridge-run-stdout.txt` / `bridge-run-stderr.txt`。
> 复核时请以**工作区当前状态**为准（`shasum -c` 在 worktree 里跑，不是 fresh clone）。

#### ★ 证据冻结口径（N-5 整改）

- 冻结动作发生在**整改全部落地之后、第二轮独立验收之前**；冻结后交付目录**不再变动**。
- 冻结前自检三项，缺一不可：
  1. **SHA256 清单重建并 `shasum -c` 全 OK**（a1-evidence 18 件 + wp05 层 20 件）；
  2. **真实机构名 grep 零命中**：模式串**不落在 Git 产物里**，存放在 Mac 授权目录
     `~/dd-v1-realbase/.real_name_patterns.txt`（一行一个，含 2 家客户行全称与简称、
     1 家客户法人名、2 个省地名）⇒ 交付目录跑 `grep -rIf <该文件>` 输出 **0 行**；
     本文件自身也不含任何字面机构名（否则扫描命令会命中自己）。
  3. **被测代码来源 provenance 当场打印**（`provenance-check.txt`）。
- 冻结时刻的 `pytest-a1-junit.xml` 是**G6 v2 + R1 整改后**重跑的结果（`1463/0/0/5`）；
  冻结时刻的 `calltrace-bridge.jsonl` / `bridge-run-*` / `real-regression-*` / `entryA-reports/`
  均在 **PII 复用整改之后**重新生成（时间戳晚于 `dd_v1_pii_service.py` 的最后改动）。

### 5.1 回归口径（任务书要求的解释器对齐）

| | 解释器 | 被测代码 | tests | failures | errors | skipped | passed |
|---|---|---|---|---|---|---|---|
| A0 基线（历史） | 3.11.14 | master `a7a7e24` | 1424 | 0 | 0 | 5 | 1419 |
| **master 同解释器对照** | **3.13.12** | **master `a7a7e24`** | 1424 | 0 | 0 | 5 | **1419** |
| **A1 接线后（G6 v2 + R1）** | **3.13.12** | **A1 worktree** | **1463** | **0** | **0** | 5 | **1458** |

- 同一解释器下 master 与 A0 基线数字**完全一致**（1419）⇒ 解释器差异为 0；
- A1 新增用例 ⇒ passed 数**上升 39**（1463−1424）；**failures/errors 均为 0** ⇒ 无回归。
- 增量构成（逐模块 A1−master 差值，合计 **39** 条）：
  · **PII 复用纪律** 12 条
    （真 import `desensitize_service` / 名单不含基线副本 / 与 `desensitize()` 差分一致）；
  · **桥接** 9 条（`test_dd_v1_bridge.py`）；
  · **冲突分桶** 12 条（`test_dd_v1_a1_conflict_bucketing.py`：G6 v2 的 9 条 + G6 v3 · R1 的 3 条类型未知分桶）；
  · **披露策略/类型闸** 6 条（补在既有 `test_dd_v1_policy_and_entry.py`）。
- 全文回归口径统一为 **1463**（上一版文档里的历史口径数字已全部更正；按第三轮 §9 第 5 条，历史数字**不得**再出现在本文档中）。

#### ★ `doc_type_terms` 的契约（NOTE-2 · 第三轮补记）

`doc_type_terms` 是**桥接侧向语义检索层注入的检索词扩展**（把义务的 `doc_type`
展开成中文检索词，让 `retrieve_minimal_evidence` 能命中同义材料）。

- **注入方**：只有 A1 的桥接调用链（`dd_v1_bridge_service` → 语义检索层）会注入；
- **非桥接调用方**：不注入 ⇒ 摘录退化为 L1–L3（按既有 `excerpt` 规则取头部片段）；
- **契约边界**：它是**检索侧**的辅助参数，**不参与**任何判定
  （不进入 `doctype_ok` / `doctype_cov` / 硬判定），也不改变材料类型口径。

#### ★ 已知边界（NOTE-3 · 第三轮补记，移交 A2）

主体判定目前是**字符串相等**：同一法人若被放在**不同命名目录**下，
两个目录名不会归一 ⇒ 同一主体的真冲突可能漏报。

- 当前实现**符合任务书口径**（保守：不误报），属 A2 的 **G-A2-3 / G-A2-8** 范围
  （主体名归一 + 别名/简称登记）；
- A2 落地后，A1 的这条边界随之收敛。

#### ★「被测代码来源」是当场打印出来的，不是推断的

worktree 的 venv 装的是 **editable install**（`.pth` 指向 `backend/src`），
而 FOS 仓 `backend/pyproject.toml` 里有 `pythonpath = ["src"]`（**相对 rootdir**，
pytest 会**前置**到 `sys.path`）：

- 裸 `python -c "import cangjie_fos"` ⇒ 解析到 **venv 指向的那棵树**；
- **pytest** 下 ⇒ 解析到 **rootdir 所在的那棵树**。

⇒ 「这轮跑的到底是哪份代码」**不能靠想**。`a1-evidence/provenance_plugin.py`
在 pytest session 起点直接打印解析结果与一个 A1 独有的源码标记：

| 跑哪边 | 解析到的源码树 | A1 标记（主体未登记分支） |
|---|---|---|
| A1 worktree | `/Users/mac/cangjie-fos-wt-a1/backend/src/cangjie_fos/__init__.py` | **True** |
| master | `/Users/mac/cangjie-fos/backend/src/cangjie_fos/__init__.py` | **False** |

原始输出：`a1-evidence/provenance-check.txt`。

### 5.2 真实材料回归（post-A1）

| | 义务 | CONFLICT | RESTRICTED | MISSING | UNCERTAIN | MATCHED |
|---|---|---|---|---|---|---|
| pre-A1 基线 | 319 | 284 | 29 | 6 | 0 | 0 |
| post-A1 v1（分桶 v1） | 319 | 285 | 20 | 6 | 8 | 0 |
| **post-A1 v2（G6 v2 后）** | 319 | **0** | **0** | 6 | **313** | **0** |
| **post-A1 v3（G6 v3 · R1 后）** | 319 | **0** | **0** | 6 | **313** | **0** |

**v2 与 v3 数字相同，但含义不同**：v2 是「权威主体名单为空 ⇒ 全部落 `unknown_bucket`」；
v3 是「**即使名单非空，材料类型认不出也不互判冲突**」（见 §3.3b）⇒ 同一组数字背后的机制已换。

**v1 → v2 的变化全是「诚实化」，不是「变好」**：
`CONFLICT 285 → 0`、`RESTRICTED 20 → 0`、`UNCERTAIN 8 → 313`。
原因是 G6 v2 之后**权威主体名单（0 条）成为唯一的「已登记」来源**
⇒ 真实材料上每份材料的 `card.entity`（= 父目录名，INFERRED）都**不再算主体已知**
⇒ 313 条义务全部落到「主体未登记，无法判定是否同一主体」⇒ 判 `UNCERTAIN`。

⇒ **这不是「能力变强」，是「不再自欺」**：v1 的 285 条 CONFLICT 里绝大多数是
**同目录不同法人被当成同一主体**的假冲突（跨法人率 78%/73% 就是证据）。
⇒ 但也必须说清楚：**真实材料上现在一条 MATCHED 都出不来**，
而且在 **A2 的 G-A2-3 把权威主体名单真正填上**之前，一条都出不来
（G-A2-3 是 MATCHED 的**必要前置**，不是可选优化）。

- ⚠️ **分簇截断（如实记账）**：案例C 有
  **4423 个主体分簇因超过上限被截断**（`MAX_ENTITY_CLUSTERS=8`）；
  **被截断的主体未被覆盖**，该数字由桥接写进 `semantic_bridge.warnings`
  与机读字段 `entity_clusters_truncated`（机器可读层与人读层都有）。
  ⇒ 因此「1790/1793 条义务取到候选证据」**不等于**「全部义务都被覆盖」。

- ⚠️ **主体线索口径**：案例A/案例B/案例C 三案例的 warnings 均写明
  「义务主体取自**卡片主体线索**（认知卡 entity 字段，来源是目录名 path_segment，INFERRED，**不是法律事实**）；
  这些语义证据只能当候选提示」；
  案例B 有 **2 条**、案例C 有 **1 条**义务**无任何主体线索** ⇒ 语义层的「同主体」过滤
  退化为「同 doc_type」⇒ **取到的证据可能横跨多个法人**（每条已标 `subject_verified=false`）。

- 语义桥接在真实材料（176 份）上**真跑通**：
  1790/1793 条（分簇后）义务取到候选证据，共 **3376** 份带 `sha256+locator` 的候选材料，
  **外部模型调用 0**；主体口径 `AUTHORITY=0 / CARD_INFERRED=1790 / UNKNOWN=3`
- ⚠️ **口径（第二轮 Reviewer N-4）**：`1790/1793` 是
  「**分簇后义务的候选证据获取率**」，**不是召回率、不是准确率**。
  1793 是**分簇后**的义务数（一条义务按主体分簇 ⇒ 一条义务 × N 个主体簇）；
  **原始义务只有 319 条，原始义务上的 MATCHED 仍是 0/319**。两个数不可混用。
  ⇒ 逐条标 `subject_verified=false` 并告警。
- 8 条 `RESTRICTED→UNCERTAIN` = G6 语义落地（主体未知 ⇒ 覆盖不可信）。
- **`MATCHED` 仍 0**：卡片 `sensitivity` 0/176 全空 ⇒ 「空等级=不可判定」⇒ 交付材料为空
  ⇒ 结构性地出不来（**A2 的 G-A2-2**，本包不越界）。

## 6. 复现命令

```bash
cd /Users/mac/cangjie-fos-wt-a1

# ① 策略判据
backend/.venv/bin/python docs/dd-v1-fos71/wp05-real-integration/a1-evidence/check_policy_g4.py

# ② 入口 A + 桥接的真 trace 与模块计数
#    （清单已冻结在 a1-evidence/a1-trace-checklist.tsv ⇒ 本节数字可复现）
export CANGJIE_DD_V1_DATA_DIR=$(mktemp -d)
backend/.venv/bin/python docs/dd-v1-fos71/wp05-real-integration/a1-evidence/a1-trace-runner.py \
  --trace-out docs/dd-v1-fos71/wp05-real-integration/a1-evidence/calltrace-bridge.jsonl \
  -- tools/dd_team_channel.py run --library A1trace库 \
     --root backend/tests/fixtures/dd_v1_fos71_wp04/snapshot \
     --checklist docs/dd-v1-fos71/wp05-real-integration/a1-evidence/a1-trace-checklist.tsv \
     --institution 某机构 --by 测试
backend/.venv/bin/python docs/dd-v1-fos71/wp05-real-integration/a1-evidence/summarize_trace.py \
  docs/dd-v1-fos71/wp05-real-integration/a1-evidence/calltrace-bridge.jsonl

# ③ 回归（failures/errors 必须为 0）
cd backend && env -u ALL_PROXY -u all_proxy .venv/bin/python -m pytest tests/ \
  --ignore=tests/test_doctor_script.py -q --junit-xml=<junit.xml>

# ④ 冻结快照自检（两处清单都必须全 OK）
cd docs/dd-v1-fos71/wp05-real-integration
shasum -a 256 -c SHA256SUMS-wp05.txt
cd a1-evidence && shasum -a 256 -c SHA256SUMS-a1-evidence.txt

# ⑤ 真实机构名零命中自检（模式串在 Mac 授权目录，不进 Git；须输出 0）
cd .. && grep -rIf ~/dd-v1-realbase/.real_name_patterns.txt . | wc -l
```
