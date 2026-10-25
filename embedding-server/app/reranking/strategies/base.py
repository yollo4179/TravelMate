from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from opentelemetry.trace import Span
from sentence_transformers import CrossEncoder


class RerankingStrategyType(StrEnum):
    CROSS_ENCODER_PREDICT = "cross_encoder_predict"
    INSTRUMENTED_PREDICT = "instrumented_predict"
    AUTOCAST_FP16 = "autocast_fp16"
    MANUAL_DIAGNOSTIC = "manual_diagnostic"


class RerankingStrategy(ABC):
    strategy_type: RerankingStrategyType

    def is_applicable(self, strategy_type: RerankingStrategyType) -> bool:
        return self.strategy_type == strategy_type

    @abstractmethod
    def execute(
        self,
        model: CrossEncoder,
        query: str,
        texts: list[str],
        batch_size: int,
        span: Span,
    ) -> list[float]:
        raise NotImplementedError


class RerankingStrategyRegistry:
    def __init__(self, strategies: list[RerankingStrategy]) -> None:
        self.strategies = strategies

    def resolve(self, strategy_type: RerankingStrategyType) -> RerankingStrategy:
        applicable_strategies = [
            strategy for strategy in self.strategies
            if strategy.is_applicable(strategy_type)
        ]
        if len(applicable_strategies) != 1:
            raise ValueError(
                f"Expected one strategy for {strategy_type.value}, found {len(applicable_strategies)}"
            )
        return applicable_strategies[0]
