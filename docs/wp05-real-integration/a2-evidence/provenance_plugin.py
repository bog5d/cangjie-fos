"""pytest 插件：session 起点打印**被测代码到底来自哪棵源码树**（A2 版）。

## 与 A1 版的差别（为什么不复用 A1 的插件）

A1 版的标记是 `主体未登记，无法判定是否同一主体` —— 那个字符串**在 A1 就已经存在**，
A2 没有改动它 ⇒ 用它做 A2 的判别标记是**无效的**（两侧都会 True，测不出差异）。

A2 专属标记：`cangjie_fos.services.dd_v1_entity_service.register_entity_alias`。
这个模块/函数**是 A2 新增的**（G-A2-8 别名归一），A1 与 master 都**不存在**
⇒ 判别力是单向可证的：A2 侧必须 True，A1/master 侧必须 False。

## 为什么仍然需要当场打印

FOS 仓 `backend/pyproject.toml` 有 `pythonpath = ["src"]`（相对 rootdir 且**前置**），
venv 又是 editable install（`.pth` 指向本 worktree 的 `backend/src`）。
⇒ 裸 python 与 pytest 解析到的源码树**可能不同**，"跑的是哪份代码"**不能靠推断**。

用法：

```bash
cd <被测 backend 目录>
PYTHONPATH=<a2-evidence 目录> \\
  env -u ALL_PROXY ... .venv/bin/python -m pytest -p provenance_plugin \\
  tests/ --ignore=tests/test_doctor_script.py -q --junit-xml=<xml>
```

输出里会出现：

    PROVENANCE: cangjie_fos = /abs/path/to/src/cangjie_fos/__init__.py
    PROVENANCE: has_A2_marker(dd_v1_entity_service.register_entity_alias) = True
"""
from __future__ import annotations


def pytest_sessionstart(session) -> None:
    import os
    import sys

    try:
        import cangjie_fos

        mod = cangjie_fos.__file__
    except Exception as exc:  # noqa: BLE001
        mod = f"<import failed: {type(exc).__name__}: {exc}>"
    print("PROVENANCE: cangjie_fos =", mod)
    print("PROVENANCE: cwd =", os.getcwd())
    rootdir = getattr(getattr(session, "config", None), "rootdir", None)
    print("PROVENANCE: rootdir =", str(rootdir))
    print("PROVENANCE: sys.path[0:4] =", sys.path[0:4])

    # A2 专属标记：别名归一服务只在 A2 存在
    try:
        import importlib

        importlib.import_module("cangjie_fos.services.dd_v1_entity_service")
        from cangjie_fos.services import dd_v1_entity_service as es

        has_a2 = hasattr(es, "register_entity_alias") and hasattr(es, "match_entity")
        print("PROVENANCE: has_A2_marker(dd_v1_entity_service.register_entity_alias) =", has_a2)
    except Exception as exc:  # noqa: BLE001
        # A1/master 侧预期走这里：模块不存在 ⇒ 标记 False
        print("PROVENANCE: has_A2_marker(dd_v1_entity_service.register_entity_alias) = False")
        print("PROVENANCE: marker check failed:", type(exc).__name__, exc)
