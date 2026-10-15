"""DD-V1 金融尽调需求理解（WP3 · M1）。

把机构清单的一条要求，拆成**可逐条判定、可逐条追责**的原子义务。

## 三条不可让步的纪律

1. **机构原编号与原文零丢失。**
   ``dd_v1_checklist_items`` 原样保存 ``item_no`` 与 ``raw_text``；
   原子义务只做**派生**（``obligation``），并通过 ``item_uid`` 指回原文。
   任何拆分都不得让原文或编号消失——评审时必须能对照机构原件。

2. **拆不出来的维度一律 UNKNOWN，绝不编造。**
   主体范围、年度、文件类型、合并/单体口径、签章、附件、有效性，
   每项都带出处 ``FACT``（原文有明文）/ ``INFERRED``（规则推导）/ ``UNKNOWN``。

3. **主体范围不凭文件名猜。**
   「集团及下属公司」要求的是**成员名单**，必须由 ``dd_v1_entities`` 里的
   权威主体登记决定；没有名单时 ``entity_scope`` 记 ``UNKNOWN`` 并阻断完整性判定，
   绝不把目录名当集团成员依据（这正是 D2/D3 的老毛病）。

相对年份（「近三年」）需要**锚定年**：不提供锚点时只记 ``period_basis=relative``
并把 ``period_from/to`` 留 0，交由调用方补锚，**不擅自假定今年**。

本模块纯确定性，**零 LLM 调用**。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from cangjie_fos.services import dd_v1_manifest_service as mf

logger = logging.getLogger(__name__)

FACT = "FACT"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"

_DDL = """
-- 机构清单原始条目：原文与编号原样保存，任何拆分不得覆盖它
CREATE TABLE IF NOT EXISTS dd_v1_checklist_items (
    item_uid    TEXT PRIMARY KEY,
    library_id  TEXT NOT NULL,
    institution TEXT NOT NULL DEFAULT '',
    item_no     TEXT NOT NULL DEFAULT '',
    raw_text    TEXT NOT NULL,
    source_ref  TEXT NOT NULL DEFAULT '',
    parsed_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_items_lib ON dd_v1_checklist_items(library_id);

-- 原子义务：一条清单项可派生多个义务
CREATE TABLE IF NOT EXISTS dd_v1_obligations (
    obligation_id    TEXT PRIMARY KEY,
    item_uid         TEXT NOT NULL,
    library_id       TEXT NOT NULL,
    seq              INTEGER NOT NULL DEFAULT 1,
    obligation       TEXT NOT NULL,
    entity_scope     TEXT NOT NULL DEFAULT '',
    entity_basis     TEXT NOT NULL DEFAULT '',
    period_from      INTEGER NOT NULL DEFAULT 0,
    period_to        INTEGER NOT NULL DEFAULT 0,
    period_basis     TEXT NOT NULL DEFAULT '',
    doc_type         TEXT NOT NULL DEFAULT '',
    doc_type_basis   TEXT NOT NULL DEFAULT '',
    caliber          TEXT NOT NULL DEFAULT '',
    caliber_basis    TEXT NOT NULL DEFAULT '',
    seal_required    TEXT NOT NULL DEFAULT '',
    needs_attachments INTEGER NOT NULL DEFAULT 0,
    attachment_basis TEXT NOT NULL DEFAULT '',
    disclosure       TEXT NOT NULL DEFAULT '',
    fields_json      TEXT NOT NULL DEFAULT '{}',
    notes            TEXT NOT NULL DEFAULT '',
    created_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_obl_item ON dd_v1_obligations(item_uid);
CREATE INDEX IF NOT EXISTS idx_dd_v1_obl_lib  ON dd_v1_obligations(library_id);
CREATE INDEX IF NOT EXISTS idx_dd_v1_obl_period ON dd_v1_obligations(library_id, period_from, period_to);

-- 权威主体登记（集团成员名单）。**没有它，多主体覆盖无法判定。**
CREATE TABLE IF NOT EXISTS dd_v1_entities (
    library_id    TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    parent_id     TEXT NOT NULL DEFAULT '',
    relation      TEXT NOT NULL DEFAULT '',   -- parent/subsidiary/affiliate/other
    valid_from    INTEGER NOT NULL DEFAULT 0,
    valid_to      INTEGER NOT NULL DEFAULT 0,  -- 0 = 至今
    is_group_root INTEGER NOT NULL DEFAULT 0,
    source_ref    TEXT NOT NULL DEFAULT '',   -- 权威依据出处（工商登记/年报等）
    registered_at REAL NOT NULL,
    PRIMARY KEY (library_id, entity_id)
);
"""

# ── 主体范围 ────────────────────────────────────────────────────────────────
_SCOPE_GROUP_SUB = re.compile(r"(集团(?:及|和|与)(?:其)?(?:全资)?(?:下属|附属)?(?:子)?公司|集团整体|集团合并)")
_SCOPE_PARENT = re.compile(r"(母公司|总部|上市主体|标的公司主体)")
_SCOPE_SUBS = re.compile(r"(各(?:全资)?子公司|下属各公司|所有子公司)")
_SCOPE_SELF = re.compile(r"(?:^|[^\w])(?:贵司|公司自身)(?:[^\w]|$)")

# ── 期间 ────────────────────────────────────────────────────────────────────
_PERIOD_RANGE_CN = re.compile(r"(\d{4})\s*(?:年)?\s*(?:至|到|-|—|–|~)\s*(\d{4})\s*年?")
_PERIOD_LIST = re.compile(r"(\d{4})\s*年?")
_PERIOD_REL = re.compile(r"(近|最近|过去)\s*([一二三四五六七八九十两\d]+)\s*年")
_PERIOD_SINGLE = re.compile(r"(\d{4})\s*年度?")
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# ── 口径 / 签章 / 附件 ──────────────────────────────────────────────────────
_CALIBER_CONSOL = re.compile(r"(合并报表|合并口径|合并财务报表|合并数)")
_CALIBER_SINGLE = re.compile(r"(母公司(?:单体)?(?:报表|口径)?|单体报表|单体|个别报表)")
_SEAL_BOTH = re.compile(r"(?:盖章|加盖.{0,4}公章|盖公章).{0,8}(?:签字|签署|签章)|(?:签字|签署|签章).{0,8}(?:盖章|加盖.{0,4}公章)")
_SEAL_ONLY = re.compile(r"(盖章|加盖.{0,4}公章|盖公章|签章)")
_SIGN_ONLY = re.compile(r"(签字|签署|签名|法人签字)")
# 允许「及其附件」「及附件」「附证明材料」等常见写法
_ATTACH = re.compile(r"(?:其|本)?及?附件|附.{0,8}(?:证明|材料|文件|扫描件|清单)|连同|附件[:：]")

# ── 材料类型关键词（映射到认知卡 purpose 词典）──────────────────────────────
_DOC_TYPE_RULES = (
    ("audit_report", "审计报告"),
    ("financial_statement", "(财务报表|资产负债表|利润表|现金流量表|财务报表附注)"),
    ("tax", "(纳税|税务|完税|纳税申报)"),
    ("license", "(营业执照|登记证书)"),
    ("charter", "(公司章程|章程)"),
    ("capital", "(验资|出资|实缴)"),
    ("resolution", "(决议|股东会|董事会)"),
    ("ip", "(专利|商标|知识产权|软著)"),
    ("labor", "(劳动合同|社保|花名册|员工)"),
    ("contract", "(合同|协议)"),
)


def _ensure_schema(conn) -> None:
    conn.executescript(_DDL)
    conn.commit()


@dataclass
class Obligation:
    """一条原子义务。每个维度都带 basis（FACT / INFERRED / UNKNOWN）。"""
    obligation: str = ""
    entity_scope: str = ""
    entity_basis: str = UNKNOWN
    period_from: int = 0
    period_to: int = 0
    period_basis: str = UNKNOWN
    doc_type: str = ""
    doc_type_basis: str = UNKNOWN
    caliber: str = ""
    caliber_basis: str = UNKNOWN
    seal_required: str = ""
    needs_attachments: int = 0
    attachment_basis: str = UNKNOWN
    disclosure: str = ""
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "obligation": self.obligation,
            "entity_scope": self.entity_scope,
            "entity_basis": self.entity_basis,
            "period_from": self.period_from,
            "period_to": self.period_to,
            "period_basis": self.period_basis,
            "doc_type": self.doc_type,
            "doc_type_basis": self.doc_type_basis,
            "caliber": self.caliber,
            "caliber_basis": self.caliber_basis,
            "seal_required": self.seal_required,
            "needs_attachments": self.needs_attachments,
            "attachment_basis": self.attachment_basis,
            "disclosure": self.disclosure,
            "notes": self.notes,
        }


def doc_type_search_terms(doc_type: str) -> list[str]:
    """把 ``doc_type`` 的内部 key 翻成**材料里的中文词**，供全文召回使用。

    首轮实现直接把 ``"audit_report"`` 这样的英文 key 当检索词，
    而认知卡/正文全是中文 → 召回恒为空，四维覆盖全部算成 0。
    必须翻成真实会出现在材料里的中文词。

    **未映射的类型返回空列表，不返回原样 key。**
    把 ``"financial_report"`` 这种英文 key 拿去检索中文语料，结果必然是 0 命中，
    只会让人误以为「材料不存在」——**判不出类型时应走「无法判定」，不是「查不到」**。
    """
    if not doc_type:
        return []
    for key, pat in _DOC_TYPE_RULES:
        if key == doc_type:
            terms = re.findall(r"[一-鿿]{2,}", pat)
            return terms or [pat]
    return []


# 中文**功能词/连词**：用作语义单元的切分点。
# 切分后取词就不会产生「制人及股」「及股权结」这类跨词边界的碎片——
# 在二元组 FTS 索引下，跨边界碎片几乎必然 0 命中，只白发查询、拖慢召回。
_UNIT_SPLIT_RE = re.compile(r"(?:以及|并且|或|及其|及|和|与|其|的|等|含|同|为)")

# 请求动词/客套前缀：出现在每条要求开头，**先剥掉**再取词，
# 否则抽出来全是「请提」「提供被」这类无意义碎片。
_TEXT_PREFIX_RE = re.compile(
    r"^(请(?:予以)?(?:提供|出具|说明|给出|补充|提交|列明|描述|解释|附上|发来)"
    r"|烦请|需(?:要)?提供|请|烦)+")

# 低信息词：本身不携带业务信息
_TEXT_STOPWORDS = {
    "提供", "说明", "给出", "补充", "需要", "要求", "相关", "对应",
    "包括", "包含", "以下", "上述", "情况", "材料", "文件", "资料",
    "内容", "信息", "一份", "完整", "全部", "所有", "其他", "有关",
    "本项", "该项", "该公司", "公司", "企业", "被投企业", "真实",
    "情况说明", "有关情况",
}


def _unit_terms(unit: str, limit: int = 3) -> list[str]:
    """从一个语义单元里取词。整段可用就整段取（≤6 字），过长才滑窗。"""
    n = len(unit)
    if n < 2:
        return []
    if 2 <= n <= 6:
        # 整段保留：FTS 是二元组索引，长词更具体、误召回更少
        return [unit]
    return [unit[i:i + 4] for i in range(n - 3)][:limit]


def text_search_terms(text: str, max_terms: int = 8) -> list[str]:
    """从义务原文里抽**可用于召回**的词。

    ## 为什么不按位置取（WP7 独立验收 D-5）

    原实现是「剥前缀 → 4 字滑窗 → **只保留前 6 个**」。滑窗从位置 0 顺序生成，
    ``max_terms`` 的截断于是**系统性地只覆盖句首约 9 个字**：

        「请说明实际控制人及股权结构」
          → ['实际控制','际控制人','控制人及','制人及股','人及股权','及股权结']
          **没有「股权结构」**

    「请提供…财务报告及审计意见」「请提供…股东名单及其持股比例」同样丢失句尾。
    只要关键名词恰好不在句首那 6 个窗口里就 0 召回——**这是「碰巧对」不是「设计上对」**。
    而判出的仍是 MISSING，输出**自信的错误答案**，用户会去追不存在的缺口。

    ## 现在的做法

    1. 剥掉「请提供 / 请说明 / 请出具」等请求前缀；
    2. 按**功能词**（及/和/与/其/的/等/或/并且）切成**语义单元**——
       这样取词不会跨词边界，不再产生「制人及股」这类必然 0 命中的碎片；
    3. 从**每个**单元取词，**跨单元交错合并**（单元A第1个、单元B第1个、单元A第2个…），
       保证句尾单元不会被前面的单元挤掉。

    与 :func:`doc_type_search_terms` 的产物合并使用：doc_type 词优先，原文词兜底。
    """
    if not text:
        return []
    s = _TEXT_PREFIX_RE.sub("", str(text).strip())
    units = [u for u in _UNIT_SPLIT_RE.split(s) if u and len(u) >= 2]
    if not units:
        return []

    # 跨单元交错，保证每个语义单元都露脸
    per_unit = [_unit_terms(u) for u in units]
    out: list[str] = []
    for i in range(max(len(x) for x in per_unit)):
        for terms in per_unit:
            if i < len(terms) and terms[i] not in out:
                out.append(terms[i])
                if len(out) >= max_terms:
                    return out
    return out


def parse_entity_scope(raw: str) -> tuple[str, str]:
    """识别主体范围。**只认原文明文**，不推测。"""
    if _SCOPE_GROUP_SUB.search(raw):
        return "group_and_subs", FACT
    if _SCOPE_SUBS.search(raw):
        return "subsidiaries", FACT
    if _SCOPE_PARENT.search(raw):
        return "parent_only", FACT
    if _SCOPE_SELF.search(raw):
        return "self", FACT
    return "", UNKNOWN


def parse_period(raw: str, anchor_year: int | None = None) -> tuple[int, int, str, list]:
    """识别期间。

    返回 ``(period_from, period_to, basis, notes)``。
    相对年份（「近三年」）在缺 ``anchor_year`` 时**不擅自假定**，
    返回 0/0 并在 notes 说明需锚定年。
    """
    notes: list[str] = []

    m = _PERIOD_RANGE_CN.search(raw)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a <= b:
            return a, b, FACT, notes
        notes.append(f"区间倒序 {a}>{b}，按原样记录")
        return b, a, FACT, notes

    m = _PERIOD_REL.search(raw)
    if m:
        span_txt = m.group(2)
        span = _CN_NUM.get(span_txt, None)
        if span is None and span_txt.isdigit():
            span = int(span_txt)
        if span and anchor_year:
            return anchor_year - span + 1, anchor_year, FACT, \
                notes + [f"相对年份「{m.group(1)}{span_txt}年」以锚定年 {anchor_year} 展开"]
        notes.append(f"相对年份「{m.group(1)}{span_txt}年」缺锚定年，未展开")
        return 0, 0, "relative_unresolved", notes

    years = [int(y) for y in _PERIOD_LIST.findall(raw)]
    if len(years) >= 2:
        uniq = sorted(set(years))
        return uniq[0], uniq[-1], INFERRED, notes + ["由文中散落年份推断区间"]

    m = _PERIOD_SINGLE.search(raw)
    if m:
        y = int(m.group(1))
        return y, y, FACT, notes

    return 0, 0, UNKNOWN, notes


def parse_doc_type(raw: str) -> tuple[str, str]:
    for key, pat in _DOC_TYPE_RULES:
        if re.search(pat, raw):
            return key, FACT
    return "", UNKNOWN


def parse_caliber(raw: str) -> tuple[str, str]:
    if _CALIBER_CONSOL.search(raw):
        return "consolidated", FACT
    if _CALIBER_SINGLE.search(raw):
        return "single_entity", FACT
    return "", UNKNOWN


def parse_seal(raw: str) -> tuple[str, str]:
    if _SEAL_BOTH.search(raw):
        return "seal_and_sign", FACT
    if _SEAL_ONLY.search(raw):
        return "seal", FACT
    if _SIGN_ONLY.search(raw):
        return "sign", FACT
    return "", UNKNOWN


def parse_attachments(raw: str) -> tuple[int, str]:
    if _ATTACH.search(raw):
        return 1, FACT
    return 0, UNKNOWN


def build_obligations(
    raw: str,
    anchor_year: int | None = None,
) -> list[Obligation]:
    """把一条清单要求拆成原子义务。

    拆分策略：按**并列连接词**（且/以及/、/及）切分出多个并列要求；
    切不出并列的，按单条义务处理。拆分只作用于派生文本，
    原文由调用方另行原样保存。
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    parts = _split_parallel(raw)
    out: list[Obligation] = []
    for part in parts:
        ob = Obligation(obligation=part)
        ob.entity_scope, ob.entity_basis = parse_entity_scope(part)
        ob.period_from, ob.period_to, ob.period_basis, notes = parse_period(
            part, anchor_year)
        ob.notes.extend(notes)
        ob.doc_type, ob.doc_type_basis = parse_doc_type(part)
        ob.caliber, ob.caliber_basis = parse_caliber(part)
        ob.seal_required, _ = parse_seal(part)
        ob.needs_attachments, ob.attachment_basis = parse_attachments(part)
        ob.disclosure = ""
        out.append(ob)
    return out


_SPLIT_RE = re.compile(r"[、]|(?:以及)|(?:，\s*并且)")


def _split_parallel(raw: str) -> list[str]:
    """按并列连接词拆分。只在**明显并列**处切，避免把长句切碎丢信息。"""
    parts = [p.strip(" 　；;，,。.") for p in _SPLIT_RE.split(raw)]
    parts = [p for p in parts if p]
    return parts or [raw]


# ── 落库 ────────────────────────────────────────────────────────────────────
def ingest_checklist(
    library_id: str,
    rows: list[dict],
    anchor_year: int | None = None,
    institution: str = "",
    db_path: Path | None = None,
) -> dict:
    """录入机构清单并拆解为原子义务。

    ``rows`` 每项需含 ``item_no``（机构原编号，可为空串）与 ``raw_text``（机构原文，必填）。

    返回统计，含「原文与编号是否零丢失」的硬校验。
    """
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    now = time.time()
    n_items = n_obls = 0
    dropped: list[dict] = []

    for r in rows:
        raw = (r.get("raw_text") or "").strip()
        if not raw:
            dropped.append({"item_no": r.get("item_no", ""),
                            "reason": "原文为空，拒绝入库（不得凭空生成要求）"})
            continue
        item_uid = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO dd_v1_checklist_items
               (item_uid, library_id, institution, item_no, raw_text, source_ref, parsed_at)
               VALUES (?,?,?,?,?,?,?)""",
            (item_uid, library_id, institution, r.get("item_no") or "",
             raw, r.get("source_ref") or "", now),
        )
        n_items += 1

        for seq, ob in enumerate(build_obligations(raw, anchor_year), 1):
            payload = ob.to_dict()
            conn.execute(
                """INSERT INTO dd_v1_obligations
                   (obligation_id, item_uid, library_id, seq, obligation,
                    entity_scope, entity_basis, period_from, period_to, period_basis,
                    doc_type, doc_type_basis, caliber, caliber_basis, seal_required,
                    needs_attachments, attachment_basis, disclosure, fields_json,
                    notes, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, item_uid, library_id, seq, ob.obligation,
                 ob.entity_scope, ob.entity_basis, ob.period_from, ob.period_to,
                 ob.period_basis, ob.doc_type, ob.doc_type_basis, ob.caliber,
                 ob.caliber_basis, ob.seal_required, ob.needs_attachments,
                 ob.attachment_basis, ob.disclosure,
                 json.dumps(payload, ensure_ascii=False),
                 "; ".join(ob.notes), now),
            )
            n_obls += 1

    conn.commit()

    # 硬校验：每条原文必须仍能按 item_no + raw_text 原样取回
    stored = conn.execute(
        "SELECT item_no, raw_text FROM dd_v1_checklist_items WHERE library_id=?",
        (library_id,),
    ).fetchall()
    roundtrip_ok = len(stored) == n_items
    for r in rows:
        raw = (r.get("raw_text") or "").strip()
        if not raw:
            continue
        hit = any(s["raw_text"] == raw and s["item_no"] == (r.get("item_no") or "")
                  for s in stored)
        if not hit:
            roundtrip_ok = False
            break

    return {
        "library_id": library_id,
        "items": n_items,
        "obligations": n_obls,
        "dropped": dropped,
        "original_text_roundtrip_ok": roundtrip_ok,
        "anchor_year": anchor_year,
    }


def get_item(item_uid: str, db_path: Path | None = None) -> dict | None:
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    row = conn.execute(
        "SELECT * FROM dd_v1_checklist_items WHERE item_uid=?", (item_uid,)
    ).fetchone()
    return dict(row) if row else None


def list_obligations(
    library_id: str, item_uid: str | None = None, db_path: Path | None = None
) -> list[dict]:
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    if item_uid:
        rows = conn.execute(
            "SELECT * FROM dd_v1_obligations WHERE item_uid=? ORDER BY seq", (item_uid,)
        )
    else:
        rows = conn.execute(
            "SELECT * FROM dd_v1_obligations WHERE library_id=? ORDER BY created_at",
            (library_id,))
    return [dict(r) for r in rows]


# ── 权威主体登记（多主体覆盖的前提）─────────────────────────────────────────
def register_entity(
    library_id: str,
    entity_id: str,
    display_name: str,
    relation: str = "other",
    parent_id: str = "",
    valid_from: int = 0,
    valid_to: int = 0,
    is_group_root: bool = False,
    source_ref: str = "",
    db_path: Path | None = None,
) -> None:
    """登记权威主体。``source_ref`` 必填理由——没有权威依据的主体不得入册。"""
    if not source_ref.strip():
        raise ValueError("source_ref 不能为空：主体登记必须有权威依据出处")
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    conn.execute(
        """INSERT INTO dd_v1_entities
           (library_id, entity_id, display_name, parent_id, relation,
            valid_from, valid_to, is_group_root, source_ref, registered_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(library_id, entity_id) DO UPDATE SET
             display_name=excluded.display_name, parent_id=excluded.parent_id,
             relation=excluded.relation, valid_from=excluded.valid_from,
             valid_to=excluded.valid_to, is_group_root=excluded.is_group_root,
             source_ref=excluded.source_ref""",
        (library_id, entity_id, display_name, parent_id, relation,
         valid_from, valid_to, 1 if is_group_root else 0, source_ref, time.time()),
    )
    conn.commit()


def resolve_entities(
    library_id: str,
    scope: str,
    as_of_year: int | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """按主体范围解析**权威**主体名单。

    **没有 `dd_v1_entities` 名单就返回空列表**——
    调用方据此把多主体覆盖判为 UNKNOWN，而不是拿目录名凑数。
    """
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM dd_v1_entities WHERE library_id=?", (library_id,))]

    if as_of_year:
        rows = [
            r for r in rows
            if (r["valid_from"] <= as_of_year)
            and (r["valid_to"] == 0 or r["valid_to"] >= as_of_year)
        ]

    if scope == "group_and_subs":
        return rows
    if scope == "subsidiaries":
        return [r for r in rows if r["relation"] == "subsidiary"]
    if scope == "parent_only":
        return [r for r in rows if r["relation"] == "parent"]
    if scope == "self":
        return [r for r in rows if r["is_group_root"]]
    return []


def entities_registered(library_id: str, db_path: Path | None = None) -> int:
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    return conn.execute(
        "SELECT COUNT(*) c FROM dd_v1_entities WHERE library_id=?", (library_id,)
    ).fetchone()["c"]


def obligation_quality(library_id: str, db_path: Path | None = None) -> dict:
    """义务解析的出处分布——「我们真的读懂了多少」的诚实度量。"""
    conn = mf._connect(db_path)
    _ensure_schema(conn)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM dd_v1_obligations WHERE library_id=?", (library_id,))]
    dims = ("entity_basis", "period_basis", "doc_type_basis",
            "caliber_basis", "attachment_basis")
    tally = {d: {FACT: 0, INFERRED: 0, UNKNOWN: 0} for d in dims}
    for r in rows:
        for d in dims:
            v = r.get(d, UNKNOWN)
            tally[d][v] = tally[d].get(v, 0) + 1
    return {
        "obligations": len(rows),
        "by_dimension": tally,
        "entities_registered": entities_registered(library_id, db_path),
    }
