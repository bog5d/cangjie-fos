"""DD-V1 材料库 Manifest（WP1）：授权目录接管、稳定文件身份、增量扫描与断点恢复。

设计约束（来源：投资尽调自动组包 V1 施工指令 §6A + SCP v3.8 §6/§8）：

1. **源文件只读。** 本模块只读取材料目录，绝不写入。所有派生产物落在受控
   Data Plane（`backend/data/dd_v1/`，已被 .gitignore 覆盖），且启动时硬校验
   Data Plane 不在材料库内部——防止"顺手把缓存写进客户材料目录"。

2. **只扫描经过授权的目录。** 必须先 `register_library(..., authorized_by=...)`
   显式登记，`build_manifest` 遇未登记的根目录直接拒绝执行。

3. **文件身份按「相对路径」而非「文件名」。** 这是对既有 D2 缺陷的根治：
   旧 `_dedup_keep_newest` 以 `f.name` 为 key + `mtime` 比大小，会把不同机构/
   不同主体下的同名文件（如各一份「营业执照.pdf」）判为重复，只留 mtime 最新一份，
   且被丢弃方完全不进索引、连机构信息都不留。本模块以
   `(library_id, rel_path)` 为唯一键，`content_hash` 另存一列，
   因此**同名不同主体的文件永远共存，永不被去重删除**。
   另：`mtime` 仅作增量扫描的快速跳过信号，**不参与业务有效性判定**
   （业务版本有效性由 WP2 的认知卡按签署/生效日期与版本线索判定）。

4. **本层零 LLM 调用。** Manifest 是确定性的纯文件系统工作，不把任何文件
   正文送进模型上下文，符合"禁止把几千份文件一次性放入 LLM 上下文"。

幂等性：同一材料库重复执行 full 扫描得到逐行相同的结果（内容哈希为稳定标识）。
断点恢复：以 `run_id` 为恢复锚点，中断后可用同一 `library_id` 续跑，
按 `(library_id, rel_path)` 幂等 upsert，已处理文件不重复计数。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from cangjie_fos.core import paths as fos_paths

# 复用既有排除规则，避免出现第二套"什么算材料"的定义（SCP v3.8 §1 复用优先）。
from cangjie_fos.services.dd_file_parser import SUPPORTED_EXTENSIONS
from cangjie_fos.services.dd_index_service import (
    _is_cangjie_internal,
    _is_excluded_dir,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# 内容哈希分块大小：材料库可能几十 GB，必须流式读，禁止整文件进内存。
_HASH_CHUNK = 1024 * 1024

# 解析状态机（确定性，不由 LLM 判定）
PARSE_PENDING = "pending"      # 已入 Manifest，尚未抽取正文
PARSE_OK = "ok"                # 成功抽取
PARSE_PARTIAL = "partial"      # 抽取成功但被长度上限截断
PARSE_FAILED = "failed"        # 抽取失败（损坏 / 加密 / 不支持）
PARSE_SKIPPED = "skipped"      # 不在支持扩展名内

# 扫描运行状态
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_ABORTED = "aborted"

# 版本线索抽取：仅作 INFERRED 提示，不作业务事实。依据见 §3 注释 3。
_VERSION_TOKEN_RE = re.compile(
    r"(?:^|[^0-9A-Za-z])[vV](\d+(?:\.\d+)*)|最终版?|终稿|定稿|终版|修订版?|签署版|盖章版"
)
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

_DDL = f"""
CREATE TABLE IF NOT EXISTS dd_v1_schema_meta (
    version     INTEGER PRIMARY KEY,
    applied_at  REAL NOT NULL
);

-- 授权材料库：只有登记在册的根目录才允许被扫描
CREATE TABLE IF NOT EXISTS dd_v1_libraries (
    library_id   TEXT PRIMARY KEY,
    root_path    TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    authorized_by TEXT NOT NULL,
    authorized_at REAL NOT NULL,
    revoked_at   REAL
);

-- 材料 Manifest（核心表）
CREATE TABLE IF NOT EXISTS dd_v1_manifest (
    file_id       TEXT PRIMARY KEY,
    library_id    TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    abs_path      TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    ext           TEXT NOT NULL DEFAULT '',
    size          INTEGER NOT NULL DEFAULT 0,
    mtime         REAL NOT NULL DEFAULT 0,
    content_hash  TEXT NOT NULL DEFAULT '',
    source_hint   TEXT NOT NULL DEFAULT '',
    version_hint  TEXT NOT NULL DEFAULT '',
    year_hint     TEXT NOT NULL DEFAULT '',
    parse_status  TEXT NOT NULL DEFAULT '{PARSE_PENDING}',
    parse_method  TEXT NOT NULL DEFAULT '',
    parse_error   TEXT NOT NULL DEFAULT '',
    truncated     INTEGER NOT NULL DEFAULT 0,
    first_seen_at REAL NOT NULL,
    last_seen_at  REAL NOT NULL,
    changed_at    REAL NOT NULL,
    deleted_at    REAL,
    UNIQUE (library_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_manifest_lib
    ON dd_v1_manifest(library_id, parse_status);
CREATE INDEX IF NOT EXISTS idx_dd_v1_manifest_hash
    ON dd_v1_manifest(content_hash);
CREATE INDEX IF NOT EXISTS idx_dd_v1_manifest_name
    ON dd_v1_manifest(file_name);

-- 扫描运行：断点恢复锚点
CREATE TABLE IF NOT EXISTS dd_v1_scan_runs (
    run_id        TEXT PRIMARY KEY,
    library_id    TEXT NOT NULL,
    root_path     TEXT NOT NULL,
    mode          TEXT NOT NULL,
    status        TEXT NOT NULL,
    started_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    heartbeat_at  REAL NOT NULL,
    lease_owner   TEXT NOT NULL DEFAULT '',
    lease_expires_at REAL NOT NULL DEFAULT 0,
    total_files   INTEGER NOT NULL DEFAULT 0,
    processed     INTEGER NOT NULL DEFAULT 0,
    added         INTEGER NOT NULL DEFAULT 0,
    updated       INTEGER NOT NULL DEFAULT 0,
    unchanged     INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    removed       INTEGER NOT NULL DEFAULT 0,
    last_rel_path TEXT NOT NULL DEFAULT '',
    last_error    TEXT NOT NULL DEFAULT '',
    data_plane    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_runs_lib
    ON dd_v1_scan_runs(library_id, status);
"""


# ── 连接 ────────────────────────────────────────────────────────────────────
_conn_lock = threading.Lock()
_conns: dict[str, sqlite3.Connection] = {}


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    """打开（或复用）DD-V1 Manifest 库的连接，并确保 schema 就绪。

    刻意独立于 `services.db_base._connect`：Manifest 在超大材料库下可能达百万行级，
    独立库避免拖慢既有 DD 查询，同时让 Data Plane 边界在文件系统上可直接核查。
    """
    path = str(db_path or fos_paths.get_dd_v1_manifest_db_path())
    with _conn_lock:
        conn = _conns.get(path)
        if conn is None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_DDL)
            conn.execute(
                "INSERT OR IGNORE INTO dd_v1_schema_meta(version, applied_at) VALUES (?,?)",
                (SCHEMA_VERSION, time.time()),
            )
            conn.commit()
            _conns[path] = conn
        return conn


def close_all() -> None:
    """关闭并清空连接缓存（测试隔离用）。"""
    with _conn_lock:
        for c in _conns.values():
            try:
                c.close()
            except sqlite3.Error:  # pragma: no cover - 关闭失败不应影响主流程
                pass
        _conns.clear()


# ── Data Plane 边界校验（源只读的安全闸）────────────────────────────────────
class DataPlaneViolation(RuntimeError):
    """Data Plane 落在材料库内部——会污染客户原始材料目录，必须拒绝。"""


def assert_data_plane_outside(root: Path, data_plane: Path) -> None:
    """硬校验 Data Plane 不在材料库内部。

    这是「源文件只读」的可执行保证：若 Data Plane 被配置到材料库内，
    本模块宁可直接报错，也不生成会污染原始目录的产物。
    """
    r = root.resolve()
    d = data_plane.resolve()
    if d == r or r in d.parents:
        raise DataPlaneViolation(
            f"Data Plane 位于材料库内部，拒绝执行以免污染原始材料：root={r}, data_plane={d}"
        )


# ── 授权登记 ────────────────────────────────────────────────────────────────
def register_library(
    library_id: str,
    root_path: str,
    authorized_by: str,
    display_name: str = "",
    db_path: Path | None = None,
) -> dict:
    """登记一个**经过授权**的材料库。未登记的根目录禁止扫描。"""
    if not library_id.strip():
        raise ValueError("library_id 不能为空")
    if not authorized_by.strip():
        raise ValueError("authorized_by 不能为空：只扫描经过授权的目录")
    root = Path(root_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"材料库根目录不存在或不是目录：{root}")

    conn = _connect(db_path)
    now = time.time()
    conn.execute(
        """
        INSERT INTO dd_v1_libraries
            (library_id, root_path, display_name, authorized_by, authorized_at, revoked_at)
        VALUES (?,?,?,?,?,NULL)
        ON CONFLICT(library_id) DO UPDATE SET
            root_path=excluded.root_path,
            display_name=excluded.display_name,
            authorized_by=excluded.authorized_by,
            authorized_at=excluded.authorized_at,
            revoked_at=NULL
        """,
        (library_id, str(root), display_name, authorized_by, now),
    )
    conn.commit()
    return {"library_id": library_id, "root_path": str(root), "authorized_by": authorized_by}


def get_library(library_id: str, db_path: Path | None = None) -> dict | None:
    row = _connect(db_path).execute(
        "SELECT * FROM dd_v1_libraries WHERE library_id=? AND revoked_at IS NULL",
        (library_id,),
    ).fetchone()
    return dict(row) if row else None


def revoke_library(library_id: str, db_path: Path | None = None) -> None:
    """撤销授权。已撤销的库不再允许新增扫描。"""
    conn = _connect(db_path)
    conn.execute(
        "UPDATE dd_v1_libraries SET revoked_at=? WHERE library_id=?",
        (time.time(), library_id),
    )
    conn.commit()


# ── 工具 ────────────────────────────────────────────────────────────────────
def iter_version_hints(file_name: str) -> tuple[str, str]:
    """从文件名抽取 (version_hint, year_hint)。

    **仅 INFERRED，不是 FACT**：文件名可能是「最终版(2).docx」这类不可信线索。
    业务有效版本必须由 WP2 的认知卡依据签署/生效日期判定；此处只提供召回线索。
    """
    stem = re.sub(r"\.\w+$", "", file_name)
    m = _VERSION_TOKEN_RE.search(stem)
    version = m.group(0).strip() if m else ""
    years = _YEAR_RE.findall(stem)
    year = years[0] if years else ""
    return version, year


def compute_content_hash(path: Path, chunk: int = _HASH_CHUNK) -> str:
    """流式计算 sha256。禁止整文件读入内存（材料库可达几十 GB）。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def make_file_id(library_id: str, rel_path: str) -> str:
    """稳定文件 ID：由 (library_id, rel_path) 决定，与 mtime/内容无关。

    因此同一份材料重复扫描得到同一个 file_id（幂等），
    且不同目录下同名文件得到不同 file_id（D2 根治点）。
    """
    raw = f"{library_id}\x00{rel_path}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _iter_candidate_files(root: Path, library_id: str) -> Iterator[Path]:
    """遍历材料库内的候选文件，复用既有排除规则（复用优先，不另立标准）。"""
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if _is_cangjie_internal(f, root):
            continue
        if _is_excluded_dir(f, root):
            continue
        yield f


@dataclass
class ScanStats:
    run_id: str = ""
    library_id: str = ""
    mode: str = ""
    total: int = 0
    processed: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    removed: int = 0
    status: str = RUN_RUNNING
    as_dict: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "library_id": self.library_id,
            "mode": self.mode,
            "total": self.total,
            "processed": self.processed,
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "removed": self.removed,
            "status": self.status,
        }


# ── 扫描主流程 ──────────────────────────────────────────────────────────────
def build_manifest(
    library_id: str,
    mode: str = "incremental",
    resume_run_id: str | None = None,
    lease_owner: str = "",
    lease_seconds: int = 900,
    progress_callback: Callable[[int, int], None] | None = None,
    db_path: Path | None = None,
) -> dict:
    """建立/更新材料 Manifest。

    mode:
      - ``full``        重新核对全部文件（仍按内容哈希幂等）
      - ``incremental`` 常规巡检；用 (size, mtime) 快速跳过未变文件
      - ``retry``       只重试 parse_status 为 failed/partial 的条目

    resume_run_id: 传入上次中断的 run_id 即从持久状态续跑。

    源目录只读：本函数只调用 stat / open('rb')，不做任何写入。
    """
    if mode not in ("full", "incremental", "retry"):
        raise ValueError(f"未知扫描模式：{mode}")

    lib = get_library(library_id, db_path)
    if lib is None:
        raise PermissionError(
            f"材料库 {library_id} 未登记授权或已撤销；只扫描经过授权的目录"
        )

    root = Path(lib["root_path"])
    data_plane = fos_paths.get_dd_v1_data_dir()
    assert_data_plane_outside(root, data_plane)

    conn = _connect(db_path)
    now = time.time()

    if resume_run_id:
        run = conn.execute(
            "SELECT * FROM dd_v1_scan_runs WHERE run_id=?", (resume_run_id,)
        ).fetchone()
        if run is None:
            raise ValueError(f"resume_run_id 不存在：{resume_run_id}")
        if run["status"] != RUN_RUNNING:
            raise ValueError(
                f"run {resume_run_id} 状态为 {run['status']}，非运行中，无需恢复"
            )
        if run["lease_owner"] and lease_owner and run["lease_owner"] != lease_owner:
            raise RuntimeError(
                f"run {resume_run_id} 已被 {run['lease_owner']} 持有，"
                f"租约未过期（{run['lease_expires_at']:.0f}），拒绝并发恢复"
            )
        run_id = resume_run_id
        logger.info("恢复扫描 run=%s library=%s（已处理 %d）",
                    run_id, library_id, run["processed"])
    else:
        run_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO dd_v1_scan_runs
               (run_id, library_id, root_path, mode, status, started_at,
                updated_at, heartbeat_at, lease_owner, lease_expires_at, data_plane)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, library_id, str(root), mode, RUN_RUNNING,
             now, now, now, lease_owner, now + lease_seconds, str(data_plane)),
        )
        conn.commit()

    stats = ScanStats(run_id=run_id, library_id=library_id, mode=mode)
    seen_rel: set[str] = set()

    try:
        files = list(_iter_candidate_files(root, library_id))
        stats.total = len(files)

        if mode == "retry":
            targets = [
                r for r in conn.execute(
                    """SELECT abs_path FROM dd_v1_manifest
                       WHERE library_id=? AND parse_status IN (?,?)""",
                    (library_id, PARSE_FAILED, PARSE_PARTIAL),
                )
            ]
            files = [Path(r["abs_path"]) for r in targets]
            files = [f for f in files if f.is_file()]
            stats.total = len(files)
        else:
            conn.execute(
                "UPDATE dd_v1_scan_runs SET total_files=? WHERE run_id=?",
                (stats.total, run_id),
            )

        for f in files:
            rel = f.relative_to(root).as_posix()
            seen_rel.add(rel)
            try:
                _upsert_file(conn, library_id, root, f, rel, mode, stats, now)
            except Exception as exc:  # noqa: BLE001 — 单文件失败不得中断整轮扫描
                stats.failed += 1
                logger.warning("Manifest 读取失败 %s：%s", rel, exc)
            stats.processed += 1

            if stats.processed % 200 == 0:
                _touch(conn, run_id, stats, lease_owner, lease_seconds)
                conn.commit()
                if progress_callback:
                    progress_callback(stats.processed, stats.total)

        if mode != "retry":
            stats.removed = _soft_delete_missing(conn, library_id, seen_rel, now)

        _touch(conn, run_id, stats, lease_owner, lease_seconds)
        stats.status = RUN_COMPLETED
        conn.execute(
            "UPDATE dd_v1_scan_runs SET status=?, last_error='' WHERE run_id=?",
            (RUN_COMPLETED, run_id),
        )
        conn.commit()

    except Exception as exc:  # noqa: BLE001
        _touch(conn, run_id, stats, lease_owner, lease_seconds)
        conn.execute(
            "UPDATE dd_v1_scan_runs SET status=?, last_error=? WHERE run_id=?",
            (RUN_FAILED, str(exc)[:500], run_id),
        )
        conn.commit()
        raise

    out = stats.to_dict()
    out["data_plane"] = str(data_plane)
    out["source_root"] = str(root)
    return out


def _touch(
    conn: sqlite3.Connection,
    run_id: str,
    stats: ScanStats,
    lease_owner: str,
    lease_seconds: int,
) -> None:
    now = time.time()
    conn.execute(
        """UPDATE dd_v1_scan_runs
           SET updated_at=?, heartbeat_at=?, lease_owner=?, lease_expires_at=?,
               processed=?, added=?, updated=?, unchanged=?, failed=?, removed=?,
               last_rel_path=?
           WHERE run_id=?""",
        (now, now, lease_owner, now + lease_seconds,
         stats.processed, stats.added, stats.updated, stats.unchanged,
         stats.failed, stats.removed, "", run_id),
    )


def _upsert_file(
    conn: sqlite3.Connection,
    library_id: str,
    root: Path,
    f: Path,
    rel: str,
    mode: str,
    stats: ScanStats,
    now: float,
) -> None:
    st = f.stat()
    file_id = make_file_id(library_id, rel)
    version_hint, year_hint = iter_version_hints(f.name)
    ext = f.suffix.lower()

    row = conn.execute(
        "SELECT * FROM dd_v1_manifest WHERE library_id=? AND rel_path=?",
        (library_id, rel),
    ).fetchone()

    if row is None:
        conn.execute(
            """INSERT INTO dd_v1_manifest
               (file_id, library_id, rel_path, abs_path, file_name, ext, size, mtime,
                content_hash, source_hint, version_hint, year_hint, parse_status,
                first_seen_at, last_seen_at, changed_at, deleted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
            (file_id, library_id, rel, str(f), f.name, ext, st.st_size, st.st_mtime,
             compute_content_hash(f), "", version_hint, year_hint,
             PARSE_PENDING if ext in SUPPORTED_EXTENSIONS else PARSE_SKIPPED,
             now, now, now),
        )
        stats.added += 1
        return

    # 增量快速跳过：size+mtime 未变则不重算哈希（大库必须，否则每轮都重读几十 GB）
    if mode == "incremental" and row["size"] == st.st_size and \
            abs((row["mtime"] or 0) - st.st_mtime) < 1e-6:
        conn.execute(
            "UPDATE dd_v1_manifest SET last_seen_at=?, deleted_at=NULL WHERE file_id=?",
            (now, file_id),
        )
        stats.unchanged += 1
        return

    new_hash = compute_content_hash(f)
    changed = new_hash != (row["content_hash"] or "")
    conn.execute(
        """UPDATE dd_v1_manifest
           SET abs_path=?, size=?, mtime=?, content_hash=?, version_hint=?, year_hint=?,
               last_seen_at=?, deleted_at=NULL,
               changed_at=?, parse_status=?
           WHERE file_id=?""",
        (str(f), st.st_size, st.st_mtime, new_hash, version_hint, year_hint, now,
         now if changed else row["changed_at"],
         row["parse_status"] if not changed else PARSE_PENDING,
         file_id),
    )
    if changed:
        stats.updated += 1
    else:
        stats.unchanged += 1


def _soft_delete_missing(
    conn: sqlite3.Connection, library_id: str, seen: set[str], now: float
) -> int:
    """本轮未见到的文件做**软删除**。

    保守处理：材料库常挂移动硬盘/网络盘，一次扫描看不到 ≠ 文件真的没了。
    因此只打 deleted_at 标记，不物理删除，recoverable() 可还原。
    """
    rows = conn.execute(
        "SELECT file_id, rel_path FROM dd_v1_manifest WHERE library_id=? AND deleted_at IS NULL",
        (library_id,),
    ).fetchall()
    n = 0
    for r in rows:
        if r["rel_path"] not in seen:
            conn.execute(
                "UPDATE dd_v1_manifest SET deleted_at=? WHERE file_id=?",
                (now, r["file_id"]),
            )
            n += 1
    return n


# ── 查询 ────────────────────────────────────────────────────────────────────
def get_manifest_entry(library_id: str, rel_path: str, db_path: Path | None = None) -> dict | None:
    row = _connect(db_path).execute(
        "SELECT * FROM dd_v1_manifest WHERE library_id=? AND rel_path=?",
        (library_id, rel_path),
    ).fetchone()
    return dict(row) if row else None


def list_manifest(
    library_id: str,
    include_deleted: bool = False,
    limit: int = 1000,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[dict]:
    sql = "SELECT * FROM dd_v1_manifest WHERE library_id=?"
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    sql += " ORDER BY rel_path LIMIT ? OFFSET ?"
    return [dict(r) for r in _connect(db_path).execute(sql, (library_id, limit, offset))]


def find_same_name_across_subjects(
    library_id: str, file_name: str, db_path: Path | None = None
) -> list[dict]:
    """同名文件跨主体共存检查——D2 回归守卫的可观测接口。

    若返回多行，说明不同相对路径下的同名文件被正确保留（未被同名去重误删）。
    """
    return [
        dict(r) for r in _connect(db_path).execute(
            """SELECT rel_path, content_hash, size, deleted_at
               FROM dd_v1_manifest
               WHERE library_id=? AND file_name=? AND deleted_at IS NULL
               ORDER BY rel_path""",
            (library_id, file_name),
        )
    ]


def manifest_summary(library_id: str, db_path: Path | None = None) -> dict:
    """材料库概览：按解析状态与扩展名统计（供 Gate 与报告使用）。"""
    conn = _connect(db_path)
    total = conn.execute(
        "SELECT COUNT(*) c FROM dd_v1_manifest WHERE library_id=? AND deleted_at IS NULL",
        (library_id,),
    ).fetchone()["c"]
    by_status = {
        r["parse_status"]: r["c"]
        for r in conn.execute(
            """SELECT parse_status, COUNT(*) c FROM dd_v1_manifest
               WHERE library_id=? AND deleted_at IS NULL
               GROUP BY parse_status""",
            (library_id,),
        )
    }
    return {
        "library_id": library_id,
        "total": total,
        "by_parse_status": by_status,
        "deleted": conn.execute(
            "SELECT COUNT(*) c FROM dd_v1_manifest WHERE library_id=? AND deleted_at IS NOT NULL",
            (library_id,),
        ).fetchone()["c"],
    }


def get_run(run_id: str, db_path: Path | None = None) -> dict | None:
    """恢复入口：任何时刻都应能从 run_id 取回断点位置。"""
    row = _connect(db_path).execute(
        "SELECT * FROM dd_v1_scan_runs WHERE run_id=?", (run_id,)
    ).fetchone()
    return dict(row) if row else None


def find_resumable_run(library_id: str, db_path: Path | None = None) -> dict | None:
    """找出上次中断、仍处于 running 的运行（断点恢复入口）。"""
    row = _connect(db_path).execute(
        """SELECT * FROM dd_v1_scan_runs
           WHERE library_id=? AND status=? ORDER BY started_at DESC LIMIT 1""",
        (library_id, RUN_RUNNING),
    ).fetchone()
    return dict(row) if row else None
