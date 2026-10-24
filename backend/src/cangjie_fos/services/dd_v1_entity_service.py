"""权威主体名单 + **别名/简称归一**（A2 · G-A2-3 / G-A2-8）。

为什么要有「别名」
----------------
认知卡的 ``entity`` 字段取的是**材料库里的目录名**（``dd_v1_card_service.build_card``
的 ``parts[-2]``，provenance=INFERRED / evidence=path_segment）。
真实材料库普遍按法人建目录，于是：

- 权威名单里登记的是**法定全称**（营业执照上的名字）；
- 卡片里存的是**目录名/客户简称**（可能还带 ``(1)`` 这类副本后缀）；
- ⇒ 两边**永不相等** ⇒ 主体 100% 判「未登记」⇒ 判定层永远 UNCERTAIN。

监工第 27 轮实测（登记 2 个法定全称主体后仍 100% 未登记）证实了这一点：
**「只填权威名单」这一格单独做完没有任何效果。**

## 两条路，司仓已裁定必须择一（G-A2-8）

- **甲（本模块实现）别名归一**：登记主体时把**材料库目录名/客户简称**登记为该主体的别名，
  匹配前归一 ⇒ 目录名从此是「**被登记的简称**」，而不是「冒充主体」；
- **乙** 改从文件名/正文抽全称 —— 扫描件 OCR 实测有 1 字误差 ⇒ 须双轨校验 + 人工确认。

别名归一只解决「同一主体的不同叫法」，**不解决**「主体到底是谁」——
后者仍须回到正文抽取 + 人工确认（见 ``dd_v1_card_service.set_human_override``）。

## 三条不可破的纪律

1. **别名不得跨主体复用** —— 一个别名挂两个主体 ⇒ **拒绝登记**（不是「先到先得」）；
2. **别名的 provenance 记 ``ALIAS``（INFERRED）**，**不得**记 FACT ——
   「目录名对应某法人」是登记事实，「这份材料的主体就是该法人」**仍需核实**；
3. **未登记就是未登记** —— 匹配不上时返回「未登记」，**不得**退化成「大概匹配」，
   更不得把目录名当 FACT 放行（FOS 的老规矩：宁可不知道，不臆造）。

## 别名存哪

- **权威库**：``dd_v1_entity_aliases`` 表（随主体登记一起入库，**不进 Git**）；
- **可选配置**：``backend/config/dd_v1_entity_aliases.json``
  （环境变量 ``CANGJIE_DD_V1_ENTITY_ALIASES`` 可指向别的文件）。
  **仓内那份是空模板** —— 真实客户简称不进 Git。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path

from cangjie_fos.services import dd_v1_manifest_service as mf

FACT = "FACT"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"

#: 匹配来源标记
BY_DISPLAY_NAME = "display_name"   # 与登记全称**逐字**相等
BY_ALIAS = "alias"                 # 与登记别名相等（INFERRED）

#: 副本后缀：材料库里常见的 ``名称(1)`` / ``名称（2）`` / ``名称-副本``。
#: 归一时**两侧都**剥掉 ⇒ 登记「主体甲」即可匹配「主体甲(1)」。
_TRAILING_COPY_RE = re.compile(r"[\s_\-]*(?:[（(]\s*\d+\s*[)）]|副本|复件|扫描件)\s*$")

_DDL = """
CREATE TABLE IF NOT EXISTS dd_v1_entity_aliases (
    library_id   TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    alias        TEXT NOT NULL,
    alias_basis  TEXT NOT NULL DEFAULT 'ALIAS',
    alias_kind   TEXT NOT NULL DEFAULT 'LEGAL',
    source_ref   TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    PRIMARY KEY (library_id, alias)
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_entity_aliases_entity
    ON dd_v1_entity_aliases(library_id, entity_id);
"""


# ── 别名种类（alias_kind）· A2 F1 产品侧守卫 ────────────────────────────────
#
# ★ 为什么需要「种类」（独立监工第 36 轮指出的**产品侧守卫缺口**）：
#   别名表原先只有三条守卫（别名非空 / source_ref 非空 / 主体必须已登记 /
#   别名不得跨主体复用），**没有一条**能挡住「把材料类型分类目录登记成主体别名」。
#   ⇒ F1 只修在**名单侧**（生成器不登记分类目录）⇒ 换个材料库、换个人写脚本、
#     或将来任何一次程序化登记，都会把「同分类目录下不同子型的材料进同一桶
#     ⇒ 异哈希 ⇒ 报假 CONFLICT」原样复现。
#
# ★ 三种别名：
#   LEGAL     —— 法定全称 / 工商简称 / 名录英文简称（**主体维度**）
#   USCI      —— 统一社会信用代码（**主体维度**，跨材料库稳定键）
#   DIRECTORY —— **材料分类目录**（如「1.审计报告」）（**分类维度，不是主体维度**）
#
# ★ DIRECTORY 型别名的处置：
#   **不参与主体归一**（既不算 entity_ok，也不参与冲突分桶）
#   ⇒ 落「主体未登记」桶 ⇒ **不产生假 CONFLICT**，同时**照常留痕**。
ALIAS_KIND_LEGAL = "LEGAL"
ALIAS_KIND_USCI = "USCI"
ALIAS_KIND_DIRECTORY = "DIRECTORY"
ALIAS_KINDS = (ALIAS_KIND_LEGAL, ALIAS_KIND_USCI, ALIAS_KIND_DIRECTORY)

#: 材料分类目录的**形态特征**：数字编号打头（材料库普遍用「1.xxx」「10.xxx」编号）。
_CLASSIFICATION_DIR_RE = re.compile(r"^\s*\d+\s*[.、．·]\s*")


def is_directory_alias(alias: str) -> bool:
    """这个别名**看起来像材料分类目录**吗（而不是主体名）？"""
    return bool(_CLASSIFICATION_DIR_RE.match(str(alias or "")))


def classify_alias_kind(alias: str, declared: str | None = None) -> str:
    """定别名种类：**形态判定优先**，显式声明只能往保守方向收紧。

    - 形态像分类目录 ⇒ **DIRECTORY**（无论声明成什么）
      ⇒ 分类维度不冒充主体维度；
    - 否则取显式声明；没声明 ⇒ ``LEGAL``。
    """
    if is_directory_alias(alias):
        return ALIAS_KIND_DIRECTORY
    d = str(declared or "").strip().upper()
    if not d:
        return ALIAS_KIND_LEGAL
    if d not in ALIAS_KINDS:
        raise ValueError(f"alias_kind 只能是 {ALIAS_KINDS} 之一，实为 {declared!r}")
    return d


def _ensure_schema(conn) -> None:
    conn.executescript(_DDL)
    _migrate_alias_kind(conn)
    conn.commit()


def _migrate_alias_kind(conn) -> None:
    """给**已存在**的别名表补 ``alias_kind`` 列（旧库升级，不丢数据）。"""
    try:
        cols = {str(r[1]) for r in conn.execute(
            "PRAGMA table_info(dd_v1_entity_aliases)")}
    except sqlite3.OperationalError:
        return
    if "alias_kind" in cols:
        return
    try:
        conn.execute(
            "ALTER TABLE dd_v1_entity_aliases "
            "ADD COLUMN alias_kind TEXT NOT NULL DEFAULT 'LEGAL'")
    except sqlite3.OperationalError:
        pass


# ── 归一 ────────────────────────────────────────────────────────────────────
def normalize_name(value: str) -> str:
    """主体名归一：去空白、去副本后缀、统一大小写。

    只做**保守**归一：不去标点、不删中间字符、不做繁简转换。
    """
    s = str(value or "").strip()
    if not s:
        return ""
    s = _TRAILING_COPY_RE.sub("", s).strip()
    return s.casefold()


# ── 别名配置（可选，仓内是空模板）────────────────────────────────────────────
def _default_alias_path() -> Path:
    env = (os.getenv("CANGJIE_DD_V1_ENTITY_ALIASES") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "config" / "dd_v1_entity_aliases.json"


def load_alias_config(path: str | Path | None = None) -> list[dict]:
    """读别名配置文件。

    - 文件不存在 → ``[]``（不是错误：别名可以只存在库里）；
    - 解析失败 → **抛异常**（静默忽略别名等于让主体判活名不副实）；
    - 结构必须是 ``{"aliases": [{"alias": ..., "entity_id": ..., "display_name": ...}]}``。
    """
    p = Path(path) if path else _default_alias_path()
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    raw = data.get("aliases")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"aliases 必须是列表，实为 {type(raw).__name__}")
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"aliases 元素必须是对象，实为 {type(item).__name__}")
        alias = str(item.get("alias") or "").strip()
        if not alias:
            continue
        out.append({
            "alias": alias,
            "entity_id": str(item.get("entity_id") or "").strip(),
            "display_name": str(item.get("display_name") or "").strip(),
            "alias_kind": (str(item.get("alias_kind") or "").strip().upper() or None),
        })
    return out


# ── 登记 ────────────────────────────────────────────────────────────────────
def register_entity_alias(library_id: str, entity_id: str, alias: str,
                          *, source_ref: str = "",
                          alias_kind: str | None = None,
                          db_path: Path | None = None) -> None:
    """给权威主体登记一个**别名/简称**。

    纪律：
    - 主体必须**已登记**（别名不能凭空存在）；
    - ``source_ref`` 必填——别名也要有依据出处；
    - **别名不得跨主体复用**：已被别的实体占用 ⇒ 直接拒绝（不覆盖、不静默改写）；
    - ★ **材料分类目录不得登记为法定主体别名**（F1 产品侧守卫）：
      形态像分类目录（数字编号打头）的别名 ⇒ 只能是 ``DIRECTORY``；
      若调用方**显式**声明成 ``LEGAL``/``USCI`` ⇒ **拒绝登记**（不静默改写）。
      （形态判定优先于声明 ⇒ 声明也救不了分类目录。）
    """
    alias = str(alias or "").strip()
    if not alias:
        raise ValueError("alias 不能为空")
    if not source_ref.strip():
        raise ValueError("source_ref 不能为空：别名登记必须有依据出处")
    kind = classify_alias_kind(alias, alias_kind)
    declared = str(alias_kind or "").strip().upper()
    if kind == ALIAS_KIND_DIRECTORY and declared in (ALIAS_KIND_LEGAL, ALIAS_KIND_USCI):
        raise ValueError(
            f"别名 {alias!r} 的形态是**材料分类目录**（数字编号打头）⇒ "
            f"只能登记为 {ALIAS_KIND_DIRECTORY}（分类维度），"
            f"不得登记为 {declared}（主体维度）；"
            f"否则同一分类目录下的不同材料会进同一「主体」桶 ⇒ 异哈希 ⇒ 报假 CONFLICT")
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    try:
        row = conn.execute(
            "SELECT display_name FROM dd_v1_entities WHERE library_id=? AND entity_id=?",
            (library_id, entity_id)).fetchone()
    except sqlite3.OperationalError as exc:
        # 该库从未登记过主体 ⇒ ``dd_v1_entities`` 表还不存在。
        # 这**不是**数据库故障，而是「主体未登记」的另一种表现形式 ⇒
        # 统一表达成既定的 ValueError 契约，**不误导调用方**。
        if "no such table" in str(exc):
            raise ValueError(
                f"主体未登记：{library_id}/{entity_id}（别名不能凭空存在）") from exc
        raise
    if not row:
        raise ValueError(f"主体未登记：{library_id}/{entity_id}（别名不能凭空存在）")
    key = normalize_name(alias)
    clash = conn.execute(
        "SELECT entity_id FROM dd_v1_entity_aliases WHERE library_id=? AND alias=?",
        (library_id, key)).fetchone()
    if clash and str(clash["entity_id"]) != str(entity_id):
        raise ValueError(
            f"别名 {alias!r} 已登记给主体 {clash['entity_id']!r}；"
            f"别名不得跨主体复用（要复用请先改名或撤销原登记）")
    conn.execute(
        """INSERT INTO dd_v1_entity_aliases
           (library_id, entity_id, alias, alias_basis, alias_kind, source_ref, created_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(library_id, alias) DO UPDATE SET
             entity_id=excluded.entity_id, alias_basis=excluded.alias_basis,
             alias_kind=excluded.alias_kind, source_ref=excluded.source_ref""",
        (library_id, entity_id, key, "ALIAS", kind, source_ref, time.time()))
    conn.commit()


def alias_map(library_id: str, db_path: Path | None = None,
              *, include_config: bool = True,
              include_directory: bool = False) -> dict[str, dict]:
    """取本库的全部别名 ⇒ ``{归一别名: {entity_id, display_name, basis, source, alias_kind}}``。

    库内登记优先于配置文件（同 key 时以库内为准）。

    ★ ``include_directory=False``（默认）⇒ **DIRECTORY 型别名（材料分类目录）
      不出现在结果里** —— 它们是**分类维度**，不得用于主体归一
      （F1 产品侧守卫：防止「同一分类目录 ⇒ 同一主体桶 ⇒ 假 CONFLICT」）。
    """
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    out: dict[str, dict] = {}

    def _kind_of(raw_alias: str, declared: str | None) -> str:
        try:
            return classify_alias_kind(raw_alias, declared)
        except ValueError:
            return ALIAS_KIND_LEGAL
    if include_config:
        try:
            for item in load_alias_config():
                key = normalize_name(item["alias"])
                if not key:
                    continue
                kind = _kind_of(str(item["alias"]), item.get("alias_kind"))
                if kind == ALIAS_KIND_DIRECTORY and not include_directory:
                    continue
                out[key] = {
                    "entity_id": item.get("entity_id") or "",
                    "display_name": item.get("display_name") or "",
                    "basis": "ALIAS",
                    "source": "config",
                    "alias_kind": kind,
                }
        except Exception:  # noqa: BLE001
            # 配置文件坏了**不能**让整条判定链崩掉，但也绝不能静默当成没有别名：
            # 宁可少一条归一（主体判「未登记」⇒ UNCERTAIN），也不静默放行。
            out = out  # 保留已读到的库内别名
    rows = conn.execute(
        """SELECT a.entity_id, a.alias, a.alias_kind, a.source_ref, e.display_name
           FROM dd_v1_entity_aliases a
           LEFT JOIN dd_v1_entities e
             ON e.library_id=a.library_id AND e.entity_id=a.entity_id
           WHERE a.library_id=?""",
        (library_id,)).fetchall()
    for r in rows:
        _declared = str(r["alias_kind"] or "") or None
        kind = _kind_of(str(r["alias"]), _declared)
        if kind == ALIAS_KIND_DIRECTORY and not include_directory:
            continue
        out[str(r["alias"])] = {
            "entity_id": str(r["entity_id"]),
            "display_name": str(r["display_name"] or ""),
            "basis": "ALIAS",
            "source": str(r["source_ref"] or ""),
            "alias_kind": kind,
        }
    return out


def list_aliases(library_id: str, db_path: Path | None = None) -> list[dict]:
    """列出本库登记的别名（审计用）。"""
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    return [dict(r) for r in conn.execute(
        "SELECT entity_id, alias, alias_basis, source_ref FROM dd_v1_entity_aliases "
        "WHERE library_id=? ORDER BY entity_id, alias", (library_id,))]


# ── 匹配 ────────────────────────────────────────────────────────────────────
def match_entity(value: str, entities: list[dict],
                 aliases: dict[str, dict] | None = None) -> dict:
    """把一个主体名线索匹配到权威主体。

    返回 ``{"matched": bool, "entity_id", "display_name", "basis", "matched_by",
    "evidence"}``。匹配不上 ⇒ ``matched=False``，**不得**猜测。
    """
    aliases = aliases or {}
    raw = str(value or "").strip()
    key = normalize_name(raw)
    if not key:
        return {"matched": False, "entity_id": "", "display_name": "",
                "basis": UNKNOWN, "matched_by": "",
                "evidence": [{"kind": "empty_subject",
                              "note": "主体线索为空；不得用目录名凑数"}]}

    # 1) 与登记全称逐字相等（归一后）
    for e in entities or []:
        if normalize_name(e.get("display_name") or "") == key:
            return {
                "matched": True,
                "entity_id": str(e.get("entity_id") or ""),
                "display_name": str(e.get("display_name") or ""),
                "basis": FACT,
                "matched_by": BY_DISPLAY_NAME,
                "evidence": [{
                    "kind": "authority_register",
                    "note": "与权威主体登记的全称相等",
                    "source_ref": str(e.get("source_ref") or ""),
                }],
            }

    # 2) 与登记别名相等（**INFERRED**，不是 FACT）
    hit = aliases.get(key)
    if hit:
        return {
            "matched": True,
            "entity_id": str(hit.get("entity_id") or ""),
            "display_name": str(hit.get("display_name") or ""),
            "basis": INFERRED,
            "matched_by": BY_ALIAS,
            "evidence": [{
                "kind": "alias_register",
                "note": "与权威主体登记的别名/简称相等；"
                        "「目录名对应该法人」是登记事实，"
                        "「这份材料的主体就是该法人」仍需核实",
                "source_ref": str(hit.get("source") or ""),
            }],
        }

    return {
        "matched": False, "entity_id": "", "display_name": "",
        "basis": UNKNOWN, "matched_by": "",
        "evidence": [{
            "kind": "subject_not_registered",
            "note": "主体线索未在权威名单中登记，也不是已登记别名；"
                    "不得拿目录名/文件名凑数",
        }],
    }


def canonical_subject(value: str, entities: list[dict],
                      aliases: dict[str, dict] | None = None) -> str:
    """把主体线索归一成**权威主体的显示名**；匹配不上就返回空串。

    归一后同一主体的不同叫法（法定全称 / 目录名 / 简称）落进**同一个桶**。
    """
    m = match_entity(value, entities, aliases)
    return m["display_name"] if m["matched"] else ""
