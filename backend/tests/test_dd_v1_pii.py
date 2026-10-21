"""WP-A1（G5）：DD-V1 PII 拒识名单与确定性拒识服务。

铁律（任务书 G5）：
- **身份类正则只有一份来源** = 本仓已验收的 ``desensitize_service._IDENTITY_PATTERNS``
  （邮箱/身份证/银行卡/手机号/座机）；名单文件
  backend/config/dd_v1_pii_denylist.json **只承载增量/覆盖**（统一社会信用代码），
  不得再抄一份全量正则（A1 整改 M-1）；
- dd_v1_pii_service 纯规则、确定性、可复现；
- 拒识在两处生效：出模型前（build_semantic_packet 的 untrusted_excerpt / 义务文本）与
  入索引前（parser 抽取正文写卡片缓存前）；
- 合成用例全部使用**合成假值**，不使用任何真实号码。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_pii_service as pii

REPO = Path(__file__).resolve().parents[2]
DENYLIST = REPO / "backend" / "config" / "dd_v1_pii_denylist.json"

# 合成假值（明显非真实的测试值，非任何真实证件/账号）
SYN_ID = "11010119900101001X"          # 假身份证（18 位，含校验位 X）
SYN_BANK = "6200000000000000001"       # 假银行账号（19 位）
SYN_MOBILE = "13800000000"             # 假手机号
SYN_USCC = "91310000MA1K35L8X0"        # 假统一社会信用代码

PII_TEXT = (
    "【合成样例 / SYNTHETIC — 非真实资料】\n"
    f"合成法人甲（虚构）联系人测试：身份证{SYN_ID}，账号{SYN_BANK}，"
    f"手机{SYN_MOBILE}，统一社会信用代码{SYN_USCC}。\n"
    "本段其余为普通业务描述：2024 年度审计报告正文，营收为虚构数字 1,234 元。"
)


# ── 1. 名单文件 ─────────────────────────────────────────────────────────────
def test_denylist_file_exists_and_loads():
    assert DENYLIST.is_file(), f"PII 拒识名单缺失：{DENYLIST}"
    st = pii.denylist_status()
    assert st["source"] == "config", f"名单未从 config 加载：{st}"
    types = {p["type"] for p in st["patterns"]}
    assert {"身份证号", "银行卡/账号", "手机号", "统一社会信用代码"} <= types, types


# ── 1b. 复用纪律（A1 整改 M-1）：身份类正则**只有一份来源** ───────────────────
def test_pii_reuses_desensitize_service_instead_of_copying():
    """基线模式必须**逐条来自** desensitize_service，不得是手抄副本。

    这条锁死 A1 第一轮 Reviewer 判的 M-1：docstring 声称复用、代码却从不 import，
    且仓内同一套正则存在 3 份副本（desensitize_service / _BUILTIN_PATTERNS / config JSON）。
    """
    import inspect

    from cangjie_fos.services import desensitize_service as ds

    src = inspect.getsource(pii)
    assert "desensitize_service" in src, "PII 服务必须真正 import desensitize_service"

    base = pii._derive_base_patterns()
    assert len(base) == len(ds._IDENTITY_PATTERNS), (len(base), len(ds._IDENTITY_PATTERNS))
    upstream = {p.pattern for _lab, p, _repl in ds._IDENTITY_PATTERNS}
    for b in base:
        assert b["pattern"] in upstream, f"基线模式不是 desensitize_service 的：{b['type']}"


def test_denylist_config_carries_only_increments_not_a_full_copy():
    """名单文件只承载**增量/覆盖**，不得再抄一份全量正则。"""
    data = json.loads(DENYLIST.read_text(encoding="utf-8"))
    base_pats = {b["pattern"] for b in pii._derive_base_patterns()}
    for it in data.get("patterns") or []:
        assert it["pattern"] not in base_pats, \
            f"名单又抄了一份基线正则：{it.get('type')}"
    types = {it.get("type") for it in data.get("patterns") or []}
    assert types == {"统一社会信用代码"}, types


def test_pii_output_matches_desensitize_baseline_except_label_and_increment():
    """与基线输出对照：**除标签口径与增量项外必须完全一致**。

    标签口径差异 = 「银行卡」在 DD-V1 叫「银行卡/账号」、占位符是 ``[账号]``；
    增量项 = 统一社会信用代码（desensitize 未覆盖）。
    """
    from cangjie_fos.services import desensitize_service as ds

    for raw in ("11010119900101001X", "6222021234567890123", "13800000000",
                "someone@example.com", "010-12345678", "13800000000@example.com"):
        a = pii.redact(raw)
        b = ds.desensitize(raw)["masked_text"]
        if raw == "6222021234567890123":
            assert a == b.replace("[银行卡]", "[账号]"), (a, b)
        else:
            assert a == b, (raw, a, b)


# ── 2. 确定性拒识 ───────────────────────────────────────────────────────────
def test_redact_masks_all_synthetic_pii():
    out = pii.redact_detailed(PII_TEXT)
    t = out["text"]
    for raw in (SYN_ID, SYN_BANK, SYN_MOBILE, SYN_USCC):
        assert raw not in t, f"拒识后仍含原串：{raw}"
    assert "[身份证]" in t and "[账号]" in t and "[手机]" in t and "[统一社会信用代码]" in t
    assert out["redacted"] is True
    hit_types = {h["type"] for h in out["hits"]}
    assert {"身份证号", "银行卡/账号", "手机号", "统一社会信用代码"} <= hit_types


def test_redact_is_deterministic():
    a = pii.redact(PII_TEXT)
    b = pii.redact(PII_TEXT)
    assert a == b, "同一输入必须得到同一输出（纯规则可复现）"
    assert pii.contains_pii(PII_TEXT) is True


def test_clean_text_not_mangled():
    """普通业务文本（年份/金额/编号）不得被误脱。"""
    clean = "2024 年度审计报告正文，营收为虚构数字 1,234 元，报告文号 FX-2024-0089。"
    out = pii.redact_detailed(clean)
    assert out["redacted"] is False
    assert out["text"] == clean


def test_id_card_never_leaks_via_bank_rule():
    """顺序敏感回归：身份证必须先于银行卡规则，18 位证件号不得被截断替换。"""
    out = pii.redact(f"证件号{SYN_ID}，请核对。")
    assert SYN_ID not in out
    assert "[身份证]" in out
    assert "[账号]" not in out  # 未被银行卡规则抢先截断


def test_broken_config_falls_closed_to_builtin(monkeypatch, tmp_path):
    """名单文件损坏时 fail-closed：退回内置默认模式，绝不静默关闭拒识。"""
    bad = tmp_path / "bad.json"
    bad.write_text("{不是JSON", encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_PII_DENYLIST", str(bad))
    pii._reset_cache()
    out = pii.redact(f"身份证{SYN_ID}")
    assert SYN_ID not in out and "[身份证]" in out
    assert pii.denylist_status()["source"] == "builtin"
    pii._reset_cache()


# ── 3. 入索引前钩子（parser → 卡片缓存）────────────────────────────────────
def test_parser_redacts_text_before_card_cache(tmp_path):
    """G5 位置 2：抽取正文写进卡片缓存前必须拒识；缓存与 FTS 里不得有 PII 原串。"""
    import os

    os.environ["CANGJIE_DD_V1_DATA_DIR"] = str(tmp_path / "_plane")
    from cangjie_fos.services import dd_v1_card_service as cs
    from cangjie_fos.services import dd_v1_manifest_service as mf
    from cangjie_fos.services import dd_v1_parser_service as ps
    from cangjie_fos.core import paths as fos_paths

    mf.close_all()
    root = tmp_path / "materials"
    root.mkdir()
    (root / "合成法人甲_含PII.txt").write_text(PII_TEXT, encoding="utf-8")
    mf.register_library("piilib", str(root), authorized_by="A1", db_path=None)
    mf.build_manifest("piilib", db_path=None)
    out = ps.extract_and_record("piilib",
                                mf.get_manifest_entry("piilib", "合成法人甲_含PII.txt",
                                                      db_path=None)["file_id"],
                                db_path=None)
    assert out["parse_status"] == mf.PARSE_OK
    conn = mf._connect(None)
    row = conn.execute("SELECT text FROM dd_v1_text_cache").fetchone()
    assert row is not None, "正文缓存应已写入"
    cached = row["text"]
    for raw in (SYN_ID, SYN_BANK, SYN_MOBILE, SYN_USCC):
        assert raw not in cached, f"缓存泄露 PII 原串：{raw}"
    assert "[身份证]" in cached
    fts = conn.execute("SELECT body FROM dd_v1_material_fts").fetchone()
    assert fts is None or (SYN_ID not in fts["body"] and SYN_MOBILE not in fts["body"])
    mf.close_all()


# ── 4. 出模型前钩子（semantic packet）─────────────────────────────────────
def test_semantic_packet_redacts_untrusted_excerpt_and_obligations(tmp_path):
    """G5 位置 1：build_semantic_packet 产出的 untrusted_excerpt / 义务文本不得含 PII。"""
    from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem

    root = tmp_path / "snap"
    root.mkdir()
    (root / "m1.txt").write_text(
        "【合成样例 / SYNTHETIC — 非真实资料】\n"
        f"合成法人甲（虚构）2024 年度审计报告正文。经办人身份证{SYN_ID}，"
        f"手机{SYN_MOBILE}，账号{SYN_BANK}，信用代码{SYN_USCC}。\n",
        encoding="utf-8")
    meta = [{"file_id": "P1", "relative_path": "m1.txt", "entity": "合成法人甲",
             "period": "2024", "doc_type": "审计报告", "part": "正文",
             "version_status": "EFFECTIVE"}]
    obligations = [{"item_id": "I1", "obligation_id": "I1-O1", "text":
                    f"提供合成法人甲（联系人手机{SYN_MOBILE}）2024 年度审计报告",
                    "entity": "合成法人甲", "period": "2024", "doc_type": "审计报告",
                    "required_parts": ["正文"], "split_method": "FOS_OBLIGATION"}]
    pkt = sem.build_semantic_packet(root, meta, [], obligations=obligations)
    ev = pkt["evidence"]["I1-O1"][0]
    for raw in (SYN_ID, SYN_BANK, SYN_MOBILE, SYN_USCC):
        assert raw not in ev["untrusted_excerpt"], f"出模型文本泄露 PII：{raw}"
    assert SYN_MOBILE not in pkt["obligations"][0]["text"], "义务文本泄露 PII"
    assert SYN_MOBILE in obligations[0]["text"], "原义务对象不得被就地改写"
    assert pkt.get("pii_redactions", {}).get("count", 0) > 0, "拒识必须留痕"


def test_packet_without_pii_keeps_text_verbatim():
    """无 PII 时义务 text 必须与 FOS 侧逐字一致（G7 的前提）。"""
    from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem

    root = REPO / "backend" / "tests" / "fixtures" / "dd_v1_fos71_wp04" / "snapshot"
    meta = [{"file_id": "G001", "relative_path": "G001_shili_audit_2024_body.txt",
             "entity": "示例科技有限公司", "period": "2024", "doc_type": "审计报告",
             "part": "正文", "version_status": "EFFECTIVE"}]
    text = "提供示例科技有限公司2024年度审计报告（含附注）"
    obligations = [{"item_id": "R1", "obligation_id": "R1-O1", "text": text,
                    "entity": "示例科技有限公司", "period": "2024",
                    "doc_type": "审计报告", "required_parts": ["正文"],
                    "split_method": "FOS_OBLIGATION"}]
    pkt = sem.build_semantic_packet(root, meta, [], obligations=obligations)
    assert pkt["obligations"][0]["text"] == text, "无 PII 不得改动义务原文"
    assert pkt["pii_redactions"]["count"] == 0
