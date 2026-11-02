"""Build an unapproved strict-service proposal; no HTTP or execution option."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from prepare_openai_comparison import create_proposal


def service_proposal() -> dict[str, Any]:
    proposal = create_proposal()
    proposal["purpose"] = "SERVICE_CONFIGURATION_FIT_NOT_IDENTICAL_MODEL_COMPARISON"
    proposal["contract"].update({
        "openai_search_strict": True,
        "mode": "STRICT_SEARCH_V1",
        "same_canonical_parameters_as_qwen": False,
        "server_contract_unchanged": True,
        "strict_schema_variant_in_scope": True,
        "provider_required_fields": ["query", "region", "city", "category", "exclude_place_ids", "area", "limit"],
        "provider_nullable_fields": ["region", "city", "category", "exclude_place_ids", "area", "limit"],
        "explicit_default_adaptation": {"limit_null": 10},
        "server_only_schema_constraints": ["minLength", "maxLength", "uniqueItems", "default"],
        "native_replay": "Original provider function_call items, not adapted arguments",
    })
    proposal["cost"]["batch_spend_limit_implemented"] = True
    proposal["cost"]["batch_spend_limit_active"] = False
    proposal["cost"]["budget_reservation"] = "Full per-call input/output upper cost plus confirmed counting-request maximum; failures retain reservations"
    proposal["local_inference_target"] = {"embedding": "cuda", "reranker": "cuda", "qwen": "not loaded; verify before execution"}
    proposal["latency"]["cpu_search_record_separately"] = False
    proposal["latency"]["gpu_embedding_and_rerank_record_separately"] = True
    proposal["latency"]["historical_cpu_rerank_ms"] = 112268
    proposal["latency"]["current_gpu_latency_ms"] = None
    proposal["remaining_before_execution"] = [
        "User confirms proposed app model and final batch spend ceiling",
        "Confirm counting endpoint billing and record a verified per-request upper charge; unknown remains blocked",
        "Bind a new Spring runtime/JAR/observation directory and the approved budget file; original Qwen collector stays Qwen-only",
        "Verify the fixed two cases and per-request 2 model turns/1 search tool/STOP policy before dispatch",
        "Record current GPU configuration and corpus/source manifests; do not compare CPU timing as GPU timing",
    ]
    return proposal


def budget_template(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "approved": False,
        "inputCountBillingConfirmed": False,
        "inputCountBillingSource": None,
        "model": proposal["model"]["proposed_app_model"],
        "contextCap": proposal["model"]["local_context_cap"],
        "outputReservation": proposal["model"]["output_reservation_including_reasoning"],
        "maxCalls": proposal["execution_policy"]["max_inference_dispatches_including_failures"],
        "maxCallsPerCase": proposal["execution_policy"]["max_model_turns_per_request"],
        "inputUsdPerMillion": proposal["cost"]["input_per_million"],
        "outputUsdPerMillion": proposal["cost"]["output_per_million"],
        "inputCountRequestMaxUsd": None,
        "maxSpendUsd": proposal["cost"]["proposed_batch_spend_limit_usd"],
        "caseInputHashes": {row["case_id"]: row["input_sha256"] for row in proposal["case_requests"]},
        "ledgerFile": "openai-service-batch-ledger.jsonl",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    arguments = parser.parse_args()
    proposal = service_proposal()
    arguments.output_directory.mkdir(parents=True, exist_ok=False)
    for name, document in (("proposal.json", proposal), ("unapproved-budget.json", budget_template(proposal))):
        with (arguments.output_directory / name).open("x", encoding="utf-8", newline="\n") as destination:
            json.dump(document, destination, ensure_ascii=False, indent=2)
            destination.write("\n")
    print(json.dumps({"execution_enabled": False, "budget_approved": False, "case_count": len(proposal["case_requests"])}))


if __name__ == "__main__":
    main()
