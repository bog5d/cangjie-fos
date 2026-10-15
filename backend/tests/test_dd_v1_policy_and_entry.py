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
        env=_env(tmp_path), capture_output=True, text=True, timeout=180)
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
