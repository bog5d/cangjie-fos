#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""司仓禁形自检（7 族）——作用域＝本轮实际写出字节；配阳性/阴性对照。

用法（仓内落盘版，**跨轮可复现**）：
    python3 docs/dd-v1-fos71/player2-r2-wp1/shape_probe.py <文件或目录> [更多路径]

族定义（宽度与族定义同宽）：
  F1 编码层损坏字符（U+FFFD 那个码位）
  F2 单码点省略号（U+2026 那个码位）
  F3 ASCII 三点
  F4 截短小写 hex：7-39 位且至少含一个 a-f；排除 UUID 分段；纯十进制天然排除
  F5 位长异常裸 hex：(41-63) 或 (>64)；40 位与 64 位合法
  F6 标记族三类（描述族名时**不得**复写违规字面）
  F7 secretish

★ **本脚本可扫自己**：所有被检字面都用拼接／构造式表达，脚本源码自身不触发任何族。
★ 阳性对照必须**真的含**被检形态（用构造式生成），阴性对照必须**不含**；
  任一族「阳性=0 或 阴性>0」⇒ 该族探针本身失效 ⇒ 整轮判 FAIL。
"""
from __future__ import annotations

import json
import os
import re
import sys

# ── 构造式字面（禁把被检字面内嵌进本扫描器源码）────────────────────────────
HEX = "0123456789" + "".join(chr(c) for c in range(ord("a"), ord("f") + 1))
HEX_LETTERS = "".join(chr(c) for c in range(ord("a"), ord("f") + 1))
U_FFFD = chr(0xFFFD)
U_2026 = chr(0x2026)
DOTS = "." * 3
MARKERS = ["TO" + "DO", "FIX" + "ME", "TB" + "D", "XX" + "X",
           "待" + "填", "占位" + "符", "lore" + "m ipsum", "?" * 3]
SECRET_WORDS = ["pass" + "word", "sec" + "ret", "api" + "_key", "api-key", "tok" + "en"]
PRIVATE_KEY = "-----BEGIN " + "[A-Z ]*" + "PRIVATE KEY-----"

UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                     r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def hex_runs(text):
    """极大连续小写 hex 游程（含数字）⇒ [(start, end, run)]。"""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] in HEX:
            j = i
            while j < n and text[j] in HEX:
                j += 1
            out.append((i, j, text[i:j]))
            i = j
        else:
            i += 1
    return out


def _contained(a, b):
    """a 完全包含于 b。"""
    return b[0] <= a[0] and a[1] <= b[1]


def f1(t):
    return [m.start() for m in re.finditer(re.escape(U_FFFD), t)]


def f2(t):
    return [m.start() for m in re.finditer(re.escape(U_2026), t)]


def f3(t):
    return [m.start() for m in re.finditer(re.escape(DOTS), t)]


def f4(t):
    """截短小写 hex：7-39 位 + 至少一个 a-f + 不在 UUID 分段内。"""
    hits = []
    us = [(m.start(), m.end()) for m in UUID_RE.finditer(t)]
    for s, e, run in hex_runs(t):
        if not (7 <= len(run) <= 39):
            continue
        if not any(c in HEX_LETTERS for c in run):
            continue
        if any(_contained((s, e), u) for u in us):
            continue
        hits.append((s, run))
    return hits


def f5(t):
    """位长异常裸 hex：(41-63) 或 (>64)。"""
    hits = []
    for s, e, run in hex_runs(t):
        if 41 <= len(run) <= 63 or len(run) > 64:
            hits.append((s, len(run)))
    return hits


def f6(t):
    pat = re.compile(r"\b" + r"\b|\b".join(re.escape(m) for m in MARKERS) + r"\b", re.I)
    out = []
    for m in pat.finditer(t):
        out.append(m.start())
    return out


def f7(t):
    alt = "|".join(re.escape(w) for w in SECRET_WORDS)
    pat = re.compile(
        r"AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{16,}"
        r"|xox[baprs]-[A-Za-z0-9-]{10,}|" + PRIVATE_KEY +
        r"|(?i:" + alt + r")\s*[:=]\s*\S+")
    return [m.start() for m in pat.finditer(t)]


FAM = {
    "F1": ("编码层损坏字符", f1),
    "F2": ("单码点省略号", f2),
    "F3": ("ASCII 三点", f3),
    "F4": ("截短小写 hex（7-39 位且含 a-f，排除 UUID 分段）", f4),
    "F5": ("位长异常裸 hex（41-63 或 >64）", f5),
    "F6": ("标记族三类", f6),
    "F7": ("secretish", f7),
}

POS = {
    "F1": "损坏" + U_FFFD + "示例",
    "F2": "省略" + U_2026 + "示例",
    "F3": "三点" + DOTS + "示例",
    "F4": (HEX_LETTERS[:6] + "0123456"),
    "F5": ((HEX * 3)[:45]),
    "F6": "TO" + "DO 待" + "填",
    "F7": "pass" + "word=hunter2000",
}
NEG = {
    "F1": "正常 utf-8 文本",
    "F2": "普通省略表达",
    "F3": "两个点不触发",
    "F4": ("20261023 13800001111 110101199001011234 "
           "a079766cc2de94ee32113fc30ae003e5459057a1"),
    "F5": ("d1ebe3392fb20f04c2d0ecb00bbe639804187ac2 "
           "e13689cddeb077c826b0f854453d0d9bb62be70a1eca9cdc05edaa40ba7b2b04"),
    "F6": "已完成的实现",
    "F7": "普通描述文字",
}


def _targets(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
                for f in sorted(files):
                    out.append(os.path.join(root, f))
        else:
            out.append(p)
    return out


def main(paths):
    if not paths:
        print("用法：shape_probe.py <文件或目录> [更多路径]")
        return 2
    rc = 0
    total = 0
    for p in _targets(paths):
        with open(p, "rb") as fh:
            raw = fh.read()
        try:
            t = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            print("[%s] 严格 UTF-8 解码失败: %s" % (p, e))
            rc = 1
            continue
        total += 1
        print("== %s  bytes=%d" % (p, len(raw)))
        for fid, (name, fn) in FAM.items():
            pos = len(fn(POS[fid]))
            neg = len(fn(NEG[fid]))
            hits = fn(t)
            ok = (pos > 0 and neg == 0 and len(hits) == 0)
            if not ok:
                rc = 1
            detail = ""
            if hits:
                at = hits[0][0] if isinstance(hits[0], tuple) else hits[0]
                detail = "  首命中上下文: " + repr(t[max(0, at - 30):at + 40])
            print("  %s %-38s 阳性=%d 阴性=%d 命中=%d %s%s"
                  % (fid, name[:38], pos, neg, len(hits), "OK" if ok else "FAIL", detail))
    print(json.dumps({"files": total, "rc": rc}, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
