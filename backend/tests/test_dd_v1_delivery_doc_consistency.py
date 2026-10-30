"""交付物口径一致性 —— **机器门禁报告**与**人读交付文档**必须说同一件事。

★ **为什么需要这条**：第 4 轮独立复核的 MINOR-1／NIT-2 抓到的正是
  「机器报告说 G6 PASS、交接包说 G6 不算 PASS」⇒ **两份产物互相打架**。
  当时只改了机器侧（amendment A7/A8），**人读侧没跟上** ⇒ 交付包内部仍自相矛盾。
  ⇒ 光修一次没用；**必须让"文档与机器读数不一致"变成机器可判的红**。

★ **判据钉的是性质，不是症状**：不检查「某一句话长什么样」，
  而检查**交付文档必须逐字复述机器门禁报告的当前读数**：

  1. `status=<机器读数>` 必须出现在交付文档里（不许出现相反的 `status=PASS`）；
  2. `failed_key_gates=<机器读数>` 必须出现（不许出现相反的 `failed_key_gates=[]`）；
  3. 文档声明的 `key_gates` 列表必须等于冻结规格里的 `key_gates`；
  4. 文档必须提到**当前**独立复核轮次；
  5. 文档引用的 `real_model_runs` 运行号必须**真实存在于**机器报告里；
  6. 独立复核结论（verdict）必须出现在交付文档里；
  7. 交接包 `SHA256SUMS` 自核必须真过；
  8. 门禁报告里的 `handoff_sha256_selfcheck` 必须与**当前**交接包文件逐位一致
     （★ A8 加了这个字段却**没人校验它** ⇒ 等于装饰品；本条让它有牙）。

★ 全程只读，不跑考试、不改任何文件。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SUITE = REPO / "docs" / "dd-v1-fos71" / "ddv1-auto-test-suite"
HANDOFF = SUITE / "handoff"
GATE_REPORT = REPO / ".audit" / "gate-runs" / "门禁报告.json"
GATE_SPEC = REPO / "backend" / "config" / "dd_v1_delivery_gate.v1.json"
REVIEWER_REPORT = REPO / ".audit" / "gate-runs" / "g6_reviewer.json"

#: 必须与机器门禁报告口径一致的交付文档（**人读侧**）。
DELIVERY_DOCS = [
    SUITE / "施工令交付物对照表.md",
    HANDOFF / "README.md",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def machine() -> dict:
    if not GATE_REPORT.is_file():
        pytest.skip(f"机器门禁报告不存在：{GATE_REPORT}")
    return _load_json(GATE_REPORT)


@pytest.fixture(scope="module")
def spec() -> dict:
    return _load_json(GATE_SPEC)


@pytest.fixture(scope="module")
def reviewer() -> dict | None:
    if not REVIEWER_REPORT.is_file():
        return None
    return _load_json(REVIEWER_REPORT)


def _key_gates_claim(doc: str) -> list[str] | None:
    """抽出文档里**明确以 key_gates 标注**的门禁列表。

    支持两种写法：``key_gates = [G1,G2,...]`` 与
    ``关键门槛（`key_gates`）＝ G1/G2/...``。
    ★ 只看 ``key_gates`` 关键字**之后**的片段 —— 避免把
      「G1—G5、G7、G8 PASS」这类**子集**陈述误当成 key_gates 声明。
    ★ 查找时排除 ``failed_key_gates``（它**包含** "key_gates" 子串，
      会把窗口截到错误的位置）。
    """
    for m in re.finditer(r"(?<![\w_])key_gates", doc):
        window = doc[m.start() : m.start() + 200]
        parsed = _parse_gate_list(window)
        if parsed is not None:
            return parsed
    return None


def _parse_gate_list(window: str) -> list[str] | None:
    """从一段文本里解析门禁列表（逗号式或斜杠式，容忍 markdown 粗体标记）。"""
    m = re.search(r"\[((?:G\d+\s*,\s*)*G\d+)\]", window)
    if m:
        return [g.strip() for g in m.group(1).split(",")]
    # 斜杠写法，**两侧都可能带 markdown 粗体标记**（例：`G1/G2/**G6**/G8`）。
    m = re.search(r"((?:G\d+)(?:[/／]\**G\d+\**)+)", window)
    if m:
        return [g.replace("*", "") for g in re.split(r"[/／]", m.group(1))]
    return None


# ── 1—6：交付文档必须复述机器读数 ───────────────────────────────────────

@pytest.mark.parametrize("doc_path", DELIVERY_DOCS, ids=lambda p: p.name)
def test_doc_states_machine_status_verbatim(doc_path: Path, machine: dict):
    if not doc_path.is_file():
        pytest.skip(f"交付文档不存在：{doc_path}")
    doc = doc_path.read_text(encoding="utf-8")
    status = str(machine.get("status") or "")
    assert status, "机器门禁报告没有 status 字段"

    assert f"status={status}" in doc, (
        f"{doc_path.name} 未逐字复述机器门禁的 status={status}；"
        "人读口径与机器口径不一致（这正是第 4 轮 MINOR-1／NIT-2 的形态）"
    )
    if status != "PASS":
        assert "status=PASS" not in doc, (
            f"{doc_path.name} 在机器读数 status={status} 时仍宣称 status=PASS"
        )


@pytest.mark.parametrize("doc_path", DELIVERY_DOCS, ids=lambda p: p.name)
def test_doc_states_failed_key_gates_verbatim(doc_path: Path, machine: dict):
    if not doc_path.is_file():
        pytest.skip(f"交付文档不存在：{doc_path}")
    doc = doc_path.read_text(encoding="utf-8")
    failed = machine.get("failed_key_gates") or []
    literal = f"failed_key_gates={json.dumps(list(failed), ensure_ascii=False)}"
    assert literal in doc, (
        f"{doc_path.name} 未逐字复述机器门禁的 {literal}；人读口径与机器口径不一致"
    )
    if failed:
        assert "failed_key_gates=[]" not in doc, (
            f"{doc_path.name} 在机器读数 failed_key_gates={failed} 时仍宣称 failed_key_gates=[]"
        )


@pytest.mark.parametrize("doc_path", DELIVERY_DOCS, ids=lambda p: p.name)
def test_doc_key_gates_claim_matches_frozen_spec(doc_path: Path, spec: dict):
    if not doc_path.is_file():
        pytest.skip(f"交付文档不存在：{doc_path}")
    doc = doc_path.read_text(encoding="utf-8")
    claimed = _key_gates_claim(doc)
    if claimed is None:
        pytest.skip(f"{doc_path.name} 未声明 key_gates（无从比对）")
    assert claimed == list(spec.get("key_gates") or []), (
        f"{doc_path.name} 声明的 key_gates={claimed} 与冻结规格 "
        f"{spec.get('key_gates')} 不一致"
    )


@pytest.mark.parametrize("doc_path", DELIVERY_DOCS, ids=lambda p: p.name)
def test_doc_mentions_current_reviewer_round(doc_path: Path, reviewer: dict | None):
    if reviewer is None:
        pytest.skip("没有独立复核报告")
    if not doc_path.is_file():
        pytest.skip(f"交付文档不存在：{doc_path}")
    doc = doc_path.read_text(encoding="utf-8")
    rnd = reviewer.get("round")
    if not isinstance(rnd, int):
        pytest.skip("复核报告没有轮次字段")
    assert f"第 {rnd} 轮" in doc, (
        f"{doc_path.name} 没有提到当前独立复核轮次（第 {rnd} 轮）⇒ 复核指针陈旧"
    )


@pytest.mark.parametrize("doc_path", DELIVERY_DOCS, ids=lambda p: p.name)
def test_doc_reviewer_verdict_matches_machine(doc_path: Path, machine: dict, reviewer: dict | None):
    if reviewer is None:
        pytest.skip("没有独立复核报告")
    if not doc_path.is_file():
        pytest.skip(f"交付文档不存在：{doc_path}")
    doc = doc_path.read_text(encoding="utf-8")
    verdict = str(reviewer.get("verdict") or "").upper()
    if not verdict:
        pytest.skip("复核报告没有 verdict")
    assert verdict in doc, (
        f"{doc_path.name} 没有复述独立复核结论 verdict={verdict}；"
        "机器判 G6 FAIL 与人读「不算 PASS」必须成对出现"
    )


@pytest.mark.parametrize("doc_path", DELIVERY_DOCS, ids=lambda p: p.name)
def test_doc_real_model_run_ids_exist_in_machine_report(doc_path: Path, machine: dict):
    if not doc_path.is_file():
        pytest.skip(f"交付文档不存在：{doc_path}")
    doc = doc_path.read_text(encoding="utf-8")
    g3_reason = str((machine.get("gates") or {}).get("G3", {}).get("reason") or "")
    for run_id in re.findall(r"real_model_runs=\['([^']+)'\]", doc):
        assert run_id in g3_reason, (
            f"{doc_path.name} 引用的 real_model_runs 运行号 {run_id} "
            "在机器门禁报告里不存在 ⇒ 文档引用的是**旧一轮**证据"
        )


# ── 7—8：交接包自身的完整性（★ A8 加了字段却没人校验 ⇒ 这里让它有牙） ──

def test_handoff_sha256sums_selfcheck_passes():
    sums = HANDOFF / "SHA256SUMS"
    if not sums.is_file():
        pytest.skip("交接包没有 SHA256SUMS")
    bad = []
    for line in sums.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        target = HANDOFF / name.strip()
        if not target.is_file():
            bad.append(f"{name}: 文件不存在")
        elif _sha256(target) != digest.strip():
            bad.append(f"{name}: 哈希不符")
    assert not bad, "交接包 SHA256SUMS 自核失败：" + "；".join(bad)


def test_gate_report_handoff_selfcheck_matches_current_files(machine: dict):
    """门禁报告里记录的交接包哈希必须与**当前**文件逐位一致。

    ★ A8 引入 ``handoff_sha256_selfcheck``，但**没有任何东西校验它**
      ⇒ 改了交接包文件后，这个字段会悄悄过期 ⇒ 证据自证失效。
    """
    snap = machine.get("handoff_sha256_selfcheck") or {}
    files = snap.get("files") or {}
    if not files:
        pytest.skip("门禁报告没有交接包自证快照")
    stale = []
    for name, digest in files.items():
        target = HANDOFF / name
        if not target.is_file():
            stale.append(f"{name}: 文件不存在")
        elif _sha256(target) != digest:
            stale.append(f"{name}: 报告 {digest[:12]} ≠ 实际 {_sha256(target)[:12]}")
    assert not stale, (
        "门禁报告的 handoff_sha256_selfcheck 与当前交接包不一致（证据自证失效）："
        + "；".join(stale)
    )
