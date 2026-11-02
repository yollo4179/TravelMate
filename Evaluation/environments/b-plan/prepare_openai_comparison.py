"""Create a proposal from preserved cases without HTTP, inference, or search."""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[3]
FROZEN_SCOPE = REPOSITORY / "Evaluation/runs/contextual/search-tool-contract-output-v1/20261102-01/next-execution-proposal.json"
MODEL = "gpt-5.4-mini-2026-03-17"
MODEL_SOURCE = "https://developers.openai.com/api/docs/models/gpt-5.4-mini"


def create_proposal() -> dict[str, Any]:
    frozen_scope = json.loads(FROZEN_SCOPE.read_text(encoding="utf-8-sig"))
    case_requests = frozen_scope["case_requests"]
    policy = frozen_scope["execution_policy"]
    model_calls = policy["max_qwen_dispatched_calls"]
    context_tokens = frozen_scope["model"]["context_tokens"]
    output_tokens = frozen_scope["model"]["output_reservation"]
    input_tokens = context_tokens - output_tokens
    input_rate = Decimal("0.75")
    output_rate = Decimal("4.50")
    inference_bound = model_calls * (input_tokens * input_rate + output_tokens * output_rate) / Decimal(1000000)
    return {
        "status": "PROPOSAL_ONLY_NOT_EXECUTED",
        "execution_enabled": False,
        "approval_required_before_any_openai_request": True,
        "frozen_scope": FROZEN_SCOPE.relative_to(REPOSITORY).as_posix(),
        "frozen_scope_sha256": hashlib.sha256(FROZEN_SCOPE.read_bytes()).hexdigest(),
        "case_requests": case_requests,
        "model": {
            "provider": "OPENAI",
            "proposed_app_model": MODEL,
            "selected_app_model": None,
            "judge_model": None,
            "endpoint": "https://api.openai.com/v1/responses",
            "service_tier": "default",
            "documented_context_tokens": 400000,
            "documented_max_output_tokens": 128000,
            "local_context_cap": context_tokens,
            "output_reservation_including_reasoning": output_tokens,
            "max_input_tokens_per_inference": input_tokens,
            "reasoning_effort": "omitted; documented snapshot default none",
            "source": MODEL_SOURCE,
        },
        "contract": {
            "version": "place-search-v2",
            "openai_search_strict": False,
            "parallel_tool_calls": False,
            "same_canonical_parameters_as_qwen": True,
            "strict_schema_variant_in_scope": False,
            "silent_argument_repair": False,
            "prompt_change_from_historical_qwen": "Request-envelope versus flat tool-arguments clarification",
        },
        "execution_policy": {
            "sequential": True,
            "repeats_per_case": policy["repeats_per_case"],
            "retries": 0,
            "max_conversation_requests": len(case_requests),
            "max_inference_dispatches_including_failures": model_calls,
            "max_input_count_requests": model_calls,
            "max_backend_search_requests": policy["max_backend_search_requests"],
            "max_model_turns_per_request": policy["max_model_turns_per_request"],
            "max_tool_calls_per_request": policy["max_tool_calls_per_request"],
            "plan_calls": 0,
            "judge_calls": 0,
            "qwen_calls": 0,
        },
        "cost": {
            "checked_on": "2026-11-02",
            "currency": "USD",
            "input_per_million": str(input_rate),
            "cached_input_per_million": "0.075",
            "output_per_million": str(output_rate),
            "cache_discount_assumed": False,
            "max_inference_input_tokens": model_calls * input_tokens,
            "max_output_tokens_including_reasoning": model_calls * output_tokens,
            "inference_token_cost_bound_usd": str(inference_bound),
            "proposed_batch_spend_limit_usd": "0.10",
            "batch_spend_limit_implemented": False,
            "total_billing_bound_confirmed": False,
            "input_count_endpoint_billing": "UNCONFIRMED: no price statement found in checked official docs",
            "tax_and_exchange_rate_included": False,
            "source": MODEL_SOURCE,
            "actual_api_requests_this_preparation": 0,
            "actual_usage": None,
        },
        "stop_conditions": frozen_scope["stop_conditions"] + [
            "Before dispatch, a reservation would exceed the approved batch spend limit",
            "Provider/model/tier/rate mismatch or unavailable usage/accounting",
            "Timeout has an unknown outcome: preserve it and do not retry",
        ],
        "evaluation_dimensions": frozen_scope["evaluation_dimensions"],
        "remaining_before_execution": [
            "User confirms proposed app model and batch spend ceiling",
            "Confirm account model access and input-count endpoint billing without paid probing",
            "Bind a new isolated OpenAI runtime; do not reuse completed Qwen observation files",
            "Add OpenAI batch accounting and stop checks to the existing Qwen-only collector",
            "Verify original corpus/settings, observations, and complete-source budget before dispatch",
        ],
        "latency": {
            "estimated_llm_latency_ms": None,
            "reason": "No measured OpenAI receipt; throughput is not guaranteed by model documentation",
            "cpu_search_record_separately": True,
            "historical_cpu_rerank_ms": 112268,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    proposal = create_proposal()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8", newline="\n") as destination:
        json.dump(proposal, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    print(json.dumps({"proposal": str(arguments.output), "inference_cost_bound_usd": proposal["cost"]["inference_token_cost_bound_usd"], "execution_enabled": False}))


if __name__ == "__main__":
    main()
