# DD-V1 考场 V1 · 实跑证据（EVIDENCE）

> **交办单**：`cangjie-fos#85`（永久验收红线）＋ `cangjie-teams-channel#108`（正式交办）
> **分支**：`feat/71-ddv1-exam-v1-20261028`｜**基线**：`abc462747e99171415dc405e735773fd9d1335d1`
> **实跑环境**：云沙箱（Python 3.11.2｜pytest 9.2.0｜2 核 / 3 GB）｜**零外部模型调用、零费用**
> **纪律**：下面每个数字都是**本机实跑出来的**，不是设计意图；未跑到的项一律写「未测」。

---

## 0. 一句话结论

**开发面四组测试全绿、全量回归零新增失败；合成考场跑出真实分数（64.5 分）；**
**独立 Reviewer 三轮增量复核：第三轮裁定 PASS（锚点 `b20f8f0`，其自跑子集 86 passed / 0 failed / 0 ERROR）。**
**真实 42 题的业务成绩仍是 `NOT_SCORABLE`** —— 原因不是系统没能力，
而是**标准答案包至今未交付**（`#74` 于 2026-10-22 按波总意见暂停），
**「未接入」≠「不存在」**，本版**没有**补造任何历史分数。

---

## 1. 四组测试（实跑）

### 第 1 组 · 考场/评分/预检/类型判定/主体识别/候选扩展（新增单测）

```
python -m pytest -q tests/test_dd_v1_exam_scoring.py \
  tests/test_dd_v1_exam_preflight.py tests/test_dd_v1_doc_type_resolution.py \
  tests/test_dd_v1_entity_resolution.py tests/test_dd_v1_candidate_expansion.py
```

**结果：75 passed / 0 failed**（评分 18＋预检 13＋类型判定 15＋主体识别 19＋候选扩展 10）

### 第 2 组 · 既有 DD-V1 链路回归（语义检索 / 桥接 / 本地跑 / 六态入口 / 别名）

```
python -m pytest -q tests/test_dd_v1_semantic_retrieval.py tests/test_dd_v1_bridge.py \
  tests/test_dd_v1_local_run.py tests/test_dd_v1_fos71_t5_six_states_entry.py \
  tests/test_dd_v1_alias.py
```

**结果：73 passed / 0 failed**（语义检索 ＋ 桥接 ＋ 本地跑 ＋ 六态入口 ＋ 别名）
★ **本版没有改动任何既有测试断言**。

### 第 3 组 · 合成考场端到端（组包 → 答卷 → 阅卷 → 版本对比）

```
python -m pytest -q tests/test_dd_v1_exam_e2e.py
```

**结果：8 passed / 0 failed**（含「上一轮残留交付清单」回归守卫）

### 第 4 组 · 模拟考场实跑（合成数据、零外部调用）

```
python docs/dd-v1-fos71/ddv1-exam-v1/run_sim_exam.py
```

**结果：跑完五步，产出全部落盘在 `证据/`** —— 见 §2。

---

## 2. 全量回归（与基线同方法、同范围对照）

| 项 | 基线 `abc4627`（**同环境复跑**） | 本分支（**读数取自本文件所在提交**） | 判词 |
|---|---|---|---|
| 跑的范围 | `backend/tests/`（`--ignore=tests/test_ui_smoke_gk.py`） | 同左 | ★ 同方法同范围 |
| 依赖版本 | ★ 与 `uv.lock` 对齐（`openai==2.32.0`） | 同左 | ★ 同环境 ⇒ 数字可比 |
| 用例总数 | **1887** | **1973**（本版新增 **86** 条：20+19+15+13+10+9） | — |
| passed | **1886** | **1972** | — |
| failed | **1** | **1** | ★ **失败集合逐条同源** ⇒ **零新增失败** |
| ERROR | **0** | **0** | ★ ERROR≠FAIL：缺依赖才算 ERROR |

★ **本分支的确数是 `--junitxml` 取的（机器可读）**，不是数进度字符：
`pytest tests/ -p no:cacheprovider --ignore=tests/test_ui_smoke_gk.py --tb=no -q --junitxml=<file>`
⇒ `<file>` 的 `testsuite` 属性：`tests=1973 failures=1 errors=0 skipped=0`（耗时 692.7s），
唯一失败 `test_doctor_script.py::test_doctor_script_exits_zero`。
★ **为什么以前数不出总数（口径更正，Reviewer 第四轮查实）**：
**不是**「重定向到文件时 pytest 不写最后那行」—— 管道给 `cat` 一样没有那行；
真因是仓内 `backend/pyproject.toml` 的 `addopts = "-q --ignore=tests/test_ui_smoke.py"` **已带一个 `-q`**，
命令行再给一个 ⇒ **双 `-q`** ⇒ pytest 抑制了「N passed」那行（`short test summary info` 段仍在）。
⇒ 实测 `-o addopts="" -q` ⇒ 那行会出现。★ **结论：用 `--junitxml` 取确数才是可靠的**（已改）。

★ **独立 Reviewer 自跑的同环境对照**（`/workspace/verify/VERIF_{base,branch}_full.log`）：
基线 **1887 / 1886 passed / 1 failed / 0 ERROR**；本分支 **1970 / 1969 / 1 / 0**
（他复核 `a7eaaa6` 时的字节），失败集合**逐条同源**＝`tests/test_doctor_script.py::test_doctor_script_exits_zero`
⇒ 与我自己的读数一致（差异仅为他复核时比我少 2 条新回归测试）。

★ **依赖对齐后的终局读数**：本分支全量回归 = **1973 条：1972 passed / 1 failed / 0 ERROR**
（Reviewer 处置后复跑；处置前是 1969/1968/1/0），
唯一那条是 `test_doctor_script.py::test_doctor_script_exits_zero`（沙箱缺 `.env` / `node_modules` / 后端依赖
⇒ doctor 报 3 个问题 ⇒ 退出码 1；★ **CI 本身就显式 `--ignore=tests/test_doctor_script.py`**
（见 `.github/workflows/ci.yml`）⇒ 沙箱这 1 条**不计入**代码质量。
★ ★ **GitHub CI（锁定依赖 ＋ 完整环境，含 `tests/test_ui_smoke_gk.py`）全绿**：
两个 required check ＋ Frontend Build Check **全部 success**。

### 2.1 沙箱里那 7 条失败的**真因**（不是代码问题，也不是「我改坏了」）

★ **依赖版本漂移**：沙箱原先装的 `openai` 是 **3.40.0**，而 `backend/uv.lock` 锁的是 **2.32.0**。
openai **3.x 在 `api_key` 为空时直接抛 `OpenAIError`** ⇒ 依赖它构造客户端的用例全红
（`test_dd_material_architecture` 4 条 ＋ `test_dd_redteam` 2 条）。
★ 对齐到锁定版本（`openai==2.32.0`）后：**那 6 条直接变绿**。
★ 剩的 1 条（doctor）是**沙箱环境**（缺 `.env` / `node_modules` / 后端依赖），
且 **CI 显式排除该文件** ⇒ 不计入代码质量。
★ 同一现象在**基线**上同样出现（基线 1887 条里 7 条红）⇒ **同方法同范围对照，本版零新增失败**。

### 2.2 那 7 条失败是**基线就红**的（本版没碰它们）

| 失败用例 | 归因 | 基线是否同红 | 锁定依赖后 |
|---|---|---|---|
| `test_dd_material_architecture.py` × 4 | `openai` 3.40.0 空 api_key 直接抛（§2.1） | ✅ 同红 | ✅ **变绿** |
| `test_dd_redteam.py` × 2 | 同上 | ✅ 同红 | ✅ **变绿** |
| `test_doctor_script.py::test_doctor_script_exits_zero` | 沙箱缺 `backend/.env`、`node_modules`、后端依赖 ⇒ doctor 报 3 个问题 ⇒ 退出码 1；★ **CI 显式排除该文件** | ✅ 同红 | ❌ 仍红（**环境**，非代码） |

★ **判词纪律**：这 7 条**不是**「我改坏了」，也**不是**「环境问题所以不算」——
它们在基线提交上**同样红**（同命令、同环境复跑确认）。
⇒ 本版**零新增失败**；修这 7 条属于**另一条线**（环境/依赖），不在本单范围内。

### 2.3 被排除的 1 个模块（如实标注，不藏）

`tests/test_ui_smoke_gk.py` —— 沙箱**没有 playwright** ⇒ **收集期 ERROR**，
pytest 会**直接中断整场收集**（不是 FAILED）。
⇒ 全量回归统一 `--ignore=tests/test_ui_smoke_gk.py`（基线与本分支**同样排除**）。
⇒ ★ 该模块**未测**，**不得**据此宣称「UI 烟雾测试通过」。

---

## 3. 第 4 组的实跑产物（`证据/`）

| 产物 | 内容 | 关键读数 |
|---|---|---|
| `成绩单.json` | 隔离阅卷成绩单 | `status=SCORED`｜`total_score=64.5`｜理解覆盖 1.0｜作答覆盖 1.0｜召回 0.9｜准确 0.45｜完整交付 0.25｜漏交 0.0｜错交 0.75｜**安全闸 PASS（0 violations）**｜**选材层面 3 条 `WRONG_ENTITY`（单列、不封顶）**｜`examinee_mode=RULE_ONLY`｜`leak_report.leaked=false` |
| `逐题评分明细.tsv` | 逐题：期望材料 / 机器选中 / 命中 / 漏选 / 多交 / 结局 | 8 题：2 × CORRECT、5 × OVER_DELIVERED、1 × WRONG_ONLY |
| `机器答卷.json` | 考生侧产物（**不含标准答案**） | 义务 8｜已理解 8｜已作答 8｜选中 20 件｜**交付 1 件** |
| `版本对比.md` / `.json` | 旧口径 vs 新口径并排 | 旧口径只给 `accuracy`（**无 0—100、无逐题明细、无安全闸分项**）⇒ **旧版本未建立可比基线** |
| `旧版本读数.json` | 旧口径原样读数 | `accuracy=0.0`（**空答卷**下的读数，**不是**历史真实成绩） |
| `预检-*.md` / `.json` | 开考前 Gate | `READY_FOR_FORMAL_SCORING`（退出码 0） |

★ 证据里出现的 `/tmp/ddv1-sim-*` 是**云沙箱的临时目录**（跑完即删）——
用来证明「材料与标准答案都在**仓库外**的受控数据面」；**不含任何真实路径、真实机构或真实材料**。

★ **这个 59.0 分是「规则链、零模型调用」跑出来的**（`mode=RULE_ONLY`）：
AI 语义判断那一路需要模型适配器，**云沙箱内没有外部模型**，
所以**本版没有**任何「模型语义判断」的成绩数字。
★ 分数**低**的两个原因都如实写在这：
① 规则链**多交** 11 件（准确率只有 0.45）—— 这正是「AI 真语义判断」要改进的地方；
② **安全闸命中 1 条 `WRONG_ENTITY`** ⇒ 总分**封顶 59**（见下）。

★ ★ **安全闸与「选材问题」分开记**（独立 Reviewer 增量复核的重要发现）：
合成考场里，规则链为「**主体乙**那道题」**多选（未交付）**了 **3 份主体甲**的材料 ⇒ **选错了法人**。
★ 但这 3 份**从未被交付**（实际交付只有 1 件，而且是对的）⇒
**「交付了错主体的材料」＝ 交付事故（进安全闸、封顶 59）**；
**「只是选中、没交付」＝ 选材质量问题（单列 `selection_mismatches`、不封顶）**。
⇒ 本版成绩单：**安全闸 PASS（0 violations）＋ 选材层面 3 条 `WRONG_ENTITY` 单列**，总分 **64.5**。
★ 这正是 Reviewer 指出的「把『选中』当『交付』⇒ 虚报交付事故并封顶」那个坑，本版已修。
★ 顺带说明：旧口径（安全闸只比「该文件**也在**标准答案里」的情形）**抓不到**
「交了别的主体的材料」——Reviewer 的探针 P8 实测过：旧口径 `safety_gate=PASS`、只进错交率；
本版补上了「多交件」这条线（且按 Reviewer 要求**只对实际交付的件封顶**）。

---

## 4. 本版实跑中踩到、并已修掉的 8 个坑（都留了痕）

| 坑 | 症状（长得像什么） | 真因 | 修法 |
|---|---|---|---|
| ① 主分区改成「不按类型筛证据」 | 六态口径塌成一种（`UNRESOLVED_DOC_TYPE` / `UNKNOWN_ENTITY` 分不出来） | 我把「类型待判定」的义务改成了走**全部主体分簇** + **不筛类型** | **回退**：主分区口径**一字不动**；类型待判定另开**独立分区**（`doc_type_resolution`），**默认关闭** |
| ② `proposed_doc_type` 进了 `required` | 既�� schema 校验失败 | 可选字段被写成了必填 | 移出 `required`，改挂 `OPTIONAL_RESULT_FIELDS`（schema 里在 `properties`，**不在** `required`） |
| ③ `build_meta` **没带 sha256** | 预检**恒**报 `GOLD_FILES_MISSING_IN_LIBRARY`（标准答案明明在库里） | meta 里压根没有内容指纹 | `build_meta` 补**实算完整 64 位** sha256（Manifest 里的 `content_hash` 是**截断 32 位**，两种口径不能混用） |
| ④ 标准答案的 `obligation_id` 挂错对象 | **每题都 `NO_ANSWER`、总分 0**（不报错，很难看出来） | 标准答案用的是清单编号（`R1-O1`），答卷用的是**库内义务主键** | 标准答案必须挂**本次答卷的真实义务 ID**；交接文档已写明「先跑 ⑥⑦ 再写标准答案」 |
| ⑤ 仿真把合成数据写进了**仓库的** `backend/data/dd_v1` | 仓库里多出一个 `SIM-LIB` 库 | 各服务在**导入时**读 `CANGJIE_DD_V1_DATA_DIR` ⇒ 环境变量设晚了 | 脚本里**import 之前**设好；已清理污染（该目录本就被 `.gitignore` 忽略，基线仓里没有） |
| ⑥ 主体登记「没生效」 | 组包时照旧提示「尚未登记权威主体名单」⇒ 91 条义务全 UNCERTAIN、0 交付 | **登记主体是挂在某个库上的** ⇒ 库还没登记 ⇒ 登记无处可挂 | 交接文档加 **⓪ 登记材料库** 一步，并写明「登记库 → 登记主体 → 跑组包」 |
| ⑦ run 的机读产物里**没有** `delivered` 键 | 真机上「明明交付了却总分 0」 | 答卷拿不到交付件数 ⇒ HR-1（0 交付强制 0 分）**误伤** | run 的 JSON 写入**实际交付清单**；`answer` 增加 `--delivered <组包manifest.tsv>`；阅卷端交付件数取「顶层清单 ∪ 逐行归集」 |
| ⑧ RULE_ONLY 模式下答卷「选中 0 件」 | 召回恒 0 ⇒ 考的是「模型跑没跑」，不是「选得对不对」 | 没接模型时 `accepted` 为空 ⇒ 没有任何「选中」 | 兜底取**规则链的 rule_hint**，并在答卷里标 `selection_source=RULE_HINT`（**不冒充模型判断**） |

---

## 5. 未测 / 不可测（如实标注）

| 项 | 状态 | 原因 |
|---|---|---|
| **真实 42 题的业务成绩** | **`NOT_SCORABLE`** | ★ **标准答案包未交付**（`#74` 已暂停）⇒ **「未接入」≠「不存在」**；本版**没有**补造任何历史分数 |
| 模型语义判断的真实效果 | **未测** | 云沙箱**没有外部模型** ⇒ 本版全部实跑均为 `RULE_ONLY`（零调用、零费用） |
| UI 烟雾测试 | **未测** | 沙箱无 playwright（见 §2.2） |
| Windows 真机 | **待刘江** | 需要授权 Windows 环境 + 真实材料 + 人工标准答案 |
| GM 调度 / Lease | **未建立** | GM 运行时是 Mac-local 常驻 daemon，云沙箱内不可用；本轮**未建 cron**（Owner 已令关闭全部定时任务） |

---

## 6. 独立 Reviewer 的裁定与处置（2026-10-29）

**独立 Reviewer 会话** `457341917651075`（Verifier）｜**报告**：`/workspace/verify/REVIEW-REPORT-PR86.md`
（独立探针 11 条红线 + 4 例「AI vs 规则脚本」反例 + 端到端接线探针）

### 6.1 裁定：**CONDITIONAL**

| Reviewer 的结论 | 我的处置 |
|---|---|
| **#85 红线本体全过**（0 分≠NOT_SCORABLE / SHA256 寻址 / 泄漏拦得住 / 安全闸封顶 59 / 不补造历史分） | 保持 |
| **① 考场契约的 `entity_scope` 进不了 run** ⇒ 交接文档让刘江「在契约里声明主体范围」**是空话** | ★ **已修**：`run` 新增 `--contract`，在「摄取清单后、匹配前」把 scope 落到**未指名主体**的义务上（`contract_single:` / `contract_group:`）；端到端探针实测：义务 `entity_scope` 由空变 `contract_single:E01`，`entity_basis=AUTHORITY`；新增回归测试 1 条 |
| **② 真·错主体交付不进安全闸**（只在「该文件也在标准答案里」时才比） | ★ **已修**：安全闸改为**义务级**期望主体/年度比对 ⇒ **多交**的材料也要过闸；新增回归测试 1 条（`WRONG_ENTITY` 命中 ⇒ 闸 FAIL ⇒ 封顶 59）。⚠️ 口径收紧：**主体**（法律事实）两类文件都比；**期间**（派生元数据）**只比多交件** ⇒ 「材料解析出 CURRENT vs 人工写 2024」这类**两种元数据口径**差异不算机器交错年份 |
| **⑫ EVIDENCE §2 把两个环境的数字并排** | ★ **已修**：改成「依赖对齐后的终局读数」，并写清旧环境那 7 条的**真因**（沙箱 `openai` 3.40.0 vs `uv.lock` 2.32.0） |
| **★ 我自己复核时发现的另一个洞**（不在 Reviewer 清单里） | **答卷的「候选」在 CLI 路径上一直是空的**：`_answer_sheet_from_bridge` 读 `o.get("evidence")`，而桥接 JSON 的候选键是 **`"candidates"`** ⇒ 考生答卷**缺来源证据**。★ **已修**（读 `candidates`、回退 `evidence`；并给候选行补 `period` / `doc_type`）⇒ 合成考场答卷的候选从 **0 变 5**（带 sha256 / 路径 / 主体 / 期间） |

### 6.2 第二轮增量复核（Reviewer 的裁定仍是 CONDITIONAL，4 条新问题）逐条处置

| 第二轮的问题 | 我的处置 |
|---|---|
| **① 安全闸把「选中」当「交付」⇒ 虚报交付事故并封顶** | ★ **已修**：主体/期间**只对实际交付的件**进安全闸封顶；「选中但未交付」的错主体/错年份**单列** `selection_mismatches`（**不封顶**）。合成考场读数随之回到 **安全闸 PASS ＋ 3 条选材层面 `WRONG_ENTITY`**，总分 64.5。**新增回归测试 1 条**（选中未交付 ⇒ 不封顶） |
| **② `exp_ent_all.pop()` 是破坏性读取** ⇒ 只有第一件多交材料过闸 | ★ **已修**：改成只读取值（`next(iter(...))`），期望集合两循环共用且不修改 |
| **③ 「期间只比多交件」的收紧只做了一半** ⇒ 多交件仍比期间 | ★ **已修**：**期间一律不比**（交付件与多交件都不比），只比**主体**（法律事实）⇒ 「材料解析出 CURRENT vs 人工写 2024」不再冤枉机器 |
| **④ 契约 scope 粘在库里** ⇒ 换一场考试静默沿用上一场的主体范围 | ★ **已修**：`apply_contract_scope` 现在**可替换** `entity_basis=CONTRACT_SCOPE` 的旧行（并如实报「替换 N 条」）；★ **「落到 0 条」不再打 ✓**，改为打印「⚠️ 本次声明未生效：库里 N 条义务仍带着上一场契约的范围」 |
| **⑤ `outcome_metrics` 的 M03 仍 PASS 15/15** | ★ **已修**：M03 改 `PARTIAL`、按 **8/15** 计（已接线的部分），`progress` 同步为 **73/100**；`check_gccseg.py --require-v3-8` 仍 **PASS** |
| **⑥ 测试文件尾部留着被证伪的旧断言** | ★ **已修**：测试头部改成「只验**自洽性**，**不证伪『这是规则脚本』**」 |
| **⑦ EVIDENCE §2 表格仍是混环境对照** | ★ **已修**：改成「基线与本分支**同环境**（依赖对齐到 `uv.lock`）复跑」的对照，并列出 Reviewer 自跑的同环境数字作旁证 |
| **⑧ 候选行 `doc_type` 空 / 成绩单不落 `leak_report` / `examinee_mode` 是 UNKNOWN** | ★ **已修**：候选行补 `doc_type`；成绩单**没有泄漏时也落** `leak_report`（`leaked=false`）；`examinee_mode` 在桥接路径按选材来源推断（RULE_ONLY / AGENT_SUGGESTION） |

### 6.3 第三轮增量复核（**Reviewer 裁定：PASS**）与残余 4 条次要的处置

★ **第三轮裁定原文结论**：「上一轮 9 条 PASS 全部仍成立；本轮 5 条收口清单逐条闭合且我用**自己的探针**复验过」⇒ **VERDICT = PASS**
（锚点 `b20f8f0`；Reviewer 核了 5 个关键文件的 blob SHA 逐个相同；子集 **86 passed / 0 failed / 0 ERROR**；
合成考场 64.5 / 安全闸 PASS / `selection_mismatches=3` / `delivered_files=1` / `RULE_ONLY`，与我的读数**逐项一致**）。
★ 完整报告：`/workspace/verify/REVIEW-INCREMENTAL2-PR86.md`（Reviewer 自跑，**未改动本仓库任何文件**）。

| 第三轮残余的 4 条「次要」（不阻塞） | 我的处置 |
|---|---|
| **① `selection_mismatch_detail` 的 `delivered` 写死 `False`** ⇒ 既选中又交付的件，成绩单会出现两行互相矛盾的话 | ★ **已修**：selected 循环先查该 file_id 是否在 delivered 集合里 ⇒ 如实标 `delivered=true/false`，文案随之区分。**新增断言**（回归测试里直接核这条） |
| **② EVIDENCE §2 的本分支条数比当前 head 少 1、表头 SHA 陈旧** | ★ **已修**：在**最新字节**上重跑全量（带 `--junitxml` 出**机器可读的确数**）后改成实际数字并更新 SHA（见 §2 表） |
| **③ 「⚠️ 本次声明未生效」分支不可达（死代码）** | ★ **已修**：补上「库里已有的范围**与本次声明一致** ⇒ 声明早已生效过（本次无需改写）」分支（现在三种情形都有话说：已生效 / 替换了旧的 / 未声明主体） |
| **④ 「期间一律不比」还差半步**：选中层的期间差异仍进单列指标 | ★ **已按 Reviewer 给的两个选项之一处置**：**保留**单列（`WRONG_PERIOD`，**不进安全闸、不封顶**），并把文档措辞改成「**期间只影响单列指标**；**主体**才是进安全闸封顶的那一项」⇒ 既满足 #85「错年份一律单列」的红线，又不冤枉机器 |

★ **第四轮「快核」裁定：PASS**（Reviewer 只核这 4 条残余，≈10 分钟）
——「第三轮 PASS 继续成立；①③④ 已闭合并经我复验；**② 在你手上**（我已给确数）。
**本轮未发现新缺陷、无新增阻塞项**」（报告：`/workspace/verify/REVIEW-FAST4-PR86.md`）。
★ Reviewer 给的期望读数 **1973 / 1972 passed / 1 failed / 0 ERROR** 与我用 `--junitxml` 取到的确数**逐项一致**。

★ **Reviewer 收口后核验（PASS 维持，锚点 `896139a`）**：本目录三个 blob 逐个核过
（`最终报告.md`＝`22d27f88410a`、`SHA256SUMS`＝`1ad9bf49d38b`（**15 条**，`sha256sum -c` ⇒ **15 OK / 0 FAILED / 0 missing**，覆盖含 `证据/` 子目录）、
`版本锚点.md`＝`b3b757a9da2a`）；`ddv1-exam-v1/` 下 16 个条目 blob sha 逐个相同；`tools/dd_team_channel.py` mode 仍 **100755** ✔。
★ **唯一未核**：**交接包 zip 本体不在共享工作区** ⇒ Reviewer 记 **NOT_MEASURED（Reviewer 未核）**；
我自跑：解包后逐件复算 **19/19 通过、0 失败**。⇒ 故 G10 的依据在最终报告里**拆成两句**（仓内 ✔／包体 Reviewer 未核）。

★ **`check_gccseg.py --require-v3-8` 的可复跑出处**（Reviewer 第三轮问「该脚本不在仓内也不在工作区」）：
该脚本属**上游规范仓** `bog5d/grill-to-spec`，路径 `scripts/check_gccseg.py`，
blob `af715407fd9c6cd7a5f63296f4bc9127cdbfbe86`，该仓 main tip `d14327c6de89e1afa2fca081f7bf984577a7e5ca`
（本次实跑所用副本 sha256 `c2eadcfcdb4aacf7f7f62416f14cc6e129d1de3b6c22786754927d1f85ccb5ef`）⇒
复跑命令：`python scripts/check_gccseg.py --require-v3-8 <本仓>/docs/dd-v1-fos71/ddv1-exam-v1/GOAL-CONTRACT.json`
⇒ 本仓实跑结果：**PASS**（GCCSEG structural + goal alignment contract）。
| **③ 「AI 真语义 vs 规则脚本」的机器可验分界不成立**（纯规则脚本能通过自洽性检查） | ★ **表述收紧**：测试头部与本文件都改成「只验**自洽性**，**不证伪『这是规则脚本』**」；GOAL-CONTRACT 的 M02 加注 |
| **④ 三个新服务模块生产零调用方** | ★ **诚实降级**：`entity_scope_service` **已接线**（①）；`entity_resolution_service`（多源分级完整实现）与 `candidate_expansion_service`（分批扩展）**本版未接线** ⇒ GOAL-CONTRACT 的 **M03 判 `PARTIAL`**，本文件与交接文档都**不宣称**这两项已生效 |
| **⑤ 预检顶层 status 把「未提供」写成「未映射」** | ★ **已修**：`status` 改为 `TEST_BLOCKED_GOLD_<STATE>`，四态一一对应 |
| **⑥ 预检把 `entity_hint:` 的义务算成「未指名」** | ★ **已修**：`entity_hint:` 前缀算**已指名** |
| **⑦ 交接文档 ⑦ 步的通配符在 PowerShell 跑不起来** | ★ **已修**：CLI 的 `--bridge-json` 现在**自己解析**通配/目录（命中多个取最新并打印说明） |
| **⑧ 成绩单不带「来源模式」** | ★ **已修**：成绩单加 `examinee_mode` 与 `selection_source` 汇总 |
| **⑨ 泄漏检测第 3 条判据在 CLI 路径永不触发** | ★ **已修**：`cmd_grade` 现在传入库内义务 id 集合与 Gold 义务 id 集合 |
| **⑩ 注释说 `content_hash` 是「截断 32 位」——**实测是完整 64 位** | ★ **已修**（这是**我写错的事实**）：注释改正；`build_meta` 直接取 Manifest 的 `content_hash`（实测＝磁盘实算，10/10 相同） |
| **⑪ `build_meta` 每份材料重算 SHA256** ⇒ 真机 1663 份每次阅卷整库重算 | ★ **已修**：改用 Manifest 的 `content_hash`，**不重算** |

★ Reviewer 独立复核的全量回归：基线 `abc4627` = **1887 条 / 1886 passed / 1 failed / 0 ERROR**；
本分支 = **1970 条 / 1969 passed / 1 failed / 0 ERROR**，失败**逐条同源**（`test_doctor_script.py`，
沙箱环境问题，**CI 显式排除该文件**）⇒ **零新增失败**。

---

## 7. 可复跑入口

```bash
# 合成考场（零外部调用、零费用）
python docs/dd-v1-fos71/ddv1-exam-v1/run_sim_exam.py

# 四组测试
cd backend && python -m pytest -q \
  tests/test_dd_v1_exam_scoring.py tests/test_dd_v1_exam_preflight.py \
  tests/test_dd_v1_doc_type_resolution.py tests/test_dd_v1_entity_resolution.py \
  tests/test_dd_v1_candidate_expansion.py
cd backend && python -m pytest -q tests/test_dd_v1_exam_e2e.py

# 全量回归（与基线同方法同范围）
cd backend && python -m pytest tests/ -q --ignore=tests/test_ui_smoke_gk.py
```

★ 跑测试前请先清 `__pycache__`（陈旧 pycache 会**伪造**「改动没生效」）：
`find . -name __pycache__ -type d -prune -exec rm -rf {} +`
