"""WP2 收口：★**0 件时 CLI 不得把「未产出正式交付件」说成「交付包已生成」**。

## 为什么必须有这个文件（★独立 Reviewer 终局复核抓出来的★）

★**独立 Reviewer 在 `d8b318f` 上的终局裁定是 CONDITIONAL，★唯一阻塞项就是这个**：

`tools/dd_team_channel.py` 在 ``package_approved`` 返回后**无条件**打印
``"  ✓ 交付包已生成：<目录>"`` ⇒ ★**即使 ``exported == 0``（一件原件都没复制）**，
★ **终端仍然显示「✓ 交付包已生成」**。

⇒ ★**这与 WP2 的原话直接冲突**：
> 「允许生成供人工检查的候选包，但**必须明确标注为非正式交付**。
> **不得把候选包冒充正式交付包。**」

★**产品自己的词汇表里本就区分这两种状态** —— ★同一个文件里「审核失效」分支的措辞是
「本次**未复制任何原件**、**未产出正式交付件**」⇒ ★**「0 件」这一档只是漏了同样的措辞**。

★**安全性质本身成立**（Reviewer 已核）：0 件 ⇒ **无任何原件被外发**、交付目录**无原件副本**、
``06-实际交付文件目录.tsv`` **仅表头**、``SHA256SUMS`` **0 字节**、
``正式交付包-说明.md`` 自陈**交付件数：0**。
⇒ ★**本条只锁「措辞」**：★**不得让操作员把「0 件」读成「已交付」**。

## 本文件锁死的判据

1. **判据 A（0 件）**：CLI 标准输出**不得**含「✓ 交付包已生成」；
   ★**必须**含「未产出正式交付件」＋「复制原件数 0」；
2. **判据 B（阳性对照 · 1 件）**：CLI 标准输出**必须**含「✓ 交付包已生成」＋「复制原件数 1」
   （★**防「闸坏了 / 样本没造对」：★若 A 恒不响，可能是这条也一起不响**★）。

## 纪律

- 全部材料**现场合成**（tmp_path），**零真实材料 / 零模型 / 零费用**；
- **不读 Gold Set**；★**只走规则层**，不接任何适配器。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cangjie_fos.services import (
    dd_v1_card_service as cs,
    dd_v1_manifest_service as mf,
    dd_v1_parser_service as ps,
    dd_v1_requirement_service as rq,
)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_team_channel as dtc  # noqa: E402

#: 合成主体（虚构，不含任何真实机构名）
PARENT = "合成甲控股母公司"
LIB = "lib-wp2cli"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """独立数据面 + 独立库（零交叉污染）。"""
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path) -> Path:
    return tmp_path / "_plane" / "manifest.sqlite"


def _license(y: int) -> str:
    return (f"营业执照\n名称：{PARENT}\n"
            f"本执照为{y}年度核发版本，登记事项为合成样例。\n")


def _audit(y: int) -> str:
    return (f"审计报告\n主体：{PARENT}\n"
            f"本报告为{y}年度财务审计结论，由{PARENT}出具。\n")


def _setup(tmp_path, files: dict[str, str]):
    """建库 → 扫描 → 解析 → 建卡 → 登记主体。返回 (root, checklist 路径)。"""
    root = tmp_path / "materials"
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.register_library(LIB, str(root), authorized_by="WP2CLI", db_path=_db(tmp_path))
    mf.build_manifest(LIB, db_path=_db(tmp_path))
    ps.parse_pending_batch(LIB, db_path=_db(tmp_path))
    cs.build_cards_for_library(LIB, db_path=_db(tmp_path))
    rq.register_entity(LIB, "E1", PARENT, relation="parent",
                       source_ref="合成样例（测试用，非真实登记）", db_path=_db(tmp_path))
    checklist = tmp_path / "checklist.tsv"
    checklist.write_text(f"1\t请提供{PARENT}2024年度审计报告\n", encoding="utf-8")
    return root, checklist


def _run_cli(tmp_path, root: Path, checklist: Path, capsys):
    argv = [
        "dd_team_channel.py", "run",
        "--library", LIB,
        "--root", str(root),
        "--checklist", str(checklist),
        "--institution", "合成机构",
        "--by", "测试",
        "--anchor-year", "2024",
        "--package",
        "--approved-by", "测试批准人",
        "--package-out", str(tmp_path / "pkg"),
        "--out", str(tmp_path / "rep"),
    ]
    old = sys.argv
    sys.argv = argv
    try:
        rc = dtc.main()
    finally:
        sys.argv = old
    out = capsys.readouterr().out
    return rc, out


def test_A_zero_exported_must_not_claim_package_generated(tmp_path, capsys):
    """★判据 A★：**0 件时** CLI 不得说「✓ 交付包已生成」。

    ★ 场景：只有**审计报告**（按设计收紧、不可外发）⇒ 一件都进不了正式交付包。
    """
    root, checklist = _setup(tmp_path, {
        f"{PARENT}/审计报告2024.txt": _audit(2024),
    })
    rc, out = _run_cli(tmp_path, root, checklist, capsys)

    assert "复制原件数 0" in out, out[-2000:]
    assert "✓ 交付包已生成" not in out, (
        "0 件时仍印「✓ 交付包已生成」⇒ **把未产出正式交付件说成了已交付**"
        "（WP2：不得把候选包冒充正式交付包）")
    assert "未产出正式交付件" in out, out[-2000:]


def test_B_one_exported_still_says_package_generated(tmp_path, capsys):
    """★判据 B★（★阳性对照★）：**1 件时** CLI 仍要说「✓ 交付包已生成」。

    ★ 防「闸坏了 / 样本没造对」：★若判据 A 恒不响，★可能是因为**这一档也不响**。
    """
    root, checklist = _setup(tmp_path, {
        f"{PARENT}/营业执照2024.txt": _license(2024),
    })
    # ★ 清单改成要营业执照（**可外发类**）⇒ 应当导出 1 件
    checklist.write_text(f"1\t请提供{PARENT}2024年度营业执照\n", encoding="utf-8")
    rc, out = _run_cli(tmp_path, root, checklist, capsys)

    assert "复制原件数 1" in out, out[-2000:]
    assert "✓ 交付包已生成" in out, out[-2000:]
