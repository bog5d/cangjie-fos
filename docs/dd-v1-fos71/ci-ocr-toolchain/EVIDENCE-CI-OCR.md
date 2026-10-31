# EVIDENCE · FOS #71 CI 红灯归因与 OCR/中文字库环境修复

- **subject_id**：DD-V1-FOS71/CI-OCR-TOOLCHAIN
- **授权来源**：董事长 2026-10-23 施工令「FOS考生2｜P0产品阻塞修复」后续项「核实 GitHub CI 红灯原因，优先修复 OCR 与中文字库环境问题，保留完整测试，禁止通过跳过测试制造 PASS」
- **base**：`d1ebe3392fb20f04c2d0ecb00bbe639804187ac2`（**PR #81 冻结 SHA**，远端 `refs/heads/feat/71-player2-p0-fix-20261023`）
- **分支**：`fix/71-ci-ocr-toolchain-20261023`（第一父 = base；**未推 master、未合并任何分支**）
- **作者**：云端 MiniMax Executor（唯一 Writer）｜**自查，不是独立复核**
- **零外部调用 / 零费用 / 零真实材料**：本轮未调用任何收费模型；未读 Gold；未写入任何真实清单、客户材料、个人信息或密钥
- **PR #81 冻结 SHA 不变**：本分支**不改** PR #81 的任何一个字节（diff 面仅 `.github/workflows/ci.yml`）；刘江侧正在复测的版本不受影响

---

## 1. 一句话结论

PR #81 的 CI 红灯**不是代码缺陷、不是平台计费阻塞、不是规则判负、不是测试被跳过**，
而是 **CI 运行环境缺 OCR 工具链**：`ubuntu-24.04` runner 既没装 tesseract，也没有中文字体，
导致 `backend/tests/test_dd_v1_ocr.py` 的 **10 条用例真实失败**。
修法是**在 CI 里补齐运行环境**——**一个测试字节都没改**。

---

## 2. 红灯分层归因（三种可能逐一排除，不靠推测）

| # | 候选解释 | 判定 | 机械证据 |
|---|---|---|---|
| 1 | **job 未启动**（Actions 账户计费/额度阻塞） | **排除** | 4 个 Backend Tests check 的 `status=COMPLETED`、`conclusion=FAILURE`，且有**真实耗时**（run `39904416668`：`05:11:53Z → 05:15:27Z`，约 3 分 34 秒）。job 未启动时 `status` 会停在 `QUEUED`/`IN_PROGRESS` 且无 `completed_at`。同批次 `Frontend Build Check` 为 `SUCCESS`（`05:11:52Z → 05:12:07Z`），说明 runner 本身可正常调度。 |
| 2 | **真实测试失败** | **成立** | run `39904416668` / job `120252959849`，step 7 `Run tests (and verify count ≥ 440)` = `failure`，step 1–6 全 `success`；作业日志 `##[error]Process completed with exit code 1.` |
| 3 | **规则判负**（测试全过但计数门槛 < 440） | **排除** | 门槛判定在 pytest 之后执行（`COUNT=$(...)` → `if [ "$COUNT" -lt 440 ]`）；日志显示 pytest **自身**以退出码 1 结束并打印 10 条 `FAILED`，流程根本没走到计数门槛。 |

★ 另有**两个 run**（push 与 pull_request 各一），job id 与失败点完全同构：

| run id | 事件 | job id | job 名 | 结论 |
|---|---|---|---|---|
| `39904314647` | `push` | `120252638064` | Backend Tests (440+ required) | failure（step 7） |
| `39904314647` | `push` | `120252637790` | Backend Tests (228 required) | failure（step 7） |
| `39904416668` | `pull_request` | `120252959849` | Backend Tests (440+ required) | failure（step 7） |
| `39904416668` | `pull_request` | `120252960051` | Backend Tests (228 required) | failure（step 7） |

---

## 3. 失败 ID 全集（10 条，全部落在同一个文件）

取数：作业日志 `GET /repos/bog5d/cangjie-fos/actions/jobs/120252959849/logs`（37,323 B，UTF-8 with BOM）。

```
tests/test_dd_v1_ocr.py::test_all_four_orientations_are_tried
tests/test_dd_v1_ocr.py::test_image_only_pdf_is_ocred
tests/test_dd_v1_ocr.py::test_local_ocr_toolchain_available
tests/test_dd_v1_ocr.py::test_ocr_failure_keeps_unreadable_and_no_text
tests/test_dd_v1_ocr.py::test_parse_method_is_recorded_as_ocr
tests/test_dd_v1_ocr.py::test_parser_uses_ocr_for_image_without_text_layer
tests/test_dd_v1_ocr.py::test_recovers_rotated_chinese_scan[0]
tests/test_dd_v1_ocr.py::test_recovers_rotated_chinese_scan[90]
tests/test_dd_v1_ocr.py::test_recovers_rotated_chinese_scan[180]
tests/test_dd_v1_ocr.py::test_recovers_rotated_chinese_scan[270]
```

**失败文件唯一**：`backend/tests/test_dd_v1_ocr.py`（其余 169 个测试文件 0 失败）。

### 3.1 失败原因只有两个（原始断言逐字）

| 断言 | 原始报错 | 出现次数 | 含义 |
|---|---|---|---|
| `assert ocr.tesseract_available(), "本机缺少 tesseract"` | `AssertionError: 本机缺少 tesseract`（`where False = <function tesseract_available ...>`） | 1 | runner 上**没有 tesseract 可执行文件** |
| `assert font_path, "本机没有可用的中文字体"` | `AssertionError: 本机没有可用的中文字体`（`assert None`） | 8 | runner 上**没有任何可用的中文字体文件** |
| `assert seen == [0, 90, 180, 270]` | `assert [] == [0, 90, 180, 270]` | 1 | tesseract 缺失 ⇒ 四方向候选**一个都没跑**（`seen` 为空） |

★ 第 3 条是**前两条的派生结果**，不是独立缺陷：`_run_tesseract` 在无 tesseract 时抛 `RuntimeError("本机未安装 tesseract")`，
四方向循环全部中断 ⇒ `seen == []`。

### 3.2 根因链（逐环有机械证）

| 环 | 内容 | 机械证据 |
|---|---|---|
| ① | 仓库的 OCR 测试**依赖本机系统级工具链**，不依赖 pip 包 | `backend/tests/test_dd_v1_ocr.py`：`test_local_ocr_toolchain_available` 断言 `ocr.tesseract_available()`；`FONT_CANDIDATES` 是**绝对路径清单**（macOS / Linux / Windows 三套） |
| ② | 生产代码同样按「本机 tesseract」设计 | `dd_v1_ocr_service.py`：`OCR_LANG = "chi_sim+eng"`；`_run_tesseract` 调 `[binary, "stdin", "stdout", "-l", OCR_LANG, "--psm", "4", "tsv"]`；`tesseract_binary()` 走 `shutil.which` + 3 个 fallback 路径 |
| ③ | **CI workflow 没有任何一行安装 OCR 工具链** | 修复前 `.github/workflows/ci.yml` 的两个 Backend Tests job，步骤集仅：`checkout` → `setup-uv` → `setup-python` → `uv sync --extra dev` → `mkdir` → `pytest`。**无 `apt-get`**、无字体安装 |
| ④ | runner 镜像确实不含 tesseract 与中文字体 | 作业日志 `Runner Image: ubuntu-24.04 / Version: 20261012.334.1`；实测断言报错「本机缺少 tesseract」「本机没有可用的中文字体」 |

★ **同一份代码在交卷席的环境里是绿的**：`test_dd_v1_ocr.py` 在**有** tesseract + 中文字体的机器上 **19/19 全绿**
（§5 复现）。⇒ 差异**只在环境**，不在代码。

---

## 4. 修法：补齐运行环境（不动任何测试）

### 4.1 改动面

| 文件 | 改动 | 行数 |
|---|---|---|
| `.github/workflows/ci.yml` | 两个 Backend Tests job 各插入一步 `Install OCR toolchain (tesseract + Chinese fonts)` | **+80 / −0**（**纯新增**） |

★ **测试文件零改动**：`backend/tests/` 本轮**未触碰任何字节**（`git diff --name-only` 仅 `.github/workflows/ci.yml`）。
★ **无 skip / 无 xfail / 无断言弱化 / 无 `-k` 过滤 / 无 `--maxfail`**：
测试命令与门槛逐字未动（`uv run --extra dev pytest tests/ --ignore=tests/test_doctor_script.py -q --tb=short --junit-xml=...`，
门槛仍为 `>= 440`）。

### 4.2 装什么、为什么是这五个包

包的存在性与版本**逐个按 Ubuntu noble 官方仓库索引核实**（`archive.ubuntu.com/ubuntu/dists/noble/{main,universe}/binary-amd64/Packages.gz`）：

| apt 包 | 仓库 | noble 版本 | 装它是为了什么 |
|---|---|---|---|
| `tesseract-ocr` | **universe** | `5.3.4-1build5` | tesseract 主程序（`OCR_LANG` 需要 `chi_sim+eng`） |
| `tesseract-ocr-chi-sim` | **universe** | `1:4.1.0-2` | `chi_sim` 中文简体语言包 |
| `tesseract-ocr-eng` | **universe** | `1:4.1.0-2` | `eng` 英文语言包（`OCR_LANG` 里显式带了 `+eng`） |
| `fonts-noto-cjk` | main | `1:20230817+repack1-3` | 提供 `NotoSansCJK-Regular.ttc`（`FONT_CANDIDATES` 第 6 项） |
| `fonts-wqy-zenhei` | **universe** | `0.9.45-8` | 提供 `wqy-zenhei.ttc`（`FONT_CANDIDATES` 第 7 项） |

★ **踩坑记录（已写进 workflow 注释）**：noble 把 **tesseract 系列放进了 `universe`**，
只配 `main` 源会装不上（实测 `noble/main/binary-amd64/Packages.gz` 中 `tesseract-ocr` **0 命中**，
`noble/universe/...` 中命中）。GitHub runner 镜像的 `sources.list` 默认含 universe，但把这件事写进注释，
免得日后镜像源配置变化时**静默装不上**、错误信息被误读为「包不存在」。

### 4.3 字体落点与测试候选清单**逐字对齐**（按 .deb 文件清单核实，非推测）

用 Ubuntu noble 官方 `.deb` 实际解包核对（`dpkg-deb -c`）：

```
fonts-noto-cjk   -> ./usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
fonts-wqy-zenhei -> ./usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
tesseract-ocr-chi-sim -> ./usr/share/tesseract-ocr/5/tessdata/chi_sim.traineddata
```

前两条与 `backend/tests/test_dd_v1_ocr.py` 的 `FONT_CANDIDATES` **逐字相同** ⇒ 装完测试一定找得到。
两条路径**互为冗余**（各自单独跑过，§5.3），任一条缺失另一条仍能兜住。

### 4.4 装完**立即自证**（缺一即本步失败）

```bash
command -v tesseract
tesseract --version | head -1
tesseract --list-langs | grep -qx chi_sim
tesseract --list-langs | grep -qx eng
for f in /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
         /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc; do
  [ -f "$f" ] || { echo "❌ 缺中文字体：$f"; exit 1; }
done
```

★ **为什么要在装环境这步自证**：环境没到位时，若不设这道闸，失败会以
「本机缺少 tesseract」/「本机没有可用的中文字体」的形式出现在**下游 9 条业务用例**上 ——
信息误导（看起来像代码/测试问题），且**定位成本高**。加了自证后，环境问题**在它自己的那一步**红，
一眼看出是环境、不是代码。

★ **两个 job 的该步骤逐字一致**（机械证：两处 `run` 文本的 sha256 相同 = `4a2261448da913d74a23c099948861c2d97a2e9d9b7dbc83fcf6ff4b8d757213`）。
**必须一致**：否则会出现「主 job 绿、兼容别名 job 红」，required check 照样不过（与 2026-10-23 05:11Z 红灯同因）。

---

## 5. 复现与验证（本地独立复跑，非自报）

环境：云沙箱；Python 3.11.2；`uv 0.12.17`；pytest **9.0.3**；tesseract **5.3.0**（+`chi_sim`/`eng`/`osd`）。
依赖安装走 `https://mirrors.aliyun.com/pypi/simple/`（沙箱内网镜像 `mirrors.cloud.aliyuncs.com` 连接被重置；
外网 `pypi.org` 不可达）⇒ **`backend/uv.lock` 0 改动**（`uv sync` 曾把锁文件重写为镜像源 URL 并引入
`torch`/`accelerate` 等无关包，已 `git checkout -- backend/uv.lock` 还原；还原后 blob = `e56d7e0516de7dd0bcfe2da256a3988bb71d3285`
= PR #81 内同一 blob，**逐位相同**）。

### 5.1 PR #81 冻结 SHA 上，OCR 测试 19/19 全绿

```
$ pytest tests/test_dd_v1_ocr.py -q --tb=short
...................                                                      [100%]
EXIT=0
```

### 5.2 断言双向可复现（探针阳性/阴性对照）

| 场景 | 构造 | 读数 | 判读 |
|---|---|---|---|
| A 模拟 runner 缺 tesseract | `ocr.tesseract_binary = lambda: None` | `tesseract_available() = False`、`ocr_available() = False` | ⇒ 断言「本机缺少 tesseract」**精确触发**（与 CI 日志同因） |
| B 字体候选全不存在 | runner 上 `FONT_CANDIDATES` 无一命中 | `assert None` | ⇒ 断言「本机没有可用的中文字体」**精确触发**（与 CI 日志同因） |
| C 本机真实环境 | 实际安装 | `tesseract_available() = True`、`pillow_available() = True`、`ocr_available() = True` | ⇒ 同一探针**不误报** |

★ 这三格构成完整对账：**CI 上的两条报错，在本地被逐字复现；在有环境的机器上不复现**。

### 5.3 用 Ubuntu noble 官方字体的端到端复跑（**不是本沙箱的旧字体**）

把 noble 官方 `.deb` 里的字体文件覆盖到测试会读到的**同路径**，再跑同一批用例：

| 字体状态 | 命中路径 | 结果 |
|---|---|---|
| `NotoSansCJK-Regular.ttc`（noble 官方版） | `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` | **19/19 全绿**，EXIT=0 |
| 把 Noto 移开 ⇒ 走 `wqy-zenhei.ttc`（noble 官方版） | `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc` | **19/19 全绿**，EXIT=0 |

★ 两条候选路径**各自独立**跑通 ⇒ §4.3 的冗余是真的，不是摆设。
★ 覆盖后字体文件 sha256：`NotoSansCJK-Regular.ttc` = `b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a`；
`wqy-zenhei.ttc` = `79c18ebe7b811951e8311bad7103ebeae8c337ed9988ea69e8a78a66cfe029b9`。
★ 补测：把字体换成 **Ubuntu 26.04 (resolute)** 官方 `.deb` 里的版本后重跑，仍 **19/19 全绿**；
且 resolute 与 noble 两版这两个字体文件的 sha256 **逐位相同** ⇒ §5.3 的 R2/R3 同时覆盖 24.04 与 26.04。

### 5.5 前瞻：本修法**能扛住 `ubuntu-latest` 的镜像迁移**（已核实，非推测）

`ubuntu-latest` 正在从 24.04 迁移到 **26.04**（GitHub 官方公告：2026-10-19 起 rollout，11-19 完成）。
本仓 workflow 用的是 `runs-on: ubuntu-latest`（**移动靶**）⇒ 修完 24.04 的环境，26.04 上可能又缺包。
**已逐个核实**（`archive.ubuntu.com` 的 `resolute/main` 与 `resolute/universe` 索引 + 官方 `.deb` 文件清单）：

| apt 包 | 26.04 (resolute) | 仓库 | 字体落点是否变化 |
|---|---|---|---|
| `tesseract-ocr` | `5.5.0-1build1` | universe | — |
| `tesseract-ocr-chi-sim` | `1:4.1.0-2build1` | universe | — |
| `tesseract-ocr-eng` | `1:4.1.0-2build1` | universe | — |
| `fonts-noto-cjk` | `1:20240730+repack1-1build1` | main | **不变**（`/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`） |
| `fonts-wqy-zenhei` | `0.9.45-8build1` | universe | **不变**（`/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`） |

★ **五个包名在 26.04 上全部存在、一字未改；两条字体落点路径一字未改** ⇒ 本修法**不会因 ubuntu-latest 迁移而失效**。
★ 本轮**未**把 `runs-on: ubuntu-latest` 改成显式版本标签：**那会改变仓库的 runner 契约，属生产配置变更，需授权**，
且本轮无证据表明必须改（迁移期显式钉 `ubuntu-24.04` 是一种可选策略，**不是**本轮的必要动作）。
★ 另注：26.04 的 tesseract 从 5.3.4 升到 **5.5.0**（大版本跳跃）。本轮**未**在 26.04 上实跑（无该环境），
⇒ 「26.04 上 19 条 OCR 用例仍全绿」目前只有**字体层**的证据（字体字节相同），
**tesseract 5.5.0 的行为差异未验证**。此点如实登记为**未验证**，不写成「已验证」。


### 5.4 全量回归

见 `TEST-EVIDENCE.md` §2（CI 同款命令：全量 + `--ignore=tests/test_doctor_script.py`，门槛 ≥440）。

---

## 6. 口径边界（如实登记，不夸大）

1. 本证据包**只证明「CI 红灯由环境缺失造成、且本修法能在 ubuntu-24.04 + noble 官方包上补齐该环境」**。
2. 本轮**未**在 GitHub runner 上实跑（那需要 push 后由 Actions 执行）。**最终绿灯以远端 Actions 的真实 check-run 为准**，
   本地复跑只是**必要条件**，不是充分条件。
3. 本轮**不构成**任何业务效果认定；PR #81 的独立 Gate 裁定（comment `6358415604`，VERDICT: PASS）
   **只覆盖交卷 SHA 的机械口径**，其自陈边界（真实材料库实测 / Windows 复测 / 模型实测均未验证）**依然成立**。
4. `mergeStateStatus` 本轮读取为 `BLOCKED`，`reviewDecision` 为 `None`，`reviews` 计数为 **0**
   ⇒ **合并授权与独立 Review 仍未取得**；本轮**未合并 master、未推 master、未改 PR #81 的冻结 SHA**。
5. G1–G5 五个已登记缺口**本轮未修**（G1 `PERMISSION_BLOCKED` 无生产者、G2 `scaffold` 单主体、
   G3 `version_status` 认不出「被取代版本」、G4 归一后主体逐字比较有口径差、G5 多类型段按整段定类型）：
   本轮只解 CI 环境阻塞，**G5 与 G2 另有独立工作包承接**（见 §8）。
