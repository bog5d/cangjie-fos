"""pytest 插件：session 起点打印**被测代码到底来自哪棵源码树**。

## 为什么需要这个插件

FOS 仓的 `backend/pyproject.toml` 里有：

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]     # 相对 rootdir，且 pytest 会**前置**到 sys.path
```

而 worktree 的 venv 里装的是 **editable install**（`.pth` 指向 `backend/src`）。

⇒ 在**裸 python** 下 `import cangjie_fos` 解析到的是 **venv 指向的那棵树**；
在 **pytest** 下则被 `pythonpath=["src"]` 前置改写成 **rootdir 所在的那棵树**。

两者不一致 ⇒ 「跑的是哪份代码」这件事**不能靠想**，必须**当场打印**。
A1 的回归对照（同解释器 master 基线 vs A1 worktree）就建立在这条上：
一旦对照跑错了树，结论就是假的。

用法（把本文件所在目录放进 PYTHONPATH，用 `-p` 加载）：

```bash
cd <被测 backend 目录>
PYTHONPATH=<a1-evidence 目录> \\
  env -u ALL_PROXY ... .venv/bin/python -m pytest -p provenance_plugin \\
  tests/ --ignore=tests/test_doctor_script.py -q --junit-xml=<xml>
```

输出里会有一行：

    PROVENANCE: cangjie_fos = /abs/path/to/src/cangjie_fos/__init__.py

这行就是「这次跑的到底是哪棵树」的**硬证据**。
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
    print("PROVENANCE: rootdir =", str(getattr(session, "config", None) and session.config.rootdir))
    print("PROVENANCE: sys.path[0:4] =", sys.path[0:4])
    # A1 独有的标记：只应出现在 A1 worktree 的代码里
    try:
        from cangjie_fos.services import dd_v1_match_service as ms
        import inspect
        has_a1 = "主体未登记，无法判定是否同一主体" in inspect.getsource(ms)
        print("PROVENANCE: has_A1_marker(主体未登记分支) =", has_a1)
    except Exception as exc:  # noqa: BLE001
        print("PROVENANCE: marker check failed:", type(exc).__name__, exc)
