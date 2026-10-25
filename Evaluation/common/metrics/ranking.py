"""Query-specific ranking metrics; no judge model or text reference required."""
from __future__ import annotations

from typing import Any
import math


def ranking_metrics(returned: list[Any], judgments: dict[Any, int], prefix: str = "") -> dict[str, float]:
    relevant = {identifier for identifier, grade in judgments.items() if grade >= 2}
    scores = {prefix + "top_1_accuracy": float(bool(returned) and returned[0] in relevant)}
    for cutoff in (5, 10):
        top = returned[:cutoff]
        hits = set(top).intersection(relevant)
        precision = len(hits) / cutoff
        recall = len(hits) / len(relevant) if relevant else 0.0
        ranks = [rank for rank, identifier in enumerate(top, 1) if identifier in relevant and identifier not in top[:rank - 1]]
        dcg = sum((2 ** judgments.get(identifier, 0) - 1) / math.log2(rank + 1) for rank, identifier in enumerate(top, 1) if identifier not in top[:rank - 1])
        ideal = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(sorted(judgments.values(), reverse=True)[:cutoff], 1))
        scores.update({
            prefix + f"top_{cutoff}_accuracy": float(bool(hits)),
            prefix + f"recall_at_{cutoff}": recall,
            prefix + f"precision_at_{cutoff}": precision,
            prefix + f"f1_at_{cutoff}": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            prefix + f"mrr_at_{cutoff}": 1 / ranks[0] if ranks else 0.0,
            prefix + f"map_at_{cutoff}": sum(len(set(top[:rank]).intersection(relevant)) / rank for rank in ranks) / min(len(relevant), cutoff) if relevant else 0.0,
            prefix + f"ndcg_at_{cutoff}": dcg / ideal if ideal else 0.0,
        })
    return scores
