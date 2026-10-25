"""LangSmith tracing for RAGAS model calls and metric results."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


class EvaluationTrace:
    def __init__(self, run: Any) -> None:
        self._run = run
        self._attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self._attributes[key] = value


@contextmanager
def evaluation_span(
    *,
    operation: str,
    case_id: str,
    strategy_version: str,
    metric_name: str,
    inputs: dict[str, Any] | None = None,
    project_name: str | None = None,
) -> Iterator[EvaluationTrace | None]:
    """Record a metric result and nest wrapped model calls under its trace."""
    tracing_enabled = (
        os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
        or os.getenv("LANGSMITH_TRACING", "").lower() == "true"
    )
    if not tracing_enabled or not os.getenv("LANGCHAIN_API_KEY"):
        yield None
        return

    from langsmith.run_helpers import tracing_context
    from langsmith.run_trees import RunTree

    run = RunTree(
        name=operation,
        run_type="chain",
        project_name=project_name or os.getenv("LANGCHAIN_PROJECT", "travelmate-ragas-v1.3.0"),
        inputs={
            "case_id": case_id,
            "strategy_version": strategy_version,
            "metric_name": metric_name,
            **(inputs or {}),
        },
    )
    trace = EvaluationTrace(run)
    try:
        run.post()
    except Exception:
        yield None
        return

    try:
        with tracing_context(parent=run, enabled=True):
            yield trace
    except Exception as exception:
        run.end(error=type(exception).__name__, end_time=datetime.now(timezone.utc))
        try:
            run.patch()
        except Exception:
            pass
        raise
    else:
        run.end(outputs=trace._attributes, end_time=datetime.now(timezone.utc))
        try:
            run.patch()
        except Exception:
            pass
