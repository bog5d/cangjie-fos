#!/usr/bin/env python3
"""DD-V1 **凭证活性探针**（BLOCKED-7：凭证腐烂没有主动告警）。

★ **要解决的实测问题**：旧 key 失效**一个月**才被撞上 —— 等到考试真跑才报 401。
  ⇒ 本探针把「凭证还在不在」变成**开考前就能知道**的一行读数。

★ **三条硬纪律**：
1. **绝不输出密钥明文**：报告里只有 **sha256 指纹前 12 位**（可用来判断「key 换没换」，
   **不泄露任何一位原文**）；异常消息、请求头、URL 一律不含凭证；
2. **不做付费模型调用**：只用**免费**的鉴权端点（``/models`` 一类）⇒ 不消耗额度；
3. **区分「没配」与「配了但坏了」**：``NOT_CONFIGURED``（规则基线照样能跑）
   与 ``EXPIRED`` / ``INVALID`` / ``QUOTA``（**要处理**）**不得混为一谈**。

★ 判定口径（与真实考试报错口径对齐）：
  - HTTP 200/2xx ⇒ ``OK``
  - HTTP 401 ⇒ ``EXPIRED``（凭证无效/已过期/已吊销）
  - HTTP 402 / 余额类报错 ⇒ ``QUOTA``
  - HTTP 403 ⇒ ``INVALID``
  - HTTP 429 ⇒ ``QUOTA``（限流/额度用尽）
  - 其它 5xx / 连接失败 / 超时 ⇒ ``UNKNOWN``（**不猜**；网络问题不等于凭证坏了）

**用法**::

    python tools/dd_v1_credential_probe.py probe                 # 探所有已配置来源
    python tools/dd_v1_credential_probe.py probe --json          # 只出 JSON
    python tools/dd_v1_credential_probe.py probe --deepseek-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import urllib.error
import urllib.request
from typing import Any

#: 来源定义：环境变量名 → 供应商与免费鉴权端点。
SOURCES: dict[str, dict[str, str]] = {
    "DEEPSEEK_API_KEY": {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "probe_path": "/models",
        "note": "DeepSeek Harness(dsh) 用的就是这一支；端点 /models 免费、不消耗额度",
    },
    "OPENAI_API_KEY": {
        "provider": "openai",
        "base_url": "https://api.openai.com",
        "probe_path": "/models",
        "note": "codex 等走 OpenAI 兼容面的调用用这一支；端点 /models 免费",
    },
}

#: 本机 CLI 型考生（凭证不在环境变量里，在各自配置树）—— 只探「在不在」，不碰它的凭证。
CLI_SOURCES: dict[str, str] = {
    "dsh": "DeepSeek Harness CLI",
    "pi": "pi 框架 CLI",
    "codex": "codex CLI",
}

STATUS_OK = "OK"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_EXPIRED = "EXPIRED"
STATUS_INVALID = "INVALID"
STATUS_QUOTA = "QUOTA"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_CLI_MISSING = "CLI_MISSING"

#: 这些状态算「有问题」（须处理）；``NOT_CONFIGURED`` 与 ``UNKNOWN`` **不算**。
BAD_STATUSES = {STATUS_EXPIRED, STATUS_INVALID, STATUS_QUOTA}


def fingerprint(secret: str) -> str:
    """凭证指纹（**不可逆**）：sha256 前 12 位。

    ★ 用途：判断「这次用的是不是同一把 key」（key 轮换了要能看出来），
      **不泄露任何一位原文**。
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def _classify(status: int | None) -> tuple[str, str]:
    if status is None:
        return STATUS_UNKNOWN, "连接失败/超时（**网络问题不等于凭证坏了**）"
    if 200 <= status < 300:
        return STATUS_OK, f"HTTP {status}"
    if status == 401:
        return STATUS_EXPIRED, "HTTP 401（凭证无效/已过期/已吊销）"
    if status == 403:
        return STATUS_INVALID, "HTTP 403"
    if status in (402, 429):
        return STATUS_QUOTA, f"HTTP {status}（余额不足/额度用尽/限流）"
    if 500 <= status < 600:
        return STATUS_UNKNOWN, f"HTTP {status}（服务端错误，**不能据此判定凭证坏了**）"
    return STATUS_UNKNOWN, f"HTTP {status}"


def probe_env_source(name: str, spec: dict[str, str], *, timeout: float = 8.0,
                     base_url_override: str | None = None) -> dict[str, Any]:
    """探一个环境变量来源。**任何路径都不把凭证写进返回值。**"""
    out: dict[str, Any] = {
        "source": name,
        "kind": "env",
        "provider": spec["provider"],
        "probe_endpoint": spec["probe_path"],
        "note": spec.get("note", ""),
    }
    secret = os.environ.get(name)
    if not secret or not secret.strip():
        out.update({"status": STATUS_NOT_CONFIGURED,
                    "detail": f"环境变量 {name} 未设置（规则基线考试不需要它）",
                    "fingerprint": None})
        return out

    out["fingerprint"] = fingerprint(secret.strip())
    out["configured"] = True
    base = (base_url_override or spec["base_url"]).rstrip("/")
    url = base + spec["probe_path"]
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + secret.strip()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            # ★ 只读状态码，**不读也不打印响应体**（响应体可能回显敏感信息）
    except urllib.error.HTTPError as exc:
        status = exc.code
    except urllib.error.URLError as exc:
        out.update({"status": STATUS_UNKNOWN, "detail": f"连接失败：{exc.reason}"})
        return out
    except (TimeoutError, socket.timeout):
        out.update({"status": STATUS_UNKNOWN, "detail": f"超时（>{timeout}s）"})
        return out
    except Exception as exc:  # noqa: BLE001
        out.update({"status": STATUS_UNKNOWN, "detail": f"{type(exc).__name__}（不打印内容，避免泄密）"})
        return out

    st, detail = _classify(status)
    out.update({"status": st, "detail": detail})
    return out


def probe_cli_sources() -> list[dict[str, Any]]:
    """探本机 CLI 型考生：**只看装没装**，不读它们的凭证、不跑它们。"""
    out: list[dict[str, Any]] = []
    for cli, desc in CLI_SOURCES.items():
        path = shutil.which(cli)
        out.append({
            "source": cli,
            "kind": "cli",
            "provider": desc,
            "status": STATUS_OK if path else STATUS_CLI_MISSING,
            "detail": (f"已安装（{path}）" if path else "未找到该 CLI（**只影响真实模型那一层**）"),
            "fingerprint": None,
        })
    return out


def probe_all(*, deepseek_only: bool = False, base_url_override: str | None = None,
              timeout: float = 8.0) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for name, spec in SOURCES.items():
        if deepseek_only and spec["provider"] != "deepseek":
            continue
        results.append(probe_env_source(name, spec, timeout=timeout,
                                         base_url_override=base_url_override))
    results.extend(probe_cli_sources())
    bad = [r for r in results if r.get("status") in BAD_STATUSES]
    return {
        "schema_version": "dd_v1_credential_probe.v1",
        "sources": results,
        "counts": {
            "total": len(results),
            "ok": sum(1 for r in results if r.get("status") == STATUS_OK),
            "not_configured": sum(1 for r in results if r.get("status") == STATUS_NOT_CONFIGURED),
            "bad": len(bad),
            "unknown": sum(1 for r in results if r.get("status") == STATUS_UNKNOWN),
        },
        "verdict": "PROBLEM" if bad else "OK",
        "bad_sources": [{"source": r["source"], "status": r["status"], "detail": r["detail"]}
                        for r in bad],
        "note": ("★ 报告里**没有**任何密钥原文，只有 sha256 指纹前 12 位。"
                 "★ `UNKNOWN` 不等于凭证坏了（网络/服务端问题），需人工再确认。"),
    }


def render(report: dict[str, Any]) -> str:
    lines = ["【DD-V1 凭证活性探针】"]
    for r in report["sources"]:
        mark = "✅" if r["status"] in (STATUS_OK, STATUS_NOT_CONFIGURED, STATUS_CLI_MISSING) else "❌"
        fp = f"  指纹={r['fingerprint']}" if r.get("fingerprint") else ""
        lines.append(f"  {mark} {r['source']:<22} {r['status']:<16}{fp}")
        lines.append(f"       {r['detail']}")
    c = report["counts"]
    lines.append("")
    lines.append(f"合计 {c['total']} 个来源：可用 {c['ok']}｜未配置 {c['not_configured']}"
                 f"｜有问题 {c['bad']}｜未知 {c['unknown']}")
    lines.append(f"结论：{report['verdict']}")
    if report["bad_sources"]:
        lines.append("★ 要处理的：" + "；".join(
            f"{b['source']}={b['status']}（{b['detail']}）" for b in report["bad_sources"]
        ))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DD-V1 凭证活性探针")
    ap.add_argument("action", choices=["probe"])
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    ap.add_argument("--deepseek-only", action="store_true")
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--base-url", default=None, help="覆盖 base url（测试用）")
    args = ap.parse_args(argv)

    report = probe_all(deepseek_only=args.deepseek_only,
                        base_url_override=args.base_url, timeout=args.timeout)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 1 if report["verdict"] == "PROBLEM" else 0


if __name__ == "__main__":
    raise SystemExit(main())
