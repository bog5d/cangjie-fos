#!/usr/bin/env python3
"""生成 backend/src/cangjie_fos/core/_embedded.py —— 外发包内置默认配置。

为什么要它：外发 zip 里同事解压即用，不用手动填 .env。把团队共享的
coach_data 同步令牌等「开箱默认值」烤进这个文件。

安全约定（不要推翻）：
  - 本脚本**不含任何密钥**，可安全提交进 git。
  - 生成出来的 `_embedded.py` 含密钥，已被 backend/.gitignore 排除，
    **绝不进公开 GitHub**；只由 build_release_zip.ps1 拷进外发 zip。
  - 值用 base64 存（不是加密，只为不让明文令牌直接躺在源码里、
    也避开 GitHub secret scanning 的误报）。inject_defaults() 只在
    .env 和系统环境变量都没有该项时才填，绝不覆盖用户自己填的值。

用法（在你自己的构建机上跑一次，令牌从环境变量读，不落命令行历史）：
  export COACH_DATA_GITHUB_TOKEN='<粘贴你的细粒度令牌>'
  export COACH_DATA_GITHUB_REPO='bog5d/coach_data'   # 可选，默认即此
  python3 tools/make_embedded.py

跑完 backend/src/cangjie_fos/core/_embedded.py 就生成好了；打包时自动进 zip。
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

# 允许烤进外发包的默认项白名单（只填这些，避免误烤无关环境变量）
_EMBEDDABLE_KEYS = (
    "COACH_DATA_GITHUB_TOKEN",
    "COACH_DATA_GITHUB_REPO",
    "COACH_DATA_TENANT_ID",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "KIMI_API_KEY",
)

_TEMPLATE = '''"""内置默认配置（自动生成，请勿手改）。

由 tools/make_embedded.py 生成。gitignored——绝不进公开 GitHub，只进外发 zip。
值用 base64 存（非加密，仅避免明文令牌直接躺源码里）。
"""
from __future__ import annotations

import base64
import os

# base64(value) —— 团队共享的开箱默认值
_DEFAULTS_B64: dict[str, str] = {defaults!r}


def inject_defaults() -> None:
    """仅填补 .env 和系统环境变量都没有的项，绝不覆盖用户已填的值。"""
    for key, b64 in _DEFAULTS_B64.items():
        if (os.getenv(key) or "").strip():
            continue  # 用户/.env 已有值 → 尊重，不覆盖
        try:
            os.environ[key] = base64.b64decode(b64).decode("utf-8")
        except Exception:  # noqa: BLE001
            pass
'''


def main() -> int:
    defaults: dict[str, str] = {}
    for key in _EMBEDDABLE_KEYS:
        val = (os.getenv(key) or "").strip()
        if val:
            defaults[key] = base64.b64encode(val.encode("utf-8")).decode("ascii")

    if not defaults:
        print("⚠️  没有从环境变量读到任何可烤入项。请先 export COACH_DATA_GITHUB_TOKEN=... 再跑。")
        return 1

    out = Path(__file__).resolve().parents[1] / "backend/src/cangjie_fos/core/_embedded.py"
    out.write_text(_TEMPLATE.format(defaults=defaults), encoding="utf-8")
    print(f"✅ 已生成 {out}")
    print(f"   烤入 {len(defaults)} 项：{', '.join(defaults.keys())}")
    print("   （此文件 gitignored，不会进 GitHub；打包时自动进外发 zip）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
