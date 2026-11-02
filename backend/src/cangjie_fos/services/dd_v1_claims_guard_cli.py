"""「声称 ↔ 实现」守卫的命令行入口。

用法：
    PYTHONPATH=backend/src python3 -m cangjie_fos.services.dd_v1_claims_guard_cli \
        --claims docs/dd-v1-fos71/wp05-real-integration/CLAIMS.json [--repo-root .] [--json]

退出码：
    0 = PASS（无虚假 PASS）
    1 = FAIL（存在 UNSUPPORTED / NOT_IMPLEMENTED ⇒ **虚假 PASS**）
    2 = 用法或 IO 错误
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cangjie_fos.services.dd_v1_claims_guard import (
    CLAIM_UNSUPPORTED,
    check_claims,
    load_claims,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="声称 ↔ 实现 守卫")
    ap.add_argument("--claims", required=True, help="claims JSON 路径")
    ap.add_argument("--repo-root", default=".", help="仓库根目录（默认当前目录）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出汇总")
    args = ap.parse_args(argv)

    claims_path = Path(args.claims)
    repo_root = Path(args.repo_root).resolve()
    if not claims_path.is_absolute():
        claims_path = repo_root / claims_path
    try:
        claims = load_claims(claims_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print("读 claims 失败：%s" % e, file=sys.stderr)
        return 2

    report = check_claims(claims, repo_root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("声称 ↔ 实现 守卫：%s（%d 条声称，仓库 %s）"
              % (report["verdict"], report["n_claims"], repo_root))
        for r in report["results"]:
            mark = "✗" if r["violation"] else ("·" if r["status"] == "DECLARED_UNKNOWN" else "✓")
            print("  %s %-26s %-18s %s" % (mark, r["id"], r["status"], r["claim"][:52]))
            for c in r["evidence_checks"]:
                print("       %-6s %-16s %s" % ("命中" if c["ok"] else "未中", c["type"], c["detail"]))
        if report["violations"]:
            print("\n★ 虚假 PASS（说了已落地但拿不出实现证据）：%s"
                  % ", ".join(r["id"] for r in report["violations"]))
        print("边界：%s" % report["capability_boundary"])
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
