"""分块读取上传流并强制大小上限。"""
from __future__ import annotations

from fastapi import HTTPException, UploadFile

from cangjie_fos.core.limits import max_upload_bytes


async def read_upload_limited(file: UploadFile) -> bytes:
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
