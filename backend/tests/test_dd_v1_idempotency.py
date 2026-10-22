"""WP-A2（G-A2-9）：入口 A 的清单摄取**幂等**。

## 为什么需要（实测根因）

旧实现每跑一次入口 A 就 `INSERT` 一批新 item + 新义务（义务 id 用 uuid4）
⇒ **同一个 `CANGJIE_DD_V1_DATA_DIR` 连跑两次，义务数直接翻倍**
（监工第 27 轮实测：32 → 64，`obligations_in` 同步）。

补料/重跑是 A2 的日常动作（每加一条判据就要重跑真实材料回归）
⇒ 不修则 **A2 的全部数字都失真**。

## 本文件锁死的判据

1. 同一 data dir 连跑两次 ⇒ **义务数不变**；
2. 留痕可查：跳过条数 + 清单指纹出现在**结构化返回体**里；
3. 指纹**只含结构化字段**（库 / 机构 / 条目编号 / 原文归一化空白）
   ⇒ **不打印真实文件名与路径**，可以安全写进日志；
4. **不得**用「清空数据目录」来回避幂等（那是掩盖，不是修复）；
5. 不同清单**照常**新增（不得把去重做成「一律跳过」）。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from cangjie_fos.services import (
    dd_v1_manifest_service as mf,
    dd_v1_requirement_service as rq,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tools" / "dd_team_channel.py"

ITEMS = [
    {"item_no": "1", "raw_text": "请提供2024年度审计报告"},
    {"item_no": "2", "raw_text": "请提供营业执照"},
]


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(tmp_path / "无策略.json"))
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path):
    return tmp_path / "_plane" / "manifest.sqlite"


def _register_lib(tmp_path, lib="lib1"):
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    (root / "样例材料2024.txt").write_text("审计报告\n本材料为合成夹具。\n", encoding="utf-8")
    mf.register_library(lib, str(root), authorized_by="A2", db_path=_db(tmp_path))
    return lib


def _obl_count(tmp_path, lib):
    return len(rq.list_obligations(lib, db_path=_db(tmp_path)))


# ═══════════════════════════════════════════════════════════════════════
# 1) 幂等：义务数不变
# ═══════════════════════════════════════════════════════════════════════


def test_ingest_same_checklist_twice_keeps_obligation_count(tmp_path):
    """同一份清单摄取两次 ⇒ 义务数**不变**。"""
    lib = _register_lib(tmp_path)
    r1 = rq.ingest_checklist(lib, [dict(i) for i in ITEMS], db_path=_db(tmp_path))
    n1 = _obl_count(tmp_path, lib)
    assert n1 == len(ITEMS), f"首轮应产出 {len(ITEMS)} 条义务：{n1}"

    r2 = rq.ingest_checklist(lib, [dict(i) for i in ITEMS], db_path=_db(tmp_path))
    n2 = _obl_count(tmp_path, lib)
    assert n2 == n1, f"重复摄取后义务数必须不变：{n1} → {n2}"
    assert r2["skipped_duplicates"] == len(ITEMS), \
        f"重复条目应全部被跳过并留痕：{r2}"
    assert r2["obligations"] == 0, f"重复摄取不得新增义务：{r2}"


def test_consecutive_whitespace_is_collapsed_and_deduped(tmp_path):
    """**连续空白**被折叠 ⇒ 视为同一条（指纹对空白做了归一化）。

    口径说明（保守）：指纹把**连续空白折叠成一个空格**，但**不整体删除空白**
    ⇒ 「A  B」与「A B」相同，而「AB」与「A B」**不同**。
    这样既不因排版差异重复建义务，也不会把「AB」与「A B」误判成同一条。
    """
    lib = _register_lib(tmp_path)
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供  2024年度审计报告"}],
                        db_path=_db(tmp_path))
    n1 = _obl_count(tmp_path, lib)
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供 2024年度审计报告"}],
                        db_path=_db(tmp_path))
    assert _obl_count(tmp_path, lib) == n1, "连续空白差异不得产生重复义务"


def test_different_checklist_still_ingests_new_items(tmp_path):
    """不同清单 ⇒ **照常新增**（去重不得做成「一律跳过」）。"""
    lib = _register_lib(tmp_path)
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2024年度审计报告"}],
                        db_path=_db(tmp_path))
    n1 = _obl_count(tmp_path, lib)
    r = rq.ingest_checklist(lib, [{"item_no": "2", "raw_text": "请提供营业执照"}],
                            db_path=_db(tmp_path))
    n2 = _obl_count(tmp_path, lib)
    assert n2 == n1 + 1, f"新条目必须入库：{n1} → {n2}"
    assert r["skipped_duplicates"] == 0, f"新条目不得被误判为重复：{r}"


def test_empty_raw_text_is_dropped_not_duplicated(tmp_path):
    """原文为空 ⇒ 拒绝入库（不得凭空生成要求），重复调用也不产生义务。"""
    lib = _register_lib(tmp_path)
    r = rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "   "}],
                        db_path=_db(tmp_path))
    assert r["obligations"] == 0
    assert r["dropped"], "空原文必须留痕"
    assert _obl_count(tmp_path, lib) == 0


# ═══════════════════════════════════════════════════════════════════════
# 2) 留痕可查 + 指纹不含真实文件名
# ═══════════════════════════════════════════════════════════════════════


def test_ingest_returns_traceable_fingerprint_fields(tmp_path):
    """结构化返回体必须带：跳过条数 + 清单指纹 + 跳过指纹列表。"""
    lib = _register_lib(tmp_path)
    rq.ingest_checklist(lib, [dict(i) for i in ITEMS], db_path=_db(tmp_path))
    r = rq.ingest_checklist(lib, [dict(i) for i in ITEMS], db_path=_db(tmp_path))
    for key in ("skipped_duplicates", "checklist_fingerprint", "skipped_fingerprints"):
        assert key in r, f"返回体缺少留痕字段 {key}：{r}"
    assert re.fullmatch(r"[0-9a-f]{16}", r["checklist_fingerprint"]), \
        f"清单指纹应是 16 位十六进制摘要：{r['checklist_fingerprint']}"
    assert r["skipped_fingerprints"], "跳过指纹列表不得为空"
    for fp in r["skipped_fingerprints"]:
        assert re.fullmatch(r"[0-9a-f]{16}", fp), f"指纹格式不对：{fp}"


def test_fingerprint_contains_no_filename_or_raw_text(tmp_path):
    """指纹**只含结构化字段**：不得出现文件名、路径或机构原文。"""
    lib = _register_lib(tmp_path)
    secret_name = "某客户敏感名称-2024审计报告.pdf"
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    (root / secret_name).write_text("审计报告\n内容。\n", encoding="utf-8")
    r = rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2024年度审计报告"}],
                        db_path=_db(tmp_path))
    r2 = rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2024年度审计报告"}],
                         db_path=_db(tmp_path))
    blob = json_dump(r) + json_dump(r2)
    assert secret_name not in blob, "留痕里不得出现真实文件名"
    assert "请提供2024年度审计报告" not in blob, "留痕里不得出现机构原文"
    assert str(root) not in blob, "留痕里不得出现材料库路径"


def json_dump(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════
# 3) 不得用「清库」回避幂等
# ═══════════════════════════════════════════════════════════════════════


def test_idempotency_is_not_achieved_by_clearing_the_database(tmp_path):
    """**红线**：不得靠清空数据库来「实现」幂等。

    判据：第二次摄取**不得**重建数据库文件（inode 与清单条目都不该被抹掉）。
    """
    lib = _register_lib(tmp_path)
    rq.ingest_checklist(lib, [dict(i) for i in ITEMS], db_path=_db(tmp_path))
    db = _db(tmp_path)
    assert db.exists()
    stat_before = db.stat()
    conn = mf._connect(_db(tmp_path))
    before_rows = conn.execute(
        "SELECT COUNT(*) FROM dd_v1_checklist_items WHERE library_id=?",
        (lib,)).fetchone()[0]
    # 注意：**不要** conn.close() —— mf._connect() 返回的是进程内共享连接，
    # 关掉它会让后续调用报「Cannot operate on a closed database」。
    mf.close_all()

    rq.ingest_checklist(lib, [dict(i) for i in ITEMS], db_path=_db(tmp_path))
    stat_after = db.stat()
    assert (stat_after.st_ino == stat_before.st_ino), \
        "数据库文件被重建了 ⇒ 幂等是靠清库实现的（红线）"
    conn = mf._connect(_db(tmp_path))
    after_rows = conn.execute(
        "SELECT COUNT(*) FROM dd_v1_checklist_items WHERE library_id=?",
        (lib,)).fetchone()[0]
    assert after_rows == before_rows, f"清单条目被清掉了：{before_rows} → {after_rows}"


# ═══════════════════════════════════════════════════════════════════════
# 4) 入口 A 端到端：同一 data dir 连跑两次
# ═══════════════════════════════════════════════════════════════════════


def _run_entry_a(tmp_path, data_dir: Path, checklist: Path, lib="lib1"):
    env = {
        "CANGJIE_DD_V1_DATA_DIR": str(data_dir),
        "CANGJIE_DD_V1_POLICY": str(tmp_path / "无策略.json"),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
    }
    cmd = [sys.executable, str(TOOL), "run",
           "--library", lib, "--root", str(tmp_path / "materials"),
           "--checklist", str(checklist),
           "--institution", "某机构", "--by", "A2",
           "--no-bridge"]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)
    return p


def test_entry_a_run_twice_same_data_dir_keeps_obligation_count(tmp_path):
    """**入口 A 端到端**：同一 data dir 连跑两次 ⇒ 义务数**不变**。

    这是 A2-12 的核心判据：补料/重跑是日常动作，数字不能翻倍。
    """
    if not TOOL.exists():
        pytest.skip(f"找不到入口脚本：{TOOL}")
    _register_lib(tmp_path)
    checklist = tmp_path / "清单.tsv"
    checklist.write_text("1\t请提供2024年度审计报告\n2\t请提供营业执照\n", encoding="utf-8")

    data_dir = tmp_path / "_plane"
    data_dir.mkdir(exist_ok=True)

    p1 = _run_entry_a(tmp_path, data_dir, checklist)
    assert p1.returncode == 0, f"首次运行失败：{p1.stdout[-800:]} {p1.stderr[-400:]}"
    n1 = _obl_count(tmp_path, "lib1")
    assert n1 > 0, "首次运行应产出义务"

    p2 = _run_entry_a(tmp_path, data_dir, checklist)
    assert p2.returncode == 0, f"第二次运行失败：{p2.stdout[-800:]} {p2.stderr[-400:]}"
    n2 = _obl_count(tmp_path, "lib1")
    assert n2 == n1, f"入口 A 连跑两次义务数必须不变：{n1} → {n2}"
    assert re.search(r"跳过", p2.stdout), \
        f"第二次运行应有跳过留痕（不得静默）：{p2.stdout[-600:]}"
