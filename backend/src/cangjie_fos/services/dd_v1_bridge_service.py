"""WP-A1（G1/G2/G7）：**薄桥**——把入口 A 的规则链接进语义层。

## 为什么需要这个模块

A0 实测（真 trace，两入口零重叠）：

- **入口 A**（``tools/dd_team_channel.py run``）= 6 个服务的**纯规则链**：
  ``register_library → build_manifest → parse_pending_batch → build_cards_for_library
  → ingest_checklist → match_library``。
  它**从不调用** ``semantic`` / ``agent_result`` / ``agent_adapters``（计数全为 0）。
- **入口 B**（``tools/dd_v1_local_run.py run``）是**唯一**用到语义层/Agent 层的入口。

⇒ 两条链在语义/Agent 层**完全不相交**：规则链算出的缺口清单，语义层一次都没看过；
语义层产出的证据，规则链一次都没读过。**这就是「线没接好」的具体形态。**

本模块是那条**薄**桥：把入口 A 已经算出来的

- **义务**（requirement service；``doc_type`` 是 ``_DOC_TYPE_RULES`` 的 10 个**英文 key**）
- **材料认知卡**（card service；``entity`` / ``fiscal_period`` / ``purpose``）

翻译成语义层认的形状（``meta`` + ``obligations``），交给
``sem.build_semantic_packet`` / ``sem.run_semantic``，产出**只作建议**的语义证据
（``review_required=true``，每条建议带 ``file_id + sha256 + locator``）。

## 三条硬纪律

1. **建议不是判定。** 本模块**不参与、不改写** ``judge()`` 的硬判定，
   不改 ``verdict``，不改 ``deliverable``，不碰 HG1（披露）/ HG2（主体）/ 人工批准闸。
   桥接产物一律 ``advisory_only=true``。
2. **doc_type 必须是同一套 key 空间。** 语义层
   ``retrieve_minimal_evidence`` 用 ``m.get("doc_type") == ob["doc_type"]`` **精确过滤**；
   义务侧是英文 key ⇒ 桥接产出的 ``meta[].doc_type`` **也必须是同一套英文 key**。
   写成中文类型名或文件扩展名 ⇒ **证据池恒空 ⇒ 桥接等于没接**（A1 开工前的头号坑）。
3. **主体不得跨法人混桶。** 语义层按 ``m["entity"] == ob["entity"]`` **精确相等**取证据。
   桥接把材料归一到**权威主体名**（有登记时）或**卡片声明主体**（无登记时），
   并且**一条义务按主体分簇**——每簇的证据里只含该主体的材料，
   绝不把甲公司的材料和乙公司的材料放进同一份证据。

## 主体口径（两档，写进输出可追溯）

| 档 | 含义 | 来源 |
|---|---|---|
| ``AUTHORITY`` | 权威登记主体名 | ``dd_v1_entities``（``rq.resolve_entities``） |
| ``ALIAS_RESOLVED`` | 目录名命中**已登记别名** ⇒ 归一到权威主体名（**INFERRED**：别名登记是事实，「这份材料的主体就是该法人」仍待核验） | ``dd_v1_entity_aliases`` |
| ``CARD_INFERRED`` | 卡片主体**线索**：认知卡的 entity 字段，来源是**目录名**（``path_segment``，INFERRED），**不是法律事实** | ``card.entity`` |
| ``UNKNOWN`` | 无任何主体线索 | — |

⚠️ **诚实边界**：本仓认知卡的 ``entity`` 是从**相对路径的父目录名**推导的
（``dd_v1_card_service.build_card``，基础 INFERRED，证据标注 ``path_segment``），
**不是**从正文抽取的法律主体，也不是工商登记事实。
因此 ``CARD_INFERRED`` 档的语义证据**只能当候选提示**，
必须经人工核验主体归属后才可使用；桥接输出对此逐条标注。

主体为空时**证据池必然为空**：这不是 bug，是语义层的原设计
（「别的主体模型看不到」）。桥接**如实报空**，绝不为了凑出证据而跨主体取材料。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cangjie_fos.services import dd_v1_agent_adapters as ad
from cangjie_fos.services import dd_v1_agent_result_service as ar
from cangjie_fos.services import dd_v1_card_service as cs
# A2（G-A2-3 判据⑤ / G-A2-8）：主体归一（法定全称 / 已登记别名 / 未登记）。
from cangjie_fos.services import dd_v1_entity_service as es
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_requirement_service as rq
from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem

BRIDGE_VERSION = "a1-bridge-v1"

#: 义务侧 doc_type 的**唯一**取值空间。**复用** requirement service 的常量，不另抄一份。
DOC_TYPE_KEYS: tuple[str, ...] = tuple(k for k, _ in rq._DOC_TYPE_RULES)

#: 每条义务的主体分簇上限（防止材料主体很多时义务数爆炸）。超出部分在输出里如实记账。
MAX_ENTITY_CLUSTERS = 8

_YEAR_RE = re.compile(r"^\d{4}")
_ATTACH_RE = re.compile(r"附注|附件|附录|appendix", re.I)
#: 英文命名的附注文件（fixture 用 ``*_notes.txt``；``body``/``memo`` 不算附件）
_ATTACH_RE_EN = re.compile(r"(^|[_\-])notes([_\-.]|$)", re.I)


def _part_of(rel_path: str, file_name: str = "") -> str:
    """part 判定：**唯一**口径在认知卡层（``dd_v1_card_service.derive_part``）。

    ★ 桥接层**不再**自己写一份 part 规则 ⇒ 全仓只有一份 part 判定。
      英文 ``*_notes.txt`` 形态仍单独识别（fixture 约定），与中文口径合并。
    """
    from cangjie_fos.services import dd_v1_card_service as cs  # noqa: PLC0415
    part = cs.derive_part(rel_path, file_name)
    if part == cs.PART_MAIN and _ATTACH_RE_EN.search(rel_path or ""):
        return "附注"
    return part
_DRAFT_RE = re.compile(r"草稿|征求意见|draft", re.I)
#: 与入口 B 的 ``scaffold`` 保持一致的「当前有效」类材料（执照/章程无年度）。
#: ★ 取值空间来自 requirement service（``rq.CURRENT_DOC_TYPES``）—— **不另抄一份**。
_CURRENT_DOC_TYPES = rq.CURRENT_DOC_TYPES


# ─────────────────────────────────────────────────── 1. 材料侧：清单 + 认知卡 → meta

def resolve_material_doc_type(card: dict[str, Any] | None) -> str:
    """判定一份材料属于哪个 doc_type（**英文 key**）。

    两个信号取并集，**命中多个就判不出**（不猜）：

    1. ``rq.parse_doc_type`` —— requirement service 的权威正则（``_DOC_TYPE_RULES``）；
    2. ``ms._DOC_TYPE_PURPOSE_MAP`` 的逆映射 —— 认知卡 ``purpose``/``title`` 里的关键词，
       与规则链 ``doctype_ok`` 维度用的是同一张表，保证两侧口径一致。

    返回 ``""`` = **UNKNOWN**（不得拿扩展名或中文名占位）。
    """
    card = card or {}
    blob = " ".join([card.get("title") or "",
                     cs.purpose_text(card),
                     card.get("doc_type") or ""])
    hits: set[str] = set()
    key, _basis = rq.parse_doc_type(blob)
    if key:
        hits.add(key)
    for dt, keys in ms._DOC_TYPE_PURPOSE_MAP.items():
        if keys and any(k in blob for k in keys):
            hits.add(dt)
    return hits.pop() if len(hits) == 1 else ""


def _material_period(card: dict[str, Any], doc_type: str) -> str:
    """材料期间 → 语义层的期间空间（``YYYY`` / ``CURRENT`` / ``UNKNOWN``）。

    ★ **唯一模型（司仓 C-1 裁定）**：语义层 period 空间对「无年度口径类型」
      （``rq.CURRENT_DOC_TYPES``：执照 / 章程）**只有一个取值 CURRENT**
      ⇒ 该类**优先于**年份取 ``CURRENT``。
      年度信息**不丢**：仍留在 ``card.fiscal_period``（材料卡片）与 requirement 的
      ``period_from`` / ``period_to``（义务卡）里，只是不进语义层 period。

    ★ 为什么要改口径：材料侧「年份优先」+ 义务侧「恒 CURRENT」⇒ **反向假缺口**
      （执照材料 period=2022、执照义务 period=CURRENT ⇒ 池里有材料、可用候选为空）。
      两侧同源（都判 CURRENT）⇒ 口径一致，不再互相错位。
    """
    if doc_type in _CURRENT_DOC_TYPES:
        return "CURRENT"
    fp = str((card or {}).get("fiscal_period") or "").strip()
    m = _YEAR_RE.match(fp)
    if m:
        return m.group(0)
    return "UNKNOWN"


def _entity_blob(card: dict[str, Any], row: dict[str, Any]) -> str:
    """主体匹配用的文本：与规则链 ``evaluate_file`` 同口径（entity + rel_path + title）。"""
    card = card or {}
    return f"{card.get('entity','')} {row.get('rel_path','')} {card.get('title','')}"


def _match_authoritative(blob: str, entities: list[dict],
                         aliases: dict | None = None,
                         card_entity: str = "") -> tuple[str, bool, str]:
    """把材料归一到权威主体名。

    返回 ``(display_name, ambiguous, basis)``：

    - ``basis="AUTHORITY"``：法定全称**逐字命中**权威名单；
    - ``basis="ALIAS_RESOLVED"``：卡片的 entity **逐字**等于某个**已登记别名**
      ⇒ 归一到该主体的法定全称（**INFERRED**，不是 FACT）；
    - ``basis=""``：未命中 ⇒ 保留卡片原值（调用方记 ``CARD_INFERRED``）。

    ``ambiguous=True`` 表示**命中多个**权威主体（材料主体表述有歧义）
    ⇒ 不归一，保留卡片原值并记账（原口径不变）。
    """
    hits = [e["display_name"] for e in entities
            if e.get("display_name") and e["display_name"] in blob]
    if len(hits) == 1:
        return hits[0], False, "AUTHORITY"
    if len(hits) > 1:
        return "", True, ""
    # A2（G-A2-8）别名通道：**逐字**匹配已登记别名（不做子串匹配——
    # 目录名做子串匹配会把无关目录也认成主体）。
    if aliases and card_entity:
        hit = aliases.get(es.normalize_name(card_entity))
        if hit and hit.get("display_name"):
            return str(hit["display_name"]), False, "ALIAS_RESOLVED"
    return "", False, ""


def build_meta(library_id: str, *, db_path: Path | None = None) -> tuple[list[dict], dict]:
    """清单 + 认知卡 → 语义层 ``meta``。

    ``meta`` 是**整个材料库**（不是检索结果）：语义层自己按
    「同主体 + 同 doc_type」取每条义务的最小证据。
    """
    entities = rq.resolve_entities(library_id, "group_and_subs", db_path=db_path)
    # A2（G-A2-8）：别名表（库内登记 + 可选配置）。取不到就当没有别名
    # ⇒ 主体仍是「未归一」，**不因此放行**。
    try:
        aliases = es.alias_map(library_id, db_path=db_path)
    except Exception:  # noqa: BLE001
        aliases = {}
    meta: list[dict] = []
    ambiguous = 0
    unknown_doc_type = 0
    alias_resolved = 0
    # ★ 内容指纹（**完整 sha256**）：标准答案包按内容寻址，索引里必须有指纹，
    #   否则「标准答案材料在库里找不到」会被**误判**成真缺材料（实测踩过：
    #   meta 里没有 sha256 ⇒ 预检恒报 GOLD_FILES_MISSING_IN_LIBRARY）。
    #   ★ 指纹取**磁盘实算**的完整 64 位（与快照/证据层同一口径）；
    #     Manifest 里的 ``content_hash`` 是**截断到 32 位**的展示值，两种口径不能混用。
    lib_root = ""
    try:
        lib_row = mf.get_library(library_id, db_path=db_path) or {}
        lib_root = str(lib_row.get("root_path") or "")
    except Exception:  # noqa: BLE001
        lib_root = ""
    for row in mf.list_manifest(library_id, limit=100000, db_path=db_path):
        card = cs.get_card(row["file_id"], db_path=db_path) or {}
        dt = resolve_material_doc_type(card)
        if not dt:
            unknown_doc_type += 1
        card_entity = str(card.get("entity") or "").strip()
        ent, amb, ent_basis = _match_authoritative(
            _entity_blob(card, row), entities, aliases, card_entity)
        if amb:
            ambiguous += 1
        if ent_basis == "ALIAS_RESOLVED":
            alias_resolved += 1
        sha256 = ""
        if lib_root:
            try:
                fp = Path(lib_root) / str(row["rel_path"])
                if fp.is_file():
                    sha256 = ar.sha256_file(fp)
            except OSError:
                sha256 = ""
        meta.append({
            "file_id": row["file_id"],
            "relative_path": row["rel_path"],
            "sha256": sha256,
            "entity": ent or card_entity,
            "entity_basis": ent_basis or "CARD_INFERRED",
            "period": _material_period(card, dt),
            "doc_type": dt,
            # ★ part 口径**全仓只有一份**：复用认知卡层的 ``derive_part``
            #   （``dd_v1_card_service``）—— 桥接层与规则层同一口径，不分叉。
            "part": _part_of(row.get("rel_path") or "", row.get("file_name") or ""),
            "version_status": "DRAFT" if _DRAFT_RE.search(row.get("rel_path") or "") else "EFFECTIVE",
        })
    stats = {
        "materials": len(meta),
        "doc_type_unknown": unknown_doc_type,
        "entity_ambiguous": ambiguous,
        "entity_alias_resolved": alias_resolved,
        "entity_declared": sum(1 for m in meta if m["entity"]),
        "authoritative_entities": len(entities),
        "entity_aliases": len(aliases),
    }
    return meta, stats


# ─────────────────────────────────────────────────── 2. 义务侧：requirement → 语义义务

def _obligation_period(obl: dict[str, Any], doc_type: str) -> str:
    """义务期间 → 语义层期间空间（``YYYY`` / ``CURRENT`` / ``UNKNOWN``）。

    ★ **与 ``_material_period`` 同源**（司仓 C-1 裁定）：无年度口径类型
      （执照 / 章程）恒为 ``CURRENT``（**优先于**年份）⇒ 材料侧与义务侧同值，
      不会互相错位造成假缺口。年度信息仍留在 ``period_from`` / ``period_to``。
    """
    if doc_type in _CURRENT_DOC_TYPES:
        return "CURRENT"
    y_from, y_to = obl.get("period_from", 0), obl.get("period_to", 0)
    if y_from and y_to and int(y_from) == int(y_to):
        return str(int(y_from))
    if y_from and y_to:
        return f"{int(y_from)}-{int(y_to)}"
    return "UNKNOWN"


def _required_parts(obl: dict[str, Any]) -> list[str]:
    """附件要求 → ``required_parts``（规则提示据此判 PARTIAL，不是 Gold）。"""
    if obl.get("needs_attachments"):
        return ["正文", "附件"]
    return []


def build_semantic_obligations(
    obl_rows: list[dict],
    meta: list[dict],
    *,
    library_id: str,
    db_path: Path | None = None,
) -> tuple[list[dict], dict]:
    """requirement 义务 → 语义义务（**不重拆**，G7）。

    - ``obligations`` 显式传给 ``sem.build_semantic_packet`` ⇒ 语义层**不再用
      ``SPLIT_RE`` 二次切碎**（A1 的 G7）。
    - 一条义务按**主体分簇**：每簇一个语义义务，``obligation_id`` 加 ``@主体`` 后缀。
      这样每份证据里**只含同一主体的材料**，跨法人不混桶。
    """
    # 主体 → basis（AUTHORITY > ALIAS_RESOLVED > CARD_INFERRED）
    _BASIS_PRIORITY = {"AUTHORITY": 3, "ALIAS_RESOLVED": 2, "CARD_INFERRED": 1}
    entities_by_dt: dict[str, dict] = {}
    for m in meta:
        slot = entities_by_dt.setdefault(m["doc_type"], {})
        if not m["entity"]:
            continue
        b = m.get("entity_basis") or "CARD_INFERRED"
        cur = slot.get(m["entity"])
        if cur is None or _BASIS_PRIORITY.get(b, 0) > _BASIS_PRIORITY.get(cur, 0):
            slot[m["entity"]] = b

    out: list[dict] = []
    basis_tally = {"AUTHORITY": 0, "ALIAS_RESOLVED": 0, "CARD_INFERRED": 0, "UNKNOWN": 0}
    truncated = 0
    for obl in obl_rows:
        dt = str(obl.get("doc_type") or "").strip()
        # ★ 类型待判定只做**标记**：分簇口径**一字不改**（既有六态契约不许动）。
        #   标记随义务带到语义层，由 ``resolve_doc_type`` 开关决定要不要另开「类型判定池」。
        doc_type_unresolved = not dt
        scope = str(obl.get("entity_scope") or "").strip()
        auth = rq.resolve_entities(library_id, scope, obl.get("period_to") or None,
                                   db_path=db_path) if scope else []
        if auth:
            clusters = [(e["display_name"], "AUTHORITY") for e in auth if e.get("display_name")]
        else:
            # 义务侧沿用**材料侧归一后的主体名与 basis** ⇒ 两侧同一口径
            slot = entities_by_dt.get(dt) or {}
            clusters = [(e, slot.get(e) or "CARD_INFERRED") for e in sorted(slot)]
        if not clusters:
            clusters = [("", "UNKNOWN")]

        if len(clusters) > MAX_ENTITY_CLUSTERS:
            truncated += len(clusters) - MAX_ENTITY_CLUSTERS
            clusters = clusters[:MAX_ENTITY_CLUSTERS]

        multi = len(clusters) > 1
        for ent, basis in clusters:
            basis_tally[basis] += 1
            oid = obl["obligation_id"]
            out.append({
                "obligation_id": f"{oid}@{ent}" if multi else oid,
                "source_obligation_id": oid,
                "item_id": oid,
                "text": obl.get("obligation") or "",
                "entity": ent,
                "entity_basis": basis,
                "period": _obligation_period(obl, dt),
                "doc_type": dt,
                # ★ 类型待判定 ⇒ 语义层**不按类型筛证据**，由模型提出类型
                "doc_type_unresolved": doc_type_unresolved,
                "doc_type_source": "UNRESOLVED" if doc_type_unresolved else "RULE",
                "required_parts": _required_parts(obl),
                "doc_type_terms": rq.doc_type_search_terms(dt),
                "split_method": "REQUIREMENT_SERVICE",
                "source": "dd_v1_obligations",
            })
    stats = {
        "obligations_in": len(obl_rows),
        "obligations_out": len(out),
        "entity_basis": basis_tally,
        "entity_clusters_truncated": truncated,
    }
    return out, stats


# ─────────────────────────────────────────────────── 3. 桥接主流程

def bridge_library(
    library_id: str,
    *,
    material_root: Path | str | None = None,
    db_path: Path | None = None,
    adapter: Any = None,
    budget: Any = None,
    workdir: Path | None = None,
    allow_real_material: bool = False,
    resolve_doc_type: bool = False,
) -> dict[str, Any]:
    """把一个材料库的规则链结果桥接进语义层，返回**只作建议**的语义证据。

    ``adapter`` 为 None ⇒ **RULE_ONLY**（零外部调用、零费用、确定性）。
    ``resolve_doc_type``：**显式打开**「规则层解析不出材料类型 ⇒ 交给模型判定」这条通道
    （默认关闭 ⇒ 既有六态口径与既有契约一字不变）。
    ``adapter`` 给了 ⇒ 额外跑语义建议（``semantic_validation.accepted``），
    仍然只是建议，且**不改写**任何硬判定。
    """
    lib = mf.get_library(library_id, db_path=db_path)
    if not lib:
        raise FileNotFoundError(f"LIBRARY_NOT_FOUND:{library_id}")
    root = Path(material_root or lib["root_path"]).resolve()

    meta, meta_stats = build_meta(library_id, db_path=db_path)
    obl_rows = rq.list_obligations(library_id, db_path=db_path)
    obl_out, obl_stats = build_semantic_obligations(obl_rows, meta,
                                                    library_id=library_id, db_path=db_path)

    # 真实材料闸：仓库内合成 fixture 免开关，其他目录必须显式 --allow-real-material。
    fixture = sem._inside(root, Path(__file__).resolve().parents[3]
                          / "tests" / "fixtures")
    snapshot_dir = sem.local_material_snapshot(root, meta,
                                               allow_real=fixture or allow_real_material)

    mode = "RULE_ONLY"
    degrade_reason = "NO_ADAPTER_PROVIDED：未接适配器，只出确定性规则提示（零外部调用、零费用）"
    suggestions: list[dict] = []
    packet: dict[str, Any] = {}
    external_model_calls = 0

    if not meta or not obl_out:
        degrade_reason = "EMPTY_INPUT：材料库或义务为空，无可桥接内容"
        packet = {"obligations": obl_out, "evidence": {}, "unsplit_items": []}
    else:
        # **G7：显式传 obligations ⇒ 语义层不再用 SPLIT_RE 二次切碎**
        packet = sem.build_semantic_packet(snapshot_dir, meta, [],
                                           obligations=obl_out,
                                           resolve_doc_type=resolve_doc_type)
        if adapter is not None:
            rec = sem.run_semantic(adapter, snapshot_dir, meta, [], budget,
                                   workdir=workdir, obligations=obl_out,
                                   resolve_doc_type=resolve_doc_type)
            v = rec.get("semantic_validation") or {}
            suggestions = list(v.get("accepted") or [])
            external_model_calls = int(rec.get("calls_used", 0) or 0)
            mode = v.get("mode") or "RULE_ONLY"
            degrade_reason = v.get("degrade_reason")
            if mode != "AGENT_SUGGESTION":
                degrade_reason = (degrade_reason
                                  or "模型未产出可接受建议（确定性门槛拦截或适配器不可用）")
        else:
            mode = "RULE_ONLY"

    evidence = packet.get("evidence") or {}
    # ★「为什么没有候选」的结构化状态（语义层已算好，六态封闭枚举 + 过滤诊断）。
    #   桥接层**只透传、不另算**（不新造第二套原因表）⇒ 薄入口拿到的口径与语义层同一个。
    evidence_status = packet.get("evidence_status") or {}
    obligations_out: list[dict[str, Any]] = []
    for ob in obl_out:
        ev = evidence.get(ob["obligation_id"]) or []
        st = evidence_status.get(ob["obligation_id"]) or {}
        # 主体是否**权威核验过**：只有 AUTHORITY 档才算。
        # 非权威档（目录名线索 / 无线索）时，证据里的材料**归属哪一家法人没被确认**，
        # 逐条标注，别让人把「候选」当成「这一家的材料」。
        subject_verified = ob["entity_basis"] == "AUTHORITY"
        obligations_out.append({
            "obligation_id": ob["obligation_id"],
            "source_obligation_id": ob["source_obligation_id"],
            "entity": ob["entity"],
            "entity_basis": ob["entity_basis"],
            "subject_verified": subject_verified,
            "doc_type": ob["doc_type"],
            "doc_type_unresolved": bool(ob.get("doc_type_unresolved")),
            "doc_type_source": str(ob.get("doc_type_source") or ("UNRESOLVED" if not ob["doc_type"] else "RULE")),
            "period": ob["period"],
            "text": ob["text"],
            "required_parts": ob["required_parts"],
            "evidence_count": len(ev),
            "evidence": [{
                "file_id": e["file_id"],
                "sha256": e["sha256"],
                "locator": e["locator"],
                "relative_path": e["relative_path"],
                "entity": e["entity"],
                "subject_verified": subject_verified,
                "period": e["period"],
                "doc_type": e.get("doc_type"),
                "version_status": e.get("version_status"),
                "part": e.get("part"),
            } for e in ev],
            # ★ 候选为空时**必须说清为什么**：第三实参 ＝ 语义层算好的 no_candidate_reason
            #   （封闭六态）⇒ 规则提示里不再只剩一个笼统的 MISSING。
            #   候选**不为空**时该实参为 None ⇒ rule_hint 的既有行为逐字不变。
            "rule_hint": sem.rule_hint(ob, ev, st.get("no_candidate_reason")),
            # ★ 追加式：把结构化状态整体带出来（薄入口据此输出六态 ＋ 诊断）。
            "evidence_status": {
                "no_candidate_reason": st.get("no_candidate_reason"),
                "candidate_status": st.get("candidate_status"),
                "diagnostics": st.get("diagnostics") or {},
                # ★★ WP3-d：候选窗口**触顶**的读数（禁静默漏检）
                "candidate_cap": st.get("candidate_cap"),
                "candidates_total": st.get("candidates_total"),
                "candidates_used": st.get("candidates_used"),
                "candidate_truncated": st.get("candidate_truncated"),
                "truncated_candidate_count": st.get("truncated_candidate_count"),
                "candidate_cap_note": st.get("candidate_cap_note"),
            },
            "advisory_only": True,
            "review_required": True,
            "hard_verdict_touched": False,
        })

    nonempty = sum(1 for o in obligations_out if o["evidence_count"])
    total_ev = sum(o["evidence_count"] for o in obligations_out)

    # ── 告警区：必须显式说出来的东西，不许藏在计数里 ──
    warnings: list[str] = []
    basis = obl_stats.get("entity_basis") or {}
    if basis.get("ALIAS_RESOLVED"):
        warnings.append(
            f"{basis['ALIAS_RESOLVED']} 条义务的主体经**已登记别名**归一到权威主体名"
            "（INFERRED：别名登记是事实，「这份材料的主体就是该法人」仍待人工核验）；"
            "这些语义证据只能当候选提示，主体归属须人工核验后方可使用")
    if basis.get("CARD_INFERRED"):
        warnings.append(
            f"{basis['CARD_INFERRED']} 条义务的主体取自**卡片主体线索**"
            "（认知卡 entity 字段，来源是目录名 path_segment，INFERRED，**不是法律事实**）；"
            "这些语义证据只能当候选提示，主体归属须人工核验后方可使用")
    if basis.get("UNKNOWN"):
        warnings.append(
            f"{basis['UNKNOWN']} 条义务无任何主体线索（无权威登记、卡片也无主体）"
            "⇒ 语义层的「同主体」过滤退化为「同 doc_type」，"
            "**取到的证据可能横跨多个法人**（每条证据已标 subject_verified=false）；"
            "不得跨主体凑证据，也不得把候选当成「这一家的材料」")
    if obl_out and not nonempty:
        warnings.append("**证据池全空**：桥接未取到任何证据。"
                        "多半是 doc_type 两侧不在同一 key 空间，或主体口径不一致；"
                        "这是「线没接上」的信号，不得当作「材料不存在」")
    if obl_stats.get("entity_clusters_truncated"):
        warnings.append(
            f"{obl_stats['entity_clusters_truncated']} 个主体分簇因超过上限被截断"
            f"（MAX_ENTITY_CLUSTERS={MAX_ENTITY_CLUSTERS}）；被截断的主体未被覆盖，如实记账")
    # ★★ WP3-d：**候选窗口触顶**必须显式告警（禁静默漏检）。
    #   旧实现只把截断数记在 diagnostics 里 ⇒ 用户侧看到的是「一切正常」，
    #   而实际上还有 N 份候选**没看** ⇒ 那 N 份可能被当成「不存在」。
    #   ⇒ 形状与上面的主体分簇告警一致（同一仓内现成样板）。
    _trunc_total = 0
    _trunc_obl = 0
    for _o in obligations_out:
        _st = _o.get("evidence_status") or {}
        if _st.get("candidate_truncated"):
            _trunc_obl += 1
            _trunc_total += int(_st.get("truncated_candidate_count") or 0)
    if _trunc_obl:
        warnings.append(
            f"{_trunc_obl} 条义务的候选窗口已达上限，合计还有 {_trunc_total} 份候选未看"
            f"（MAX_FILES_PER_OBLIGATION={sem.MAX_FILES_PER_OBLIGATION}）；"
            f"未看部分**不得**当作「不存在」，如实记账")

    return {
        "bridge_version": BRIDGE_VERSION,
        "library_id": library_id,
        "material_root": str(root),
        "mode": mode,
        "degrade_reason": degrade_reason,
        "external_model_calls": external_model_calls,
        "advisory_only": True,
        "hard_verdict_touched": False,
        "key_space": {
            "doc_type_keys": list(DOC_TYPE_KEYS),
            "source": "dd_v1_requirement_service._DOC_TYPE_RULES（复用，未另抄）",
        },
        "counts": {
            **meta_stats,
            **obl_stats,
            "obligations_with_evidence": nonempty,
            "evidence_total": total_ev,
        },
        "warnings": warnings,
        "obligations": obligations_out,
        "suggestions": suggestions,
        "unsplit_items": packet.get("unsplit_items") or [],
    }
