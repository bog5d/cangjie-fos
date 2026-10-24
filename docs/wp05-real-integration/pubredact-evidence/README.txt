# 本包证据索引（T-FOS-PUBREDACT-2026-WP-R1）
# 生成时间: 2026-10-22T14:33:59+0800

00-scope-and-method.txt        范围 · 扫描面口径 · 替身代称口径 · 替换手法 · 纪律落实
01-scan-before-after.txt       全仓扫描：改前 12 命中（真实名 12 文件 / 代号 0 文件）→ 改后 0
02-pytest-baseline-vs-after.txt 后端全量 pytest：基线态 vs 改后（逐项数字 + 退出码）
03-frontend-checks.txt         前端 vitest + vite build 实跑结果
04-discriminative-probe.txt    R-5 判别力：回退脱敏 ⇒ 扫描重新命中（3 个目标 + SHA256 指纹）
05-whitelist-reconciliation.txt 白名单对账（改动集合从 git 差集自动推导）
07-provenance.txt               base commit / 分支 / 脚本清单 / 环境事实
08-observations-and-limits.txt 观察与限制（诚实登记，含未验证项）
09-delivery-surface-scan.txt   R-7 交付面自净扫描（两套匹配规则）
10-raw-measurement-logs.txt    执行者本地暂存区 · 原始测量日志登记（**非交付件**）
SHA256SUMS-pubredact-evidence.txt  本目录全部文件的 SHA256（清单自身除外）
SHA256SUMS-modified-files.txt      12 个被改文件的 SHA256

★ 本目录**零字面量**：真实名/代号只以序号出现；替身代称（主体甲/乙/丙、案例A/B/C）不是敏感字面量。

## SHA256 清单自校验（逐条重算比对，**结果现算**）
  `SHA256SUMS-pubredact-evidence.txt`：12 条 ⇒ **OK 12 / 不符 0**
  `SHA256SUMS-modified-files.txt`    ：12 条 ⇒ **OK 12 / 不符 0**
  判定：**两份清单均自校验通过**
  复核命令：
    cd docs/dd-v1-fos71/wp05-real-integration/pubredact-evidence
    shasum -a 256 -c SHA256SUMS-pubredact-evidence.txt
    # 在仓根执行：shasum -a 256 -c docs/dd-v1-fos71/wp05-real-integration/pubredact-evidence/SHA256SUMS-modified-files.txt
