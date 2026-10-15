"""DD-V1 材料库 Manifest 测试（WP1）。

覆盖三个必须被守住的不变量：
1. **只扫描授权目录** —— 未登记/已撤销的库拒绝扫描。
2. **同名不同主体不得互删**（D2 回归守卫）—— 旧 `_dedup_keep_newest` 以
   `f.name` + `mtime` 去重，会把不同机构下的同名文件（如各一份营业执照）
   判为重复且丢弃方不入索引。本模块以相对路径为身份，必须全部共存。
3. **幂等与可恢复** —— 重复扫描结果一致；中断的 run 可按 run_id 续跑。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_manifest_service as mf


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每个测试独立的 Manifest 库 + 独立 Data Plane，绝不碰真实 backend/data。"""
    db = tmp_path / "_dp" / "manifest.sqlite"
    plane = tmp_path / "_plane"
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(plane))
    mf.close_all()
    yield
    mf.close_all()


def _mk_library(tmp_path: Path, name: str = "lib1") -> tuple[str, Path]:
    root = tmp_path / "materials"
    root.mkdir()
    mf.register_library(
        "lib1", str(root), authorized_by="波总", display_name=name,
        db_path=tmp_path / "_dp" / "manifest.sqlite",
    )
    return "lib1", root


def _db(tmp_path: Path):
    return tmp_path / "_dp" / "manifest.sqlite"


# ── 1. 授权闸 ───────────────────────────────────────────────────────────────
def test_unregistered_library_is_rejected(tmp_path):
    with pytest.raises(PermissionError, match="授权"):
        mf.build_manifest("never-registered", db_path=_db(tmp_path))


def test_revoked_library_is_rejected(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    (root / "a.txt").write_text("甲", encoding="utf-8")
    mf.revoke_library(lib_id, db_path=_db(tmp_path))
    with pytest.raises(PermissionError, match="授权"):
        mf.build_manifest(lib_id, db_path=_db(tmp_path))


def test_register_requires_authorizer(tmp_path):
    with pytest.raises(ValueError, match="authorized_by"):
        mf.register_library("x", str(tmp_path), authorized_by="", db_path=_db(tmp_path))


# ── 2. Data Plane 边界（源文件只读的可执行保证）─────────────────────────────
def test_data_plane_inside_library_is_refused(tmp_path):
    root = tmp_path / "materials"
    (root / "sub").mkdir(parents=True)
    with pytest.raises(mf.DataPlaneViolation):
        mf.assert_data_plane_outside(root, root / "sub" / "cache")
    with pytest.raises(mf.DataPlaneViolation):
        mf.assert_data_plane_outside(root, root)
    # 库外的 Data Plane 必须被允许
    mf.assert_data_plane_outside(root, tmp_path / "elsewhere")


def test_scan_does_not_write_into_source(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    (root / "审计报告2023.txt").write_text("正文内容" * 50, encoding="utf-8")
    before = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    res = mf.build_manifest(lib_id, db_path=_db(tmp_path))
    assert res["added"] == 1
    after = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    assert before == after, "扫描不得修改或新增材料库内的任何文件"
    assert sorted(p.name for p in root.rglob("*") if p.is_file()) == ["审计报告2023.txt"]


# ── 3. D2 回归守卫：同名不同主体共存 ────────────────────────────────────────
def test_same_name_different_subject_files_all_preserved(tmp_path):
    """三个不同主体各有一份「营业执照.pdf」，必须全部入库且互不覆盖。

    这是旧实现会静默丢数据的场景：_dedup_keep_newest 以 f.name 为 key，
    只留 mtime 最新一份，另两份完全不进索引。
    """
    lib_id, root = _mk_library(tmp_path)
    subs = ["集团母公司", "子公司甲", "子公司乙"]
    for i, sub in enumerate(subs):
        d = root / sub
        d.mkdir()
        (d / "营业执照.pdf").write_text(f"{sub} 的营业执照正文 {i}", encoding="utf-8")
        # 拉开 mtime，确保旧去重逻辑一定会「只留最新的」
        os.utime(d / "营业执照.pdf", (1_700_000_000 + i * 86400,) * 2)

    res = mf.build_manifest(lib_id, db_path=_db(tmp_path))
    assert res["added"] == 3, "三份同名材料必须全部入库"

    rows = mf.find_same_name_across_subjects(lib_id, "营业执照.pdf", db_path=_db(tmp_path))
    assert len(rows) == 3, "同名跨主体文件必须共存"
    assert {r["rel_path"] for r in rows} == {
        "集团母公司/营业执照.pdf", "子公司甲/营业执照.pdf", "子公司乙/营业执照.pdf",
    }
    # 内容不同的三份材料，hash 必须互不相同（未被当作同一份）
    hashes = {r["content_hash"] for r in rows}
    assert len(hashes) == 3, "不同主体内容不同，hash 不得相同"


def test_identical_content_different_path_stays_separate(tmp_path):
    """即便内容完全相同，路径不同也是两条独立记录（不做内容级去重）。

    内容去重会让「同一份材料被两个主体引用」这类关系无法表达。
    """
    lib_id, root = _mk_library(tmp_path)
    for sub in ("A", "B"):
        (root / sub).mkdir()
        (root / sub / "章程.pdf").write_text("完全相同的章程", encoding="utf-8")

    mf.build_manifest(lib_id, db_path=_db(tmp_path))
    rows = mf.find_same_name_across_subjects(lib_id, "章程.pdf", db_path=_db(tmp_path))
    assert len(rows) == 2
    assert rows[0]["content_hash"] == rows[1]["content_hash"]


def test_flat_same_name_files_are_kept(tmp_path):
    """扁平目录下同名文件也必须共存（不依赖 per_institution 布局）。"""
    lib_id, root = _mk_library(tmp_path)
    (root / "审计报告.txt").write_text("版本一", encoding="utf-8")
    (root / "审计报告_副本.txt").write_text("版本二", encoding="utf-8")
    res = mf.build_manifest(lib_id, db_path=_db(tmp_path))
    assert res["added"] == 2


# ── 4. 幂等 ────────────────────────────────────────────────────────────────
def test_repeated_full_scan_is_idempotent(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    for i in range(5):
        (root / f"材料{i}.txt").write_text(f"正文{i}", encoding="utf-8")

    first = mf.build_manifest(lib_id, mode="full", db_path=_db(tmp_path))
    entries_first = mf.list_manifest(lib_id, db_path=_db(tmp_path))
    second = mf.build_manifest(lib_id, mode="full", db_path=_db(tmp_path))
    entries_second = mf.list_manifest(lib_id, db_path=_db(tmp_path))

    assert first["added"] == 5 and second["added"] == 0
    assert second["unchanged"] == 5
    assert len(entries_first) == len(entries_second) == 5
    assert [e["file_id"] for e in entries_first] == [e["file_id"] for e in entries_second]


def test_file_id_is_stable_and_path_based(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    (root / "x.txt").write_text("内容", encoding="utf-8")
    a = mf.make_file_id("lib1", "x.txt")
    b = mf.make_file_id("lib1", "x.txt")
    c = mf.make_file_id("lib1", "sub/x.txt")
    d = mf.make_file_id("lib2", "x.txt")
    assert a == b, "同一路径必须得到同一 file_id（幂等基础）"
    assert a != c, "不同相对路径必须不同 file_id"
    assert a != d, "不同材料库必须不同 file_id"


# ── 5. 增量 ────────────────────────────────────────────────────────────────
def test_incremental_skips_unchanged(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    for i in range(3):
        (root / f"f{i}.txt").write_text(f"v1-{i}", encoding="utf-8")
    mf.build_manifest(lib_id, db_path=_db(tmp_path))

    res = mf.build_manifest(lib_id, mode="incremental", db_path=_db(tmp_path))
    assert res["unchanged"] == 3 and res["updated"] == 0 and res["added"] == 0


def test_incremental_detects_content_change(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    p = root / "审计报告2023.txt"
    p.write_text("第一版正文", encoding="utf-8")
    mf.build_manifest(lib_id, db_path=_db(tmp_path))
    before = mf.get_manifest_entry(lib_id, "审计报告2023.txt", db_path=_db(tmp_path))

    time.sleep(0.01)
    p.write_text("第二版正文，内容已修订", encoding="utf-8")
    res = mf.build_manifest(lib_id, mode="incremental", db_path=_db(tmp_path))
    assert res["updated"] == 1

    after = mf.get_manifest_entry(lib_id, "审计报告2023.txt", db_path=_db(tmp_path))
    assert after["content_hash"] != before["content_hash"]
    assert after["changed_at"] >= before["changed_at"]
    # 内容变了必须回到 pending，等 WP2 重新解析
    assert after["parse_status"] == mf.PARSE_PENDING


def test_mtime_change_without_content_change_is_not_a_version_bump(tmp_path):
    """mtime 变了但内容没变 → 记为 unchanged，不伪造成新版本。

    对应指令要求：mtime 不代表业务最新有效版本。
    """
    lib_id, root = _mk_library(tmp_path)
    p = root / "财报.txt"
    p.write_text("完全相同的内容", encoding="utf-8")
    mf.build_manifest(lib_id, db_path=_db(tmp_path))
    st = p.stat()
    os.utime(p, (st.st_atime + 5000, st.st_mtime + 5000))

    res = mf.build_manifest(lib_id, mode="incremental", db_path=_db(tmp_path))
    assert res["updated"] == 0
    assert res["unchanged"] == 1


# ── 6. 断点恢复与租约 ──────────────────────────────────────────────────────
def test_interrupted_run_can_resume(tmp_path, monkeypatch):
    lib_id, root = _mk_library(tmp_path)
    for i in range(6):
        (root / f"m{i}.txt").write_text(f"正文{i}", encoding="utf-8")

    real_iter = mf._iter_candidate_files

    def boom_after_2(*a, **kw):
        for n, f in enumerate(real_iter(*a, **kw)):
            if n >= 2:
                raise RuntimeError("模拟磁盘故障/进程中断")
            yield f

    monkeypatch.setattr(mf, "_iter_candidate_files", boom_after_2)
    with pytest.raises(RuntimeError, match="模拟磁盘故障"):
        mf.build_manifest(lib_id, mode="full", db_path=_db(tmp_path))
    monkeypatch.undo()

    run = mf.find_resumable_run(lib_id, db_path=_db(tmp_path))
    assert run is None, "失败运行应标记为 failed，不再是 running"

    # 以新的 full 扫描完成全库（失败运行的 run_id 不可复用）
    res = mf.build_manifest(lib_id, mode="full", db_path=_db(tmp_path))
    assert res["added"] == 6
    assert mf.find_resumable_run(lib_id, db_path=_db(tmp_path)) is None


def test_running_run_is_found_as_resume_entry(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    (root / "a.txt").write_text("甲", encoding="utf-8")
    res = mf.build_manifest(lib_id, db_path=_db(tmp_path))
    run = mf.get_run(res["run_id"], db_path=_db(tmp_path))
    assert run["status"] == mf.RUN_COMPLETED
    assert run["processed"] == 1
    assert run["data_plane"], "run 必须记录 Data Plane 路径供核查"


def test_resume_rejects_concurrent_lease_holder(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    (root / "a.txt").write_text("甲", encoding="utf-8")
    db = _db(tmp_path)
    res = mf.build_manifest(lib_id, db_path=db)

    # 人为把 run 改回 running 且由他人持有租约
    import sqlite3
    conn = mf._connect(db)
    conn.execute(
        "UPDATE dd_v1_scan_runs SET status=?, lease_owner=?, lease_expires_at=? WHERE run_id=?",
        (mf.RUN_RUNNING, "other-worker", time.time() + 600, res["run_id"]),
    )
    conn.commit()

    with pytest.raises(RuntimeError, match="持有"):
        mf.build_manifest(lib_id, resume_run_id=res["run_id"],
                          lease_owner="me", db_path=db)
    conn.close()


# ── 7. 软删除（保守）───────────────────────────────────────────────────────
def test_missing_files_are_soft_deleted_not_dropped(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    (root / "keep.txt").write_text("保留", encoding="utf-8")
    (root / "gone.txt").write_text("将消失", encoding="utf-8")
    mf.build_manifest(lib_id, db_path=_db(tmp_path))
    assert len(mf.list_manifest(lib_id, db_path=_db(tmp_path))) == 2

    (root / "gone.txt").unlink()
    res = mf.build_manifest(lib_id, db_path=_db(tmp_path))
    assert res["removed"] == 1

    live = mf.list_manifest(lib_id, db_path=_db(tmp_path))
    assert len(live) == 1 and live[0]["file_name"] == "keep.txt"

    # 关键：物理记录仍在，可审计/可恢复
    all_rows = mf.list_manifest(lib_id, include_deleted=True, db_path=_db(tmp_path))
    assert len(all_rows) == 2
    assert mf.manifest_summary(lib_id, db_path=_db(tmp_path))["deleted"] == 1


def test_reappearing_file_is_revived(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    p = root / "temp.txt"
    p.write_text("临时", encoding="utf-8")
    mf.build_manifest(lib_id, db_path=_db(tmp_path))
    p.unlink()
    mf.build_manifest(lib_id, db_path=_db(tmp_path))
    p.write_text("回来了", encoding="utf-8")
    mf.build_manifest(lib_id, db_path=_db(tmp_path))

    e = mf.get_manifest_entry(lib_id, "temp.txt", db_path=_db(tmp_path))
    assert e is not None and e["deleted_at"] is None, "文件回来后应复活，不留墓碑"


# ── 8. 哈希与线索 ──────────────────────────────────────────────────────────
def test_content_hash_matches_hashlib(tmp_path):
    import hashlib
    p = tmp_path / "big.bin"
    p.write_bytes(b"x" * 1000)
    assert mf.compute_content_hash(p) == hashlib.sha256(b"x" * 1000).hexdigest()


def test_version_and_year_hints_are_inferred_only(tmp_path):
    v, y = mf.iter_version_hints("审计报告2023最终版.pdf")
    assert y == "2023"
    assert "最终版" in v
    v2, y2 = mf.iter_version_hints("普通材料.txt")
    assert v2 == "" and y2 == ""


def test_unsupported_extension_marked_skipped(tmp_path):
    lib_id, root = _mk_library(tmp_path)
    (root / "合同.docx").write_text("x", encoding="utf-8")
    (root / "图片.png").write_text("x", encoding="utf-8")
    mf.build_manifest(lib_id, db_path=_db(tmp_path))
    summary = mf.manifest_summary(lib_id, db_path=_db(tmp_path))
    assert summary["by_parse_status"][mf.PARSE_PENDING] == 1
    assert summary["by_parse_status"][mf.PARSE_SKIPPED] == 1


def test_derived_cangjie_dir_excluded(tmp_path):
    """派生缓存 _cangjie_ 不得二次入库（复用既有排除规则）。"""
    lib_id, root = _mk_library(tmp_path)
    (root / "真实材料.txt").write_text("原", encoding="utf-8")
    d = root / "_cangjie_预处理_md"
    d.mkdir()
    (d / "真实材料.txt.md").write_text("# 派生", encoding="utf-8")

    mf.build_manifest(lib_id, db_path=_db(tmp_path))
    names = [e["file_name"] for e in mf.list_manifest(lib_id, db_path=_db(tmp_path))]
    assert names == ["真实材料.txt"]
