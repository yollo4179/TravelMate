"""Verify identical saved requests offline; never invokes Ollama or application APIs."""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
import struct
import subprocess
from typing import Any

from common.dataset.io import read_json, read_jsonl, write_json, write_jsonl
from tracks.tool_call.qwen_tokenization import (
    NativeQwenVocabulary, file_sha256, independent_byte_bpe, read_gguf_metadata,
)


def compact(document: Any) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verified_inputs(prior: Path, saved_tool_events: Path) -> list[dict[str, Any]]:
    blueprint = read_json(prior / "initial-wire-example.json")
    budgets = read_jsonl(prior / "qwen-budgets.jsonl")
    initial = {row["case_id"]: row for row in budgets if row["scope"] == "INITIAL_API_REQUEST"}
    requests = []
    for row in read_jsonl(prior / "case-connections.jsonl"):
        request = row["minimal_api_request"]
        wire = copy.deepcopy(blueprint)
        wire["messages"] = ([blueprint["messages"][0]]
                            + [{"role": message["role"].lower(), "content": message["content"]}
                               for message in request["history"]]
                            + [{"role": "user", "content": compact({"message": request["message"],
                                                                    "planningRequest": request["planningRequest"]})}])
        _match_wire(wire, initial[row["case_id"]])
        requests.append({"key": row["case_id"], "wire": wire, "prior_budget": initial[row["case_id"]],
                         "input_sha256": row["input_sha256"]})
    followup = next(row for row in budgets if row["scope"] == "SAVED_MOCK_SEARCH_FOLLOWUP")
    original = next(row for row in requests if row["key"] == followup["case_id"])
    selected = next(event["payload"] for event in read_jsonl(saved_tool_events) if event["event"] == "TOOL_RESULT")
    result = selected["result"]
    model_input = selected["modelData"]
    user = compact({"message": json.loads(original["wire"]["messages"][-1]["content"])["message"],
                    "planningRequest": model_input["request"]})
    feedback = compact({"type": result["type"], "data": model_input})
    matched = []
    # Preserve the previous JVM's Map.of key ordering by checking its recorded byte hash.
    for outer in itertools.permutations(("type", "function")):
        for inner in itertools.permutations(("name", "arguments")):
            values = {"name": result["name"], "arguments": json.loads(result["arguments"])}
            function = {key: values[key] for key in inner}
            call_values = {"type": "function", "function": function}
            call = {key: call_values[key] for key in outer}
            wire = copy.deepcopy(blueprint)
            wire["messages"] = [blueprint["messages"][0], {"role": "user", "content": user},
                                {"role": "assistant", "content": "", "tool_calls": [call]},
                                {"role": "tool", "content": feedback, "tool_name": result["name"]}]
            if sha256(compact(wire).encode()) == followup["wire_sha256"]:
                matched.append(wire)
    if len(matched) != 1:
        raise ValueError("Saved followup native bytes could not be verified; do not count a substituted prompt")
    requests.append({"key": followup["case_id"] + ":saved-mock-followup", "wire": matched[0],
                     "prior_budget": followup, "input_sha256": original["input_sha256"]})
    return requests


def _match_wire(wire: dict[str, Any], budget: dict[str, Any]) -> None:
    if sha256(compact(wire).encode()) != budget["wire_sha256"]:
        raise ValueError("Native request differs from the previously budgeted bytes")


def verify(
    *,
    prior: Path,
    saved_tool_events: Path,
    model: Path,
    expected_model_sha256: str,
    libraries: Path,
    expected_library_sha256: str,
    renderer: Path,
    expected_renderer_sha256: str,
    output: Path,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("Verification cannot overwrite a previous run")
    if file_sha256(model) != expected_model_sha256 or file_sha256(renderer) != expected_renderer_sha256:
        raise ValueError("Unverified model or renderer identity")
    metadata = read_gguf_metadata(model)
    show = read_json(prior / "qwen-show.json")
    if show.get("template_source") != "go_template" or show.get("system"):
        raise ValueError("Unsupported model renderer or default system prompt")
    requests = verified_inputs(prior, saved_tool_events)
    envelopes = [{"key": row["key"], "wire": row["wire"], "template": show["template"],
                  "template_source": show["template_source"]} for row in requests]
    completed = subprocess.run([str(renderer.resolve())], input="".join(compact(row) + "\n" for row in envelopes).encode(),
                               capture_output=True, check=True, timeout=60)
    rendered = [json.loads(line) for line in completed.stdout.decode("utf-8").split("\n") if line]
    if len(rendered) != len(requests):
        raise ValueError("Missing rendered prompts")
    comparisons = []
    output.mkdir(parents=True)
    with NativeQwenVocabulary(libraries, model, expected_library_sha256) as native:
        policy = native.special_policy()
        if policy["add_bos"] or policy["add_eos"]:
            raise ValueError("Unverified automatic special-token policy")
        independent = independent_byte_bpe(metadata, native.special_tokens())
        for request, rendered_prompt in zip(requests, rendered, strict=True):
            budget = request["prior_budget"]
            if request["key"] != rendered_prompt["key"] or rendered_prompt["wire_sha256"] != budget["wire_sha256"]:
                raise ValueError("Renderer changed request identity")
            if rendered_prompt["template_sha256"] != budget["count"]["evidence"]["templateSha256"]:
                raise ValueError("Template differs from the previously budgeted template")
            prompt = rendered_prompt["prompt"]
            if sha256(prompt.encode()) != rendered_prompt["prompt_sha256"]:
                raise ValueError("Rendered prompt byte hash mismatch")
            identifiers = native.encode(prompt)
            secondary = independent.encode(prompt, add_special_tokens=False).ids
            if identifiers != secondary or native.decode(identifiers, len(prompt.encode())) != prompt.encode():
                raise ValueError("Token ID cross-check or exact byte roundtrip failed")
            exact = len(identifiers)
            comparisons.append({"case_id": budget["case_id"], "scope": budget["scope"],
                                "input_sha256": request["input_sha256"], "wire_sha256": budget["wire_sha256"],
                                "template_sha256": rendered_prompt["template_sha256"],
                                "prompt_sha256": rendered_prompt["prompt_sha256"],
                                "token_ids_sha256": sha256(struct.pack("<" + str(exact) + "i", *identifiers)),
                                "count_quality": "EXACT_OFFLINE_CROSSCHECKED", "input_tokens": exact,
                                "prior_conservative_input_bound": budget["count"]["inputTokens"],
                                "bound_minus_exact_input_tokens": budget["count"]["inputTokens"] - exact,
                                "output_reservation": budget["output_reservation"],
                                "exact_input_plus_reserved_output": exact + budget["output_reservation"],
                                "configured_context": budget["context_tokens_configured"],
                                "fits_by_offline_exact_count_only": exact + budget["output_reservation"] <= budget["context_tokens_configured"],
                                "runtime_guard_changed_or_bypassed": False, "inference_dispatched": False,
                                "native_and_independent_token_ids_identical": True, "full_prompt_byte_roundtrip_identical": True})
        (output / "native-vocabulary-load.txt").write_text("".join(native.log), encoding="utf-8", newline="\n")
    initial = [row for row in comparisons if row["scope"] == "INITIAL_API_REQUEST"]
    summary = {"baseline": "95552e7f", "inference_calls": 0, "llama_context_created": False,
               "model_tensors_loaded": False, "model_sha256_verified": expected_model_sha256,
               "native_library_sha256_verified": expected_library_sha256, "renderer_sha256_verified": expected_renderer_sha256,
               "renderer_module": "github.com/ollama/ollama@v0.40.13", "llama_cpp_header_pin": "b11963",
               "native_special_policy": policy, "metadata_bytes_before_tensor_table": metadata["inspection.bytes_read_before_tensor_table"],
               "metadata_tensor_count_not_loaded": metadata["inspection.tensor_count_not_loaded"],
               "identical_prior_wire_and_template_count": len(comparisons), "initial_requests": len(initial),
               "initial_exact_input_tokens_min": min(row["input_tokens"] for row in initial),
               "initial_exact_input_tokens_max": max(row["input_tokens"] for row in initial),
               "initial_bound_overcount_min": min(row["bound_minus_exact_input_tokens"] for row in initial),
               "initial_bound_overcount_max": max(row["bound_minus_exact_input_tokens"] for row in initial),
               "offline_exact_fit_count": sum(row["fits_by_offline_exact_count_only"] for row in comparisons),
               "unchanged_guard_policy_would_reject_count": sum(row["prior_budget"]["status"] == "EXCEEDED" for row in requests),
               "runtime_guard_changed": False,
               "context_increased": False, "evidence_truncated": False,
               "future_uncaptured_tool_and_async_prompts": "UNVERIFIED",
               "server_reported_usage": None}
    write_jsonl(output / "counts.jsonl", comparisons)
    write_json(output / "summary.json", summary)
    write_json(output / "first-wire.json", requests[0]["wire"])
    (output / "first-rendered-prompt.txt").write_text(rendered[0]["prompt"], encoding="utf-8", newline="\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--saved-tool-events", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--expected-model-sha256", required=True)
    parser.add_argument("--libraries", type=Path, required=True)
    parser.add_argument("--expected-library-sha256", required=True)
    parser.add_argument("--renderer", type=Path, required=True)
    parser.add_argument("--expected-renderer-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(verify(prior=arguments.prior, saved_tool_events=arguments.saved_tool_events, model=arguments.model,
                            expected_model_sha256=arguments.expected_model_sha256, libraries=arguments.libraries,
                            expected_library_sha256=arguments.expected_library_sha256, renderer=arguments.renderer,
                            expected_renderer_sha256=arguments.expected_renderer_sha256, output=arguments.output)))


if __name__ == "__main__":
    main()
