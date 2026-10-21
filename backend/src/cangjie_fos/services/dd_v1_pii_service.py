"""DD-V1 PII 拒识服务（WP-A1 / G5）。

**纯规则、确定性、可复现**——拒识是安全底线，绝不依赖会漂移的模型。

职责：把材料正文 / 义务文本里的个人敏感信息（身份证号、银行卡/账号、手机号、
统一社会信用代码等）替换成稳定占位符，在两处强制生效：

1. **出模型前**（``dd_v1_semantic_retrieval_service.build_semantic_packet``）：
   ``untrusted_excerpt`` 与义务 ``text`` 进 prompt 前不得含 PII；
2. **入索引前**（``dd_v1_parser_service.extract_and_record`` → ``cache_text``）：
   抽取正文写进卡片缓存 / FTS 前不得含 PII。

名单来自 ``backend/config/dd_v1_pii_denylist.json``（版本化、可审计）；
文件缺失/损坏时 **fail-closed** 退回内置默认模式（绝不静默关闭拒识）。

设计来源（SCP §1 复用优先）：身份类正则**不在本模块维护第二份**，
一律从本仓已验收的 ``desensitize_service._IDENTITY_PATTERNS`` **派生**
（连它的「先长后短、身份证不被银行卡规则截断」的顺序也照搬）；
本模块只做两件事：
1. **薄适配层**：把 desensitize 的标签/占位符翻成 DD-V1 口径
   （``银行卡/账号`` + ``[账号]``）——**唯一允许的差异**；
2. **增量**：补上 desensitize **没有**覆盖的「统一社会信用代码」，
   由版本化名单 ``backend/config/dd_v1_pii_denylist.json`` 承载
   （名单同时可**覆盖**基线里同名的类型）。

业务数字（金额/文号）不脱——与 ``test_desensitize.py`` 的红线一致。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# ★ 复用优先（SCP §1 / A1-R5）：身份类正则**只有一份**——desensitize_service。
from cangjie_fos.services import desensitize_service

#: desensitize_service 的标签 → (DD-V1 类型名, DD-V1 占位符)
#: 这是本模块**唯一**允许的差异（类型名口径 + 「银行卡」在 DD-V1 叫「银行卡/账号」）。
_TYPE_MAP: dict[str, tuple[str, str]] = {
    "邮箱": ("邮箱", "[邮箱]"),
    "身份证": ("身份证号", "[身份证]"),
    "银行卡": ("银行卡/账号", "[账号]"),
    "手机号": ("手机号", "[手机]"),
    "座机": ("座机", "[电话]"),
}

#: 本仓新增的一类（desensitize_service 覆盖的是 邮箱/身份证/银行卡/手机/座机）。
#: 名单文件缺失/损坏时用它兜底（fail-closed：宁可按最严拒识）。
_USCC_PATTERN: dict[str, str] = {
    "type": "统一社会信用代码",
    "pattern": r"[159Y][1239]\d{6}[0-9A-HJ-NP-RTUWXY]{10}",
    "replacement": "[统一社会信用代码]",
}


def _derive_base_patterns() -> list[dict[str, str]]:
    """基线模式：**从 desensitize_service 派生**（本模块不持有第二份正则）。

    顺序**照搬** desensitize_service 的顺序（邮箱 → 身份证 → 银行卡 → 手机号 → 座机）：
    身份证必须先于银行卡（否则 18 位证件号被 16–19 位规则截断）；
    邮箱在前可保证「手机+邮箱」这类样本与 desensitize 的输出**完全一致**。
    """
    out: list[dict[str, str]] = []
    for label, pat, repl in desensitize_service._IDENTITY_PATTERNS:
        t, r = _TYPE_MAP.get(label, (label, repl))
        out.append({"type": t, "pattern": pat.pattern, "replacement": r})
    return out


def _builtin_extra_patterns() -> list[dict[str, str]]:
    """名单缺失/损坏时的兜底增量（仍然拒识统一社会信用代码）。"""
    return [dict(_USCC_PATTERN)]


_CACHE: dict[str, Any] = {}


def _default_denylist_path() -> Path:
    env = (os.getenv("CANGJIE_DD_V1_PII_DENYLIST") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "config" / "dd_v1_pii_denylist.json"


def _load_patterns() -> dict[str, Any]:
    """加载名单。任何异常都退回内置默认（fail-closed），并保留 load_error 供审计。"""
    if _CACHE:
        return _CACHE
    p = _default_denylist_path()
    # 基线：desensitize_service 派生（**唯一来源**）
    base = _derive_base_patterns()
    patterns: list[dict[str, str]] = [dict(x) for x in base]
    source, error = "builtin", ""
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            raw = data.get("patterns") or []
            compiled: list[dict[str, str]] = []
            for it in raw:
                if not isinstance(it, dict):
                    continue
                pat = str(it.get("pattern") or "").strip()
                if not pat:
                    continue
                re.compile(pat)  # 先验证再收录；坏模式整条丢弃
                compiled.append({
                    "type": str(it.get("type") or "未命名"),
                    "pattern": pat,
                    "replacement": str(it.get("replacement") or "[已拒识]"),
                })
            if compiled:
                # 名单是**增量/覆盖**：同 type 覆盖基线，新 type 追加在基线之后
                # （追加 ⇒ 增量项在「银行卡」之后，避免 18 位纯数字账号被误判成 USCC）。
                merged = {x["type"]: x for x in base}
                for x in compiled:
                    merged[x["type"]] = x
                ordered = [dict(x) for x in base if x["type"] not in
                           {c["type"] for c in compiled}]
                ordered += [x for x in compiled]
                patterns, source = ordered, "config"
        except Exception as exc:  # noqa: BLE001 — 名单损坏必须 fail-closed，不静默关闭
            error = f"名单文件无法解析：{exc}"
    else:
        error = f"名单文件不存在：{p}"
    if source == "builtin":
        # 名单不可用 ⇒ 退回「基线 + 内置增量」，**仍然拒识**，绝不静默关闭
        patterns = [dict(x) for x in base] + _builtin_extra_patterns()
    _CACHE.update({"patterns": patterns, "source": source, "load_error": error,
                   "path": str(p),
                   "base_source": "desensitize_service._IDENTITY_PATTERNS（唯一来源）"})
    return _CACHE


def _reset_cache() -> None:
    """测试与换名单时清缓存（名单在进程内缓存，保证确定性）。"""
    _CACHE.clear()


def denylist_status() -> dict[str, Any]:
    """名单加载状态——供 CLI/报告如实展示，不隐去「未生效」。"""
    c = _load_patterns()
    return {"source": c["source"], "path": c["path"], "load_error": c["load_error"],
            "base_source": c.get("base_source", ""),
            "patterns": [{"type": p["type"]} for p in c["patterns"]]}


def redact_detailed(text: str) -> dict[str, Any]:
    """确定性拒识。返回 {text, hits, count, redacted}。

    hits 每项含 type/original/replacement（original 仅即时返回给操作者复核，
    调用方**不得**把它写进任何外发或入库产物）。
    """
    if not text:
        return {"text": "", "hits": [], "count": 0, "redacted": False}
    c = _load_patterns()
    masked = text
    hits: list[dict[str, str]] = []
    for spec in c["patterns"]:
        pat = re.compile(spec["pattern"])

        def _sub(m: re.Match[str], _spec=spec) -> str:
            hits.append({"type": _spec["type"], "original": m.group(0),
                         "replacement": _spec["replacement"]})
            return _spec["replacement"]

        masked = pat.sub(_sub, masked)
    return {"text": masked, "hits": hits, "count": len(hits),
            "redacted": masked != text}


def redact(text: str) -> str:
    """只取拒识后文本的便捷入口（管线内默认用这个）。"""
    return redact_detailed(text)["text"]


def contains_pii(text: str) -> bool:
    """快速判定：文本里是否还有可识别的 PII 模式（用于断言/自检）。"""
    if not text:
        return False
    c = _load_patterns()
    return any(re.search(p["pattern"], text) for p in c["patterns"])
