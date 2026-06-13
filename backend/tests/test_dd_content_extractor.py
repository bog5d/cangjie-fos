"""v1.17.0 内容层补盲 — 统一抽取（解密 + 文字层 + MarkItDown/OCR 兜底）测试。

依赖（msoffcrypto/pikepdf/markitdown）全部 mock，不需真实加密/扫描文件。
"""
from __future__ import annotations

from pathlib import Path

from cangjie_fos.services import dd_content_extractor as ce


def test_missing_file():
    text, readable, method = ce.extract_for_verify("/不存在/x.pdf")
    assert (text, readable, method) == ("", False, "missing")


def test_text_layer_hit(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("营业执照正文内容", encoding="utf-8")
    text, readable, method = ce.extract_for_verify(str(f))
    assert "营业执照" in text
    assert readable is True
    assert method == "text"


def test_decrypt_then_text(tmp_path, monkeypatch):
    """加密文件：用密码解密 → 临时明文 → 文字层抽取，method=decrypt+text。"""
    enc = tmp_path / "secret.docx"
    enc.write_bytes(b"ENCRYPTED")
    plain = tmp_path / "plain.docx"
    plain.write_text("解密后的正文", encoding="utf-8")

    monkeypatch.setattr(ce, "_try_decrypt", lambda p, pw: plain)
    monkeypatch.setattr(ce, "extract_full_text", lambda p, max_chars=6000: ("解密后的正文", True))

    text, readable, method = ce.extract_for_verify(str(enc), password="123")
    assert text == "解密后的正文"
    assert method == "decrypt+text"


def test_markitdown_fallback_when_text_empty(tmp_path, monkeypatch):
    """文字层空（扫描件/图片）→ MarkItDown 兜底，method=markitdown。"""
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF fake")
    monkeypatch.setattr(ce, "extract_full_text", lambda p, max_chars=6000: ("", False))
    monkeypatch.setattr(ce, "_try_markitdown", lambda p, mc: "OCR识别出的正文")

    text, readable, method = ce.extract_for_verify(str(f))
    assert text == "OCR识别出的正文"
    assert readable is True
    assert method == "markitdown"


def test_all_empty_unreadable(tmp_path, monkeypatch):
    f = tmp_path / "blank.pdf"
    f.write_bytes(b"%PDF")
    monkeypatch.setattr(ce, "extract_full_text", lambda p, max_chars=6000: ("", False))
    monkeypatch.setattr(ce, "_try_markitdown", lambda p, mc: "")
    text, readable, method = ce.extract_for_verify(str(f))
    assert (text, readable, method) == ("", False, "unreadable")


def test_decrypt_failure_falls_back(tmp_path, monkeypatch):
    """解密失败（密码错/非加密）→ _try_decrypt 返回 None → 走普通文字层抽取。"""
    f = tmp_path / "x.docx"
    f.write_text("普通内容", encoding="utf-8")
    monkeypatch.setattr(ce, "_try_decrypt", lambda p, pw: None)
    monkeypatch.setattr(ce, "extract_full_text", lambda p, max_chars=6000: ("普通内容", True))
    text, _r, method = ce.extract_for_verify(str(f), password="wrong")
    assert text == "普通内容"
    assert method == "text"  # 未解密成功 → 不带 decrypt 前缀


def test_markitdown_import_missing_safe(tmp_path, monkeypatch):
    """MarkItDown 依赖缺失/异常 → 返回空串，不抛（优雅降级）。"""
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF")
    def boom(*a, **k):
        raise ImportError("markitdown 未安装")
    monkeypatch.setattr(ce, "_build_markitdown", boom)
    assert ce._try_markitdown(Path(str(f)), 6000) == ""


# ── v1.18.0：视觉 OCR 开箱配置（复用百炼 DASHSCOPE_API_KEY）──

def _clear_vision_env(monkeypatch):
    for k in ("CANGJIE_VISION_BASE_URL", "CANGJIE_VISION_API_KEY",
              "CANGJIE_VISION_MODEL", "CANGJIE_OCR_DISABLED", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_vision_default_uses_dashscope(monkeypatch):
    """有 DASHSCOPE_API_KEY 即开箱：自动 qwen-vl-max + 百炼兼容端点。"""
    _clear_vision_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-ds")
    cfg = ce._resolve_vision()
    assert cfg is not None
    base, key, model = cfg
    assert "dashscope" in base and key == "sk-ds" and model == "qwen-vl-max"


def test_vision_explicit_override(monkeypatch):
    _clear_vision_env(monkeypatch)
    monkeypatch.setenv("CANGJIE_VISION_BASE_URL", "http://x/v1")
    monkeypatch.setenv("CANGJIE_VISION_API_KEY", "kk")
    monkeypatch.setenv("CANGJIE_VISION_MODEL", "my-vl")
    assert ce._resolve_vision() == ("http://x/v1", "kk", "my-vl")


def test_vision_model_override_on_dashscope(monkeypatch):
    _clear_vision_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-ds")
    monkeypatch.setenv("CANGJIE_VISION_MODEL", "qwen-vl-plus")
    assert ce._resolve_vision()[2] == "qwen-vl-plus"


def test_vision_disabled_switch(monkeypatch):
    """CANGJIE_OCR_DISABLED=1 → 关闭，省 API 成本。"""
    _clear_vision_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-ds")
    monkeypatch.setenv("CANGJIE_OCR_DISABLED", "1")
    assert ce._resolve_vision() is None


def test_vision_none_when_no_key(monkeypatch):
    _clear_vision_env(monkeypatch)
    assert ce._resolve_vision() is None
