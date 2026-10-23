# -*- coding: utf-8 -*-
"""MINOR-4 fixture 豁免闸口 · 回归守卫（5 条）。

★ 背景（监工第 38 条①；已用会话工作区探针 v2 **独立复现确证**）：
  `tools/dd_v1_local_run.py` 的合成 fixture 豁免曾写成
      fixture = inside(orig_material_root, fixtures) or inside(material_root, fixtures)
  而 `material_root` 在盲化/冻结之后 = **输出路径**
  ⇒ 闸口从「输入是不是真材料」退化成「输出落在哪」
  ⇒ 仓外材料 + 输出落仓内 fixtures ⇒ 闸口不触发 ⇒ 真实材料可被放行，
     且仓外材料的副本被写进仓内（公开仓泄漏面）。
  对照实验：A 仓内 fixture ⇒ 放行；C 仓外不盲化 ⇒ 拒绝；
            B 仓外 + 输出落仓内 ⇒ 旧实现**未**拒绝；B' 只按原始根 ⇒ 拒绝。

★ 本文件固定 5 条判据：
  T1 仓外材料 + 不盲化                     ⇒ exit 3 + stderr 含「BLOCKED: 真实材料」
  T2 仓外材料 + 盲化输出落**仓内** fixtures  ⇒ exit 3 **且仓内零材料副本**
  T3 仓内合成 fixture（正常流程）            ⇒ exit 0（正常放行）
  T4 豁免规则单测：只认**原始材料根**（且规则只吃一个参数 ⇒ 输出落点无法影响）
  T5 接线单测：cmd_run 交给闸口的 allow_real **只**由该规则决定（单一来源）

★ 纪律：
  - 测试**不得写/删仓库文件** ⇒ T2 需要「仓内 fixtures」时一律在**仓副本**（tmp）上跑；
    副本的 ROOT 由副本位置决定 ⇒ 判据语义与真仓一致。
  - 仓外材料用**自造合成内容**（零真实客户标识）。
"""
from __future__ import annotations

import contextlib
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_v1_local_run as lr  # noqa: E402

FIXTURE = REPO / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4"
MATERIAL = FIXTURE / "material"
A4_LEAK_WORDS = "Q-2024-07,案例甲机构,案例乙机构,星海项目"
#: 仓外材料的唯一指纹（用来查仓内是否被写入副本）
MARKER = "MINOR4-PROBE-MARKER"
OUTSIDE_MATERIAL = f"外部材料正文（合成回归用） 某外部机构 2024 年度审计报告。{MARKER}"


def _write_outside_material(root: Path) -> tuple[Path, Path, Path]:
    """造一份**仓外**合成材料（零真实客户标识）；meta 放在材料根内（盲化契约要求）。"""
    mat = root / "materials"
    mat.mkdir(parents=True, exist_ok=True)
    (mat / "audit_2024.txt").write_text(OUTSIDE_MATERIAL, encoding="utf-8")
    (mat / "meta.json").write_text(json.dumps(
        [{"file_id": "X001", "relative_path": "audit_2024.txt",
          "entity": "某外部机构", "period": "2024", "doc_type": "审计报告"}],
        ensure_ascii=False), encoding="utf-8")
    items = root / "items.json"
    items.write_text(json.dumps(
        [{"item_id": "R1", "entity": "某外部机构", "text": "请提供2024年度审计报告"}],
        ensure_ascii=False), encoding="utf-8")
    return mat, items, mat / "meta.json"


def _polluted(root: Path) -> list[str]:
    """仓内是否被写进了仓外材料的副本（按指纹查）。"""
    hits = []
    for p in root.rglob("*"):
        if p.is_file():
            try:
                if MARKER in p.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(p.relative_to(root)))
            except OSError:
                pass
    return hits


@pytest.fixture(scope="module")
def repo_copy(tmp_path_factory):
    """仓副本：ROOT 由副本位置决定 ⇒「输出落仓内 fixtures」在副本里成立，且**不写真仓**。"""
    dst = tmp_path_factory.mktemp("minor4") / "repo"
    dst.mkdir(parents=True)
    shutil.copytree(REPO / "tools", dst / "tools",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO / "backend" / "src", dst / "backend" / "src",
                    ignore=shutil.ignore_patterns("__pycache__"))
    fx = dst / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4"
    fx.mkdir(parents=True)
    shutil.copytree(FIXTURE / "material", fx / "material")
    shutil.copytree(FIXTURE / "replies", fx / "replies")
    shutil.copy2(FIXTURE / "raw_items.json", fx / "raw_items.json")
    return dst


# ---------------------------------------------------------------- T1 闸口：仓外必须拒绝
def test_outside_material_without_blind_is_blocked(tmp_path, capsys):
    """T1：仓外材料 + 不盲化 ⇒ exit 3 + 「BLOCKED: 真实材料」。"""
    mat, items, meta = _write_outside_material(tmp_path / "outside")
    rc = lr.main(["run", "--material-root", str(mat), "--meta", str(meta),
                  "--items", str(items), "--out", str(tmp_path / "run")])
    err = capsys.readouterr().err
    assert rc == 3, err
    assert "BLOCKED: 真实材料" in err, err


# ---------------------------------------------------------------- T2 闸口 + 写入门：输出落仓内也不得放行
def test_outside_material_blinding_into_repo_fixtures_is_blocked(repo_copy, tmp_path):
    """T2：仓外材料 + 盲化输出落**仓内** fixtures ⇒ exit 3，且**仓内零材料副本**。

    ★ 在**仓副本**上跑（测试不得写仓库文件）；副本的 ROOT = 副本位置。
    """
    mat, items, meta = _write_outside_material(tmp_path / "outside")
    blind_into = repo_copy / "backend" / "tests" / "fixtures" / "probe-evilcase" / "blind"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_copy / "backend" / "src")
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(k, None)
    p = subprocess.run(
        [sys.executable, str(repo_copy / "tools" / "dd_v1_local_run.py"), "run",
         "--material-root", str(mat), "--meta", str(meta), "--items", str(items),
         "--out", str(tmp_path / "run"),
         "--blind-material-out", str(blind_into),
         "--blind-leak-words", "某外部机构",
         "--blind-mapping-out", str(tmp_path / "map.json")],
        capture_output=True, text=True, env=env, cwd=str(repo_copy))
    err = p.stdout + p.stderr
    assert p.returncode == 3, err
    assert "不得写入仓库目录" in err, err
    # ★ 泄漏面：仓内**不得**留下任何仓外材料副本
    assert _polluted(repo_copy) == [], _polluted(repo_copy)


# ---------------------------------------------------------------- T3 仓内合成 fixture 必须正常放行
def test_inside_fixture_is_allowed(tmp_path, capsys):
    """T3：仓内合成 fixture（正常流程）⇒ exit 0。写入门不得误伤仓内 fixture。"""
    obl = tmp_path / "obligations.json"
    items = tmp_path / "blinded_items.json"
    assert lr.main(["split", "--items", str(FIXTURE / "raw_items.json"), "--out", str(obl),
                    "--blind-leak-words", A4_LEAK_WORDS, "--blind-items-out", str(items)]) == 0
    rc = lr.main(["run",
                  "--material-root", str(MATERIAL), "--meta", str(MATERIAL / "meta.json"),
                  "--items", str(items), "--obligations", str(obl),
                  "--blind-material-out", str(tmp_path / "blind"),
                  "--blind-leak-words", A4_LEAK_WORDS,
                  "--blind-mapping-out", str(tmp_path / "mapping.json"),
                  "--adapter", "manual", "--synthetic-replies", str(FIXTURE / "replies"),
                  "--out", str(tmp_path / "run")])
    err = capsys.readouterr().err
    assert rc == 0, err


# ---------------------------------------------------------------- T4 豁免规则单测
def test_exemption_rule_depends_only_on_original_material_root(tmp_path):
    """T4：豁免规则只认**原始材料根**；规则只吃一个参数 ⇒ 输出落点无法影响豁免。"""
    assert lr._fixture_exempt(MATERIAL) is True          # 仓内合成 fixture ⇒ 豁免
    outside = tmp_path / "materials"
    outside.mkdir()
    assert lr._fixture_exempt(outside) is False          # 仓外 ⇒ 不豁免
    params = list(inspect.signature(lr._fixture_exempt).parameters)
    assert params == ["orig_material_root"], params      # ★ 输出路径在结构上进不来


# ---------------------------------------------------------------- T5 接线单测：单一来源
def test_cmd_run_decides_exemption_via_the_single_rule(tmp_path, monkeypatch):
    """T5：cmd_run 交给闸口的 allow_real **只**由豁免规则决定（单一来源，无第二处判定）。"""
    mat, items, meta = _write_outside_material(tmp_path / "outside")
    seen: dict = {}
    real = lr.sem.local_material_snapshot

    def spy(root, meta_, *, allow_real=False):
        seen["allow_real"] = allow_real
        return real(root, meta_, allow_real=allow_real)

    monkeypatch.setattr(lr.sem, "local_material_snapshot", spy)
    args = ["run", "--material-root", str(mat), "--meta", str(meta),
            "--items", str(items), "--out", str(tmp_path / "run"),
            "--adapter", "manual", "--synthetic-replies", str(FIXTURE / "replies")]

    assert lr.main(args) == 3                     # 仓外材料 ⇒ 闸口拒绝
    assert seen["allow_real"] is False            # ★ 闸口收到的 allow_real 必须是 False

    # 把规则打成 True ⇒ 闸口收到的 allow_real 必须变成 True
    # ⇒ 证明 cmd_run **只**经由该规则决策（没有第二处硬编码判定）
    monkeypatch.setattr(lr, "_fixture_exempt", lambda p: True)
    with contextlib.suppress(Exception, SystemExit):
        lr.main(args)
    assert seen["allow_real"] is True
