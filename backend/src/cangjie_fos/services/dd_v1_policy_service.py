"""DD-V1 披露策略与「哪一级可外发」映射（WP7）。

## 为什么必须有这个模块

WP7 起草时发现一处**真实安全漏洞**：
``dd_v1_match_service.evaluate_file`` 原本对敏感等级做的是**二值判定**——

```python
if card.get("sensitivity") in ("", None):
    deliverable = 0
```

即：**只要 ``sensitivity`` 非空就放行**。没有「哪一级可以外发」的映射。
后果：把等级填成 ``secret``、``top_secret``、``内部绝密`` 甚至 ``乱写的字``
都会**通过** Gate 并进入对外交付包——**填了等级反而比留空更危险**。

## 本模块的处置

1. **显式的级别→可外发映射**，由版本化策略文件提供，不硬编码在判定逻辑里。
2. **未知等级一律拒绝**。填了认识不出的等级不是「更严格」，而是**不可判定**，
   按最严处理并留痕。
3. **无策略时默认全禁**。策略文件缺失/损坏/版本不识别 → 全部 ``RESTRICTED``，
   一律不可外发。这是安全默认，宁可不发不可错发。
4. **策略是数据不是代码**：等级名、判定维度、默认值都来自策略文件，
   业务负责人审核通过后改文件即可，**无需改代码、无需重新发版**。

## 与 #75 草案的关系

teams-channel #75 提出的草案 V0.1（**待业务审核，尚未生效**）给了四级命名：
``PUBLIC`` / ``INTERNAL`` / ``CONFIDENTIAL`` / ``RESTRICTED`` 与「默认取最严」。
本模块**按该草案预留**这四级名与该默认值，但：

- 草案未获审核通过 → 仓库**不放**该策略文件 → 全部材料 ``RESTRICTED``，一律不可外发。
- 审核通过 → 把策略文件放进 ``config/`` 并改 ``policy_version`` 即可生效。
- **本模块不替业务决定「什么材料算哪一级」**，那属于 #75 的审核范围。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# 建议的级别名（与 #75 草案一致）。**未获审核前不作为默认生效值。**
LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")

# 无策略 / 策略不可用时的兜底级别：最严，一律不可外发
FALLBACK_LEVEL = "RESTRICTED"

# 级别顺序，数字越大越严
_LEVEL_ORDER = {name: i for i, name in enumerate(LEVELS)}


@dataclass
class PolicyDecision:
    """一次披露判定的完整可追溯结果。"""
    level: str = FALLBACK_LEVEL
    externally_sendable: bool = False
    requires_review: bool = True
    reason: str = ""
    policy_version: str = "none"
    matched_rule: str = ""
    evidence: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "externally_sendable": self.externally_sendable,
            "requires_review": self.requires_review,
            "reason": self.reason,
            "policy_version": self.policy_version,
            "matched_rule": self.matched_rule,
        }


@dataclass
class DisclosurePolicy:
    """版本化披露策略。**策略是数据，判定是代码。**"""
    version: str = "unset"
    loaded: bool = False
    load_error: str = ""
    levels: dict = field(default_factory=dict)   # {LEVEL: {externally_sendable, requires_review}}
    default_level: str = FALLBACK_LEVEL
    rules: list = field(default_factory=list)   # 判定规则，按序

    def strictest(self, *names: str) -> str:
        """取若干级别中最严的一个。"""
        vals = [n for n in names if n in _LEVEL_ORDER]
        if not vals:
            return FALLBACK_LEVEL
        return max(vals, key=lambda n: _LEVEL_ORDER[n])


def _default_policy_path() -> Path:
    env = (os.getenv("CANGJIE_DD_V1_POLICY") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "config" / "dd_v1_disclosure_policy.json"


def load_policy(path: str | Path | None = None) -> DisclosurePolicy:
    """加载披露策略。**任何异常都退化为「全部不可外发」，绝不部分生效。**

    宁可「策略读不出来 → 什么都不发」，也不要「策略读了一半 → 半数规则失效」。
    """
    p = Path(path) if path else _default_policy_path()
    if not p.exists():
        return DisclosurePolicy(
            load_error=f"策略文件不存在：{p}；未配置披露政策时一律按最严处理，全部不可外发")

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return DisclosurePolicy(load_error=f"策略文件无法解析：{exc}")

    version = str(data.get("policy_version") or "").strip()
    if not version:
        return DisclosurePolicy(load_error="策略文件缺 policy_version，按未生效处理")

    levels_raw = data.get("levels") or {}
    if not isinstance(levels_raw, dict) or not levels_raw:
        return DisclosurePolicy(load_error="策略文件缺 levels 映射，按未生效处理")

    levels: dict = {}
    unknown = []
    for name, spec in levels_raw.items():
        key = str(name).strip().upper()
        if key not in _LEVEL_ORDER:
            # 未知级别**不静默丢弃也不静默接受**——必须报出来，
            # 否则「填个新等级名就绕过 Gate」的老坑会以另一种形式回来
            unknown.append(name)
            continue
        spec = spec if isinstance(spec, dict) else {}
        levels[key] = {
            "externally_sendable": bool(spec.get("externally_sendable", False)),
            "requires_review": bool(spec.get("requires_review", True)),
            "description": spec.get("description", ""),
        }

    if unknown:
        return DisclosurePolicy(
            version=version,
            load_error=f"策略含未识别级别 {unknown}；已知级别为 {list(LEVELS)}。"
                       f"未识别级别一律按最严处理，不做「猜一个相近的」",
            levels=levels)

    default_level = str(data.get("default_level") or FALLBACK_LEVEL).strip().upper()
    if default_level not in _LEVEL_ORDER:
        default_level = FALLBACK_LEVEL
    # **安全默认**：`default_level` 本身必须不可外发。
    # 若默认级别可外发，则任何没命中规则的材料都会被直接放行——这是最危险的配置。
    # （此处原写成 `not ... and != FALLBACK`，逻辑反了，`default_level: PUBLIC`
    #   反而被接受；由 test_dangerous_default_level_is_rejected 当场抓出。）
    if levels.get(default_level, {}).get("externally_sendable", False):
        return DisclosurePolicy(
            version=version,
            load_error=f"策略把 default_level 设为可外发的 {default_level}，"
                       f"风险过高；默认级别必须不可外发（安全默认）")

    return DisclosurePolicy(
        version=version, loaded=True, levels=levels,
        default_level=default_level,
        rules=list(data.get("rules") or []))


def evaluate(policy: DisclosurePolicy, sensitivity: str,
             doc_type: str = "", entity: str = "") -> PolicyDecision:
    """判定一份材料能否对外交付。

    **空等级不是「最宽松」而是「不可判定」**——按最严处理并说明原因。
    """
    # 1) 策略没生效 → 全部拒绝
    if not policy.loaded:
        return PolicyDecision(
            level=FALLBACK_LEVEL, externally_sendable=False, requires_review=True,
            reason=policy.load_error or "披露策略未配置，按安全默认一律不可对外",
            policy_version="none")

    raw = (sensitivity or "").strip()
    if not raw:
        return PolicyDecision(
            level=policy.default_level,
            externally_sendable=False, requires_review=True,
            reason="敏感等级为空 = 不可判定，按安全默认处理；不得因留空就放行",
            policy_version=policy.version)

    # 2) 等级必须认识。**不认识 ≠ 更严格，而是不可判定**
    level = raw.upper()
    if level not in policy.levels:
        return PolicyDecision(
            level=FALLBACK_LEVEL, externally_sendable=False, requires_review=True,
            reason=f"敏感等级 {raw!r} 不在策略已知级别 {sorted(policy.levels)} 内，"
                   f"按不可判定处理（一律不可外发），不得猜测",
            policy_version=policy.version)

    spec = policy.levels[level]

    # 3) 规则可进一步收紧（取最严），但**不得放宽**基线判定
    final = level
    matched = ""
    for rule in policy.rules:
        if not _rule_hit(rule, doc_type, entity):
            continue
        cand = str(rule.get("level") or "").strip().upper()
        if cand in _LEVEL_ORDER:
            final = policy.strictest(final, cand)
            matched = str(rule.get("id") or rule.get("name") or "")

    final_spec = policy.levels.get(final, {"externally_sendable": False,
                                           "requires_review": True})
    return PolicyDecision(
        level=final,
        externally_sendable=bool(spec["externally_sendable"]
                                 and final_spec["externally_sendable"]),
        requires_review=bool(final_spec["requires_review"]),
        reason=f"声明等级={raw}" + (f"，规则收紧为 {final}" if matched else ""),
        policy_version=policy.version,
        matched_rule=matched)


def _rule_hit(rule: dict, doc_type: str, entity: str) -> bool:
    """规则命中：纯确定性匹配，**不做语义猜测**。"""
    rt = rule.get("doc_type")
    if rt and doc_type and rt != doc_type:
        return False
    re_ = rule.get("entity")
    if re_ and entity and re_ != entity:
        return False
    # 规则本身没给条件 → 视为总是命中（用于「兜底收紧」）
    return True


def policy_status() -> dict:
    """策略生效状态——供 CLI/审核页如实展示，不隐去「未生效」。"""
    pol = load_policy()
    return {
        "policy_version": pol.version,
        "loaded": pol.loaded,
        "load_error": pol.load_error,
        "default_level": pol.default_level,
        "known_levels": sorted(pol.levels) if pol.levels else list(LEVELS),
        "externally_sendable_levels": [k for k, v in pol.levels.items()
                                       if v.get("externally_sendable")],
        "effective": "全部材料按最严处理，一律不可对外交付" if not pol.loaded
                     else "按策略分级执行",
    }
