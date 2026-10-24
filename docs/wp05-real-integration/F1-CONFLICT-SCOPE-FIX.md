# F1 修正包 · CONFLICT 相关性闸（监工第 35 轮 P0）

- 修正包：分支 `feat/71-a3-f1-conflict-scope`，基线 `feat/71-a3-packaging` @ `c44700f`
- 工作树：`/Users/mac/cangjie-fos-wt-f1`
- 判据来源：独立监工第 35 轮 · F1（`cangjie-gm/work/evidence/W-DD-V1-REALINT-2026-A0/MONITOR-ROUND61-FINDINGS-F1-F4.md`）
- ★ 司仓**先独立复现、后动手**（不采信口述）；复现脚本与判别力探针均为自建。

---

## 1. 缺陷（一句话）

材料库里只要存在**一对**「同主体 + 同期间 + 同类型 + 异哈希」的文档，
**该库内所有义务**都会被判 `CONFLICT`（包括那些**与这对材料毫无关系**的义务）
⇒ 材料包为空 ⇒ **系统在该库上完全不可用**。

## 2. 根因（代码级）

`backend/src/cangjie_fos/services/dd_v1_match_service.py::judge()`：

```python
anom = detect_anomalies(obl, results, need_entities, ...)
if anom["has_conflict"]:
    verdict = V_CONFLICT          # ← 无条件覆盖本义务判定
```

冲突是**候选池内部**的发现（桶键 = 主体 × 期间 × 材料类型），
与「本义务要求哪一类材料」**无关**；
而同一个文件里 **UNKNOWN** 桶有相关性门控（A2 · G-A2-12「只有可能是本义务要求的那一份才降级」）、
**STALE** 桶有 verdict 门控，**唯独 CONFLICT 桶没有这道门控**。

## 3. 司仓独立复现（真实产品管线 · 合成材料 · 隔离环境）

探针：`workspace/gm_probe_f1_conflict_scope.py`（三变体 + /tmp 符号链接农场 + 加载路径断言）

材料：一对「2024 审计报告 / 2024 审计报告补充说明」（同主体同期间同类型异哈希 ⇒ 真冲突）
+ 一份营业执照；义务三条：审计报告 / 营业执照 / 专利证书（**库里零 ip 材料**）。

| 变体 | L1 审计报告 | L2 营业执照 | L3 专利证书 |
|---|---|---|---|
| **修复前**（`c44700f` 原树） | CONFLICT ✔ | **CONFLICT** ✘ | **CONFLICT** ✘ |
| **回退 F1 闸**（同树但去掉相关性判定） | CONFLICT | CONFLICT | CONFLICT |
| **已修**（本包） | CONFLICT ✔ | **RESTRICTED** ✔ | **PARTIAL** ✔ |

★ L3 修复前的 `missing_detail` 里明明已有「**材料类型缺 1/1 份（维度：材料类型）**」
这条**可行动的缺口信号**，却被冲突**覆盖**掉 ⇒ 复核者拿不到「缺什么」。
修复后该信号**回到判定文案里**。

## 4. 修法（与 A2 G-A2-12 **同构**）

在 `judge()` 里给 CONFLICT 加**相关性闸**：
冲突对里有「**可能是本义务要求的那一份**」的候选时（`_may_be_required`，
**同一套**相关性口径）本义务才改判 CONFLICT；否则**只留痕**、**不改判**。

### 不变量（全部守住）

| 不变量 | 保障方式 |
|---|---|
| **检测口径一字不改** | 桶键 / 唯一性 / 主体归一 / `has_conflict` / `conflicts` **全部不动**；`detect_anomalies` 未改一行 |
| **冲突事实不丢**（T3 语义不变） | `has_conflict=True`、冲突组数不减、落 `anomalies_json` 审计面、`missing_detail` 有「（留痕）…仍需人工裁定」 |
| **真冲突仍必报** | 义务要求的类型与冲突对类型**一致** ⇒ 仍 CONFLICT |
| **最保守** | 义务**未指名类型** ⇒ 任何候选都可能是 ⇒ 一律按相关处理（仍 CONFLICT） |
| **旧调用路径不破** | 缺 `_may_be_required` 标记时按最保守（True）处理 |

★ 监工原文写 L3 期望「回到 MISSING/类型维缺口」；产品既有口径下
「材料类型缺」对应 **PARTIAL**（MISSING 是 QC 维度概念，不是判定取值），
**关键判据「不再判 CONFLICT + 缺口可行动」均满足**，此处据实说明。

## 5. 判别力（回退 ⇒ 必须转红）

| 变体 | 期望 | 实测 |
|---|---|---|
| 未回退 | L2/L3 **不得** CONFLICT | ✔（RESTRICTED / PARTIAL） |
| 回退 F1 闸 | L2/L3 **回到** CONFLICT | ✔（CONFLICT / CONFLICT） |
| 修复前的树 | 复现原始缺陷 | ✔（CONFLICT / CONFLICT） |

★ 判别力探针 9/9 逐条核对全绿；**加载路径当场断言**（`cangjie_fos.__file__` 前缀）
+ 被测文件 SHA256 指纹自证 ⇒ 不是假绿。

## 6. 回归

- 新增用例 `backend/tests/test_dd_v1_f1_conflict_scope.py`（**6 条**）：
  无关义务不被染黑（2）/ 真冲突仍报（2）/ 冲突事实与审计面仍留痕（2）。
- 新增用例 `backend/tests/test_dd_v1_entity_text_redaction_guard.py`（**1 条**）：
  补 A3 §2 判别力实验实测发现的**覆盖缺口**（判定文案那条脱敏线此前无守卫）。
- 全量套件（同一 venv、同一命令、两树对跑）：
  - 基线树 `c44700f`：**1641** 条用例，失败 **7** 条；
  - 修正包：**1648** 条用例（+7 = 6 + 1），失败 **7** 条；
  - ★ **失败集合逐字相同 ⇒ 零新增失败、零修复**。
  - 那 7 条是**环境性**既红：6 条 LLM-refine（代理 SOCKS 缺 `socksio` 致假红）
    + 1 条 `test_doctor_script`（缺 `backend/.env` 与前端 `node_modules`）。

## 6.5 ★ 独立验收裁定与遗留风险披露

<!-- gm-fix-f1-doc-disclose-review -->

> **独立 Reviewer 裁定**：`VERDICT: PASS（限定：R1–R7 全 PASS，无必须修的问题；
> 2 条低 severity 观察需在晋级说明中显式披露）`
> 裁定书：`/Users/mac/cangjie-gm/work/evidence/W-DD-V1-REALINT-2026-F1/VERDICT.md`
> （Reviewer **独立复现**，未采信本包任何自报。）

### 6.5.1 Reviewer 的 R1–R7 逐条结论（摘要）

| # | 项 | Reviewer 判定 | 关键实测 |
|---|---|---|---|
| R1 | 缺陷客观存在 | PASS | 基线树 `c44700f` 上，L2 营业执照 / L3 专利证书义务确被误判 `CONFLICT`；L3 的可行动缺口（「材料类型缺 1/1 份」）被覆盖。Reviewer 用**自写脚本 + 不同合成材料 + 不同主体名**复现 |
| R2 | 修法正确 | PASS | L1 仍 `CONFLICT`；L2 = `RESTRICTED`；L3 = `PARTIAL` 且缺口文案可见；`has_conflict=True`、冲突组数、「（留痕）…仍需人工裁定」**全部保留** ⇒ 不是靠抹掉冲突换来的绿 |
| R3 | 检测层未被削弱 | PASS | `detect_anomalies` 与 `_may_be_required_type` 两树**逐字相同**（AST 段 SHA256 相同），改动只在 `judge()` 判定层 |
| R4 | 测试有判别力 | PASS | 7 条新用例在**四个独立回退方向**下全部至少转红过一次；模块来源断言写在 **pytest 进程内**，并实测拦下过一次农场装配错误 ⇒ 无假绿 |
| R5 | 零新增回归 | PASS | 两树全量 pytest 失败**各 7 条**，失败集合**逐字相同**（MD5 相同），用例数 1641 → 1648（+7 精确对应 2 个新文件） |
| R6 | 严格性未放宽 | PASS | 未改客观门基线、未改 A2/A3 判据条文、未把「未知类型」从 FAIL 改成通过 |
| R7 | 合规 | PASS | 改动面**恰为**白名单 4 件，**无白名单外改动**；交付物**零真实客户名**；`backend/uv.lock` 在修正包树**干净** |

### 6.5.2 ★ Reviewer 指出的 2 条低 severity 观察（**显式披露**）

1. **措辞口径不统一（观察 1）**｜`L1` 的 `missing_detail` 用「同一主体/期间存在 1 组内容冲突」，
   而 `L2/L3` 用「（留痕）候选材料中…」。两处措辞口径不同但**语义不矛盾**。
   ⇒ 保留现状（消息里的冲突组数口径 = **相关**冲突组数，见 6.5.3 风险 1）。
2. **`elif` → `else` 的连带效应（观察 2 · 口径外连带改动）**｜结构改写后，
   「存在冲突但**全部无关**」且 `has_stale`、且改判前 verdict ∈ {MATCHED, PARTIAL} 时，
   **旧口径判 `CONFLICT`、新口径判 `STALE`**。
   ⇒ Reviewer 判断：**不是把闸放宽成通过** —— 两者都是**非通过判定**；
   交付侧 `dd_v1_package_service.py:388` 的缺口清单口径是 `verdict != "MATCHED"`
   ⇒ 两者**同样进入**「需人工处理」清单（仅分桶不同）；冲突事实仍在 `missing_detail`
   的**留痕行**里、仍写着「仍需人工裁定」。
   ⇒ **显式披露**（执行者初版文档未披露这一条 —— Reviewer 指出，属披露缺口）。

### 6.5.3 Reviewer 列出的全部遗留风险（原文口径）

| # | 风险 | 性质 | 处置 |
|---|---|---|---|
| 1 | 消息里的冲突组数口径由「冲突总组数」改为「相关冲突组数」（`:1008` / `:1014`）。当前 `ANNUAL_UNIQUE` **只有 `audit_report` 一种** ⇒ 冲突组只会全有或全无地相关/无关 ⇒ 数字不失真。**但若日后新增第二个 `ANNUAL_UNIQUE` 类型**并出现「相关冲突 + 无关冲突并存」，则无关冲突既不计入消息数字、也**不会产生留痕行** | 前瞻性 · 当前不可达 | ★ **已在本包内闭合**（见 6.5.4） |
| 2 | `elif` → `else` 的连带改动（非通过判定之间的分桶差异） | 口径外连带改动 | ★ **已在上表 6.5.2-2 显式披露**；Reviewer 判定不阻断放行 |
| 3 | 两树共有的 **7 条环境性失败**（6 条 LLM-refine 代理缺 `socksio` + 1 条 `test_doctor_script` 缺 `.env`/`node_modules`） | 环境面 | 本包**未修复也无需修复**，单独排期 |
| 4 | ★ **全量 pytest 会改写被测树的 `backend/uv.lock`**：根因是 `tools/doctor.py::check_deps()` 在 `cwd=backend` 下执行 `uv run --extra dev python -c "import cangjie_fos"`，`uv run` 会**隐式重新解析并写回 lockfile**（把可选 extras 全量展开：torch / docling / accelerate 等 **1797 行**）。该副作用是**既有**的 | 仓库卫生 · 环境面 | ★ 流程已固定：**跑套件前记录 `uv.lock`、跑完还原**；本包提交前已还原（`git diff --stat backend/uv.lock` 为空） |
| 5 | 修正包当时**仍是未提交的工作区改动** | 流程面 | ★ **已闭合**：本包已落成提交（见 §7 改动面与提交记录） |

### 6.5.4 ★ 裁定**通过之后**的追加改进（闭合风险 1）

把 `_conf_irr` 的**留痕**从 `else:` 分支**移出** ⇒ **无论有没有相关冲突**，
无关冲突**一律留痕**。

| 口径 | 改动前 | 改动后 |
|---|---|---|
| 无关冲突留痕 | 只在「**没有**相关冲突」时出现 | **一律出现** |
| 判定分支（CONFLICT / STALE） | — | **一字不改** |
| `verdict` 取值 | — | **一字不改** |
| STALE 分支位置与触发条件 | — | **保持原样** |
| 留痕文案 | — | **逐字不变** |

★ 只**多一行文案**，**不放宽任何闸**（不可能让任何判定变松）。
★ 该改进**在 Reviewer 裁定之后**追加 ⇒ 已在此**显式披露**，
并由 Reviewer 第二轮复裁覆盖（见复裁裁定书）。

---

## 7. 改动面

| 路径 | 性质 |
|---|---|
| `backend/src/cangjie_fos/services/dd_v1_match_service.py` | 改：`judge()` 的 CONFLICT 相关性闸（带 marker `gm-fix-f1-conflict-scope`） |
| `backend/tests/test_dd_v1_f1_conflict_scope.py` | 新增（6 条） |
| `backend/tests/test_dd_v1_entity_text_redaction_guard.py` | 新增（1 条） |
| `docs/dd-v1-fos71/wp05-real-integration/F1-CONFLICT-SCOPE-FIX.md` | 新增（本文件） |

⇒ 未改任何 A0–A4 判定书与证据；未改 `pyproject.toml` / `uv.lock`；
未 commit 到 `master` / `origin/master`；未建 PR / 未 merge。

---

*本文件由司仓（GM）生成；F1 是独立修正包，不自证 A3 的 PASS/FAIL。*
