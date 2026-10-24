"""内置默认配置生成器 tools/make_embedded.py 的逻辑测试。

真正的 _embedded.py 含密钥、gitignored、CI 里不存在，所以这里测的是
**生成器的模板逻辑**（base64 往返 + inject_defaults 只填补不覆盖），
不涉及任何真实令牌。
"""
from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

import pytest

_GEN_PATH = Path(__file__).resolve().parents[2] / "tools" / "make_embedded.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("make_embedded", _GEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_embedded_namespace(defaults_plain: dict[str, str]) -> dict:
    """用生成器模板产出 _embedded.py 源码并 exec，返回其命名空间。"""
    gen = _load_generator()
    b64 = {k: base64.b64encode(v.encode()).decode("ascii") for k, v in defaults_plain.items()}
    src = gen._TEMPLATE.format(defaults=b64)
    ns: dict = {}
    exec(compile(src, "<embedded_test>", "exec"), ns)  # noqa: S102
    return ns


def test_generator_file_is_committable_without_secret():
    """生成器脚本本身不得含任何真实令牌前缀。"""
    text = _GEN_PATH.read_text(encoding="utf-8")
    assert "github_pat_" not in text
    assert "ghp_" not in text


def test_inject_fills_empty_env(monkeypatch):
    monkeypatch.delenv("COACH_DATA_GITHUB_TOKEN", raising=False)
    ns = _build_embedded_namespace({"COACH_DATA_GITHUB_TOKEN": "github_pat_FAKE123"})
    ns["inject_defaults"]()
    import os
    assert os.environ["COACH_DATA_GITHUB_TOKEN"] == "github_pat_FAKE123"


def test_inject_does_not_override_user_value(monkeypatch):
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "USER_OWN")
    ns = _build_embedded_namespace({"COACH_DATA_GITHUB_TOKEN": "github_pat_FAKE123"})
    ns["inject_defaults"]()
    import os
    assert os.environ["COACH_DATA_GITHUB_TOKEN"] == "USER_OWN"


def test_inject_ignores_blank_env(monkeypatch):
    """环境变量存在但为空串 → 视为未填，应被默认值填补。"""
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "   ")
    ns = _build_embedded_namespace({"COACH_DATA_GITHUB_TOKEN": "github_pat_FAKE123"})
    ns["inject_defaults"]()
    import os
    assert os.environ["COACH_DATA_GITHUB_TOKEN"] == "github_pat_FAKE123"


def test_generator_whitelist_covers_sync_keys():
    """同步必需的键必须在可烤入白名单里。"""
    gen = _load_generator()
    for key in ("COACH_DATA_GITHUB_TOKEN", "COACH_DATA_GITHUB_REPO", "COACH_DATA_TENANT_ID"):
        assert key in gen._EMBEDDABLE_KEYS
