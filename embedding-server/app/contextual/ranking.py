"""고정된 장소 후보에 근거를 더 연결하고 근거별 점수를 장소로 묶는다."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import IntEnum
import json
import math
from typing import Any

MAX_RERANK_PAIRS = 90
MAX_RERANK_TOKENS = 32768


class EvidenceCount(IntEnum):
    ONE = 1
    TWO = 2
    THREE = 3


def evidence_document(value: Any) -> dict[str, Any] | None:
    return json.loads(value) if isinstance(value, str) else value


def evidence_key(document: dict[str, Any]) -> tuple[str, str]:
    return document['chunk_id'], document['context_version']


@dataclass(frozen=True)
class EvidencePair:
    candidate_index: int
    text: str
    evidence: dict[str, Any] | None
    semantic_score: float


def validate_token_budget(pairs: list[EvidencePair], lengths: list[int]) -> None:
    if len(lengths) != len(pairs) or any(type(length) is not int or length <= 0 for length in lengths):
        raise ValueError('리랭킹 토큰 길이가 유효하지 않습니다')
    if sum(lengths) > MAX_RERANK_TOKENS:
        raise ValueError('리랭킹 토큰 예산을 초과했습니다')


def build_pairs(
    candidates: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    count: EvidenceCount,
) -> list[EvidencePair]:
    if len({candidate['place_id'] for candidate in candidates}) != len(candidates):
        raise ValueError('장소 후보가 중복되었습니다')
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row['place_id']].append(row)
    pairs = []
    for index, candidate in enumerate(candidates):
        primary = evidence_document(candidate.get('evidence'))
        selected = [{'evidence': primary, 'semantic_score': candidate['semantic_score']}]
        if count != EvidenceCount.ONE:
            selected = grouped.get(candidate['place_id'], [])
            if not selected or any(row['source_version'] != candidate['source_version'] for row in selected):
                raise ValueError('후보 검색 이후 장소 버전이나 활성 상태가 변경되었습니다')
            first = evidence_document(selected[0]['evidence'])
            if (primary is None) != (first is None) or (primary and evidence_key(primary) != evidence_key(first)):
                raise ValueError('후보 검색 이후 활성 근거가 변경되었습니다')
        seen = set()
        emitted = 0
        for row in selected:
            document = evidence_document(row['evidence'])
            key = evidence_key(document) if document else None
            if key in seen:
                continue
            seen.add(key)
            text = f"{document['context_text']}\n\n{document['chunk_text']}" if document else candidate['description'] or candidate['name']
            pairs.append(EvidencePair(index, text, document, float(row['semantic_score'])))
            emitted += 1
            if emitted == count:
                break
    if len(pairs) > MAX_RERANK_PAIRS:
        raise ValueError('리랭킹 입력 쌍 예산을 초과했습니다')
    return pairs


def rank_places(
    candidates: list[dict[str, Any]],
    pairs: list[EvidencePair],
    scores: list[float],
) -> list[tuple[dict[str, Any], float]]:
    if len(pairs) != len(scores) or not all(math.isfinite(score) for score in scores):
        raise ValueError('리랭킹 점수 개수 또는 값이 유효하지 않습니다')
    grouped: dict[int, list[tuple[EvidencePair, float]]] = defaultdict(list)
    for pair, score in zip(pairs, scores, strict=True):
        grouped[pair.candidate_index].append((pair, score))
    ranked = []
    for index, candidate in enumerate(candidates):
        evidence_scores = sorted(grouped[index], key=lambda item: item[1], reverse=True)
        if not evidence_scores:
            raise ValueError('점수를 계산하지 않은 장소 후보가 있습니다')
        winner, score = evidence_scores[0]
        # 합산하면 근거가 많은 장소가 유리해지므로 최고 근거 점수를 사용한다.
        ranked.append(({**candidate, 'description': winner.text, 'evidence': winner.evidence,
            'reranked_evidence_chunks': [{**pair.evidence, 'rerank_score': pair_score,
                'semantic_score': pair.semantic_score} for pair, pair_score in evidence_scores if pair.evidence]}, score))
    return sorted(ranked, key=lambda item: item[1], reverse=True)
