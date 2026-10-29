"""DD-V1 主体识别与主体范围判定服务 · cangjie-fos#71 / `#108` 实测 P0-1、P0-2。

**两个真问题**（`#108` 刘江 2026-10-28 Windows 实测）：

- **P0-1**：义务**没有指名主体**，而库里登记了多个主体 ⇒ 旧口径判「无法判定」
  ⇒ 42 题 91 条义务**全部 UNCERTAIN**、**0 件交付**。
- **P0-2**：材料库目录**不携带法人级**（证照类用「四川及湖南、北京子公司营业执照」
  这类**分类目录**）⇒ 材料侧主体**认不出**（实测 17 份候选主体未登记）。

**本模块的两条纪律**：

1. **主体识别不能只靠文件夹名**。按**证据强度**依次综合：人工确认映射 ＞ 登记全称/别名
   命中文件名 ＞ 命中文件正文 ＞ 可信元数据 ＞ **认不出（保留不确定）**。
   每一档都留 ``matched_by`` 与证据，**认不出就认不出**，不猜。

2. **题目没写主体 ≠ 集团所有公司都符合要求**。主体范围由**考场契约里的显式声明**
   （``SINGLE_ENTITY`` / ``GROUP``）决定；**没有声明 ⇒ 保持不确定**（不无条件放行）。
   这正是「按业务语境、集团范围及明确规则判断；无法确定时保留不确定状态」。
"""
from __future__ import annotations

from typing import Any

from cangjie_fos.services import dd_v1_entity_service as es

FACT = "FACT"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"

#: 主体证据来源（**闭枚举**；`matched_by` 只会取这些值）
MATCHED_BY = (
    "HUMAN_CONFIRMED",     # 人工确认的主体映射表
    "REGISTRY_DISPLAY_NAME",  # 命中登记全称
    "REGISTRY_ALIAS",      # 命中登记别名（INFERRED）
    "FILENAME",            # 文件名里出现登记名
    "BODY_TEXT",           # 正文里出现登记全称
    "TRUSTED_METADATA",    # 可信元数据字段
    "DECLARED_META",       # meta 里已解析出主体
    "UNRESOLVED",          # 认不出
)
#: 主体范围的三种形态
SCOPE_SINGLE = "SINGLE_ENTITY"
SCOPE_GROUP = "GROUP"
SCOPE_UNSCOPED = "UNSCOPED"

#: 文件名里做全称匹配时，登记名至少要有这么长（防短名误命中）
_MIN_FULLNAME_LEN = 4
#: 正文扫描的最大字符数（只扫开头，避免长文档尾部噪声）
_BODY_SCAN_CHARS = 4000


def _norm(value: Any) -> str:
    return es.normalize_name(str(value or ""))


def _filename_of(meta_row: dict[str, Any]) -> str:
    rp = str(meta_row.get("relative_path") or "")
    return rp.replace("\\", "/").rsplit("/", 1)[-1]


def _path_of(meta_row: dict[str, Any]) -> str:
    return str(meta_row.get("relative_path") or "").replace("\\", "/")


def _entity_rows(entities: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [e for e in (entities or []) if str(e.get("display_name") or "").strip()]


def resolve_material_entity(meta_row: dict[str, Any] | None,
                            entities: list[dict[str, Any]] | None = None,
                            alias_map: dict[str, dict[str, Any]] | None = None,
                            *,
                            body_text: str | None = None,
                            confirmed_map: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """判定一份材料属于哪个法人主体。

    返回::

        {"entity": "主体全称", "entity_id": "...", "basis": "FACT|INFERRED|UNKNOWN",
         "matched_by": "<MATCHED_BY 之一>", "evidence": [...],
         "unresolved_reason": "..."（认不出时才有）}

    ★ **绝不**用「文件夹名看起来像公司名」当结论（`#108` 实测的失败方向）。
    ★ 认不出 ⇒ ``matched_by="UNRESOLVED"`` + ``unresolved_reason``，
      **保留不确定状态**，不静默归到某个主体。
    """
    row = meta_row or {}
    aliases = alias_map or {}
    confirmed = confirmed_map or {}
    regs = _entity_rows(entities)
    fname = _filename_of(row)
    path = _path_of(row)

    # 0) meta 已经解析出主体（上游 bridge 已解析过）⇒ 直接沿用，但**保留其依据**
    declared = str(row.get("entity") or "").strip()
    declared_basis = str(row.get("entity_basis") or "").strip()
    if declared and declared_basis in (FACT, INFERRED):
        return {
            "entity": declared, "entity_id": "", "basis": declared_basis,
            "matched_by": "DECLARED_META",
            "evidence": [{"kind": "declared_meta", "note": "沿用上游已解析的主体",
                          "basis": declared_basis}],
            "unresolved_reason": "",
        }

    # 1) 人工确认映射（最高优先级：人已经判过了）
    # ★ 认三种键：sha256（内容身份）｜file_id（FOS 内部稳定 id）｜归一后的文件名/路径
    for key in (str(row.get("sha256") or "").strip().lower(),
                str(row.get("file_id") or "").strip().lower(),
                _norm(fname), _norm(path)):
        if key and key in confirmed:
            c = confirmed[key]
            return {
                "entity": str(c.get("entity") or c.get("display_name") or ""),
                "entity_id": str(c.get("entity_id") or ""),
                "basis": FACT,
                "matched_by": "HUMAN_CONFIRMED",
                "evidence": [{"kind": "human_confirmed_map",
                              "note": "命中人工确认的主体映射表",
                              "source_ref": str(c.get("source_ref") or "")}],
                "unresolved_reason": "",
            }

    # 2) 登记全称出现在**路径段**（目录名**逐字等于**登记全称）或**文件名**里
    #    （文件名是材料的自述，比目录名可靠；目录段逐字相等才算，不做子串凑数）
    path_segments = [s for s in path.split("/") if s]
    for e in regs:
        name = str(e.get("display_name") or "")
        if len(name) < _MIN_FULLNAME_LEN:
            continue
        if any(seg == name for seg in path_segments):
            return {
                "entity": name, "entity_id": str(e.get("entity_id") or ""), "basis": FACT,
                "matched_by": "REGISTRY_DISPLAY_NAME",
                "evidence": [{"kind": "path_segment_equals_registered_name",
                              "note": "路径中有目录名逐字等于登记主体全称",
                              "source_ref": str(e.get("source_ref") or "")}],
                "unresolved_reason": "",
            }
        if name in fname:
            return {
                "entity": name, "entity_id": str(e.get("entity_id") or ""), "basis": FACT,
                "matched_by": "REGISTRY_DISPLAY_NAME",
                "evidence": [{"kind": "filename_contains_registered_name",
                              "note": "文件名内出现登记主体全称",
                              "source_ref": str(e.get("source_ref") or "")}],
                "unresolved_reason": "",
            }

    # 3) 登记别名出现在文件名里（INFERRED：别名匹配不等于主体确认）
    for alias_key, hit in aliases.items():
        if not alias_key or len(alias_key) < _MIN_FULLNAME_LEN:
            continue
        if alias_key in _norm(fname):
            return {
                "entity": str(hit.get("display_name") or ""),
                "entity_id": str(hit.get("entity_id") or ""),
                "basis": INFERRED,
                "matched_by": "REGISTRY_ALIAS",
                "evidence": [{"kind": "filename_contains_alias",
                              "note": "文件名内出现登记别名；别名匹配是推断，仍需核实",
                              "source_ref": str(hit.get("source") or "")}],
                "unresolved_reason": "",
            }

    # 4) 登记全称出现在**文件正文**开头（材料自述的法定名称）
    if body_text:
        head = str(body_text)[:_BODY_SCAN_CHARS]
        for e in regs:
            name = str(e.get("display_name") or "")
            if len(name) >= _MIN_FULLNAME_LEN and name in head:
                return {
                    "entity": name, "entity_id": str(e.get("entity_id") or ""), "basis": FACT,
                    "matched_by": "BODY_TEXT",
                    "evidence": [{"kind": "body_contains_registered_name",
                                  "note": "材料正文内出现登记主体全称",
                                  "source_ref": str(e.get("source_ref") or "")}],
                    "unresolved_reason": "",
                }

    # 5) 可信元数据字段
    for key in ("legal_entity", "entity_declared", "company_legal_name"):
        v = str(row.get(key) or "").strip()
        if not v:
            continue
        m = es.match_entity(v, entities or [], aliases)
        if m.get("matched"):
            return {
                "entity": str(m.get("display_name") or ""), "entity_id": str(m.get("entity_id") or ""),
                "basis": str(m.get("basis") or INFERRED), "matched_by": "TRUSTED_METADATA",
                "evidence": [{"kind": "trusted_metadata_field", "field": key,
                              "note": "可信元数据字段命中登记主体"}],
                "unresolved_reason": "",
            }

    # 6) 认不出 ⇒ 保留不确定
    reasons: list[str] = []
    if not regs:
        reasons.append("本库未登记任何权威主体 ⇒ 主体维度无法判定")
    else:
        reasons.append(f"文件名/正文/元数据均未命中 {len(regs)} 个登记主体中的任何一个")
    if row.get("relative_path"):
        reasons.append("材料目录不携带法人级信息（分类目录 ≠ 法人）")
    return {
        "entity": "", "entity_id": "", "basis": UNKNOWN, "matched_by": "UNRESOLVED",
        "evidence": [{"kind": "entity_unresolved", "note": "；".join(reasons)}],
        "unresolved_reason": "；".join(reasons),
    }


# ── 义务侧：主体范围判定 ─────────────────────────────────────────────────────

def resolve_obligation_entity_scope(ob: dict[str, Any] | None,
                                    declared_scope: dict[str, Any] | None = None,
                                    *,
                                    group_members: list[str] | None = None) -> dict[str, Any]:
    """判定一条义务的**主体范围**。

    返回::

        {"mode": "SINGLE|GROUP|UNRESOLVED", "entity": "..."（单主体时）,
         "entity_ids": [...], "basis": "FACT|INFERRED|UNKNOWN",
         "source": "OBLIGATION_NAMED|CONTRACT_SINGLE|CONTRACT_GROUP|NONE",
         "reason": "..."}

    ★ 义务**指名**了主体 ⇒ 该主体（``FACT``），不受契约影响。
    ★ 义务**没指名** ⇒ 看契约里的显式声明：
      - ``SINGLE_ENTITY`` ⇒ 唯一主体（``INFERRED``，来源 ``CONTRACT_SINGLE``）；
      - ``GROUP`` ⇒ 集团成员集合（``INFERRED``，来源 ``CONTRACT_GROUP``），
        **集合来自登记的集团结构**，不是「所有公司都算」；
      - 未声明 ⇒ ``UNRESOLVED``（**保留不确定状态**）。
    """
    ob = ob or {}
    scope = declared_scope or {}
    named = str(ob.get("entity") or "").strip()
    if named:
        return {"mode": "SINGLE", "entity": named, "entity_ids": [named],
                "basis": FACT, "source": "OBLIGATION_NAMED",
                "reason": "义务指名了主体"}
    mode = str(scope.get("scope_mode") or SCOPE_UNSCOPED)
    if mode == SCOPE_SINGLE:
        ids = [str(x) for x in (scope.get("entity_ids") or []) if str(x).strip()]
        if len(ids) == 1:
            return {"mode": "SINGLE", "entity": ids[0], "entity_ids": ids,
                    "basis": INFERRED, "source": "CONTRACT_SINGLE",
                    "reason": "契约声明本场考试只针对单一主体"}
        return {"mode": "UNRESOLVED", "entity": "", "entity_ids": [],
                "basis": UNKNOWN, "source": "NONE",
                "reason": (f"契约声明 SINGLE_ENTITY 但给了 {len(ids)} 个主体"
                           "⇒ 无法判定该义务针对哪个主体")}
    if mode == SCOPE_GROUP:
        members = [str(x) for x in (group_members or scope.get("entity_ids") or [])
                   if str(x).strip()]
        if not members:
            return {"mode": "UNRESOLVED", "entity": "", "entity_ids": [],
                    "basis": UNKNOWN, "source": "NONE",
                    "reason": "契约声明 GROUP 但未给出集团成员名单 ⇒ 无法判定"}
        return {"mode": "GROUP", "entity": "", "entity_ids": members,
                "basis": INFERRED, "source": "CONTRACT_GROUP",
                "reason": (f"契约声明本场考试覆盖集团（{len(members)} 个登记成员）"
                           "⇒ 义务未指名主体时，按集团范围判定")}
    return {"mode": "UNRESOLVED", "entity": "", "entity_ids": [],
            "basis": UNKNOWN, "source": "NONE",
            "reason": ("义务未指名主体，且考场契约未声明主体范围"
                       "（SINGLE_ENTITY / GROUP）⇒ 主体维度不可判定")}


def entity_matches(scope: dict[str, Any] | None, material_entity: str) -> bool | None:
    """材料主体是否满足义务的主体范围。

    返回 ``True`` / ``False`` / ``None``（**不可判定**）。

    ★ ``None`` ≠ ``False``：不可判定时**不得**当成「不符」（会把好材料错杀），
      也不得当成「相符」（会把坏材料放行）。
    """
    sc = scope or {}
    mode = str(sc.get("mode") or "UNRESOLVED")
    mat = str(material_entity or "").strip()
    if mode == "SINGLE":
        want = str(sc.get("entity") or "").strip()
        if not want or not mat:
            return None
        return mat == want
    if mode == "GROUP":
        ids = [str(x) for x in (sc.get("entity_ids") or [])]
        if not ids or not mat:
            return None
        return mat in ids
    return None
