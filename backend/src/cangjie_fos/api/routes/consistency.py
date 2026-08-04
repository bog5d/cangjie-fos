"""口径一致性对比 API（F1 跨录音 + BP vs 访谈）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, UploadFile
from pydantic import BaseModel

from cangjie_fos.services.consistency_service import (
    run_bp_consistency_check,
    run_consistency_check,
)

router = APIRouter(prefix="/api/v1/consistency", tags=["consistency"])


@router.get("/check")
def check_consistency(
    tenant_id: str = Query(..., description="租户 ID"),
    limit: int = Query(8, ge=1, le=30, description="回看最近多少场录音"),
    institution: str = Query("", description="只看某机构相关录音（可选）"),
) -> dict:
    """跨最近若干场路演/访谈录音做关键指标口径一致性对比。"""
    return run_consistency_check(tenant_id, limit=limit, institution_filter=institution)


class BpCheckRequest(BaseModel):
    tenant_id: str
    bp_text: str
    limit: int = 8


@router.post("/bp-check")
def bp_check(req: BpCheckRequest) -> dict:
    """BP 文本 vs 高管访谈 口径比对（粘贴 BP 正文）。"""
    return run_bp_consistency_check(req.tenant_id, req.bp_text, limit=req.limit)


@router.post("/bp-check-file")
async def bp_check_file(
    file: UploadFile,
    tenant_id: str = Query(...),
    limit: int = Query(8, ge=1, le=30),
) -> dict:
    """上传 BP 文件（pdf/docx/txt/md）做口径比对。

    注：.pptx 暂不支持直接解析，请把 BP 文字粘贴到 /bp-check。
    """
    from cangjie_fos.services.dd_file_parser import extract_text  # noqa: PLC0415
    import tempfile

    fname = file.filename or "bp"
    suffix = Path(fname).suffix or ".txt"
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
        tmp.write(content)
        tmp.flush()
        text, readable = extract_text(Path(tmp.name), max_chars=20000)
    if not readable or not text.strip():
        return {"bp_topics": 0, "checked_interviews": [], "comparisons": [],
                "hard_conflicts": [], "counts": {},
                "note": "该文件正文读不出（如 .pptx / 图片型）。请把 BP 文字粘贴到 /bp-check。"}
    return run_bp_consistency_check(tenant_id, text, limit=limit)
