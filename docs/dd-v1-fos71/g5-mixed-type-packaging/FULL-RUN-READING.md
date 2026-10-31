# FULL-RUN-READING · G5 修复的全量回归读数（cangjie-fos#71 · 独立工作包）

本件是**机器读数**：命令、退出码、失败 ID 全集、JUnit XML 解析读数、取数时刻、被测对象身份。
凡「自报」不采信；凡未实跑的一律标 UNKNOWN。

---

## 0. 被测对象

| 项 | 读数 |
|---|---|
| 仓库 | `bog5d/cangjie-fos`（public） |
| 分支 | `fix/71-g5-mixed-type-packaging-20261023` |
| head | `2306c63812bd089ed34c5a1e51b590569d06bbd3` |
| 基座 | `d1ebe3392fb20f04c2d0ecb00bbe639804187ac2` ＝ **PR #81 的冻结 head**（本分支在其上**只**加 G5 一处） |
| 变更面 | `backend/src/cangjie_fos/services/` 下 **4 个 `.py`** ＋ `backend/tests/test_dd_v1_g5_mixed_type_packaging.py`（新增） |
| ★ PR | #83（base ＝ PR #81 分支 `feat/71-player2-p0-fix-20261023` ⇒ diff 只含 G5 增量） |

## 1. 命令（与 CI step 7 逐字相同）

```bash
cd backend
CANGJIE_PITCH_COACH_ROOT=/tmp/mock_pitch_coach CANGJIE_DRY_RUN=true \
  ./.venv/bin/python -m pytest tests/ --ignore=tests/test_doctor_script.py \
    -q --tb=short --junitxml=/tmp/result_g5c.xml
```

★ 计数门槛 **≥ 440** 在 CI 侧**未改**；本读数 1735 条远超该门槛。
★ 本轮**未新增/未修改/未删除**任何既有断言，**未加 skip/xfail**，`backend/uv.lock` **零改动**。

## 2. 读数（机器解析，非自报）

| 项 | 读数 |
|---|---|
| 取数窗口（UTC） | **2026-10-23T10:25:16Z → 2026-10-23T10:34:51Z**（耗时 **9 分 35 秒**） |
| **退出码** | **0** |
| `tests`（collected） | **1735**（＝ PR #81 基线 1724 ＋ 本轮新增 11） |
| `failures` | **0** |
| `errors` | **0** |
| `skipped` | **5**（仓内既有 skip；本轮**未新增**） |
| 套件耗时（JUnit `time`） | **572.551 秒** |
| **失败 ID 全集** | **空集（0 条）** —— JUnit XML 内 `<failure>`/`<error>` 节点数 0 |
| 环境 | Python 3.11.2 / pytest 9.0.3 / tesseract 5.3.0（chi_sim、eng） |

## 3. 分层读数（作用域各不同，不可混用）

| 层 | 读数 | 命令 |
|---|---|---|
| ① 新增判据（本轮 G5 文件） | **11/11 全绿** | `pytest tests/test_dd_v1_g5_mixed_type_packaging.py -q` |
| ② 受影响文件（cards／policy／matching／packaging／packaging_exact／player2_p0／selection／bridge／local_run） | **165 条全绿** | 同上 9 个文件 |
| ③ 全量 | **1735 collected / 0 failures / 0 errors / 5 skipped / exit 0** | §1 |

★ ① 的**红→绿**对照：把 4 个产品码文件暂存（`git stash`）后跑同一条判据 ⇒
链级用例如期红，报错逐字为
`AssertionError: 段内可外发类材料被披露闸拦下（G5 未修复）：["披露不可外发（等级=RESTRICTED）：材料类型 'audit_report' 不在策略允许外发的类型清单 ['license'] 内；规则已收紧为 R1-AUDIT；不可判定，按最严处理，不得外发"]`
⇒ **成因环与后果环在同一条判据上闭合**。

## 4. 一次**作废**的读数（如实登记，不藏）

首轮全量回归（10:0xZ）读到 **1735 collected / 1 failure**，失败用例是
`tests/test_dd_v1_recovery.py::test_scale_baseline[20-25]`，
断言 `inc_s < full_s`（增量扫描应快于全量）实测 0.1404 < 0.1274 为假。
⇒ 该用例是**时序敏感**的（并发负载下翻转），且**不触及**本次改动的任何代码路径
（素材扫描的 size+mtime 快跳）；单独复跑 **3/3 通过**。
⇒ **但该轮读数仍被我判作不可用**：同一时间窗内我 checkout 了另一个分支，
**运行中的 pytest 脚下的 `.py` 被替换成另一分支的树** ⇒ 读数对象不再是被验对象
⇒ 已停任务、回到本分支**重跑**，§2 是重跑后的合法读数。
⇒ ★**纪律**：长跑测试期间冻结工作树（不 checkout、不改被测文件）。

## 5. 副产物（可复算）

| 产物 | 位置 |
|---|---|
| pytest 全量日志 | `/tmp/full_g5c.log` |
| JUnit XML | `/tmp/result_g5c.xml`（`<testsuite … tests="1735" failures="0" errors="0" skipped="5">`） |

★ 二者在沙箱内、**未随件落盘**；本文件记录**解析后的读数**，任何人可用 §1 同一条命令重跑复核。

## 6. 远端真实 runner 的读数（PR #83）

★ 本 PR 的 check **红**，且**红因不在本 PR**：失败 job `120363578739`
（`Backend Tests (440+ required)`，run `39938417409`，作业日志 36,515 B）逐条提取 ⇒
**失败 ID 全集 10 条，全部落在 `tests/test_dd_v1_ocr.py`**
（`本机缺少 tesseract`／`本机没有可用的中文字体`／`assert [] == [0, 90, 180, 270]`），
**G5 相关失败 0 条**；step 1–6 全 success、只有 step 7 红。
⇒ 与 PR #81 的红灯**逐条同形** ⇒ 根因是**基座分支不含 CI 环境修复**（那是 PR #82）。
⇒ ★**本地绿 ≠ 远端绿**的两侧读数在此**不一致且各有解释**（本地有 OCR 环境、远端基座没有）。

## 7. 口径边界（如实登记，不夸大）

1. 本读数证明的是「**本 G5 改动没有破坏既有 1735 条测试**，且新判据从红转绿」。
2. 它**不**证明业务效果：真实材料库实测、Windows 复测、模型表现**均未验证**；
   效果账仍为 **0/100 REAL_PASS**。
3. 本轮**未合并 master、未推 master、未改 PR #81 的冻结 SHA**；
   `mergeStateStatus=BLOCKED`、`reviewDecision=None`、`reviews=0` 依然成立。
4. 本轮**无独立 Reviewer 席产出裁定**（本 PR 的修法与判据为自查 ＋ 机器读数）。
5. **遗留缺口 G5-bis**：材料自身类型认不出时，披露闸仍退回「段的类型」判定 ——
   该退化路径沿用既有口径，本轮**不擅自扩大改动面**。
6. **证据池平面**（快照 meta 的单值 `doc_type`）**未改** ⇒ 多值化需桥接层另行承接。
