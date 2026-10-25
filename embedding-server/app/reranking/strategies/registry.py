from app.reranking.strategies.base import RerankingStrategy, RerankingStrategyRegistry
from app.reranking.strategies.manual_diagnostic import ManualDiagnosticStrategy
from app.reranking.strategies.predict import (
    CrossEncoderPredictStrategy,
    InstrumentedCrossEncoderPredictStrategy,
)


def build_reranking_strategy_registry() -> RerankingStrategyRegistry:
    strategies: list[RerankingStrategy] = [
        CrossEncoderPredictStrategy(),
        InstrumentedCrossEncoderPredictStrategy(),
        ManualDiagnosticStrategy(),
    ]
    return RerankingStrategyRegistry(strategies)
