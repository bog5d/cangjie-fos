# FULL-RUN-READING · 全量回归读数（cangjie-fos#71 · CI 红灯修复分支）

本件是**机器读数**记录：命令、退出码、失败 ID 全集、JUnit XML 解析读数、取数时刻。
凡「自报」一律不采信；凡本轮未实跑的一律标 UNKNOWN。

---

## 0. 被测对象

| 项 | 读数 |
|---|---|
| 仓库 | `bog5d/cangjie-fos`（public） |
| 分支 | `fix/71-ci-ocr-toolchain-20261023` |
| 基座 | `d1ebe3392fb20f04c2d0ecb00bbe639804187ac2` ＝ **PR #81 的冻结 head**（本分支在其上**只**加 CI 与证据包） |
| 相对 PR #81 冻结 SHA 的变更面 | `.github/workflows/ci.yml`（+94 行）＋ `docs/dd-v1-fos71/ci-ocr-toolchain/**`（本证据包，**不含任何 `.py`**） |
| ★ Python 树 | **与 PR #81 逐位相同**（`git diff --name-only` 中无任何 `.py`/`.toml`/`.lock`）⇒ 本读数**同时**是 PR #81 的全量基线读数 |

## 1. 命令（与 CI step 7 逐字相同）

```bash
cd backend
CANGJIE_PITCH_COACH_ROOT=/tmp/mock_pitch_coach CANGJIE_DRY_RUN=true \
  ./.venv/bin/python -m pytest tests/ --ignore=tests/test_doctor_script.py \
    -q --tb=short --junitxml=/tmp/result_ci.xml
```

★ 只把 CI 的 `uv run --extra dev pytest` 换成本沙箱 venv 的 `python -m pytest`
（`uv` 在本沙箱会重写 `backend/uv.lock`；本轮**锁文件零污染**，blob 仍为
`e56d7e0516de7dd0bcfe2da256a3988bb71d3285` ＝ PR #81 内同一 blob）。
★ 计数门槛 **≥ 440** 在 CI 侧**未改**；本读数的 1724 条远超该门槛。

## 2. 读数（机器解析，非自报）

| 项 | 读数 |
|---|---|
| 取数窗口（UTC） | **2026-10-23T10:07:52Z → 2026-10-23T10:17:12Z**（耗时 **9 分 20 秒**） |
| **退出码** | **0** |
| `tests`（collected） | **1724** |
| `failures` | **0** |
| `errors` | **0** |
| `skipped` | **5**（仓内既有 skip；本轮**未新增**任何 skip/xfail） |
| 套件耗时（JUnit XML `time`） | **552.123 秒** |
| **失败 ID 全集** | **空集（0 条）** —— JUnit XML 内 `<failure>`/`<error>` 节点数 0 |
| 门槛判定 | 1724 ≥ 440 ⇒ **通过**（CI 侧同一条判据） |
| 环境 | Python 3.11.2 / pytest 9.0.3 / tesseract 5.3.0（chi_sim、eng） |

★ **失败 ID 全集为空**这一点是本轮与 CI 红灯的**直接对照**：
CI 侧同一命令有 **10 条**失败 ID（全部在 `tests/test_dd_v1_ocr.py`，报错字面
「本机缺少 tesseract」/「本机没有可用的中文字体」/「assert [] == [0, 90, 180, 270]」），
本地同一命令 **0 条** ⇒ 差异是**环境**（runner 缺 tesseract 与中文字体），不是代码、不是测试写错。

## 3. 副产物（可复算）

| 产物 | 位置 | 读数时刻（UTC） |
|---|---|---|
| pytest stdout/stderr 全量日志 | `/tmp/full_ci.log` | 2026-10-23T10:07:52Z–10:17:12Z |
| JUnit XML | `/tmp/result_ci.xml` | 同上（`<testsuite … tests="1724" failures="0" errors="0" skipped="5">`） |

★ 二者均在沙箱内、**未随件落盘**（避免把一次性运行日志塞进仓内交付件）；
本文件记录的是**解析后的读数**，任何人可用上面同一条命令重跑复核。

## 4. 口径边界（如实登记，不夸大）

1. 本读数证明的是：**在 ubuntu-24.04 + noble 官方包补齐 OCR 环境后，本仓全量测试在本地全绿**。
   它**不**证明 GitHub runner 上已绿 —— 那一项以 **push 后的远端 Actions 真实 check-run** 为准。
2. 本轮**未在真实 runner 上实跑**（沙箱无 Docker/podman、无 docker socket，无法本地起
   ubuntu-24.04 容器端到端演练）⇒ 替代证据是「官方 `.deb` 解包 ＋ 落点核对 ＋ 字体实跑」。
3. `ubuntu-latest` 正在从 24.04 迁移到 26.04（resolute）：已逐个核实 resolute 的**五个包名**
   与**两条字体落点路径**一字未改，**字体字节 sha256 与 noble 版逐位相同**；
   但 **tesseract 5.5.0 的 OCR 行为差异未实跑验证** ⇒ 此点记 **UNKNOWN**，不写成「已验证」。
4. 本读数**不构成**任何业务效果认定：PR #81 的独立 Gate 裁定（comment `6358415604`，VERDICT: PASS）
   **只覆盖交卷 SHA 的机械口径**；真实材料库实测、Windows 复测、模型实测**均未验证**。
5. 本轮**未合并 master、未推 master、未改 PR #81 的冻结 SHA**；`mergeStateStatus=BLOCKED`、
   `reviewDecision=None`、`reviews=0` 的读数**依然成立**。
