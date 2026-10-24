#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A1 / G4 披露策略实测（司仓自证，不依赖任何外部目录）。

口径：
- 策略判定吃**义务侧** doc_type（见 dd_v1_match_service.py:196-198）
- doc_type 取值空间 = dd_v1_requirement_service._DOC_TYPE_RULES 的 10 个内部英文 key
- license（营业执照/登记证书）= 唯一可外发类；其余九类收紧 RESTRICTED；空 doc_type = 最严兜底

用法：
    cd backend && .venv/bin/python ../docs/dd-v1-fos71/wp05-real-integration/a1-evidence/check_policy_g4.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from cangjie_fos.services import dd_v1_policy_service as pol  # noqa: E402
from cangjie_fos.services import dd_v1_requirement_service as req  # noqa: E402

TIGHTENED = ["audit_report", "financial_statement", "tax", "charter", "capital",
             "resolution", "ip", "labor", "contract"]


def main() -> int:
    p = pol.load_policy()
    keys = [k for k, _ in req._DOC_TYPE_RULES]
    cases = []

    # --- 结构性前置 ---
    assert p.loaded, f"策略未生效：{p.load_error}"
    assert set(keys) == set(TIGHTENED + ["license"]), f"key 空间漂移：{keys}"
    assert p.default_level == "RESTRICTED", f"default_level 必须 RESTRICTED，实为 {p.default_level}"
    assert p.levels["PUBLIC"]["externally_sendable"] is True
    for lv in ("INTERNAL", "CONFIDENTIAL", "RESTRICTED"):
        assert p.levels[lv]["externally_sendable"] is False, f"{lv} 不得可外发"
    assert p.levels["RESTRICTED"]["externally_sendable"] is False

    # --- 三禁令 ---
    for r in p.rules:
        assert r.get("doc_type"), f"无条件规则（总是命中）：{r}"
        assert not r.get("entity"), f"entity 规则（entity 常为空 ⇒ 等同无条件）：{r}"
    assert all(str(r.get("level", "")).upper() == "RESTRICTED" for r in p.rules), \
        "规则只能收紧为 RESTRICTED"
    assert not any(r.get("doc_type") == "license" for r in p.rules), "license 不得被收紧"

    # --- 类型闸必须启用且只放行 license ---
    assert p.sendable_doc_types is not None, "类型闸未启用：非 key 的 doc_type 会落回声明级别"
    assert p.sendable_doc_types == ["license"], p.sendable_doc_types

    # --- 正向：license + PUBLIC + entity 非空 ⇒ 可外发 ---
    d = pol.evaluate(p, "PUBLIC", doc_type="license", entity="甲公司")
    cases.append(("G4-P1 license+PUBLIC => True", d.externally_sendable is True,
                  f"level={d.level} matched={d.matched_rule!r}"))

    # --- 正向：同一 license 但无 entity 也应放行（license 无收紧规则）---
    d = pol.evaluate(p, "PUBLIC", doc_type="license", entity="")
    cases.append(("G4-P2 license+PUBLIC+空entity => True", d.externally_sendable is True,
                  f"level={d.level}"))

    # --- 反向：九类逐类收紧 ---
    for k in TIGHTENED:
        d = pol.evaluate(p, "PUBLIC", doc_type=k, entity="甲公司")
        cases.append((f"G4-R1 {k} => False", d.externally_sendable is False,
                      f"level={d.level} matched={d.matched_rule!r}"))

    # --- 反向：空 sensitivity（不可判定）---
    d = pol.evaluate(p, "", doc_type="license", entity="甲公司")
    cases.append(("G4-R2 空 sensitivity => False", d.externally_sendable is False,
                  f"level={d.level}"))

    # --- 反向：未知等级 ---
    d = pol.evaluate(p, "TOP_SECRET_X", doc_type="license", entity="甲公司")
    cases.append(("G4-R3 未知等级 => False", d.externally_sendable is False,
                  f"level={d.level}"))

    # --- 反向：空 doc_type（最严兜底）---
    d = pol.evaluate(p, "PUBLIC", doc_type="", entity="甲公司")
    cases.append(("G4-R4 空 doc_type => False", d.externally_sendable is False,
                  f"level={d.level} matched={d.matched_rule!r}"))

    # --- 反向：其余三档声明等级 ---
    for lv in ("INTERNAL", "CONFIDENTIAL", "RESTRICTED"):
        d = pol.evaluate(p, lv, doc_type="license", entity="甲公司")
        cases.append((f"G4-R5 {lv} => False", d.externally_sendable is False,
                      f"level={d.level}"))

    # --- 反向：中文 doc_type 不应命中任何规则（证明 key 空间一致）---
    d = pol.evaluate(p, "PUBLIC", doc_type="营业执照", entity="甲公司")
    cases.append(("G4-R6 中文 doc_type 不得放行（类型闸兜底）",
                  d.externally_sendable is False,
                  f"level={d.level} matched={d.matched_rule!r}"))

    # --- 反向：文件扩展名不得放行 ---
    d = pol.evaluate(p, "PUBLIC", doc_type="pdf", entity="甲公司")
    cases.append(("G4-R7 扩展名 doc_type 不得放行", d.externally_sendable is False,
                  f"level={d.level} matched={d.matched_rule!r}"))

    # --- 反向：不存在的 key 不得放行 ---
    d = pol.evaluate(p, "PUBLIC", doc_type="not_a_real_key", entity="甲公司")
    cases.append(("G4-R8 未知 key 不得放行", d.externally_sendable is False,
                  f"level={d.level}"))

    # --- 同类归一：大小写/空白扰动不得改变同一类材料的判定 ---
    for jitter in (" LICENSE ", "License", "license ", "LiCeNsE"):
        d = pol.evaluate(p, "PUBLIC", doc_type=jitter, entity="甲公司")
        cases.append((f"G4-R9a 同类归一 {jitter!r} ⇒ 与 license 一致(可外发)",
                      d.externally_sendable is True,
                      f"level={d.level}"))

    # --- 近邻串必须拒绝：不得用包含/前缀匹配当类型闸 ---
    for near in ("licenses", "license2", "xlicense", "licen", "sub_license"):
        d = pol.evaluate(p, "PUBLIC", doc_type=near, entity="甲公司")
        cases.append((f"G4-R9b 近邻串 {near!r} 不得放行", d.externally_sendable is False,
                      f"level={d.level}"))

    ok = sum(1 for _, good, _ in cases if good)
    for name, good, detail in cases:
        print(f"{'PASS' if good else 'FAIL'}  {name}   [{detail}]")
    print(f"\n{ok}/{len(cases)} passed")
    print(f"policy_version={p.version} default_level={p.default_level} "
          f"rules={len(p.rules)} sendable_doc_types={p.sendable_doc_types} "
          f"doc_type_keys={keys}")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
