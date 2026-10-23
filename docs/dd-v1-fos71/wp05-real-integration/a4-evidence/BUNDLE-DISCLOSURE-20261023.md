# 7 项成卷 · 已公开披露声明（清零记录）

> 本文件是**公开面清理的披露**，不是交付物。相关 11 个文件已从本仓移除。

## 一、哪些文件曾在公开面上

下列 **11 个文件**（相对本仓根）曾在公开面上，自 2026-10-22（施工侧仓内落盘版 d9bd8e8） 起、至 2026-10-23（本批清零提交） 止：

| `01-input-checklist.tsv` | `d7efd58aca51e51e1ef9805f34ac5a32ee9cd1a24b715b0bb7d81b60ca9b8415` | 171B |
| `02-retrieved-materials.tsv` | `43ee268a387a85777d5dee6b57b504e7823270ad46131eabf77cfa9355e3ba82` | 570B |
| `03-match-verdicts.tsv` | `fcf2d7b09a748c195f9ea26664949902407e2a5bcab96248fe7153046b9fef57` | 436B |
| `04-gaps-and-uncertainty.tsv` | `8a29dab4145905b5a98180311546c43744b5cbb6724145eb63a804757db8b705` | 1080B |
| `05-human-review-step.md` | `1ab7d359cc97c43d3bbf4debfb9a8b477770c061df3048929ea4753383d1bafa` | 1402B |
| `06-delivery-package-manifest.tsv` | `38ebb47b6c12038f160321da904a9eb82f5ed7243396361b965d4371be4f11a9` | 233B |
| `06-delivery-package/S2/F004_shili_business_license.txt` | `b18f53a48238bfd8eec4957f52ea6da2dee2ea849511447b5acfa65b48ab9e88` | 315B |
| `06-delivery-package/未选用清单.tsv` | `6c382207aedb95a43eded9656a0d313829292669739d75b5bda77ee860f2a760` | 1918B |
| `06-delivery-package/组包manifest.tsv` | `bc5bb561bc7497cf9bb04923e93571bcfb67b55c35b3536b2b11120973a8fb9a` | 306B |
| `06-delivery-package/被拦截清单.json` | `89962373c7213ab9186ac2a444b1ff181042fdcb27db03b0da94b6252ca4de5f` | 3901B |
| `07-repro-commands-and-evidence.txt` | `2aa6f068fb2ec8ef7ab3bcc4fe5f916d052484ca496f678a998cc7ab03a92fe2` | 2167B |

## 二、什么时间、在哪些线上

- 首次进入公开面：2026-10-22（施工侧仓内落盘版 d9bd8e8）（提交 `d9bd8e8`「7 项成卷 · 施工侧仓内落盘版」）。
- 波及公开线（实测 `git ls-tree -r <branch> | grep -c seven-item-bundle` 均为 11）：
  `master`、`spec/71-ddv1-real-engine-integration-20261021`、`feat/71-a4-blind-exam`、
  `feat/71-player2-p0-fix-20261023`、`feat/71-player2-r2-wp1-period-semantics`、
  `fix/71-ci-ocr-toolchain-20261023`、`fix/71-g5-mixed-type-packaging-20261023`。
- 清零方式：**向前提交**删除（无 force-push、无历史改写）；历史提交中仍可见 ⇒
  「曾经公开过」这一事实不可撤回，故在此留痕。

## 三、内容范围

全部 11 个文件均为**合成**材料与合成运行记录（示例主体），不含真实客户标识；暴露内容范围 = 7 项成卷的清单/检索/判定/缺口/审核步骤/交付包与复现命令记录。

★ 复现命令记录（原 `07-repro-commands-and-evidence.txt`）内的本机绝对路径与司仓会话 ID
已在**披露声明**中用占位符表达：树 = `$WORKTREE`、隔离数据面 = `$SESSION_WS`、
解释器 = `$VENV`；原始成卷文件在仓外固化目录中保持**逐字节原样**（sha256 见上表）。

## 四、已如何移除

1. 整卷 11 个文件从本仓**删除**（`git rm -r`），删除内容逐字节导出到**仓外固化目录**：
   `GM 仓 work/evidence/W-DD-V1-REALINT-2026-WP-A3/SEVEN-ITEM-BUNDLE-20261022/`（该目录随仓外证据面保存，**不进 Git**；`SHA256SUMS.txt` 一并落地）。
2. 本仓保留本披露声明（**不含**成卷内容）。
3. 七条公开线各一条清零提交 ⇒ 公开面计数归零。

★ 说明：本条清理**只处理公开暴露面**，不改变 A4a 的裁定结论，也不改变工程/效果两条进度分。
