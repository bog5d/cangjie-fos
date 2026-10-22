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

import hashlib
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
    -- ★ A3（G-A3-1）：「应有几份」的承载体。
    --   expected_count = 0   ⇒ 清单**未规定**份数（该维度不构成门槛）
    --   expected_count = NULL ⇒ 清单**提及**份数但**解析不出**（该维不可判定 ⇒ 判 UNCERTAIN）
    --   expected_count = N>0 ⇒ 权威份数 N（应有 N 份）
    expected_count    INTEGER DEFAULT 0,
    expected_count_basis TEXT NOT NULL DEFAULT 'UNKNOWN',
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
# ★ A2（G-A2-5）新增：**「提到了期间但解析不出」的识别式**（保守）。
#   覆盖的是那些**语义上是期间、但无法换算成绝对年份**的说法：
#   「最近三个月」「本年度」「去年」「上年度」「最近一期」「上一期」……
#   ★ 必须**保守**：只认「近/最近/过去/前/本/今/上/该 + 数词 + 年/月/季度/期」这类形态，
#     不做泛化匹配（否则把普通句子里的「上」字也当期间 ⇒ 义务被无端判 UNCERTAIN）。
#   ★ 判定顺序：RANGE → REL → LIST → SINGLE → **MENTION** → UNKNOWN
#     ⇒ 能解析的照旧解析；只有「提了却解析不出」才落 `unresolved`。
_PERIOD_MENTION = re.compile(
    r"(?:近|最近|过去|前|本|今|上|该|去)\s*(?:一|二|两|三|四|五|六|七|八|九|十|\d)*\s*"
    r"(?:年度?|个月|季度|期)"
    r"|去年同期|往年|历史期间|本报告期|当期"
)
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


# ── 材料类型的**唯一性口径**（G-A2-10）────────────────────────────────
# 与上面的 ``_DOC_TYPE_RULES`` **不是同一维度**：
#   ``_DOC_TYPE_RULES`` 决定「这是哪一类材料」；
#   这里决定「这一类材料在同一主体同一期间下**是否应当只有一份**」。
# ★ **不是第二份类型规则表**：键必须取自上面那 10 个 key，只多一个维度。
_DOC_TYPE_UNIQUENESS = {
    "audit_report": "ANNUAL_UNIQUE",       # 审计报告：一年一份（法定）
    "financial_statement": "MULTI_LEGAL",  # 财务报表：按月/多项目，可多份合法
    "license": "MULTI_LEGAL",              # 执照：正本/副本并存
    "charter": "MULTI_LEGAL",              # 章程：可有修正案/工商底档多分册
    "capital": "MULTI_LEGAL",              # 出资/验资：多笔
    "tax": "MULTI_LEGAL",                  # 税务：按期多份
    "resolution": "MULTI_LEGAL",           # 决议：多份
    "ip": "MULTI_LEGAL",                   # 知识产权：多项
    "labor": "MULTI_LEGAL",                # 劳动合同/社保：多份
    "contract": "MULTI_LEGAL",             # 合同/协议：多份
}


def doc_type_uniqueness(doc_type: str) -> str:
    """材料类型的唯一性口径：``ANNUAL_UNIQUE`` / ``MULTI_LEGAL`` / ``UNKNOWN``。

    - ``ANNUAL_UNIQUE``：同一主体同一期间**应当只有一份**
      ⇒ 出现内容哈希不同的多份 ⇒ **真冲突，必须报**；
    - ``MULTI_LEGAL``：同一主体同一期间**合法多份**
      （正/副本、修正案、按月报表、多项目、底档多分册……）
      ⇒ **不报**内容冲突，只**留痕**；
    - ``UNKNOWN``：认不出唯一性口径 ⇒ 按不唯一处理并**留痕**
      （**不得**默认当成真冲突，也不得当成可放行）。

    ★ 这**不是**放松硬 Gate：只是把「本来就合法多份」从「冲突」挪到「留痕」，
      **唯一性类的真冲突仍然必须报**（判据双向）。
    """
    return _DOC_TYPE_UNIQUENESS.get(str(doc_type or "").strip(), "UNKNOWN")


def _ensure_schema(conn) -> None:
    conn.executescript(_DDL)
    _ensure_columns(conn)
    conn.commit()


def _ensure_columns(conn) -> None:
    """给**已存在**的库补齐 A3 新增列。

    ★ ``CREATE TABLE IF NOT EXISTS`` **不会**给旧表加列 ⇒ 直接改 DDL
      对已有数据面无效（旧库读不到 ``expected_count`` ⇒ KeyError）。
    ⇒ 这里做一次**幂等**的列补齐：只看列名，不动任何既有数据。
    """
    try:
        have = {r[1] for r in conn.execute(
            "PRAGMA table_info(dd_v1_obligations)").fetchall()}
    except Exception:  # noqa: BLE001 — 表还不存在时无需补列
        return
    for name, ddl in (("expected_count", "INTEGER DEFAULT 0"),
                      ("expected_count_basis", "TEXT NOT NULL DEFAULT 'UNKNOWN'")):
        if name in have:
            continue
        try:
            conn.execute(
                f"ALTER TABLE dd_v1_obligations ADD COLUMN {name} {ddl}")
            logger.info("已补齐列 dd_v1_obligations.%s", name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("补列失败 dd_v1_obligations.%s：%s", name, exc)


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
    # ★ A3（G-A3-1）：「应有几份」。0=未规定 / None=提及但不可判定 / N=权威份数。
    expected_count: int | None = 0
    expected_count_basis: str = UNKNOWN
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
            "expected_count": self.expected_count,
            "expected_count_basis": self.expected_count_basis,
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


#: 义务原文里的**主体前缀**形态：「<主体简称>：<要求>」
#:   （真实材料实测形如「<主体简称>公司：最新的营业执照正」）
#: ★ 刻意**保守**：只看冒号**前**的一小段，且必须像机构名
#:   （含「公司/集团/银行/厂/所/中心/合作社/事务所/有限/股份」之一），
#:   并排除常见非主体词（说明/备注/注意/其他/如下…）。
#:   宁可漏判（当作没指名主体）也不误判（把「说明：」当主体）。
_SUBJECT_HINT_RE = re.compile(r"^\s*([^：:]{2,12})\s*[：:]")
_SUBJECT_HINT_STOP = {
    "说明", "备注", "注意", "其他", "如下", "例如", "包括", "具体", "详见",
    "备注说明", "背景", "目的", "范围", "要求", "内容", "问题", "建议",
}
_SUBJECT_HINT_MARKERS = (
    "公司", "集团", "银行", "厂", "所", "中心", "合作社", "事务所",
    "有限", "股份", "研究院", "委员会",
)


#: 主体前缀 scope 的**唯一**前缀常量（仓内只有这一处定义）。
ENTITY_HINT_PREFIX = "entity_hint:"

#: 主体前缀在**文案**里的统一脱敏标签（客户标识 ⇒ 原文不得外露）。
ENTITY_HINT_LABEL = "义务指名的主体（简称）"


def entity_scope_value(scope: str) -> str:
    """把 ``entity_scope`` 变成**可展示**的值（脱敏）。

    ★ 单一来源：仓内只有这一处决定「主体范围的值怎么对外写」。
    ★ ``entity_hint:<简称>`` 里存的是**客户标识**（简称）⇒ 展示时统一脱敏
      成「义务指名的主体（简称）」，原文**不得**进任何判据文案 / 报告 / 交付物。
    ★ 数据库里的**原值不动**（判定层要用它做主体解析）。
    """
    s = str(scope or "").strip()
    if not s:
        return ""
    if s.startswith(ENTITY_HINT_PREFIX):
        return ENTITY_HINT_LABEL
    return s


def entity_scope_label(scope: str) -> str:
    """把 ``entity_scope`` 变成可直接嵌进文案的**短语**。

    - ``entity_hint:...`` ⇒ 「义务指名的主体（简称）」（脱敏）
    - 其它 ⇒ 「主体范围「xxx」」（与既有文案**逐字一致**）
    """
    v = entity_scope_value(scope)
    if not v:
        return ""
    if v == ENTITY_HINT_LABEL:
        return v
    return f"主体范围「{v}」"


#: 结尾的**角色括号后缀**（如「（保证人）」「(借款方)」）—— 只带文字的才算角色后缀
_PAREN_TAIL_RE = re.compile(r"[（(][^（()）]{0,24}[)）]\s*$")


def _strip_trailing_paren(s: str) -> str:
    """剥掉结尾的**角色括号后缀**；没有就原样返回。

    ★ A2（G-A2-13）：义务里的主体简称可能带角色后缀
      （形如「<主体>（保证人）」）⇒ 归一后对不上登记的简称。
    ★ **只剥带文字的**；纯数字内容（副本后缀「(1)」）交给 `normalize_name` 处理，
      避免两个只差副本号的简称被合并。
    """
    raw = str(s or "")
    m = _PAREN_TAIL_RE.search(raw)
    if not m:
        return raw
    content = re.sub(r"[（()）\s]", "", m.group(0))
    if not content or content.isdigit():
        return raw
    return raw[:m.start()].strip()


def _hint_lookup_keys(hint: str) -> list[str]:
    """主体简称的**查表键候选**（由严到宽）。

    ★ A2（G-A2-13）：先试**原样归一**（命中角色后缀形式的登记别名），
      再试**剥掉角色括号后缀**后的归一（命中「只登记了干净简称」的情况）。
    ★ 只在**查表路径**剥：登记侧不剥 ⇒ 不会制造归一碰撞
      （登记侧本就有「归一键不得跨主体复用」的守卫）。
    ★ 剥不掉就认不了 ⇒ 调用方判「未登记」（不猜、不退化）。
    """
    try:
        from cangjie_fos.services import dd_v1_entity_service as es
        norm = es.normalize_name
    except Exception:  # noqa: BLE001
        def norm(x):  # type: ignore[misc]
            return str(x or "").strip().casefold()
    keys: list[str] = []
    raw = str(hint or "").strip()
    for cand in (raw, _strip_trailing_paren(raw)):
        k = norm(cand)
        if k and k not in keys:
            keys.append(k)
    return keys


def subject_hint_prefix(raw: str) -> str:
    """取义务原文里的**主体前缀**（简称线索），没有就返回空串。

    ★ 返回的是**原文里的简称**，属客户标识 ⇒
      判据文案里**不得**直接打印（要脱敏），也不得进任何 Git 交付物。
    """
    m = _SUBJECT_HINT_RE.match(str(raw or ""))
    if not m:
        return ""
    prefix = m.group(1).strip()
    if not (2 <= len(prefix) <= 12):
        return ""
    if prefix in _SUBJECT_HINT_STOP:
        return ""
    if not any(k in prefix for k in _SUBJECT_HINT_MARKERS):
        return ""
    return prefix


def entity_registry_tokens(
    library_id: str,
    conn,
    db_path: Path | None = None,
) -> list[tuple[str, str]]:
    """本库**权威主体名单 + 别名**的可匹配词表 ⇒ ``[(原文串, entity_id), ...]``。

    ★ gm-fix-f2-subject-scope: F2（MAJOR）· 主体指名范围
      主体前缀抽取只认「<主体>：<要求>」一种形态，其余形态**一律抽不出**
      ⇒ `entity_scope` 为空 ⇒ 主体维度永久不可判定 ⇒ 判 UNCERTAIN。
      ★ **别名登记救不了**：失败发生在**抽取阶段**，压根没进查表路径。
      ⇒ 本函数提供「**回落查权威名单**」所需的词表。

    ★ 只收**登记过的**串：登记全称（`dd_v1_entities.display_name`）+
      库内别名（`dd_v1_entity_aliases.alias`，**排除 DIRECTORY 型**
      —— 分类目录是分类维度，不是主体标识，与 F1 产品侧守卫同一口径）。
    ★ 不含配置文件别名：配置文件不是**本库**的权威名单 ⇒ 不进回落路径。
    ★ 长串优先（最长匹配更具体）；同长度按串本身排序 ⇒ 结果**可复现**。
    """
    out: list[tuple[str, str]] = []
    lib = str(library_id or "").strip()
    if not lib:
        return out
    try:
        for _r in conn.execute(
                "SELECT entity_id, display_name FROM dd_v1_entities "
                "WHERE library_id=?", (lib,)):
            _n = str(_r["display_name"] or "").strip()
            if _n:
                out.append((_n, str(_r["entity_id"] or "")))
    except Exception:  # noqa: BLE001 — 名单取不到就当没有 ⇒ 不猜
        pass
    try:
        for _r in conn.execute(
                "SELECT entity_id, alias FROM dd_v1_entity_aliases "
                "WHERE library_id=? AND alias_kind<>?",
                (lib, "DIRECTORY")):
            _n = str(_r["alias"] or "").strip()
            if _n:
                out.append((_n, str(_r["entity_id"] or "")))
    except Exception:  # noqa: BLE001 — 别名表还没有就当没有
        pass
    return sorted(out, key=lambda kv: (-len(kv[0]), kv[0]))


def entity_scope_from_registry(
    raw: str,
    tokens: list[tuple[str, str]],
) -> tuple[str, str]:
    """**回落查权威名单**：原文里**逐字**出现了哪个登记名/别名。

    ★ gm-fix-f2-subject-scope: F2（MAJOR）
      口径（**不猜不退化**）：
        - 只认**逐字出现**的登记串 ⇒ 认不出还是认不出（不模糊、不语义猜）；
        - **最长匹配**且唯一 ⇒ 取它（更具体的那个）；
        - 多个**同等长度**的登记串同时出现 ⇒ 不知该指谁 ⇒ **不猜**（UNKNOWN）；
        - 命中**别名**时，判定层照常用别名表归一（**别名从此才有机会生效**）。
      ★ 返回的 scope 复用 `entity_hint:` 前缀 ⇒ 对外仍是**脱敏标签**，
        原文不落任何交付面。
    """
    text = str(raw or "")
    if not text.strip() or not tokens:
        return "", UNKNOWN
    best_len = 0
    best: list[tuple[str, str]] = []
    for _tok, _eid in tokens:
        if len(_tok) < 2:
            continue
        if _tok not in text:
            continue
        if len(_tok) > best_len:
            best_len = len(_tok)
            best = [(_tok, _eid)]
        elif len(_tok) == best_len:
            best.append((_tok, _eid))
    if not best:
        return "", UNKNOWN
    if len({e for _t, e in best}) > 1:
        # ★ 同等长度、指向**不同主体** ⇒ 判定不了该指谁 ⇒ 不猜
        return "", UNKNOWN
    return f"{ENTITY_HINT_PREFIX}{best[0][0]}", INFERRED


def parse_entity_scope(raw: str, registry=None) -> tuple[str, str]:
    """识别主体范围。**只认原文明文**，不推测。

    A2（G-A2-11）：除原有的范围口径外，新增**主体前缀**口径
    （「<主体简称>：<要求>」）⇒ ``("entity_hint:<简称>", INFERRED)``。
    ★ basis 是 **INFERRED**（不是 FACT）：简称是线索，不是法律事实；
      是否真的对上登记主体，由判定层用**权威名单**核实。

    ★ gm-fix-f2-subject-scope: F2（MAJOR）
      新增**回落查权威名单**路径 —— 前缀口径与 FACT 范围口径都落空时，
      用**本库登记的主体名/别名**在原文里逐字找一次
      （`entity_scope_from_registry`）。
      ★ 顺序不变：**文本前缀命中 > FACT 范围 > 名单回落**
        ⇒ 既有口径**不被削弱**（FACT 范围不会被回落路径覆盖）。
    """
    _hint = subject_hint_prefix(raw)
    if _hint:
        return f"{ENTITY_HINT_PREFIX}{_hint}", INFERRED
    if _SCOPE_GROUP_SUB.search(raw):
        return "group_and_subs", FACT
    if _SCOPE_SUBS.search(raw):
        return "subsidiaries", FACT
    if _SCOPE_PARENT.search(raw):
        return "parent_only", FACT
    if _SCOPE_SELF.search(raw):
        return "self", FACT
    # ★ gm-fix-f2-subject-scope: 回落查权威名单/别名表
    #   （**只认登记过的、逐字出现的**；匹配不到就还是不知道 ⇒ 不猜不退化）
    if registry:
        _sc, _bs = entity_scope_from_registry(raw, registry)
        if _sc:
            return _sc, _bs
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

    # ★ A2（G-A2-5）：**提到了期间但解析不出绝对区间** ⇒ basis="unresolved"
    #   （**不是** UNKNOWN：UNKNOWN 表示「文本压根没提期间」，该维度不构成门槛；
    #     而「提了却解析不出」必须诚实地说「期间无法解析」并降 UNCERTAIN，
    #     否则期间闸门会被**静默丢掉** —— 那是危险方向：闸门消失，不是变松）。
    m = _PERIOD_MENTION.search(raw)
    if m:
        notes.append(f"文本提及期间「{m.group(0)}」但未能解析为绝对区间")
        return 0, 0, "unresolved", notes

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


# ── 「应有几份」的份数口径（G-A3-1）────────────────────────────────────────
#: 份数的**提及**形态：
#:   ① 数字 + 份（「3 份」「一式两份」）
#:   ② 「若干/多/数/几 份」（⇒ 提到了但**数不出**）
#:   ③ 「份数」（⇒ 提到了但可能没给数）
#: ★ 「部分」里的「份」**不算**（那是词的一部分，不是数量）——
#:   否则「请提供部分材料」会被当成份数要求 ⇒ 白白把义务判成 UNCERTAIN。
_COUNT_MENTION_RE = re.compile(
    r"(?:[0-9０-９]+|[一二两三四五六七八九十]+)\s*份"
    r"|(?:若干|多|数|几)\s*份"
    r"|份数"
)
#: 可解析的**具体**份数：「N 份」或「份数为 N」
_COUNT_NUM_RE = re.compile(
    r"([0-9]+|[一二两三四五六七八九十]+)\s*份"
    r"|份数\s*(?:为|是|[:：])?\s*([0-9]+|[一二两三四五六七八九十]+)"
)
_CN_COUNT_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                 "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def parse_expected_count(raw: str) -> tuple[int | None, str]:
    """解析清单原文里的**「应有几份」**。

    返回 ``(expected_count, basis)``，三态语义（A3-1）：

    | 返回 | 含义 | 齐套判定上的后果 |
    |---|---|---|
    | ``(N, FACT)`` | 原文明文给出份数（「一式两份」「3 份」） | 份数维**构成门槛**，需 N 份 |
    | ``(N, INFERRED)`` | 多处份数求和（「正本 1 份、副本 1 份」⇒ 2） | 同上 |
    | ``(None, UNKNOWN)`` | 原文**提及**份数但**解析不出**（「若干份」「多份」） | 份数维**不可判定** ⇒ 判 UNCERTAIN + 人工确认 |
    | ``(0, UNKNOWN)`` | 原文**根本没提**份数 | 份数维**不构成门槛**（与「期间未提」「无附件」同规格） |

    ★ **不得默认 1 份**：解析不出时留 ``None``（不是 1），
      让判定层诚实地说「这一维不可判定」，而不是替人编造一个权威份数。
    """
    text = str(raw or "")
    if not _COUNT_MENTION_RE.search(text):
        return 0, UNKNOWN
    nums: list[int] = []
    for m in _COUNT_NUM_RE.finditer(text):
        tok = m.group(1) or m.group(2)
        if not tok:
            continue
        n = int(tok) if tok.isdigit() else _CN_COUNT_NUM.get(tok)
        if n and n > 0:
            nums.append(n)
    if not nums:
        return None, UNKNOWN
    total = sum(nums)
    if len(nums) == 1:
        return total, FACT
    return total, INFERRED


def build_obligations(
    raw: str,
    anchor_year: int | None = None,
    registry=None,
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
    # ★ A2（G-A2-11 · 11d）：同一条清单项切出的并列义务**共享主体前缀**。
    #   「<主体>：最新的营业执照正、副本复印件」按「、」切成两条后，
    #   第二条若丢掉前缀 ⇒ 主体维度**无门槛放行** ⇒ 假 MATCHED 的口子。
    #   ⇒ 把第一段识别到的主体前缀**传给同项的其它片段**。
    #   ★ 只传**主体口径**，**不改义务原文**（原文零丢失是硬校验）。
    _hint_scope = ""
    if parts:
        # ★ gm-fix-f2-subject-scope: 同项的并列片段**共享**主体口径
        #   （名单回落也算一种口径 ⇒ 同一项的其它片段同样继承）
        _s, _b = parse_entity_scope(parts[0], registry=registry)
        if _s.startswith(ENTITY_HINT_PREFIX):
            _hint_scope = _s
    for _idx, part in enumerate(parts):
        ob = Obligation(obligation=part)
        ob.entity_scope, ob.entity_basis = parse_entity_scope(part, registry=registry)
        if _idx > 0 and _hint_scope:
            ob.entity_scope, ob.entity_basis = _hint_scope, INFERRED
        ob.period_from, ob.period_to, ob.period_basis, notes = parse_period(
            part, anchor_year)
        ob.notes.extend(notes)
        ob.doc_type, ob.doc_type_basis = parse_doc_type(part)
        ob.caliber, ob.caliber_basis = parse_caliber(part)
        ob.seal_required, _ = parse_seal(part)
        ob.needs_attachments, ob.attachment_basis = parse_attachments(part)
        # ★ A3（G-A3-1）：份数从**本段原文**解析（拆分后的每段各管各的份数）。
        ob.expected_count, ob.expected_count_basis = parse_expected_count(part)
        if ob.expected_count is None:
            ob.notes.append("清单提及份数但无法解析出权威份数，份数维不可判定")
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
def _checklist_fingerprint(library_id: str, institution: str, item_no: str,
                           raw_text: str) -> str:
    """清单条目的**内容指纹**（前 16 位 sha256）。

    **只含结构化字段**（库 / 机构 / 条目编号 / 原文归一化空白）——
    **不打印真实文件名与路径**，因此可以安全地写进结构化日志。
    """
    h = hashlib.sha256()
    for part in (library_id or "", institution or "", item_no or "",
                 " ".join(str(raw_text or "").split())):
        h.update(str(part).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


def _checklist_digest(fingerprints: list) -> str:
    """整份清单的**摘要指纹**（版本标识）。"""
    h = hashlib.sha256()
    for fp in sorted(fingerprints):
        h.update(str(fp).encode("ascii"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


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
    # ★ gm-fix-f2-subject-scope: F2（MAJOR）
    #   本库**权威主体名单 + 别名**的回落词表（**一次取**，循环里共用
    #   ⇒ 不重复读库、也保证同一次摄取里口径一致）。
    _registry = entity_registry_tokens(library_id, conn, db_path)

    # ── A2（G-A2-9）幂等：同一份清单重复摄取**不得**产生重复义务 ──────────
    # 旧实现每次都 INSERT 新 item + 新义务（uuid4）⇒ 同一 data dir 跑两次
    # ⇒ 义务数翻倍（实测 32 → 64）⇒ 判定数字全部失真。
    # 现在按**内容指纹**去重：已存在 ⇒ 跳过并留痕（跳过条数 + 指纹），
    # 不重复入库。**不得**用「清空数据目录」来回避幂等（那是掩盖，不是修复）。
    seen_fp = set()
    for _row in conn.execute(
            "SELECT item_no, institution, raw_text FROM dd_v1_checklist_items "
            "WHERE library_id=?", (library_id,)):
        seen_fp.add(_checklist_fingerprint(library_id, _row["institution"],
                                           _row["item_no"], _row["raw_text"]))
    skipped_dup = 0
    skipped_fps: list = []
    new_fps: list = []

    for r in rows:
        raw = (r.get("raw_text") or "").strip()
        if not raw:
            dropped.append({"item_no": r.get("item_no", ""),
                            "reason": "原文为空，拒绝入库（不得凭空生成要求）"})
            continue
        fp = _checklist_fingerprint(library_id, institution,
                                    r.get("item_no") or "", raw)
        if fp in seen_fp:
            skipped_dup += 1
            skipped_fps.append(fp)
            continue
        seen_fp.add(fp)
        new_fps.append(fp)
        item_uid = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO dd_v1_checklist_items
               (item_uid, library_id, institution, item_no, raw_text, source_ref, parsed_at)
               VALUES (?,?,?,?,?,?,?)""",
            (item_uid, library_id, institution, r.get("item_no") or "",
             raw, r.get("source_ref") or "", now),
        )
        n_items += 1

        for seq, ob in enumerate(
                build_obligations(raw, anchor_year, registry=_registry), 1):
            payload = ob.to_dict()
            conn.execute(
                """INSERT INTO dd_v1_obligations
                   (obligation_id, item_uid, library_id, seq, obligation,
                    entity_scope, entity_basis, period_from, period_to, period_basis,
                    doc_type, doc_type_basis, caliber, caliber_basis, seal_required,
                    needs_attachments, attachment_basis, disclosure,
                    expected_count, expected_count_basis, fields_json,
                    notes, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, item_uid, library_id, seq, ob.obligation,
                 ob.entity_scope, ob.entity_basis, ob.period_from, ob.period_to,
                 ob.period_basis, ob.doc_type, ob.doc_type_basis, ob.caliber,
                 ob.caliber_basis, ob.seal_required, ob.needs_attachments,
                 ob.attachment_basis, ob.disclosure,
                 ob.expected_count, ob.expected_count_basis,
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
    # A2（G-A2-9）：去重后库里条目数会**多于**本次新增数 ⇒ 这里用 ``>=``；
    # 真正的硬校验是下面的逐条「原样取回」检查（新增与跳过的条目都要取得到）。
    roundtrip_ok = len(stored) >= n_items
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
        # A2（G-A2-9）幂等留痕：跳过条数 + 指纹（**不含真实文件名/路径**）
        "skipped_duplicates": skipped_dup,
        "checklist_fingerprint": _checklist_digest(new_fps + skipped_fps),
        "skipped_fingerprints": skipped_fps[:50],
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

    if scope.startswith(ENTITY_HINT_PREFIX):
        # ★ A2（G-A2-11 · 11b）：义务指名了某个主体 ⇒ 解析成**该主体**的登记行。
        #   简称先经 `normalize_name` 归一（剥副本后缀）⇒
        #   清单里的「<主体简称>公司」能对上登记的别名「<主体简称>公司(1)」。
        #   命中不了 ⇒ 返回空 ⇒ 调用方据此判「未登记」（不猜、不退化）。
        hint = scope.split(":", 1)[1].strip()
        if not hint:
            return []
        try:
            from cangjie_fos.services import dd_v1_entity_service as es
            amap = es.alias_map(library_id, db_path)
        except Exception:  # noqa: BLE001
            amap = {}
        try:
            from cangjie_fos.services import dd_v1_entity_service as es
            key = es.normalize_name(hint)
        except Exception:  # noqa: BLE001
            key = hint
        # ★ A2（G-A2-13）：查表键**由严到宽**：先原样归一（命中带角色后缀的登记别名），
        #   再剥掉角色括号后缀（命中只登记了干净简称的情况）。
        keys = _hint_lookup_keys(hint)
        hit = None
        for _k in keys:
            _cand = amap.get(_k)
            if _cand and _cand.get("entity_id"):
                hit = _cand
                break
        if hit and hit.get("entity_id"):
            eid = str(hit.get("entity_id"))
            return [r for r in rows if str(r.get("entity_id")) == eid]
        # ★ A2（G-A2-13 配套）：**登记全称**逐字相等（归一后）也要算命中 ——
        #   与材料侧 `dd_v1_entity_service.match_entity` 的第一档**同一口径**。
        #   ★ 义务侧只查别名表而材料侧认全称 ⇒ 就是**两套口径**（G-A2-3 要消灭的东西）。
        #   ★ 只认逐字相等（归一后），不做模糊匹配、不做子串匹配。
        try:
            from cangjie_fos.services import dd_v1_entity_service as es
            _norm = es.normalize_name
        except Exception:  # noqa: BLE001
            _norm = lambda x: str(x or "").strip().casefold()  # noqa: E731
        for _r in rows:
            _dn = str(_r.get("display_name") or "").strip()
            if not _dn:
                continue
            if any(_norm(_dn) == _k for _k in keys):
                return [_r]
        return []

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
