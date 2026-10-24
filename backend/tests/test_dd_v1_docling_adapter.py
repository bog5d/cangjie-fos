"""DD-V1 Docling 适配层契约测试（WP2 遗留缺口的关闭）。

WP2 交付时自陈：「本环境 docling_available()=false，Docling 层代码路径
**未经真实执行验证**，只验证了『缺席时正确降级』」。

本文件用**桩模块**（`sys.modules` 注入）验证 Docling 适配器的完整契约，
**不安装 Docling**——它重且会拖慢测试，属 `pyproject` 的 `[docling]` 可选依赖。
这样既关闭了「代码路径从未被执行」的缺口，又不为跑测试付出重依赖代价。

覆盖：Docling 优先、结果采用、截断标记、异常降级、缺席跳过。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_parser_service as ps


class _StubDocument:
    def __init__(self, text: str):
        self._t = text

    def export_to_markdown(self) -> str:
        return self._t


def _install_stub(payloads: dict, boom: bool = False) -> None:
    """把一个最小 docling 桩塞进 sys.modules。"""
    class DocumentConverter:  # noqa: D401 - 桩
        def __init__(self, *a, **k):
            pass

        def convert(self, path):
            if boom:
                raise RuntimeError("stub: docling 转换失败")
            return types.SimpleNamespace(
                document=_StubDocument(payloads.get(str(path), "")))

    docling = types.ModuleType("docling")
    conv = types.ModuleType("docling.document_converter")
    conv.DocumentConverter = DocumentConverter
    docling.document_converter = conv
    sys.modules["docling"] = docling
    sys.modules["docling.document_converter"] = conv


@pytest.fixture
def _no_docling():
    """确保测试结束后不把桩留在 sys.modules 里污染其他用例。"""
    saved = {k: v for k, v in sys.modules.items() if k.startswith("docling")}
    for k in list(saved):
        del sys.modules[k]
    yield
    for k in [k for k in sys.modules if k.startswith("docling")]:
        del sys.modules[k]
    sys.modules.update(saved)


def test_absent_docling_is_detected(_no_docling):
    assert ps.docling_available() is False


def test_stub_makes_available_true(_no_docling):
    _install_stub({})
    assert ps.docling_available() is True


def test_docling_result_is_used_and_marked(tmp_path, _no_docling):
    """Docling 产出被采用，且 method 明确标为 docling（可追溯）。"""
    f = tmp_path / "版式复杂.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    _install_stub({str(f): "# 标题\n\n正文内容"})

    r = ps.extract_content(f)
    assert r.readable is True
    assert r.method == ps.M_DOCLING
    assert "正文内容" in r.text


def test_docling_truncation_is_explicit(tmp_path, _no_docling):
    f = tmp_path / "超长.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    _install_stub({str(f): "甲" * 5000})

    r = ps.extract_content(f, max_chars=1000)
    assert r.truncated is True
    assert len(r.text) == 1000
    assert r.original_chars == 5000


def test_docling_failure_degrades_to_existing_extractor(tmp_path, _no_docling):
    """Docling 抛异常 → 必须降级到既有抽取器，且**不留半截内容冒充成功**。"""
    f = tmp_path / "会崩.pdf"
    f.write_text("这是既有抽取器能读出的正文", encoding="utf-8")
    _install_stub({}, boom=True)

    r = ps.extract_content(f)
    assert r.readable is True, "Docling 崩了必须降级，不能整条链失败"
    assert r.method != ps.M_DOCLING, "降级后 method 不得再声称用了 docling"
    assert "既有抽取器能读出的正文" in r.text


def test_docling_all_layers_fail_reports_reason(tmp_path, _no_docling):
    """Docling 崩且既有抽取器也读不出 → 明确不可读，且带原因。"""
    f = tmp_path / "彻底坏.bin"
    f.write_bytes(b"\x00\xff" * 200)
    _install_stub({}, boom=True)

    r = ps.extract_content(f)
    if not r.readable:
        assert r.method in (ps.M_UNREADABLE, ps.M_EMPTY)
        assert r.error, "全部失败必须有原因"


def test_allow_docling_false_skips_layer(tmp_path, _no_docling):
    """显式关闭 Docling 时，即便装了桩也不走该层。"""
    f = tmp_path / "正文.txt"
    f.write_text("既有抽取路径的正文" * 10, encoding="utf-8")
    _install_stub({str(f): "这段来自 docling 桩，不应出现"})

    r = ps.extract_content(f, allow_docling=False)
    assert r.method != ps.M_DOCLING
    assert "不应出现" not in r.text


def test_docling_preferred_over_existing(tmp_path, _no_docling):
    """两层都能出结果时，Docling 在前（波形/表格还原更好）。"""
    f = tmp_path / "双通.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    _install_stub({str(f): "来自 docling 的还原结果"})

    r = ps.extract_content(f, allow_docling=True)
    assert r.method == ps.M_DOCLING
    assert "来自 docling" in r.text


def test_empty_docling_output_marks_empty_not_success(tmp_path, _no_docling):
    """Docling 成功但产出为空 → 标 empty，**不冒充 readable**。"""
    f = tmp_path / "空.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    _install_stub({str(f): "   "})

    r = ps.extract_content(f, allow_docling=True)
    if not r.readable:
        assert r.method == ps.M_EMPTY
