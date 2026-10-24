"""尽调 gk 模式专属逻辑：材料库布局检测 + 加密文件检测。

机构问答响应引擎 阶段一（F1/F3）。

材料库布局（与"响应场景"正交）：
  flat            — 文件平铺在一个大文件夹（zt 结构，现有行为）
  per_institution — 根目录下按机构名分子文件夹（gk 结构）

布局由扫描时自动检测，无需用户手动切换。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 直属子目录中属于"系统/噪音"的名字，不计入机构子文件夹判定
_SYSTEM_DIR_NAMES = {
    "备份", "回收站", "归档", "临时", "缓存",
    "temp", "tmp", "archive", "backup", "cache", "trash",
    ".git", "__pycache__", "node_modules", ".idea", ".vscode",
    "$recycle.bin", "system volume information",
}


def detect_folder_layout(folder_path: str) -> str:
    """检测材料库布局：'flat' 或 'per_institution'。

    判定规则：根目录直属子目录中，剔除隐藏目录与系统/噪音目录后，
    若剩余"有意义"的子目录 ≥ 2 个，判定为 per_institution（按机构分类）；
    否则 flat（平铺）。
    """
    root = Path(folder_path)
    if not root.is_dir():
        return "flat"

    meaningful = [
        d for d in root.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and d.name.lower() not in _SYSTEM_DIR_NAMES
        and d.name not in _SYSTEM_DIR_NAMES
    ]
    if len(meaningful) >= 2:
        return "per_institution"
    return "flat"


# Office 正常文件是 ZIP 容器（PK\x03\x04 开头）；加密后变成 OLE2 复合文档
_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
_OFFICE_ZIP_EXTS = {".xlsx", ".docx", ".pptx"}
_OFFICE_OLE_EXTS = {".xls", ".doc", ".ppt"}


def is_file_encrypted(path: Path | str) -> bool:
    """启发式判断文件是否加密（无需密码，仅看字节签名）。

    - xlsx/docx/pptx：正常是 ZIP（PK 开头）；加密后是 OLE2 容器 → 视为加密。
    - pdf：文件头部出现 ``/Encrypt`` 关键字 → 视为加密。
    - 旧版 xls/doc 本身就是 OLE2，无法靠 magic 区分，保守判为非加密（靠文件名匹配）。

    MVP 范围：仅检测与标记，不解密、不读取加密内容。
    """
    p = Path(path)
    ext = p.suffix.lower()
    try:
        with open(p, "rb") as f:
            head = f.read(2048)
    except OSError as e:
        logger.warning("读取文件头失败 %s: %s", p, e)
        return False

    if ext in _OFFICE_ZIP_EXTS:
        # 正常应是 ZIP；不是 ZIP 而是 OLE2 → 加密
        if head.startswith(_OLE2_MAGIC):
            return True
        return False

    if ext == ".pdf":
        return b"/Encrypt" in head

    return False
