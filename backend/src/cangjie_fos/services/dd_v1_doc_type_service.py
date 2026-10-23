"""材料类型（规范 key）解析 —— **G-A2-7 总开关**。

为什么必须有这个模块
------------------
认知卡的 ``doc_type`` 字段过去存的是**文件扩展名**（pdf / xlsx / png …）。
那不是材料类型。于是两件事同时坏掉：

1. **语义层证据池恒空** —— ``dd_v1_semantic_retrieval_service.retrieve_minimal_evidence``
   按 ``m["doc_type"] == ob["doc_type"]`` 精确过滤，义务侧是规范 key
   （``audit_report``），材料侧是 ``"pdf"`` ⇒ **一份材料都取不到**
   （「语义链接上了但拿不到料」）。
2. **披露规则层惰性** —— ``dd_v1_policy_service`` 的 ``rules[].doc_type``
   同样按精确值匹配；``evaluate(pol, "PUBLIC", doc_type="pdf")``
   **一条规则都不命中** ⇒ 身份证 / 银行流水 / 人事薪酬 / 客户名单等
   十类不放开材料在真实卡片上**打不中任何收紧规则**。

本模块是**材料类型取值的唯一来源**。

取值空间只有一个
--------------
``dd_v1_requirement_service._DOC_TYPE_RULES`` 的 10 个英文 key：
``audit_report`` / ``financial_statement`` / ``tax`` / ``license`` /
``charter`` / ``capital`` / ``resolution`` / ``ip`` / ``labor`` / ``contract``。

- 中文类型名（审计报告…）**不是**合法取值，只是给人读的；
- 文件扩展名（pdf / xlsx…）**不是**合法取值；
- 认不出 ⇒ **留空标 UNKNOWN**，**不得**拿扩展名或中文名占位。

**本模块不抄规则表**：判断与解析一律走 ``dd_v1_requirement_service`` 的公开 API，
避免仓内出现第二套类型口径（同一套正则只允许有一份来源）。

取值顺序（**不可改**）
------------------
1. **文件名关键词** —— 材料的类型身份主要由它自己叫什么决定；
2. **正文关键词**（只取正文头部）—— 材料的自述标题在这一段；
3. **卡片 purpose**；
4. 认不出 ⇒ ``("", UNKNOWN, 说明)``。

**为什么只看文件名、不看整个相对路径**：真实材料库普遍按法人/类型建多级目录，
实测出现过形如 ``1.审计报告(1)/营业执照2024.pdf`` 的布局——
用整条路径判定会把**目录里别人的类型**认成**这份材料的类型**。
只看文件自己的名字才是「这份材料是什么」。

provenance 一律 **INFERRED**
------------------------
材料不会「自称」自己是审计报告；类型是从可观察线索**推断**出来的，
不是法律事实。（人工复核定级由 ``dd_v1_card_service.set_human_override``
负责保留，见该函数。）
"""
from __future__ import annotations

import re
from pathlib import Path

from cangjie_fos.services import dd_v1_requirement_service as rq

FACT = "FACT"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"

# 正文里判定材料类型时**只看头部**：材料自述标题在这一段；
# 正文后段常提到别的材料类型（合同 / 协议 / 章程…），按全文判定会认错类型。
CONTENT_HEAD_CHARS = 800


def is_canonical(doc_type: str) -> bool:
    """``doc_type`` 是否已经是**规范 key**。

    中文类型名、文件扩展名、拼错的 key 一律返回 ``False``。

    实现走 ``rq.doc_type_search_terms``（公开 API），**不抄规则表**。
    """
    raw = str(doc_type or "").strip().lower()
    if not raw:
        return False
    return bool(rq.doc_type_search_terms(raw))


def normalize_doc_type(value: str) -> str:
    """把**任意来源**的 doc_type 归一到规范 key（英文）。

    这是「**比较/归一环节**」的唯一入口：证据池、义务侧、材料侧都先过这里，
    再做相等比较 ⇒ **两侧 key 空间不同就不会再把证据池筛空**。

    - 已是规范 key（``audit_report`` 等）⇒ 原样返回（大小写归一）；
    - 中文类型名（审计报告 / 社保缴纳证明 等）⇒ 用 ``rq.parse_doc_type`` 归一到 key
      （**旧 meta / 旧 fixture 里的中文 doc_type 仍然可用**，不必一次性改完调用方）；
    - 文件扩展名（pdf / xlsx）、乱写、认不出 ⇒ **空串**（= UNKNOWN），
      **不得**拿扩展名或中文名占位。
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    if is_canonical(raw):
        return raw.lower()
    key, _basis = rq.parse_doc_type(raw)
    return key


#: **索引/目录件**识别（这类文件**不是材料**，只是同目录材料的列表）
_INDEX_ARTIFACT_RE = re.compile(
    r"(索引|目录|文件说明|材料目录|readme|^index)", re.IGNORECASE)


def is_index_artifact(file_name: str) -> bool:
    """这个文件是**索引/目录/清单件**而不是一份材料吗？

    为什么必须有这个判断（G-A2-10 · 10a）
    --------------------------------------
    真实材料库里普遍有「00_索引.md」这类文件，它只是把同目录的材料列一遍。
    ⚠️ 它**不是**材料，但过去会被当成材料：

    1. 它的正文里写着「2022年审计报告」等字样 ⇒ 被解析成 ``audit_report``；
    2. 于是它与**真正的**审计报告**同主体 + 同期间 + 同类型**落进同一冲突桶
       ⇒ 内容哈希不同 ⇒ **假 CONFLICT**。

    ⇒ 索引件必须**排除出材料判定**：不作为类型证据、不参与冲突判定、
      不可交付；但**必须留痕**（不得静默丢弃）。

    判据刻意**保守**：只认「索引/目录/文件说明/readme/index」与「00 序号开头
    的 md/txt/csv」两种形态 —— 宁可漏判（当作普通材料）也不误杀真材料。
    """
    name = Path(str(file_name or "")).name.strip()
    if not name:
        return False
    stem = Path(name).stem
    if _INDEX_ARTIFACT_RE.search(stem):
        return True
    if re.match(r"^\d{1,2}[_\-.]", stem) and Path(name).suffix.lower() in (".md", ".txt", ".csv"):
        # 「00_xxx」这类序号件：只有 md/txt/csv 才算索引件（xlsx/pdf 可能是真材料）
        return True
    return False


def resolve_doc_type(
    file_name: str = "",
    text: str = "",
    purpose: str = "",
) -> tuple[str, str, list[dict]]:
    """解析材料的规范类型。

    返回 ``(key, provenance, evidence)``：
    认不出时 ``key == ""``、``provenance == UNKNOWN``，**evidence 仍要说明为什么不知道**。
    """
    name = Path(str(file_name or "")).name.strip()

    # 1) 文件名关键词
    if name:
        key, _basis = rq.parse_doc_type(name)
        if key:
            return key, INFERRED, [{
                "kind": "filename_keyword",
                "loc": name,
                "rule": "文件名命中规范材料类型关键词。"
                        "只取文件自己的名字，不取目录名"
                        "（目录名常是别的材料的类型，不能当作本材料的类型）",
            }]

    # 2) 正文关键词（只看头部）
    head = str(text or "")[:CONTENT_HEAD_CHARS]
    if head:
        key, _basis = rq.parse_doc_type(head)
        if key:
            return key, INFERRED, [{
                "kind": "content_keyword",
                "loc": f"{name}#正文头部",
                "rule": "正文头部命中规范材料类型关键词；"
                        "材料类型是推断结论，不是法律事实",
            }]

    # 3) 卡片用途
    pur = str(purpose or "")
    if pur:
        key, _basis = rq.parse_doc_type(pur)
        if key:
            return key, INFERRED, [{
                "kind": "purpose_keyword",
                "loc": f"{name}#purpose",
                "rule": "卡片用途关键词命中规范材料类型",
            }]

    # 4) 认不出 —— 留空标 UNKNOWN，**不用扩展名占位**
    return "", UNKNOWN, [{
        "kind": "unresolved",
        "note": "未识别材料类型；不得用文件扩展名或中文类型名占位"
                "（认不出就是认不出，交给人工）",
    }]
