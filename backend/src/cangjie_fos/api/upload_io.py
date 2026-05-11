"""分块读取上传流并强制大小上限。"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile

from cangjie_fos.core.limits import max_upload_bytes


async def read_upload_limited(file: UploadFile) -> bytes:
    """小文件用（QA 文字稿等）：读入内存后返回 bytes。"""
    max_b = max_upload_bytes()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 64)
        if not chunk:
            break
        total += len(chunk)
        if total > max_b:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "E_UPLOAD_TOO_LARGE",
                    "message": f"文件超过 {max_b // (1024 * 1024)}MB 限制",
                },
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def stream_upload_to_path(file: UploadFile, dest: Path) -> int:
    """大文件用（音频）：流式边读边落盘，不把完整文件加载到内存。

    返回写入的字节数；超限时删除不完整文件并抛 HTTP 413。
    """
    max_b = max_upload_bytes()
    total = 0
    try:
        with open(dest, "wb") as fh:
            while True:
                chunk = await file.read(1024 * 64)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_b:
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "code": "E_UPLOAD_TOO_LARGE",
                            "message": f"文件超过 {max_b // (1024 * 1024)}MB 限制",
                        },
                    )
                fh.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)  # 清理不完整文件
        raise
    return total
