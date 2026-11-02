"""「声称 ↔ 实现」机读守卫（把虚假 PASS 变成可回归的红灯）。

★ 为什么需要它（本轮两次独立 Reviewer FAIL 的**同款根因**）：
  文档写「G8 真实模型参与门禁已落地 / 三模式字段已落地 / 永久回归已落地」，
  而冻结实现里 `requested_mode` / `execution_path` / `identity_verified` /
  `NO_REAL_MODEL_RUN_AT_ALL` **grep 命中 0** ⇒ **文档在制造虚假 PASS**。
  ⇒ 凡是「声称已落地」的东西，都必须有一条**可机读的实现证据**；
  证据不存在时，状态只能是 `UNSUPPORTED`（违规），**不允许**悄悄留在「已落地」。

★ 状态语义（刻意区分「没做」和「说了没做」）：
  - `IMPLEMENTED`：声称已落地 **且** 证据全部命中；
  - `UNSUPPORTED`：**声称已落地但证据不命中** ⇒ 虚假 PASS ⇒ 违规（守卫必须红）；
  - `DECLARED_UNKNOWN`：声称本身写了「未落地/未知」⇒ **不违规**（但缺口仍然可见）；
  - `NOT_IMPLEMENTED`：无证据且未声明状态 ⇒ 违规。

★ 能力边界（必须如实承认）：
  守卫只证明「**字面锚点**在仓里存在」，**不**证明它被真正执行过、
  也**不**证明语义正确 ⇒ 它是「有没有」的闸，不是「对不对」的闸。
  语义正确性靠**独立 Reviewer + 回归测试 + 对抗性变异**三条腿。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "dd_v1_claims_guard.v1"

CLAIM_IMPLEMENTED = "IMPLEMENTED"
CLAIM_UNSUPPORTED = "UNSUPPORTED"
CLAIM_DECLARED_UNKNOWN = "DECLARED_UNKNOWN"
CLAIM_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

#: 声称「已落地」时允许的书写方式（含中文与英文变体）。
_STATUS_IMPLEMENTED = {"IMPLEMENTED", "IMPLEMENTED_AND_VERIFIED", "LANDED", "已落地", "已完成"}
#: 声称「未落地 / 未知」的书写方式。
_STATUS_UNKNOWN = {"NOT_IMPLEMENTED", "UNKNOWN", "PENDING", "OPEN", "BLOCKED", "未落地", "未知", "待定"}

EVIDENCE_TYPES = ("file_exists", "file_absent", "grep", "json_value", "json_path_exists",
                   "json_items_all")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dig(obj: Any, dotted: str) -> tuple[bool, Any]:
    """按 `a.b.c` 取值；返回 (是否存在, 值)。

    ★ 支持三种根写法：`""` / `"$"` / `"$."` 都表示**根对象**（列表也合法）。
      （教训：曾把 `"$"` 当普通路径 ⇒ 报「不是列表」⇒ 守卫「因为错误的理由」而绿。）
    """
    if dotted in ("", "$", "$."):
        return True, obj
    cur = obj
    for part in dotted.lstrip("$.").split("."):
        if not part:
            continue
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def _iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            out.append(p)
    return out


def check_evidence(ev: dict, repo_root: Path) -> dict:
    """检查**一条**实现证据；返回 {ok, type, detail}。"""
    kind = ev.get("type")
    if kind not in EVIDENCE_TYPES:
        return {"ok": False, "type": kind, "detail": "未知证据类型"}
    rel = ev.get("path")
    if not rel:
        return {"ok": False, "type": kind, "detail": "证据缺少 path"}
    target = repo_root / rel

    if kind == "file_exists":
        ok = target.exists()
        return {"ok": ok, "type": kind, "detail": ("存在" if ok else "不存在: %s" % rel)}

    if kind == "file_absent":
        ok = not target.exists()
        return {"ok": ok, "type": kind, "detail": ("确实不存在" if ok else "仍然存在: %s" % rel)}

    if kind == "grep":
        if not target.exists():
            return {"ok": False, "type": kind, "detail": "路径不存在: %s" % rel}
        pattern = ev.get("pattern")
        if not pattern:
            return {"ok": False, "type": kind, "detail": "grep 证据缺少 pattern"}
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return {"ok": False, "type": kind, "detail": "正则非法: %s" % e}
        min_hits = int(ev.get("min_hits", 1))
        hits = 0
        for f in _iter_files(target):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            hits += len(rx.findall(text))
        ok = hits >= min_hits
        return {"ok": ok, "type": kind, "detail": "命中 %d 次（要求 ≥%d）" % (hits, min_hits),
                "hits": hits}

    if kind in ("json_value", "json_path_exists", "json_items_all"):
        if not target.exists():
            return {"ok": False, "type": kind, "detail": "路径不存在: %s" % rel}
        try:
            obj = _read_json(target)
        except (OSError, json.JSONDecodeError) as e:
            return {"ok": False, "type": kind, "detail": "JSON 读不出来: %s" % e}
        dotted = ev.get("json_path")
        if not dotted:
            return {"ok": False, "type": kind, "detail": "%s 证据缺少 json_path" % kind}
        found, val = _dig(obj, dotted)
        if kind == "json_path_exists":
            return {"ok": found, "type": kind, "detail": ("存在" if found else "缺失: %s" % dotted)}
        if kind == "json_value":
            if not found:
                return {"ok": False, "type": kind, "detail": "缺失: %s" % dotted}
            expected = ev.get("equals")
            ok = (val == expected)
            return {"ok": ok, "type": kind,
                    "detail": "值=%r（要求 %r）" % (val, expected)}

        # —— json_items_all：列表里**每一条**都要满足字段断言 ——
        if not found or not isinstance(val, list):
            return {"ok": False, "type": kind, "detail": "不是列表: %s" % dotted}
        if not val:
            return {"ok": False, "type": kind, "detail": "列表为空: %s" % dotted}
        field = ev.get("field")
        if not field:
            return {"ok": False, "type": kind, "detail": "json_items_all 缺少 field"}
        bad: list[str] = []
        for i, item in enumerate(val):
            if not isinstance(item, dict) or field not in item:
                bad.append("#%d 缺字段 %s" % (i, field))
                continue
            v = item[field]
            if "not_contains" in ev and str(ev["not_contains"]) in str(v):
                bad.append("#%d %s=%r 含 %r" % (i, field, v, ev["not_contains"]))
            elif "equals" in ev and v != ev["equals"]:
                bad.append("#%d %s=%r（要求 %r）" % (i, field, v, ev["equals"]))
            elif "matches_regex" in ev:
                try:
                    if not re.search(ev["matches_regex"], str(v)):
                        bad.append("#%d %s=%r 不匹配 %r" % (i, field, v, ev["matches_regex"]))
                except re.error as e:
                    return {"ok": False, "type": kind, "detail": "正则非法: %s" % e}
            else:
                return {"ok": False, "type": kind,
                        "detail": "json_items_all 需要 not_contains / equals / matches_regex 之一"}
        ok = not bad
        detail = ("%d 条全部满足" % len(val)) if ok else ("%d/%d 条不满足：%s"
                                                         % (len(bad), len(val), bad[0]))
        return {"ok": ok, "type": kind, "detail": detail}

    return {"ok": False, "type": kind, "detail": "未处理的证据类型"}


def evaluate_claim(claim: dict, repo_root: Path) -> dict:
    """评估**一条**声称 ⇒ 机读状态。"""
    cid = claim.get("id") or "<无 id>"
    raw_status = str(claim.get("status") or "").strip()
    evidence = claim.get("evidence") or []
    checks = [check_evidence(e, repo_root) for e in evidence]
    satisfied = bool(checks) and all(c["ok"] for c in checks)

    if satisfied:
        status = CLAIM_IMPLEMENTED
    elif raw_status in _STATUS_UNKNOWN:
        status = CLAIM_DECLARED_UNKNOWN
    elif raw_status in _STATUS_IMPLEMENTED:
        status = CLAIM_UNSUPPORTED          # ★ 说了「已落地」却拿不出证据 ⇒ 虚假 PASS
    else:
        status = CLAIM_NOT_IMPLEMENTED

    return {
        "id": cid,
        "claim": claim.get("claim", ""),
        "declared_status": raw_status,
        "status": status,
        "violation": status in (CLAIM_UNSUPPORTED, CLAIM_NOT_IMPLEMENTED),
        "evidence_checks": checks,
        "note": claim.get("note", ""),
    }


def check_claims(claims: list[dict], repo_root: Path) -> dict:
    """评估一组声称 ⇒ 汇总报告。"""
    results = [evaluate_claim(c, repo_root) for c in claims]
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    violations = [r for r in results if r["violation"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "n_claims": len(results),
        "by_status": by_status,
        "violations": violations,
        "verdict": "PASS" if not violations else "FAIL",
        "results": results,
        "capability_boundary": "本守卫只证明「给出的实现证据是否成立」，"
                               "不证明它被真正执行、也不证明语义正确；"
                               "证据是否**充分**支撑该声称，仍需人判断。",
    }


def load_claims(claims_path: Path) -> list[dict]:
    data = _read_json(claims_path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("claims"), list):
        return data["claims"]
    raise ValueError("claims 文件格式无法识别：%s" % claims_path)
