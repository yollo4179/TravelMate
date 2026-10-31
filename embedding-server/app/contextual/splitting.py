"""원문을 재작성하지 않고 분할 버전별 경계를 계산한다."""
from __future__ import annotations

import re
from typing import Protocol

from .contracts import SourceDocument, SplitterVersion


class SplitterStrategy(Protocol):
    def is_applicable(self, version: SplitterVersion) -> bool: ...
    def split(self, source: SourceDocument, size: int) -> list[tuple[int, int]]: ...


class LegacySplitter:
    def is_applicable(self, version: SplitterVersion) -> bool:
        return version == SplitterVersion.LEGACY

    def split(self, source: SourceDocument, size: int) -> list[tuple[int, int]]:
        spans = []
        start = 0
        while start < len(source.text):
            end = min(start + size, len(source.text))
            if end < len(source.text):
                boundary = max(source.text.rfind("\n", start + size // 2, end), source.text.rfind(". ", start + size // 2, end))
                if boundary > start:
                    end = boundary + 1
            if source.text[start:end].strip():
                spans.append((start, end))
            start = end
        return spans


class SentenceParagraphSplitter:
    # 줄바꿈 전체를 문장으로 취급하면 블로그의 시각적 줄바꿈까지 잘리므로 종결 표현을 함께 본다.
    AFTER = (
        re.compile(r"\r?\n[ \t]*(?:\r?\n)+"),
        re.compile(r"(?m)^[ \t]*(?:\.{3,}|…+)[ \t]*(?:\r?\n|$)"),
        re.compile(r"(?<=[.!?。！？])(?:[ \t]+|\r?\n)+(?=\S)"),
        re.compile(r"[다요죠][ \t]*(?:\r?\n)+"),
    )
    BEFORE = re.compile(r"(?m)^[ \t]*(?:#{1,6}[ \t]+[^\r\n]+|\*\*[^\r\n]+\*\*[ \t]*)(?:\r?\n|$)")

    def is_applicable(self, version: SplitterVersion) -> bool:
        return version == SplitterVersion.SENTENCE

    def split(self, source: SourceDocument, size: int) -> list[tuple[int, int]]:
        cuts = {0, len(source.text)}
        for pattern in self.AFTER:
            cuts.update(match.end() for match in pattern.finditer(source.text))
        cuts.update(match.start() for match in self.BEFORE.finditer(source.text))
        ordered = sorted(cuts)
        spans: list[tuple[int, int]] = []
        pending = 0
        for _, end in zip(ordered, ordered[1:]):
            quotation = source.text[pending:end]
            if not any(character.isalnum() for character in quotation):
                continue
            spans.append((pending, end))
            pending = end
        if pending < len(source.text):
            if spans:
                spans[-1] = (spans[-1][0], len(source.text))
            elif source.text.strip():
                spans.append((0, len(source.text)))
        if any(end - start > size for start, end in spans):
            raise ValueError("문장·문단 경계 없는 긴 구간은 임의 절단하지 않습니다")
        if "".join(source.text[start:end] for start, end in spans) != source.text:
            raise ValueError("새 분할은 원문을 공백까지 완전히 보존해야 합니다")
        return spans


SPLITTERS: tuple[SplitterStrategy, ...] = (LegacySplitter(), SentenceParagraphSplitter())


def split_document(source: SourceDocument, size: int, version: str) -> list[tuple[int, int]]:
    if size < 1:
        raise ValueError("Chunk size must be positive")
    selected = [strategy for strategy in SPLITTERS if strategy.is_applicable(SplitterVersion(version))]
    if len(selected) != 1:
        raise ValueError("분할 전략은 정확히 하나여야 합니다")
    return selected[0].split(source, size)
