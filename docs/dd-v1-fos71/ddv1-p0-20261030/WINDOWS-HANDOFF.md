# DD-V1｜Windows 复测操作指南（2026-10-30 P0 修复版）

★ **本轮冻结版本（唯一）**：`e57cf4854ec63c37c66860a3d8f3e2627efa2af0`
★ 分支：`feat/71-ddv1-exam-v1-20261028`（PR #86 的 head）｜★ 同名 ref：`feat/71-ddv1-p0-fix-20261030`（**同一 commit**）
★ ★ **必须逐位核对**（下面第 ① 步）——★ **版本不符就停测并报告**，★ 不要用 master、不要用旧 ZIP。

★ 本轮修了刘江 2026-10-30 报的两个 P0：
· **P0-1 空库假 READY**：`preflight` 以前在「0 份材料 ＋ 0 条义务 ＋ 0 份 Gold 映射」时返回 `READY_FOR_FORMAL_SCORING`
　 ⇒ 现在「空」一律是**阻塞事实**，且预检给出**三档能力**（工程测试／业务诊断／正式评分）。
· **P0-2 两套拆解**（库侧 91 条 vs 运行器侧 15 条）⇒ ★ 现在**统一到库侧权威拆解**
　 ⇒ **跑 42 题必须加 `--library <LIB>`**（★ 见第 ⑤ 步；不加会走旧路径、**会丢一半题**）。

---

## ① 版本核验（先做）

```powershell
git fetch --depth 1 origin e57cf4854ec63c37c66860a3d8f3e2627efa2af0
git rev-parse FETCH_HEAD
# 期望输出：e57cf4854ec63c37c66860a3d8f3e2627efa2af0   （40 位，逐位一致）
git status --porcelain     # 期望：0 行
```

## ② 环境检查（doctor 要在**后端启动之前**跑）

```powershell
python tools\doctor.py
```
★ 上一轮踩过的坑：**doctor 要求 8000 端口空闲** ⇒ ★ **先停掉旧后端再跑 doctor**。

## ③ 登记图书馆 ＋ 主体 ＋ 清单（顺序不能颠倒）

```powershell
python tools\dd_v1_manifest.py register --library LIB-<你的库ID> --root "<受控本地材料库路径>" --authorized-by 刘江
python tools\dd_v1_manifest.py entity   --library LIB-<你的库ID> --id E01 --name "<母公司全称>" --relation parent --group-root --source "<执照文件名>"
python tools\dd_v1_manifest.py entity   --library LIB-<你的库ID> --id E02 --name "<子公司全称>" --relation subsidiary --parent E01 --source "<执照文件名>"
python tools\dd_v1_manifest.py build    --library LIB-<你的库ID> --mode full
python tools\dd_v1_manifest.py checklist --library LIB-<你的库ID> --file checklist42-exam.tsv --anchor-year 2026 --institution 华西
python tools\dd_v1_manifest.py obligations --library LIB-<你的库ID>     # ★ 看 obligations 条数与覆盖题数
```
★ **主体登记必须在首次摄取/组包前完成**；★ 主体登记**挂在库上** ⇒ ★ **没先 `register --library` 就 `entity` ⇒ 登记不生效**
　（上一轮 42 题全 UNCERTAIN 的一个原因就是这个）。

## ④ 开考前 Gate（★ 本轮重点）

```powershell
python tools\dd_team_channel.py preflight --contract "<考场契约.json>" --library LIB-<你的库ID>
```
★ 报告里现在有**三档能力**（看 `当前档位`）：
- `FORMAL_SCORING` ⇒ 可正式评分；
- `DIAGNOSTIC` ⇒ **只能做诊断试跑**，结果**必须标「非正式评分」**；
- `ENGINEERING` ⇒ 只能做工程测试（合成数据）。
★ **空库/0 义务/0 期望文件 ⇒ 一定是 `ENGINEERING`/`DIAGNOSTIC` ＋ `是否具备正式评分条件：否`** ⇒ ★ **不会再假 READY**。

## ⑤ Gold 映射逐件检查（★ 波总要的那张清单）

```powershell
python tools\dd_team_channel.py gold-report --contract "<考场契约.json>" --library LIB-<你的库ID>
```
★ 输出**逐件**：题号／原始路径／指纹／**分类 A–F**／候选／修复动作。
★ A＝确实缺料（**补料清单**）｜C＝文件名匹配错｜D＝哈希/内容识别错｜E＝主体/期间/范围错｜F＝Gold 侧需人工补。
★ ★ **不要删 Gold、不要改 Gold**；★ 能在本机安全纠正映射的**直接纠正**；★ 确实缺料的**单列补料**。

## ⑥ 42 题正式考试（★ 关键：**带 `--library`**）

```powershell
python tools\dd_v1_local_run.py run --material-root "<受控本地材料库路径>" --meta "<库meta路径>" ^
  --items "<42题条目.json>" --library LIB-<你的库ID> ^
  --out "<受控运行目录>" --adapter dsh --allow-local-dsh --allow-real-material ^
  --period-anchor '{"year": 2026}' --resolve-doc-type
```
★ ★ **`--library` 是本轮的关键**：它让运行器**用库侧权威拆解**（覆盖全部 42 题，义务 id 与 Gold 同源）；
　**不给** ⇒ 走旧的本机规则拆解 ⇒ ★ **会丢掉「无材料类型关键词」的整题**（实测 42 题只覆盖 21 题）⇒ 分数必错。
★ `--resolve-doc-type` 建议打开：★ 让「规则层判不出材料类型」的题**进模型做语义判断**（否则那些题会判「没理解」）。
★ `--adapter dsh` 需要 `--allow-local-dsh`；★ 真实材料需要 `--allow-real-material`。
★★ **数据流**：★ `dsh` 通过 `DEEPSEEK_API_KEY` 调 **DeepSeek 云端模型** ⇒ ★ **真实材料进模型即离开本机**
　⇒ ★ **必须**有波总的书面授权；★ 未授权 ⇒ 只用脱敏/合成数据跑，真实 42 题记 **BLOCKED**。

## ⑦ 机器答卷 ＋ 正式评分（三组成绩单）

```powershell
python tools\dd_team_channel.py answer --run-dir "<运行目录>" --contract "<考场契约.json>" ^
  --delivered "<组包manifest.tsv>" --exam-id EX-<编号>
python tools\dd_team_channel.py grade --answer "<机器答卷.json>" --contract "<考场契约.json>" --library LIB-<你的库ID>
```
★ 成绩单现在**同时**给三组：
① **全卷成绩**：题数（**分母来源**写明）／已处理／正确／未匹配／歧义／未完成／**全卷可验证覆盖率**；
② **Gold 可评分成绩**：可评分义务（**分母**）／正确／错误／得分率／**未纳入原因**；
③ **证据差异**：逐项（Gold 预期文件／机器实际选择／主体／期间／是否正确／**文件哈希**／归因）。
★ ★ **部分缺料 ≠ 全盘不可评分** ⇒ 状态 `SCORED_PARTIAL`，★ **保留全卷分母**；缺口逐件列在 `gold_gaps`。
★ **0 件交付 ⇒ 总分强制 0**（**不是** NOT_SCORABLE）；★ 不可评分时**仍保留量化诊断**（`diagnostic`）⇒ 既不是 0 分，也不是「没有结果」。

## ⑧ 诊断包导出（交回证据用）

```powershell
# 预检 / Gold 缺口 / 成绩单 三份都落在 <data>/考场/
# 例：
Get-ChildItem "<数据面目录>\考场\*.json" | Select-Object Name, Length
```
★ 交回时**只交脱敏产物**：机器答卷、成绩单、预检 md/json、Gold 缺口 json；★ **不要**把 Gold 原文或真实材料放进 Git。

---

## 常见错误与恢复

| 现象 | 原因 | 恢复 |
|---|---|---|
| `READY_FOR_FORMAL_SCORING` 但你知道库是空的 | **旧版本**（本轮已修）⇒ 核对 `git rev-parse HEAD` | 换到本轮冻结 SHA |
| 42 题只处理了一半 | **没加 `--library`** ⇒ 走了旧规则拆解 | 加 `--library LIB-<ID>` 重跑 |
| `obligations` 数远小于 42 | 清单里多数题「无材料类型关键词」 | 正常（库侧**不丢题**）；★ 用 `--library` 路径 |
| 42 题全 UNCERTAIN | ★ 主体没先 `register --library` 就 `entity`（登记不生效） | 按第 ③ 步重做，主体先于摄取 |
| `GOLD_FILES_MISSING_IN_LIBRARY` | Gold 里那几份**内容指纹**在库快照里找不到 | 跑第 ⑤ 步拿逐件清单；★ A 类＝**补料**，**不删 Gold** |
| `GOLD_FILES_AMBIGUOUS_CONTENT` | 同一指纹命中多份库材料 | 看 `gold-report` 的**候选** ⇒ **人工指定**（程序不猜） |
| doctor 报端口占用 | 旧后端没停 | 先停后端再跑 doctor |
| `dsh` 报缺凭据 | 未配 `DEEPSEEK_API_KEY` | ★ 按授权口径处理；★ 未授权就用合成数据，真实考试记 BLOCKED |
