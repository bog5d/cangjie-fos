# TEST · 验收证据（cangjie-fos#71 CI 红灯 · OCR/中文字库环境修复）

全部验证**零外部调用 / 零费用 / 零真实材料**：OCR 用例自带的扫描件是**测试自己用 PIL 现场合成**的
（`backend/tests/test_dd_v1_ocr.py` 的 `_make_scan_image`），不依赖任何真实材料库。

---

## 0. 本轮**没有新增或修改任何测试用例**

| 项 | 读数 |
|---|---|
| 新增用例 | **0** |
| 修改用例 | **0** |
| 删除用例 | **0** |
| 跳过 / xfail | **0** |
| 断言弱化 | **0** |
| `git diff --name-only`（相对 PR #81 冻结 SHA） | **`.github/workflows/ci.yml`**（唯一） |
| `backend/uv.lock` | **0 改动**（blob = `e56d7e0516de7dd0bcfe2da256a3988bb71d3285` = PR #81 内同一 blob） |

★ **本轮的修法在环境侧，不在测试侧**。这是刻意的：红灯的成因是 runner 缺 tesseract 与中文字体，
**把测试改绿**（skip / 弱化断言 / 删用例 / 加 xfail）就是**用假绿掩盖真缺口**，
与「保留完整测试、禁止通过跳过测试制造 PASS」的施工令直接冲突。

---

## 1. CI 失败读数（远端一手，非自报）

### 1.1 check-run 层

来源：GraphQL `pullRequest(number:81).statusCheckRollup`（取数时刻 2026-10-23T09:1xZ；`cangjie-fos` 仓）。

| check 名 | status | conclusion | startedAt | completedAt | 耗时 |
|---|---|---|---|---|---|
| Backend Tests (440+ required) | COMPLETED | **FAILURE** | 2026-10-23T05:11:53Z | 2026-10-23T05:15:27Z | ≈3m34s |
| Backend Tests (440+ required) | COMPLETED | **FAILURE** | 2026-10-23T05:10:44Z | 2026-10-23T05:14:47Z | ≈4m03s |
| Backend Tests (228 required) | COMPLETED | **FAILURE** | 2026-10-23T05:11:53Z | 2026-10-23T05:15:44Z | ≈3m51s |
| Backend Tests (228 required) | COMPLETED | **FAILURE** | 2026-10-23T05:10:44Z | 2026-10-23T05:14:30Z | ≈3m46s |
| Frontend Build Check | COMPLETED | SUCCESS | 2026-10-23T05:11:52Z | 2026-10-23T05:12:07Z | ≈15s |
| Frontend Build Check | COMPLETED | SUCCESS | 2026-10-23T05:10:44Z | 2026-10-23T05:11:06Z | ≈22s |

★ `statusCheckRollup.state = FAILURE`；`mergeStateStatus = BLOCKED`。

### 1.2 job / step 层（区分「job 未启动」）

来源：REST `GET /repos/bog5d/cangjie-fos/actions/runs/{run_id}/jobs`（run `39904416668` = `pull_request` 事件）。

| job id | job 名 | conclusion | 失败 step | 其余 step |
|---|---|---|---|---|
| `120252959849` | Backend Tests (440+ required) | failure | step 7 `Run tests (and verify count ≥ 440)` | 1–6 全 success，12–15 按 GitHub 惯例 skipped/success |
| `120252960051` | Backend Tests (228 required) | failure | step 7 `Run FULL test suite under the legacy check name (same ≥440 gate)` | 同上 |
| `120252959646` | Frontend Build Check | success | — | 全 success |

★ **step 1–6 全部 success**（含 `Install dependencies`）⇒ 依赖装好了、Python 装好了、代码 checkout 成功。
失败**只**发生在真正跑测试那一步 ⇒ **不是 job 未启动**。

### 1.3 失败 ID 全集

来源：REST `GET /repos/bog5d/cangjie-fos/actions/jobs/120252959849/logs`（37,323 B；UTF-8 with BOM；508 行）。

| # | 失败 ID | 原始报错（逐字） |
|---|---|---|
| 1 | `tests/test_dd_v1_ocr.py::test_local_ocr_toolchain_available` | `AssertionError: 本机缺少 tesseract` |
| 2 | `tests/test_dd_v1_ocr.py::test_all_four_orientations_are_tried` | `assert [] == [0, 90, 180, 270]` |
| 3 | `tests/test_dd_v1_ocr.py::test_recovers_rotated_chinese_scan[0]` | `AssertionError: 本机没有可用的中文字体` |
| 4 | `tests/test_dd_v1_ocr.py::test_recovers_rotated_chinese_scan[90]` | 同上 |
| 5 | `tests/test_dd_v1_ocr.py::test_recovers_rotated_chinese_scan[180]` | 同上 |
| 6 | `tests/test_dd_v1_ocr.py::test_recovers_rotated_chinese_scan[270]` | 同上 |
| 7 | `tests/test_dd_v1_ocr.py::test_parser_uses_ocr_for_image_without_text_layer` | 同上 |
| 8 | `tests/test_dd_v1_ocr.py::test_ocr_failure_keeps_unreadable_and_no_text` | 同上 |
| 9 | `tests/test_dd_v1_ocr.py::test_image_only_pdf_is_ocred` | 同上 |
| 10 | `tests/test_dd_v1_ocr.py::test_parse_method_is_recorded_as_ocr` | 同上 |

★ **失败文件唯一**：`backend/tests/test_dd_v1_ocr.py`。
★ 作业日志尾部：`##[error]Process completed with exit code 1.` ⇒ pytest 自身非零退出，**流程未走到 ≥440 计数门槛**。

---

## 2. 修复后本地复跑

### 2.1 OCR 专项（19 条，全绿）

命令（CI 同款环境变量）：

```bash
cd backend
CANGJIE_PITCH_COACH_ROOT=/tmp/mock_pitch_coach CANGJIE_DRY_RUN=true \
  ./.venv/bin/python -m pytest tests/test_dd_v1_ocr.py -q --tb=short
```

| 轮次 | 字体来源 | 结果 |
|---|---|---|
| R1 | 本沙箱字体 | `...................  [100%]` **EXIT=0**（19/19） |
| R2 | **Ubuntu noble 官方 `fonts-noto-cjk`**（覆盖同路径） | `...................  [100%]` **EXIT=0**（19/19） |
| R3 | **Ubuntu noble 官方 `fonts-wqy-zenhei`**（把 Noto 移开） | `...................  [100%]` **EXIT=0**（19/19） |

★ R2/R3 用的是从 `archive.ubuntu.com` 下载的 **noble 官方 `.deb`**（`dpkg-deb -x` 解包）里的真实字体文件，
**不是**本沙箱原有的旧版本 ⇒ 模拟的就是 runner 装完后的状态。
★ R2 与 R3 各自独立全绿 ⇒ `FONT_CANDIDATES` 的两条 Linux 路径**互为冗余**，任一条可用即可。

### 2.2 断言双向可复现（探针阳性 / 阴性对照）

| # | 场景 | 构造方式 | 读数 | 结论 |
|---|---|---|---|---|
| A | **阳性**（模拟 runner 缺 tesseract） | `ocr.tesseract_binary = lambda: None` | `tesseract_available() = False`；`ocr_available() = False` | CI 的「本机缺少 tesseract」**逐字复现** |
| B | **阳性**（模拟 runner 缺中文字体） | `FONT_CANDIDATES` 无一命中 | `assert None` | CI 的「本机没有可用的中文字体」**逐字复现** |
| C | **阴性**（本机真实环境） | 实际安装 | `tesseract_available() = True`；`pillow_available() = True`；`ocr_available() = True` | 同一探针**不误报** |

★ 三格合起来才是完整证据：**CI 上的报错在本地被逐字复现，而同一探针在有环境的机器上不响**
⇒ 差异是**环境**，不是代码、不是测试写错。

### 2.3 全量回归（CI 同款命令）

```bash
cd backend
CANGJIE_PITCH_COACH_ROOT=/tmp/mock_pitch_coach CANGJIE_DRY_RUN=true \
  ./.venv/bin/python -m pytest tests/ --ignore=tests/test_doctor_script.py \
    -q --tb=short --junit-xml=/tmp/result_local.xml
```

| 项 | 读数 |
|---|---|
| 命令 | 与 CI step 7 **逐字相同**（只把 `uv run --extra dev pytest` 换成本地 venv 的 `python -m pytest`；`uv` 在本沙箱会重写锁文件，故不用） |
| 环境 | Python 3.11.2 / pytest 9.0.3 / tesseract 5.3.0 |
| 退出码 | 见 §2.4 |
| 失败 ID 全集 | 见 §2.4 |
| 计数门槛 | CI 侧仍为 `>= 440`（**未改**） |

### 2.4 全量结果

见 `EVIDENCE-CI-OCR.md` §5.4 与本文件随附的 `FULL-RUN-READING.md`（含退出码、失败 ID 全集、JUnit XML 解析读数、取数时刻）。

---

## 3. 「不制造假绿」的机械证据

| 检查项 | 读数 |
|---|---|
| 跳过标记 `skip` / `xfail` | 本轮 workflow 与测试**均未新增**任何 skip/xfail |
| 测试命令被改动？ | **否**（逐字比对 CI step 7 前后） |
| 计数门槛被降低？ | **否**（`>= 440` 前后一致；兼容别名 job 同样 `>= 440`） |
| 被排除的测试 | **未变**（仍只有仓内标准命令本就排除的 `test_doctor_script.py`） |
| 环境自证 | 装 tesseract/字体后**立即断言**到位，缺一即该步失败 |

★ 换句话说：**红灯的成因被消除了，而不是被遮住了**。若装环境失败，CI 会在
`Install OCR toolchain` 这一步**以明确信息红**（而不是让 9 条业务用例以误导性的断言信息红）。

---

## 4. 取数时刻与对象版本（全部 UTC）

| 读数 | 时刻 | 对象 |
|---|---|---|
| PR #81 head SHA | 2026-10-23T09:1xZ | `d1ebe3392fb20f04c2d0ecb00bbe639804187ac2` |
| PR #81 base SHA | 同上 | `d9bd8e89c1a35aa7f27893bfcd84be4713cf27d2` |
| check-run 读数 | 2026-10-23T09:1xZ | run `39904416668` / `39904314647` |
| 作业日志下载 | 2026-10-23T09:2xZ | job `120252959849` |
| 本地 OCR 专项复跑 | 2026-10-23T09:2xZ | 本沙箱 venv（pytest 9.0.3） |
| noble 包索引核实 | 2026-10-23T09:2xZ | `archive.ubuntu.com` noble main/universe |
| 全量回归 | 2026-10-23T09:2xZ–09:3xZ | 同上 venv |

★ 不同读数时刻之间的差异是**时序差**，不是事实矛盾。
