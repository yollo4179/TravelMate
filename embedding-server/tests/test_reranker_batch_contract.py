from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.reranking.strategies.predict import (
    AutocastFp16CrossEncoderPredictStrategy,
    CrossEncoderPredictStrategy,
    InstrumentedCrossEncoderPredictStrategy,
)


class RerankerBatchContractTests(unittest.TestCase):
    def test_predict_strategies_forward_configured_batch_without_model_inference(self) -> None:
        for strategy in (
            CrossEncoderPredictStrategy(),
            InstrumentedCrossEncoderPredictStrategy(),
            AutocastFp16CrossEncoderPredictStrategy(),
        ):
            with self.subTest(strategy=strategy.strategy_type):
                model = Mock()
                model.device = "cpu"
                model.predict.return_value.tolist.return_value = [0.25, 0.75]
                scores = strategy.execute(model, "fixture", ["source one", "source two"], 8, Mock())
                model.predict.assert_called_once_with([["fixture", "source one"], ["fixture", "source two"]], batch_size=8)
                self.assertEqual([0.25, 0.75], scores)
