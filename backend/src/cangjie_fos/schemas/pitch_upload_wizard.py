"""Phase 6.2：两阶段上传向导 JSON 契约（对齐 AI_Pitch_Coach app.py 主表单）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SniperRow(BaseModel):
    quote: str = ""
    reason: str = ""


class WizardTrackSpec(BaseModel):
    """单条录音元数据（音频二进制通过后续 multipart 上传）。"""

    client_temp_id: str = Field(..., min_length=1, description="前端稳定键")
    interviewee: str = Field(..., min_length=1, description="被访谈人，必填")
    sniper_rows: list[SniperRow] = Field(default_factory=list)
    speaker_hint: str = Field(default="", description="身份映射提示，并入 session_notes")


class UploadWizardCreateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    user_name: str = Field(default="", description="当前指挥官，无账号体系")
    memory_company_id: str = Field(
        default="",
        description="Coach 记忆 company_id；空则服务端用 tenant_id 兜底",
    )
    category: str = Field(..., min_length=1, description="业务大类，不可为占位串")
    institution_name: str = Field(..., min_length=1)
    batch_label: str = ""
    investor_name: str = ""
    custom_roles_other: str = ""
    company_background: str = ""
    sensitive_words_raw: str = ""
    hot_words_raw: str = ""
    enable_asr_polish: bool = Field(
        True,
        description="开启错别字轻修正 → skip_asr_polish = not enable_asr_polish",
    )
    use_langgraph_v1: bool = False
    tracks: list[WizardTrackSpec] = Field(..., min_length=1)


class UploadSessionCreateResponse(BaseModel):
    session_id: str
    track_count: int


class UploadSessionCommitResponse(BaseModel):
    job_ids: list[str]
    assistant_echo: str
    """HTTP 回包内自然语言，供无 WS 时客户端本地 pushLine。"""


class UploadSessionCommitError(BaseModel):
    detail: str


class WizardPartAck(BaseModel):
    """分片上传成功回执（非 pitch job）。"""

    ok: bool = True
    track_index: int = 0
