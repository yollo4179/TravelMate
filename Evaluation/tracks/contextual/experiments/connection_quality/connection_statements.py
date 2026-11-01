"""과거 이동 정규식 정책의 오프라인 실험. 서비스 검색에 연결하지 않는다."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Protocol


class StatementStatus(StrEnum):
    POSITIVE = "reported_positive"
    BLOCKED = "reported_blocked"
    UNKNOWN = "unassessed"


class TravelMode(StrEnum):
    ANY = "any"
    WALKING = "walking"
    VEHICLE = "vehicle"
    UNSPECIFIED = "unspecified"


ABILITY = r"수\s*있(?:었다|다|으며|습니다|어요|음)(?!면)"
WALKING_POSITIVE = re.compile(r"(?:걸어(?:갈|올|서\s*(?:갈|올))\s*" + ABILITY + r"|걸어(?:갔다|왔다|갔어요|왔어요)|도보(?:로)?[^.!?\n]*(?:이동할|갈)\s*" + ABILITY + r")")
VEHICLE_POSITIVE = re.compile(r"(?:차량|자동차|버스|택시|차로)[^.!?\n]*(?:(?:이동할|갈|올)\s*" + ABILITY + r"|이동했다|갔다)")
GENERIC_POSITIVE = re.compile(r"(?:(?:이동할|갈|올)\s*" + ABILITY + r"|이동했다|연결되어\s*있다|이어져\s*있다)")
GENERAL_BLOCK = re.compile(r"(?:길[이은]\s*막(?:혀|혔)|도로[^,.;!?\n]*(?:폐쇄|차단)|전면\s*통행\s*금지|통행[이은]\s*(?:불가|차단)|(?:이동할|갈|걸어갈)\s*수\s*없)")
WALKING_BLOCK = re.compile(r"(?:도보[^,.;!?\n]*(?:금지|불가)|걸어갈\s*수\s*없)")
UNCERTAIN = re.compile(r"(?:것\s*같|듯하|추측|소문|아마|인지\s*모르|다고\s*(?:들|하|했)|라는\s*말|않|아니다|예정|계획|싶|다면|끝나면|열리면|개방되면)")


@dataclass(frozen=True)
class StatementAssessment:
    status: StatementStatus
    mode: TravelMode


def has_positive(quote: str) -> bool:
    return any(pattern.search(quote) for pattern in (WALKING_POSITIVE, VEHICLE_POSITIVE, GENERIC_POSITIVE))


def has_block(quote: str) -> bool:
    return bool(GENERAL_BLOCK.search(quote) or (WALKING_BLOCK.search(quote) and not VEHICLE_POSITIVE.search(quote)))


def reported_mode(quote: str) -> TravelMode:
    modes = [
        mode for mode, pattern in (
            (TravelMode.VEHICLE, VEHICLE_POSITIVE),
            (TravelMode.WALKING, WALKING_POSITIVE),
        ) if pattern.search(quote)
    ]
    if len(modes) == 1:
        return modes[0]
    if WALKING_BLOCK.search(quote):
        return TravelMode.WALKING
    return TravelMode.UNSPECIFIED


class StatementStrategy(Protocol):
    def is_applicable(self, quote: str) -> bool: ...
    def assess(self, quote: str) -> StatementAssessment: ...


class BlockedStatementStrategy:
    def is_applicable(self, quote: str) -> bool:
        return not UNCERTAIN.search(quote) and has_block(quote)

    def assess(self, quote: str) -> StatementAssessment:
        return StatementAssessment(StatementStatus.BLOCKED, reported_mode(quote))


class PositiveStatementStrategy:
    def is_applicable(self, quote: str) -> bool:
        return not UNCERTAIN.search(quote) and not has_block(quote) and has_positive(quote)

    def assess(self, quote: str) -> StatementAssessment:
        return StatementAssessment(StatementStatus.POSITIVE, reported_mode(quote))


class UnknownStatementStrategy:
    def is_applicable(self, quote: str) -> bool:
        return bool(UNCERTAIN.search(quote)) or (not has_block(quote) and not has_positive(quote))

    def assess(self, quote: str) -> StatementAssessment:
        return StatementAssessment(StatementStatus.UNKNOWN, reported_mode(quote))


STATEMENT_STRATEGIES: tuple[StatementStrategy, ...] = (
    BlockedStatementStrategy(),
    PositiveStatementStrategy(),
    UnknownStatementStrategy(),
)


def assess_statement(
    quote: str,
    strategies: tuple[StatementStrategy, ...] = STATEMENT_STRATEGIES,
) -> StatementAssessment:
    applicable = [strategy for strategy in strategies if strategy.is_applicable(quote)]
    if len(applicable) != 1:
        raise ValueError("이동 표현 판정 전략은 정확히 하나여야 합니다")
    return applicable[0].assess(quote)
