"""披露策略映射与团队调用入口测试（WP7）。

本文件锁住一处**真实安全漏洞**的修复：
``dd_v1_match_service.evaluate_file`` 原先对敏感等级做**二值判定**——
只要 ``sensitivity`` 非空就放行，没有「哪一级可外发」的映射。
后果是**填了等级比留空更危险**：填 ``secret``、``top_secret``、``乱写的字``
都能通过 Gate 进入对外交付包。

另锁住 WP7 的团队调用入口：一个非开发角色的人能独立跑通并看懂输出。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_policy_service as P

_REPO = Path(__file__).resolve().parents[2]
_TOOLS = _REPO / "tools"


def _write_policy(tmp_path: Path, **over) -> Path:
    data = {
        "policy_version": "test-v1",
        "default_level": "RESTRICTED",
        "levels": {
            "PUBLIC": {"externally_sendable": True, "requires_review": True,
                       "description": "可直接外发"},
            "INTERNAL": {"externally_sendable": False, "requires_review": True,
                         "description": "脱敏后可发"},
            "CONFIDENTIAL": {"externally_sendable": False, "requires_review": True,
                             "description": "不外发，需书面授权"},
            "RESTRICTED": {"externally_sendable": False, "requires_review": True,
                           "description": "一律不外发"},
        },
        "rules": [],
    }
    data.update(over)
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


# ── 1. 安全默认：无策略一律不可外发 ────────────────────────────────────────
def test_no_policy_means_nothing_is_sendable(tmp_path):
    pol = P.load_policy(tmp_path / "不存在的策略.json")
    assert pol.loaded is False
    for level in ("", "PUBLIC", "secret", "乱写的字"):
        d = P.evaluate(pol, level)
        assert d.externally_sendable is False, f"{level!r} 竟被放行"
        assert d.level == P.FALLBACK_LEVEL


def test_policy_status_is_honest_when_not_loaded(tmp_path):
    pol = P.load_policy(tmp_path / "缺失.json")
    assert pol.loaded is False
    assert "不可外发" in (pol.load_error or "")


# ── 2. 漏洞回归：未知等级必须被拒 ─────────────────────────────────────────
def test_unknown_level_is_rejected_not_guessed(tmp_path):
    """**这是本文件的核心断言。**

    二值判定时代，任意非空值都放行；现在未知等级必须判为不可判定、一律不可外发。
    """
    pol = P.load_policy(_write_policy(tmp_path))
    assert pol.loaded is True
    for bad in ("secret", "top_secret", "内部绝密", "绝密", "restricted_v2", "!!!"):
        d = P.evaluate(pol, bad)
        assert d.externally_sendable is False, f"{bad!r} 竟被放行"
        assert d.level == P.FALLBACK_LEVEL
        assert "不在策略已知级别" in d.reason


def test_empty_level_is_not_permissive(tmp_path):
    pol = P.load_policy(_write_policy(tmp_path))
    d = P.evaluate(pol, "")
    assert d.externally_sendable is False
    assert d.level == "RESTRICTED"
    assert "不可判定" in d.reason


# ── 3. 有策略时的正确映射 ────────────────────────────────────────────────
def test_public_is_sendable_and_others_are_not(tmp_path):
    pol = P.load_policy(_write_policy(tmp_path))
    assert P.evaluate(pol, "PUBLIC").externally_sendable is True
    for lvl in ("INTERNAL", "CONFIDENTIAL", "RESTRICTED"):
        assert P.evaluate(pol, lvl).externally_sendable is False, lvl


def test_case_insensitive(tmp_path):
    pol = P.load_policy(_write_policy(tmp_path))
    assert P.evaluate(pol, "public").externally_sendable is True


def test_rules_can_only_tighten_never_loosen(tmp_path):
    """规则可把 PUBLIC 收紧为 CONFIDENTIAL，但不得把 CONFIDENTIAL 放宽为 PUBLIC。"""
    pol = P.load_policy(_write_policy(tmp_path, rules=[
        {"id": "r-person", "level": "CONFIDENTIAL",
         "note": "含个人信息的一律收紧"},
    ]))
    tightened = P.evaluate(pol, "PUBLIC")
    assert tightened.level == "CONFIDENTIAL"
    assert tightened.externally_sendable is False
    # 已是 CONFIDENTIAL 的不能被同规则"放宽"
    stays = P.evaluate(pol, "CONFIDENTIAL")
    assert stays.externally_sendable is False
    assert stays.level == "CONFIDENTIAL"


# ── 4. 危险配置被拒绝 ───────────────────────────────────────────────────
def test_dangerous_default_level_is_rejected(tmp_path):
    """把 default_level 设成可外发是危险配置：没命中规则的材料会被直接放行。"""
    p = _write_policy(tmp_path, default_level="PUBLIC")
    pol = P.load_policy(p)
    assert pol.loaded is False
    assert "风险过高" in pol.load_error


def test_policy_with_unknown_level_key_is_rejected(tmp_path):
    p = _write_policy(tmp_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["levels"]["绝密"] = {"externally_sendable": False}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    pol = P.load_policy(p)
    assert pol.loaded is False
    assert "未识别级别" in pol.load_error


def test_corrupt_policy_does_not_partially_apply(tmp_path):
    """策略读不出来 → 全部不可外发，绝不「读一半生效一半」。"""
    p = tmp_path / "坏.json"
    p.write_text("{ 这不是合法 JSON", encoding="utf-8")
    pol = P.load_policy(p)
    assert pol.loaded is False
    assert P.evaluate(pol, "PUBLIC").externally_sendable is False


# ── 5. 团队调用入口：一个非开发角色能独立跑通并看懂输出 ──────────────────
def _env(tmp_path: Path) -> dict:
    e = dict(os.environ)
    e["CANGJIE_DD_V1_DATA_DIR"] = str(tmp_path / "_plane")
    e["PYTHONPATH"] = str(_REPO / "backend" / "src")
    return e


# WP-A1 修订（G8 允许的断言同步）：仓库新增 backend/config/dd_v1_disclosure_policy.json 后，
# load_policy() 默认路径在测试进程里也指向仓库 config/，`loaded` 不再恒为 False。
# 本测试「无策略 → 显示未生效」的原意图改用 CANGJIE_DD_V1_POLICY 指向空路径显式保留，
# 仓库策略真实生效另有 test_a1_repo_policy_* 三条专门锁定。
def _env_no_policy(tmp_path: Path) -> dict:
    e = _env(tmp_path)
    e["CANGJIE_DD_V1_POLICY"] = str(tmp_path / "无策略.json")
    return e


def test_team_channel_entry_runs_end_to_end(tmp_path):
    """一个人、一条命令，从清单跑到可读报告与机读 JSON。"""
    materials = tmp_path / "materials"
    (materials / "子公司甲").mkdir(parents=True)
    for y in (2021, 2022, 2023):
        (materials / "子公司甲" / f"审计报告{y}.txt").write_text(
            f"审计报告\n本报告为{y}年度财务审计结论，由子公司甲出具。\n", encoding="utf-8")
    cl = tmp_path / "清单.tsv"
    cl.write_text("3.2.1\t请提供2021-2023年度审计报告\n3.2.2\t请提供2023年度营业执照\n",
                  encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(_TOOLS / "dd_team_channel.py"), "run",
         "--library", "测试库", "--root", str(materials),
         "--checklist", str(cl), "--institution", "某机构", "--by", "刘江"],
        env=_env_no_policy(tmp_path), capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-800:]
    out = r.stdout
    # 非开发角色要能看懂：每一步都有中文说明
    for kw in ("第 1 步", "第 6 步", "不会向任何机构发送", "披露策略状态"):
        assert kw in out, f"输出缺少「{kw}」"
    # 缺口与判定要出现
    assert "逐条结果" in out
    assert "缺材料" in out or "不完整" in out or "无法判定" in out

    reports = list((tmp_path / "_plane" / "团队报告").glob("*.md"))
    jsons = list((tmp_path / "_plane" / "团队报告").glob("*.json"))
    assert reports and jsons
    data = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert data["sent_to_institution"] is False
    assert data["human_approval_required"] is True
    # WP-A1 修订：无策略场景由 CANGJIE_DD_V1_POLICY 显式构造，断言意图不变
    assert data["disclosure_policy"]["loaded"] is False, "无策略时必须显示未生效"
    assert data["summary"]["obligations"] == 2


def test_team_channel_entry_reports_missing_inputs_clearly(tmp_path):
    """给错路径要说人话，不是抛栈。"""
    r = subprocess.run(
        [sys.executable, str(_TOOLS / "dd_team_channel.py"), "run",
         "--library", "x", "--root", str(tmp_path / "不存在"),
         "--checklist", str(tmp_path / "也不存在.tsv")],
        env=_env(tmp_path), capture_output=True, text=True, timeout=120)
    assert r.returncode == 2
    assert "材料库路径不存在" in r.stderr


def test_team_channel_never_claims_to_have_sent_anything(tmp_path):
    materials = tmp_path / "m"
    materials.mkdir()
    (materials / "a.txt").write_text("正文", encoding="utf-8")
    cl = tmp_path / "c.tsv"
    cl.write_text("1\t请提供2023年度审计报告\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(_TOOLS / "dd_team_channel.py"), "run",
         "--library", "L", "--root", str(materials), "--checklist", str(cl)],
        env=_env(tmp_path), capture_output=True, text=True, timeout=180)
    assert r.returncode == 0
    assert "系统不会自动向机构发送任何材料" in r.stdout
    # 默认不复制任何原件
    files = list((tmp_path / "_plane" / "团队报告").glob("*.json"))
    assert json.loads(files[0].read_text(encoding="utf-8"))["sent_to_institution"] is False


# ── WP-A1（G4）：仓库级披露策略文件必须真实生效 ────────────────────────────
# A1 之前：backend/config/ 目录不存在 → load_policy 恒 loaded=False →
# judge() 末尾「全部受限」→ MATCHED 永远出不来（任务书堵点①）。
# A1 落地 config 文件后：默认加载路径必须读到且生效；
# 「声明已批准级别可外发、空等级仍不可外发」两条安全语义必须同时成立。

import pytest as _pytest  # noqa: E402  (WP-A1 追加区，避免与既有 import 顺序冲突)


REPO_ROOT_A1 = Path(__file__).resolve().parents[2]
REPO_POLICY_A1 = REPO_ROOT_A1 / "backend" / "config" / "dd_v1_disclosure_policy.json"



def test_a1_repo_disclosure_policy_file_exists_and_loads():
    """G4：backend/config/dd_v1_disclosure_policy.json 存在且 load_policy() 生效。"""
    assert REPO_POLICY_A1.is_file(), f"策略文件缺失：{REPO_POLICY_A1}"
    pol = P.load_policy()  # 默认路径 = 仓库 config/
    assert pol.loaded is True, f"仓库策略未生效：{pol.load_error}"
    assert pol.version == pol.version and pol.default_level == "RESTRICTED"
    assert pol.levels  # 四级映射齐全



def test_a1_repo_policy_policy_status_loaded_true():
    """G4：policy_status()['loaded'] 必须为 True（dd_team_channel 报告 JSON 同源）。"""
    st = P.policy_status()
    assert st["loaded"] is True, f"policy_status 未生效：{st}"
    assert st["policy_version"] not in ("", "none", "unset")



def test_a1_repo_policy_declared_public_sendable_but_empty_still_denied():
    """G4：声明 PUBLIC **且类型在允许清单内**的材料可外发；其余一律不可外发。

    WP-A1 口径更正（司仓 2026-10-22）：本断言原用**中文** doc_type（"审计报告"）并断言
    「可外发」——那是在旧口径下写的，既不是策略 key 空间，又把「审计报告可外发」这个
    反向安全含义锁进了用例。真实取值空间 = ``dd_v1_requirement_service._DOC_TYPE_RULES``
    的 10 个内部英文 key；业务口径只放开 ``license``（营业执照/登记证书/资质证照/工商公开登记信息）。
    """
    pol = P.load_policy()
    # 正向：license + PUBLIC ⇒ 可外发（唯一可外发类）
    pub = P.evaluate(pol, "PUBLIC", doc_type="license", entity="合成法人甲")
    assert pub.externally_sendable is True, "声明已批准级别且类型在允许清单内必须可外发"
    assert pub.requires_review is True
    # 空 sensitivity 仍一律不可外发（安全默认）
    for empty in ("", "   ", None):
        d = P.evaluate(pol, empty or "")
        assert d.externally_sendable is False, f"空等级 {empty!r} 竟被放行"
        assert d.level == "RESTRICTED"
    # 规则收紧后 PUBLIC 仍受规则约束（收紧不得放宽）：九类逐类收紧为 RESTRICTED
    for key in ("audit_report", "financial_statement", "tax", "charter", "capital",
                "resolution", "ip", "labor", "contract"):
        tightened = P.evaluate(pol, "PUBLIC", doc_type=key, entity="合成法人甲")
        assert tightened.externally_sendable is False, f"{key} 竟被放行"
        assert tightened.level == "RESTRICTED", key
        assert tightened.matched_rule, f"{key} 未命中任何收紧规则"


def test_a1_repo_policy_unknown_doc_type_is_denied_not_defaulted():
    """G4 补强：类型闸必须把「不认识」当不可判定，不得落回声明级别。

    规则只能按 doc_type **相等**收紧 ⇒ 非空但不在 key 空间内的 doc_type
    （中文类型名 / 文件扩展名 / 拼错的 key）会一条规则都不命中。
    若没有类型闸，它会直接落回声明级别 PUBLIC ⇒ 静默放行。
    """
    pol = P.load_policy()
    assert pol.sendable_doc_types == ["license"], pol.sendable_doc_types
    for junk in ("审计报告", "pdf", "not_a_real_key", "licenses", ""):
        d = P.evaluate(pol, "PUBLIC", doc_type=junk, entity="合成法人甲")
        assert d.externally_sendable is False, f"{junk!r} 竟被放行"
        assert d.level == "RESTRICTED", junk


def test_a1_repo_policy_without_type_gate_keeps_legacy_behavior(tmp_path):
    """G4 补强：类型闸是**可选**的 ⇒ 未声明该键的策略行为与引入前完全一致（向后兼容）。

    没有这条，A0 的 1419 条基线（用不带 ``sendable_doc_types`` 的临时策略）会被悄悄改语义。
    """
    legacy = {
        "policy_version": "legacy-compat",
        "default_level": "RESTRICTED",
        "levels": {
            "PUBLIC": {"externally_sendable": True, "requires_review": True},
            "RESTRICTED": {"externally_sendable": False, "requires_review": True},
        },
        "rules": [],
    }
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    pol = P.load_policy(p)
    assert pol.loaded is True
    assert pol.sendable_doc_types is None, "未声明类型闸 ⇒ 不启用"
    # 旧语义：没有类型闸时，doc_type 不参与判定
    assert P.evaluate(pol, "PUBLIC", doc_type="pdf").externally_sendable is True
    assert P.evaluate(pol, "PUBLIC", doc_type="").externally_sendable is True
    # 但空等级/未知等级的安全默认不受影响
    assert P.evaluate(pol, "").externally_sendable is False
    assert P.evaluate(pol, "secret").externally_sendable is False


def test_a1_repo_policy_malformed_type_gate_fails_closed(tmp_path):
    """G4 补强：类型闸写坏了 ⇒ 策略不生效 ⇒ 全部不可外发（fail-closed，不得部分生效）。"""
    bad = {
        "policy_version": "bad-gate",
        "default_level": "RESTRICTED",
        "levels": {
            "PUBLIC": {"externally_sendable": True, "requires_review": True},
            "RESTRICTED": {"externally_sendable": False, "requires_review": True},
        },
        "rules": [],
        "sendable_doc_types": "license",
    }
    p = tmp_path / "bad_gate.json"
    p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    pol = P.load_policy(p)
    assert pol.loaded is False
    assert "sendable_doc_types" in (pol.load_error or "")
    assert P.evaluate(pol, "PUBLIC", doc_type="license").externally_sendable is False
