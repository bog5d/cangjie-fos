"""DD-V1 多文件匹配与四维完整性覆盖（WP3 · M2 / M3）。

把「一条原子义务 → 多个证据文件」这件事做实，并把「找到一份就算完成」改掉。

## 直接对治既有缺陷

**D3（候选上限只是 prompt 文本）**
旧实现把「最多 2 个」写在提示词里（`dd_match_service.py:928`），解析处
（`:988-998`）没有任何代码切片，实际靠 LLM 自觉。
本模块把候选上限变成**显式可配置参数** ``candidate_cap``（默认 20，可按库调），
并做**高召回 → 确定性精排**两段式，**任何截断都记录被截断的数量**。

**D3（多文件聚合只按年份）**
旧 `_apply_multifile_aggregation:1348` 只按年份聚合，母子公司/多主体无任何建模。
本模块按**主体 × 期间 × 材料类型 × 必备附件**四维分别计算覆盖率，
**一个义务可以同时需要「母公司×合并 + 3 个子公司×单体」共 4 份以上材料**。

**D4（决策记忆无主体/版本/时效校验）**
记忆命中一律要过 `revalidate_memory_hit()`：主体、期间、版本、有效性、
适用范围五项任一不符即拒绝沿用。旧实现把 `last_institution` 写进去却从不读
（`dd_match_service.py:1478` vs `:1546`），属写而不读。

## 判定口径

一个义务的最终判定 = 四维覆盖 + 冲突/受限检查，**不是「有没有找到相关文件」**：

- ``MATCHED``    四维全覆盖且无冲突
- ``PARTIAL``    缺一部分（典型：主体缺 1 家，或期间缺 1 年）
- ``MISSING``    四维基本为零
- ``STALE``      找到材料但版本/期间不满足当前要求（如要求今年却是去年的）
- ``CONFLICT``   同一义务存在互相矛盾的多份材料（如两份不同主体的审计报告同号）
- ``UNCERTAIN``  证据不足以判定（主体范围无权威名单、相对年份未锚定等）
- ``RESTRICTED`` 材料敏感/受限/不可读/权限未知——**不得自动纳入可对外交付结果**
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_doc_type_service as dts
# A2（G-A2-8）：主体名归一（法定全称 / 已登记别名 / 未登记）。
# 依赖方向安全：entity_service 只依赖 manifest_service ⇒ 无循环导入。
from cangjie_fos.services import dd_v1_entity_service as es
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_policy_service as dpol
# A3（G-A3-3）：五维齐套组装层（主体/期间/类型/附件/份数）。
# ★ 只做「维度状态 + 缺哪一维」，**不重算**任何覆盖率 ⇒ 不产生第二份规则表。
from cangjie_fos.services import dd_v1_qc_service as qc
from cangjie_fos.services import dd_v1_requirement_service as rq

logger = logging.getLogger(__name__)

# ── 判定枚举 ────────────────────────────────────────────────────────────────
V_MATCHED = "MATCHED"
V_PARTIAL = "PARTIAL"
V_MISSING = "MISSING"
V_STALE = "STALE"
V_CONFLICT = "CONFLICT"
V_UNCERTAIN = "UNCERTAIN"
V_RESTRICTED = "RESTRICTED"

# ── 默认参数（全部可配，禁止硬编码「最多 2 份」）────────────────────────────
DEFAULT_CANDIDATE_CAP = int(
    __import__("os").getenv("CANGJIE_DD_V1_CANDIDATE_CAP", "20") or "20"
)
# 四维覆盖率阈值：低于 FULL 即判不完整。调高会让「找到一份就算完成」的毛病复发。
FULL_COVERAGE = 0.999

_DDL = """
CREATE TABLE IF NOT EXISTS dd_v1_matches (
    match_id      TEXT PRIMARY KEY,
    obligation_id TEXT NOT NULL,
    library_id    TEXT NOT NULL,
    file_id       TEXT NOT NULL,
    rank          INTEGER NOT NULL DEFAULT 0,
    score         REAL NOT NULL DEFAULT 0,
    entity_ok     INTEGER NOT NULL DEFAULT 0,
    period_ok     INTEGER NOT NULL DEFAULT 0,
    doctype_ok    INTEGER NOT NULL DEFAULT 0,
    attachment_ok INTEGER NOT NULL DEFAULT 0,
    seal_ok       INTEGER NOT NULL DEFAULT 0,
    deliverable   INTEGER NOT NULL DEFAULT 1,
    verdict       TEXT NOT NULL DEFAULT '',
    evidence      TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    UNIQUE (obligation_id, file_id)
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_match_obl ON dd_v1_matches(obligation_id);
CREATE INDEX IF NOT EXISTS idx_dd_v1_match_lib ON dd_v1_matches(library_id);

CREATE TABLE IF NOT EXISTS dd_v1_obligation_status (
    obligation_id  TEXT PRIMARY KEY,
    library_id     TEXT NOT NULL,
    verdict        TEXT NOT NULL,
    entity_cov     REAL NOT NULL DEFAULT 0,
    period_cov     REAL NOT NULL DEFAULT 0,
    doctype_cov    REAL NOT NULL DEFAULT 0,
    attach_cov     REAL NOT NULL DEFAULT 0,
    need_entities  INTEGER NOT NULL DEFAULT 0,
    need_periods   INTEGER NOT NULL DEFAULT 0,
    missing_detail TEXT NOT NULL DEFAULT '',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    capped         INTEGER NOT NULL DEFAULT 0,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_status_lib ON dd_v1_obligation_status(library_id);
"""

# 认知卡 purpose 关键词 → 义务 doc_type 的映射（确定性，不猜）
_DOC_TYPE_PURPOSE_MAP = {
    "audit_report": ("审计",),
    "financial_statement": ("财务", "利润", "资产负债", "现金流"),
    "tax": ("纳税", "税务", "完税"),
    "license": ("营业执照", "主体存续"),
    "charter": ("章程", "治理"),
    "capital": ("验资", "出资"),
    "resolution": ("决议", "决策记录"),
    "ip": ("知识产权", "专利", "商标"),
    "labor": ("用工合规",),
    "contract": (),
}


def _ensure_schema(conn) -> None:
    conn.executescript(_DDL)
    # 异常检测结果（STALE/CONFLICT）需要持久化，供审核包与组包读取。
    # 用 ALTER 而非改 CREATE，保证既有库平滑升级。
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(dd_v1_obligation_status)")}
    if "anomalies_json" not in cols:
        conn.execute("ALTER TABLE dd_v1_obligation_status ADD COLUMN anomalies_json TEXT NOT NULL DEFAULT '{}'")
    # ★ A3（G-A3-1）：义务表的**份数列**也要平滑升级。
    #   不做这一步 ⇒ **既有库**上 `SELECT * FROM dd_v1_obligations` 取不到
    #   `expected_count` ⇒ 判定层拿到 None ⇒ 被当成「份数不可判定」
    #   ⇒ **全部义务误判 UNCERTAIN**（A2 封版的库直接踩坑）。
    # ⇒ 复用 requirement_service 的**唯一**列补齐实现（不另写第二份列清单）。
    rq._ensure_schema(conn)
    conn.commit()


def _conn(db_path: Path | None = None):
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    return conn


# ── 单文件对单义务的维度判定 ────────────────────────────────────────────────
def _alias_map_for(library_id: str, db_path: Path | None = None) -> dict:
    """取该库的别名表（库内登记 + 可选配置文件）。取不到就当没有别名。

    **取不到别名 ≠ 放行**：主体匹配不上仍然是「未登记」⇒ UNCERTAIN。

    ★★ **必须传 `db_path`**（2026-10-22 修 · 监工第 38 轮定位，司仓独立复现）：
    不传 ⇒ `mf._connect(None)` ⇒ 打开**默认库**而不是本次运行的数据目录
    ⇒ **别名表读出来是空的** ⇒ 别名归一**永远失配**
    ⇒ 目录名/简称类的卡片永远判「主体未登记」⇒ 主体维度不可判定
    ⇒ 明明齐套的义务被判 PARTIAL。
    """
    lib = str(library_id or "").strip()
    if not lib:
        return {}
    try:
        # ★ F1 产品侧守卫：**DIRECTORY 型别名（材料分类目录）不参与主体归一**
        #   ⇒ 既不算 entity_ok，也不参与冲突分桶
        #   ⇒ 落「主体未登记」桶 ⇒ **不产生假 CONFLICT**，同时**照常留痕**。
        return es.alias_map(lib, db_path, include_directory=False)
    except Exception:  # noqa: BLE001
        return {}


def _match_subject(value: str, scope_entities: list, aliases: dict) -> dict:
    """主体线索 → 权威主体（**含别名归一**）。

    - 与登记全称逐字相等 ⇒ ``FACT``；
    - 与已登记别名相等 ⇒ ``ALIAS``/``INFERRED``；
    - 都不匹配 ⇒ 未登记（**不猜**）。
    - 归一后的主体**必须在本义务的主体范围内**，否则不算命中。
    """
    m = es.match_entity(value, list(scope_entities or []), aliases)
    if m.get("matched") and m.get("entity_id"):
        ids = {str(e.get("entity_id") or "") for e in (scope_entities or [])}
        if m["entity_id"] not in ids:
            m = dict(m, matched=False, evidence=list(m.get("evidence") or []) + [{
                "kind": "subject_out_of_scope",
                "note": "别名归一后的主体不在本义务要求的主体范围内",
            }])
    return m


def evaluate_file(
    obligation: dict,
    card: dict | None,
    manifest_row: dict | None,
    need_entities: list[dict],
    alias_map: dict | None = None,
) -> dict:
    """算出一份材料对一个义务的四维命中情况。**确定性，不含 LLM。**

    ★ `alias_map`：**由调用方一次取好传进来**（`None` ⇒ 自己按 `db_path` 取）
    —— 一是**避免每条候选重复读库**，二是**保证与判定层用同一份别名表**
    （避免「桶键一份、覆盖一份」这种两套口径）。
    """
    ent_ok = per_ok = doc_ok = seal_ok = 0

    # 主体维度
    if need_entities and card:
        names = {e["display_name"] for e in need_entities}
        blob = f"{card.get('entity','')} {card.get('rel_path','')} {card.get('title','')}"
        ent_ok = 1 if any(n and n in blob for n in names) else 0
        if not ent_ok:
            # A2（G-A2-8）别名归一：卡片的 entity 常是**材料库目录名/简称**，
            # 与权威名单里的法定全称永不相等 ⇒ 登记过别名才算命中。
            _m = _match_subject(
                card.get("entity") or "", need_entities,
                alias_map if alias_map is not None else _alias_map_for(
                    (manifest_row or {}).get("library_id") or ""))
            ent_ok = 1 if _m.get("matched") else 0
    elif not need_entities:
        # 义务没要求特定主体范围（如「贵司」）→ 主体维度不构成门槛
        ent_ok = 1

    # 期间维度
    y_from, y_to = obligation.get("period_from", 0), obligation.get("period_to", 0)
    if y_from and y_to:
        pv = card.get("fiscal_period") if card else ""
        per_ok = 1 if pv and y_from <= int(pv) <= y_to else 0
    else:
        per_ok = 1   # 期间未锚定 → 由 obligation_status 判 UNCERTAIN，不在此扣分

    # ★ A2（G-A2-10 · 10a）：索引/目录件**不是材料** ⇒ 类型维度不算命中、不可交付。
    _is_index = False
    if manifest_row is not None:
        _fname = manifest_row.get("file_name") or Path(str(manifest_row.get("rel_path") or "")).name
        _is_index = dts.is_index_artifact(_fname)
    # 注：索引件的**处置**（记原因 + 不可交付）在下面 ``reasons`` 初始化之后做
    #     —— 这里只做**检测**（``doc_ok`` 需要它）。

    # 材料类型维度
    dt = obligation.get("doc_type") or ""
    if _is_index:
        doc_ok = 0
    elif dt:
        # WP-A1 修正：**必须走结构化字段**（`cs.purpose_text`）。
        # 卡片 `purpose` 列存的是 JSON 字符串，原写法 `" ".join(card.get("purpose") or [])`
        # 把字符串**逐字符**加空格拼接 ⇒ 中文关键词永远匹配不上 ⇒ doctype_ok 恒 0
        # ⇒ doctype_cov 一票否决 ⇒ MATCHED 永远出不来（详见 cs.multi_text 的说明）。
        purposes = cs.purpose_text(card)
        keys = _DOC_TYPE_PURPOSE_MAP.get(dt)
        doc_ok = 1 if (card and ((not keys) or any(k in purposes or k in card.get("title", "") for k in keys))) else 0
    else:
        doc_ok = 1

    # 签章维度（认知卡里 seal_status 恒 UNKNOWN → 这里必然不满足，属已知缺口）
    seal_req = obligation.get("seal_required") or ""
    if seal_req:
        seal_ok = 1 if (card and card.get("seal_status") == seal_req) else 0
    else:
        seal_ok = 1

    # 可交付性：不可读/解析失败/披露不可外发 → 不得自动纳入对外交付
    deliverable = 1
    reasons = []
    if _is_index:
        reasons.append("索引/目录件，不是材料")
        deliverable = 0
    # 默认按最严：无卡片 / 无策略时一律不可外发，**不允许「没信息」等于「没问题」**
    disclosure = dpol.PolicyDecision().to_dict()
    if manifest_row is not None:
        if manifest_row.get("parse_status") not in (mf.PARSE_OK, mf.PARSE_PARTIAL):
            deliverable = 0
            reasons.append(f"解析状态={manifest_row.get('parse_status')}")
    if card is not None:
        # 披露判定走**版本化策略**（dd_v1_policy_service），不再二值判定。
        # 原实现只要 sensitivity 非空就放行 —— 填「secret」也能过，
        # 等于**填了等级比留空更危险**。现在由策略给出级别→可外发映射，
        # 未知等级按「不可判定」处理，一律不可外发。
        #
        # ★ G5（PR #81 登记缺口的修复面）：披露闸的输入是**材料自己的类型**，
        #   不再是「整段的类型归属」（= 义务侧的 doc_type）。
        #   过去：一条清单项若横跨多类材料（例：「营业执照与2024年度审计报告」），
        #   整段只落**一个**类型 ⇒ 段内**可外发类**（执照）的材料被按另一类判定
        #   ⇒ 被披露闸拦下 ⇒ 授权组包取不到它（G5 的成因环 + 后果环）。
        #   现在：按材料自己命中的**全部**类型判定 ⇒ 可外发类材料不再被连坐；
        #   反向也一并变严：段内**受限类**材料不再被段的「可外发类」类型放过
        #   （它的等级由自己的类型派生，类型闸逐类判）。
        #   材料自身类型认不出（UNKNOWN）⇒ 退回段的类型（沿用既有口径，
        #   登记为遗留缺口 G5-bis，不在本次修复范围内）。
        pol = dpol.load_policy()
        _own_types = cs.doc_types_key(card)
        _gate_types = _own_types or [obligation.get("doc_type") or ""]
        # ★ P0-3：业务负责人对**这一份**材料的**逐份书面授权**
        #   （策略文件登记的「豁免需业务负责人逐份书面授权」这条业务规则的落地）。
        #   ★ 授权**只**替代**类型闸**；等级闸 / 规则闸 / requires_review 全部照旧
        #   ⇒ 授权**不会**让「敏感等级未知」的材料变成可外发。
        _auth = cs.external_send_authorization(card)
        _authorized = str(_auth.get("value") or "").upper() == "GRANTED"
        dec = dpol.evaluate(pol, card.get("sensitivity") or "",
                             doc_type=_gate_types,
                             entity=card.get("entity") or "",
                             authorized=_authorized)
        disclosure = dec.to_dict()
        disclosure["external_send_authorized"] = _authorized
        disclosure["authorization_granted_by"] = _auth.get("granted_by") or ""
        disclosure["authorization_reason"] = _auth.get("reason") or ""
        if not dec.externally_sendable:
            deliverable = 0
            reasons.append(f"披露不可外发（等级={dec.level}）：{dec.reason}")
    else:
        deliverable = 0
        reasons.append("无材料认知卡，按不可判定处理，不得自动纳入对外交付")

    # 必备附件维度：读**已解析的** fields.related_files。
    # 注意不能直接读卡片表的 related_files 列——那是 json.dumps 的字符串，
    # `json.dumps([])` 得到 "[]"，是真值，会让本维度恒判定为满足（假阳性）。
    if obligation.get("needs_attachments"):
        rel = []
        if card:
            fields = card.get("fields") or {}
            raw = (fields.get("related_files") or {}).get("value") or []
            rel = raw if isinstance(raw, list) else []
        attachment_ok = 1 if rel else 0
    else:
        attachment_ok = 1

    return {
        "entity_ok": ent_ok, "period_ok": per_ok, "doctype_ok": doc_ok,
        "seal_ok": seal_ok, "attachment_ok": attachment_ok,
        "deliverable": deliverable, "reasons": reasons,
        "disclosure": disclosure,
    }


# ── P0-3：披露**四方归因**（谁拦的、为什么拦）──────────────────────────────
#: 披露判定的**四个维度**（四方）。归因只在这四个维度里选，**不新增第五个**。
DISCLOSURE_DIMENSIONS = ("doc_type", "sensitivity", "parse_status", "policy")

#: 拦截的**性质**（区分「按设计被拦」与「因误分类被误拦」）
#:
#: - ``按设计``：分类**正确**、策略**就是要拦**（例：章程 = RESTRICTED）
#:   ⇒ 改它要改**业务授权**，不是改代码、也不是改授权清单；
#: - ``误分类``：材料**认不出类型**（或类型认错）⇒ 判据本身失效，
#:   正解是**人工补定类型**（``set_human_override``）或补**业务授权**
#:   （``grant_external_send``），**不是**放宽放行清单；
#: - ``等级不可判定`` / ``读取失败``：材料**本身**没定级或读不出来
#:   ⇒ fail-closed，继续默认拒绝（可人工补级后放行）。
BLOCK_KIND_AS_DESIGNED = "按设计被拦"
BLOCK_KIND_MISCLASSIFIED = "误分类被拦"
BLOCK_KIND_LEVEL_UNKNOWN = "敏感等级不可判定"
BLOCK_KIND_UNREADABLE = "读取失败"
BLOCK_KIND_NO_CARD = "无认知卡"
BLOCK_KIND_OK = ""


def diagnose_disclosure(
    card: dict | None,
    manifest_row: dict | None = None,
    obligation: dict | None = None,
) -> dict:
    """披露**四方归因**：① 材料类型 ② 敏感等级 ③ 读取状态 ④ 披露规则。

    返回一份**可审计**的归因结论：

    - ``blocked_by`` ＝ 到底是**哪一方**拦的（``doc_type`` / ``sensitivity`` /
      ``parse_status`` / ``policy`` / ``""``）；
    - ``blocked_kind`` ＝ 拦的**性质**（按设计 / 误分类 / 等级不可判定 / 读取失败）；
    - ``four_dimensions`` ＝ 四方各自的读数（**原样**留证，不加工）。

    ★ 用途：把「正确候选被披露策略拦下」这类投诉**变成可核的四方读数**，
      而不是靠猜（猜错就会去改不该改的东西——比如去动放行清单）。
    """
    obl = obligation or {}
    pol = dpol.load_policy()
    if card is None:
        return {
            "file_id": (manifest_row or {}).get("file_id") or "",
            "rel_path": (manifest_row or {}).get("rel_path") or "",
            "blocked_by": "policy",
            "blocked_kind": BLOCK_KIND_NO_CARD,
            "blocked_reason": "无材料认知卡，按不可判定处理，不得自动纳入对外交付",
            "deliverable": False,
            "four_dimensions": {
                "doc_type": {"types": [], "basis": "UNKNOWN",
                             "note": "无认知卡"},
                "sensitivity": {"level": "", "basis": "UNKNOWN",
                                "note": "无认知卡 ⇒ 等级不可判定"},
                "parse_status": {"value": (manifest_row or {}).get("parse_status") or "",
                                 "note": "无认知卡"},
                "policy": {"version": pol.version, "loaded": pol.loaded,
                           "sendable_doc_types": list(pol.sendable_doc_types or []),
                           "note": "无认知卡 ⇒ 按最严处理"},
            },
            "external_send_authorized": False,
        }

    own_types = list(cs.doc_types_key(card) or [])
    gate_types = own_types or [str(obl.get("doc_type") or "")]
    sensitivity = str(card.get("sensitivity") or "")
    parse_status = str((manifest_row or {}).get("parse_status") or "")
    auth = cs.external_send_authorization(card)
    authorized = str(auth.get("value") or "").upper() == "GRANTED"
    dec = dpol.evaluate(pol, sensitivity, doc_type=gate_types,
                         entity=card.get("entity") or "", authorized=authorized)

    blocked_by = ""
    blocked_kind = BLOCK_KIND_OK
    reason = ""
    _level_spec = (pol.levels or {}).get(str(sensitivity or "").strip().upper(), {})
    _sens_node = card.get("sensitivity")
    _sens_prov = (_sens_node or {}).get("provenance") \
        if isinstance(_sens_node, dict) else None
    if _sens_prov is None:
        _f = card.get("fields") or {}
        _sn = (_f.get("sensitivity") or {}) if isinstance(_f, dict) else {}
        _sens_prov = _sn.get("provenance") if isinstance(_sn, dict) else None
    if parse_status and parse_status not in (mf.PARSE_OK, mf.PARSE_PARTIAL):
        blocked_by = "parse_status"
        blocked_kind = BLOCK_KIND_UNREADABLE
        reason = f"解析状态={parse_status}"
    elif dec.externally_sendable:
        # 四方都过了（可能含逐份书面授权）⇒ 没有被拦
        blocked_by = ""
        blocked_kind = BLOCK_KIND_OK
        reason = dec.reason
    elif not own_types:
        # ★ 归因到**根因**：类型**认不出** ⇒ 等级留空只是它的**后果**
        #   ⇒ 「谁拦的」答「材料类型」⇒ 正解是补类型 / 补授权，**不是**放宽。
        blocked_by = "doc_type"
        blocked_kind = BLOCK_KIND_MISCLASSIFIED
        reason = (f"材料类型认不出（认知卡 doc_type 空）⇒ 敏感等级无法按类型判定"
                  f"（留空 ⇒ 不可判定）⇒ 按最严处理，不得外发")
    elif not sensitivity:
        blocked_by = "sensitivity"
        blocked_kind = BLOCK_KIND_LEVEL_UNKNOWN
        reason = "敏感等级为空 = 不可判定，按安全默认处理；不得因留空就放行"
    elif not _level_spec.get("externally_sendable", False):
        # 等级**认得出**、但该级别在策略里**不可外发**
        # ★ 归因要看等级的**出处**：
        #   - 机器从**类型**推出来的（INFERRED）⇒ 根因是**类型**（收紧设计）
        #   - 人工自己定的（FACT）⇒ 根因是**等级**（人的决定）
        if _sens_prov == cs.FACT:
            blocked_by = "sensitivity"
            blocked_kind = BLOCK_KIND_AS_DESIGNED
            reason = (f"敏感等级={sensitivity}（人工补定）在策略里不可外发"
                      f"（externally_sendable=false）⇒ 按设计不放行")
        else:
            blocked_by = "policy"
            blocked_kind = BLOCK_KIND_AS_DESIGNED
            reason = (f"材料类型 {own_types} 属收紧类型 ⇒ 敏感等级按策略默认映射为 "
                      f"{sensitivity}（该级别不可外发）⇒ 按设计不放行")
    else:
        # 等级可外发、类型认得出 ⇒ 是**类型闸**（收紧设计）拦的
        blocked_by = "policy"
        blocked_kind = BLOCK_KIND_AS_DESIGNED
        reason = dec.reason

    return {
        "file_id": (manifest_row or {}).get("file_id") or card.get("file_id") or "",
        "rel_path": card.get("rel_path") or (manifest_row or {}).get("rel_path") or "",
        "blocked_by": blocked_by,
        "blocked_kind": blocked_kind,
        "blocked_reason": reason or dec.reason,
        "deliverable": bool(dec.externally_sendable)
        and not (parse_status and parse_status not in (mf.PARSE_OK, mf.PARSE_PARTIAL)),
        "policy_version": dec.policy_version,
        "external_send_authorized": authorized,
        "authorization_granted_by": auth.get("granted_by") or "",
        "authorization_reason": auth.get("reason") or "",
        "four_dimensions": {
            "doc_type": {
                "types": own_types,
                "gate_types": gate_types,
                "basis": (card.get("doc_type") or {}).get("provenance")
                if isinstance(card.get("doc_type"), dict) else "UNKNOWN",
                "note": ("材料自己的类型" if own_types
                         else "材料类型认不出 ⇒ 退回义务侧类型（遗留缺口 G5-bis）"),
            },
            "sensitivity": {
                "level": sensitivity,
                "basis": _sens_prov or "UNKNOWN",
                "note": ("等级由类型默认映射或人工补定" if sensitivity
                         else ("等级留空是「类型认不出」的**后果**（根因在类型那一维）"
                               if not own_types
                               else "等级留空 ⇒ 不可判定 ⇒ 不可外发（fail-closed）")),
            },
            "parse_status": {
                "value": parse_status,
                "note": ("可读" if parse_status in (mf.PARSE_OK, mf.PARSE_PARTIAL)
                         else "不可读/解析失败 ⇒ 不可交付"),
            },
            "policy": {
                "version": dec.policy_version,
                "loaded": pol.loaded,
                "level": dec.level,
                "externally_sendable": dec.externally_sendable,
                "requires_review": dec.requires_review,
                "sendable_doc_types": list(pol.sendable_doc_types or []),
                "matched_rule": dec.matched_rule,
                "note": dec.reason,
            },
        },
    }


# ── 高召回 + 确定性精排 ────────────────────────────────────────────────────
def _recall_candidates(
    obligation: dict, library_id: str, cap: int, db_path: Path | None
) -> tuple[list[dict], bool, list[str]]:
    """高召回：**doc_type 词优先，义务原文词兜底**。

    WP7 验收发现的缺陷（原实现只取 doc_type）：大量尽调要求识别不出
    ``doc_type``（如「请说明实际控制人及股权结构」），于是 ``terms=[]``，
    **一次 FTS 查询都不发** → 恒 0 召回 → 恒判 MISSING。
    索引层是好的（材料在库里、FTS 也在），只是没去查——
    输出的是**自信的错误答案**，用户会照着去追不存在的缺口。

    返回 ``(候选, 是否被截断, 实际使用的检索词)``，第三项便于复核。
    """
    dt = rq.doc_type_search_terms(obligation.get("doc_type") or "")
    tx = rq.text_search_terms(obligation.get("obligation") or "")
    # doc_type 词更具体，优先；原文词兜底。两者都没有时不去瞎猜——
    # 宁可少召回交给 UNCERTAIN，也不要发一个注定 0 命中的查询。
    terms = dt + [t for t in tx if t not in dt]

    hits: dict[str, float] = {}
    for rank, t in enumerate(terms):
        # **召回阶段用宽松二元组检索，不用短语查询。**
        # 短语查询要求二元组相邻，「财务报告」就匹配不到写「财务报表/财务数据」
        # 的真实材料——系统性过严，把明明存在的材料判成不存在。
        # 宁可多召回：精度由后续主体/期间/类型/附件四维判定收窄。
        for h in cs.search_materials_loose(library_id, t, limit=cap * 2,
                                           db_path=db_path):
            prior = 1.0 - (rank * 0.01)   # doc_type 词优先占位
            cur = hits.get(h["file_id"])
            cand = h["score"] * prior
            if cur is None or cand < cur:
                hits[h["file_id"]] = cand
    ordered = sorted(hits.items(), key=lambda kv: kv[1])[:cap]
    return ([{"file_id": fid, "score": sc} for fid, sc in ordered],
            len(hits) > cap, terms)


def match_obligation(
    library_id: str,
    obligation_id: str,
    candidate_cap: int = DEFAULT_CANDIDATE_CAP,
    db_path: Path | None = None,
) -> dict:
    """对一条原子义务做匹配并给出最终判定。"""
    conn = _conn(db_path)
    obl = conn.execute(
        "SELECT * FROM dd_v1_obligations WHERE obligation_id=?", (obligation_id,)
    ).fetchone()
    if obl is None:
        raise KeyError(f"义务不存在：{obligation_id}")
    obl = dict(obl)

    need_entities = rq.resolve_entities(
        library_id, obl.get("entity_scope") or "", obl.get("period_to") or None, db_path)
    # WP-A1（G6 v2）**全量权威主体名单**（不按义务范围过滤）——
    # 冲突分桶要回答的是「这个主体是不是登记过的法人」，不是
    # 「这条义务要求哪几个主体」。义务范围为空时 need_entities 也是空的，
    # 但权威名单里可能有登记主体 ⇒ 两件事必须分开取。
    authority_entities = rq.resolve_entities(
        library_id, "group_and_subs", obl.get("period_to") or None, db_path)

    # ★ A2（G-A2-12 · F4 配套）：**`need_entities` 不得空洞**。
    #   义务**未指名**主体、而本库**恰好登记了一个**主体时，
    #   主体维度**不是空洞的** —— 库里唯一的主体就是本条要求的**隐含对象**
    #   （义务没说给谁，库里只有一个人）⇒ 把它作为隐含要求纳入 `need_entities`。
    #   ⇒ `ent_cov` 才不是「无约束的 1.0」，MATCHED 也才有主体维度的实证。
    # ★ 义务指名了主体但**没登记上** ⇒ **不回落**（仍然 need_entities=0，不猜）。
    # ★ 库里 ≥2 个主体 ⇒ 不补（G-A2-11 闸：主体维度不可判定，不得 MATCHED/PARTIAL）。
    if (not need_entities
            and not (obl.get("entity_scope") or "").strip()
            and len(authority_entities or []) == 1):
        need_entities = list(authority_entities)

    # 召回：doc_type 词优先 + 义务原文词兜底；两者皆空说明**没真正查过**
    candidates, capped, used_terms = _recall_candidates(
        obl, library_id, candidate_cap, db_path)

    # ★★ **别名表一次取、往下传**（2026-10-22 修 · 监工第 38 轮定位）：
    #   ① 必须在**本库**上取（`library_id`），且**必须带 `db_path`**
    #      ⇒ 否则读的是**默认库**的别名表（空的）⇒ 别名归一永远失配；
    #   ② 取一次给三个下游用 ⇒ 省掉每条义务 3 次库读，
    #      且**保证「桶键 / 覆盖 / 归一」三处用同一份** ⇒ 不产生第二套口径。
    _alias_map = _alias_map_for(library_id, db_path)

    results = []
    for c in candidates:
        card = cs.get_card(c["file_id"], db_path=db_path)
        mrow = conn.execute(
            "SELECT * FROM dd_v1_manifest WHERE file_id=?", (c["file_id"],)
        ).fetchone()
        ev = evaluate_file(obl, card, dict(mrow) if mrow else None, need_entities,
                           alias_map=_alias_map)
        score = (ev["entity_ok"] + ev["period_ok"] + ev["doctype_ok"] + ev["seal_ok"]) / 4.0
        results.append({**c, "card": card, "manifest": dict(mrow) if mrow else None,
                        "ev": ev, "score": round(score, 4)})

    # ★ A2（G-A2-12 · 相关性闸）：给每条候选打「**是不是本义务要求的那一份**」的标记。
    #   降级闸（主体未登记 / 类型认不出）只看标记为 True 的那些候选 ——
    #   与本义务要求的类型**确定不同**的材料，压根不是那一类，
    #   不该把结论打成 UNCERTAIN。
    #   ★ 留痕字段（unknown_entities / unknown_types）与冲突判定口径**一字不改**。
    _obl_dt = str(obl.get("doc_type") or "").strip()
    _obl_terms = rq.doc_type_search_terms(_obl_dt) if _obl_dt else []
    _textmap: dict[str, str] = {}
    try:
        for _row in conn.execute("SELECT file_id, text FROM dd_v1_text_cache"):
            _textmap[str(_row["file_id"])] = str(_row["text"] or "")
    except Exception:  # noqa: BLE001
        _textmap = {}
    for _r in results:
        _r["_may_be_required"] = _may_be_required_type(
            _r, _obl_dt, _obl_terms, _textmap)

    results.sort(key=lambda r: -r["score"])
    for i, r in enumerate(results, 1):
        r["rank"] = i

    # ★ A2（G-A2-11 · 11c）：主体证据闸的输入。
    #   ① 义务指名了主体但**没登记上** ⇒ need_entities 为空而 entity_scope 非空
    #      （judge 里已有对应分支，文案已脱敏）；
    #   ② 义务**没指名**主体，而**本库登记了多于一个**主体
    #      ⇒ 主体维度不可判定 ⇒ 不得产出 MATCHED/PARTIAL。
    _scope = str(obl.get("entity_scope") or "")
    _entity_unverifiable = bool(
        (not _scope) and len(authority_entities or []) > 1)

    status = judge(obl, results, need_entities, capped, used_terms,
                   authority_entities, entity_unverifiable=_entity_unverifiable,
                   alias_map=_alias_map)
    _persist(conn, library_id, obligation_id, obl, results, status)
    return status


def _blocking_info(rows: list[dict], note: str) -> list[dict]:
    """把「阻断集」整理成与留痕字段同构的结构（计数 + 相对路径 + 说明）。"""
    if not rows:
        return []
    rels = sorted(((r.get("card") or {}).get("rel_path")
                    or (r.get("manifest") or {}).get("rel_path") or "")
                   for r in rows)
    return [{"count": len(rows), "rel_paths": rels, "note": note}]


def _related_of(r: dict) -> list[str]:
    """取卡片里已解析的 related_files（不是 JSON 字符串列）。"""
    fields = (r.get("card") or {}).get("fields") or {}
    raw = (fields.get("related_files") or {}).get("value") or []
    return raw if isinstance(raw, list) else []


def _is_attachment_of_other(pool: list[dict], fid: str, fids: set[str]) -> bool:
    """该文件是否是同组里另一份文件的附件。"""
    me = next((r for r in pool if r["file_id"] == fid), None)
    if me is None:
        return False
    mine = set(_related_of(me))
    for other in fids - {fid}:
        orow = next((r for r in pool if r["file_id"] == other), None)
        if orow is None:
            continue
        rel_other = ((orow.get("card") or {}).get("rel_path")
                     or (orow.get("manifest") or {}).get("rel_path") or "")
        rel_me = ((me.get("card") or {}).get("rel_path")
                  or (me.get("manifest") or {}).get("rel_path") or "")
        if rel_other in mine or rel_me in set(_related_of(orow)):
            return True
    return False


def detect_entity_substitution(pool, need_entities) -> list[dict]:
    """跨主体复用检测：同一份材料被用于满足**不同主体**的义务。

    这是 HG2「主体冒充」的第二层——第一层只看「同一 file_id 是否挂了多个主体」，
    但更常见的错法是：拿 A 公司的材料去顶 B 公司的要求。
    """
    names = {e["display_name"] for e in need_entities if e.get("display_name")}
    by_file: dict[str, set[str]] = {}
    for r in pool:
        card = r.get("card") or {}
        ent = card.get("entity") or ""
        if not ent:
            continue
        by_file.setdefault(r["file_id"], set()).add(ent)
    out = []
    for fid, ents in by_file.items():
        other = ents & names - {next(iter(ents))} if len(ents & names) > 1 else set()
        if len(ents & names) > 1:
            out.append({"file_id": fid, "entities": sorted(ents & names)})
    return out


def detect_anomalies(
    obl: dict, pool: list[dict], need_entities: list[dict],
    authority_entities: list[dict] | None = None,
    alias_map: dict | None = None,
) -> dict:
    """检测 STALE（过期）与 CONFLICT（冲突）。

    WP3 交付时这两态尚未有实质实现，本函数补上：

    - **STALE**：某主体名下只有**区间外**年份的材料覆盖了它，而区间内没有。
      即「拿旧版本顶当期要求」——`mtime` 不代表业务有效，必须靠期间判定。
    - **CONFLICT**：同一义务下，**同一主体 + 同一期间**出现内容哈希不同的多份材料，
      无法判定哪份为准，不得自动二选一。
    """
    stale_entities: list[str] = []
    conflict_pairs: list[dict] = []
    unknown_entities: list[dict] = []
    unknown_types: list[dict] = []
    y_from, y_to = obl.get("period_from", 0), obl.get("period_to", 0)

    # 按 (主体, 期间) 分桶 —— WP-A1（G6）修正：
    # 旧实现 ent 取 card.entity，为空时回落 `rel_path.split("/")[0]`；卡片 entity 空 +
    # 扁平 rel_path 时回落仍为空 → 桶键 ("", period) → **跨法人混桶 → 假 CONFLICT**
    # （A0 基线：319 条义务 284 条 89% 报 CONFLICT，全部由此产生）。
    # FOS 自己的原则是「缺权威名单就判 UNCERTAIN，不得拿目录名凑数」：
    # 1) 移除目录名回落——主体只能取 card.entity（权威来源：卡片声明/权威登记）；
    # 2) 主体未知的材料**不参与 CONFLICT 判定**，单独记入 unknown_entities，
    #    由 judge() 据此报 UNCERTAIN 并注明「主体未登记，无法判定是否同一主体」；
    # 3) 只有主体已知 + 同主体 + 同期间 + 内容哈希不同才报 CONFLICT。
    # ── WP-A1（G6 v2）权威主体名单 ────────────────────────────────────────
    # **「主体未知」的准确定义是「该主体不在权威名单里」，不是「card.entity 为空」。**
    #
    # 为什么必须查名单：认知卡的 ``entity`` 在真实材料上**就是父目录名**
    # （``dd_v1_card_service.build_card`` 的 ``parts[-2]``，provenance=INFERRED、
    # evidence.kind=path_segment，全仓唯一写入点）——**非空**。
    # 只判空 ⇒ 「主体未登记」被误判成「主体已知」⇒ 同目录的**不同法人**
    # 落进同一个桶 ⇒ 报假 CONFLICT（A0 基线 319 条义务里 284 条 89% 报 CONFLICT
    # 就是这么来的），且 ``has_unknown_entities=False`` ⇒
    # ``judge()`` 的「主体未登记 ⇒ 降级 UNCERTAIN」**根本不触发**。
    #
    # 名单来源（两个来源取并集）：
    # - 第 3 位参 ``need_entities``：**任务书与验收脚本的权威名单口径**
    #   （独立 Reviewer 的三支脚本都把权威名单放在这个位参）；
    # - 第 4 位参 ``authority_entities``：产品路径额外传入的**全量权威名单**
    #   （不按义务范围过滤）——「这条义务要求哪几个主体」与
    #   「这个法人登记过没有」是两件事，必须分开取。
    # A2（G-A2-8）：**主体名先归一再分桶** ——
    # 归一口径 = 与权威登记全称逐字相等（FACT）或与已登记别名相等（ALIAS/INFERRED）；
    # 都对不上 ⇒ 主体未登记（不猜、不退化）。
    entities_all = list(need_entities or []) + list(authority_entities or [])
    _pool_lib = ""
    for _r in pool:
        _lib = (_r.get("manifest") or {}).get("library_id")
        if _lib:
            _pool_lib = str(_lib)
            break
    _aliases = alias_map if alias_map is not None else _alias_map_for(_pool_lib)
    registered = {str(e.get("display_name") or "").strip() for e in entities_all}
    registered.discard("")
    #
    # 桶键 = (主体, 期间, 材料类型)
    # 类型维度：不同材料类型（营业执照 vs 车辆登记证）**不得互判冲突**。
    buckets: dict[tuple[str, str, str], set[str]] = {}
    unknown_bucket: list[dict] = []
    # ★ A2（G-A2-12）：**阻断集** = 「可能是本义务要求的那一份」的未知候选。
    #   未知候选**全部**仍进 unknown_bucket（留痕 + 不参与冲突判定，口径不变）；
    #   只有阻断集里的那些才让 judge() 降级 UNCERTAIN。
    #   ★ 缺 `_may_be_required` 标记的候选（直接调用本函数的旧用法）按**最保守**处理。
    blocking_unknown_entity: list[dict] = []
    blocking_unknown_type: list[dict] = []
    # ── WP-A1（G6 v3 · R1）材料类型认不出 ⇒ 不参与冲突判定 ──────────────────
    # 桶键里的 doc_type 认不出时取空串 ""；空串照样进桶 ⇒ 两份**类型未知**材料
    # 落进同一桶 (entity, period, "") ⇒ 同主体同期间异哈希 ⇒ **误报 CONFLICT**。
    # 诚实性口径与「主体未登记」一致：认不出类型 ⇒ 无法判定两份材料是不是
    # 同一材料类型的两个版本 ⇒ 不得断言冲突 ⇒ 单列桶 + judge() 降级 UNCERTAIN。
    unknown_type_bucket: list[dict] = []
    # ★ A2（G-A2-10）：索引件单独成桶（留痕）；合法多份单独成桶（留痕）
    index_artifacts: list[dict] = []
    multi_legal: list[dict] = []
    for r in pool:
        card = r.get("card") or {}
        ent_raw = (card.get("entity") or "").strip()
        pv = str(card.get("fiscal_period") or "")
        # 10a：索引/目录件**不是材料** ⇒ 不参与任何冲突判定（但留痕）
        _mfrow = r.get("manifest") or {}
        _fname = _mfrow.get("file_name") or Path(str(_mfrow.get("rel_path") or "")).name
        if dts.is_index_artifact(_fname):
            index_artifacts.append(r)
            continue
        dt = cs.doc_type_key(card)
        _sm = _match_subject(ent_raw, entities_all, _aliases)
        if not _sm.get("matched"):
            # 主体未知（字段为空 / 未在权威名单里 / 别名未登记）⇒ 不参与冲突判定
            unknown_bucket.append(r)
            if r.get("_may_be_required", True):
                blocking_unknown_entity.append(r)
            continue
        ent = _sm.get("display_name") or ent_raw   # 归一后的权威主体名
        if not dt:
            # 类型未知（认不出规范 doc_type key）⇒ 不参与冲突判定
            unknown_type_bucket.append(r)
            if r.get("_may_be_required", True):
                blocking_unknown_type.append(r)
            continue
        # ★ A2（G-A2-10 · 10b）：**期间内合法多份**的类型 ⇒ 不报冲突，只留痕。
        #   （如工商底档多分册、执照正副本、按月财务报表、多份合同。）
        #   ★ **唯一性类（ANNUAL_UNIQUE）不受影响** ⇒ 真冲突仍必须报（判据双向）。
        if rq.doc_type_uniqueness(dt) == "MULTI_LEGAL":
            multi_legal.append(r)
            continue
        buckets.setdefault((ent, pv, dt), set()).add(r["file_id"])
    if unknown_bucket:
        rels = sorted(((r.get("card") or {}).get("rel_path")
                       or (r.get("manifest") or {}).get("rel_path") or "")
                      for r in unknown_bucket)
        unknown_entities.append({
            "count": len(unknown_bucket),
            "rel_paths": rels,
            "note": "主体未登记，无法判定是否同一主体；不参与内容冲突判定，需人工确认主体归属",
        })

    if unknown_type_bucket:
        rels = sorted(((r.get("card") or {}).get("rel_path")
                       or (r.get("manifest") or {}).get("rel_path") or "")
                      for r in unknown_type_bucket)
        unknown_types.append({
            "count": len(unknown_type_bucket),
            "rel_paths": rels,
            "note": "材料类型认不出，无法判定是否同一材料类型；不参与内容冲突判定，需人工确认材料类型",
        })

    for (ent, pv, _dt), fids in buckets.items():
        if len(fids) > 1:
            # **主文档与它的附表不是「冲突版本」**，必须排除，
            # 否则「审计报告 + 审计报告附表」这种正常组合会被误判为内容冲突。
            fids = {f for f in fids if not _is_attachment_of_other(pool, f, fids)}
            if len(fids) <= 1:
                continue
            hashes = {
                (r.get("manifest") or {}).get("content_hash")
                for r in pool if r["file_id"] in fids
            }
            hashes.discard(None)
            if len(hashes) > 1:
                conflict_pairs.append({
                    "entity": ent, "period": pv,
                    "files": sorted(fids), "distinct_hashes": len(hashes),
                })

    # STALE：有主体只在区间外被覆盖（WP-A1：同样只用已声明的 card.entity，不用目录名凑数）
    if y_from and y_to:
        covered_by_entity: dict[str, set[int]] = {}
        for r in pool:
            card = r.get("card") or {}
            _sm = _match_subject((card.get("entity") or "").strip(),
                                 entities_all, _aliases)
            if not _sm.get("matched"):
                continue  # 主体未知不参与 STALE 判定（与冲突分桶同一口径：必须在权威名单里）
            ent = _sm.get("display_name") or (card.get("entity") or "").strip()
            pv = str(card.get("fiscal_period") or "")
            if pv.isdigit():
                covered_by_entity.setdefault(ent, set()).add(int(pv))
        targets = ([e["display_name"] for e in need_entities] if need_entities
                   else list(covered_by_entity.keys()))
        for ent in targets:
            years = covered_by_entity.get(ent)
            if not years:
                continue
            inside = {y for y in years if y_from <= y <= y_to}
            outside = years - inside
            if not inside and outside:
                stale_entities.append(f"{ent}: 仅有 {sorted(outside)}，要求 {y_from}-{y_to}")

    if index_artifacts:
        rels = sorted(((r.get("card") or {}).get("rel_path")
                       or (r.get("manifest") or {}).get("rel_path") or "")
                      for r in index_artifacts)
        index_artifacts_info = [{
            "count": len(index_artifacts),
            "rel_paths": rels,
            "note": "索引/目录件不是材料；不参与内容冲突判定（留痕），需人工确认",
        }]
    else:
        index_artifacts_info = []

    if multi_legal:
        rels = sorted(((r.get("card") or {}).get("rel_path")
                       or (r.get("manifest") or {}).get("rel_path") or "")
                      for r in multi_legal)
        multi_legal_info = [{
            "count": len(multi_legal),
            "rel_paths": rels,
            "note": "该材料类型在同一主体同一期间**合法多份**"
                    "（唯一性口径 MULTI_LEGAL）⇒ 不判内容冲突，仅留痕",
        }]
    else:
        multi_legal_info = []

    return {
        "stale_entities": stale_entities,
        "conflicts": conflict_pairs,
        "unknown_entities": unknown_entities,
        "blocking_unknown_entities": _blocking_info(
            blocking_unknown_entity,
            "主体未登记，且**可能是本义务要求的那一份** ⇒ 结论降级"),
        "blocking_unknown_types": _blocking_info(
            blocking_unknown_type,
            "材料类型认不出，且**可能是本义务要求的那一份** ⇒ 结论降级"),
        "unknown_types": unknown_types,
        "index_artifacts": index_artifacts_info,
        "multi_legal": multi_legal_info,
        "has_stale": bool(stale_entities),
        "has_conflict": bool(conflict_pairs),
        "has_unknown_entities": bool(unknown_entities),
        "has_unknown_types": bool(unknown_types),
    }


def _requirement_summary(obl: dict) -> str:
    """把一条义务**要求什么**写成一句可读的摘要（给 MISSING 的缺口定位用）。

    目的：MISSING 不能给出一份空白缺口清单——复核者要能据此去追缺口。
    """
    parts = []
    if obl.get("doc_type"):
        parts.append(f"材料类型={obl['doc_type']}")
    if obl.get("entity_scope"):
        # ★ A2（G-A2-11）：主体前缀是客户标识 ⇒ 摘要里只写脱敏标签
        #   （脱敏规则由 requirement_service 单一来源提供，不在这里另写一份）
        parts.append(f"主体范围={rq.entity_scope_value(obl['entity_scope'])}")
    pf, pt = obl.get("period_from") or 0, obl.get("period_to") or 0
    if pf and pt:
        parts.append(f"期间={pf}-{pt}")
    elif obl.get("period_basis") in ("relative_unresolved", "unresolved"):
        parts.append("期间=提及但无法解析")
    if obl.get("seal_required"):
        parts.append(f"签章={obl['seal_required']}")
    if obl.get("needs_attachments"):
        parts.append("需附件")
    return "、".join(parts) or "（未识别出可定位的维度）"


def _may_be_required_type(r: dict, obl_dt: str, terms: list[str],
                          text_lookup: dict[str, str]) -> bool:
    """这条候选**是不是**本义务要求的那一份材料？

    ★ A2（G-A2-12 · 相关性闸）：「主体未登记 / 类型认不出 ⇒ 降级 UNCERTAIN」
      这条闸原本挂在**整个候选池**上 ⇒ 池子里一份身份证复印件就能把
      「营业执照齐备没有」打成 UNCERTAIN ⇒ MATCHED 永远出不来。
    ⇒ 降级只看**可能是本义务要求的那一份**的候选：

    - 义务**没**要求类型 ⇒ 任何候选都可能是（最保守）；
    - 候选类型**认得出**且与要求**相等** ⇒ 是；
    - 候选类型**认得出**但**不等** ⇒ **不是**（它压根不是那一类）；
    - 候选类型**认不出** ⇒ 查**全文**（路径 + 标题 + 正文缓存）：
      要求类型的关键词在里面 ⇒ 它**可能**是那一类（保守：阻断）；不在 ⇒ **不是**。

    ★ 只影响「要不要因『认不出』而降级」，**不改变**：
      冲突判定口径、唯一性口径、doctype_cov 口径、留痕字段。
    """
    dt_c = str(cs.doc_type_key(r.get("card") or {}) or "").strip()
    if not obl_dt:
        return True
    if dt_c:
        return dt_c == obl_dt
    hay = " ".join([
        str((r.get("manifest") or {}).get("rel_path") or ""),
        str((r.get("card") or {}).get("title") or ""),
        str(text_lookup.get(str(r.get("file_id") or "")) or ""),
    ])
    return any(t and t in hay for t in terms)


def judge(
    obl: dict, results: list[dict], need_entities: list[dict], capped: bool,
    used_terms: list[str] | None = None,
    authority_entities: list[dict] | None = None,
    entity_unverifiable: bool = False,
    alias_map: dict | None = None,
) -> dict:
    """四维覆盖 → 最终判定。**核心：不是「有没有找到相关文件」。**"""
    n_ent = len(need_entities)
    # 需要的期间数（每一年都要有）
    y_from, y_to = obl.get("period_from", 0), obl.get("period_to", 0)
    need_periods = (y_to - y_from + 1) if (y_from and y_to and y_to >= y_from) else 0

    matched = [r for r in results if r["ev"]["deliverable"]]
    # 覆盖度按**全部候选**计算（材料是否存在），而不是只算可交付的。
    # 「材料存在但受限」与「材料根本不存在」在缺口清单里是两回事，必须分开报：
    # 前者 RESTRICTED，后者 MISSING/PARTIAL。
    pool = results

    # 主体覆盖：需要的主体里有多少被覆盖
    # 主体别名表（**全义务共用一份**，避免每条候选重复读库）
    # ★★ 优先用**调用方传进来的**那份（`match_obligation` 已取好）
    #   ⇒ 与 `evaluate_file` / `detect_anomalies` 用**同一份**别名表
    #   ⇒ 桶键、覆盖、归一**三处口径一致**（不出现「两套口径」）。
    _al: dict = alias_map if alias_map is not None else {}
    if not _al:
        for r in pool:
            _lib = (r.get("manifest") or {}).get("library_id")
            if _lib:
                _al = _alias_map_for(str(_lib))
                break

    ent_cov = 0.0
    if n_ent:
        covered = set()
        for r in pool:
            blob = f"{(r['card'] or {}).get('entity','')} {r['manifest']['rel_path'] if r['manifest'] else ''}"
            hit = False
            for e in need_entities:
                if e["display_name"] and e["display_name"] in blob:
                    covered.add(e["entity_id"])
                    hit = True
            if not hit:
                # A2（G-A2-8）别名归一：目录名/简称匹配到已登记主体也算覆盖
                _m = _match_subject((r.get("card") or {}).get("entity") or "",
                                     need_entities, _al)
                if _m.get("matched") and _m.get("entity_id"):
                    covered.add(_m["entity_id"])
        ent_cov = len(covered) / n_ent
    else:
        ent_cov = 1.0

    # 期间覆盖：需要的年份里有多少被覆盖
    period_cov = 0.0
    if need_periods:
        years = set()
        for r in pool:
            pv = (r["card"] or {}).get("fiscal_period")
            if pv and str(pv).isdigit():
                y = int(pv)
                if y_from <= y <= y_to:
                    years.add(y)
        period_cov = len(years) / need_periods
    else:
        period_cov = 1.0

    # ── 类型维度覆盖：**按「需要多少份该类型材料」计**（A2 · G-A2-4）────
    # 旧口径 = 类型命中候选数 / 全部候选数 ⇒ 候选池里混进十几份无关材料，
    # 就把「找到 1 份对的」也算成 0.05 ⇒ 一票否决 ⇒ 判 PARTIAL。
    # 实测：案例A/B/C 有类型的义务中 63%–67% 因此判 PARTIAL。
    # 那是**召回噪声**被当成了**类型覆盖不足**。
    # 新口径（与其它三维同构：都是「覆盖到的需求数 / 需求总数」）：
    #   分子 = 覆盖到该类型材料的「主体 × 期间」格子数；
    #   分母 = 本义务**需要的**该类型材料数 = 主体数 × 年数（无约束时取 1）。
    # 红线：**不是**把 doctype_cov 恒置 1，也**不是**把分母硬编码成 1 ——
    #       分母由义务的主体/期间约束算出来，主体×年份不足时照样 < 1。
    need_type = max(1, (n_ent or 1) * (need_periods or 1))
    _cells = set()
    for r in pool:
        _ev = r.get("ev") or {}
        if not _ev.get("doctype_ok"):
            continue
        _card = r.get("card") or {}
        if need_periods and not _ev.get("period_ok"):
            continue          # 期间不满足 ⇒ 不算覆盖到该格子
        _m = _match_subject(_card.get("entity") or "", need_entities, _al)
        _ent = _m.get("display_name") or "*"
        _pv = str(_card.get("fiscal_period") or "") if need_periods else "*"
        _cells.add((_ent, _pv))
    doctype_cov = (min(len(_cells), need_type) / need_type) if need_type else 0.0
    # 必备附件覆盖：义务要求附件时，看**可交付**的命中材料里有多少带可观察的关联件。
    # 认知卡的 related_files 自 WP6 起可由确定性规则填充，故此维度不再是恒 0。
    if obl.get("needs_attachments"):
        attach_cov = (sum(1 for r in pool if r["ev"]["attachment_ok"]) / len(pool)
                      if pool else 0.0)
    else:
        attach_cov = 1.0

    missing = []
    if capped:
        # A2（G-A2-4）：候选池打满 ⇒ 召回被截断 ⇒ **类型维度结论置信度低**，
        # 必须在报告里显式标注（否则读者会把截断后的结论当成全量结论）。
        missing.append("【置信提示】候选池打满（召回上限已触顶），"
                       "类型维度结论置信度低")
    # ★ A3（G-A3-3）：主体/期间/类型/附件/份数**每一维**的缺口都要指名，
    #   由 qc_service 统一产出（见本函数末尾）——
    #   旧实现只报**第一个**命中的分支 ⇒ 其余维度静默丢失，
    #   复核者只会看到「缺 1 样」，不知道缺的是哪一维。

    # 判定
    #
    # **「没查」与「查了没有」必须分开**（WP7 验收 D-1/D-4）：
    # 原实现把 `not results` 直接短路成 MISSING，排在「要求主体范围却无权威名单
    # → UNCERTAIN」之前，于是该规则永远执行不到；更糟的是**根本没发出过任何
    # 检索词**时也会判 MISSING——材料可能就在库里，只是没去查。
    # 那会输出一份**自信的错误缺口清单**，用户照着去追不存在的缺口。
    searched = bool(used_terms) if used_terms is not None else True
    if not results and not searched:
        verdict = V_UNCERTAIN
        missing.append("未能提取任何检索词，**没有真正检索过**；"
                       "不能据此断言材料缺失")
    elif not results and obl.get("entity_scope") and not need_entities:
        # 要求了主体范围却没有权威名单 → 判 UNCERTAIN，不得拿目录名凑数
        verdict = V_UNCERTAIN
        missing.append(f"要求{rq.entity_scope_label(obl['entity_scope'])}"
                       f"但无权威主体名单，无法判定（候选 0 份）；不得用目录名凑数")
    elif not results:
        verdict = V_MISSING
        # A2（G-A2-0）：MISSING 必须**说清缺什么、为什么缺**，
        # 不能给出一份空白的缺口清单（那会让复核者无从下手）。
        missing.append(
            f"未检索到任何候选材料（检索词：{'、'.join(used_terms or []) or '（无）'}）；"
            f"本条要求：{_requirement_summary(obl)} ⇒ 缺口：缺上述材料")
    elif not n_ent and obl.get("entity_scope"):
        # ★ A2（G-A2-11 · 11c① · **M-1 整改**）：主体闸**必须早于所有 PARTIAL 分支**。
        #   ★ 独立 Reviewer 第一轮实测抓到：期间分支早于主体闸 ⇒
        #     「义务指名的主体未登记」被「期间只覆盖一部分」抢先 ⇒ 产出 **PARTIAL**
        #     ⇒ 主体维度**从未核对过**却给出了「部分齐备」的结论 ⇒ **判据违反**。
        #   ★ 该顺序在 A1 时代是**潜伏**的（A1 的 entity_scope 恒空 ⇒ 该闸永不触发），
        #     A2 引入非空 entity_scope 后被**激活成可达** ⇒ 由 A2 收口。
        #   ★ 只把结论**改保守**（PARTIAL → UNCERTAIN），不放松任何硬 Gate。
        verdict = V_UNCERTAIN
        # ★ A2（G-A2-11）：主体前缀是**客户标识** ⇒ 文案里**不得**出现原文
        #   （脱敏规则由 requirement_service 单一来源提供，不在这里另写一份）
        _scope_label = rq.entity_scope_label(obl.get("entity_scope"))
        missing.append(f"要求{_scope_label}但无权威主体名单，"
                       f"无法判定（候选 {len(results)} 份）；不得用目录名凑数")
    elif need_periods and period_cov < 1.0 and period_cov > 0:
        verdict = V_PARTIAL
    elif not obl.get("period_basis"):
        verdict = V_UNCERTAIN
        missing.append("期间基准缺失（义务未解析出期间口径），"
                       "不得当作「没有期间要求」放行")
    elif obl.get("period_basis") in ("relative_unresolved", "unresolved"):
        # A2（G-A2-5）：**期间提及但解析不出** ⇒ 不得当作「没有期间要求」放行。
        # 口径区分：`period_basis=UNKNOWN` 是「文本压根没提期间」，
        # 该维度**不构成门槛**（不得因此把 98% 的义务判成 UNCERTAIN——
        # 实测 241 条真实义务里 236 条的清单根本没写年份）；
        # 只有「提了却解析不出」才必须诚实地说「期间无法解析」。
        verdict = V_UNCERTAIN
        missing.append("期间无法解析（相对期间缺锚定年 / 期间口径不明），"
                       "不得当作「没有期间要求」放行")
    elif ent_cov < FULL_COVERAGE:
        verdict = V_PARTIAL
    elif doctype_cov < FULL_COVERAGE:
        verdict = V_PARTIAL
    elif attach_cov < FULL_COVERAGE:
        verdict = V_PARTIAL
    else:
        verdict = V_MATCHED

    # ★ A2（G-A2-11 · 11c②）：**主体维度不可判定** ⇒ 不得产出 MATCHED / PARTIAL。
    #   触发条件：义务**没有**指名主体（entity_scope 空），而**本库登记了多于一个主体**
    #   ⇒ 无法判定这条义务针对哪个主体 ⇒ 主体维度**不构成门槛**的老口径
    #   （`ent_ok=1` 无门槛放行）会产出**假 MATCHED**。
    #   ★ 该闸**只会把结论改保守**（MATCHED/PARTIAL → UNCERTAIN），
    #     **不会**放松任何硬 Gate；确证缺失（MISSING）也不受影响（缺失与主体无关）。
    if entity_unverifiable and verdict in (V_MATCHED, V_PARTIAL):
        verdict = V_UNCERTAIN
        missing.append("主体维度不可判定：义务未指名主体，而本库登记了多个主体，"
                       "无法判定该义务针对哪个主体；不得无门槛放行为 MATCHED")

    # 受限材料不能顶替：覆盖完整但**一份都不可交付**时，不得判 MATCHED。
    # 这是硬门槛 HG1「未经人工最终批准不得对外交付」的机器侧兜底。
    if verdict == V_MATCHED and not matched:
        verdict = V_RESTRICTED
        missing.append("材料已找到但全部受限/不可读/敏感等级未知，不得自动纳入对外交付")

    # STALE / CONFLICT 优先于 MATCHED/PARTIAL：拿旧版本顶当期、或同主体同期多版本冲突，
    # 都必须让人看见，不能被「覆盖率够了」盖过去。
    anom = detect_anomalies(obl, results, need_entities,
                      authority_entities, alias_map=_al)
    # gm-fix-f1-conflict-scope: CONFLICT 的**相关性闸**（F1 · 监工第 35 轮 P0）
    #
    # ★ 为什么必须加这道闸（司仓**独立复现**确认，不是采信口述）：
    #   冲突是**候选池内部**的发现（桶键 = 主体 × 期间 × 材料类型），
    #   与「本义务要求哪一类材料」**无关**。旧实现让**任意**类型的冲突对
    #   无条件覆盖本义务的最终判定 ⇒ 一对
    #   「2024 审计报告 + 2024 审计报告补充说明」把**整库**义务全打成 CONFLICT
    #   ⇒ 与该义务毫无关系的「缺专利证书」这类**可行动缺口信号被覆盖**
    #   （实测该义务的 missing_detail 里明明有「材料类型缺 1/1 份」）
    #   ⇒ 材料包为空 ⇒ **系统在该库上完全不可用**。
    #
    # ★ 闸的口径：与 A2（G-A2-12）**同构** —— 冲突**只影响相关义务**：
    #   冲突对里有「**可能是本义务要求的那一份**」的候选时
    #   （`_may_be_required`，**同一套**相关性口径）本义务才改判 CONFLICT；
    #   否则**只留痕**、**不改判**。
    #
    # ★ 不放宽冲突本身：
    #   - `detect_anomalies` 的**检测口径一字不改**（桶键 / 唯一性 / 主体归一全不动）
    #     ⇒ `anom["conflicts"]`、`anom["has_conflict"]` 与既有测试断言**完全不变**；
    #   - 冲突事实仍落 `anomalies_json` 审计面 ⇒ **T3 语义不变**：
    #     同主体同期同类型异哈希**仍然必须报**（只是不再染黑无关义务）；
    #   - 义务**未指名类型** ⇒ 任何候选都可能是 ⇒ 一律按相关处理（最保守），
    #     不会把真冲突放过；
    #   - 缺 `_may_be_required` 标记的旧调用路径按最保守（True）处理。
    _may_by_file: dict[str, bool] = {}
    for _r in (results or []):
        _may_by_file[str(_r.get("file_id") or "")] = bool(
            _r.get("_may_be_required", True)
        )
    _conf_rel: list[dict] = []
    _conf_irr: list[dict] = []
    for _c in (anom.get("conflicts") or []):
        _hit = any(_may_by_file.get(str(_f), True) for _f in (_c.get("files") or []))
        (_conf_rel if _hit else _conf_irr).append(_c)
    if _conf_rel:
        verdict = V_CONFLICT
        if n_ent:
            missing.append(f"同一主体/期间存在 {len(_conf_rel)} 组内容冲突，需人工裁定")
        else:
            # ★ F3（监工第 33 轮）：该义务**未指名主体** ⇒ 主体维度从未参与判定
            #   ⇒「同一主体」是**对候选材料**的断言，不是对本义务的断言 ⇒ 措辞收窄。
            #   ★ 冲突这一**事实与 CONFLICT 判定都保留**：
            #   不得因为「断言不成立」就吞掉必须人工裁定的发现。
            missing.append(f"候选材料中同一主体/期间存在 {len(_conf_rel)} 组内容冲突，"
                           "需人工裁定（该义务未指名主体，此为**材料层**发现，"
                           "不构成该义务的主体维度断言）")
    else:
        if anom["has_stale"] and verdict in (V_MATCHED, V_PARTIAL):
            verdict = V_STALE
            missing.append("；".join(anom["stale_entities"]))
    # gm-fix-f1-always-trace-irrelevant: 无关冲突**一律留痕**（不再藏在 `else:` 里）
    #   ★ 病（结构）：原先 `if _conf_irr:` 在 `else:` 分支内 ⇒ 只要**存在相关冲突**，
    #     无关冲突的留痕就**完全不出现** ⇒ 冲突事实在**消息层**被丢掉
    #     （`anomalies_json` 里还在，但审核人看的是消息）。
    #     独立 Reviewer 裁定书「风险 1」：当前 `ANNUAL_UNIQUE` 只有一种 ⇒ 不可达；
    #     但若日后新增第二种类型，「相关 + 无关并存」时就会露出来。
    #   ★ 治：留痕**移出 `else:`** ⇒ 无论有没有相关冲突，一律留痕。
    #   ★ 只**多一行文案**，**不放宽任何闸**：判定分支与 `verdict` 取值**一字不改**，
    #     STALE 分支的触发条件与位置**保持原样**，留痕文案**逐字不变**。
    if _conf_irr:
        # gm-fix-f1-conflict-scope: 冲突**存在**但**与本义务无关** ⇒ 只留痕。
        #   冲突涉及的材料类型与本义务要求的类型**确定不同**
        #   ⇒ 不可能是本义务要求的那一份 ⇒ **不改判**本义务
        #   （否则可行动的缺口信号会被无关冲突覆盖）。
        #   ⇒ 但**必须留痕**（不静默丢弃）：冲突事实与「需人工裁定」都保留。
        missing.append(f"（留痕）候选材料中同一主体/期间存在 {len(_conf_irr)} 组内容冲突，"
                       "但这些冲突涉及的材料类型与本义务要求的材料类型**确定不同** ⇒ "
                       "不可能是本义务要求的那一份，不改判本义务；仍需人工裁定")

    # WP-A1（G6）主体未登记 ⇒ **覆盖类判定不可信**，一律改判 UNCERTAIN。
    #
    # 为什么不能只挂在 MATCHED 上：主体未知 ⇒ 无法判定材料是不是目标主体那一份
    # ⇒「覆盖率够了」这个结论本身就不成立（PARTIAL / MATCHED / RESTRICTED 全部建立在覆盖之上），
    # 所以 RESTRICTED 也要一起改判——否则就会退回「受限所以不可外发」这一句，
    # 把真正缺的那句「主体未登记，无法判定是否同一主体」盖掉。
    # 为什么 CONFLICT 不改判：冲突是**更具体、必须人工裁定**的发现，
    # 改判成 UNCERTAIN 反而把可行动信息降级；两条事实都写进 missing_detail，一个都不丢。
    # 为什么放在 MATCHED→RESTRICTED 降级之后仍然有效：
    # 降级只改 verdict 取值，不改「候选里有主体未知的材料」这个事实；
    # 降级写下的受限原因已原样留在 missing_detail 里（见 restricted 追加逻辑）。
    if anom.get("has_unknown_entities"):
        if anom.get("blocking_unknown_entities"):
            # ★ G-A2-12：只有「**可能是本义务要求的那一份**」的未知主体候选才降级。
            if verdict in (V_MATCHED, V_PARTIAL, V_RESTRICTED):
                verdict = V_UNCERTAIN
            missing.append("主体未登记，无法判定是否同一主体；"
                           f"候选中有 {anom['blocking_unknown_entities'][0]['count']} 份材料主体未登记，"
                           "且**可能是本义务要求的那一份**；需人工确认主体归属")
        else:
            # ★ G-A2-12：类型与本义务要求的类型**确定不同** ⇒ 不可能是那一份
            #   ⇒ **不降级**，但**必须留痕**（不静默丢弃）。
            missing.append(f"（留痕）候选中有 {anom['unknown_entities'][0]['count']} 份材料主体未登记，"
                           "但它们与本义务要求的材料类型**确定不同** ⇒ 不可能是本义务要求的那一份，"
                           "不阻断结论；仍需人工确认主体归属")

    # WP-A1（G6 v3 · R1）材料类型认不出 ⇒ **类型维度结论不可信** ⇒ 降级 UNCERTAIN。
    #
    # 为什么必须降级而不是只「不报 CONFLICT」：认不出类型 ⇒ 无法判定这份材料
    # 是不是义务要求的那种材料 ⇒ 「类型覆盖够了」这个结论本身就不成立
    # （PARTIAL / MATCHED / RESTRICTED 都建立在覆盖之上）。
    # 为什么 CONFLICT 不改判：冲突是**更具体、必须人工裁定**的发现，
    # 改判成 UNCERTAIN 反而把可行动信息降级（同 has_unknown_entities 的处理）。
    if anom.get("has_unknown_types"):
        if anom.get("blocking_unknown_types"):
            # ★ G-A2-12：只有「**可能是本义务要求的那一份**」的未知类型候选才降级。
            if verdict in (V_MATCHED, V_PARTIAL, V_RESTRICTED):
                verdict = V_UNCERTAIN
            missing.append("材料类型认不出，无法判定是否同一材料类型；"
                           f"候选中有 {anom['blocking_unknown_types'][0]['count']} 份材料类型认不出，"
                           "且**可能是本义务要求的那一份**；需人工确认材料类型")
        else:
            missing.append(f"（留痕）候选中有 {anom['unknown_types'][0]['count']} 份材料类型认不出，"
                           "但它们**不是**本义务要求的材料类型（全文无该类型关键词）"
                           "⇒ 不可能是本义务要求的那一份，不阻断结论；仍需人工确认材料类型")

    # ★ F4（监工第 33 轮 · B8b）：MATCHED 要求主体维度**确实核对过**。
    #   `n_ent == 0` 时 `ent_cov = 1.0` 只是「本义务没要求主体 ⇒ 该维度无约束」的
    #   **空洞满分**，不是「主体已核对」⇒ 不得据此说「材料齐备」⇒ 不得产出 MATCHED。
    #   ★ 只把 MATCHED 降为 UNCERTAIN；RESTRICTED（找到了但不可外发）**不受影响**
    #     —— 它断言的是「找到了」，而「没要求主体」时「找到」并不空洞。
    if verdict == V_MATCHED and n_ent == 0:
        verdict = V_UNCERTAIN
        missing.append("主体维度未经核对（该义务未指名主体，权威名单解析出 0 个主体）："
                       "ent_cov=1.0 只是「无约束」而非「已核对」；不得据此判 MATCHED")

    # ── ★ A3（G-A3-1 / G-A3-3）：**份数维度**接入齐套判定 ──────────────────
    # 「可交付份数」按**同一「主体 × 期间」格子**算，不是候选池总数——
    # 否则「5 份不同年份的审计报告」会被误当成「一式五份」而假装齐备。
    _avail = sum(
        1 for r in pool
        if (r.get("ev") or {}).get("deliverable")
        and (r.get("ev") or {}).get("entity_ok")
        and (r.get("ev") or {}).get("period_ok")
        and (r.get("ev") or {}).get("doctype_ok")
    )
    _cov = {
        "entity": {"covered": round(ent_cov * n_ent), "total": n_ent},
        "period": {"covered": round(period_cov * need_periods), "total": need_periods},
        "doctype": {"covered": round(doctype_cov * need_type), "total": need_type},
        "attachment": {
            "covered": round(attach_cov * len(pool)),
            "total": len(pool) if obl.get("needs_attachments") else 0,
        },
    }
    _qc = qc.build_completeness(obl, _cov, _avail)
    _cdim = _qc["by_dimension"][qc.DIM_COUNT]
    # ★ A3（G-A3-3）：把**每一维**的缺口都指名写进 missing_detail
    #   （旧实现只报第一个命中的分支 ⇒ 其它维度静默丢失）。
    for _d in _qc["missing"]:
        if _d["dimension"] == qc.DIM_COUNT:
            continue
        missing.append(_d["detail"])
    if not _cdim["determinable"]:
        # 清单**提及**份数但解析不出 ⇒ 该维不可判定 ⇒ 不得判齐备。
        # ★ 只把结论改**保守**（MATCHED/PARTIAL/RESTRICTED → UNCERTAIN），
        #   MISSING（确证缺失）/ CONFLICT（须人工裁定）/ STALE 不受影响。
        if verdict in (V_MATCHED, V_PARTIAL, V_RESTRICTED):
            verdict = V_UNCERTAIN
        missing.append(_cdim["detail"])
    elif _cdim["required"] and not _cdim["ok"]:
        if verdict == V_MATCHED:
            verdict = V_PARTIAL
        missing.append(_cdim["detail"])

    return {
        "obligation_id": obl["obligation_id"],
        "verdict": verdict,
        "entity_cov": round(ent_cov, 4),
        "period_cov": round(period_cov, 4),
        "doctype_cov": round(doctype_cov, 4),
        "attach_cov": round(attach_cov, 4),
        "need_entities": n_ent,
        "need_periods": need_periods,
        "missing_detail": "; ".join(missing),
        "candidate_count": len(results),
        "capped": 1 if capped else 0,
        "deliverable_count": len(matched),
        "recall_terms": list(used_terms or []),
        "actually_searched": searched,
        # ★ A3（G-A3-3）：五维齐套状态（随判定一起走，供核对表逐维展示）
        "completeness": _qc,
        "count_expected": _cdim["expected"],
        "count_available": _avail,
        **anom,
    }


def _persist(conn, library_id, obligation_id, obl, results, status) -> None:
    now = time.time()
    conn.execute("DELETE FROM dd_v1_matches WHERE obligation_id=?", (obligation_id,))
    for r in results:
        conn.execute(
            """INSERT INTO dd_v1_matches
               (match_id, obligation_id, library_id, file_id, rank, score,
                entity_ok, period_ok, doctype_ok, attachment_ok, seal_ok,
                deliverable, verdict, evidence, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, obligation_id, library_id, r["file_id"],
             r["rank"], r["score"], r["ev"]["entity_ok"], r["ev"]["period_ok"],
             r["ev"]["doctype_ok"], r["ev"]["attachment_ok"], r["ev"]["seal_ok"],
             r["ev"]["deliverable"], "", json.dumps(r["ev"]["reasons"], ensure_ascii=False), now),
        )
    conn.execute(
        """INSERT INTO dd_v1_obligation_status
           (obligation_id, library_id, verdict, entity_cov, period_cov,
            doctype_cov, attach_cov, need_entities, need_periods,
            missing_detail, candidate_count, capped, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(obligation_id) DO UPDATE SET
             verdict=excluded.verdict, entity_cov=excluded.entity_cov,
             period_cov=excluded.period_cov, doctype_cov=excluded.doctype_cov,
             attach_cov=excluded.attach_cov, need_entities=excluded.need_entities,
             need_periods=excluded.need_periods, missing_detail=excluded.missing_detail,
             candidate_count=excluded.candidate_count, capped=excluded.capped,
             updated_at=excluded.updated_at""",
        (obligation_id, library_id, status["verdict"], status["entity_cov"],
         status["period_cov"], status["doctype_cov"], status["attach_cov"],
         status["need_entities"], status["need_periods"], status["missing_detail"],
         status["candidate_count"], status["capped"], now),
    )
    conn.execute(
        "UPDATE dd_v1_obligation_status SET anomalies_json=? WHERE obligation_id=?",
        (json.dumps({k: status.get(k) for k in
                     ("stale_entities", "conflicts", "has_stale", "has_conflict")},
                    ensure_ascii=False), obligation_id),
    )
    conn.commit()


def match_library(
    library_id: str,
    candidate_cap: int = DEFAULT_CANDIDATE_CAP,
    db_path: Path | None = None,
) -> dict:
    """批量匹配全库义务。"""
    conn = _conn(db_path)
    obl_ids = [r["obligation_id"] for r in conn.execute(
        "SELECT obligation_id FROM dd_v1_obligations WHERE library_id=?", (library_id,))]
    tally: dict[str, int] = {}
    for oid in obl_ids:
        st = match_obligation(library_id, oid, candidate_cap=candidate_cap, db_path=db_path)
        tally[st["verdict"]] = tally.get(st["verdict"], 0) + 1
    return {
        "library_id": library_id,
        "obligations": len(obl_ids),
        "candidate_cap": candidate_cap,
        "by_verdict": tally,
        "docling_note": "候选上限为显式配置项，非硬编码",
    }


def get_status(obligation_id: str, db_path: Path | None = None) -> dict | None:
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_obligation_status WHERE obligation_id=?", (obligation_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d.update(json.loads(d.pop("anomalies_json") or "{}"))
    except (ValueError, TypeError):
        d["anomalies_json"] = "{}"
    return d


def list_matches(obligation_id: str, db_path: Path | None = None) -> list[dict]:
    conn = _conn(db_path)
    return [dict(r) for r in conn.execute(
        """SELECT m.*, c.rel_path AS card_rel_path, c.title AS card_title
           FROM dd_v1_matches m
           LEFT JOIN dd_v1_material_cards c ON c.file_id = m.file_id
           WHERE m.obligation_id=? ORDER BY m.rank""", (obligation_id,))]


def file_serves_count(file_id: str, db_path: Path | None = None) -> int:
    """一个文件可服务多条义务——统计复用度（对应指令「一个文件也允许服务多条需求」）。"""
    conn = _conn(db_path)
    return conn.execute(
        "SELECT COUNT(*) c FROM dd_v1_matches WHERE file_id=?", (file_id,)
    ).fetchone()["c"]


# ── D4：决策记忆的严格复验 ─────────────────────────────────────────────────
def revalidate_memory_hit(
    remembered: dict,
    current_entity: str,
    current_period: tuple[int, int] | None,
    card: dict | None,
) -> tuple[bool, str]:
    """决策记忆是否仍可沿用。任一项不符即拒绝。

    直接对治 D4：旧实现把 ``last_institution`` 写入 ``dd_decision_memory`` 却从不在
    lookup 里读（`dd_match_service.py:1478` 写 / `:1546` 读），等于跨主体自动锁定。
    """
    if not remembered:
        return False, "无记忆"
    rec_entity = (remembered.get("last_institution") or "").strip()
    if rec_entity and current_entity and rec_entity != current_entity:
        return False, f"主体不符：记忆={rec_entity} 当前={current_entity}"
    if remembered.get("valid_to"):
        return False, "记忆条目有失效期，当前实现未接入有效期判定，不作沿用"
    if current_period and card:
        pv = card.get("fiscal_period")
        if pv and str(pv).isdigit():
            y = int(pv)
            if not (current_period[0] <= y <= current_period[1]):
                return False, f"期间不符：记忆文件 {y} 不在 {current_period}"
    return True, "通过"
