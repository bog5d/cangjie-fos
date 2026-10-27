# 交卷 · cangjie-fos#71 R2-WP1（期间语义四态）

- **交卷对象**：`feat/71-player2-r2-wp1-period-semantics` 分支 R2 线（考生2）
- **被验 head**：`fb0e42f3ac8d28a10360b5440204afadb98b797c`
- **对照基座**：#81 分支 tip `16e18b21f261fb97e22352a64cc64ebb289c74ea`（现读）｜**merge base**：`d1ebe3392fb20f04c2d0ecb00bbe639804187ac2`（＝ PR #83 的 base.sha）
- **取数时刻（UTC）**：`2026-10-23T14:31:47Z`（当场程序化取）
- **本件性质**：交卷文档（登记面）；**不含任何独立裁定**，不构成通过结论。
- ★**本文件是纯文档**（0 代码字节）⇒ 上表读数所用 head 与本文件的**父提交**相同 ⇒ 两者被验**代码字节逐位相同**。

## 1 登记口径（定案句 · 逐字）

> 仅单年 EXPLICIT 分支受相对期间闸保护；散落年份轴（≥2 散落年份 ⇒ 推断区间）为已知残留，方向为区间放大导致假阳性放行。

- 同一句在**产品注释面**（`dd_v1_period_service.py`，笔 E ＋ 笔 F 落）与**台账**（§八十八）一致。
- **散落年份轴的机械读数**（我方在终态 head 上自跑，非转述）：
  输入「请提供截至2024年的近三年审计报告（另有2019年存档）」⇒ 现行判 `EXPLICIT`，`years` 为 2019 至 2024（六年区间），`basis` 为 `INFERRED` ⇒ 相对期间字面「近三年」被静默丢弃、
  窗口**放大** ⇒ 方向为**假阳性放行**；该轴位于 C-1 闸之前且先行 return ⇒ **对 C-1 闸零判别力**。
- 对照（受闸保护的单年轴）：「请提供近三年的审计报告（报告期截至2024年6月30日）」⇒ 现行判 `RELATIVE`。

## 2 读数三件套（每跑批：collected／failures／errors／skipped／退出码 ＋ 失败 ID 全集）

★ collected 口径＝**junit XML 的 tests 属性**（单份＝该次跑批那一份 junit）；`--collect-only` 求和仅作交叉核对（两者相等）。
★ 两侧跑批**同一 `--ignore`**（`tests/ --ignore=tests/test_doctor_script.py -q`）、同一命令形状。

| 读数面 | collected | failures | errors | skipped | 退出码 | 窗口(UTC) | 失败 ID 全集 |
|---|---|---|---|---|---|---|---|
| 阶梯 1（同树复现）· 树＝`16e18b21f261fb97e22352a64cc64ebb289c74ea`×`0351386f1d18dde3c4bc7f4d1d9b7009676c76a6` | 1794 | 0 | 0 | 5 | 0 | 2026-10-23T13:54:07Z → 2026-10-23T14:04:16Z | （空） |
| 终态 merge 面 · 树＝`16e18b21f261fb97e22352a64cc64ebb289c74ea`×被验 head | 1814 | 0 | 0 | 5 | 0 | 2026-10-23T14:05:19Z → 2026-10-23T14:15:28Z | （空） |
| 终态 head 树 | 1809 | 0 | 0 | 5 | 0 | 2026-10-23T14:16:29Z → 2026-10-23T14:28:25Z | （空） |
| doctor **单独**跑批（与批次分列） | 2 | 1 | 0 | 0 | — | — → — | tests.test_doctor_script::test_doctor_script_exits_zero |

★ ps 采样（每跑批落盘，**本 checkout 内 pytest 主进程恒为 1**；自己进程的 PID 留痕）：
  · ladder1_same_tree    PYTEST_PID=73617｜PS_SAMPLES=287｜PS_MAX_PROCS=1｜PS_MAX_PROCS_GLOBAL=1｜PS_CWD=/workspace/fos-wt-merge/backend
  · final_merge          PYTEST_PID=76831｜PS_SAMPLES=287｜PS_MAX_PROCS=1｜PS_MAX_PROCS_GLOBAL=1｜PS_CWD=/workspace/fos-wt-merge3/backend
  · final_head           PYTEST_PID=79857｜PS_SAMPLES=337｜PS_MAX_PROCS=1｜PS_MAX_PROCS_GLOBAL=1｜PS_CWD=/workspace/fos-wt-r2D/backend
  ★ 跑前跑后快照：HEAD 同一、`git status --porcelain` 空 ⇒ **跑批窗口 0 checkout**。

## 3 那条耗时型断言的三态定性 ＋ 机械证

- 断言原文：`assert inc_s < full_s`（两侧算子均为 `time.perf_counter()` 测量值）⇒ **零余量的纯耗时序比较**；
  同函数 docstring 自称「阈值刻意宽松」而实现无容差带 ⇒ **该红不能作红灯依据、该绿也不能作绿灯依据**。
- **阶梯 1（同树复现 1 次）＝绿** ⇒ 该树**红绿可翻转** ⇒ 归「**零余量耗时型**」⇒ 按阶梯口径，
  阶梯 2（隔离单跑）与阶梯 3（3 组交错）**均不需要**。
- 历史两次红的**两侧算子都在变**（合并面那次 0.35850304899940966 < 0.25968767999984266；
  笔 A 树那次 0.2875512099999469 < 0.25665000600019994）⇒ 区间比翻转，非某常量被改。
- **0 改产品逻辑、0 放宽断言、0 改尺子**；本地若仍红 ⇒ 登记为「已定性的耗时型」并交齐
  ①失败 ID ②机械证 ③三态定性 ④断言字节事实 交独立 Reviewer 评（**不由施工席自评**）。

## 4 平台权威读数（平台读数优先于本地读数；每推一笔重开一次 run，不外推）

| 被验 head | check | id | 结论 | 起止(UTC) |
|---|---|---|---|---|
| fb0e42f3ac8d28a10360b5440204afadb98b797c | （rollup＝PENDING） | | | |
| fb0e42f3ac8d28a10360b5440204afadb98b797c | Backend Tests (440+ required) | 120455703712 | IN_PROGRESS／None | 2026-10-23T14:00:27Z → None |
| fb0e42f3ac8d28a10360b5440204afadb98b797c | Backend Tests (228 required) | 120455703485 | COMPLETED／SUCCESS | 2026-10-23T14:00:26Z → 2026-10-23T14:04:36Z |
| fb0e42f3ac8d28a10360b5440204afadb98b797c | Frontend Build Check | 120455703093 | COMPLETED／SUCCESS | 2026-10-23T14:00:27Z → 2026-10-23T14:00:48Z |

## 5 T4 覆盖清单（净变更面按 merge base 计，命令用 `diff-tree -r`）

- `git merge-base(#81 tip, 被验 head)`＝`d1ebe3392fb20f04c2d0ecb00bbe639804187ac2`（＝ PR #83 的 base.sha ⇒ 两口径一致）
- 净变更面＝**25 条路径**（`diff-tree -r`；`git diff` 口径条数相同，⚠ 部分克隆下 `git diff` 会静默返回空 ⇒ 一律用 `diff-tree -r`）

| 状态 | 路径 | 被验 head 上的 blob | 是否在 Gate 覆盖内 |
|---|---|---|---|
| M | `.github/workflows/ci.yml` | `fdf0e0cca7d8b25ef0ba2a0573e184f8e9aea382` | **须补覆盖**（点名 4 条 ＋ 笔 D 新增 1 条） |
| M | `backend/src/cangjie_fos/services/dd_v1_agent_result_service.py` | `03fd3b36190a4d10dab5ab18d3ba699409bcca24` | **须补覆盖**（点名 4 条 ＋ 笔 D 新增 1 条） |
| A | `backend/src/cangjie_fos/services/dd_v1_period_service.py` | `10e42c22098be4735a70027f1a7320217cdd7db7` | 否（新文件，Gate 须覆盖） |
| M | `backend/src/cangjie_fos/services/dd_v1_semantic_retrieval_service.py` | `63d13d1f001f64520d35f5d903087e0cfdffe76b` | **须补覆盖**（点名 4 条 ＋ 笔 D 新增 1 条） |
| A | `backend/tests/test_dd_v1_fos71_r2_wp1_entry_wiring.py` | `b95b4edc640c521e59f65c241d2221ecffedb0d4` | 否（新文件，Gate 须覆盖） |
| A | `backend/tests/test_dd_v1_fos71_r2_wp1_period.py` | `f2fb04ee2eba32f6f0d95852b2f0b1df52ee0295` | 否（新文件，Gate 须覆盖） |
| A | `backend/tests/test_dd_v1_period_service.py` | `0ae978ed6922d5ed521dad786c795cbb2fb1d0dd` | 否（新文件，Gate 须覆盖） |
| A | `docs/dd-v1-fos71/player2-r2-wp1/README.md` | `600e268c30340e8822a415a2a3e2b27910b627a5` | 否（新文件，Gate 须覆盖） |
| A | `docs/dd-v1-fos71/player2-r2-wp1/before_after_period.py` | `8071dccfadcd7321beb21fdc6ac47ab7cef09b35` | 否（新文件，Gate 须覆盖） |
| A | `docs/dd-v1-fos71/player2-r2-wp1/run_with_ps_evidence.sh` | `c1b6e605094f4735afb92959985fc952aaee7cab` | 否（新文件，Gate 须覆盖） |
| A | `docs/dd-v1-fos71/player2-r2-wp1/shape_probe.py` | `ce4b7ec13c51fb222d410b214fc9f120f1310078` | 否（新文件，Gate 须覆盖） |
| A | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/BUNDLE-DISCLOSURE-20261023.md` | `dbc3f5e77e733b6a6d5aae211832f69a2188ec67` | 否（新文件，Gate 须覆盖） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/01-input-checklist.tsv` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/01-input-checklist.tsv` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/02-retrieved-materials.tsv` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/02-retrieved-materials.tsv` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/03-match-verdicts.tsv` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/03-match-verdicts.tsv` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/04-gaps-and-uncertainty.tsv` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/04-gaps-and-uncertainty.tsv` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/05-human-review-step.md` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/05-human-review-step.md` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package-manifest.tsv` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package-manifest.tsv` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package/S2/F004_shili_business_license.txt` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package/S2/F004_shili_business_license.txt` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package/\346\234\252\351\200\211\347\224\250\346\270\205\345\215\225.tsv` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package/\346\234\252\351\200\211\347\224\250\346\270\205\345\215\225.tsv` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package/\347\273\204\345\214\205manifest.tsv` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package/\347\273\204\345\214\205manifest.tsv` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package/\350\242\253\346\213\246\346\210\252\346\270\205\345\215\225.json` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/06-delivery-package/\350\242\253\346\213\246\346\210\252\346\270\205\345\215\225.json` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| D | `docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/07-repro-commands-and-evidence.txt` | `fb0e42f3ac8d28a10360b5440204afadb98b797c:docs/dd-v1-fos71/wp05-real-integration/a4-evidence/seven-item-bundle/07-repro-commands-and-evidence.txt` | 否（**他席**「公开面清零」笔所删；随附披露文件） |
| M | `tools/dd_team_channel.py` | `ebd2fbb8cab4b2a335b2d8f4c0188120cff46c57` | **须补覆盖**（点名 4 条 ＋ 笔 D 新增 1 条） |
| M | `tools/dd_v1_local_run.py` | `3981543733ca643b0caaab255de77729ff8a964b` | **须补覆盖**（点名 4 条 ＋ 笔 D 新增 1 条） |

★ 合并面与 head 树的 blob 对照（4＋1 条「须补覆盖」路径）：

| 路径 | 被验 head blob | 合并面 blob | 同字节 |
|---|---|---|---|
| `backend/src/cangjie_fos/services/dd_v1_agent_result_service.py` | `03fd3b36190a4d10dab5ab18d3ba699409bcca24` | `03fd3b36190a4d10dab5ab18d3ba699409bcca24` | 是 |
| `backend/src/cangjie_fos/services/dd_v1_semantic_retrieval_service.py` | `63d13d1f001f64520d35f5d903087e0cfdffe76b` | `63d13d1f001f64520d35f5d903087e0cfdffe76b` | 是 |
| `.github/workflows/ci.yml` | `fdf0e0cca7d8b25ef0ba2a0573e184f8e9aea382` | `fdf0e0cca7d8b25ef0ba2a0573e184f8e9aea382` | 是 |
| `tools/dd_v1_local_run.py` | `3981543733ca643b0caaab255de77729ff8a964b` | `f23f89692879e093c9ffbd9db10b174040796fb1` | **否** |
| `tools/dd_team_channel.py` | `ebd2fbb8cab4b2a335b2d8f4c0188120cff46c57` | `ebd2fbb8cab4b2a335b2d8f4c0188120cff46c57` | 是 |

★ 合并树与 head 树的差异（逐条列名）：
  · A　backend/tests/test_dd_v1_minor4_fixture_gate.py
  · A　docs/dd-v1-fos71/ci-ocr-toolchain/EVIDENCE-CI-OCR.md
  · A　docs/dd-v1-fos71/ci-ocr-toolchain/FULL-RUN-READING.md
  · A　docs/dd-v1-fos71/ci-ocr-toolchain/SHA256SUMS
  · A　docs/dd-v1-fos71/ci-ocr-toolchain/SKILLS-REVIEW.md
  · A　docs/dd-v1-fos71/ci-ocr-toolchain/TEST-EVIDENCE.md
  · A　docs/dd-v1-fos71/wp05-real-integration/MINOR4-FIXTURE-GATE-ERRATA.md
  · A　docs/dd-v1-fos71/wp05-real-integration/a4-evidence/minor4-fixture-gate/README.md
  · A　docs/dd-v1-fos71/wp05-real-integration/a4-evidence/minor4-fixture-gate/SHA256SUMS.txt
  · A　docs/dd-v1-fos71/wp05-real-integration/a4-evidence/minor4-fixture-gate/probe-result-after.json
  · A　docs/dd-v1-fos71/wp05-real-integration/a4-evidence/minor4-fixture-gate/probe-result-before.json
  · A　docs/dd-v1-fos71/wp05-real-integration/a4-evidence/minor4-fixture-gate/probe_minor4_fixture_gate.py
  · A　docs/dd-v1-fos71/wp05-real-integration/a4-evidence/minor4-fixture-gate/regression-tests.txt
  · M　tools/dd_v1_local_run.py

## 6 T3 语义解（`tools/dd_v1_local_run.py`；**不推 #81**）

- 两侧标记**字面**（合并结果里逐项现读计数）：

| 来源 | 标记字面 | 合并面命中处数 |
|---|---|---|
| #81 侧（OBS-1 两道 fail-closed 门） | `gm-fix-minor4-fixture-gate` | 2 |
| #81 侧（OBS-1 两道 fail-closed 门） | `gm-fix-minor4-write-guard` | 2 |
| #81 侧（OBS-1 两道 fail-closed 门） | `_fixture_exempt` | 2 |
| #81 侧（OBS-1 两道 fail-closed 门） | `_guard_material_output_not_in_repo` | 2 |
| R2 侧（笔 D 接线，local_run） | `_period_anchor_arg` | 3 |
| R2 侧（笔 D 接线，local_run） | `period_anchor=anchor` | 3 |
| R2 侧（笔 D 接线，team_channel） | `_period_spec_view` | 3 |
| R2 侧（笔 D 接线，team_channel） | `_config_anchor` | 3 |

- ★**两侧同时保住**（OBS-1 两道门各 2 处 ＋ 笔 D 接线标记在位）⇒ **不出现「直接取 R2 侧」那种静默丢门**。
- 合并结果**不等于任一侧**（第三方合成字节）⇒ 无一侧的 hunk 被丢弃。
- 合并面 tree＝`55e2383386adee9ab70ec37752a334ecdab84836`；**本地合并 commit 未推送**（等 Gate 结论后再谈 T2／T3 落 #81）。

## 7 锚点（路径 ＋ 字节 ＋ sha256 ＋ 取数时刻 UTC ＋ 代码路径的 blob）

| 路径 | 字节 | sha256 | 取数时刻(UTC) | blob |
|---|---|---|---|---|
| `backend/src/cangjie_fos/services/dd_v1_period_service.py` | 30087 | `4f67ed097b46b44faa78bd4552bf248d1e569afc477cf896d51eac3cd9c0c8b6` | 2026-10-23T14:31:47Z | `10e42c22098be4735a70027f1a7320217cdd7db7` |
| `backend/src/cangjie_fos/services/dd_v1_agent_result_service.py` | 13615 | `8e3a9863ed112fda3abb97d1996965370f2dac081da670ba0d7b11a7e55d406b` | 2026-10-23T14:31:47Z | `03fd3b36190a4d10dab5ab18d3ba699409bcca24` |
| `backend/src/cangjie_fos/services/dd_v1_semantic_retrieval_service.py` | 55724 | `020d2aec4b1529bbfe8e263b6ef65f7026440e16726ffc2889812c8e2e4e11ea` | 2026-10-23T14:31:47Z | `63d13d1f001f64520d35f5d903087e0cfdffe76b` |
| `backend/tests/test_dd_v1_period_service.py` | 18614 | `537b47a62c5bbf5779ca1fce062ceb6b8f663b50b5765c70b33c1c74e4c714ef` | 2026-10-23T14:31:47Z | `0ae978ed6922d5ed521dad786c795cbb2fb1d0dd` |
| `backend/tests/test_dd_v1_fos71_r2_wp1_period.py` | 20788 | `effa6b64e6ba055e409e0e45c26a6f955b82069164ccac0fbdf0b201415bfe4e` | 2026-10-23T14:31:47Z | `f2fb04ee2eba32f6f0d95852b2f0b1df52ee0295` |
| `backend/tests/test_dd_v1_fos71_r2_wp1_entry_wiring.py` | 8730 | `d7d63bf2509e4d59c6f3834d10ff7c83d5d7917d8c6a07f9e98f3ce568d237f0` | 2026-10-23T14:31:47Z | `b95b4edc640c521e59f65c241d2221ecffedb0d4` |
| `tools/dd_v1_local_run.py` | 28156 | `ca95d5bbf7f42121417cd03b2a594bf9d511e114ae8d8a123a8bdfe1b4895273` | 2026-10-23T14:31:47Z | `3981543733ca643b0caaab255de77729ff8a964b` |
| `tools/dd_team_channel.py` | 34810 | `0b4cd51813f779874fe8be5782dadb39ccaf0c794e2280ef4140ea4f7bcad050` | 2026-10-23T14:31:47Z | `ebd2fbb8cab4b2a335b2d8f4c0188120cff46c57` |
| `docs/dd-v1-fos71/player2-r2-wp1/README.md` | 4453 | `c7f0b967f24f859c4d5e93f1b2ef2d3368454567f3de21b45766ca67d36e41a1` | 2026-10-23T14:31:47Z | `600e268c30340e8822a415a2a3e2b27910b627a5` |
| `docs/dd-v1-fos71/player2-r2-wp1/shape_probe.py` | 6438 | `b6ec96e16e62d730d5a01fe55e43c7e6ae35b9d8b265b7e3667197ccced7f885` | 2026-10-23T14:31:47Z | `ce4b7ec13c51fb222d410b214fc9f120f1310078` |
| `docs/dd-v1-fos71/player2-r2-wp1/run_with_ps_evidence.sh` | 2856 | `5bf93d455813ed1bbc0bf5fa836e477d206053d09dbdd0ffdabb38d228934eae` | 2026-10-23T14:31:47Z | `c1b6e605094f4735afb92959985fc952aaee7cab` |
| `docs/dd-v1-fos71/player2-r2-wp1/before_after_period.py` | 4729 | `caedffae737071302b1a7a1f66be8bf067c94ab0615d9c4ae9fb6d97d6fbefbd` | 2026-10-23T14:31:47Z | `8071dccfadcd7321beb21fdc6ac47ab7cef09b35` |

## 8 技能回执

`检索126项｜命中6项｜复用2项｜新增候选2项｜升级0项｜独立验证通过3项｜跨端加载成功2项`

- **检索项 126**：技能库 `README.md` 索引全量条目（`grep -cE "^- \*\*"` ＝ 126）＋ `AGENTS.md` 接盘协议；
  包内 `SKILL.md` 总数 585（含 `.archive`），顶层技能目录 80。
- **命中项 6**（按 name/description 关键词计分 ≥3 机械命中）：`scp-v3-4-coding-principles`、
  `vocab-batch-challenge`、`git-precheck`、`fundraising-roadshow-ledger`、
  `delegation-attribution-audit`、`adjutant-material-ingest`。
- **复用 2 项**（实际加载并应用）：
  · `git-precheck`（开发前 Git 前置检查）⇒ 每笔 push 前**现读远端 tip**并与本地父链比对，
    远端已移动即停；CA 证书与 credential 只走环境变量。
  · `scp-v3-4-coding-principles`（复用优先／黑盒化可审计）⇒ 复用既有 entity_service／语义检索／
    需求解析，不新造匹配引擎、不另抄类型表；退化入口唯一（六态阶梯与候选状态枚举 0 改动）。
- **新增候选 2 项**（登记，**未写入技能库**，未经批准不得合入）：
  ① **闸覆盖面与闸位置**：闸若只包住一条分支，则该闸对其余分支**零判别力** ⇒ 交付前须逐轴给出
     「该轴是否受闸保护」的机械判据（散落年份轴的教训）。
  ② **零余量耗时断言不构成证据**：无容差带的耗时序比较，其红与绿都不可作回归／无回归证据 ⇒
     归因按「同树复现 → 隔离单跑 → 交错」阶梯，且**平台读数优先**。
- **升级 0 项**：本轮未修改任何既有技能（只读技能库，不写回）。
- **独立验证通过 3 项**：笔 D／笔 E／笔 F 三笔均经司仓**字节层独立核验**（逐路径 blob 与改动面核对一致）。
- **跨端加载成功 2 项**：2 个 `SKILL.md` 均成功读取并应用；⚠ **加载通道非标准**（tarball 取只读副本，
  而非文档写的 `git clone`）—— 已如实登记。

## 9 边界回执

0 合并 master｜0 关 PR｜0 代写独立裁定｜0 改 Issue #71 AC｜0 改尺子｜0 改 GM 名册｜0 改写他人已落字节｜
0 amend｜0 force push（远端 ref 更新 force=false，父链完整）｜0 新建分支｜0 新建调度器｜0 第二写者｜
0 spawn｜0 改判定逻辑｜0 放宽断言｜0 扩枚举｜0 以平台绿替代机械证｜0 以未收齐的前置写成已收齐｜
0 并发全量跑批｜0 跑批窗口内 checkout｜0 输出明文 token

## 10 未闭环项（交出即明示）

- T2（G5 四文件并入 #81）／T3（R2 线并入 #81）：**等 Gate 结论**；我 0 自行抢跑、0 推 #81。
- T4（#81 终态 head 重锚独立 Gate）：由独立 Reviewer 出结论，施工席 0 自评。
- master 合并（H1）／关闭 PR #82（H2）：**人类授权项**，施工席 0 代做。
- 散落年份轴残留：见 §1，**按 C-1 原始口径不阻断 T4**；若后续要收敛，需另立授权面。

## 11 施工席 T3 追加说明（doc-only 追加；本节 0 代码字节；不修改本文件既有任何一行）

★ 本节由 **T2／T3 施工席**（`Player2 T2 Executor`）在 T3 合并落地后追加，**只追加、不改写**本文件既有任何一行。

### 11.1 §2「终态 head 树」行与「doctor 单独跑批」行的读数时点

§2 表格里这两行读数，是在**各自窗口、对当时那个被验 head**（本文件头部登记的 `fb0e42f3ac8d28a10360b5440204afadb98b797c`）上实测的，**在各自读数时刻为真**。
T3（R2 线并入 #81 线）落地后 #81 分支 tip 已前进 ⇒ **这两行不是终态读数**；施工席**不自行补写**任何未实测的终态读数。

★ **本文档的终态读数以 T4 独立复核席在终态合并面的实测为准（载体 ＝ PR #84 comment）。**

### 11.2 T3 合并面的一手机械读数（施工席实测；作用域 ＝ 合并面）

| 项 | 读数 |
|---|---|
| 合并 commit | `7858d88db68b151109a409a5b6b35cd9178d8009`（2 parents：`792b627d8cfc15742b1d7391dfec2e37d27c9e48` ＋ `32af192c62818f599418bb06311b09dce5b7848e`） |
| tree | `8273f43f684be41ae9631a82ca91ea7e17817c52` |
| merge base | `d1ebe3392fb20f04c2d0ecb00bbe639804187ac2` |
| git 三方合并 | rc ＝ 0；unmerged index 条数 ＝ 0；冲突标记计数 ＝ 0 |
| `tools/dd_v1_local_run.py` | 30,918 B；字节恒等式 25,088 ＋ (OURS−MB 2,762) ＋ (THEIRS−MB 3,068) ＝ 30,918（逐位相等） |
| OBS-1 五项 | 2 / 2 / 2 / 2 / 1（两枚 `gm-fix-minor4-*` 标记、两个闸函数 `_fixture_exempt` 与 `_guard_material_output_not_in_repo`、拒绝文案「BLOCKED: 仓外材料不得写入仓库目录」） |
| R2 接线四项 | `_period_anchor_arg` 3｜`period_anchor=anchor` 3｜`_period_spec_view` 3｜`_config_anchor` 3 |
| R2 路径 | 9 条全部在合并后树内（4 条产品/测试 ＋ 5 条交卷文档） |
| 变更面（blob 口径） | 新增 9 ／ 删除 0 ／ 既有 blob 变更 4 ＝ 13 条路径；派生 tree 口径单列：新增 1 ／ 删除 0 ／ 变更 8 ＝ 9 |

### 11.3 施工席侧受影响子集跑批（作用域 ＝ 18 个受影响文件）

343 collected / 0 failures / 0 errors / 0 skipped / exit 0；失败 ID 全集 ＝ （空）；`--collect-only` 求和 343 ＝ junit XML 343。

★ 本节读数**不是**全量读数，**也不是**终态 merge 面读数：★ **本轮未跑全量**（全量由 T4 独立复核席在终态合并面跑）★ **业务效果账仍 0/100 REAL_PASS**（本轮不代表效果已验证）。

### 11.4 载体指向更正（追加式；0 改既有字节；0 代码字节）

★ **更正 §11.1 末句的载体指向**：§11.1 写的「载体 ＝ PR #84 comment」**已作废**；★ **T4 终态裁定的落点 ＝ PR #81 的一条 comment**（理由：终态被验 head 落在 #81 线上，而 #81 才是要并入 master 的那个 PR；PR #84 的 comment 面只留历史，含已被取代的旧 FAIL 锚）。
★ 本句**只更正载体指向**这一项，§11.1 的其余表述**一字不改**（该表述本身仍成立）。
★ 另补一句事实：**R2 线已并入 #81 线后，本 PR 的交卷内容进入 #81 线**（合并 commit `7858d88db68b151109a409a5b6b35cd9178d8009`，2 parents ＝ `792b627d8cfc15742b1d7391dfec2e37d27c9e48` ＋ `32af192c62818f599418bb06311b09dce5b7848e`）。
★ 本节 0 代码字节；★ **终态读数仍以 T4 独立复核席在终态合并面的实测为准**（载体更正为 PR #81 的一条 comment），★ 施工席 0 自行补写任何未实测的终态读数。
