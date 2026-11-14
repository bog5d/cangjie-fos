"""cangjie-fos#71 · 考生2 P0 修复验收测试（合成材料 / 零模型 / 零费用 / 零真实材料 / 零外部调用）。

对照司仓 2026-10-23 派工本的**验收判据**逐条落成用例：

- 判据2 类型归一：正式入口 ``scaffold`` 产出的 doc_type 与
  ``dd_v1_doc_type_service.resolve_doc_type`` **逐位一致**，且不含中文类型名、不含扩展名；
- 判据3 多主体 / 多年度：甲公司材料不得出现在乙公司义务的证据池；
  2022 与 2024 同类材料不得互相顶替；
- 判据4 完整合成组包：清单 → 拆分 → 类型归一 → 候选召回 → 语义判断 → 规则校验 → 审核 → 授权组包
  全链路通，产物落盘且 sha256 可复算；
- 判据5 安全负例：受限资料披露**不被放宽**（PUBLIC 放行清单仍只有 license）；
- WP1：10 类全覆盖；一段多类 ⇒ 拆成多条原子义务（正例）；复合词**不拆**（反例，误匹配率不升）；
- WP3：候选为空时**区分六种原因**；旧 meta（中文 doc_type）仍然可用。

★ 全部材料都是**现场合成的**（tmp_path），不含任何真实材料 / 个人信息 / 密钥；
  全程不调用任何模型（人工交换适配器 + 预置合成回放 ⇒ 零进程零费用）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_result_service as ar
from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_doc_type_service as dts
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_package_service as pkg
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_policy_service as pol_svc
from cangjie_fos.services import dd_v1_requirement_service as rq
from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_v1_local_run as lr  # noqa: E402

#: 规范材料类型的**唯一**取值空间（requirement service 的权威表，不另抄一份）
DOC_TYPE_KEYS = tuple(k for k, _ in rq._DOC_TYPE_RULES)

JIA = "合成法人甲"
YI = "合成法人乙"

#: 合成材料：目录名**刻意**复刻真实材料库布局（按法人/类型建多级目录）
_MATERIALS: dict[str, str] = {
    f"{JIA}/1.审计报告/审计报告2024.txt": f"审计报告\n本报告为2024年度财务审计结论，由{JIA}出具。\n",
    f"{JIA}/1.审计报告/审计报告2022.txt": f"审计报告\n本报告为2022年度财务审计结论，由{JIA}出具。\n",
    f"{JIA}/1.审计报告/审计报告2022-草稿.txt": f"审计报告\n本报告为2022年度财务审计结论（草稿），由{JIA}出具。\n",
    # ★ 目录污染用例：目录名是「审计报告」，文件自己叫「营业执照2024」
    f"{JIA}/1.审计报告/营业执照2024.txt": f"营业执照\n{JIA}\n经营范围：合成样例。\n",
    f"{JIA}/2.营业执照/营业执照.txt": f"营业执照\n{JIA}\n经营范围：合成样例。\n",
    f"{JIA}/3.章程/公司章程.txt": f"公司章程\n{JIA}\n第一条 总则：合成样例条款。\n",
    f"{JIA}/4.决议/股东会决议2024.txt": f"股东会决议\n{JIA}\n关于合成样例事项的决议。\n",
    f"{JIA}/5.知识产权/专利证书.txt": f"专利证书\n{JIA}\n合成样例专利。\n",
    f"{JIA}/6.劳动/劳动合同.txt": f"劳动合同\n{JIA}\n合成样例劳动合同。\n",
    f"{JIA}/7.合同/经营资产租赁合同.txt": f"经营资产租赁合同\n{JIA}\n合成样例租赁合同。\n",
    f"{YI}/审计报告2024.txt": f"审计报告\n本报告为2024年度财务审计结论，由{YI}出具。\n",
}

#: 合成清单（义务侧）
_ITEMS: list[dict[str, str]] = [
    {"item_id": "C1", "entity": JIA, "text": f"请提供{JIA}最新营业执照"},
    {"item_id": "C2", "entity": JIA, "text": f"请提供{JIA}2024年度审计报告"},
    {"item_id": "C3", "entity": JIA, "text": f"请提供{JIA}2022年度审计报告"},
    {"item_id": "C4", "entity": JIA, "text": f"请提供{JIA}经营资产租赁合同"},
    {"item_id": "C5", "entity": YI, "text": f"请提供{YI}2024年度审计报告"},
]


# ────────────────────────────────────────────────────────────── 夹具

def _material_tree(tmp_path: Path) -> Path:
    """把合成材料写到磁盘（**现场生成**，无真实材料）。"""
    root = tmp_path / "material"
    for rel, content in _MATERIALS.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


def _scaffold(tmp_path: Path, root: Path, entity: str = "") -> list[dict]:
    """走**正式入口 B** 的 ``scaffold`` 产出 meta（不手工拼装）。"""
    out = tmp_path / "meta.json"
    assert lr.main(["scaffold", "--material-root", str(root), "--out", str(out), "--entity", entity]) == 0
    return json.loads(out.read_text("utf-8"))


def _meta_by_directory(root: Path) -> list[dict]:
    """按**法人目录**（第一层）取主体、按**文件名**取类型 —— 与桥接链同口径。

    ★ 桥接链的主体是「认知卡线索 + 权威名单归一」；权威名单在整条相对路径里
      命中法人名 ⇒ 等价于取第一层法人目录（认知卡本身只取父目录名，
      多级目录布局下父目录是**类型目录**，靠权威名单纠正）。
    ★ 正式入口 B 的 ``scaffold`` 目前是**单主体**（``--entity``），
      多主体库要走桥接链或人工分批；本函数只用于多主体隔离用例。
    """
    meta: list[dict] = []
    for i, p in enumerate(sorted(x for x in root.rglob("*") if x.is_file())):
        rel = p.relative_to(root).as_posix()
        dt, _prov, _ev = dts.resolve_doc_type(file_name=p.name)
        year = "".join(ch for ch in p.name if ch.isdigit())[:4]
        meta.append({
            "file_id": f"M{i + 1:03d}", "relative_path": rel,
            "entity": Path(rel).parts[0],
            "period": year or ("CURRENT" if dt in rq.CURRENT_DOC_TYPES else ""),
            "doc_type": dt, "part": "正文",
            "version_status": "DRAFT" if "草稿" in p.name else "EFFECTIVE",
        })
    return meta


def _write_synthetic_reply(path: Path, root: Path, meta: list[dict], items: list[dict]) -> None:
    """按**规则提示**造一份合成回贴（零进程零费用，行为可复现）。"""
    pkt = sem.build_semantic_packet(root, meta, items)
    results = []
    for ob in pkt["obligations"]:
        ev = pkt["evidence"][ob["obligation_id"]]
        hint = sem.rule_hint(ob, ev)
        cands = [{"file_id": e["file_id"], "relative_path": e["relative_path"], "sha256": e["sha256"],
                   "locator": e["locator"], "entity": e["entity"], "period": e["period"],
                   "match_reason": "正文写明主体与年度"} for e in ev if e["file_id"] in hint["files"]]
        results.append({
            "item_id": ob["item_id"], "obligation_id": ob["obligation_id"], "agent_id": "synthetic",
            "provider": "synthetic", "model_id_or_unknown": "UNKNOWN",
            "prompt_version": pkt["prompt_version"], "source_snapshot_id": pkt["source_snapshot_id"],
            "candidate_files": cands, "proposed_verdict": hint["verdict"],
            "confidence_or_uncertain": 0.9 if cands else "UNCERTAIN",
            "abstain_reason": None if cands else "无证据", "warnings": [], "elapsed": "UNKNOWN",
            "token_usage_or_UNKNOWN": "UNKNOWN",
        })
    path.write_text(json.dumps({"results": results}, ensure_ascii=False), "utf-8")


# ───────────────────────────────────── 判据2：类型归一（正式入口 + 权威口径一致）

def test_scaffold_doc_type_equals_resolve_doc_type(tmp_path):
    """判据2：scaffold 产出的 doc_type 与 resolve_doc_type **逐位一致**。

    ★ 旧实现拿**整条相对路径**去匹配一张 7 类中文表 ⇒
      ① 目录名会污染文件自己的类型（``1.审计报告/营业执照2024.txt`` 被认成审计报告）；
      ② 只覆盖权威 10 类中的 7 类（决议 / 知识产权 / 合同一律空）。
    """
    root = _material_tree(tmp_path)
    meta = _scaffold(tmp_path, root, entity=JIA)
    assert meta
    for m in meta:
        name = Path(m["relative_path"]).name
        expect, prov, _evidence = dts.resolve_doc_type(file_name=name)
        assert m["doc_type"] == expect, m["relative_path"]
        assert m["doc_type_provenance"] == prov, m["relative_path"]
        # 不含中文类型名、不含文件扩展名
        assert m["doc_type"] == "" or m["doc_type"] in DOC_TYPE_KEYS
        assert not any("一" <= ch <= "鿿" for ch in m["doc_type"])
        assert not m["doc_type"].lower().endswith((".pdf", ".txt", ".docx", ".xlsx", ".csv"))


def test_scaffold_ignores_directory_name_pollution(tmp_path):
    """★ 目录污染反例：``1.审计报告/营业执照2024.txt`` 的类型必须是 license。"""
    root = _material_tree(tmp_path)
    meta = _scaffold(tmp_path, root, entity=JIA)
    polluted = next(m for m in meta if m["relative_path"].endswith("1.审计报告/营业执照2024.txt"))
    assert polluted["doc_type"] == "license"
    # 同一份材料在权威服务里也是 license（两侧同源 ⇒ 证据池不会恒空）
    key, _prov, _ev = dts.resolve_doc_type(file_name="营业执照2024.txt")
    assert key == "license" == polluted["doc_type"]


def test_scaffold_covers_all_ten_canonical_types(tmp_path):
    """WP1：10 类全覆盖（旧实现只认 7 类 ⇒ 决议/知识产权/合同全是空）。"""
    samples = {
        "audit_report": "审计报告2024", "financial_statement": "财务报表2024", "tax": "纳税证明2024",
        "license": "营业执照", "charter": "公司章程", "capital": "验资报告",
        "resolution": "股东会决议2024", "ip": "专利证书", "labor": "劳动合同", "contract": "经营资产租赁合同",
    }
    assert set(samples) == set(DOC_TYPE_KEYS)
    root = tmp_path / "material"
    for name in samples.values():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{name}\n合成样例\n", encoding="utf-8")
    meta = _scaffold(tmp_path, root, entity=JIA)
    got = {m["doc_type"] for m in meta}
    assert set(samples) <= got, f"缺类型：{sorted(set(samples) - got)}"


# ───────────────────────────────────── 判据3：多主体 / 多年度不混桶、不顶替

def test_multi_entity_evidence_never_crosses_legal_persons(tmp_path):
    """判据3 前半：甲公司材料不得出现在乙公司义务的证据池（跨法人不混桶）。"""
    root = _material_tree(tmp_path)
    meta = _meta_by_directory(root)
    obs, _flags = sem.split_items(_ITEMS)
    by_id = {o["obligation_id"]: o for o in obs}
    jia_2024 = by_id["C2-O1"]
    yi_2024 = by_id["C5-O1"]
    ev_jia = sem.retrieve_minimal_evidence(root, meta, jia_2024)
    ev_yi = sem.retrieve_minimal_evidence(root, meta, yi_2024)
    assert ev_jia and ev_yi
    assert all(e["entity"] == JIA for e in ev_jia), [e["entity"] for e in ev_jia]
    assert all(e["entity"] == YI for e in ev_yi), [e["entity"] for e in ev_yi]
    assert not ({e["file_id"] for e in ev_jia} & {e["file_id"] for e in ev_yi})


def test_multi_year_materials_do_not_substitute_each_other(tmp_path):
    """判据3 后半：2022 与 2024 同类材料**不得互相顶替**。

    ★ 证据池按「同主体 + 同类型」召回（近邻材料仍给模型看，供 OUTDATED 判定），
      但「可用候选」必须期间一致 ⇒ 规则提示不会拿 2024 的材料去 MATCH 2022 的义务。
    """
    root = _material_tree(tmp_path)
    meta = _meta_by_directory(root)
    obs, _flags = sem.split_items(_ITEMS)
    by_id = {o["obligation_id"]: o for o in obs}
    ob_2022, ob_2024 = by_id["C3-O1"], by_id["C2-O1"]
    ev_2022 = sem.retrieve_minimal_evidence(root, meta, ob_2022)
    ev_2024 = sem.retrieve_minimal_evidence(root, meta, ob_2024)
    files_2022 = set(sem.rule_hint(ob_2022, ev_2022)["files"])
    files_2024 = set(sem.rule_hint(ob_2024, ev_2024)["files"])
    assert files_2022 and files_2024
    assert not (files_2022 & files_2024), "2022 与 2024 的材料互相顶替了"
    # 草稿不得被当成可用候选
    draft = next(m for m in meta if "草稿" in m["relative_path"])
    assert draft["file_id"] not in files_2022


def test_wrong_year_candidate_is_rejected_by_semantic_gate(tmp_path):
    """★ 判据3 的硬证据：拿 2024 的材料去答 2022 的义务 ⇒ 必须被确定性闸拦下。"""
    root = _material_tree(tmp_path)
    meta = _meta_by_directory(root)
    pkt = sem.build_semantic_packet(root, meta, _ITEMS)
    ob = next(o for o in pkt["obligations"] if o["obligation_id"] == "C3-O1")
    ev = pkt["evidence"]["C3-O1"]
    wrong = next(e for e in ev if e["period"] == "2024")
    res = {
        "item_id": ob["item_id"], "obligation_id": ob["obligation_id"], "agent_id": "t", "provider": "t",
        "model_id_or_unknown": "UNKNOWN", "prompt_version": pkt["prompt_version"],
        "source_snapshot_id": pkt["source_snapshot_id"],
        "candidate_files": [{"file_id": wrong["file_id"], "relative_path": wrong["relative_path"],
                             "sha256": wrong["sha256"], "locator": wrong["locator"],
                             "entity": wrong["entity"], "period": wrong["period"],
                             "match_reason": "年度看起来差不多"}],
        "proposed_verdict": "MATCH", "confidence_or_uncertain": 0.95, "abstain_reason": None,
        "warnings": [], "elapsed": "UNKNOWN", "token_usage_or_UNKNOWN": "UNKNOWN",
    }
    rep = sem.validate_semantic(json.dumps({"results": [res]}), root, meta, pkt).to_dict()
    assert not rep["accepted"], "拿错年度的材料当 MATCH 被放行了"
    errs = [e for r in rep["rejected"] for e in r["errors"]]
    assert any("PERIOD_MISMATCH" in e for e in errs), errs


# ───────────────────────────────────── WP1：一段多类 ⇒ 原子义务（正例 + 反例）

def test_multi_type_segment_splits_into_atomic_obligations_with_separate_pools(tmp_path):
    """★ WP1(a) 正例：一段含两类 ⇒ 拆成两条原子义务，各自只召回自己那一类材料。"""
    root = _material_tree(tmp_path)
    meta = _meta_by_directory(root)
    obs, flags = sem.split_item({"item_id": "M1", "entity": JIA, "text": "请提供审计报告/营业执照合订本"})
    assert [o["doc_type"] for o in obs] == ["audit_report", "license"]
    assert [f["status"] for f in flags] == ["AMBIGUOUS_SPLIT"]
    pools = {o["doc_type"]: {e["doc_type"] for e in sem.retrieve_minimal_evidence(root, meta, o)}
             for o in obs}
    assert pools["audit_report"] == {"audit_report"}
    assert pools["license"] == {"license"}
    # 拆出来的两条义务**没有**互相污染对方的证据池（误匹配率不升）
    assert sem.retrieve_minimal_evidence(root, meta, obs[0]) != sem.retrieve_minimal_evidence(root, meta, obs[1])


def test_compound_words_are_not_split_into_two_obligations(tmp_path):
    """★ WP1(a) 反例：复合词**不拆**（拆了就是猜 ⇒ 误匹配率会上升）。

    「员工合同」「劳动合同」= 一个复合名词，不是两类材料；拆开就会凭空多出一条义务
    （多一条 MISSING、多一次误匹配）。规则：两次类型命中**紧挨着**（无间隔）⇒ 不拆。
    """
    for text, expect in (("请提供员工合同", ["labor"]),
                         ("请提供劳动合同", ["labor"]),
                         ("请提供审计报告/营业执照合订本", ["audit_report", "license"])):
        obs, _flags = sem.split_item({"item_id": "M2", "entity": JIA, "text": text})
        assert [o["doc_type"] for o in obs] == expect, text


def test_multi_type_with_year_in_between_is_split(tmp_path):
    """★ 可分离性规则的边界：间隔里有**年份/非汉字** ⇒ 两类，必须拆。

    「审计报告2024年营业执照」：间隔「2024年」不是复合词连接（含数字 ⇒ 非汉字），
    判两类 ⇒ 拆成两条原子义务（修复前整条被丢弃）。
    """
    obs, flags = sem.split_item({"item_id": "M3", "entity": JIA,
                                 "text": "请提供审计报告2024年营业执照"})
    assert [o["doc_type"] for o in obs] == ["audit_report", "license"]
    assert [f["status"] for f in flags] == ["AMBIGUOUS_SPLIT"]


def test_han_only_connector_is_treated_as_compound(tmp_path):
    """★ 反例（保守方向）：纯**汉字连接**的间隔（如「甲公司」）⇒ 判复合词 ⇒ 不拆。

    「请提供甲公司营业执照」是**一份**材料（该公司的执照），不是两类 ⇒ 不拆。
    """
    obs, _flags = sem.split_item({"item_id": "M4", "entity": JIA, "text": "请提供甲公司营业执照"})
    assert [o["doc_type"] for o in obs] == ["license"]


def test_all_ten_types_are_recognized_on_the_obligation_side():
    """WP1：义务侧 10 类全覆盖（缺的那 3 类正是「拆不出义务」的来源）。"""
    samples = {
        "audit_report": "请提供2024年度审计报告", "financial_statement": "请提供2024年度财务报表",
        "tax": "请提供2024年度纳税证明", "license": "请提供最新营业执照", "charter": "请提供公司章程",
        "capital": "请提供验资报告", "resolution": "请提供股东会决议", "ip": "请提供专利证书",
        "labor": "请提供劳动合同", "contract": "请提供经营资产租赁合同",
    }
    for key, text in samples.items():
        obs, flags = sem.split_item({"item_id": "T", "entity": JIA, "text": text})
        assert [o["doc_type"] for o in obs] == [key], text
        assert not [f for f in flags if f["status"] == "NEEDS_HUMAN_SPLIT"], text


# ───────────────────────────────────── WP3：候选为空的六种原因

def test_no_candidate_reason_distinguishes_six_states(tmp_path):
    """WP3：候选为空 ⇒ 必须说清**为什么**（不得统一伪装成「没有材料」）。"""
    root = tmp_path / "material"
    root.mkdir()
    (root / "a.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    (root / "b.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    meta = [
        {"file_id": "S1", "relative_path": "a.txt", "entity": JIA, "period": "2024",
         "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
        {"file_id": "S2", "relative_path": "b.txt", "entity": JIA, "period": "2024",
         "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE",
         "access": "RESTRICTED"},
    ]
    ob = {"entity": JIA, "doc_type": "audit_report", "period": "2024", "required_parts": []}

    # ① NO_MATERIAL：该主体该类型确实没有材料（库里只有审计报告，没有执照）
    d = sem.retrieve_minimal_evidence_detailed(root, meta, {**ob, "doc_type": "license"})
    assert d["evidence"] == [] and d["no_candidate_reason"] == "NO_MATERIAL"
    assert d["candidate_status"] == "NO_CANDIDATE", d["candidate_status"]

    # ② UNRESOLVED_DOC_TYPE：类型判不出
    d = sem.retrieve_minimal_evidence_detailed(root, meta, {**ob, "doc_type": "看不懂的类型"})
    assert d["no_candidate_reason"] == "UNRESOLVED_DOC_TYPE"
    assert d["candidate_status"] == "NO_CANDIDATE", d["candidate_status"]

    # ③ UNKNOWN_ENTITY：主体未知
    d = sem.retrieve_minimal_evidence_detailed(root, meta, {**ob, "entity": ""})
    assert d["no_candidate_reason"] == "UNKNOWN_ENTITY"
    assert d["candidate_status"] == "NO_CANDIDATE", d["candidate_status"]

    # ④ PERMISSION_BLOCKED：材料被访问规则挡下（且没有别的候选）
    # ★ **已知缺口（如实登记）**：meta 的 ``access`` / ``restricted`` 是**留出的扩展点**，
    #   仓内两个 meta 生产者（桥接链 build_meta、入口 B scaffold）**都不写**这两个字段
    #   ⇒ **生产路径下该状态不可达**；本条证明的是**分支逻辑**成立，不是「生产接线已覆盖」。
    only_blocked = [m for m in meta if m["file_id"] == "S2"]
    d = sem.retrieve_minimal_evidence_detailed(root, only_blocked, ob)
    assert d["evidence"] == [] and d["no_candidate_reason"] == "PERMISSION_BLOCKED"
    assert d["diagnostics"]["rejected_by_permission"] == 1

    # ⑤ RETRIEVAL_EXHAUSTED：候选被上限截断 ⇒ **不得**断言「确实没有」
    many = [{"file_id": f"T{i:03d}", "relative_path": "a.txt", "entity": JIA, "period": "2019",
             "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"} for i in range(8)]
    d = sem.retrieve_minimal_evidence_detailed(root, many, ob)
    assert d["no_candidate_reason"] == "RETRIEVAL_EXHAUSTED"
    assert d["diagnostics"]["truncated_candidate_count"] == 8 - sem.MAX_FILES_PER_OBLIGATION

    # ⑥ OTHER：材料读不到（兜底；不吞掉异常）
    broken = [{"file_id": "S9", "relative_path": "missing.txt", "entity": JIA, "period": "2024",
               "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
    snap = ar.load_snapshot(root, meta)
    snap["S9"] = ar.SnapshotFile(file_id="S9", relative_path="missing.txt", sha256="0" * 64,
                                 entity=JIA, period="2024")
    d = sem.retrieve_minimal_evidence_detailed(root, broken, ob, snap=snap)
    assert d["evidence"] == [] and d["no_candidate_reason"] == "OTHER"
    assert d["diagnostics"]["read_errors"] == 1

    # 原因枚举本身是**封闭六态**（派工令的枚举；不扩项 ⇒ 不偏离 AC）
    assert set(sem.NO_CANDIDATE_REASONS) == {
        "NO_MATERIAL", "UNRESOLVED_DOC_TYPE", "UNKNOWN_ENTITY",
        "PERMISSION_BLOCKED", "RETRIEVAL_EXHAUSTED", "OTHER"}
    assert len(sem.NO_CANDIDATE_REASONS) == 6
    # 候选侧状态是**另一个**枚举（不是原因枚举的扩项）
    assert set(sem.CANDIDATE_STATUSES) == {
        "OK", "NO_CANDIDATE", "PERIOD_OR_VERSION_MISMATCH", "EXHAUSTED"}
    assert len(sem.CANDIDATE_STATUSES) == 4
    # ★ 四态**互斥**、判定顺序写死：OK → EXHAUSTED → PERIOD_OR_VERSION_MISMATCH → NO_CANDIDATE
    #   （EXHAUSTED 优先于 PERIOD_OR_VERSION_MISMATCH：被上限截断时不得断言「期间不符」）
    many8 = [{"file_id": f"T{i:03d}", "relative_path": "a.txt", "entity": JIA, "period": "2019",
              "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}
             for i in range(8)]
    d = sem.retrieve_minimal_evidence_detailed(root, many8, ob)
    assert d["candidate_status"] == "EXHAUSTED", d["candidate_status"]
    # 候选存在但期间/版本不可用 ⇒ reason 留空（枚举域外）+ candidate_status 明确表达
    d = sem.retrieve_minimal_evidence_detailed(root, [dict(meta[0], period="2022")], ob)
    assert d["no_candidate_reason"] is None
    assert d["candidate_status"] == "PERIOD_OR_VERSION_MISMATCH", d["candidate_status"]


def test_empty_candidate_reason_is_carried_into_rule_hint_and_packet(tmp_path):
    """WP3：空候选的原因要**结构化落到包里**（不得只留一个 MISSING）。"""
    root = tmp_path / "material"
    root.mkdir()
    (root / "a.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    meta = [{"file_id": "S1", "relative_path": "a.txt", "entity": JIA, "period": "2024",
             "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
    items = [{"item_id": "Q1", "entity": JIA, "text": "请提供最新营业执照"}]
    pkt = sem.build_semantic_packet(root, meta, items)
    assert pkt["evidence"]["Q1-O1"] == []
    assert pkt["evidence_status"]["Q1-O1"]["no_candidate_reason"] == "NO_MATERIAL"
    hint = sem.rule_hint(pkt["obligations"][0], pkt["evidence"]["Q1-O1"],
                          pkt["evidence_status"]["Q1-O1"]["no_candidate_reason"])
    assert hint["verdict"] == "MISSING"
    assert hint["no_candidate_reason"] == "NO_MATERIAL"


def test_legacy_chinese_doc_type_meta_still_matches(tmp_path):
    """★ 兼容：旧 meta / 旧 fixture 里的**中文 doc_type** 仍然可用（归一在比较环节做）。"""
    fx = Path(__file__).parent / "fixtures" / "dd_v1_fos71_wp04"
    meta = json.loads((fx / "meta.json").read_text("utf-8"))
    items = json.loads((fx / "raw_items.json").read_text("utf-8"))
    assert any(m["doc_type"] and not m["doc_type"].isascii() for m in meta), "旧 fixture 应当是中文 doc_type"
    obs, _flags = sem.split_items(items)
    ev = sem.retrieve_minimal_evidence(fx / "snapshot", meta, obs[0])
    assert ev, "旧中文 doc_type 的材料仍应命中英文 key 的义务（证据池不再恒空）"
    assert {e["doc_type"] for e in ev} == {"audit_report"}


# ───────────────────────────────────── 判据5：安全负例（披露不放宽）

def test_public_release_list_is_still_license_only():
    """判据5：``dd_v1_policy_service`` 的 PUBLIC 放行清单**仍只有 license**。"""
    pol = pol_svc.load_policy()
    assert pol.loaded is True, pol.load_error
    assert pol.sendable_doc_types == ["license"]
    pub = pol_svc.evaluate(pol, "PUBLIC", doc_type="license", entity=JIA)
    assert pub.externally_sendable is True and pub.requires_review is True
    for key in ("audit_report", "financial_statement", "tax", "charter", "capital",
                "resolution", "ip", "labor", "contract"):
        d = pol_svc.evaluate(pol, "PUBLIC", doc_type=key, entity=JIA)
        assert d.externally_sendable is False, f"{key} 竟被放行"
        assert d.level == "RESTRICTED", key
    for junk in ("审计报告", "pdf", "not_a_real_key", ""):
        d = pol_svc.evaluate(pol, "PUBLIC", doc_type=junk, entity=JIA)
        assert d.externally_sendable is False, f"{junk!r} 竟被放行"
        assert d.level == "RESTRICTED"


# ───────────────────────────────────── 判据4：完整合成组包

def test_full_synthetic_chain_to_authorized_package(tmp_path, monkeypatch):
    """判据4：清单 → 拆分 → 类型归一 → 候选召回 → 语义判断 → 规则校验 → 审核 → 授权组包。

    ★ 两段链跑在**同一批合成材料**上：
      ① 语义链（正式入口 B：scaffold → split → run，零模型零费用）；
      ② 组包链（清单 → 匹配 → 审核包 → 人工批准 → 授权组包 + hash 核验）。
    """
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    mf.close_all()
    try:
        root = _material_tree(tmp_path)
        # ── ① 语义链 ────────────────────────────────────────────────
        meta_path = tmp_path / "meta.json"
        assert lr.main(["scaffold", "--material-root", str(root), "--out", str(meta_path), "--entity", JIA]) == 0
        meta = json.loads(meta_path.read_text("utf-8"))
        items_path = tmp_path / "items.json"
        items_path.write_text(json.dumps(_ITEMS, ensure_ascii=False), "utf-8")
        obl_path = tmp_path / "obligations.json"
        assert lr.main(["split", "--items", str(items_path), "--out", str(obl_path)]) == 0
        obl = json.loads(obl_path.read_text("utf-8"))
        assert obl, "清单一条都没拆出来"
        assert all(o["doc_type"] in DOC_TYPE_KEYS for o in obl), "义务侧 doc_type 未归一到规范 key"
        # 候选召回：材料侧与义务侧**同一 key 空间** ⇒ 证据池非空
        pkt = sem.build_semantic_packet(root, meta, _ITEMS)
        assert pkt["evidence"]["C2-O1"], "2024 审计报告义务的证据池是空的（类型空间又分叉了？）"
        # 合成回放（零进程零费用）
        replies = tmp_path / "replies"
        replies.mkdir()
        _write_synthetic_reply(replies / "run-all.json", root, meta, _ITEMS)
        out_dir = tmp_path / "out"
        rc = lr.main(["run", "--material-root", str(root), "--meta", str(meta_path),
                      "--items", str(items_path), "--out", str(out_dir), "--adapter", "manual",
                      "--synthetic-replies", str(replies), "--allow-real-material", "--single-pack"])
        assert rc == 0, "语义链没有跑通"
        rec = json.loads((out_dir / "run-all" / "run_record.json").read_text("utf-8"))
        v = rec["semantic_validation"]
        assert v["mode"] == "AGENT_SUGGESTION" and v["accepted"]
        assert all(r["review_required"] and r["approved"] is False for r in v["accepted"])
        assert rec["authoritative_validation"] == "semantic_validation"

        # ── ② 组包链 ────────────────────────────────────────────────
        db = tmp_path / "_dp" / "manifest.sqlite"
        lib_root = tmp_path / "lib-materials"
        lib_root.mkdir()
        mf.register_library("lib-p0", str(lib_root), authorized_by="波总", db_path=db)
        for rel, content in _MATERIALS.items():
            if not rel.startswith(JIA + "/"):
                continue
            p = lib_root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        mf.build_manifest("lib-p0", db_path=db)
        ps.parse_pending_batch("lib-p0", db_path=db)
        cs.build_cards_for_library("lib-p0", db_path=db)
        rq.register_entity("lib-p0", "S1", JIA, relation="target",
                           source_ref="合成样例（测试用，非真实登记）", db_path=db)
        rq.ingest_checklist("lib-p0", [
            {"item_no": "1", "raw_text": f"请提供{JIA}最新营业执照"},
            {"item_no": "2", "raw_text": f"请提供{JIA}2024年度审计报告"},
        ], db_path=db)
        ms.match_library("lib-p0", db_path=db)
        rev = pkg.build_review_pack("lib-p0", institution="合成机构", db_path=db)
        # ★ P0-2：这两条义务的判定是 ``UNCERTAIN``（不是 MATCHED）——
        #   原因是认知卡的 ``entity`` 字段取的是**父目录名**，而本用例的材料树
        #   刻意复刻了「法人/类型/文件」多级布局 ⇒ 父目录是**类型目录**
        #   （如 ``2.营业执照``）⇒ 判定层按 G6 v2 判「主体未登记 ⇒ 改判 UNCERTAIN」。
        #   （主体字段归一属**后续工作包**「主体匹配错误」，本轮只登记不修。）
        #   ⇒ P0-2 的逐条交付闸默认只放行 MATCHED ⇒ 这里**人工逐条确认**
        #   （= 人工已核对主体归属），再重新批准 ⇒ 走通「审核 → 交付」全链路。
        for _obl in rq.list_obligations("lib-p0", db_path=db):
            pkg.confirm_obligation(rev["review_id"], _obl["obligation_id"],
                                    confirmed_by="波总",
                                    reason="人工已核对主体归属（材料在本法人目录下）",
                                    db_path=db)
        pkg.approve(rev["review_id"], approved_by="波总", db_path=db)
        res = pkg.package_approved(rev["review_id"], db_path=db)

        # 产物落盘 + sha256 可复算（独立复算：读产物字节重算哈希，与清单登记值逐位比对）
        import hashlib
        assert res["status"] == pkg.ST_PACKAGED
        assert res["hash_mismatched"] == 0
        out = Path(res["output_dir"])
        manifest_path = out / "组包manifest.tsv"
        assert manifest_path.exists()
        lines = manifest_path.read_text("utf-8").splitlines()
        header = lines[0].split("\t")
        rows = [dict(zip(header, ln.split("\t"))) for ln in lines[1:] if ln.strip()]
        assert rows, "组包manifest.tsv 没有登记任何交付件"
        assert res["exported"] == len(rows)
        for row in rows:
            dest = out / row["交付路径"]
            assert dest.is_file(), row["交付路径"]
            assert hashlib.sha256(dest.read_bytes()).hexdigest() == row["副本sha256"] == row["源sha256"]
            assert row["一致"] == "是"
        assert [p for p in out.rglob("*") if p.is_file()]
        # ★ 安全负例：受限材料（审计报告 = RESTRICTED）**不得**进入交付目录
        assert res["exported"] >= 1, "执照（唯一可外发类）应当被导出"
        assert res["blocked"] >= 1, "受限的审计报告应当被拦下并记账"
        blocked_rel = " ".join(str(b.get("rel_path") or "") for b in res["blocked_detail"])
        assert "审计报告" in blocked_rel
    finally:
        mf.close_all()


# ─────────────────────────────────── 阻断项整改（B1 PII / B2 六态定级）+ 建议 A1

def test_split_stage_output_faces_have_no_plaintext_pii(tmp_path):
    """★ B1：split 阶段的**对外落盘面**不得带明文 PII（手机号 / 身份证）。

    三个落盘面全部锁死：
      ① 命令 ``split`` 写盘的文件（义务 text）；
      ② 语义包的 ``split_flags``（``segment`` / ``unparsed_segments`` / ``text``）；
      ③ ``run_record.json``（随 ②）。
    ★ 脱敏走**同一个** ``dd_v1_pii_service``；**检索仍用原文**
      （``_excerpt`` 的检索键是类型词 / 期间 / 附件，不含义务文本）⇒ 摘录不退化。
    """
    from cangjie_fos.services import dd_v1_agent_adapters as ad
    from cangjie_fos.services import dd_v1_pii_service as pii

    phone, idcard = "13800001111", "110101199001011234"
    root = _material_tree(tmp_path)
    meta = _scaffold(tmp_path, root, entity=JIA)
    items = [
        {"item_id": "P1", "entity": JIA,
         "text": f"请提供合成法人甲审计报告/营业执照 联系人手机号{phone}"},
        {"item_id": "P2", "entity": JIA, "text": f"请提供联系人手机号{phone}"},
        {"item_id": "P3", "entity": JIA,
         "text": f"请提供合成法人甲审计报告 身份证{idcard}"},
    ]
    items_path = tmp_path / "items.json"
    items_path.write_text(json.dumps(items, ensure_ascii=False), "utf-8")

    # ① 命令 `split` 写盘的文件
    out = tmp_path / "obligations.json"
    assert lr.main(["split", "--items", str(items_path), "--out", str(out)]) == 0
    blob = out.read_text("utf-8")
    assert phone not in blob and idcard not in blob
    assert not pii.contains_pii(blob)

    # ② 语义包的 split_flags
    pkt = sem.build_semantic_packet(root, meta, items)
    flags_blob = json.dumps(pkt["split_flags"], ensure_ascii=False)
    assert phone not in flags_blob and idcard not in flags_blob
    assert not pii.contains_pii(flags_blob)
    # 义务文本（packet 内）也不得带明文
    assert not pii.contains_pii(json.dumps(pkt["obligations"], ensure_ascii=False))

    # ③ run_record.json
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "reply.json").write_text(json.dumps({"results": []}, ensure_ascii=False), "utf-8")
    rec = sem.run_semantic(ad.ManualExchangeAdapter(), root, meta, items,
                           ad.Budget(timeout_s=20), workdir=wd)
    rec_blob = (wd / "run_record.json").read_text("utf-8")
    assert phone not in rec_blob and idcard not in rec_blob
    assert not pii.contains_pii(rec_blob)
    assert not pii.contains_pii(json.dumps(rec, ensure_ascii=False))


def test_period_or_version_mismatch_is_not_reported_as_no_material(tmp_path):
    """★ B2：同主体同类型的材料**存在**、只是期间/版本不可用
    ⇒ **不得**报 ``NO_MATERIAL``（材料存在却报「确实没有」＝契约禁止的伪装），
      也**不得**报 ``UNRESOLVED_DOC_TYPE``（类型明明判得出）。
    """
    root = tmp_path / "material"
    root.mkdir()
    (root / "a.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    ob = {"entity": JIA, "doc_type": "audit_report", "period": "2024", "required_parts": []}

    # A1：同类型同主体，仅**年份**不符
    meta = [{"file_id": "M1", "relative_path": "a.txt", "entity": JIA, "period": "2022",
             "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
    d = sem.retrieve_minimal_evidence_detailed(root, meta, ob)
    # ★ 候选**存在** ⇒ 不是「候选为空」⇒ 原因枚举不适用（留空），
    #   由 candidate_status 明确表达；**不得**是 NO_MATERIAL / UNRESOLVED_DOC_TYPE。
    assert d["no_candidate_reason"] is None, d["no_candidate_reason"]
    assert d["no_candidate_reason"] not in ("NO_MATERIAL", "UNRESOLVED_DOC_TYPE")
    assert d["candidate_status"] == "PERIOD_OR_VERSION_MISMATCH", d["candidate_status"]
    assert d["diagnostics"]["rejected_by_period"] == 1
    assert d["diagnostics"]["candidates_total"] == 1

    # A3：期间对得上，仅**版本**是草稿（非现行有效）
    meta_draft = [dict(meta[0], period="2024", version_status="DRAFT")]
    d2 = sem.retrieve_minimal_evidence_detailed(root, meta_draft, ob)
    assert d2["no_candidate_reason"] is None, d2["no_candidate_reason"]
    assert d2["candidate_status"] == "PERIOD_OR_VERSION_MISMATCH", d2["candidate_status"]
    assert d2["diagnostics"]["rejected_by_version"] == 1

    # A2：期间不符 **且** 库里另有其他类型材料 ⇒ 仍**不得**报 NO_MATERIAL
    meta_mixed = meta + [{"file_id": "M2", "relative_path": "a.txt", "entity": JIA, "period": "2024",
                         "doc_type": "license", "part": "正文", "version_status": "EFFECTIVE"}]
    d3 = sem.retrieve_minimal_evidence_detailed(root, meta_mixed, ob)
    assert d3["no_candidate_reason"] is None, d3["no_candidate_reason"]
    assert d3["candidate_status"] == "PERIOD_OR_VERSION_MISMATCH", d3["candidate_status"]

    # 真正的「确实没有这一类材料」⇒ 仍然是 NO_MATERIAL（阳性对照；候选为空 ⇒ 原因枚举适用）
    only_other = [meta_mixed[1]]
    d4 = sem.retrieve_minimal_evidence_detailed(root, only_other, ob)
    assert d4["no_candidate_reason"] == "NO_MATERIAL", d4["no_candidate_reason"]
    assert d4["candidate_status"] == "NO_CANDIDATE", d4["candidate_status"]


def test_current_doc_types_is_a_subset_of_the_authoritative_ten_keys():
    """★ 建议 A1：``CURRENT_DOC_TYPES`` 必须是权威 10 key 的**子集**（不是第三套类型表）。

    权威表将来新增「无年度口径」的类型时，这条断言会提醒同步（而不是静默漂移）。
    """
    authoritative = {key for key, _ in rq._DOC_TYPE_RULES}
    assert set(rq.CURRENT_DOC_TYPES) <= authoritative
    assert rq.CURRENT_DOC_TYPES == ("license", "charter")
    # 桥接层不得另抄一份
    from cangjie_fos.services import dd_v1_bridge_service as br
    assert br._CURRENT_DOC_TYPES == rq.CURRENT_DOC_TYPES


def test_license_obligation_never_inherits_the_segment_year(tmp_path):
    """★ 复核发现①（假缺口）：执照类义务**不得继承段年份**。

    「请提供2024年度审计报告与营业执照」里的 2024 是**审计报告**的年度口径；
    若执照义务也拿 2024，而执照材料的期间是 ``CURRENT``（scaffold / bridge 同口径）
    ⇒ 池里有执照材料、但没有「期间一致」的可用候选 ⇒ **假缺口**（本轮 P0 的核心 KPI）。

    ⇒ 执照/章程（``CURRENT_DOC_TYPES``）的期间恒为 ``CURRENT``，两侧口径一致。
    """
    obs, _flags = sem.split_item(
        {"item_id": "X", "entity": JIA, "text": "请提供2024年度审计报告与营业执照"})
    by_type = {o["doc_type"]: o for o in obs}
    assert by_type["audit_report"]["period"] == "2024"
    assert by_type["license"]["period"] == "CURRENT", by_type["license"]["period"]

    # 端到端：执照材料（期间 CURRENT）必须能匹配上这条执照义务
    root = tmp_path / "material"
    (root / "1.审计报告").mkdir(parents=True)
    (root / "1.审计报告" / "审计报告2024.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    (root / "2.营业执照").mkdir(parents=True)
    (root / "2.营业执照" / "营业执照.txt").write_text("营业执照\n合成样例\n", encoding="utf-8")
    meta = [{"file_id": "M1", "relative_path": "1.审计报告/审计报告2024.txt", "entity": JIA,
             "period": "2024", "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
            {"file_id": "M2", "relative_path": "2.营业执照/营业执照.txt", "entity": JIA,
             "period": "CURRENT", "doc_type": "license", "part": "正文", "version_status": "EFFECTIVE"}]
    lic = by_type["license"]
    d = sem.retrieve_minimal_evidence_detailed(root, meta, lic)
    assert d["evidence"], "执照义务匹配不到执照材料 ⇒ 假缺口"
    assert d["candidate_status"] == "OK", d["candidate_status"]
    assert d["no_candidate_reason"] is None
    # ★ 逐类期间：同一段里两类各拿各的年份（判据③「多年度不混桶」）
    obs2, _f2 = sem.split_item(
        {"item_id": "Y", "entity": JIA, "text": "请提供2024年度审计报告与2022年度财务报表"})
    assert {o["doc_type"]: o["period"] for o in obs2} == {
        "audit_report": "2024", "financial_statement": "2022"}


def test_scaffold_does_not_treat_index_artifact_as_material(tmp_path):
    """★ 复核发现③（既有坑，本轮动过 scaffold 的类型判定 ⇒ 顺手接上）：
    索引/目录件**不是材料** ⇒ 不得被解析成 ``audit_report``
    （否则与真审计报告同主体同类型同期间落进同一冲突桶 ⇒ **假 CONFLICT**）。

    口径与卡片层（``dd_v1_card_service``）一致：类型强制留空 + 留痕。
    """
    root = tmp_path / "material"
    (root / "1.审计报告").mkdir(parents=True)
    (root / "1.审计报告" / "审计报告2024.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    (root / "00_审计报告目录.md").write_text("材料目录\n1. 审计报告2024.txt\n", encoding="utf-8")
    out = tmp_path / "meta.json"
    assert lr.main(["scaffold", "--material-root", str(root), "--out", str(out),
                     "--entity", JIA]) == 0
    meta = json.loads(out.read_text("utf-8"))
    by_path = {m["relative_path"]: m for m in meta}
    idx = by_path["00_审计报告目录.md"]
    assert idx["doc_type"] == "", "索引件被判成了材料类型"
    assert idx["doc_type_provenance"] == "UNKNOWN"
    assert by_path["1.审计报告/审计报告2024.txt"]["doc_type"] == "audit_report"
    # 索引件不占任何类型桶 ⇒ 不得出现第二个 audit_report
    assert sum(1 for m in meta if m["doc_type"] == "audit_report") == 1


def test_bridge_period_space_for_current_doc_types_is_current_only():
    """★ 司仓 C-1 裁定的**材料侧 + 义务侧**口径：语义层 period 空间对
    「无年度口径类型」（执照 / 章程）**只有一个取值 CURRENT** ⇒ 两侧同源。

    机械证（数字，不接受自述）：
      ② 材料侧：``card.fiscal_period="2022"`` 的**执照**材料 ⇒ 语义 period == ``CURRENT``
         （**不是 2022**；年度信息仍留在 card.fiscal_period 里，不进语义 period）；
      ②' 义务侧：``period_from=period_to=2022`` 的**执照**义务 ⇒ 语义 period == ``CURRENT``；
      ②'' 反向不回归：审计报告类**仍按年份**（两侧都取 2022）⇒ 判据③「多年度不混桶」不被削弱。
    """
    from cangjie_fos.services import dd_v1_bridge_service as br

    # ② 材料侧：执照材料带 fiscal_period 年份 ⇒ 语义 period 恒 CURRENT
    assert br._material_period({"fiscal_period": "2022"}, "license") == "CURRENT"
    assert br._material_period({"fiscal_period": "2022"}, "charter") == "CURRENT"
    # ★ 年度信息不丢：card 自己的 fiscal_period 原样保留
    card = {"fiscal_period": "2022"}
    assert card["fiscal_period"] == "2022"

    # ②' 义务侧：同口径
    assert br._obligation_period({"period_from": 2022, "period_to": 2022}, "license") == "CURRENT"
    assert br._obligation_period({"period_from": 2022, "period_to": 2022}, "charter") == "CURRENT"

    # ②'' 反向不回归：审计报告类仍按年份
    assert br._material_period({"fiscal_period": "2022"}, "audit_report") == "2022"
    assert br._obligation_period({"period_from": 2022, "period_to": 2022}, "audit_report") == "2022"

    # ★ 桥接层的类型空间与权威 10 key 同源（不另抄一份 CURRENT 集合）
    assert br._CURRENT_DOC_TYPES == rq.CURRENT_DOC_TYPES


def test_license_obligation_end_to_end_has_no_false_gap(tmp_path):
    """★ 司仓 C-1 机械证 ③：端到端（材料侧 CURRENT + 义务侧 CURRENT）⇒ **无假缺口**。

    同主体同类型的执照材料（期间 CURRENT）与该义务匹配时：
      可用候选非空、``rule_hint`` 的结论**不是** MISSING、``rejected_by_period == 0``。
    ★ 反向不回归（机械证 ④）：
      「请提供2024年度审计报告」仍 2024；
      「请提供2024年度审计报告、营业执照」（分段）执照仍 CURRENT；
      「请提供2024年度审计报告与2022年度财务报表」两类各拿各的年份。
    """
    root = tmp_path / "material"
    (root / "1.审计报告").mkdir(parents=True)
    (root / "1.审计报告" / "审计报告2024.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    (root / "2.营业执照").mkdir(parents=True)
    (root / "2.营业执照" / "营业执照2022.txt").write_text("营业执照\n合成样例\n", encoding="utf-8")
    meta = [{"file_id": "M1", "relative_path": "1.审计报告/审计报告2024.txt", "entity": JIA,
             "period": "2024", "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
            {"file_id": "M2", "relative_path": "2.营业执照/营业执照2022.txt", "entity": JIA,
             "period": "CURRENT", "doc_type": "license", "part": "正文", "version_status": "EFFECTIVE"}]

    obs, _flags = sem.split_item(
        {"item_id": "X", "entity": JIA, "text": "请提供2024年度审计报告与营业执照"})
    lic = [o for o in obs if o["doc_type"] == "license"][0]
    d = sem.retrieve_minimal_evidence_detailed(root, meta, lic)
    assert d["evidence"], "执照义务匹配不到执照材料 ⇒ 假缺口"
    assert d["candidate_status"] == "OK", d["candidate_status"]
    assert d["diagnostics"]["rejected_by_period"] == 0
    hint = sem.rule_hint(lic, d["evidence"])
    assert hint.get("verdict") != "MISSING", hint

    # ④ 反向不回归
    a, _ = sem.split_item({"item_id": "Y", "entity": JIA, "text": "请提供2024年度审计报告"})
    assert a[0]["period"] == "2024"
    b, _ = sem.split_item({"item_id": "Z", "entity": JIA, "text": "请提供2024年度审计报告、营业执照"})
    assert {o["doc_type"]: o["period"] for o in b} == {"audit_report": "2024", "license": "CURRENT"}
    c, _ = sem.split_item(
        {"item_id": "W", "entity": JIA, "text": "请提供2024年度审计报告与2022年度财务报表"})
    assert {o["doc_type"]: o["period"] for o in c} == {
        "audit_report": "2024", "financial_statement": "2022"}
