# SKILLS · 复盘（cangjie-fos#71 考生2 P0 修复）

- **技能库**：`bog5d/bog-global-skills`（私有，默认分支 `master`），本次经
  用 GitHub codeload 端点的 master 分支 tarball（`codeload.github.com` + 仓 `bog5d/bog-global-skills`）取只读副本（**本包不写完整 URL**）
  （★ **本沙箱的 git 没有 CA 证书包**，`git clone` 报 `server certificate verification failed: CAfile: none`
  ⇒ 改走 codeload tarball + Bearer token，**只读**，不写回技能库）。
- **开发前**：读 `AGENTS.md`（接盘手册）与 `README.md`（**126 条**技能索引），按 name/description
  匹配「调试 / 测试 / 代码审查 / 项目环境」，**只加载 3 个 SKILL.md**（未全量扫）。

## 检索与命中

| 口径 | 数量 | 明细 |
|---|---|---|
| 检索项 | **126** | `README.md` 技能索引全量条目（`grep -cE "^- \*\*" = 126`）+ `AGENTS.md` 接盘协议 |
| 命中项 | **6** | ① `systematic-debugging`（调试：根因调查 + 紧反馈回路）② `test-driven-development`（测试：先写红再改）③ `requesting-code-review`（代码审查：提交前静态扫描 + 基线测试 + **独立复核**）④ `github-code-review`（代码审查他人 PR，本轮不适用）⑤ `cangjie-fos-project`（FOS 环境速查：测试命令、已知问题、多 AI 并行协议）⑥ `git-precheck`（开发前 Git 前置检查） |
| 实际复用项 | **3** | `cangjie-fos-project`、`systematic-debugging`、`requesting-code-review`（各加载并**实际应用**，见下） |
| 跨端加载成功 | **3 / 3** | 3 个 SKILL.md 全部成功读取并应用；但**加载通道非标准**（tarball 而非文档写的 `git clone ~/.agents/skills`），已如实登记 |

### 实际应用了什么（不是「读了没用」）

| 技能 | 落在本轮的哪个动作 |
|---|---|
| `cangjie-fos-project` | ① 确认本仓**标准测试命令**是 `pytest tests/ --ignore=tests/test_doctor_script.py -q` —— 这解释了 `test_doctor_script_exits_zero` 为何是**环境型既有失败**（该技能与 `AGENTS.md` 都明确排除它）；② 采纳其 TDD 铁律：先写红测试再改产品码；③ 采纳其「开发前 `git fetch` + 三方向检查」：本轮 `git fetch` 后确认远端 master 未前进（无竞争租约） |
| `systematic-debugging` | ① 「先根因、后修复」：司仓给的 5 条根因**逐条自己跑机械证复核**（含 `repro.py` 自己跑一遍取数，不引用既有输出）；② 「紧反馈回路」：把「证据池恒空」变成可跑红的命令（`python -c` 现场验 `parse_doc_type_spans` / 归一后的池命中数），而不是靠读代码推断；③ 定位到**我自己实现里的一个真 bug**（重叠消解时元组解包顺序错 ⇒ `劳动合同` 被误判为两类），靠紧反馈回路当场抓到并修掉 |
| `requesting-code-review` | ① 提交前**静态安全扫描**（硬编码密钥 / `shell=True` / `eval` / `pickle` / SQL 拼接）逐条跑过；② 「基线测试」纪律：改动前先跑全量记基线失败数（1 条），改动后确认不新增；③ 「**No agent should verify its own work**」：本轮**另起一个独立 Reviewer 会话**做只读对抗性复核（不合并、不改码） |

## 开发后：候选 / 升级 / 独立验证

| 口径 | 数量 | 说明 |
|---|---|---|
| 新增候选 | **1** | 候选技能《**多账不同源的 key 空间分叉**》：症状 = 「语义链接上了但拿不到料 / 证据池恒空且静默」；根因 = 义务侧与材料侧各自用了一张**只覆盖部分**的类型表且字面不同；判据 = ① 比较前**归一**（不要求调用方一次性改完）② 空结果必须给**结构化原因**而不是空列表 ③ 判据要**正反成对**（该拆的拆 / 不该拆的不拆）。**真实根因 ✓、回归复验 ✓、独立复核 ✓** —— 列入候选，但**未经波总批准不得合入个人全局 Skills 库 master**，本轮**未写入**技能库 |
| 升级 | **0** | 本轮没有修改任何既有技能（不写技能库，只登记候选） |
| 独立验证 | **1 轮（2 项发现，均已修）** | 独立复核席（另起的会话，只读复核）在本轮**独立跑出 2 个真问题**：① **可分离性规则漏掉「带年份的间隔」**（「审计报告2024年营业执照」这类不拆 ⇒ 拆解率仍偏低）② **`PERMISSION_BLOCKED` 没有生产者**（meta 的 `access` / `restricted` 是留出的扩展点，仓内两个 meta 生产者都不写 ⇒ 生产路径下该状态不可达）。两项都已按机械证改正并补了用例/文档（详见 `EVIDENCE-PLAYER2-P0.md` §8-C7/C8 与 §6.3） |

### 独立复核的两项发现（原文要点 + 我的处置）

1. **可分离性规则的边界**（复核席机械证）：初版规则只认「标点分隔符」才算可分离
   ⇒「审计报告2024年营业执照」这种**间隔里有年份**的情形被误判成复合词 ⇒ 不拆。
   **处置**：规则改成「间隔非空 **且**（含连接词/标点 **或** 含非汉字字符〔年份、拉丁字母、括号〕）⇒ 可拆；
   间隔为空（紧挨着）或**纯汉字连接**（如「甲公司营业执照」）⇒ 判复合词 ⇒ 不拆」，
   并补 **2 条用例**（带年份 ⇒ 拆；纯汉字连接 ⇒ 不拆）。
2. **`PERMISSION_BLOCKED` 无生产者**（复核席机械证：查了两个 meta 生产者，都不写该字段）。
   **处置**：**不假装已接线** —— 在 `_access_blocked` 的 docstring、`NO_CANDIDATE_REASONS` 的注释、
   测试 docstring、证据包 §8-C7/G1 **四处写明**「当前是留出的扩展点，生产路径下不可达」，
   并写清**为什么不接敏感等级**（策略默认 9/10 类为 `RESTRICTED` ⇒ 按敏感等级过滤证据池会让复核覆盖面塌陷；
   受限材料的**披露**闸在 `dd_v1_policy_service`，不在证据召回口径）。

★ 另：独立复核席**独立复现**了本包 §6.3 记的那次并发假失败（它那次并发跑也撞上
`test_p0_retry_eval` / `test_pipeline_e2e` 的状态泄漏）⇒ 两路独立同向 ⇒ 该环境事实成立。

## 尚未复用的命中项（登记，不假装用过）

- `test-driven-development`：其「先写红测试」的纪律被 `cangjie-fos-project` 的同名条款覆盖，本轮按后者执行 ⇒ **未单独加载**。
- `github-code-review`：审的是**他人**的 PR；本轮是自研自审 + 独立 Reviewer 会话 ⇒ **不适用，未加载**。
- `git-precheck`：其「三方向检查」的动作已由 `cangjie-fos-project` 的多 AI 协议条款覆盖 ⇒ **未单独加载**。

## 复盘结论（一句话）

三个技能里**真正改变施工过程**的是两个：`systematic-debugging` 让我抓到了自己实现里的重叠消解 bug，
`requesting-code-review` 让我把「独立复核」做成了另起的会话而不是自审；
`cangjie-fos-project` 提供了「本仓标准测试命令」这条决定基线口径的事实。
