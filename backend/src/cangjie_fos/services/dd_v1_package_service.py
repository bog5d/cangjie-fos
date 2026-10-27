"""DD-V1 人工审核、完整性报告与交付组包（WP4）。

## 最重要的一条：未经人工最终批准，不得复制任何材料

这是硬门槛 HG1（严重越权披露）的机器侧强制实现：

- ``build_review_pack()`` 只在受控 Data Plane 生成**审核包**（核对表 / 缺口清单 /
  证据说明 / Manifest+hash），**不碰材料源文件，也不复制任何原件**。
- ``package_approved()`` 是唯一会复制原件的入口，它**必须**先通过
  :func:`assert_approval`，否则抛 :class:`ApprovalRequired` 并**在复制之前**中止。
- 受限、不可读、解析失败、敏感等级未知的材料**一律不进交付目录**，
  即使人工勾选了也会被 Gate 拦下并记录原因（人可覆盖判定，但不能绕过受限事实）。

## 第二重要的一条：审核通过 ≠ 每一条义务都通过（P0-2 · 逐条交付闸）

**旧行为（有缺陷）**：``assert_approval()`` 只检查两件事——单据
``status ∈ {approved, packaged}``、``approved_by`` 非空。于是
**「人工批量批准」＝「全部放行」**：哪怕 26 条义务的判定**全部**是
``UNCERTAIN``（证据不足以判定），程序照样把原件复制进正式交付包。

**新行为（fail-closed）**：组包时逐条义务要过一道**交付闸**
（:func:`_delivery_gate`）：

1. **判定闸**：默认只有 ``MATCHED``（四维全覆盖且无冲突）能进正式交付包；
   ``PARTIAL / MISSING / STALE / CONFLICT / UNCERTAIN / RESTRICTED``
   **一律不进**（不确定 ⇒ 不进正式交付包，这是默认）。
2. **人工逐条确认闸**：人可以对**具体某一条**义务写明确认人与理由
   （:func:`confirm_obligation`）来放行它——**可追责、逐条、只落
   ``review_id`` 维度**（一次确认**不得**升级为全局规则）。
3. **披露闸**（取其严）：即便前两道过了，材料本身
   **受限 / 不可读 / 敏感等级未知**时**仍然不进**交付包
   ——人工确认**不能**绕过受限事实。

⇒ **审核包与交付包严格隔离**：审核包（``build_review_pack()``）只读材料、
**零复制**，并把每条义务的过闸结论写进核对表；交付包（``package_approved()``）
**只装逐条过闸的件**。被拦的件**单独留痕**（「未过闸清单.tsv」＋
「被拦截清单.json」里的独立分类），**不得**与「材料根本不存在」混同。

## 复用优先

路径清洗与越界防护**直接复用** ``dd_export_service._within / _safe_filename /
_safe_dirname``（既有代码已在真实导出中跑过），不另立第二套文件名安全标准。

## 人工纠错沉淀

每次修改记录：原候选、机器判断、证据、修正前后、修改人、修改原因、
适用主体、机构、时间、版本。一次修改**不会**被自动升级为全局规则——
经验只落到 ``review_id`` 维度，跨任务复用属 WP5 且必须经 Gate。
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
import uuid
from pathlib import Path

from cangjie_fos.core import paths as fos_paths
from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_manifest_service as mf
# A3（G-A3-2）：精确选中规则（交付集合 = 选中件 + 必备附件，不是全部候选）
from cangjie_fos.services import dd_v1_selection_service as selsvc
from cangjie_fos.services import dd_v1_requirement_service as rq

# 复用既有路径安全工具（不另立标准）
from cangjie_fos.services.dd_export_service import (  # noqa: PLC0415
    _safe_dirname, _safe_filename, _within,
)

logger = logging.getLogger(__name__)

# 审核单状态机
ST_DRAFT = "draft"            # 已生成审核包，待人工审阅
ST_REVIEWED = "reviewed"      # 人工已提交修改意见
ST_APPROVED = "approved"      # 人工已最终批准
ST_PACKAGED = "packaged"      # 已组包
ST_REJECTED = "rejected"      # 人工否决

_DDL = """
CREATE TABLE IF NOT EXISTS dd_v1_reviews (
    review_id     TEXT PRIMARY KEY,
    library_id    TEXT NOT NULL,
    institution   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'draft',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    reviewed_by   TEXT NOT NULL DEFAULT '',
    approved_by   TEXT NOT NULL DEFAULT '',
    approved_at   REAL,
    review_note   TEXT NOT NULL DEFAULT '',
    pack_path     TEXT NOT NULL DEFAULT '',
    pack_manifest TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_reviews_lib ON dd_v1_reviews(library_id);

-- 人工修改留痕（一次修改 ≠ 一条全局规则）
CREATE TABLE IF NOT EXISTS dd_v1_review_edits (
    edit_id       TEXT PRIMARY KEY,
    review_id     TEXT NOT NULL,
    obligation_id TEXT NOT NULL DEFAULT '',
    action        TEXT NOT NULL,
    before_json   TEXT NOT NULL DEFAULT '{}',
    after_json    TEXT NOT NULL DEFAULT '{}',
    reason        TEXT NOT NULL DEFAULT '',
    scope_entity  TEXT NOT NULL DEFAULT '',
    institution   TEXT NOT NULL DEFAULT '',
    template      TEXT NOT NULL DEFAULT '',
    version       TEXT NOT NULL DEFAULT 'v1',
    edited_by     TEXT NOT NULL,
    edited_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_edits_review ON dd_v1_review_edits(review_id);

-- ★ P0-2：逐条义务的**人工确认**（交付闸的第二道）。
--   一次确认**只**落 review_id 维度 ⇒ 不得升级为全局规则（同 record_edit 的原则）。
CREATE TABLE IF NOT EXISTS dd_v1_review_confirmations (
    confirm_id    TEXT PRIMARY KEY,
    review_id     TEXT NOT NULL,
    obligation_id TEXT NOT NULL,
    verdict       TEXT NOT NULL DEFAULT '',
    confirmed_by  TEXT NOT NULL,
    reason        TEXT NOT NULL,
    created_at    REAL NOT NULL,
    UNIQUE (review_id, obligation_id)
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_confirm_review
    ON dd_v1_review_confirmations(review_id);
"""


#: 逐条义务判定 → **默认**可进正式交付包的取值集合。
#:
#: ★ 只有 ``MATCHED``（四维全覆盖且无冲突）默认放行。
#:   PARTIAL（未齐套）/ MISSING（查无此物）/ STALE（版本或期间不对）/
#:   CONFLICT（同主体同期冲突）/ UNCERTAIN（证据不足）/ RESTRICTED（受限）
#:   ⇒ **一律不进**正式交付包（fail-closed：不确定 ⇒ 不进正式交付包）。
#: ★ 例外**只有**一条：人工逐条确认（:func:`confirm_obligation`）——
#:   写明确认人与理由、可追责；且**不能**绕过披露闸（受限事实仍然拦）。
GATE_DEFAULT_PASS_VERDICTS = ("MATCHED",)

#: 交付闸结论取值
GATE_PASS = "PASS"
GATE_BLOCKED = "BLOCKED"


class ApprovalRequired(RuntimeError):
    """未获人工最终批准就请求组包——必须在复制任何原件之前中止。"""


class GateBlocked(RuntimeError):
    """材料被安全 Gate 拦截（受限/不可读/敏感等级未知）。"""


def _ensure(conn) -> None:
    conn.executescript(_DDL)
    # 本服务的核对表依赖 WP3 的义务表与 WP2 的认知卡表：
    # 未先跑过匹配时这些表可能尚不存在，必须一并确保，
    # 否则「只生成审核包」这条最轻的路径反而会因缺表崩掉。
    rq._ensure_schema(conn)
    cs._ensure_schema(conn)
    ms._ensure_schema(conn)
    conn.commit()


def _conn(db_path: Path | None = None):
    conn = mf._connect(db_path)
    _ensure(conn)
    return conn


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


# ── A3（G-A3-2 / G-A3-5 / H-3）：审核包与交付包共用的「组包计划」────────────
def _related_map(candidates: list[dict], db_path: Path | None = None) -> dict:
    """``file_id → related_files 相对路径列表``（只认认知卡里**显式**列出的）。"""
    out: dict[str, list[str]] = {}
    for c in candidates or []:
        fid = str(c.get("file_id") or "")
        if not fid or fid in out:
            continue
        card = cs.get_card(fid, db_path=db_path)
        fields = (card or {}).get("fields") or {}
        raw = (fields.get("related_files") or {}).get("value") or []
        out[fid] = [str(x) for x in raw] if isinstance(raw, list) else []
    return out


def _candidate_type_map(candidates: list[dict], db_path: Path | None = None) -> dict:
    """``file_id → 材料自己命中的全部规范类型``（★ P0-1 的类型闸输入）。

    ★ **为什么必须是「材料自己的类型」**：组包链过去按**整段的类型归属**
      给材料定类型 ⇒ 段内**可外发类**的材料被按另一类判定（PR #81 登记缺口 G5），
      且**认不出类型**的材料（认知卡 doc_type 空）会被当成「看起来像」的答案
      ⇒ 同一份无关材料被反复当成多条义务的答案。
    ★ 类型口径**只有一份**：走 ``dd_v1_card_service.doc_types_key``
      （旧卡无多值字段时自动退回单值主类型；认不出就是认不出 ⇒ 空列表）。
    """
    out: dict[str, list[str]] = {}
    for c in candidates or []:
        fid = str(c.get("file_id") or "")
        if not fid or fid in out:
            continue
        card = cs.get_card(fid, db_path=db_path)
        out[fid] = list(cs.doc_types_key(card) or [])
    return out


def _entity_display_map(rows: list[dict]) -> tuple[dict, dict]:
    """主体范围 → **稳定代号**（★ H-3：审核包不得带出客户标识）。

    ★ 判定「这个值是不是客户标识」**只用** ``rq.entity_scope_value()``
      ——判定层已有的**唯一**脱敏口径；本模块**不另写第二套**。
    ★ 代号按**首次出现顺序**分配（``主体-1``、``主体-2``……）⇒ 同一主体全表一致。
    ★ **列里不出现任何原值**（连范围类型也不出现）——原值只作内存里的分组键。
    """
    codes: dict[str, str] = {}
    stats = {"scopes": 0, "masked": 0}
    n = 0
    for r in rows or []:
        raw = str(r.get("entity_scope") or "").strip()
        if not raw or raw in codes:
            continue
        stats["scopes"] += 1
        if rq.entity_scope_value(raw) != raw:
            stats["masked"] += 1
        n += 1
        codes[raw] = f"主体-{n}"
    return codes, stats


#: 受限/不可交付原因的**分类**（G-A3-5：受限与「不存在」必须分开报）
_BLOCKED_CATEGORIES = (
    ("披露不可外发", "受限（披露策略判定不可外发）"),
    ("敏感等级", "受限（敏感等级未知）"),
    ("解析状态", "不可读/解析失败"),
    ("无材料认知卡", "受限（无认知卡，敏感等级不可判定）"),
    ("索引/目录件", "索引件（非材料）"),
    ("源文件已不存在", "源文件不存在"),
    ("目标越界", "越界拦截（安全跳过）"),
    # ★ P0-2：逐条义务**未过交付闸**（判定非 MATCHED 且无人工逐条确认）
    #   ⇒ 单独成一类，**不得**与「材料根本不存在」混同。
    ("审核闸未通过", "审核闸未通过（逐条义务未过闸）"),
)


def _disclosure_diagnosis(file_id: str, row: dict, db_path: Path | None = None) -> dict:
    """披露**四方归因**（★ P0-3）：谁拦的、为什么拦、按设计还是误分类。

    ★ 复用判定层的 ``dd_v1_match_service.diagnose_disclosure``（**唯一**口径），
      本模块**不另写**一套披露判定。
    """
    try:
        card = cs.get_card(file_id, db_path=db_path)
        conn = mf._connect(db_path)
        mrow = conn.execute(
            "SELECT * FROM dd_v1_manifest WHERE file_id=?", (file_id,)).fetchone()
        return ms.diagnose_disclosure(card, dict(mrow) if mrow else None,
                                      obligation={
                                          "doc_type": row.get("doc_type") or "",
                                      "obligation": row.get("obligation") or "",
                                      "obligation_id": row.get("obligation_id") or "",
                                      "entity_scope": row.get("entity_scope") or "",
                                      "period_from": row.get("period_from") or 0,
                                      "period_to": row.get("period_to") or 0,
                                      "period_basis": row.get("period_basis") or "",
                                      })
    except Exception as exc:  # noqa: BLE001 — 归因失败**不得**阻断组包
        logger.warning("披露归因失败（%s）：%s", file_id, exc)
        return {"error": str(exc)}


def _disclosure_trace(diag: dict | None) -> dict:
    """把披露四方归因**摊平**成可写进清单的一行（WP4：放行/拦截都要留依据）。

    ★ 口径来自判定层的 ``diagnose_disclosure``（**唯一**来源），本模块不另写一套。
    ★ 放行侧（``blocked_by`` 为空）同样留证：**是哪条规则允许它外发**
      （策略版本 / 等级 / 可外发类型清单 / 是否走了逐份书面授权）。
    """
    d = diag or {}
    four = d.get("four_dimensions") if isinstance(d.get("four_dimensions"), dict) else {}
    pol = four.get("policy") if isinstance(four.get("policy"), dict) else {}
    if not pol and isinstance(d.get("policy"), dict):
        pol = d["policy"]
    return {
        "blocked_by": str(d.get("blocked_by") or ""),
        "blocked_kind": str(d.get("blocked_kind") or ""),
        "blocked_reason": str(d.get("blocked_reason") or ""),
        "level": str(pol.get("level") or ""),
        "policy_version": str(pol.get("version") or d.get("policy_version") or ""),
        "sendable_doc_types": ",".join(pol.get("sendable_doc_types") or []),
        "authorized": ("是" if d.get("external_send_authorized") else "否"),
        "authorized_by": str(d.get("authorization_granted_by") or ""),
    }


def _yn(value) -> str:
    """匹配标志 → 清单里的「是 / 否」（**不**写 1/0，避免与「未判定」混淆）。"""
    if value is None or value == "":
        return "未判定"
    return "是" if int(value) else "否"


def _blocked_category(reason: str) -> str:
    """把拦截原因归类（原始原因**一并保留**，分类只是给人看的标签）。"""
    text = str(reason or "")
    for key, label in _BLOCKED_CATEGORIES:
        if key in text:
            return label
    return "受限/不可交付"


# ── P0-2：逐条义务的**交付闸** ────────────────────────────────────────────
def _candidate_identity(cand: dict, db_path: Path | None = None) -> dict:
    """候选材料的**六件套**身份（WP1）：原始路径 / 文件名 / SHA256 / 主体 / 期间 / 类型。

    ★ 口径全部来自**已有产物**（manifest 行 + 认知卡），**不重算**：
      - ``rel_path`` ＝ 库内相对路径（原始材料的位置）；
      - ``file_name`` ＝ 原始文件名；
      - ``sha256`` ＝ 扫描时算出的内容哈希（``dd_v1_manifest.content_hash``）；
      - ``entity`` / ``period`` / ``doc_type`` ＝ 认知卡上的材料自身属性。
    ★ SHA256 取**扫描时的**哈希（不是此刻重算的）—— 两者不等正是
      「材料在审核后被改过」的信号（见 :func:`_stale_materials`）。
    """
    out = {"orig_rel_path": "", "file_name": "", "sha256": "",
           "material_entity": "", "material_period": "", "material_doc_type": "",
           "material_sensitivity": "", "material_doc_types": ""}
    fid = str(cand.get("file_id") or "")
    if not fid:
        return out
    try:
        conn = mf._connect(db_path)
        mrow = conn.execute(
            "SELECT * FROM dd_v1_manifest WHERE file_id=?", (fid,)).fetchone()
    except Exception:  # noqa: BLE001
        mrow = None
    if mrow is not None:
        out["orig_rel_path"] = str(mrow["rel_path"] or "")
        out["file_name"] = str(mrow["file_name"] or "")
        out["sha256"] = str(mrow["content_hash"] or "")
    card = cs.get_card(fid, db_path=db_path) or {}
    out["material_entity"] = str(card.get("entity") or "")
    out["material_period"] = str(card.get("fiscal_period") or "")
    out["material_doc_type"] = str(card.get("doc_type") or "")
    out["material_sensitivity"] = str(card.get("sensitivity") or "")
    out["material_doc_types"] = ",".join(cs.doc_types_key(card) or [])
    return out


def _required_parts_of(o: dict) -> list[str]:
    """义务的**必备 part**——取法唯一（requirement_service 的 ``required_parts_of``）。"""
    return rq.required_parts_of(o)


def _count_reading(row: dict) -> dict:
    """**应交 / 找到 / 缺**（WP3-c）——显式三段式，复核者不必自己算。

    ★ 两个轴**分开算、合并显示**（父席口径：part 维与 count 维不是一条）：
      - **主件份数**（count 维）：``expected_count``（清单明文份数）或
        「去冗余 1 份主件」；
      - **必备附件**（attachment 维）：``needs_attachments`` ⇒ 应交 1 个附件。
    ★ 找到的份数 = **选中集合**里可交付的件数（主件 + 显式附件）。
    ★ **找到 1 份不得判这条完成** —— 份数维的门槛判定在判定层
      （``qc_service.count_dimension``）已经按 N 判；这里只负责**如实报数**。
    """
    expected_raw = row.get("expected_count")
    if expected_raw is None:
        primary_required = None          # 不可判定（清单提了份数但数不出）
    else:
        try:
            n = int(expected_raw)
        except (TypeError, ValueError):
            n = 0
        primary_required = n if n > 0 else 1   # 未规定 ⇒ 去冗余 1 份主件
    # ★ 必备 **part**（正文之外的组成部分）——「（含附注）」这类要求。
    #   part 维与份数维是**两条轴**（份数＝一式几份；part＝一件里几部分）。
    part_required = list(row.get("required_parts") or [])
    attach_required = 1 if row.get("needs_attachments") else 0

    # ★ 「找到」的**口径**＝ **对得上**（主体/期间/类型都对得上）的件数，
    #   **不是**「已选中」的件数 —— 两者是两回事：
    #     - 「找到」回答的是**材料在不在、对不对得上**（缺口清单的口径）；
    #     - 「可交付」回答的是**能不能外发**（披露闸的口径，单独报）。
    #   ⇒ 把两者混在一起会得出「齐备」却一件都交不出去的自相矛盾结论。
    _matched = [c for c in (row.get("candidates") or [])
                if int(c.get("entity_ok") or 0)
                and int(c.get("period_ok") or 0)
                and int(c.get("doctype_ok") or 0)]
    _part_set = set(part_required)
    primary_found = sum(1 for c in _matched
                        if str(c.get("material_part") or "") not in _part_set)
    part_found = sum(1 for c in _matched
                     if str(c.get("material_part") or "") in _part_set)
    selected = row.get("selected") or []
    selected_count = len(selected)
    deliverable_found = sum(1 for c in _matched if c.get("deliverable"))

    if primary_required is None:
        total_required = None
        total_found = primary_found + part_found
        total_missing = None
        status = "不可判定（清单提及份数但无法解析出权威份数）"
    else:
        total_required = primary_required + len(part_required) + attach_required
        total_found = primary_found + part_found
        total_missing = max(0, total_required - total_found)
        status = "齐备" if total_missing == 0 else "缺件"
    return {
        "count_primary_required": primary_required,
        "count_primary_found": primary_found,
        "count_part_required": len(part_required),
        "count_part_found": part_found,
        "count_missing_parts": list(row.get("missing_parts") or []),
        "count_attach_required": attach_required,
        "count_attach_found": 0,
        # ★ 「找到」与「可交付」**分开报**（不混成一个数）
        "count_selected": selected_count,
        "count_deliverable": deliverable_found,
        "count_total_required": total_required,
        "count_total_found": total_found,
        "count_total_missing": total_missing,
        "count_status": status,
        "count_reading": (
            f"应交 {total_required if total_required is not None else '不可判定'}"
            f" / 找到 {total_found}"
            f" / 缺 {total_missing if total_missing is not None else '不可判定'}"
        ),
        "count_reading_full": (
            f"应交 {total_required if total_required is not None else '不可判定'}"
            f" / 找到 {total_found}"
            f" / 缺 {total_missing if total_missing is not None else '不可判定'}"
            f"（其中可交付 {deliverable_found} 件；已选中 {selected_count} 件）"
        ),
    }


def _confirmations_map(review_id: str, db_path: Path | None = None) -> dict:
    """``obligation_id → 人工逐条确认记录``（本审核单维度，跨审核单不通用）。"""
    if not review_id:
        return {}
    conn = _conn(db_path)
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT * FROM dd_v1_review_confirmations WHERE review_id=?", (review_id,)
    ).fetchall():
        out[str(r["obligation_id"])] = dict(r)
    return out


def _delivery_gate(row: dict, confirmations: dict) -> dict:
    """一条义务**能不能进正式交付包**（逐条判定，不是一刀切）。

    返回 ``{"gate", "gate_basis", "gate_reason"}``。

    ★ 三道闸**取其严**（任一不过 ⇒ 不过）：

    1. **判定闸**：默认只有 ``MATCHED`` 放行；其余判定（UNCERTAIN / PARTIAL /
       MISSING / STALE / CONFLICT / RESTRICTED）**默认不进**正式交付包
       ——「不确定 ⇒ 不进正式交付包」是**默认**，不是例外。
    2. **人工逐条确认闸**：本审核单上若有人对该条义务写了确认人 + 理由，
       则该条**可**放行（可追责、逐条、只落 review_id 维度）。
       ★ 本函数**只管**前两道；**披露闸**（受限 / 不可读 / 敏感等级未知）
         在复制那一层单独执行 ⇒ 人工确认**不能**绕过受限事实。
    """
    verdict = str(row.get("verdict") or "")
    obl_id = str(row.get("obligation_id") or "")
    if verdict in GATE_DEFAULT_PASS_VERDICTS:
        return {
            "gate": GATE_PASS,
            "gate_basis": "verdict",
            "gate_reason": f"判定={verdict}（四维全覆盖且无冲突）",
        }
    conf = (confirmations or {}).get(obl_id)
    if conf:
        return {
            "gate": GATE_PASS,
            "gate_basis": "human_confirmation",
            "gate_reason": (f"人工逐条确认放行（确认人={conf.get('confirmed_by') or ''}，"
                            f"理由={conf.get('reason') or ''}）"),
        }
    return {
        "gate": GATE_BLOCKED,
        "gate_basis": "",
        "gate_reason": (f"逐条义务未过审核闸（判定={verdict or 'UNKNOWN'}）："
                        f"不确定/未齐套 ⇒ 默认不进正式交付包"
                        f"（需人工逐条确认后方可放行）"),
    }


def confirm_obligation(
    review_id: str,
    obligation_id: str,
    confirmed_by: str,
    reason: str = "",
    db_path: Path | None = None,
) -> dict:
    """人工**逐条**确认一条义务可以进正式交付包（P0-2 的第二道闸）。

    ★ 必须写明确认人与理由（可追责）——「不确定就放行」必须留下是谁放行的。
    ★ 一次确认**只**落 ``review_id`` 维度 ⇒ **不**升级为全局规则
      （与 ``record_edit`` 同原则；跨任务复用属 WP5 且必须经 Gate）。
    ★ 记录确认会把单据打回 ``reviewed`` ⇒ **必须重新批准**才能组包
      （「批完再改」是常见越权口子，见 ``test_editing_resets_approval``）。
    ★ 本确认**不能**让受限材料进交付包——披露闸在复制那一层独立执行。
    """
    if not str(confirmed_by or "").strip():
        raise ValueError("confirmed_by 不能为空：逐条确认必须有可追责的人")
    if not str(reason or "").strip():
        raise ValueError("reason 不能为空：逐条确认必须写明为什么可以放行")
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_reviews WHERE review_id=?", (review_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"审核单不存在：{review_id}")
    if row["status"] == ST_PACKAGED:
        raise ValueError("已组包，不可再逐条确认")
    obl = conn.execute(
        "SELECT obligation_id FROM dd_v1_obligations WHERE obligation_id=?",
        (obligation_id,)).fetchone()
    if obl is None:
        raise KeyError(f"义务不存在：{obligation_id}")
    now = time.time()
    conn.execute(
        """INSERT INTO dd_v1_review_confirmations
           (confirm_id, review_id, obligation_id, verdict, confirmed_by, reason, created_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(review_id, obligation_id) DO UPDATE SET
             verdict=excluded.verdict, confirmed_by=excluded.confirmed_by,
             reason=excluded.reason, created_at=excluded.created_at""",
        (uuid.uuid4().hex, review_id, obligation_id,
         str((ms.get_status(obligation_id, db_path=db_path) or {}).get("verdict") or ""),
         str(confirmed_by).strip(), str(reason).strip(), now),
    )
    conn.execute(
        "UPDATE dd_v1_reviews SET status=?, updated_at=? WHERE review_id=?",
        (ST_REVIEWED, now, review_id))
    conn.commit()
    return {
        "review_id": review_id,
        "obligation_id": obligation_id,
        "confirmed_by": str(confirmed_by).strip(),
        "reason": str(reason).strip(),
        "promoted_to_global_rule": False,
    }


def list_confirmations(review_id: str, db_path: Path | None = None) -> list[dict]:
    """本审核单上的人工逐条确认清单（可审计）。"""
    conn = _conn(db_path)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM dd_v1_review_confirmations WHERE review_id=? ORDER BY created_at",
        (review_id,))]


def _build_rows(library_id: str, db_path: Path | None = None,
                review_id: str = "") -> list[dict]:
    """逐义务算出：判定 + 候选 + **选中集合** + **交付闸结论**。

    ★ 审核包（``build_review_pack``）与交付包（``package_approved``）
      **共用这一份计划** ⇒ 人工审阅的集合 = 实际交付的集合，
      不会出现「审的是 A、交的是 B」。
    ★ ``review_id`` 传入时，人工逐条确认（``confirm_obligation``）才会生效；
      审核包刚建出来时**还没有**任何确认 ⇒ 核对表里如实显示「未过闸」。
    """
    conn = _conn(db_path)
    confirmations = _confirmations_map(review_id, db_path) if review_id else {}
    obl_rows = [dict(r) for r in conn.execute(
        "SELECT o.*, i.item_no, i.raw_text FROM dd_v1_obligations o "
        "LEFT JOIN dd_v1_checklist_items i ON i.item_uid=o.item_uid "
        "WHERE o.library_id=? ORDER BY i.item_no, o.seq", (library_id,))]

    rows: list[dict] = []
    for o in obl_rows:
        st = ms.get_status(o["obligation_id"], db_path=db_path) or {}
        cands = ms.list_matches(o["obligation_id"], db_path=db_path)
        related = _related_map(cands, db_path) if o.get("needs_attachments") else {}
        # ★ P0-1：把材料**自己**命中的类型集传进选中层
        #   （类型闸要判「材料是不是那一类」，不能只看段落的类型归属）。
        cand_types = _candidate_type_map(cands, db_path)
        sel = selsvc.select_for_obligation(o, cands, related=related,
                                           cand_types=cand_types)
        row = {
            "item_no": o.get("item_no") or "",
            "raw_text": o.get("raw_text") or "",
            "obligation": o["obligation"],
            "obligation_id": o["obligation_id"],
            # ★ WP1：义务的**稳定 ID**（可复算、不随排序变）
            "obligation_key": o.get("obligation_key") or o["obligation_id"],
            "entity_scope": o["entity_scope"],
            "entity_basis": o["entity_basis"],
            "period": f"{o['period_from']}-{o['period_to']}" if o["period_from"] else "",
            "period_from": o.get("period_from") or 0,
            "period_to": o.get("period_to") or 0,
            "period_basis": o["period_basis"],
            "doc_type": o["doc_type"],
            "doc_type_basis": o["doc_type_basis"],
            "expected_count": o.get("expected_count", 0),
            "expected_count_basis": o.get("expected_count_basis") or "",
            "needs_attachments": o.get("needs_attachments", 0),
            "attachment_basis": o.get("attachment_basis") or "",
            # ★ WP3-c：必备 part（正文之外的组成部分）
            "required_parts": _required_parts_of(o),
            "verdict": st.get("verdict", "UNMATCHED"),
            "entity_cov": st.get("entity_cov", 0),
            "period_cov": st.get("period_cov", 0),
            "doctype_cov": st.get("doctype_cov", 0),
            "need_entities": st.get("need_entities", 0),
            "need_periods": st.get("need_periods", 0),
            "missing_detail": st.get("missing_detail", ""),
            "candidate_count": st.get("candidate_count", 0),
            # ★ WP3-d：候选上限的读数（触顶时能报「还有 N 份未看」）
            "candidate_cap": st.get("candidate_cap", 0),
            "truncated_candidate_count": st.get("truncated_candidate_count", 0),
            "capped": st.get("capped", 0),
            "candidates": [
                {
                    "file_id": c["file_id"],
                    "rel_path": c.get("card_rel_path") or "",
                    "title": c.get("card_title") or "",
                    "score": c["score"],
                    "deliverable": bool(c["deliverable"]),
                    "evidence": c.get("evidence", ""),
                    # ★ 判定层的四维命中（展示层据此算「找到」的口径）
                    "entity_ok": c.get("entity_ok", 0),
                    "period_ok": c.get("period_ok", 0),
                    "doctype_ok": c.get("doctype_ok", 0),
                    "attachment_ok": c.get("attachment_ok", 0),
                    # ★ WP3-c：材料是正文还是附注/附录
                    "material_part": c.get("material_part", ""),
                    # ★ WP1：候选材料的**六件套**（原始路径 / 文件名 / SHA256 /
                    #   主体 / 期间 / 类型）—— 复核者据此可独立复算与核对。
                    **_candidate_identity(c, db_path),
                } for c in cands
            ],
            "selected": sel["selected"],
            "unselected": sel["unselected"],
            "selection_rule": sel["rule"],
            "target_reason": sel["target_reason"],
            "count_pending": sel["count_pending"],
            # ★ WP3-c：必备 part 的要求 / 已找到 / 缺
            "missing_parts": sel.get("missing_parts") or [],
            "found_parts": sel.get("found_parts") or [],
        }
        # ★ WP3-c：**应交 / 找到 / 缺**（显式三段式，不让复核者自己算）
        row.update(_count_reading(row))
        # ★ P0-2：逐条义务的**交付闸**结论（默认 fail-closed）
        row.update(_delivery_gate(row, confirmations))
        rows.append(row)

    codes, stats = _entity_display_map(rows)
    for r in rows:
        raw = str(r.get("entity_scope") or "").strip()
        r["entity_display"] = codes.get(raw, "")
    return rows


# ── 1. 生成审核包（只读材料，不复制原件）─────────────────────────────────
def build_review_pack(
    library_id: str,
    institution: str = "",
    db_path: Path | None = None,
) -> dict:
    """生成审核包：核对表 / 缺口清单 / 证据说明 / Manifest+hash。

    **绝不复制任何原件**——这一步只是让人看清楚系统判了什么、依据是什么。
    """
    conn = _conn(db_path)
    review_id = uuid.uuid4().hex
    now = time.time()

    # ★ A3（G-A3-2）：逐义务的「判定 + 候选 + 选中集合」由 _build_rows 统一算，
    #   审核包与交付包**共用同一份计划** ⇒ 审的 = 交的。
    # ★ 传入本审核单的 review_id ⇒ 核对表里显示的交付闸结论与组包时**同一口径**
    #   （刚建出来时还没有任何人工确认 ⇒ 非 MATCHED 的行如实显示「未过闸」）。
    rows = _build_rows(library_id, db_path, review_id=review_id)

    out_dir = fos_paths.get_dd_v1_data_dir() / "reviews" / review_id
    out_dir.mkdir(parents=True, exist_ok=True)
    written = _write_pack_files(out_dir, review_id, rows)
    # ★ WP5：候选包输出**前五项**（①–⑤）＋ 候选验证信息；
    #   ★ **不生成**正式交付件（⑥⑦ 与原件复制都在授权之后才发生）。
    # ★ WP2：候选包必须**显式标注「非正式交付」**，且与正式交付包**物理隔离**。
    _chain = _write_delivery_chain(
        out_dir, rows, [], [], [], {"review_id": review_id}, {},
        db_path=db_path)
    written.extend(_chain)
    (out_dir / "非正式交付-候选包说明.md").write_text(
        "# 非正式交付 · 候选包（审核包）\n\n"
        f"- 审核单：{review_id}\n"
        f"- 机构：{institution or '（未填）'}\n"
        f"- 义务数：{len(rows)}\n"
        "- ★★ **本目录是候选包（审核包），不是正式交付件。**\n"
        "  - 本目录**只读材料、零复制**：里面没有任何原件副本。\n"
        "  - 未经人工最终批准（approve + package_approved），"
        "**不会**产生正式交付包。\n"
        "  - 正式交付包落在**另一个平级目录** "
        "`<data_dir>/deliveries/<review_id>/` ⇒ **物理隔离**，不得混用。\n"
        "- 本目录含 WP5 交付链的前五项产出：\n"
        "  ① 输入需求清单 ② 检索材料清单 ③ 匹配结果及理由\n"
        "  ④ 缺失/冲突/不确定清单 ⑤ 人工审核记录\n"
        "- ★ 候选验证信息（`匹配核对表.xlsx` / `证据与完整性说明.md` / "
        "`交付清单与hash核验.tsv`）只用于**人工核对**，不构成交付。\n",
        encoding="utf-8")
    written.append("非正式交付-候选包说明.md")

    conn.execute(
        """INSERT INTO dd_v1_reviews
           (review_id, library_id, institution, status, created_at, updated_at, pack_path)
           VALUES (?,?,?,?,?,?,?)""",
        (review_id, library_id, institution, ST_DRAFT, now, now, str(out_dir)),
    )
    conn.commit()

    tally: dict[str, int] = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    return {
        "review_id": review_id,
        "library_id": library_id,
        "status": ST_DRAFT,
        "obligations": len(rows),
        "by_verdict": tally,
        # ★ P0-2：审核包里**如实**显示有几条义务过不了交付闸
        #   （默认只有 MATCHED 能过 ⇒ 审核人一眼看出哪些需要逐条确认）。
        "gate_passed": sum(1 for r in rows if r.get("gate") == GATE_PASS),
        "gate_blocked": sum(1 for r in rows if r.get("gate") == GATE_BLOCKED),
        "pack_path": str(out_dir),
        "files": written,
        "copied_source_files": 0,
        "note": ("审核包只读材料、零复制；复制原件必须经 approve + package_approved；"
                 "★ 未过交付闸的义务（默认只有 MATCHED 过）不进正式交付包，"
                 "需人工逐条确认（confirm_obligation）后方可放行"),
    }


def _count_label(r: dict) -> str:
    """核对表里「应有份数」列的文案（三态：A3-1）。"""
    v = r.get("expected_count")
    if v is None:
        return "不可判定（待人工确认）"
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "清单未规定"
    return f"{n} 份"


# ══════════════════════════════════════════════════════════════════════
# ★ WP5：真实交付链的 7 项产出（缺一不可）＋ 逐件可追溯
# ══════════════════════════════════════════════════════════════════════
#
# ★ 7 项产出（波总点名，缺一不可）：
#   ① 输入需求清单   ② 检索材料清单   ③ 匹配结果及理由
#   ④ 缺失/冲突/不确定清单  ⑤ 人工审核记录  ⑥ 实际交付文件目录
#   ⑦ 文件完整性校验结果
#
# ★ 每份交付文件必须可追溯：**原始材料 → 匹配义务 → 审核结论 → 交付位置**
#   ⇒ 由 ``03-匹配结果及理由.tsv`` ＋ ``组包manifest.tsv`` 两条链承载，
#     每一行都带 file_id / 义务ID / 判定 / 审核结论 / 交付路径 / 两侧 SHA256。
#
# ★ **未获得有效审核授权时，只能输出前五项 ＋ 候选验证信息**，
#   **不得生成正式交付件**（⑥⑦ 与原件复制都在授权之后才发生）。
DELIVERY_ARTIFACTS = (
    "01-输入需求清单.tsv",
    "02-检索材料清单.tsv",
    "03-匹配结果及理由.tsv",
    "04-缺失冲突不确定清单.tsv",
    "05-人工审核记录.tsv",
    "06-实际交付文件目录.tsv",
    "07-文件完整性校验结果.tsv",
)


def _write_delivery_chain(
    out_dir: Path, rows: list[dict], exported: list[dict],
    blocked: list[dict], gate_blocked_rows: list[dict],
    review: dict, confirmations: dict, db_path: Path | None = None,
) -> list[str]:
    """写 WP5 的 7 项产出（**在授权之后**才写 ⑥⑦）。"""
    written: list[str] = []

    # ── ① 输入需求清单 ───────────────────────────────────────────────
    lines = ["机构编号\t原文\t原子义务\t义务ID\t主体范围\t主体出处\t期间\t期间出处"
             "\t材料类型\t类型出处\t应有份数\t应有附件\t判定\t应交\t找到\t缺\t交付闸"]
    for r in rows:
        lines.append("\t".join(str(x) for x in (
            r.get("item_no") or "", r.get("raw_text") or "", r.get("obligation") or "",
            r.get("obligation_key") or r.get("obligation_id") or "",
            r.get("entity_display") or r.get("entity_scope") or "",
            r.get("entity_basis") or "", r.get("period") or "",
            r.get("period_basis") or "", r.get("doc_type") or "",
            r.get("doc_type_basis") or "", _count_label(r),
            r.get("count_attach_required") or 0, r.get("verdict") or "",
            r.get("count_total_required") if r.get("count_total_required") is not None
            else "不可判定",
            r.get("count_total_found") or 0,
            r.get("count_total_missing") if r.get("count_total_missing") is not None
            else "不可判定",
            r.get("gate") or "")))
    (out_dir / "01-输入需求清单.tsv").write_text("\n".join(lines), encoding="utf-8")
    written.append("01-输入需求清单.tsv")

    # ── ② 检索材料清单（每份候选的六件套身份）─────────────────────────
    seen_files: dict[str, dict] = {}
    for r in rows:
        for c in r.get("candidates") or []:
            fid = c.get("file_id") or ""
            if fid and fid not in seen_files:
                seen_files[fid] = c
    lines = ["file_id\t原始路径\t文件名\tSHA256\t主体\t期间\t材料类型\t全部类型"
             "\t敏感等级\t被几条义务引用"]
    ref_count: dict[str, int] = {}
    for r in rows:
        for c in r.get("candidates") or []:
            fid = c.get("file_id") or ""
            if fid:
                ref_count[fid] = ref_count.get(fid, 0) + 1
    for fid in sorted(seen_files):
        c = seen_files[fid]
        lines.append("\t".join(str(x) for x in (
            fid, c.get("orig_rel_path") or c.get("rel_path") or "",
            c.get("file_name") or "", c.get("sha256") or "",
            c.get("material_entity") or "", c.get("material_period") or "",
            c.get("material_doc_type") or "", c.get("material_doc_types") or "",
            c.get("material_sensitivity") or "", ref_count.get(fid, 0))))
    (out_dir / "02-检索材料清单.tsv").write_text("\n".join(lines), encoding="utf-8")
    written.append("02-检索材料清单.tsv")

    # ── ③ 匹配结果及理由（**每一行**都可核）──────────────────────────
    lines = ["机构编号\t义务ID\t原子义务\tfile_id\t原始路径\tSHA256\t判定"
             "\t类型匹配\t主体匹配\t期间匹配\t匹配证据\t选中\t理由\t审核结论\t交付位置"]
    sel_by_obl: dict[str, dict] = {}
    for e in exported:
        sel_by_obl.setdefault(str(e.get("obligation_id") or ""), {})[
            str(e.get("file_id") or "")] = e
    for r in rows:
        obl_id = str(r.get("obligation_id") or "")
        for c in r.get("candidates") or []:
            fid = c.get("file_id") or ""
            sel = next((p for p in (r.get("selected") or [])
                        if p.get("file_id") == fid), None)
            exp = (sel_by_obl.get(obl_id) or {}).get(fid)
            lines.append("\t".join(str(x) for x in (
                r.get("item_no") or "", r.get("obligation_key") or obl_id,
                r.get("obligation") or "", fid,
                c.get("orig_rel_path") or c.get("rel_path") or "",
                c.get("sha256") or "", r.get("verdict") or "",
                _yn((sel or {}).get("doctype_ok")) if sel else "未选中",
                _yn((sel or {}).get("entity_ok")) if sel else "未选中",
                _yn((sel or {}).get("period_ok")) if sel else "未选中",
                (sel or {}).get("match_evidence") or "",
                "是" if sel else "否",
                (sel or {}).get("reason") or
                next((u.get("reason") for u in (r.get("unselected") or [])
                      if u.get("file_id") == fid), ""),
                r.get("gate") or "",
                (exp or {}).get("dest") or "")))
    (out_dir / "03-匹配结果及理由.tsv").write_text("\n".join(lines), encoding="utf-8")
    written.append("03-匹配结果及理由.tsv")

    # ── ④ 缺失/冲突/不确定清单 ───────────────────────────────────────
    lines = ["分类\t机构编号\t义务ID\t原子义务\t判定\t缺口明细\t候选数\t交付闸"]
    for r in rows:
        if r.get("verdict") in ("MATCHED",) and r.get("gate") == GATE_PASS:
            continue
        _cat = {"MISSING": "缺失", "CONFLICT": "冲突", "UNCERTAIN": "不确定",
                "PARTIAL": "不完整", "STALE": "过期", "RESTRICTED": "受限"}.get(
            str(r.get("verdict") or ""), str(r.get("verdict") or ""))
        lines.append("\t".join(str(x) for x in (
            _cat, r.get("item_no") or "", r.get("obligation_key") or "",
            r.get("obligation") or "", r.get("verdict") or "",
            r.get("missing_detail") or "", r.get("candidate_count") or 0,
            r.get("gate") or "")))
    (out_dir / "04-缺失冲突不确定清单.tsv").write_text("\n".join(lines),
                                                      encoding="utf-8")
    written.append("04-缺失冲突不确定清单.tsv")

    # ── ⑤ 人工审核记录（批准人 + 逐条确认 + 修改留痕）────────────────
    lines = ["记录类型\t义务ID\t原子义务\t人\t理由\t时间"]
    conn = _conn(db_path)
    rev_row = conn.execute(
        "SELECT approved_by, approved_at, review_note, status FROM dd_v1_reviews "
        "WHERE review_id=?", (review.get("review_id") or "",)).fetchone()
    if rev_row is not None:
        lines.append("\t".join(str(x) for x in (
            "单据批准", "", "", rev_row["approved_by"] or "",
            rev_row["review_note"] or f"状态={rev_row['status']}",
            rev_row["approved_at"] or "")))
    for obl_id, conf in (confirmations or {}).items():
        lines.append("\t".join(str(x) for x in (
            "逐条确认", obl_id, "", conf.get("confirmed_by") or "",
            conf.get("reason") or "", conf.get("created_at") or "")))
    try:
        for e in conn.execute(
                "SELECT obligation_id, action, edited_by, reason, edited_at "
                "FROM dd_v1_review_edits WHERE review_id=? ORDER BY edited_at",
                (review.get("review_id") or "",)).fetchall():
            lines.append("\t".join(str(x) for x in (
                "修改留痕:" + str(e["action"] or ""), e["obligation_id"] or "",
                "", e["edited_by"] or "", e["reason"] or "", e["edited_at"] or "")))
    except Exception:  # noqa: BLE001
        pass
    (out_dir / "05-人工审核记录.tsv").write_text("\n".join(lines), encoding="utf-8")
    written.append("05-人工审核记录.tsv")
    return written


def _evidence_text(raw) -> str:
    """把候选的 evidence（JSON 数组字符串）摊平成可读文本。"""
    text = str(raw or "")
    try:
        items = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(items, list):
        return "；".join(str(x) for x in items)
    return text


def _write_pack_files(out_dir: Path, review_id: str, rows: list[dict]) -> list[str]:
    """写核对表 / 缺口清单 / 证据说明 / Manifest+hash。全部在 Data Plane 内。"""
    written: list[str] = []

    # ── 1) Excel 匹配核对表 ────────────────────────────────────────────
    try:
        from openpyxl import Workbook  # noqa: PLC0415
        wb = Workbook()
        ws = wb.active
        ws.title = "匹配核对表"
        headers = ["机构编号", "机构原文", "原子义务", "义务稳定ID", "主体范围", "主体出处",
                   "期间", "期间出处", "材料类型", "类型出处", "判定",
                   "主体覆盖", "期间覆盖", "类型覆盖", "需主体数", "需期间数",
                   "缺口明细", "候选数", "候选上限", "被上限挡掉", "候选文件", "可交付",
                   # ★ A3（G-A3-1 / G-A3-2）：份数与**选中集合**
                   #   主体范围列写的是**稳定代号**（H-3 脱敏），不写原值
                   "应有份数", "选中件数", "选中文件", "选中理由",
                   "未选用文件", "未选用理由", "选中规则",
                   # ★ WP3-c：**应交 / 找到 / 缺**（显式三段式）
                   "应交", "找到", "缺", "份数状态",
                   # ★ P0-2：逐条义务的**交付闸**结论（默认只有 MATCHED 过）
                   "交付闸", "交付闸依据", "交付闸理由"]
        ws.append(headers)
        for r in rows:
            ws.append([
                r["item_no"], r["raw_text"], r["obligation"],
                r.get("obligation_key") or r.get("obligation_id") or "",
                r.get("entity_display", ""), r["entity_basis"], r["period"],
                r["period_basis"], r["doc_type"], r["doc_type_basis"],
                r["verdict"], r["entity_cov"], r["period_cov"],
                r["doctype_cov"], r["need_entities"], r["need_periods"],
                r["missing_detail"], r["candidate_count"],
                r.get("candidate_cap") or 0, r.get("truncated_candidate_count") or 0,
                "; ".join(c["rel_path"] for c in r["candidates"][:5]),
                "是" if any(c["deliverable"] for c in r["candidates"]) else "否",
                _count_label(r),
                len(r.get("selected") or []),
                "; ".join(p["rel_path"] for p in (r.get("selected") or [])),
                "; ".join(p["reason"] for p in (r.get("selected") or [])),
                "; ".join(u["rel_path"] for u in (r.get("unselected") or [])),
                "; ".join(u["reason"] for u in (r.get("unselected") or [])),
                r.get("selection_rule", ""),
                r.get("count_total_required")
                if r.get("count_total_required") is not None else "不可判定",
                r.get("count_total_found") or 0,
                r.get("count_total_missing")
                if r.get("count_total_missing") is not None else "不可判定",
                r.get("count_status", ""),
                r.get("gate", ""),
                r.get("gate_basis", ""),
                r.get("gate_reason", ""),
            ])
        p = out_dir / "匹配核对表.xlsx"
        wb.save(p)
        written.append(p.name)
    except Exception as exc:  # noqa: BLE001 — Excel 失败不阻断其余产物
        logger.warning("Excel 核对表生成失败：%s", exc)
        (out_dir / "匹配核对表.csv").write_text(
            "\n".join(
                "\t".join(str(r.get(k, "")) for k in
                          ("item_no", "raw_text", "obligation", "verdict", "missing_detail"))
                for r in rows), encoding="utf-8")
        written.append("匹配核对表.csv")

    # ── 2) 缺失与待确认清单（★ G-A3-5：受限与「不存在」**分区单列**）─────
    #   「材料存在但不可外发」与「材料根本不存在」是两回事，混在一起
    #   ⇒ 复核者会去追一份根本不存在的材料，而真正该处理的受限件被淹没。
    _sections = (
        ("一、材料根本不存在（MISSING）", ("MISSING",),
         "未检索到**满足本条要求**的材料；"
         "每条下面列出**实际候选池**（候选池里有的材料为什么不被选中，一并写明）"),
        ("二、材料不完整（PARTIAL）", ("PARTIAL",),
         "材料存在，但五维未齐（缺口明细已指名缺哪一维）"),
        ("三、材料存在但受限·不可外发（RESTRICTED）", ("RESTRICTED",),
         "材料在，但不可对外交付（原因逐条列出，不混入 MISSING）"),
        ("四、不可判定·待人工确认（UNCERTAIN）", ("UNCERTAIN",),
         "证据不足以判定，不得猜"),
        ("五、需人工裁定（CONFLICT）", ("CONFLICT",),
         "同主体同期内容冲突，必须人工裁定"),
        ("六、版本或期间不满足（STALE）", ("STALE",),
         "找到材料但版本/期间不满足当期要求"),
    )
    _gaps = [r for r in rows if r["verdict"] != "MATCHED"]
    _gate_blocked = [r for r in rows if r.get("gate") == GATE_BLOCKED]
    _lines = ["以下义务未达完整状态，需人工处理。判定口径见 Goal Contract 硬门槛。",
              f"未达完整状态义务数：{len(_gaps)}（总义务 {len(rows)}）", ""]
    # ★ P0-2：交付闸结论**单列**一段（与「材料不存在」严格分开）
    _lines.append(f"## 零、逐条交付闸未通过的义务（{len(_gate_blocked)} 条）")
    _lines.append("    默认只有判定=MATCHED 的义务能进正式交付包；"
                  "以下义务**不会**被复制进交付包，"
                  "需人工逐条确认（confirm_obligation）后方可放行。")
    if not _gate_blocked:
        _lines.append("    （无）")
    for r in _gate_blocked:
        _lines.append(f"  [{r['verdict']}] {r['item_no']} {r['obligation']}")
        _lines.append(f"    交付闸：{r.get('gate_reason', '')}")
    _lines.append("")
    for title, verdicts, blurb in _sections:
        bucket = [r for r in _gaps if r["verdict"] in verdicts]
        _lines.append(f"## {title}（{len(bucket)} 条）")
        _lines.append(f"    {blurb}")
        if not bucket:
            _lines.append("    （无）")
        for r in bucket:
            _lines.append(f"  [{r['verdict']}] {r['item_no']} {r['obligation']}")
            _lines.append(f"    缺口：{r['missing_detail'] or '（未提供明细）'}")
            if r["verdict"] == "RESTRICTED":
                _reasons = []
                for c in r["candidates"]:
                    if c["deliverable"]:
                        continue
                    ev = _evidence_text(c.get("evidence"))
                    _reasons.append(f"{c['rel_path']}：{_blocked_category(ev)}"
                                    f"（{ev or '未提供原因'}）")
                _lines.append(f"    受限原因：{'；'.join(_reasons) or '（未提供明细）'}")
            _lines.append(f"    候选："
                          f"{'; '.join(c['rel_path'] for c in r['candidates']) or '（无）'}")
            if r.get("count_pending"):
                _lines.append("    ★ 份数待人工确认：清单提及份数但无法解析出权威份数"
                              "（不得默认 1 份），本条不自动交付主件")
        _lines.append("")
    (out_dir / "缺口与待确认清单.txt").write_text("\n".join(_lines), encoding="utf-8")
    written.append("缺口与待确认清单.txt")

    # ── 3) 证据与完整性说明 ────────────────────────────────────────────
    (out_dir / "证据与完整性说明.md").write_text(
        "# 证据与完整性说明\n\n"
        "## 判定口径\n\n"
        "- 主体覆盖：权威名单中已被材料覆盖的主体占比。**无权威名单时判 UNCERTAIN**，\n"
        "  不用目录名凑数。\n"
        "- 期间覆盖：要求区间内已被覆盖的年份占比。**相对年份（如「近三年」）无锚定年时\n"
        "  不展开，判 UNCERTAIN**。\n"
        "- 必备附件与签章：认知卡字段目前恒 UNKNOWN，故这两个维度**必然不满足**——\n"
        "  这是已知缺口被如实暴露，不是数据问题。\n"
        "- 交付资格：解析失败、不可读、或敏感等级未知的材料**不进入交付目录**。\n"
        "- 逐条交付闸：默认**只有判定=MATCHED** 的义务能进正式交付包；\n"
        "  UNCERTAIN / PARTIAL / MISSING / STALE / CONFLICT / RESTRICTED 一律不进。\n"
        "  人工可对**具体某一条**义务写明确认人与理由来放行（confirm_obligation），\n"
        "  但**不能**绕过披露闸（受限 / 不可读 / 敏感等级未知的材料仍然不进交付包）。\n\n"
        "## 逐条说明\n\n" +
        "\n".join(
            f"### {r['item_no']} {r['obligation']}\n\n"
            f"- 判定：**{r['verdict']}**\n"
            f"- 交付闸：**{r.get('gate', '')}**（{r.get('gate_reason', '')}）\n"
            f"- 主体覆盖 {r['entity_cov']} / 期间覆盖 {r['period_cov']} / 类型覆盖 {r['doctype_cov']}\n"
            f"- 应有份数：{_count_label(r)}（{r.get('target_reason', '')}）\n"
            f"- 缺口：{r['missing_detail'] or '无'}\n"
            f"- 选中集合（{len(r.get('selected') or [])} 件）：\n" +
            ("\n".join(
                f"    - [选中·{p.get('role', '主件')}] {p['rel_path']}：{p['reason']}"
                for p in (r.get("selected") or [])) or "    （无）") + "\n"
            f"- 未选用（{len(r.get('unselected') or [])} 件，不进交付目录）：\n" +
            ("\n".join(
                f"    - [未选用] {u['rel_path']}：{u['reason']}"
                for u in (r.get("unselected") or [])) or "    （无）") + "\n"
            f"- 候选与证据：\n" +
            "\n".join(
                f"    - {c['rel_path']}（score={c['score']}, 可交付={'是' if c['deliverable'] else '否'}）"
                f" {c['evidence']}"
                for c in r["candidates"]) + "\n"
            for r in rows
        ), encoding="utf-8")
    written.append("证据与完整性说明.md")

    # ── 4) Manifest + hash 核验（此处只记录源文件 hash，不复制）─────────
    mpath = out_dir / "交付清单与hash核验.tsv"
    # ★ WP1：每份候选材料保留**六件套**（原始路径/文件名/SHA256/主体/期间/类型）
    lines = ["file_id\t原始路径\t文件名\tsha256\t主体\t期间\t材料类型\t全部类型"
             "\t敏感等级\tsize\t可交付\t选中\t阻断原因"]
    for r in rows:
        _sel_ids = {p.get("file_id") for p in (r.get("selected") or [])}
        for c in r["candidates"]:
            ev = c.get("evidence") or ""
            lines.append(f"{c['file_id']}\t{c.get('orig_rel_path') or c['rel_path']}\t"
                         f"{c.get('file_name') or ''}\t{c.get('sha256') or ''}\t"
                         f"{c.get('material_entity') or ''}\t"
                         f"{c.get('material_period') or ''}\t"
                         f"{c.get('material_doc_type') or ''}\t"
                         f"{c.get('material_doc_types') or ''}\t"
                         f"{c.get('material_sensitivity') or ''}\t\t"
                         f"{'是' if c['deliverable'] else '否'}\t"
                         f"{'是' if c['file_id'] in _sel_ids else '否'}\t{ev}")
    mpath.write_text("\n".join(lines), encoding="utf-8")
    written.append(mpath.name)

    return written


# ── 2. 人工修改留痕 ───────────────────────────────────────────────────────
def record_edit(
    review_id: str,
    action: str,
    edited_by: str,
    reason: str = "",
    obligation_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
    scope_entity: str = "",
    institution: str = "",
    template: str = "",
    db_path: Path | None = None,
) -> dict:
    """记录一次人工修改。**一次修改不得无条件升级为全局规则。"""
    if not edited_by.strip():
        raise ValueError("edited_by 不能为空：人工修改必须可追责")
    if not reason.strip():
        raise ValueError("reason 不能为空：人工修改必须写明原因")
    conn = _conn(db_path)
    edit_id = uuid.uuid4().hex
    now = time.time()
    conn.execute(
        """INSERT INTO dd_v1_review_edits
           (edit_id, review_id, obligation_id, action, before_json, after_json,
            reason, scope_entity, institution, template, version, edited_by, edited_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (edit_id, review_id, obligation_id, action,
         json.dumps(before or {}, ensure_ascii=False),
         json.dumps(after or {}, ensure_ascii=False),
         reason, scope_entity, institution, template, "v1", edited_by, now),
    )
    conn.execute(
        "UPDATE dd_v1_reviews SET status=?, updated_at=? WHERE review_id=?",
        (ST_REVIEWED, now, review_id))
    conn.commit()
    return {"edit_id": edit_id, "review_id": review_id, "action": action,
            "promoted_to_global_rule": False}


def list_edits(review_id: str, db_path: Path | None = None) -> list[dict]:
    conn = _conn(db_path)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM dd_v1_review_edits WHERE review_id=? ORDER BY edited_at",
        (review_id,))]


# ── 3. 人工批准 Gate（HG1 机器侧强制）────────────────────────────────────
def approve(review_id: str, approved_by: str, note: str = "",
            db_path: Path | None = None) -> dict:
    if not approved_by.strip():
        raise ValueError("approved_by 不能为空：交付必须有可追责的批准人")
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_reviews WHERE review_id=?", (review_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"审核单不存在：{review_id}")
    if row["status"] == ST_PACKAGED:
        raise ValueError("已组包，不可重复批准")
    now = time.time()
    conn.execute(
        """UPDATE dd_v1_reviews SET status=?, approved_by=?, approved_at=?,
           review_note=?, updated_at=? WHERE review_id=?""",
        (ST_APPROVED, approved_by, now, note, now, review_id))
    conn.commit()
    return {"review_id": review_id, "status": ST_APPROVED,
            "approved_by": approved_by, "approved_at": now}


def assert_approval(review_id: str, db_path: Path | None = None) -> dict:
    """组包前的强制检查。**不通过就抛异常，且必须在复制任何文件之前。**"""
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_reviews WHERE review_id=?", (review_id,)
    ).fetchone()
    if row is None:
        raise ApprovalRequired(f"审核单不存在：{review_id}")
    if row["status"] not in (ST_APPROVED, ST_PACKAGED):
        raise ApprovalRequired(
            f"审核单 {review_id} 当前状态为 {row['status']}，"
            f"未经人工最终批准，拒绝组包（HG1）")
    if not (row["approved_by"] or "").strip():
        raise ApprovalRequired(f"审核单 {review_id} 无批准人，拒绝组包（HG1）")
    return dict(row)


# ── 4. 组包（唯一会复制原件的入口）──────────────────────────────────────
def _default_delivery_dir(review_id: str) -> Path:
    """正式交付包的**默认目录**（WP2：与候选包**物理隔离**）。

    ★ 候选包（审核包）落在 ``<data_dir>/reviews/<review_id>/``；
      正式交付包落在 ``<data_dir>/deliveries/<review_id>/`` ——
      **两个平级目录**，不是父子关系 ⇒ 收件人不可能把候选件误当正式件。
    """
    return fos_paths.get_dd_v1_data_dir() / "deliveries" / str(review_id)


def _stale_materials(rows: list[dict], conn, db_path: Path | None = None) -> list[dict]:
    """**审核失效预检**（WP2）：材料在审核后被改过（SHA256 变了）⇒ 审核失效。

    ★ 判据：**此刻**重算源文件的 SHA256，与**扫描时**记在 manifest 里的
      ``content_hash`` 比对 ⇒ 不等即「材料变了」。
    ★ 只查**会进交付包**的件（选中件）——没选的件被改了不影响这次交付。
    ★ 返回**逐条**清单（可核），供交卷件与「审核失效清单.tsv」使用。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        if r.get("gate") == GATE_BLOCKED:
            continue
        for p in (r.get("selected") or []):
            fid = str(p.get("file_id") or "")
            if not fid or fid in seen:
                continue
            seen.add(fid)
            mrow = conn.execute(
                "SELECT * FROM dd_v1_manifest WHERE file_id=?", (fid,)).fetchone()
            if mrow is None:
                continue
            src = Path(str(mrow["abs_path"]))
            if not src.is_file():
                continue
            scanned = str(mrow["content_hash"] or "")
            current = _sha256(src)
            if scanned and current and scanned != current:
                out.append({
                    "file_id": fid,
                    "rel_path": str(mrow["rel_path"] or ""),
                    "scanned_sha256": scanned,
                    "current_sha256": current,
                    "verdict": str(r.get("verdict") or ""),
                    "reason": "源文件的 SHA256 与审核时的记录不一致 ⇒ 材料已变更",
                })
    return out


def package_approved(
    review_id: str,
    output_dir: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """按机构原编号组织目录并复制原件。**必须先通过人工批准。**"""
    review = assert_approval(review_id, db_path=db_path)   # ← 闸在前，复制在后
    conn = _conn(db_path)

    lib_root = Path(conn.execute(
        "SELECT root_path FROM dd_v1_libraries WHERE library_id=?",
        (review["library_id"],)).fetchone()["root_path"])

    out = Path(output_dir) if output_dir else _default_delivery_dir(review_id)
    # ★ WP2：候选包与正式交付包**物理隔离** —— 正式交付包**不得**落在
    #   审核包（候选包）目录里面。落在里面 ⇒ 收件人分不清哪个是正式件、
    #   候选包里的清单/说明也会被当成交付内容一起发出去。
    _review_pack_dir = Path(str(review.get("pack_path") or "")).resolve()
    if _review_pack_dir and str(_review_pack_dir) not in ("", "."):
        try:
            _out_res = out.resolve()
        except OSError:
            _out_res = out
        if _out_res == _review_pack_dir or _review_pack_dir in _out_res.parents:
            raise ValueError(
                f"正式交付包目录必须与候选包（审核包）物理隔离："
                f"交付目录 {out} 位于候选包目录 {_review_pack_dir} 之内 ⇒ 拒绝组包")
    out.mkdir(parents=True, exist_ok=True)

    exported: list[dict] = []
    blocked: list[dict] = []
    gate_blocked_rows: list[dict] = []

    # ★ A3（G-A3-2）：交付集合 = **选中件** + 必备附件，**不是全部候选**。
    #   计划与审核包**共用**（_build_rows）⇒ 人工审阅的集合 = 实际交付的集合。
    # ★ P0-2：传入 review_id ⇒ 人工逐条确认在组包时生效。
    rows = _build_rows(review["library_id"], db_path, review_id=review_id)
    unselected_rows: list[dict] = []

    # ★★ WP2：**审核失效预检** —— 审核通过后材料若发生变化（SHA256 变了），
    #   审核结论已不成立 ⇒ **强制重新审核**，本次**不得**产出正式交付件。
    #   ⇒ 预检**先于**任何复制（fail-closed：不复制一件原件）。
    stale = _stale_materials(rows, conn, db_path)
    if stale:
        now = time.time()
        (out / "审核失效清单.tsv").write_text(
            "file_id\t原始路径\t审核时SHA256\t当前SHA256\t判定\t原因\n" +
            "\n".join(
                f"{s['file_id']}\t{s['rel_path']}\t{s['scanned_sha256']}\t"
                f"{s['current_sha256']}\t{s['verdict']}\t{s['reason']}"
                for s in stale), encoding="utf-8")
        conn.execute(
            "UPDATE dd_v1_reviews SET status=?, updated_at=? WHERE review_id=?",
            (ST_REVIEWED, now, review_id))
        conn.commit()
        return {
            "review_id": review_id,
            "status": ST_REVIEWED,
            "review_invalidated": True,
            "stale_materials": stale,
            "stale_material_count": len(stale),
            "exported": 0,
            "copied_source_files": 0,
            "output_dir": str(out),
            "reason": ("审核通过后材料发生变化（SHA256 与审核时不一致）⇒ "
                       "审核失效 ⇒ 强制重新审核；本次**未复制任何原件**、"
                       "**未产出正式交付件**"),
            "note": ("材料被改过 ⇒ 之前的审核结论已不成立 ⇒ "
                     "必须重新核对并重新批准后才能组包"),
        }

    for r in rows:
        for u in (r.get("unselected") or []):
            unselected_rows.append({
                "item_no": r["item_no"] or "",
                "obligation": r["obligation"],
                "file_id": u["file_id"],
                "rel_path": u["rel_path"],
                "reason": u["reason"],
            })
        # ★ G-A3-5：受限/不可交付的候选**单独分类**记录，不与「不存在」混同
        for c in r["candidates"]:
            if c["deliverable"]:
                continue
            ev = _evidence_text(c.get("evidence"))
            blocked.append({
                "obligation": r["obligation"],
                "file_id": c["file_id"],
                "rel_path": c["rel_path"],
                "category": _blocked_category(ev),
                "reason": ev or "受限/不可读/敏感等级未知",
                # ★ P0-3：**四方归因**（谁拦的、为什么拦、按设计还是误分类）
                "disclosure_diagnosis": _disclosure_diagnosis(c["file_id"], r, db_path),
            })
        sel = r.get("selected") or []

        # ★★ P0-2：逐条义务的**交付闸** —— 不过闸 ⇒ **一件都不复制**。
        #   「人工批量批准」≠「全部放行」：单据批准只是**单据级**放行，
        #   逐条义务仍要各自过闸（默认只有 MATCHED 过）。
        if r.get("gate") == GATE_BLOCKED:
            gate_blocked_rows.append({
                "item_no": r["item_no"] or "",
                "obligation_id": r.get("obligation_id") or "",
                "obligation": r["obligation"],
                "verdict": r["verdict"],
                "gate_reason": r.get("gate_reason") or "",
                "would_deliver": len(sel),
                "candidates": [
                    {"file_id": p.get("file_id") or "",
                     "rel_path": p.get("rel_path") or "",
                     "role": p.get("role", "主件"),
                     "match_evidence": p.get("match_evidence", "")}
                    for p in sel
                ],
            })
            # 被闸拦下的件**单独留痕**（分类与「不存在」「受限」都不同）
            for p in sel:
                blocked.append({
                    "obligation": r["obligation"],
                    "file_id": p["file_id"],
                    "rel_path": p.get("rel_path", ""),
                    "category": _blocked_category("审核闸未通过"),
                    "reason": (f"审核闸未通过：{r.get('gate_reason', '')}"
                               f"（判定={r['verdict']}）"),
                })
            # ★ 不建目录：未过闸的义务**不得**在交付包里留任何目录/文件
            continue

        if not sel:
            # 没有选中件 ⇒ **不建目录**（空目录也是「同目录顺带复制」的残留）
            continue

        item_dir = out / _safe_dirname((r["item_no"] or r["obligation_id"]))
        item_dir.mkdir(parents=True, exist_ok=True)

        for p in sel:
            c = next((x for x in r["candidates"] if x["file_id"] == p["file_id"]), None)
            if c is None or not c["deliverable"]:
                blocked.append({
                    "obligation": r["obligation"], "file_id": p["file_id"],
                    "rel_path": p.get("rel_path", ""),
                    "category": "受限/不可交付",
                    "reason": "选中件在复制前失去交付资格",
                })
                continue
            mrow = conn.execute(
                "SELECT * FROM dd_v1_manifest WHERE file_id=?", (c["file_id"],)
            ).fetchone()
            if mrow is None:
                continue
            src = Path(mrow["abs_path"])
            if not src.is_file():
                blocked.append({"obligation": r["obligation"],
                                "file_id": c["file_id"], "rel_path": c["rel_path"],
                                "category": "源文件不存在",
                                "reason": "源文件已不存在"})
                continue
            dest = item_dir / _safe_filename(mrow["file_name"])
            # 越界兜底闸：清洗后仍异常则跳过，不写
            if not _within(out, dest):
                blocked.append({"obligation": r["obligation"],
                                "file_id": c["file_id"], "rel_path": c["rel_path"],
                                "category": "越界拦截（安全跳过）",
                                "reason": "目标越界，安全跳过"})
                continue
            if dest.exists():
                dest = item_dir / f"{_safe_filename(src.stem)}_{_safe_filename(c['file_id'][:8])}{src.suffix}"
                if not _within(out, dest):
                    blocked.append({"obligation": r["obligation"],
                                    "file_id": c["file_id"], "rel_path": c["rel_path"],
                                    "category": "越界拦截（安全跳过）",
                                    "reason": "目标越界，安全跳过"})
                    continue
            shutil.copy2(src, dest)
            exported.append({
                "item_no": r["item_no"] or "",
                "obligation": r["obligation"],
                # ★ WP1：义务的**稳定 ID**（可复算）+ 材料身份六件套
                "obligation_id": r.get("obligation_id") or "",
                "obligation_key": r.get("obligation_key") or "",
                "file_id": c["file_id"],
                "orig_rel_path": c.get("orig_rel_path") or c.get("rel_path") or "",
                "file_name": mrow["file_name"],
                "material_entity": c.get("material_entity") or "",
                "material_period": c.get("material_period") or "",
                "material_doc_type": c.get("material_doc_type") or "",
                "dest": str(dest.relative_to(out)),
                "src_sha256": mrow["content_hash"],
                "dest_sha256": _sha256(dest),
                "verdict": r["verdict"],
                # ★ WP4：**放行依据**（谁没拦它、按哪条规则放行）
                "gate": r.get("gate") or "",
                "gate_basis": r.get("gate_basis") or "",
                "gate_reason": r.get("gate_reason") or "",
                # ★ WP4：披露**四方归因**（放行侧同样留证：是哪条规则允许它外发）
                "disclosure_diagnosis": _disclosure_diagnosis(
                    c["file_id"], r, db_path),
                "role": p.get("role", "主件"),
                # ★ P0-1：同一文件被 N 条义务引用时，**每一行**都要带可核的匹配证据
                "match_evidence": p.get("match_evidence", ""),
                "entity_ok": p.get("entity_ok", ""),
                "period_ok": p.get("period_ok", ""),
                "doctype_ok": p.get("doctype_ok", ""),
            })

    # hash 核验：复制件必须与源哈希一致，否则是交付事故
    mismatched = [e for e in exported if e["src_sha256"] != e["dest_sha256"]]
    for e in mismatched:
        logger.error("hash 核验不一致：%s", e["dest"])

    (out / "组包manifest.tsv").write_text(
        "机构编号\t义务ID\t原子义务\tfile_id\t原始材料路径\t文件名\t交付路径"
        "\t源sha256\t副本sha256\t一致\t判定\t审核结论"
        "\t类型匹配\t主体匹配\t期间匹配\t匹配证据"
        # ★ WP4：放行/拦截的**规则依据**（谁拦的 + 按设计还是误分类）
        "\t披露归因_谁拦的\t披露归因_拦的性质\t披露归因_理由\t披露_敏感等级"
        "\t披露_策略版本\t披露_可外发类型\t披露_逐份授权\n" +
        "\n".join(
            f"{e['item_no']}\t{e.get('obligation_key') or e.get('obligation_id') or ''}\t"
            f"{e['obligation']}\t{e.get('file_id') or ''}\t{e.get('orig_rel_path') or ''}\t"
            f"{e.get('file_name') or ''}\t{e['dest']}\t{e['src_sha256']}\t"
            f"{e['dest_sha256']}\t{'是' if e['src_sha256']==e['dest_sha256'] else '否'}\t{e['verdict']}"
            f"\t{e.get('gate') or ''}"
            f"\t{_yn(e.get('doctype_ok'))}\t{_yn(e.get('entity_ok'))}\t{_yn(e.get('period_ok'))}"
            f"\t{e.get('match_evidence', '')}"
            f"\t{_dd['blocked_by']}\t{_dd['blocked_kind']}"
            f"\t{_dd['blocked_reason']}\t{_dd['level']}"
            f"\t{_dd['policy_version']}\t{_dd['sendable_doc_types']}\t{_dd['authorized']}"
            for e in exported
            for _dd in [_disclosure_trace(e.get("disclosure_diagnosis"))]),
            encoding="utf-8")
    (out / "被拦截清单.json").write_text(
        json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8")
    # ★ P0-2：**未过闸清单** —— 逐条义务层面的独立留痕。
    #   与「材料根本不存在」严格分开（不得把「被拦」和「不存在」混同）。
    (out / "未过闸清单.tsv").write_text(
        "机构编号\t原子义务\tobligation_id\t判定\t交付闸结论\t交付闸理由\t本可交付件数\n" +
        "\n".join(
            f"{g['item_no']}\t{g['obligation']}\t{g['obligation_id']}\t{g['verdict']}\t"
            f"{GATE_BLOCKED}\t{g['gate_reason']}\t{g['would_deliver']}"
            for g in gate_blocked_rows), encoding="utf-8")
    (out / "未过闸明细.json").write_text(
        json.dumps(gate_blocked_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    # ★ A3（G-A3-2）：**未选用清单**必须可审计——
    #   「不交」是决定，「不解释」是失职。逐条写明**为什么没选**。
    (out / "未选用清单.tsv").write_text(
        "机构编号\t原子义务\tfile_id\t相对路径\t未选用原因\n" +
        "\n".join(
            f"{u['item_no']}\t{u['obligation']}\t{u['file_id']}\t"
            f"{u['rel_path']}\t{u['reason']}"
            for u in unselected_rows), encoding="utf-8")

    # ★ WP5：真实交付链的 7 项产出（①–⑦）
    _chain_files = _write_delivery_chain(
        out, rows, exported, blocked, gate_blocked_rows, review,
        _confirmations_map(review_id, db_path), db_path=db_path)
    # ── ⑥ 实际交付文件目录（**逐件**列，含交付位置）────────────────────
    _files_lines = ["交付路径\t文件名\t字节数\tSHA256\t源SHA256\t一致\t机构编号\t义务ID"]
    for e in exported:
        _p = out / e["dest"]
        _files_lines.append("\t".join(str(x) for x in (
            e["dest"], e.get("file_name") or "",
            _p.stat().st_size if _p.is_file() else 0,
            e["dest_sha256"], e["src_sha256"],
            "是" if e["src_sha256"] == e["dest_sha256"] else "否",
            e["item_no"], e.get("obligation_key") or e.get("obligation_id") or "")))
    (out / "06-实际交付文件目录.tsv").write_text("\n".join(_files_lines),
                                                 encoding="utf-8")
    _chain_files.append("06-实际交付文件目录.tsv")
    # ── ⑦ 文件完整性校验结果（**逐件复算**，不是复制前算一次就算）────────
    _verify_lines = ["交付路径\t源SHA256\t副本SHA256(复制后读回复算)\t结论"]
    _verify_ok = 0
    for e in exported:
        _p = out / e["dest"]
        _recomputed = _sha256(_p) if _p.is_file() else ""
        _same = ("是" if (_recomputed and _recomputed == e["src_sha256"]
                          == e["dest_sha256"]) else "否")
        if _same == "是":
            _verify_ok += 1
        _verify_lines.append("\t".join(str(x) for x in (
            e["dest"], e["src_sha256"], _recomputed, _same)))
    (out / "07-文件完整性校验结果.tsv").write_text("\n".join(_verify_lines),
                                                   encoding="utf-8")
    _chain_files.append("07-文件完整性校验结果.tsv")
    # ★ `SHA256SUMS`：**逐件复算**的哈希清单（可被 `sha256sum -c` 直接核）
    _sums_lines = [f"{e['dest_sha256']}  {e['dest']}" for e in exported]
    (out / "SHA256SUMS").write_text(
        ("\n".join(_sums_lines) + "\n") if _sums_lines else "", encoding="utf-8")
    # ★ WP2：正式交付包的**明确标识**（与候选包物理隔离 ＋ 各自有标识）
    (out / "正式交付包-说明.md").write_text(
        "# 正式交付包\n\n"
        f"- 审核单：{review_id}\n"
        f"- 批准人：{review.get('approved_by') or ''}\n"
        f"- 交付件数：{len(exported)}\n"
        f"- 完整性校验通过：{_verify_ok}/{len(exported)}\n"
        "- ★ 本目录是**正式交付包**；候选包（审核包）在**另一个目录**，"
        "两者物理隔离，不得混用。\n"
        "- ★ 本目录内的原件是**逐件复算**过的副本（见 `07-文件完整性校验结果.tsv`"
        " 与 `SHA256SUMS`）。\n"
        "- 追溯链：`组包manifest.tsv` / `03-匹配结果及理由.tsv` 逐行给出"
        "「原始材料 → 匹配义务 → 审核结论 → 交付位置」。\n",
        encoding="utf-8")

    now = time.time()
    conn.execute(
        "UPDATE dd_v1_reviews SET status=?, pack_path=?, updated_at=? WHERE review_id=?",
        (ST_PACKAGED, str(out), now, review_id))
    conn.commit()

    return {
        "review_id": review_id,
        "status": ST_PACKAGED,
        "output_dir": str(out),
        "exported": len(exported),
        "blocked": len(blocked),
        # ★ WP3-d：截断**必须显式报数**（禁静默漏检）——
        #   完整的明细**已经落盘**（被拦截清单.json / 未过闸明细.json），
        #   返回值这里只给**前 20 条预览**，但**必须**说清还有多少没显示。
        "blocked_detail": blocked[:20],
        "blocked_total": len(blocked),
        "blocked_shown": min(len(blocked), 20),
        "blocked_truncated": max(0, len(blocked) - 20),
        "blocked_truncation_note": (
            f"被拦截明细共 {len(blocked)} 条，返回值只含前 {min(len(blocked), 20)} 条预览；"
            f"还有 {max(0, len(blocked) - 20)} 条**未在此显示**"
            f"（完整明细见「被拦截清单.json」）"
            if len(blocked) > 20 else ""),
        "hash_mismatched": len(mismatched),
        # ★ WP1：逐件复算的完整性校验读数
        "hash_verified": _verify_ok,
        "hash_verified_total": len(exported),
        "sha256sums": str(out / "SHA256SUMS"),
        # ★ WP5：7 项交付链产出的落盘路径
        "delivery_chain_files": _chain_files,
        "approved_by": review["approved_by"],
        # ★ A3（G-A3-2）：交付集合的口径要能自证——
        #   交了几件、没交几件、没交的理由都在清单里。
        "unselected": len(unselected_rows),
        "unselected_manifest": str(out / "未选用清单.tsv"),
        # ★ P0-2：交付闸的**分账**读数（与「被拦」「不存在」严格分开）
        "gate_blocked_obligations": len(gate_blocked_rows),
        "gate_blocked_detail": gate_blocked_rows[:20],
        "gate_blocked_total": len(gate_blocked_rows),
        "gate_blocked_shown": min(len(gate_blocked_rows), 20),
        "gate_blocked_truncated": max(0, len(gate_blocked_rows) - 20),
        "gate_blocked_truncation_note": (
            f"未过闸义务共 {len(gate_blocked_rows)} 条，返回值只含前 "
            f"{min(len(gate_blocked_rows), 20)} 条预览；"
            f"还有 {max(0, len(gate_blocked_rows) - 20)} 条**未在此显示**"
            f"（完整明细见「未过闸明细.json」）"
            if len(gate_blocked_rows) > 20 else ""),
        "gate_blocked_manifest": str(out / "未过闸清单.tsv"),
        "gate_default_pass_verdicts": list(GATE_DEFAULT_PASS_VERDICTS),
        "selection_rule": ("可交付候选按「四维命中分 → 主体命中 → 期间命中 → "
                           "类型命中 → file_id 升序」确定性排序取前 N 份；"
                           "必备附件只认 related_files 显式列出的文件"),
    }


def get_review(review_id: str, db_path: Path | None = None) -> dict | None:
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_reviews WHERE review_id=?", (review_id,)
    ).fetchone()
    return dict(row) if row else None
