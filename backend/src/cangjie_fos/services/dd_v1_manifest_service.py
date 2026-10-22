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
import json
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

# 提交节奏（断点恢复的关键参数）。
#
# 首轮实现每 200 份才 commit 一次，实测暴露为真实缺陷：进程被 SIGKILL 时，
# 已处理但未提交的最多 200 份工作全部丢失，且 run 记录的 processed 仍为 0，
# 恢复入口拿不到真实进度——「恢复了状态，没恢复工作」。
#
# 现在改为「按份数或按时间，先到先触发」，默认更密：
#   - 库很小（<25 份）时在扫描结束时一次性提交；
#   - 库很大时最多每 25 份 / 每 2 秒落一次盘，崩溃最多损失一个窗口的进度。
# 两者均可由环境变量覆盖，便于按磁盘 IO 特性调优。
COMMIT_EVERY_FILES = int(os.getenv("CANGJIE_DD_V1_COMMIT_EVERY", "25") or "25")
COMMIT_EVERY_SECONDS = float(os.getenv("CANGJIE_DD_V1_COMMIT_SECONDS", "2") or "2")

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

-- 清单排除审计记录（W8 / A2-1）：每轮扫描一行，只存**计数与规则 id**，
-- 不存任何真实文件名 ⇒ 对外可审计，又不泄露客户材料名。
CREATE TABLE IF NOT EXISTS dd_v1_checklist_exclusions (
    run_id                          TEXT PRIMARY KEY,
    library_id                      TEXT NOT NULL,
    ruleset_version                 TEXT NOT NULL DEFAULT '',
    rules_source                    TEXT NOT NULL DEFAULT '',
    excluded_checklist_count        INTEGER NOT NULL DEFAULT 0,
    excluded_by_rule                TEXT NOT NULL DEFAULT '{{}}',
    rule_hit_but_not_excluded_count INTEGER NOT NULL DEFAULT 0,
    created_at                      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_chk_excl_lib
    ON dd_v1_checklist_exclusions(library_id, created_at);
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


# ── 清单类文件排除规则（W8 / A2-1）────────────────────────────────────────
#
# 缺陷背景：材料库里混着**机构下发的尽调清单**（清单 / 资料清单 / 尽职调查清单 /
# 授信资料清单 / 尽调清单 ...）。清单是**考题**，不是**证据**；一旦清单文件自己
# 进入材料库、又被匹配到对应义务，就会出现「清单自证」——用考题证明自己交了考题。
# 实测案例A的清单自证率 12%，目标 0%。
#
# 因此：**清单类文件一律不得进入材料库**（只做软删除，绝不动客户原始文件）。
#
# 判定规则集是**命名 + 结构化 + 可配置**的：
#   - 内置规则写在代码里（``_BUILTIN_CHECKLIST_RULES``），调整口径不必改代码；
#   - 运行时用环境变量 ``CANGJIE_DD_V1_CHECKLIST_RULES`` 指向一个 JSON 规则文件即可覆盖；
#   - 规则文件损坏/读不出来 ⇒ **回退内置规则**并记 ``load_error``：
#     绝不因为配置坏了就把清单放回材料库（排除行为 fail-closed）。
#
# 规则字段（每条规则都带 id 与 priority；priority 小的先判，命中即止 ⇒ 结果确定）：
#
#   rule_id      规则标识，出现在 ``excluded_by_rule`` 里（对外只暴露 id 与计数）
#   priority     判定顺序（小者先判）；同 priority 按 rule_id 字典序兜底
#   kind         判定方式：
#                 filename_keyword —— 文件名主干含 patterns 之一
#                 path_segment     —— 任一**目录名**等于 patterns 之一（子目录里的清单同样命中）
#                 extension        —— 扩展名命中 extensions（可用 patterns 收窄文件名）
#                 content_sniff    —— 正文前 sniff_bytes 字节命中 patterns / require_all
#   patterns     命中词（kind=content_sniff 时按正则解释）
#   require_all  全部必须命中（kind=content_sniff 时为正则 AND 组；其余 kind 为文件名 AND 组）
#   extensions   扩展名集合；kind=extension 时是命中集合，其余 kind 是收窄条件
#   vetoes       出现即**不**命中（避免把「资产清单」这类真证据误杀）
#   sniff_bytes  正文嗅探字节数上限（默认 64KB）
#   enabled      是否启用
#   description  人读说明（审计用）
#
# 已知边界（留给司仓定策，代码不擅自扩大口径）：
#   - content_sniff 只对**纯文本类扩展名**有效；.xlsx/.pdf 是压缩/二进制容器，
#     正文嗅探读不到表头，只能靠文件名/目录名规则兜。
#   - 「清单」二字在中文材料里既可能是考题（尽调清单）也可能是证据（资产清单），
#     内置口径按「默认考题 + 已知证据合成词放行」处理，白名单需人工维护。

CHECKLIST_RULES_ENV = "CANGJIE_DD_V1_CHECKLIST_RULES"
DEFAULT_CHECKLIST_RULESET_VERSION = "dd-v1-checklist-rules-v1"
_CHECKLIST_SNIFF_BYTES = 64 * 1024
_RULE_KINDS = ("filename_keyword", "path_segment", "extension", "content_sniff")

# 泛化「清单」时需要放行的**真证据**合成词（veto）：这些是材料本身，不是考题。
_CHECKLIST_NAME_VETOES = (
    "资产清单", "债权清单", "借款清单", "固定资产清单", "存货清单",
    "费用清单", "工资清单", "薪酬清单", "抵债资产清单",
)

# 内置规则集（结构化、可审计、可被 JSON 文件整体覆盖）。
_BUILTIN_CHECKLIST_RULES: tuple[dict, ...] = (
    {
        "rule_id": "CL-001-path-segment",
        "priority": 10,
        "kind": "path_segment",
        "patterns": [
            "清单", "尽调清单", "尽调资料清单", "尽职调查清单", "尽调材料清单",
            "资料清单", "授信资料清单", "检查清单", "核查清单",
            "checklist", "dd_checklist", "due_diligence_checklist",
        ],
        "description": "文件所在任一目录名就是清单目录 ⇒ 该目录整体是考题，不进材料库",
    },
    {
        "rule_id": "CL-002-exam-phrase-in-filename",
        "priority": 20,
        "kind": "filename_keyword",
        "patterns": [
            "尽职调查清单", "尽调清单", "尽职调查资料清单", "尽调资料清单",
            "尽职调查材料清单", "尽调材料清单", "尽调材料目录", "尽调资料目录",
            "授信资料清单", "资料清单", "检查清单", "核查清单",
            "checklist", "dd checklist", "due diligence checklist",
        ],
        "description": "文件名直接是尽调考题（强特征，无放行词）",
    },
    {
        "rule_id": "CL-003-generic-qingdan-in-filename",
        "priority": 30,
        "kind": "filename_keyword",
        "patterns": ["清单"],
        "vetoes": list(_CHECKLIST_NAME_VETOES),
        "description": "文件名只说「清单」：默认按考题处理，已知属于真证据的合成词放行",
    },
    {
        "rule_id": "CL-004-checklist-table-header",
        "priority": 40,
        "kind": "content_sniff",
        "extensions": [".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".html", ".htm"],
        "require_all": [
            r"(需提供|要求提供|是否提供|是否齐备|是否具备|是否提交|提供情况|是否齐全|是否到位)",
            r"(序号|编号|清单项|材料名称|资料名称|项目名称|材料要求|item\s*no)",
        ],
        "description": "正文表头同时出现「供给状态列」与「表头列」⇒ 典型清单表（只嗅探文本类扩展名）",
    },
    {
        "rule_id": "CL-005-tabular-checklist-file",
        "priority": 50,
        "kind": "extension",
        "extensions": [".tsv", ".csv"],
        "patterns": ["清单", "checklist"],
        "vetoes": list(_CHECKLIST_NAME_VETOES),
        "description": "表格类清单文件（机构下发清单常为 TSV/CSV）：扩展名 + 名称双特征",
    },
)


@dataclass(frozen=True)
class ChecklistRule:
    """一条清单排除规则（结构化、可序列化、可被 JSON 文件覆盖）。"""

    rule_id: str
    priority: int
    kind: str
    patterns: tuple[str, ...] = ()
    require_all: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    vetoes: tuple[str, ...] = ()
    sniff_bytes: int = _CHECKLIST_SNIFF_BYTES
    enabled: bool = True
    description: str = ""


@dataclass(frozen=True)
class ChecklistRules:
    """一份可用的规则集（内置或来自 JSON 文件）。"""

    ruleset_version: str
    source: str            # builtin / config / env
    path: str
    rules: tuple[ChecklistRule, ...]
    load_error: str = ""

    def to_dict(self) -> dict:
        """对外摘要：只给版本、来源与规则 id（不含任何文件名）。"""
        return {
            "ruleset_version": self.ruleset_version,
            "source": self.source,
            "path": self.path,
            "load_error": self.load_error,
            "rule_ids": [r.rule_id for r in self.rules],
        }


def _checklist_rules_config_path() -> Path | None:
    """规则文件路径：环境变量优先，其次仓库默认 config（存在才用）。"""
    env = (os.getenv(CHECKLIST_RULES_ENV) or "").strip()
    if env:
        return Path(env)
    default = Path(__file__).resolve().parents[3] / "config" / "dd_v1_checklist_rules.json"
    return default if default.exists() else None


def _rule_from_dict(raw: object) -> ChecklistRule | None:
    """把一条 JSON 规则转成 ``ChecklistRule``；不合法则整条丢弃（不影响其它规则）。"""
    if not isinstance(raw, dict):
        return None
    rule_id = str(raw.get("rule_id") or "").strip()
    kind = str(raw.get("kind") or "").strip().lower()
    if not rule_id or kind not in _RULE_KINDS:
        return None

    def _strlist(key: str) -> tuple[str, ...]:
        val = raw.get(key) or []
        if isinstance(val, str):
            val = [val]
        if not isinstance(val, list):
            return ()
        return tuple(str(x).strip() for x in val if str(x).strip())

    try:
        priority = int(raw.get("priority", 100))
    except (TypeError, ValueError):
        priority = 100
    try:
        sniff_bytes = int(raw.get("sniff_bytes") or _CHECKLIST_SNIFF_BYTES)
    except (TypeError, ValueError):
        sniff_bytes = _CHECKLIST_SNIFF_BYTES

    exts = tuple(
        (e if e.startswith(".") else "." + e).lower() for e in _strlist("extensions")
    )
    rule = ChecklistRule(
        rule_id=rule_id,
        priority=priority,
        kind=kind,
        patterns=_strlist("patterns"),
        require_all=_strlist("require_all"),
        extensions=exts,
        vetoes=_strlist("vetoes"),
        sniff_bytes=sniff_bytes,
        enabled=bool(raw.get("enabled", True)),
        description=str(raw.get("description") or ""),
    )
    # 必填项缺失 ⇒ 该规则永远不会命中，留着只是噪音，直接丢弃。
    if kind in ("filename_keyword", "path_segment") and not rule.patterns:
        return None
    if kind == "extension" and not rule.extensions:
        return None
    if kind == "content_sniff" and not (rule.patterns or rule.require_all):
        return None
    if kind == "content_sniff":
        for pat in rule.patterns + rule.require_all:
            try:
                re.compile(pat)
            except re.error:
                return None
    return rule


_RULES_CACHE: dict[tuple, ChecklistRules] = {}


def load_checklist_rules(path: str | Path | None = None) -> ChecklistRules:
    """加载清单排除规则集。

    优先级：显式 ``path`` > 环境变量 ``CANGJIE_DD_V1_CHECKLIST_RULES`` > 内置规则。

    **读不出来就回退内置规则**（排除行为不因配置坏了而失效），
    失败原因记在 ``load_error`` 里，供审计如实展示。
    """
    if path is not None:
        cfg = Path(path)
    else:
        cfg = _checklist_rules_config_path()

    if cfg is None:
        return ChecklistRules(
            ruleset_version=DEFAULT_CHECKLIST_RULESET_VERSION,
            source="builtin",
            path="",
            rules=_builtin_rules(),
        )

    key = _rules_cache_key(cfg)
    cached = _RULES_CACHE.get(key)
    if cached is not None:
        return cached

    source = "env" if (os.getenv(CHECKLIST_RULES_ENV) or "").strip() else "config"
    rules, version, error = _parse_rules_file(cfg)
    if rules is None:
        # 规则文件不可用 ⇒ 回退内置（fail-closed：清单照常被排除）
        ruleset = ChecklistRules(
            ruleset_version=DEFAULT_CHECKLIST_RULESET_VERSION,
            source="builtin",
            path=str(cfg),
            rules=_builtin_rules(),
            load_error=error or f"规则文件不可用：{cfg}",
        )
        _RULES_CACHE[key] = ruleset
        return ruleset

    ruleset = ChecklistRules(
        ruleset_version=version or DEFAULT_CHECKLIST_RULESET_VERSION,
        source=source,
        path=str(cfg),
        rules=rules,
        load_error=error,
    )
    _RULES_CACHE[key] = ruleset
    return ruleset


def _rules_cache_key(cfg: Path) -> tuple:
    try:
        st = cfg.stat()
        return (str(cfg), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(cfg), 0, 0)


def _parse_rules_file(cfg: Path) -> tuple[tuple[ChecklistRule, ...] | None, str, str]:
    """解析 JSON 规则文件。返回 (rules, version, error)；rules=None 表示不可用。"""
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — 规则文件坏了必须回退内置
        return None, "", f"规则文件无法解析：{exc}"
    if not isinstance(data, dict):
        return None, "", "规则文件根节点必须是对象"

    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        return None, "", "规则文件缺 rules 列表（或为空）"

    rules: list[ChecklistRule] = []
    seen: set[str] = set()
    errors: list[str] = []
    for raw in raw_rules:
        rule = _rule_from_dict(raw)
        if rule is None:
            errors.append("有条规则字段不合法，已丢弃")
            continue
        if rule.rule_id in seen:
            errors.append(f"规则 id 重复：{rule.rule_id}（保留首条）")
            continue
        seen.add(rule.rule_id)
        rules.append(rule)

    if not rules:
        return None, "", "规则文件里没有一条可用规则"

    # 确定性顺序：priority 小者先判；同 priority 按 rule_id 字典序。
    rules.sort(key=lambda r: (r.priority, r.rule_id))
    version = str(data.get("ruleset_version") or "").strip()
    return tuple(rules), version, ("；".join(errors) if errors else "")


def _builtin_rules() -> tuple[ChecklistRule, ...]:
    rules = [r for r in (_rule_from_dict(x) for x in _BUILTIN_CHECKLIST_RULES) if r]
    rules.sort(key=lambda r: (r.priority, r.rule_id))
    return tuple(rules)


def _stem(name: str) -> str:
    """文件名主干（去扩展名）。"""
    return name.rsplit(".", 1)[0] if "." in name else name


def _path_segments(rel_path: str) -> tuple[str, ...]:
    """相对路径里的**目录名**（不含文件名本身）。"""
    parts = Path(rel_path).parts
    return tuple(p.casefold() for p in parts[:-1])


def _decode_sniff(raw: bytes) -> str:
    """嗅探字节解码。

    顺序：**严格 UTF-8 → 截尾 UTF-8 → 严格 GB18030**。

    不能用「谁的中文字符多就用谁」—— UTF-8 字节被当成 GBK 解出来的乱码
    （搴忓彿…）同样是中文且数量更多，会把正常材料判成乱码。
    """
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # 嗅探窗口可能把 UTF-8 的最后一个字符切成半个序列 ⇒ 去掉尾字节再试。
    for trim in range(1, 5):
        if len(raw) <= trim:
            break
        try:
            return raw[: len(raw) - trim].decode("utf-8")
        except UnicodeDecodeError:
            continue
    try:
        return raw.decode("gb18030")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="ignore")


def _sniff_text(file_path: Path, sniff_bytes: int, cache: dict) -> str:
    """读取文件头部若干字节并解码成文本（只读，不改文件）。"""
    key = (str(file_path), sniff_bytes)
    if key in cache:
        return cache[key]
    text = ""
    try:
        with file_path.open("rb") as fh:
            raw = fh.read(max(0, sniff_bytes))
        text = _decode_sniff(raw)
    except OSError:
        text = ""
    cache[key] = text
    return text


def _rule_matches(
    rule: ChecklistRule,
    rel_path: str,
    file_path: Path,
    text_cache: dict,
) -> bool:
    """单条规则是否命中。判定纯确定性，不依赖时间/顺序/外部状态。"""
    name = Path(rel_path).name
    ext = Path(name).suffix.lower()
    stem = _stem(name).casefold()

    # 扩展名收窄（kind=extension 时它就是命中集合）
    if rule.extensions and ext not in rule.extensions:
        return False

    if rule.kind == "filename_keyword":
        if any(v.casefold() in stem for v in rule.vetoes):
            return False
        if not any(p.casefold() in stem for p in rule.patterns):
            return False
        return all(p.casefold() in stem for p in rule.require_all)

    if rule.kind == "path_segment":
        want = {p.casefold() for p in rule.patterns}
        for seg in _path_segments(rel_path):
            if seg in want:
                if any(v.casefold() in seg for v in rule.vetoes):
                    continue
                return True
        return False

    if rule.kind == "extension":
        if ext not in rule.extensions:
            return False
        if any(v.casefold() in stem for v in rule.vetoes):
            return False
        if rule.patterns and not any(p.casefold() in stem for p in rule.patterns):
            return False
        return True

    if rule.kind == "content_sniff":
        text = _sniff_text(file_path, rule.sniff_bytes, text_cache)
        if not text:
            return False
        for pat in rule.vetoes:
            if re.search(pat, text):
                return False
        if rule.require_all:
            return all(re.search(p, text) for p in rule.require_all)
        return any(re.search(p, text) for p in rule.patterns)

    return False


def classify_checklist_file(
    rel_path: str,
    file_path: Path,
    rules: ChecklistRules,
    text_cache: dict | None = None,
) -> tuple[str, str] | None:
    """判定一个文件是否属于「清单类（考题）」。

    返回 ``(rule_id, kind)`` 表示命中；``None`` 表示是材料（证据），应进材料库。
    **返回里绝不含文件名**：调用方拿到的只是规则 id 与计数。
    """
    cache = text_cache if text_cache is not None else {}
    for rule in rules.rules:
        if not rule.enabled:
            continue
        try:
            if _rule_matches(rule, rel_path, file_path, cache):
                return rule.rule_id, rule.kind
        except Exception as exc:  # noqa: BLE001 — 单条规则异常不得中断整轮扫描
            logger.warning("清单排除规则 %s 判定异常，本条跳过：%s", rule.rule_id, exc)
    return None


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
    # 清单排除（W8 / A2-1）：结构化计数，对外只给数量与规则 id
    excluded_checklist_count: int = 0
    excluded_by_rule: dict = field(default_factory=dict)
    rule_hit_but_not_excluded_count: int = 0
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
            "excluded_checklist_count": self.excluded_checklist_count,
            "excluded_by_rule": dict(self.excluded_by_rule),
            "rule_hit_but_not_excluded_count": self.rule_hit_but_not_excluded_count,
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
            # 租约围栏：只在**租约仍然有效**时拒绝他人。
            # 首轮实现漏判 lease_expires_at，导致进程崩溃后租约虽过期却永远无人能接管，
            # run 永久卡在 running——与 GM 侧 G02/G08「围栏不跨重启」同类病症。
            if run["lease_expires_at"] > now:
                raise RuntimeError(
                    f"run {resume_run_id} 已被 {run['lease_owner']} 持有，"
                    f"租约有效至 {run['lease_expires_at']:.0f}，拒绝并发恢复"
                )
            logger.warning(
                "run %s 原持有者 %s 的租约已于 %.0f 过期，由 %s 接管恢复",
                resume_run_id, run["lease_owner"], run["lease_expires_at"], lease_owner,
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
    last_rel = ""
    last_commit_at = time.time()
    rules = load_checklist_rules()
    text_cache: dict = {}

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
            conn.commit()

        for f in files:
            rel = f.relative_to(root).as_posix()
            # 清单 = 考题，不是证据：命中规则的文件**不进材料库**（W8 / A2-1）。
            hit = classify_checklist_file(rel, f, rules, text_cache)
            if hit is not None:
                rule_id, _kind = hit
                stats.excluded_checklist_count += 1
                stats.excluded_by_rule[rule_id] = stats.excluded_by_rule.get(rule_id, 0) + 1
                # 排除动作：把历史轮次可能已入库的同一路径软删除（绝不碰客户原文件）。
                _exclude_from_corpus(conn, library_id, rel, now)
                # 命中规则却仍留在材料库 ⇒ 计数（必须恒为 0；非 0 即是缺陷）。
                if _still_in_corpus(conn, library_id, rel):
                    stats.rule_hit_but_not_excluded_count += 1
                continue
            seen_rel.add(rel)
            last_rel = rel
            try:
                _upsert_file(conn, library_id, root, f, rel, mode, stats, now)
            except Exception as exc:  # noqa: BLE001 — 单文件失败不得中断整轮扫描
                stats.failed += 1
                logger.warning("Manifest 读取失败 %s：%s", rel, exc)
            stats.processed += 1

            # 按份数或按时间先到先提交：保证崩溃时最多损失一个窗口的进度，
            # 且 run 记录里的 processed 始终反映「真正落盘」的进度。
            now_ts = time.time()
            if (stats.processed % COMMIT_EVERY_FILES == 0
                    or now_ts - last_commit_at >= COMMIT_EVERY_SECONDS):
                _touch(conn, run_id, stats, lease_owner, lease_seconds)
                conn.commit()
                last_commit_at = now_ts
                if progress_callback:
                    progress_callback(stats.processed, stats.total)

        if mode != "retry":
            stats.removed = _soft_delete_missing(conn, library_id, seen_rel, now)

        _touch(conn, run_id, stats, lease_owner, lease_seconds)
        stats.status = RUN_COMPLETED
        conn.execute(
            "UPDATE dd_v1_scan_runs SET status=?, last_error='', last_rel_path=? WHERE run_id=?",
            (RUN_COMPLETED, last_rel, run_id),
        )
        conn.commit()

    except Exception as exc:  # noqa: BLE001
        _touch(conn, run_id, stats, lease_owner, lease_seconds)
        conn.execute(
            "UPDATE dd_v1_scan_runs SET status=?, last_error=? WHERE run_id=?",
            (RUN_FAILED, str(exc)[:500], run_id),
        )
        conn.commit()
        # 失败也要留痕：排除动作已发生的部分必须可审计。
        _record_checklist_exclusions(conn, library_id, run_id, rules, stats, now)
        conn.commit()
        raise

    _record_checklist_exclusions(conn, library_id, run_id, rules, stats, now)
    conn.commit()
    if stats.excluded_checklist_count:
        logger.info(
            "清单类文件已排除 %d 份（规则分布 %s；命中未排除 %d）",
            stats.excluded_checklist_count,
            ", ".join(f"{rid}={cnt}" for rid, cnt in sorted(stats.excluded_by_rule.items())),
            stats.rule_hit_but_not_excluded_count,
        )

    out = stats.to_dict()
    out["data_plane"] = str(data_plane)
    out["source_root"] = str(root)
    out["checklist_rules"] = rules.to_dict()
    return out


def _exclude_from_corpus(conn: sqlite3.Connection, library_id: str, rel_path: str, now: float) -> None:
    """把一份清单类文件从材料库里摘掉（**软删除**，绝不删客户原文件）。

    幂等：已删除的行不受影响；历史轮次已入库的清单靠这一步退出材料库。
    """
    conn.execute(
        """UPDATE dd_v1_manifest SET deleted_at=?
           WHERE library_id=? AND rel_path=? AND deleted_at IS NULL""",
        (now, library_id, rel_path),
    )


def _still_in_corpus(conn: sqlite3.Connection, library_id: str, rel_path: str) -> bool:
    """该路径是否仍有一条**存活**的材料记录（命中规则却仍在库 ⇒ 缺陷）。"""
    row = conn.execute(
        """SELECT 1 FROM dd_v1_manifest
           WHERE library_id=? AND rel_path=? AND deleted_at IS NULL LIMIT 1""",
        (library_id, rel_path),
    ).fetchone()
    return row is not None


def _record_checklist_exclusions(
    conn: sqlite3.Connection,
    library_id: str,
    run_id: str,
    rules: ChecklistRules,
    stats: ScanStats,
    now: float,
) -> None:
    """把本轮排除结果落成一行审计记录（**只存计数与规则 id，不存文件名**）。"""
    conn.execute(
        """INSERT OR REPLACE INTO dd_v1_checklist_exclusions
           (run_id, library_id, ruleset_version, rules_source,
            excluded_checklist_count, excluded_by_rule,
            rule_hit_but_not_excluded_count, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            run_id, library_id, rules.ruleset_version, rules.source,
            stats.excluded_checklist_count,
            json.dumps(dict(sorted(stats.excluded_by_rule.items())), ensure_ascii=False),
            stats.rule_hit_but_not_excluded_count, now,
        ),
    )


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


def _exclusion_record(row: sqlite3.Row) -> dict:
    """一行审计记录 → 结构化 dict（只含计数与规则 id）。"""
    try:
        by_rule = json.loads(row["excluded_by_rule"] or "{}")
    except (ValueError, TypeError):
        by_rule = {}
    if not isinstance(by_rule, dict):
        by_rule = {}
    return {
        "run_id": row["run_id"],
        "ruleset_version": row["ruleset_version"],
        "rules_source": row["rules_source"],
        "excluded_checklist_count": row["excluded_checklist_count"],
        "excluded_by_rule": by_rule,
        "rule_hit_but_not_excluded_count": row["rule_hit_but_not_excluded_count"],
        "created_at": row["created_at"],
    }


def _latest_exclusion_record(conn: sqlite3.Connection, library_id: str) -> dict:
    """该材料库最近一轮的排除记录 + 历次累计（无记录时给全 0）。"""
    row = conn.execute(
        """SELECT * FROM dd_v1_checklist_exclusions
           WHERE library_id=? ORDER BY created_at DESC, run_id DESC LIMIT 1""",
        (library_id,),
    ).fetchone()
    if row is None:
        return {
            "run_id": "", "ruleset_version": "", "rules_source": "",
            "excluded_checklist_count": 0, "excluded_by_rule": {},
            "rule_hit_but_not_excluded_count": 0, "created_at": 0,
            "excluded_checklist_total": 0, "rule_hit_but_not_excluded_total": 0,
        }
    rec = _exclusion_record(row)
    agg = conn.execute(
        """SELECT COALESCE(SUM(excluded_checklist_count),0) AS s,
                  COALESCE(SUM(rule_hit_but_not_excluded_count),0) AS h
           FROM dd_v1_checklist_exclusions WHERE library_id=?""",
        (library_id,),
    ).fetchone()
    rec["excluded_checklist_total"] = agg["s"]
    rec["rule_hit_but_not_excluded_total"] = agg["h"]
    return rec


def manifest_summary(library_id: str, db_path: Path | None = None) -> dict:
    """材料库概览：按解析状态与扩展名统计（供 Gate 与报告使用）。

    同时给出清单排除的结构化计数（只含数量与规则 id，不含文件名），
    便于调用方直接读数而不必去解析日志文本。
    """
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
    excl = _latest_exclusion_record(conn, library_id)
    return {
        "library_id": library_id,
        "total": total,
        "by_parse_status": by_status,
        "deleted": conn.execute(
            "SELECT COUNT(*) c FROM dd_v1_manifest WHERE library_id=? AND deleted_at IS NOT NULL",
            (library_id,),
        ).fetchone()["c"],
        "excluded_checklist_count": excl["excluded_checklist_count"],
        "excluded_by_rule": excl["excluded_by_rule"],
        "rule_hit_but_not_excluded_count": excl["rule_hit_but_not_excluded_count"],
        "checklist_exclusion": excl,
    }


def get_checklist_exclusion_report(
    library_id: str | None = None,
    run_id: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """清单排除审计报告：只给计数与规则 id，**不给任何真实文件名**。

    - 传 ``run_id`` ⇒ 该轮扫描的排除记录；
    - 传 ``library_id`` ⇒ 该库最近一轮的排除记录 + 历次累计；
    - 都不传 ⇒ 全库最近一轮。
    """
    conn = _connect(db_path)
    if run_id:
        row = conn.execute(
            "SELECT * FROM dd_v1_checklist_exclusions WHERE run_id=?", (run_id,)
        ).fetchone()
        return _exclusion_record(row) if row else {
            "run_id": run_id, "ruleset_version": "", "rules_source": "",
            "excluded_checklist_count": 0, "excluded_by_rule": {},
            "rule_hit_but_not_excluded_count": 0, "created_at": 0,
        }
    if library_id:
        return _latest_exclusion_record(conn, library_id)
    row = conn.execute(
        """SELECT * FROM dd_v1_checklist_exclusions
           ORDER BY created_at DESC, run_id DESC LIMIT 1"""
    ).fetchone()
    return _exclusion_record(row) if row else {
        "run_id": "", "ruleset_version": "", "rules_source": "",
        "excluded_checklist_count": 0, "excluded_by_rule": {},
        "rule_hit_but_not_excluded_count": 0, "created_at": 0,
    }


def get_run(run_id: str, db_path: Path | None = None) -> dict | None:
    """恢复入口：任何时刻都应能从 run_id 取回断点位置。"""
    row = _connect(db_path).execute(
        "SELECT * FROM dd_v1_scan_runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    out = dict(row)
    # 顺带带上本轮的清单排除计数（不改动原表结构，只做读取合并）。
    out["checklist_exclusion"] = get_checklist_exclusion_report(run_id=run_id, db_path=db_path)
    return out


def find_resumable_run(library_id: str, db_path: Path | None = None) -> dict | None:
    """找出上次中断、仍处于 running 的运行（断点恢复入口）。"""
    row = _connect(db_path).execute(
        """SELECT * FROM dd_v1_scan_runs
           WHERE library_id=? AND status=? ORDER BY started_at DESC LIMIT 1""",
        (library_id, RUN_RUNNING),
    ).fetchone()
    return dict(row) if row else None
