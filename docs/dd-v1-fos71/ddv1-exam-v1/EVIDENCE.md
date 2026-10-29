# DD-V1 考场 V1 · 实跑证据（EVIDENCE）

> **交办单**：`cangjie-fos#85`（永久验收红线）＋ `cangjie-teams-channel#108`（正式交办）
> **分支**：`feat/71-ddv1-exam-v1-20261028`｜**基线**：`abc462747e99171415dc405e735773fd9d1335d1`
> **实跑环境**：云沙箱（Python 3.11.2｜pytest 9.2.0｜2 核 / 3 GB）｜**零外部模型调用、零费用**
> **纪律**：下面每个数字都是**本机实跑出来的**，不是设计意图；未跑到的项一律写「未测」。

---

## 0. 一句话结论

**开发面四组测试全绿、全量回归零新增失败；合成考场跑出真实分数（64.5 分）；**
**独立 Reviewer 三轮增量复核：第三轮裁定 PASS（锚点 `b20f8f0`（★本地历史 sha，REST 重建后仓内已不存在），其自跑子集 86 passed / 0 failed / 0 ERROR）。**
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
（锚点 `b20f8f0`（★本地历史 sha，REST 重建后仓内已不存在）；Reviewer 核了 5 个关键文件的 blob SHA 逐个相同；子集 **86 passed / 0 failed / 0 ERROR**；
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

★ **Reviewer 收口后核验（PASS 维持，锚点 `896139a`（★本地历史 sha，REST 重建后仓内已不存在））**：本目录三个 blob 逐个核过
（`最终报告.md`＝`22d27f88410a`、`SHA256SUMS`＝`1ad9bf49d38b`
　　⚠️ **这两个 blob 是历史快照：那个 `SHA256SUMS` blob 里的清单是「当时」的 15 条，不要拿它当当前口径**（★ **当前**目录的清单是 **16 条**）
　　⇒ **当前口径只认本目录的 `SHA256SUMS` 文件本身**：`sha256sum -c SHA256SUMS` ⇒ **16 OK / 0 FAILED / 0 missing**，覆盖含 `证据/` 子目录）、
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

## 8. 第 5 轮（2026-10-29 接线轮）：三个模块「从零调用方 → 真实组包链上的调用方」

> 上一轮 Reviewer 判 M03=PARTIAL 的根因是**生产链路零调用方**（模块写好了、也测过了，
> 但真实组包里根本没走它们）⇒ 本轮逐条接线，并把「接线证据」落到**机读读数**上。

### 8.1 本轮改了什么（不动判定逻辑）

| 模块 | 上一版 | 本版 |
|---|---|---|
| 多源主体识别 | `dd_v1_entity_resolution_service` 完整实现，**生产零调用方** | 接进 `dd_v1_match_service.evaluate_file`：主口径判「认不出（SUBJECT_UNREGISTERED）」时**补位**；主口径已判命中/他法人的**一律不动**；留痕 `subject_matched_by` / `subject_multi_source` 落 `dd_v1_matches.evidence` |
| 候选分批扩展 | `dd_v1_candidate_expansion_service` 完整实现，**生产零调用方** | 接进 `dd_v1_match_service.match_library`：触顶义务自动分批放大窗口（步长从 cap **之上**起步 ⇒ 不重复第一窗）；扩展后的结论**替换**原结论、库级判定分布按新结论重算 |
| 模型参与 | 回执格式有，答卷**不带**模型选材 | `dd_v1_agent_adapters` + `dd_v1_bridge_service` + `dd_v1_exam_service`：适配器实现决定参与类别；模型选材进机器答卷（`selection_source=MODEL`） |

### 8.2 机读读数（我在本地实跑，同一份合成夹具）

| 读数 | 修复前 `2a4ea18` | 修复后 `fd9bb21` |
|---|---|---|
| 机读结果顶层有 `candidate_expansion` | **无此字段**（模块零调用方） | **有** |
| 触顶义务数 | 无此读数 | 8（a5 夹具，池 32 份 > 上限 20） |
| 实际检查候选 | 20/义务（触顶即止） | **32/义务（池已穷尽）** |
| 「还剩多少没看」 | **无此读数 ⇒ 静默漏检** | 0（**且确为 0**：池已穷尽） |
| 扩展步长 | — | `[60, 180]`（从上限之上起步） |
| 触顶义务的结论变化 | — | 上限=2 那轮 **6/8 条 verdict 变了** |
| 停因分布 | — | `VERDICT_STABLE` × 8 |
| 模型参与类别 | 恒 `RULE_ONLY` | 分 6 档（`HARNESS_MODEL` / `HARNESS_MANUAL` / `PREBAKED_RESULT` / `UNKNOWN_ADAPTER` / `MODEL_SELECTION_WITHOUT_RECEIPT` / `RULE_ONLY`）｜★ 第 5 轮复核后**按适配器实现类判定**（不再只看自填 `adapter_id`）⇒ `PREBAKED_RESULT` 也**真正可达**了 |

### 8.3 修复前后对比（同一合成考场）：**分数没变**，如实记

| 对照 | 夹具/上限 | before | after |
|---|---|---|---|
| 触顶扩容 | a5（池 32 份）/ 20 | 51.86 | **51.86** |
| 窗口太窄 | a4 / 2 | 64.5 | **64.5** |
| 标准考场 | a4 / 20 | 64.5 | **64.5** |

★ **为什么分数不变（不是 excuses，是考场的性质）**：
合成考场的答卷来自 `answer --bridge-json <尽调结果-*.json>` ⇒ 选中**就是本次 run 窗口内的可交付候选**
（★ 更正：**不是**来自夹具预置的 `replies/` —— 脚本根本没读 `replies/`）；
但**扩出来的候选进不了「选中」集合**（过不了可交付闸 / 内容冲突闸），
「交付了什么」又由**披露策略**决定（合成考场未配策略 ⇒ 按最严 ⇒ 不可交付）
⇒ ⇒ **分数在结构上就对「候选窗口」不敏感**。
⇒ ⇒ a5 上多出的 24 份硬负样本与正解件**同主体/同期间/同类型** ⇒ 触发**内容冲突闸**
⇒ ⇒ 扩窗口**解决不了冲突**（冲突要人工裁定）。
⇒ ⇒ **本轮不主张「分数提高」**，主张「**覆盖到的候选从 20 份变成 32 份，且不再静默漏检**」。

★ ★ **同时必须说清的另一半（否则就是不完整）**：**扩窗确实会改「判定」，只是没改「分数」。**
自己复跑（同夹具、同脚本、只有代码不同）：

| 库级判定分布 `summary.by_verdict` | before（`2a4ea18`） | after（当前 head） |
|---|---|---|
| a4 · cap=2 | **`RESTRICTED` × 8** | **`CONFLICT` × 6 ＋ `RESTRICTED` × 2**（6/8 条 verdict 变了） |
| a5 · cap=2 | `CONFLICT` × 6 ＋ `RESTRICTED` × 2 | 同左（0 条变化） |
| a5 · cap=20 | `CONFLICT` × 6 ＋ `RESTRICTED` × 2 | 同左（0 条变化） |

⇒ 「本轮只改覆盖率、没改判定」**不准确**（已更正）；准确说法是：
**扩窗改判定**（看得更全 ⇒ 内容冲突闸能开火）**不改分数**（冲突件选不中也交不出去）。
★ before 侧机读产物**已补存**：`/workspace/work/ab/{before,after}_cli*/`、`/workspace/work/ab/a4_{before,after}_cli_cap2/`。

★ 完整报告：`/workspace/work/ab/AB-成绩对比.md`（仓内副本：`docs/dd-v1-fos71/ddv1-exam-v1/AB-成绩对比.md`）。

### 8.4 本轮自检抓到的**自己引入的**缺陷（已修）

★ `dd_v1_bridge_service.bridge_library`：`agent_receipt` / `model_sel` 的初始化写在 `else:` 分支**内部**，
而返回体无条件读它们 ⇒ ⇒ **空材料库/空义务**时 `UnboundLocalError` ⇒ 崩。
⇒ **既有**测试 `tests/test_dd_v1_bridge.py::test_bridge_on_empty_library_does_not_raise` 当场抓住
（全量回归 2003 条 / 2 failures ⇒ 除基线那条 doctor 外多这一条）。
⇒ 已修（初始化提到分支之外）⇒ 复跑子集 **74 tests / 0 failures / 0 errors**。

★ **教训（跨项目可复用）**：**接线类改动必须跑全量**，不能只跑自己新写的测试
—— 接线改的全是**既有链路**（bridge/答卷/阅卷），只跑新测试会漏掉这类崩溃。

### 8.5 新增回归（本轮）

| 文件 | 条数 | 覆盖 |
|---|---|---|
| `backend/tests/test_dd_v1_wiring_entity_expansion.py` | 10 | 多源补位的正例（文件名/正文命中）、反例（认不出仍认不出）、**判别力**（关掉接线 ⇒ 正例必须回到认不出）、扩展找到窗口外那份、读数到最外层容器、未看数如实报、可关闭 |
| `backend/tests/test_dd_v1_model_participation.py` | **23** | 参与身份只认适配器实现、预置回执不算 Harness、R4 排除项硬校验（4 条）、排除式读数 PASS/WEAK、答卷层 MODEL vs RULE_ONLY、「有模型选材但没回执」必须被标出、端到端（桥接 → 答卷） |

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

---

## 9. 第 5 轮复核（CONDITIONAL）修复的证据

★ Reviewer 第 5 轮（锚点 `5dfaa4f`（★本地历史 sha，REST 重建后仓内已不存在））裁定 **CONDITIONAL**，抓到 3 条重要缺陷 ＋ 1 条条件项。
本节给出**修法**与**可复现的负向证据**。

### 9.1 缺陷 ①：候选扩展路径丢掉人工确认映射

- **真因**：`dd_v1_candidate_expansion_service.match_with_expansion()` 调
  `ms.match_obligation(..., candidate_cap=cap, db_path=db_path)` —— **没传** `confirmed_map`；
  接线层 `dd_v1_match_service._expand_capped_obligations()` 同样**没透传**。
  ⇒ 触顶义务（正是最需要人工确认的那批）的**最终结论**是在「无人工确认口径」下算出来的，
  主体依据从 `HUMAN_CONFIRMED` 掉回 `BODY_TEXT`/`UNRESOLVED`，最强一档证据被抹掉。
- **修法**：两层都透传 `confirmed_map` ⇒ **扩展后的结论与第一遍同一套口径**。
- **负向证据**：`backend/tests/test_dd_v1_wiring_entity_expansion.py::test_expansion_keeps_human_confirmed_evidence`
  —— 跑在缺陷前字节 `a0324a9` 上 **变红**（扩展后留痕里没有 `HUMAN_CONFIRMED`）。

### 9.2 缺陷 ②：参与身份只按自填 `adapter_id` 判定

- **真因**：`adapter_provenance(adapter_id)` 是**字符串查表** ⇒ `class _SpoofAdapter: adapter_id = "codex-cli"`
  即得 `HARNESS_MODEL` ⇒ 回执里出现一条**假凭据**。
- **修法**：**判定入口换成适配器实现类**——
  `dd_v1_agent_adapters.ADAPTER_PARTICIPATION_CLASSES`（**精确类型匹配**，子类也不认）
  ＋ `dd_v1_bridge_service.adapter_participation_class(adapter_object)`。
  - id 级查表**降级为旁证**：回执里改记 `declared_provenance`（id 级声明）＋
    `provenance_mismatch`（声明与实现不一致 ⇒ 会被标出来）＋ `provenance_source="ADAPTER_IMPLEMENTATION"`。
  - 回执补**可核验运行痕迹**：`executable`（真正被调起的可执行文件）、`argv_digest`（sha256）、
    `workdir_digest`（sha256）—— 只留指纹，不留材料内容。
- **负向证据**：`test_spoof_adapter_with_known_id_is_not_credited_as_model`、
  `test_bridge_receipt_judges_identity_by_implementation_not_by_id`
  —— 两条在缺陷前字节 `a0324a9` 上**都变红**。

### 9.3 缺陷 ③：`PREBAKED_RESULT` 不可达

- **真因**：`KNOWN_HARNESS_ADAPTERS` 里没有 `prebaked-result` ⇒ 真正的 `PrebakedResultAdapter`
  在 id 级查表里落 `UNKNOWN_ADAPTER` ⇒ **与文档口径「预置回执 ⇒ `PREBAKED_RESULT`」不符**。
- **修法**：白名单补 `prebaked-result → PREBAKED_RESULT`；实现类注册表里同样登记
  ⇒ **两类口径一致**，且**仍不是** `HARNESS_MODEL`（贴进来的回执永远不算本机 Harness 运行）。
- **负向证据**：`test_prebaked_result_is_not_a_harness_run`（缺陷前字节 **红**）。

### 9.4 条件项 ④：`file_id` 大写查表键静默不命中

- **真因**：只归一「行内键」、不归一「表内键」 ⇒ 表里写 `FILE-ABC`、行内 `file_id=file-abc` ⇒ 对不上
  ⇒ 看起来像「人工没确认过」，实际是**写法**不同。
- **修法**：`dd_v1_entity_resolution_service._confirmed_index()`：表内键同时登记
  「原样／去空白小写／归一文件名」三种写法 ⇒ 命中与否只取决于**内容**，不取决于**写法**。
- **负向证据**：`test_confirmed_map_key_case_does_not_matter`（缺陷前字节 **红**）。

### 9.5 负向回归的整体执行方式（可复现）

```bash
git worktree add /workspace/work/fosgit_prefix a0324a9      # 缺陷前字节
cp backend/tests/test_dd_v1_model_participation.py  /workspace/work/fosgit_prefix/backend/tests/
cp backend/tests/test_dd_v1_wiring_entity_expansion.py /workspace/work/fosgit_prefix/backend/tests/
cd /workspace/work/fosgit_prefix/backend && PYTHONPATH=src \
  pytest tests/test_dd_v1_model_participation.py tests/test_dd_v1_wiring_entity_expansion.py \
  --junitxml=/workspace/work/junit_prefix.xml
```

★ 实测：**8 failed / 27 passed** ⇒ 这 **8 条**确实打到点上**（在缺陷前字节上红、在修复后字节上绿）。

### 9.6 修复后的全量回归（最终字节 `b7d2ff9` → `9d6e13b`）

```bash
cd /workspace/work/fosgit/backend && PYTHONPATH=src \
  pytest tests/ -p no:cacheprovider --ignore=tests/test_ui_smoke_gk.py --tb=no -q \
  --junitxml=/workspace/work/junit_final4.xml
```

★ 读数（**已按第 9 轮修复后的最终字节重跑**）：**tests=2019 / failures=1 / errors=0 / skipped=0**
- 与上一轮（接线字节 `d7aa3b0`）的 **2003** 条相比 **+5**（＝本轮新增的 5 条负向回归：model_participation +3、wiring +2）；
- **失败集合仍只有一条**：`tests/test_doctor_script.py::test_doctor_script_exits_zero`
  （沙箱缺 `.env`/`node_modules`/后端依赖；★ **CI 本身就显式 `--ignore` 这一条**）
  ⇒ **零新增失败**；
- 基线 `abc4627` 同环境为 1887/1886/1/0 ⇒ 本分支 **2019/2018/1/0**（相对上一版 2008 条 **+11** ＝ 第 6 轮 5 条 ＋ 第 7 轮 2 条 ＋ 第 8 轮 F21 2 条 ＋ 第 9 轮 F24／F25 2 条）。
- ★ 逐文件条数差（机器对账）：`test_dd_v1_model_participation` 23→**33**（**+10**）、`test_dd_v1_wiring_entity_expansion` 12→13（**+1**）⇒ 合计 **+11**，与上条一致。
- ★ 失败集合**只有** `tests.test_doctor_script::test_doctor_script_exits_zero`（沙箱环境项）⇒ **零新增失败**。

### 9.7 第 6 轮独立复核在新 head 上抓到的两处（已修）

★ 复核（新 head `35de52cb3cf2`）**独立复现**了两处，均已修：

**① 答卷层仍采信适配器自填的 `provenance` ⇒ 自填即可冒充「模型参与」（重要）**

- **真因**：`dd_v1_exam_service.build_answer_sheet` 读 `adapter["provenance"]` 的**第一个非空值**；
  而 `adapter.provenance` 是**适配器自己写的自由字段**（`AdapterResult.provenance`）
  ⇒ 一份 `run_record.json` 把它写成 `"HARNESS_MODEL"` ⇒ 机器答卷就自称「有本机 Harness 参与」
  ⇒ 与第 5 轮修掉的「自填 `adapter_id`」**同族**，但落在**答卷层**这第二个入口上。
- **修法**：**只认「盖章」** ——
  - 参与类别必须带 `provenance_source == "ADAPTER_IMPLEMENTATION"` 才采信；
  - 盖章由**实现侧**产生：`dd_v1_semantic_retrieval_service.run_semantic` 在 run_record 里盖
    （`rec["model_participation"]`，provenance 来自 `ad.participation_class_of(adapter)`）、
    `dd_v1_bridge_service` 的回执带 `provenance_source`、`tools/dd_team_channel.py` 把它带进答卷；
  - 适配器自填的那一档**只记进 `examinee.declared_provenance`**（留痕、可查、**不作数**）。
- **负向回归**：`test_answer_sheet_refuses_unstamped_provenance`、
  `test_answer_sheet_honors_stamped_provenance`（跑在修复前字节 `fe939b6` 上 **3 red**）。

**② 查表键归一造成误命中 ⇒ 人工确认反了（重要）**

- **真因**：`_confirmed_index` 把「归一后的写法」也塞进**精确档**
  ⇒ 表里的 `FILE-ABC` 会用它的归一形 `file-abc` **占掉** `file-abc` 那一条
  ⇒ 行内 `file_id=file-abc` 的材料被判成**另一个主体**。
- **修法**：**两级查表** —— ① 精确档**只放原样键**（原样键优先 ⇒ 各归各的）；
  ② 大小写不敏感档**只作兜底**（表里写 `FILE-ABC`、行内 `file-abc` 仍能命中）。
- **负向回归**：`test_confirmed_map_exact_key_wins_over_case_variant`（修复前字节 **红**）。

**③ 措辞收紧**：参与类别判定**不是安全边界** —— 进程内代码理论上能替换实现
（monkeypatch / 改 `__class__`）⇒ 挡的是「自填字段/自造替身冒充」这一类；
真正不可伪造的那一段是**下游只认盖章**（伪造要连盖章一起造 ⇒ 那就不是「自填」了）。

### 9.8 第 6 轮复核（复裁）的判词与本轮修复

★ 独立复核（新 head `35de52cb3cf2`）裁定 **CONDITIONAL**：第 5 轮那 3 条重要缺陷**代码层已闭合**
（复核方自跑负向回归复现了「8 red / 27 passed」），但**新抓到 4 处**。逐条处置如下。

| # | 发现 | 严重度 | 处置 |
|---|---|---|---|
| F1 | **Harness 没跑出回执，答卷/成绩单却自称 `HARNESS_MODEL`**（exit 127／回执未贴／文件不存在 ⇒ `participated` 其实是 false） | 重要 | **已修**：参与类别与「真的跑出回执」**拆成两件事** —— 新增 `participated`（由 `ad.participated_flag()` 判定：`status==OK` 且有 `raw_text`）；**没跑出回执 ⇒ `examinee.mode` 记 `RULE_ONLY`**，`provenance` 仍留身份那一档，`degrade_reason` 写明原因 |
| F2 | `_confirmed_index` **误命中**（表里 `FILE-ABC` 的归一形占掉 `file-abc` 那条 ⇒ 人工确认反了）＋ docstring「原样键优先」**不实** | 重要 | **已修**：**两级查表** —— 精确档**只放原样键** ＋ 大小写不敏感档**只作兜底** |
| F3 | 「参与类别只认实现类」**端到端不成立**（答卷读适配器自填的 `provenance`） | 重要 | **已修**：**只认盖章**（`provenance_source=ADAPTER_IMPLEMENTATION`），盖章由**实现侧**产生并随回执落盘；自填那档只记 `declared_provenance` |
| F4 | `--run-dir` 路径机读产物里出现 **Python dict repr**（`"{'independent_examinee_answer': False}"`） | 重要 | **已修**：不是合法类别值的 `declared_provenance` 一律记 `UNDECLARED`（不把 dict repr 写进机读产物） |
| F5 | 「可核验运行痕迹」三字段是**适配器自报**的（可被替身伪造）＋ 不派生进程的适配器这三项为空 | 条件项 | **已修（措辞）**：文档改为「只作**旁证**，不能单独当『跑过』的证据」；不派生进程的适配器这三项为空（已写明） |
| F6 | 类属性 `participation_class` **没人读**（自填字段留在最显眼的地方） | 条件项 | **已修**：注册表改为**由类属性生成** ⇒ 类属性成为**唯一来源**（不再是「没人读的自填字段」） |
| F7 | `__class__` 改写可绕过精确类型匹配（进程内代码能替换实现） | 条件项（威胁模型的边界，进程内无法根治） | **已修（措辞）**：写清「挡的是**自填字段/自造替身冒充**；进程内改实现挡不住；不可伪造的那一段是**下游只认盖章**」 |
| F8 | 包级 `SHA256SUMS` 条数写 **15**，实际 **16** | 文档 | **已修**（`最终报告.md` G10 ＋ `EVIDENCE.md`） |
| F9 | 引用了**仓内不存在**的本地历史 sha（`b20f8f0`／`896139a`／`5dfaa4f`）⇒ 读者无法从仓内核对 | 文档 | **已修**：这几处一律标注「★本地历史 sha，REST 重建后仓内已不存在；可核的是它引用的 blob sha」 |
| F10 | G9 写「三轮、第三轮 PASS」**陈旧**（未反映第 5/6 轮 CONDITIONAL） | 文档 | **已修**：G9 改判 **PARTIAL**（复核已跑 6 轮；本分支第 5/6 轮为 CONDITIONAL ⇒ 收口判词待下一轮复裁；前四轮 PASS 维持，其判词针对**上一版**） |
| F11 | 「这 6 条」应为「这 8 条」 | 文档 | **已修** |
| F12 | AB 报告 §0 的 after 锚点陈旧 | 文档 | **已修**（改为「可核的是产物文件本身」＋ 标注本地历史 sha） |

★ **负向回归口径（★ 作用域 ＋ 文件版本，两个都要写清）**：
★ **作用域 ＝ `test_dd_v1_model_participation.py`（33）＋ `test_dd_v1_wiring_entity_expansion.py`（13）＝ 当前 46 条**
（测试文件取自 head，拷到各缺陷前字节跑），`--junitxml` 确数：
★ `a0324a9` ⇒ **19 red**｜`fe939b6` ⇒ **11 red**｜`2d42995` ⇒ **7 red**｜`cf81685`（第 8 轮被复核的 head）⇒ **5 red**；
★ **累计（并集）＝ 19**；包含关系（**机器验过**）：`cf81685` ⊂ `2d42995` ⊂ `fe939b6` ⊂ `a0324a9`。
★ ★ **口径纪律**：复核方第 9 轮实测 **17／9／5／3**（**作用域相同、但测试文件版本少 2 条 F24／F25 用例**）
⇒ 差值恰为新增条数 ⇒ **同一把尺子、互相印证**（不是「两把尺子」）。
⇒ ★ **凡报红数必带「作用域（哪几个文件／多少条）＋ 测试文件版本」** —— 同一个字节、换个文件版本，读数就会变。
★ ★ **一条「契约变更导致的红」要单独说清**：`test_failed_harness_run_must_not_claim_model_participation`
在 `2d42995`／`cf81685` 上红，**不是**它自己坏了，而是**它断言的措辞随契约变了**
（旧字节写的正是 F21 指出的那句**不实**的话）⇒ 它同时**就是 F21 的证据**。
★ ★ **一条「契约变更导致的红」要单独说清**：`test_failed_harness_run_must_not_claim_model_participation`
在 `2d42995`／`cf81685` 上红，**不是**它自己坏了，而是**它断言的措辞随契约变了**
（旧字节写的正是 F21 指出的那句**不实**的话）⇒ 它同时**就是 F21 的证据**。
★ 历史文档里写的「4 red / 累计 7」**是错值**（既不是复核方的 5／13，也不是本席的 19／11／7／5）⇒ 已在 §9.11 与本节更正。
★ **12 文件子集（作用域＝ bridge / semantic_retrieval / local_run / exam_scoring / exam_preflight / exam_e2e /
wiring_entity_expansion / model_participation / agent_result / six_states_entry / candidate_expansion / entity_resolution）**
＝ **232 passed / 0 failed / 0 errors**（本席实跑，`--junitxml` 确数，2026-10-29 12:1x）
｜★ 复核方第 9 轮实测 **230**（**同一作用域、测试文件版本少 2 条 F24／F25 用例**）⇒ **互相印证**。


### 9.9 `--run-dir` 路径的**实跑**三例（复核方点名要验的那条）

★ 第 6 轮复核问：「人工贴回执（`HARNESS_MANUAL`）的路径还能不能正确落到 `HARNESS_MANUAL`？」
⇒ 我用真实 CLI（`tools/dd_team_channel.py answer --run-dir <目录>`）实跑三例：

| 情形 | `examinee.mode` | `provenance` | `provenance_source` | `participated` | `declared_provenance` |
|---|---|---|---|---|---|
| 盖章 ＋ **跑出回执**（人工贴回执） | **`HARNESS_MANUAL`** ✔ | `HARNESS_MANUAL` | `ADAPTER_IMPLEMENTATION` | `true` | `UNDECLARED`（dict **不进产物**） |
| **无盖章**（旧 run_record） | `RULE_ONLY`／`UNKNOWN`（按有无义务行） | 空 | 空 | **`false`**（安全侧） | `HARNESS_MODEL`（**留痕、不作数**） |
| 盖章 ＋ **跑失败**（exit 127） | **`RULE_ONLY`** ✔（不自称模型参与） | `HARNESS_MODEL`（**身份那一档仍留痕**） | `ADAPTER_IMPLEMENTATION` | `false` | 空 |

★ 复现：`answer --run-dir <含 run_record.json 的目录> --out <输出目录>`；机读产物＝`机器答卷-*.json` 的 `examinee` 段。
★ 自查时发现并已修：原先**无盖章**时 `participated` 默认报 `true`（字段在说谎）⇒ 改为默认 **false**（安全侧：认不出就当没有参与）。

### 9.10 一处**如实记账**：远端历史里有一条**重复提交**

★ 我在推 `2d42995` 时把范围写成了 `d0e85be^..2d42995` ⇒ 该范围**含**已在远端的 `d0e85be`
⇒ REST 重建时又建了一条**内容相同、sha 不同**的孪生提交（远端 `cbabe93e` ≡ 本地 `d0e85be`）。
⇒ **处置**：★ **不做** force／改写已落字节（只做前向更正）⇒ 这条重复**留在历史里**，在此**如实记录**。
⇒ **对内容的影响：无**（远端 tip 的文件内容已逐路径核对 **142/142 一致**；tip 的 tree 与本地 HEAD 的 tree **逐位相同**）。

★ ★ **续：自查时又查出更细的一层（已在 helper 修掉）** ——
  `rest_push.py` 取 blob 内容时读的是**工作树文件**，**不是**该提交的内容
  ⇒ 我推 `d0e85be` 时工作树**已经**含下一条提交（`2d42995`）的改动
  ⇒ 远端那条「`d0e85be`」的 tree **静默带上了后面的改动**
  ⇒ 后果：远端 `cbabe93e`（消息是 d0e85be）内容 = `2d42995` 的内容；
  而后一条 `14d929b`（消息是 2d42995）**成了空提交**（与前者同 tree）。
⇒ **核过的事实**：`20c9abe6`（首次推的 d0e85be）内容**正确**（仍是 `_participated = True`）；
  `cbabe93e`／`14d929b`／`e60cd8d`（tip）内容 = 最终正确内容；★ **tip 的内容与本地 HEAD 逐路径一致（142/142）**。
⇒ **处置**：★ **不 force、不改写已落字节**（只做前向更正）⇒ 这两处历史瑕疵**留在历史里**，在此如实记录。
⇒ **已修 helper**：`rest_push.py` 改为 `git show <commit>:<path>` 取 blob（⇒ 提交内容与消息不会再错位）。
⇒ **教训**：★ **推之前先算准范围**（`rest_push.py <base>..<tip>` 的 base 必须是**远端已有**的那条，
  不是「上一条本地提交」）—— 范围算错 ⇒ **多推一条**（幂等护栏只能挡「重跑同一条」，挡不住「范围算错」）。

### 9.11 第 7 轮复核（CONDITIONAL）的处置：F14／F15／F16／F17／F18

★ 独立复核（第 7 轮，head `17859a0`）裁定 **CONDITIONAL**：
★ **F1–F4、F19 已复验闭合 ✔**（复核方自跑子集 **885 passed / 1 failed**，唯一红＝沙箱 doctor 环境项）；
★ **仍开的重要项只剩 F14**，另有 F15／F16／F17／F18 四条文档/实现项。逐条处置如下。

| # | 发现 | 严重度 | 处置 |
|---|---|---|---|
| **F14** | **`--bridge-json` 路径上「真跑了的模型参与」被记成 `RULE_ONLY`**，且 `degrade_reason` 写着**不实**的「这次没跑出回执」 | **重要** | **已修（两处都补）**：① `dd_v1_bridge_service` 的 `model_participation` 块补 **`provenance_source`（取自 `agent_receipt`）** ＋ `run_participated` ＋ `declared_provenance`；② `tools/dd_team_channel.py` 构造 `rec["adapter"]` 时补 **`participated`**。★ **根因**：答卷层的取值循环**只认带盖章的源**（F3 的纪律）⇒ 这两处**都没带盖章** ⇒ 循环**整个跳过** ⇒ 落到 `rec["adapter"]` 的 `bool(None)` ⇒ **永远 False** ⇒ 类别判成 `RULE_ONLY` ⇒ 且理由写成了「没跑出回执」（**那句当时是假的**） |
| **F15** | AB 报告 §0 的 after 锚点陈旧（`fd9bb21` 在远端**查无此 commit** ⇒ 读者无从核对） | 文档 | **已修**：该 sha 与 `2a4ea18` 一律标注为「**本地历史 sha、未上远端**」；并写明**真正可核的是产物文件本身**（本目录 `证据/` ＋ `SHA256SUMS`） |
| **F16** | `dd_v1_agent_adapters.py` 的 `UNKNOWN_ADAPTER` 定义在推导式**之后**（靠 `or` 短路侥幸没炸）⇒ 再加一个**没有** `participation_class` 属性的适配器类 ⇒ `NameError at import` ⇒ **整个 backend 起不来** | 重要（可致命） | **已修**：常量**上移**到 `ADAPTER_PARTICIPATION_CLASSES` **之前**；已验证 `import OK` |
| **F17** | 负向回归的**红数口径**在文档里写错（「4 red / 累计 7」） | 文档 | **已修**（并于第 8 轮**再修一次**：把「作用域」也写进数字旁）⇒ 现口径 ＝ **作用域 46 条**（两文件）＋ **测试文件版本**：见 §9.8 的完整口径表 |
| **F18** | 答卷层**未读盖章块自带的 `declared_provenance`** ⇒ 人工贴回执路径记 `UNDECLARED` 而非 `HARNESS_MANUAL` ⇒ **审计信息丢了** | 重要 | **已修**：自填值**不是合法类别**时，回落到**盖章块**的 `declared_provenance`（只认盖章块 ⇒ 与 F3 同一条纪律；合法值照旧保留 ⇒ 不改既有行为） |

★ **负向回归口径（★ 作用域 ＋ 文件版本，两个都要写清）**：
★ **作用域 ＝ `test_dd_v1_model_participation.py`（33）＋ `test_dd_v1_wiring_entity_expansion.py`（13）＝ 当前 46 条**
（测试文件取自 head，拷到各缺陷前字节跑），`--junitxml` 确数：
★ `a0324a9` ⇒ **19 red**｜`fe939b6` ⇒ **11 red**｜`2d42995` ⇒ **7 red**｜`cf81685`（第 8 轮被复核的 head）⇒ **5 red**；
★ **累计（并集）＝ 19**；包含关系（**机器验过**）：`cf81685` ⊂ `2d42995` ⊂ `fe939b6` ⊂ `a0324a9`。
★ ★ **口径纪律**：复核方第 9 轮实测 **17／9／5／3**（**作用域相同、但测试文件版本少 2 条 F24／F25 用例**）
⇒ 差值恰为新增条数 ⇒ **同一把尺子、互相印证**（不是「两把尺子」）。
⇒ ★ **凡报红数必带「作用域（哪几个文件／多少条）＋ 测试文件版本」** —— 同一个字节、换个文件版本，读数就会变。
★ ★ **一条「契约变更导致的红」要单独说清**：`test_failed_harness_run_must_not_claim_model_participation`
在 `2d42995`／`cf81685` 上红，**不是**它自己坏了，而是**它断言的措辞随契约变了**
（旧字节写的正是 F21 指出的那句**不实**的话）⇒ 它同时**就是 F21 的证据**。
★ ★ **一条「契约变更导致的红」要单独说清**：`test_failed_harness_run_must_not_claim_model_participation`
在 `2d42995`／`cf81685` 上红，**不是**它自己坏了，而是**它断言的措辞随契约变了**
（旧字节写的正是 F21 指出的那句**不实**的话）⇒ 它同时**就是 F21 的证据**。
★ **F14／F18 两条负向回归**（缺陷前字节上确实变红）：
`test_cli_bridge_json_path_keeps_real_participation`（F14）、`test_answer_sheet_falls_back_to_stamped_declared_provenance`（F18）
⇒ 在 `2d42995` 上 **2 red**（F14 ⇒ `mode=RULE_ONLY` ＋ 不实理由；F18 ⇒ `UNDECLARED`），在当前字节上 **全绿**。
★ 两条都只存在于 `test_dd_v1_model_participation.py`；`test_dd_v1_wiring_entity_expansion.py` 的 3 条红是**第 6 轮 F2** 的查表用例。

★ ★ **一个值得记住的坑**：F14 那条负向回归**第一版是「绿的但测不到东西」** ——
因为测试里造的桥接结果**带模型选材** ⇒ bridge 块那个「选材口径」的 `participated=True` **恰好**把缺陷掩盖了
⇒ 真跑缺陷（`2d42995`）也是 `mode=RULE_ONLY`（**复现不出来**）。
⇒ 正解：负向回归的场景必须是「**跑过、但建议全被确定性闸拒了**」（accepted=0 ⇒ 无模型选材）——这才是复核方实跑到的组合。

### 9.12 第 8 轮复核：新抓到并已修的三条（F21／F22／F23）

★ 第 8 轮独立复核（head `1d3916953d4b`）**复验闭合了 F14／F15／F16／F18／F20**（并确认 F1–F4、F19 未回归），
★ **F17** 由本席**在同轮内**认领并已修（口径问题，见 §9.8）。
★ **本轮新抓到 3 条**，逐条处置如下。

| # | 发现 | 严重度 | 处置 |
|---|---|---|---|
| **F21** | **「选材口径」冒充「回执口径」**：机读产物里有两个 `participated` 味的字段，**含义不同**（`model_participation.participated`＝「有义务用了模型选材」；`agent_receipt.participated`／`run_participated`＝「这次真的跑出了回执」）。★ 上一版在「盖章块缺 `run_participated`」时**退回选材口径** ⇒ 在「回执说跑过、但选材口径是 False」时会**误判成「没跑出回执」**，还写出**不实的**理由 | 重要 | **已修（口径显式化 ＋ fail-closed）**：① 产出侧统一加**口径标记** `participated_scope`（`RECEIPT` ／ `SELECTION`）与 `run_participated_scope`；② 答卷层**只采信标了 `participated_scope == "RECEIPT"` 的源**；③ 只有选材口径 ⇒ **fail-closed（当作没有参与）**，**绝不**拿选材口径冒充回执口径；④ `degrade_reason` **不再无条件断言**具体成因（不写「这次没跑出回执」这种可能不成立的话），改为只陈述**确实知道**的事（拿不到可采信的回执口径参与标记）＋ 成因列为**可能** |
| **F22** | 文档里「12 文件子集 **226 passed**」**陈旧**（历次随用例增加而变：228 → 230 → **232**） | 文档 | **已修**：三处（`EVIDENCE.md`／`最终报告.md`／`CLAUDE.md`）统一改为 **232 passed / 0 failed / 0 errors**，**并把「作用域＝哪 12 个文件」写在数字旁**（本席实跑，`--junitxml` 确数） |
| **F23** | 交接说明里**没写**「两个 `participated` 字段含义不同」⇒ 操作员读桥接 JSON 里的 `model_participation.participated` 极易误读成「模型有没有参与」 | 文档 | **已修**：`WINDOWS-HANDOFF.md` 的核验清单补一段**口径对照**（哪个字段是回执口径、哪个是选材口径、该看哪个） |

★ **F21 的负向回归**（缺陷前字节 `cf81685` 上**真红**（3 red 中的 2 条），当前字节全绿）：
`test_answer_sheet_never_uses_selection_scope_as_receipt_scope`（情形 A：盖章块只有选材口径 False ＋ 回执口径 True ⇒ 旧版误判 RULE_ONLY）、
`test_degrade_reason_does_not_assert_unproven_causes`（旧版无条件断言「这次没跑出回执」）。
★ ★ **既有 4 条用例已按新契约更新**（补 `participated_scope: RECEIPT` ＋ 措辞断言改为「拿不到可采信的回执口径参与标记」）
⇒ ⇒ **这不是「把测试改绿」，是把「口径」从隐含约定变成显式契约**（旧形状不再被默认采信）。

### 9.12b 远端落盘的**一处如实记账**（第 8 轮这轮）

★ 推第 8 轮修复时，本席给 REST helper 的范围是 `f63520b..70096a7` ⇒ **只推出了一条提交**（`70096a7`），
  而本地链上是**两条**（`f63520b`＝F17 口径更正、`70096a7`＝F21／F22／F23）。
★ **第一反应**：「`f63520b` 没推上去 ⇒ 远端缺 F17 的口径更正」——**这是错的**，已现读远端对象态核清：
  远端 tip `d24c2dabfdf0` 的 **tree ＝ `e2d4330ff873` ＝ 本地 `70096a7` 的 tree（逐位相同）**
  ⇒ ★ **F17 的口径更正在远端**（因为 `70096a7` 那些文档 blob 本身就是**累积**的 ⇒ 含 F17 的更正）。
★ ⇒ **教训（与 §9.10 同一个）**：判「远端有没有这次改动」**只认远端对象态（tree／逐路径 blob sha）**，
  **禁**凭「我推了几个 sha」推断；★ 推的**范围**参数写窄了 ⇒ 提交条数会少，但**内容**可能仍是对的 ⇒ 两者要分开判。

### 9.13 第 8 轮复核的判词与本轮处置（F21／F22／F23 ＋ F17 口径更正）

> **第 8 轮独立复核（2026-10-29 · head `1d3916953d4b`）**：判词 **CONDITIONAL（文档级）**。
> ★ 复核方**逐条实跑**确认闭合：**F14**（合成 bridge JSON ＋ 真实 CLI `--agent prebaked` ⇒ `mode='PREBAKED_RESULT'`；
> 缺陷前字节 `2d42995` 上同一条命令给 `RULE_ONLY`）｜**F15**（并用只读 REST 核了 `fd9bb21`／`2a4ea18` 远端确实 Not Found）｜
> **F16**（重跑地雷探针：加一个无该属性的类不再 NameError）｜**F18**｜**F20**｜**F1–F4、F19 无回归**。
> ★ 复核方自跑全量（CI 等价）：**2013 passed / 0 failed / 0 errors**（EXIT=0）⇒ 与本席的 2015/2014/1/0 **完全自洽**
> （doctor 那条被 CI 显式 ignore）⇒ **失败集合为空**。
> ★ 本轮新抓到 **3 条**：**F21**（条件项·代码：选材口径冒充回执口径）｜**F22**（文档·计数陈旧）｜**F23**（文档·机读产物字段语义缺口）。
> ★ 复核方明确：**「①②③ 落地后我这一轮就能给 PASS」**（①②＝F17 口径、②＝F22 三处计数、③＝F23 交接清单）⇒
> 本席已全部落地并**追加**了 F21 的代码修法 ⇒ **第 9 轮复裁进行中** ⇒ **M03 仍为 `PARTIAL`**（不预告 PASS）。

★ **F21 的修法（与复核方建议同向，并按其「永不回落到选材口径」的要求做成 fail-closed）**：
| 产出侧 | 加**口径标记**：`participated_scope`（`RECEIPT`／`SELECTION`）、`run_participated_scope`（`RECEIPT`） |
|---|---|
| 消费侧（答卷层） | **只采信标了 `RECEIPT` 的源**；只有选材口径 ⇒ **fail-closed**（当作没有参与）⇒ **绝不拿选材口径冒充回执口径** |
| 理由文案 | `degrade_reason` **不再无条件断言**具体成因（不写「这次没跑出回执」这种可能不成立的话）⇒ 只陈述**确实知道**的事（拿不到可采信的回执口径参与标记）＋ 成因列为**可能** |

★ **既有 4 条用例按新契约更新**（补 `participated_scope: RECEIPT` ＋ 措辞断言改为「拿不到可采信的回执口径参与标记」）
⇒ ★ **这不是「把测试改绿」，是把「口径」从隐含约定变成显式契约**（旧形状不再被默认采信）。
★ **F21 负向回归**：`test_answer_sheet_never_uses_selection_scope_as_receipt_scope`（情形 A：回执说跑过、选材口径是 False ⇒ 旧版误判 `RULE_ONLY`）、
`test_degrade_reason_does_not_assert_unproven_causes`（旧版无条件断言成因）⇒ 在缺陷前字节 `cf81685` 上**真红**，当前字节全绿。

### 9.14 第 9 轮复核的判词与本轮处置（F24／F25）

> **第 9 轮独立复核（2026-10-29 · head `e304bb6a6253`）**：判词 **CONDITIONAL** ——
> ★ **本轮没有未闭的重要项**、**没有假凭据**、**没有数据错**、**没有回归失败**；只剩 **2 条条件项**（F24／F25）。
> ★ 复核方**独立实跑**：全量 **2017 / 2016 passed / 1 failed（doctor 环境项）/ 0 ERROR**（与本席逐位一致）｜
> 12 文件子集 **230 passed**（逐位一致）｜负向回归 `a0324a9` 17／`fe939b6` 9／`2d42995` 5／`cf81685` 3／并集 17（逐位一致，含机器验过的包含关系）。
> ★ ★ **对本席「被更新过的 4 条既有用例有没有被削弱」的正面答复**：复核方**做了变异测试**
>   （把 F1 缺陷重新塞回答卷层 ⇒ 更新后的用例**照样变红**）⇒ **断言仍咬得住原缺陷**；
>   并逐条核了改动面（「4 条只在 fixture 上加了 `participated_scope`，**行为断言一条没动**」；
>   `degrade_reason` 的断言由「**必须说出某个具体成因**」换成「**只准说确实知道的** ＋ **禁止说那句假话**」⇒ **净变强**）。
> ★ 复核方还独立核了 §9.12b 的远端记账（远端 `d24c2dab…` 的 tree ＝ 本地 `70096a7` 的 tree，逐位相同）⇒ 属实。

★ **F24（条件项·测试护栏 ＋ 文档与代码一致）** 三小条全部处置：

| 小条 | 复核方的发现 | 本席处置 |
|---|---|---|
| ① | F14 那条端到端用例**仍在用旧契约形状**（fixture 无口径标记），它还能过靠的是消费侧那行**兼容逃逸** ⇒ **不再证明新契约端到端成立** | **已修**：该用例的 fixture 换成**新契约形状**（`participated_scope: SELECTION` ＋ `run_participated_scope: RECEIPT` ＋ 回执侧 `participated_scope: RECEIPT`）；**另留一条「旧形状」兼容用例**（旧 JSON 无口径标记 ⇒ 盖章块被跳过 ⇒ CLI **从回执重新盖章** ⇒ 仍判 `HARNESS_MODEL`） |
| ② | bridge 侧的 `run_participated` / `run_participated_scope` **零测试保护**（突变测试：删掉它们，全套 60 条仍全绿）⇒ **不变式只靠一个生产者撑着** | **已修**：新增 `test_bridge_emits_participation_scope_contract` — **直接断言产出侧真的写了契约字段**、且 `run_participated == bool(回执.participated)`（**不是**选材口径） |
| ③ | 交接清单写「以 `participated_scope` 为准」，而代码还会采信**没标记、只带 `run_participated` 键**的源 ⇒ **规则按字面写与代码行为不完全一致** | **已修（代码侧收紧，不改文档去迁就代码）**：**删掉那条兼容逃逸** ⇒ 现在**只认带口径标记的源**（`participated_scope == RECEIPT` ／ `run_participated_scope == RECEIPT`），其余一律 fail-closed ⇒ **文档规则与代码逐字一致**；新增 `test_unmarked_participated_key_is_not_trusted` 守住它 |

★ **F25（条件项·一句措辞）**：`degrade_reason` 原先对**两种不同情形**用**同一句话**
⇒ 「回执口径的标记**在、且明确为假**」（F1 那个最常见场景：exit 127／CALL_FAILED）也被说成「**拿不到**可采信的标记」⇒ **不准确**。
⇒ **已修（2 行 + 1 处外露）**：
① `_part_scope` **外露**为 `examinee.participated_scope`（`RECEIPT` ／ `SELECTION_ONLY` ／ `NONE`）⇒ 读者能看出判词从哪来；
② 措辞**分两种情形**：「**回执口径的参与标记为假**（回执明确说：这次没跑出回执）」／「**拿不到可采信的回执口径参与标记**（可能是：…）」。
⇒ ★ 既有 2 条用例按新契约更新，且**断言更强**（已知成因 ⇒ 必须直说且**不得**带「可能是」猜测清单；未知成因 ⇒ 必须带猜测清单且**不得**说「没跑出回执」）。

★ **本轮新增/更新的 4 条用例在缺陷前字节上真红**（`cf81685`）：`test_degrade_reason_does_not_assert_unproven_causes`／
`test_bridge_emits_participation_scope_contract`／`test_unmarked_participated_key_is_not_trusted` ⇒ **3 red**；
（F14 那条按设计**不在** `cf81685` 上红 —— 那个缺陷在 `2d42995` 上，见 §9.11。）
