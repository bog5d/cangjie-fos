"""Pitch Job 失败信息规范化（Error Presentation Layer，Phase 6.3 修订）。

主界面/API 以 error_summary 为「说人话」主字段；error_detail 仅供 Tooltip/排障（脱敏+截断）。
"""
from __future__ import annotations

import json
import re
from typing import Any

CODE_UNKNOWN = "UNKNOWN"
CODE_ASR_VENDOR = "ASR_VENDOR"
CODE_ASR_TIMEOUT = "ASR_TIMEOUT"
CODE_GRAPH_EVAL = "GRAPH_EVAL"
CODE_NETWORK = "NETWORK"

_SUMMARY_MAX = 160
_DETAIL_MAX = 6000


def _redact(text: str) -> str:
    out = text
    out = re.sub(r"sk-[a-zA-Z0-9]{10,}", "sk-[已脱敏]", out)
    out = re.sub(r"(?i)bearer\s+[a-zA-Z0-9\-_.+/=]{20,}", "Bearer [已脱敏]", out)
    return out


def _truncate(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _guess_code_from_text(s: str) -> str:
    low = s.lower()
    if "timeout" in low or "timed out" in low or "超时" in s:
        return CODE_ASR_TIMEOUT
    if "transcrib" in low or "asr" in low or "speech" in low or "转写" in s or "语音识别" in s:
        return CODE_ASR_VENDOR
    if "langgraph" in low or "evaluat" in low or "model" in low or "openai" in low or "评估" in s:
        return CODE_GRAPH_EVAL
    if "connection" in low or "network" in low or "连接" in s:
        return CODE_NETWORK
    return CODE_UNKNOWN


def _summary_from_dict(d: dict[str, Any]) -> tuple[str, str | None]:
    candidates: list[str] = []
    for key in (
        "message",
        "Message",
        "error_message",
        "errorMessage",
        "msg",
        "error_msg",
        "Error",
        "error",
        "statusText",
        "reason",
        "Reason",
        "diagnostic_message",
    ):
        v = d.get(key)
        if isinstance(v, str) and v.strip() and not v.strip().startswith("{"):
            candidates.append(v.strip())
    summary = next((c for c in candidates if len(c) < 500), "")

    if not summary:
        out = d.get("output") or d.get("Output") or d.get("response")
        if isinstance(out, dict):
            inner_s, inner_d = _summary_from_dict(out)
            if inner_s:
                rid_top = d.get("request_id") or d.get("RequestId") or d.get("requestId")
                parts: list[str] = []
                if rid_top:
                    parts.append(f"request_id={rid_top}")
                if inner_d:
                    parts.append(inner_d)
                merged = "\n".join(parts) if parts else inner_d
                return inner_s, merged
        if isinstance(out, str) and out.strip():
            summary = out.strip()[:200]

    detail_parts: list[str] = []
    rid = d.get("request_id") or d.get("RequestId") or d.get("requestId")
    if rid:
        detail_parts.append(f"request_id={rid}")
    try:
        blob = json.dumps(d, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        blob = str(d)
    blob = _redact(blob)
    detail = _truncate(blob, _DETAIL_MAX) if blob else None
    if detail_parts and detail:
        detail = "\n".join(detail_parts) + "\n" + detail
    elif detail_parts:
        detail = "\n".join(detail_parts)

    if summary:
        return _truncate(summary.replace("\n", " "), _SUMMARY_MAX), detail
    return "", detail


def normalize_pitch_failure(raw: str | BaseException, *, job_id: str = "") -> dict[str, str | None]:
    """输出 error_summary / error_detail / error_code；summary 永不为 Raw JSON 块。"""
    text = str(raw).strip() if isinstance(raw, BaseException) else str(raw).strip()
    suffix = f"（任务尾号 {job_id[-6:]}）" if len(job_id) >= 6 else ""

    code = _guess_code_from_text(text)
    summary = ""
    detail: str | None = None

    if text.startswith("{") or text.startswith("["):
        try:
            parsed: Any = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            s, det = _summary_from_dict(parsed)
            summary = s
            detail = det
            code = _guess_code_from_text((summary or "") + (detail or "")) or code
        elif isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            s, det = _summary_from_dict(parsed[0])
            summary = s
            detail = det

    if not summary and text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                s, det = _summary_from_dict(parsed)
                summary = s or "语音转写或服务端返回异常，请稍后重试。"
                detail = det
                code = CODE_ASR_VENDOR if code == CODE_UNKNOWN else code
        except json.JSONDecodeError:
            pass

    if not summary:
        if len(text) > 240 or text.startswith("{") or _looks_like_vendor_blob(text):
            summary = "处理失败，请稍后重试或联系管理员。" + (suffix if suffix else "")
            detail = _truncate(_redact(text), _DETAIL_MAX)
        else:
            summary = _truncate(_redact(text), _SUMMARY_MAX) or ("处理失败，请稍后重试。" + (suffix if suffix else ""))
            if len(text) > len(summary) + 20:
                detail = _truncate(_redact(text), _DETAIL_MAX)

    summary = _truncate(summary.replace("\n", " "), _SUMMARY_MAX)
    if detail:
        detail = _truncate(_redact(detail), _DETAIL_MAX)

    if code == CODE_UNKNOWN and detail:
        code = _guess_code_from_text(detail)

    return {"error_summary": summary, "error_detail": detail, "error_code": code}


def _looks_like_vendor_blob(text: str) -> bool:
    t = text.strip()
    return "request_id" in t.lower() and ("output" in t.lower() or "'output'" in t or '"output"' in t)


def job_failure_update_kwargs(raw: str | BaseException, *, job_id: str) -> dict[str, str | None]:
    n = normalize_pitch_failure(raw, job_id=job_id)
    return {
        "error_summary": n["error_summary"],
        "error_detail": n["error_detail"],
        "error_code": n["error_code"],
        "error": n["error_summary"],
    }


def resolve_stored_job_errors(row: dict[str, Any], job_id: str) -> dict[str, str | None]:
    """读 API 时：新字段优先；仅有 legacy error 时现场规范化（内存旧态兼容）。"""
    if row.get("error_summary"):
        ec = row.get("error_code")
        return {
            "error_summary": str(row["error_summary"]),
            "error_detail": str(row["error_detail"]) if row.get("error_detail") is not None else None,
            "error_code": str(ec) if ec is not None else None,
            "error": str(row["error_summary"]),
        }
    raw = row.get("error")
    if not raw:
        return {"error_summary": None, "error_detail": None, "error_code": None, "error": None}
    n = normalize_pitch_failure(str(raw), job_id=job_id)
    return {
        "error_summary": n["error_summary"],
        "error_detail": n["error_detail"],
        "error_code": n["error_code"],
        "error": n["error_summary"],
    }
