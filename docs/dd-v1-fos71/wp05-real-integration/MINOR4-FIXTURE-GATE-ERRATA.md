# MINOR-4 勘误二次修订 · 合成 fixture 豁免闸口收紧 + 写入门

> 本文件是 **A4 ROUND2 裁定之后的独立修正包**（监工第 38 条①）。
> ★ **A4 的判据条文（A4-1…A4-11）与 A0–A4 裁定书一律未改**；A4-BLIND-EXAM.md 未被本包触碰。
> ★ 本包只改 `tools/dd_v1_local_run.py` 一处闸口判定 + 一个新增守卫函数，并新增一条测试文件。
> ★ 交付物内**零真实客户标识**；探针与守卫用的都是自造合成内容。

---

## 0. 一句话

合成 fixture 的豁免判定被写成了「**原始材料根**在仓内 fixtures 下 **或** **盲化/冻结后**材料根在仓内 fixtures 下」，
而后者是**输出路径** ⇒ 闸口从「输入是不是真材料」退化成「输出落在哪」
⇒ **仓外真实材料只要把输出指到仓内就能被放行**，且其副本被写进仓内（公开仓泄漏面）。

---

## 1. 主张与独立复现

### 1.1 主张（监工第 38 条①）

`tools/dd_v1_local_run.py` 的 fixture 豁免原为：

```python
fixture = (sem._inside(orig_material_root, ROOT / "backend" / "tests" / "fixtures")
           or sem._inside(material_root, ROOT / "backend" / "tests" / "fixtures"))
```

`material_root` 在 `_prepare_material()` 之后 = **盲化/冻结后的输出路径**。

### 1.2 独立复现（四组对照，探针可复跑）

被测代码：`tools/dd_v1_local_run.py`，sha256 `15282351088537ee79f126203ddc26bbfb3582ee2751de59aa6b181b82b56d46`

| 组 | 场景 | 期望 | **修前实测** | 修后实测 |
|---|---|---|---|---|
| A | 仓内合成 fixture（正常流程） | 放行 rc 0 | rc 0 放行 ✓ | rc 0 放行 ✓ |
| C | 仓外材料 + 不盲化 | 拒绝 rc 3 + `BLOCKED: 真实材料` | rc 3 **真实材料闸口** ✓ | rc 3 **真实材料闸口** ✓ |
| B | 仓外材料 + `--blind-material-out` 落**仓内** fixtures | 拒绝 rc 3 | rc 3 **但拒绝语是「DeepSeek Harness 需要显式 --allow-local-dsh」⇒ 闸口已放行** ✗ | rc 3 **写入门拦住** ✓ |
| B' | 同 B，但豁免只按原始材料根 | 拒绝 rc 3 | rc 3 真实材料闸口 ✓ | rc 3 写入门 ✓ |

**修前仓内污染**：B 案与 B' 案**都**把仓外材料正文写进了仓副本
（`backend/tests/fixtures/probe-evilcase/blind/audit_2024.txt`）⇒ **闸口拒绝也来不及**，副本已落盘。

⇒ **主张成立**（绕过 + 泄漏面两半都成立）。修前探针判定：`PROBE_VERDICT=REPRODUCED`，`CRITERIA_ALL_PASS=False`；
修后：`PROBE_VERDICT=FIXED`，`CRITERIA_ALL_PASS=True`。

### 1.3 ★ 探针自身的两处缺陷（如实记录，避免读数被当成产品缺陷）

第一版探针（v1）给出的 `REPRODUCED` 结论**建立在错误读数上**，已作废：

1. v1 把 `items.json` 写在 `.../fixtures/`，而 CLI 读 `.../dd_v1_fos71/` ⇒ A 案 rc=1（假失败）；
2. v1 未传 `--blind-leak-words` ⇒ `blind_material` 先抛 `BLIND_NO_LEAK_WORDS`
   ⇒ B/B' 的 rc=1 发生在**闸口之前**，闸口根本没被走到。

⇒ 纪律：**探针自身报错时不得据此判主张成立/不成立**；v2 修掉两处后才重新取证（本次落盘的即是 v2）。

---

## 2. 修法

### 2.1 P1 闸口收紧（监工第 38 条① 指定口径）

```python
fixture = _fixture_exempt(orig_material_root)      # 只看**原始材料根**
```

`_fixture_exempt()` **只吃一个参数** ⇒ 输出路径（盲化目录 / 冻结目录）**在结构上无法**影响豁免。

★ 未做的事（按监工边界）：没有改成「原始根与冻结后根都在 fixtures 下」；
没有放宽 `dd_v1_semantic_retrieval_service.local_material_snapshot` 的 `allow_real` 语义（该函数未改一行）。

### 2.2 P2 写入门（监工主张的另一半：副本被写进公开仓）★ 显式披露

只修 P1 **不足以**堵住泄漏面：`blind_material()` 在闸口**之前**就把副本写到 `--blind-material-out` /
`--snapshot-freeze-dir` ⇒ 即使随后 exit 3，仓外材料的副本**已经**落进仓库树（修前 B' 案实测污染即此）。

故新增 `_guard_material_output_not_in_repo()`，在**任何写入之前**先拦：
源材料不在仓内 fixture 下时，盲化 / 冻结 / 评估目标一律不得落在仓库树内（仓内合成 fixture 源不受此限）。

★ 这是**监工指定修法之外**的一笔新增，已在此显式披露，供独立 Reviewer 判定。

---

## 3. 判据（回归守卫 5 条 + 探针 4 组）

新增 `backend/tests/test_dd_v1_minor4_fixture_gate.py`（sha256 `ee7e10b13bc0c1fcfb634e80abee5b24a573a7b105a6bec09acff2f1907eecbf`）：

| 判据 | 内容 | 修前 | 修后 |
|---|---|---|---|
| T1 | 仓外材料 + 不盲化 ⇒ exit 3 + `BLOCKED: 真实材料` | 绿 | 绿 |
| T2 | 仓外材料 + 盲化输出落**仓内** fixtures ⇒ exit 3 **且仓内零材料副本** | **红** | 绿 |
| T3 | 仓内合成 fixture（正常流程）⇒ exit 0 | 绿 | 绿 |
| T4 | 豁免规则只认原始材料根；且规则**只吃一个参数** ⇒ 输出落点无法影响 | **红** | 绿 |
| T5 | `cmd_run` 交给闸口的 `allow_real` **只**由该规则决定（单一来源，无第二处判定） | **红** | 绿 |

★ **判别力已验证**：把 `tools/dd_v1_local_run.py` 回退到原始态后重跑 ⇒ **3 红 / 2 绿**（T2/T4/T5 红）；
打上修复 ⇒ **5 绿**。T1/T3 修前也绿是预期的（这两条守的是本来就成立的两条）。

★ T2 的**修前失败详情**即烟枪：拒绝语是「拒绝：DeepSeek Harness 需要显式 --allow-local-dsh」
⇒ 真实材料闸口**早已放行**，流程一路走到适配器。

★ 测试纪律：T2 需要「仓内 fixtures」时一律在**仓副本**（tmp）上跑（副本的 ROOT 由副本位置决定）；
测试**不写/不删仓库文件**；仓外材料用自造合成内容（零真实客户标识）。

---

## 4. 零回归

同一套件在**基线树**（master `d9bd8e8`）与**修正树**各跑一遍，比对**失败集**：

- 同一套件在**基线树**（`master` = `d9bd8e8`，1702 条）与**修正树**（本包，1707 条 = +5 条守卫）
  各跑一遍（`pytest -q --tb=no -rf`），**失败集逐条相同**（`diff` 为空 ⇒ `ZERO_REGRESSION=YES`）：

| 失败用例 | 条数 | 性质 |
|---|---|---|
| `tests/test_dd_material_architecture.py`（Phase1/Phase2 refine 用例） | 4 | 环境性既红：缺 `socksio` |
| `tests/test_dd_redteam.py::TestPromptInjection`（refine 用例） | 2 | 环境性既红：缺 `socksio` |
| `tests/test_doctor_script.py::test_doctor_script_exits_zero` | 1 | 环境性既红：缺 `.env` / `node_modules` |

- 修正树新增的 5 条守卫用例 **全绿**；全量用例数 1702 → 1707。
- 判别力（原始输出见 `regression-tests.txt`）：修前 **3 红（T2/T4/T5）+ 2 绿（T1/T3）** ⇒ 修后 **5 绿**。

---

## 5. 边界披露

- 未改 A2/A3 判据条文；未改 A4 ROUND2 判据（A4-1…A4-11）；未改 A0–A4 裁定书；未改 `A4-BLIND-EXAM.md`。
- 未改 `dd_v1_semantic_retrieval_service.py`（`local_material_snapshot` 的 `allow_real` 语义保持原样）。
- 未新建第二调度器；未解除任何熔断或人工批准闸；未改客观门基线。
- 交付物（本文、探针、两份读数、守卫测试）**零真实客户标识**；探针用的仓外材料为自造合成文本。
- 修法**只影响本地 CLI 的材料闸口**：仓外材料仍须显式 `--allow-real-material`；仓内合成 fixture 流程不受影响（T3 绿）。

---

## 6. 复跑

```bash
# 探针（四组对照；默认仓根 = 本脚本所在仓；--python 指向装了依赖的解释器）
python3 docs/dd-v1-fos71/wp05-real-integration/a4-evidence/minor4-fixture-gate/probe_minor4_fixture_gate.py \
    --python backend/.venv/bin/python --label 本机复跑

# 回归守卫（5 条）
cd backend && .venv/bin/python -m pytest tests/test_dd_v1_minor4_fixture_gate.py -v
```

★ 修前读数可用**回退 `tools/dd_v1_local_run.py`** 复现（把探针判据里的 B/B' 两组转红即为绕过复现）。
