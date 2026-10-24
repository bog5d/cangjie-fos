"""文字稿解析器：将粘贴的对话文本转换为 TranscriptionWord 列表。

支持多种常见格式：
  - 说话人A: 你好，请问...
  - Speaker 1: Hello...
  - [说话人0] 我们的产品...
  - 【A】 内容...
  - 无标记（全部归入 speaker_id="0"）
"""
from __future__ import annotations

import re

from cangjie_fos.engine.schema import TranscriptionWord

# 匹配常见说话人标记格式
_SPEAKER_PATTERNS = [
    re.compile(r"^说话人\s*([A-Za-z0-9一-鿿]+)\s*[：:]\s*(.+)$"),
    re.compile(r"^Speaker\s*([A-Za-z0-9]+)\s*[：:]\s*(.+)$", re.IGNORECASE),
    re.compile(r"^\[([A-Za-z0-9一-鿿]+)\]\s*(.+)$"),
    re.compile(r"^【([A-Za-z0-9一-鿿]+)】\s*(.+)$"),
    re.compile(r"^([A-Za-z一-鿿]{1,6})\s*[：:]\s*(.+)$"),  # 通用 "X:" 格式
]


def _normalize_speaker_id(raw: str) -> str:
    """将各种说话人标记规范化为数字ID（如 A→0, B→1, 说话人0→0）。"""
    # 纯数字：直接用
    if raw.isdigit():
        return raw
    # 单字母：A=0, B=1, …
    if len(raw) == 1 and raw.isalpha():
        return str(ord(raw.upper()) - ord("A"))
    # 其他情况：用哈希取模生成简短ID
    return str(abs(hash(raw)) % 100)


def parse_transcript_to_words(text: str) -> list[TranscriptionWord]:
    """将对话文字稿解析为 TranscriptionWord 列表。

    时间戳全部设为0（文字稿没有真实时间），不影响LangGraph处理。
    """
    lines = text.strip().splitlines()
    words: list[TranscriptionWord] = []
    word_index = 0
    current_speaker = "0"
    speaker_map: dict[str, str] = {}  # raw → normalized

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 尝试匹配说话人标记
        matched_speaker = None
        matched_content = None
        for pattern in _SPEAKER_PATTERNS:
            m = pattern.match(line)
            if m:
                raw_speaker = m.group(1).strip()
                matched_speaker = raw_speaker
                matched_content = m.group(2).strip()
                break

        if matched_speaker is not None:
            if matched_speaker not in speaker_map:
                speaker_map[matched_speaker] = str(len(speaker_map))
            current_speaker = speaker_map[matched_speaker]
            content = matched_content or ""
        else:
            content = line

        if not content:
            continue

        # 将内容按标点/空格分割成词（简单分割，保持语义完整性）
        # 对于中文，以句子为单位更合适
        segments = re.split(r"([，。！？；,!?;])", content)
        buffer = ""
        for seg in segments:
            buffer += seg
            if re.search(r"[，。！？；,!?;]", seg) or len(buffer) >= 20:
                t = buffer.strip()
                if t:
                    words.append(TranscriptionWord(
                        word_index=word_index,
                        text=t,
                        start_time=0.0,
                        end_time=0.0,
                        speaker_id=current_speaker,
                    ))
                    word_index += 1
                buffer = ""

        # 处理剩余 buffer
        if buffer.strip():
            words.append(TranscriptionWord(
                word_index=word_index,
                text=buffer.strip(),
                start_time=0.0,
                end_time=0.0,
                speaker_id=current_speaker,
            ))
            word_index += 1

    return words
