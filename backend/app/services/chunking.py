"""Structure-aware text chunking.

Text is split into natural units (paragraphs -> lines -> sentences -> words),
then units are greedily packed into chunks of ~`chunk_size` characters with a
tail overlap of ~`overlap` characters so context isn't lost at boundaries.
Chunks never span sections, which keeps page numbers accurate for citations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.parsers import Section

_SEPARATORS = [r"\n\s*\n", r"\n", r"(?<=[.!?])\s+", r"\s+"]


@dataclass
class TextChunk:
    text: str
    page: int | None


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_units(text: str, max_len: int, level: int = 0) -> list[str]:
    """Recursively split text until each unit is <= max_len."""
    if len(text) <= max_len:
        return [text]
    if level >= len(_SEPARATORS):
        return [text[i : i + max_len] for i in range(0, len(text), max_len)]
    pieces = [p for p in re.split(_SEPARATORS[level], text) if p.strip()]
    if len(pieces) <= 1:
        return _split_units(text, max_len, level + 1)
    units: list[str] = []
    for piece in pieces:
        units.extend(_split_units(piece.strip(), max_len, level + 1))
    return units


def _pack(units: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for unit in units:
        extra = len(unit) + (1 if current else 0)
        if current and length + extra > chunk_size:
            chunks.append("\n".join(current))
            # Carry trailing units forward as overlap.
            tail: list[str] = []
            tail_len = 0
            for prev in reversed(current):
                if tail_len + len(prev) > overlap:
                    break
                tail.insert(0, prev)
                tail_len += len(prev) + 1
            current, length = tail, max(tail_len - 1, 0)
            extra = len(unit) + (1 if current else 0)
        current.append(unit)
        length += extra
    if current:
        chunks.append("\n".join(current))
    return chunks


def chunk_sections(
    sections: list[Section], chunk_size: int = 1000, overlap: int = 150
) -> list[TextChunk]:
    out: list[TextChunk] = []
    for section in sections:
        text = _normalize(section.text)
        if not text:
            continue
        units = _split_units(text, chunk_size)
        for chunk in _pack(units, chunk_size, overlap):
            if chunk.strip():
                out.append(TextChunk(chunk.strip(), section.page))
    return out
