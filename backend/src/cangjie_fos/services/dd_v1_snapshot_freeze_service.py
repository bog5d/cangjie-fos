"""DD-V1 快照冻结服务（cangjie-fos#71 A4a · G-A4a-2 快照冻结）。

职责（全部确定性、零模型、零费用）：
1. ``freeze_snapshot``：把材料目录复制成一份**冻结快照**，逐件**现场**算 sha256
   （复用 ``dd_v1_agent_result_service.load_snapshot``，**不重写 sha 计算**），
   写 ``snapshot.json``（``snapshot_id`` / ``frozen_at`` / 逐件 sha256 清单），并把目录置只读。
2. ``verify_frozen``：逐件重算 sha256 与清单比对 ⇒ **任何改动都能检出**。
3. ``compare_snapshots``：被考侧 / 被评侧两份快照逐件 sha256 相等才算「同一份快照」。

不变量：
- ``snapshot_id`` 一律取 ``dd_v1_agent_result_service.snapshot_id()``（同一份口径，不另造）。
- 冻结后目录只读；只读是**兜底**，改动检出靠 sha256 比对（只读可被 root/owner 改掉）。
"""
from __future__ import annotations

FREEZE_IMPL_BEGIN = "GM:A4A:FREEZE:IMPL:BEGIN"

import json
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cangjie_fos.services import dd_v1_agent_result_service as ar

FREEZE_SCHEMA_VERSION = "dd_v1_snapshot_freeze.v1"
MANIFEST_NAME = "snapshot.json"


class FreezeError(RuntimeError):
    """冻结失败（fail closed）。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    """复用 agent_result_service 的现场 sha256（**不重写 sha 计算**）。"""
    return ar.sha256_file(Path(path))


def make_writable(root: Path) -> None:
    """把只读目录恢复成可写（重新冻结前必须做，否则覆盖不掉）。"""
    root = Path(root)
    if not root.exists():
        return
    for p in [root, *root.rglob("*")]:
        try:
            mode = p.stat().st_mode
            p.chmod(mode | stat.S_IWUSR | (stat.S_IXUSR if p.is_dir() else 0))
        except OSError:
            pass


def make_readonly(root: Path) -> None:
    """目录置只读（文件 0444 / 目录 0555）。

    只读是**兜底**（owner 仍可改）；改动检出靠 ``verify_frozen`` 的 sha256 比对。
    """
    root = Path(root)
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        try:
            p.chmod(0o555 if p.is_dir() else 0o444)
        except OSError:
            pass
    try:
        root.chmod(0o555)
    except OSError:
        pass


def freeze_snapshot(source_dir: Path, meta: list[dict[str, Any]], freeze_dir: Path, *,
                    read_only: bool = True) -> dict[str, Any]:
    """复制材料目录 → 冻结目录；逐件**现场**算 sha256；写 snapshot.json；置只读。

    - sha256 一律取 ``ar.load_snapshot()``（现场算，不信任元数据指纹）。
    - ``snapshot_id`` 一律取 ``ar.snapshot_id()``（同一份口径，不另造）。
    """
    src = Path(source_dir).resolve()
    dst = Path(freeze_dir).resolve()
    if not src.is_dir():
        raise FreezeError(f"FREEZE_SOURCE_NOT_DIR:{src}")
    if dst == src or src in dst.parents:
        raise FreezeError(f"FREEZE_DIR_INSIDE_SOURCE:{dst}")
    if dst in src.parents:
        raise FreezeError(f"FREEZE_DIR_CONTAINS_SOURCE:{dst}")
    make_writable(dst)
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, copy_function=shutil.copyfile)
    snap = ar.load_snapshot(dst, meta)
    manifest = {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "snapshot_id": ar.snapshot_id(snap),
        "frozen_at": _now_iso(),
        "source_dir": str(src),
        "meta_relative_path": "meta.json" if (src / "meta.json").is_file() else None,
        "files": [
            {"file_id": snap[fid].file_id, "relative_path": snap[fid].relative_path,
             "sha256": snap[fid].sha256}
            for fid in sorted(snap)
        ],
    }
    (dst / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    if read_only:
        make_readonly(dst)
    return manifest


def verify_frozen(snapshot_dir: Path, snapshot: Any) -> dict[str, Any]:
    """逐件重算 sha256 与清单比对 ⇒ **任何改动都能检出**。

    返回 ``{"ok", "changed": [...]}``；``changed`` 的 kind ∈ MISSING / MODIFIED / EXTRA。
    """
    if isinstance(snapshot, (str, Path)):
        snapshot = json.loads(Path(snapshot).read_text("utf-8"))
    root = Path(snapshot_dir).resolve()
    changed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in snapshot.get("files", []):
        fid, rel = str(entry.get("file_id")), str(entry.get("relative_path"))
        seen.add(rel)
        p = root / rel
        if not p.is_file():
            changed.append({"file_id": fid, "relative_path": rel, "kind": "MISSING",
                            "expected_sha256": entry.get("sha256"), "actual_sha256": None})
            continue
        got = _sha256_file(p)
        if got != entry.get("sha256"):
            changed.append({"file_id": fid, "relative_path": rel, "kind": "MODIFIED",
                            "expected_sha256": entry.get("sha256"), "actual_sha256": got})
    meta_rel = snapshot.get("meta_relative_path")
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == MANIFEST_NAME or rel == meta_rel:
            continue
        if rel not in seen:
            changed.append({"file_id": "", "relative_path": rel, "kind": "EXTRA",
                            "expected_sha256": None, "actual_sha256": _sha256_file(p)})
    return {"ok": not changed, "changed": changed,
            "snapshot_id": snapshot.get("snapshot_id"), "frozen_at": snapshot.get("frozen_at")}


def compare_snapshots(dir_a: Path, dir_b: Path, meta: list[dict[str, Any]]) -> dict[str, Any]:
    """被考侧 / 被评侧两份快照逐件 sha256 相等才算「同一份快照」。"""
    a = ar.load_snapshot(Path(dir_a), meta)
    b = ar.load_snapshot(Path(dir_b), meta)
    mismatched: list[dict[str, Any]] = []
    for fid in sorted(set(a) | set(b)):
        fa, fb = a.get(fid), b.get(fid)
        if fa is None or fb is None:
            mismatched.append({"file_id": fid, "kind": "MISSING_ON_ONE_SIDE"})
        elif fa.sha256 != fb.sha256:
            mismatched.append({"file_id": fid, "kind": "SHA_MISMATCH",
                               "a_sha256": fa.sha256, "b_sha256": fb.sha256})
    return {"ok": not mismatched, "mismatched": mismatched,
            "snapshot_id_a": ar.snapshot_id(a), "snapshot_id_b": ar.snapshot_id(b),
            "files": len(a)}
FREEZE_IMPL_END = "GM:A4A:FREEZE:IMPL:END"
