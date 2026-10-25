"""Build canonical gold and deterministic group/type/track views; never write run results."""
from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import math
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.contracts import ENVELOPE_SCHEMA, TOOL_ARGUMENT_SCHEMAS, TOOL_CONTRACTS, ResponseType, ToolName
from tracks.plan.score_route import optimal_route
from common.dataset.io import digest, read_json, read_jsonl, write_json, write_jsonl

from common.paths import DEFAULT_DATASET

ROOT = DEFAULT_DATASET
GROUPS = ("plannerLLM", "managerLLM")


def place_payload(place: dict[str, Any]) -> dict[str, Any]:
    return {
        "placeId": place["id"], "name": place["name"], "description": place["description"],
        "region": place["region"], "city": place["city"],
        "latitude": place["latitude"], "longitude": place["longitude"],
        "imageUrl": place["image_url"],
    }


def reference_data(case: dict[str, Any], source: dict[str, Any], corpus: dict[int, dict[str, Any]]) -> Any:
    kind = ResponseType(case["expected_response_type"])
    calls = case["expectations"]["tool_call"]["required_calls"]
    if kind == ResponseType.TEXT:
        return None
    if kind == ResponseType.PLACES:
        return [place_payload(corpus[place_id]) for place_id in source["relevant_place_ids"]]
    if kind == ResponseType.CLARIFICATION:
        return {"missing": case["expectations"]["behavior"]["missing"]}
    if kind == ResponseType.PLAN_DIFF:
        if case["expectations"]["state"]["applied"]:
            return case["fixtures"]["server_mutation_receipt"]
        arguments = calls[0]["arguments"]
        return {
            "planId": arguments["plan_id"], "baseVersion": 3,
            "proposalId": f"fixture-proposal-{case['case_id']}", "applied": False,
            "changes": [arguments],
        }
    arguments = next(call["arguments"] for call in calls if call["name"] == ToolName.CREATE_PLAN)
    selected = arguments["place_ids"]
    matrix = case["fixtures"].get("travel_cost_matrix")
    order = optimal_route(selected, matrix)[0] if matrix else selected
    stops = []
    clock = datetime.fromisoformat(arguments["start_at"])
    previous = "origin"
    for sequence, place_id in enumerate(order, 1):
        if matrix:
            clock += timedelta(minutes=matrix["costs"][previous][str(place_id)])
        stop = {"placeId": place_id, "sequence": sequence, "stayMinutes": 40}
        if matrix:
            stop.update(arrivalAt=clock.isoformat(), departureAt=(clock + timedelta(minutes=40)).isoformat())
            clock += timedelta(minutes=40)
        stops.append(stop)
        previous = str(place_id)
    return {"proposalId": f"fixture-proposal-{case['case_id']}", "applied": False, "stops": stops}


def validate_source(cases: list[dict[str, Any]], sources: dict[str, dict[str, Any]], corpus: dict[int, dict[str, Any]]) -> None:
    if len(cases) != 200 or len({case["case_id"] for case in cases}) != 200:
        raise ValueError("Expected 200 unique canonical cases")
    splits: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        ResponseType(case["expected_response_type"])
        if case["evaluation_group"] not in GROUPS or case["split"] not in ("development", "test"):
            raise ValueError(f"{case['case_id']}: unknown evaluation group or split")
        if not case["reference"].strip() or not isinstance(case["evaluation_tracks"], list) or not case["evaluation_tracks"]:
            raise ValueError(f"{case['case_id']}: reference/tracks missing")
        splits[case["scenario_group"]].add(case["split"])
        source = sources[case["source_case_id"]]
        if case["split"] != source["split"] or case["scenario_group"] != source["group_id"]:
            raise ValueError(f"{case['case_id']}: shared source group split changed")
        candidate_ids = case["input"]["candidate_place_ids"]
        if len(set(candidate_ids)) != len(candidate_ids) or any(type(place_id) is not int or place_id not in corpus for place_id in candidate_ids):
            raise ValueError(f"{case['case_id']}: invalid candidate ID")
        for call in case["expectations"]["tool_call"]["required_calls"]:
            ToolName(call["name"])
            if not isinstance(call["arguments"], dict):
                raise ValueError("Tool arguments must be objects")
        search = case["expectations"]["search"]
        if search and (case["input"]["query"] != source["query"] or case["input"]["conditions"] != source["conditions"]):
            raise ValueError("Query-specific human judgments cannot be reused for a different query or conditions")
        plan = case["expectations"]["plan"]
        if plan:
            allowed = set(plan["allowed_place_ids"])
            if not allowed <= set(candidate_ids) or not set(plan["required_place_ids"]) <= allowed:
                raise ValueError("Invalid allowed/required selection IDs")
            if allowed.intersection(plan["exclude_place_ids"]):
                raise ValueError("Allowed selection includes excluded places")
            start, end = datetime.fromisoformat(plan["start_at"]), datetime.fromisoformat(plan["end_at"])
            if start.tzinfo is None or end.tzinfo is None or end <= start:
                raise ValueError("Plan fixture requires an explicit positive time window")
        matrix = case["fixtures"].get("travel_cost_matrix")
        if matrix:
            nodes = ["origin", *(str(place_id) for place_id in candidate_ids)]
            for first in nodes:
                for second in nodes:
                    cost = matrix["costs"][first][second]
                    if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
                        raise ValueError("Route fixture costs must be finite nonnegative minutes")
        if case["expected_response_type"] == ResponseType.CLARIFICATION and not case["expectations"]["behavior"].get("missing"):
            raise ValueError("Clarification requires named missing fields")
    if any(len(values) != 1 for values in splits.values()):
        raise ValueError("A scenario group crosses development/test in different views")
    if Counter(case["evaluation_group"] for case in cases) != Counter({"plannerLLM": 100, "managerLLM": 100}):
        raise ValueError("Expected 100 cases per evaluation group")


def compile_cases(root: Path) -> list[dict[str, Any]]:
    common = root / "source"
    sources = {case["case_id"]: case for case in read_jsonl(common / "source_goldenset_v1.3.0.jsonl")}
    corpus = {place["id"]: place for place in read_json(common / "corpus.source.json")}
    cases = read_json(common / "cases.source.json")["cases"]
    validate_source(cases, sources, corpus)
    compiled = copy.deepcopy(cases)
    for case in compiled:
        source = sources[case["source_case_id"]]
        case["place_judgments"] = source["judgments"] if case["expectations"]["search"] else []
        case["reference_envelope"] = {
            "type": case["expected_response_type"], "message": case["reference"],
            "data": reference_data(case, source, corpus), "conversationId": case["input"]["conversationId"],
        }
    return compiled


def generated_views(root: Path, cases: list[dict[str, Any]]) -> dict[Path, list[dict[str, Any]]]:
    views = {root / "generated/golden.jsonl": cases}
    for split in ("development", "test"):
        views[root / f"generated/{split}.jsonl"] = [case for case in cases if case["split"] == split]
    for kind in ResponseType:
        views[root / f"generated/by_type/{kind.value}.jsonl"] = [case for case in cases if case["expected_response_type"] == kind]
    for track in sorted({track for case in cases for track in case["evaluation_tracks"]}):
        views[root / f"generated/by_track/{track}.jsonl"] = [case for case in cases if track in case["evaluation_tracks"]]
    views[root / "generated/by_track/persona.jsonl"] = [case for case in cases if "message" in case["evaluation_tracks"]]
    for group in GROUPS:
        selected = [case for case in cases if case["evaluation_group"] == group]
        views[root / "generated/by_group" / group / "golden.jsonl"] = selected
        for split in ("development", "test"):
            views[root / "generated/by_group" / group / f"{split}.jsonl"] = [case for case in selected if case["split"] == split]
        for kind in ResponseType:
            views[root / "generated/by_group" / group / f"by_type/{kind.value}.jsonl"] = [case for case in selected if case["expected_response_type"] == kind]
    return views


def manifest(root: Path, cases: list[dict[str, Any]], views: dict[Path, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "dataset_version": "1.4.0", "architecture": "one conversational/control LLM with tools; evaluation tracks share a canonical dataset",
        "case_count": len(cases), "reference_count": sum(bool(case["reference"]) for case in cases),
        "counts_by_group": dict(Counter(case["evaluation_group"] for case in cases)),
        "counts_by_split": dict(Counter(case["split"] for case in cases)),
        "counts_by_type": dict(Counter(case["expected_response_type"] for case in cases)),
        "counts_by_track": dict(Counter(track for case in cases for track in case["evaluation_tracks"])),
        "canonical_source": "source/cases.source.json",
        "source_git_commit": read_json(root / "source/cases.source.json").get("source_git_commit"),
        "source_sha256": {
            name: digest(root / name)
            for name in ("source/cases.source.json", "source/corpus.source.json", "source/snapshot.json",
                         "source/source_goldenset_v1.3.0.jsonl", "source/review_notes.csv")
        },
        "contract_sha256": {
            name: digest(root / name)
            for name in ("generated/schemas/envelope.schema.json", "generated/schemas/tool_contracts.json", "generated/schemas/tool_arguments.schema.json",
                         "source/persona/guide_v1.json", "source/judge_config.json", "generated/schemas/response_record.schema.json",
                         "rubrics/plan_quality.md", "rubrics/behavior.md")
        },
        "view_sha256": {str(path.relative_to(root)): digest(path) for path in views},
        "all_views_generated_not_independently_authored": True,
        "new_role_expectations_human_reviewed": False,
        "source_human_review_preserved": True,
        "system_outputs_embedded_in_gold": False,
        "runtime_results_managed_separately": True,
    }


def build(root: Path = ROOT) -> dict[str, Any]:
    write_json(root / "generated/schemas/envelope.schema.json", ENVELOPE_SCHEMA)
    write_json(root / "generated/schemas/tool_contracts.json", TOOL_CONTRACTS)
    write_json(root / "generated/schemas/tool_arguments.schema.json", TOOL_ARGUMENT_SCHEMAS)
    cases = compile_cases(root)
    write_json(root / "generated/corpus.json", read_json(root / "source/corpus.source.json"))
    views = generated_views(root, cases)
    for path, rows in views.items():
        write_jsonl(path, rows)
    report = manifest(root, cases, views)
    write_json(root / "manifest.json", report)
    write_json(root / "validation.json", {"status": "passed", "manifest_sha256": digest(root / "manifest.json"), "case_count": len(cases)})
    return report


def check(root: Path = ROOT) -> dict[str, Any]:
    from jsonschema import Draft202012Validator

    cases = compile_cases(root)
    if read_json(root / "generated/schemas/envelope.schema.json") != ENVELOPE_SCHEMA:
        raise ValueError("Envelope schema differs from the common contract")
    if read_json(root / "generated/schemas/tool_arguments.schema.json") != TOOL_ARGUMENT_SCHEMAS:
        raise ValueError("Tool argument schema differs from the common contract")
    if read_json(root / "generated/schemas/tool_contracts.json") != TOOL_CONTRACTS:
        raise ValueError("Tool contract differs from the shared definition")
    views = generated_views(root, cases)
    validator = Draft202012Validator(ENVELOPE_SCHEMA)
    for case in cases:
        validator.validate(case["reference_envelope"])
        for call in case["expectations"]["tool_call"]["required_calls"]:
            Draft202012Validator(TOOL_ARGUMENT_SCHEMAS[call["name"]]).validate(call["arguments"])
    for path, expected in views.items():
        if not path.exists() or read_jsonl(path) != expected:
            raise ValueError(f"Generated view differs from canonical source: {path.relative_to(root)}")
    if read_json(root / "generated/corpus.json") != read_json(root / "source/corpus.source.json"):
        raise ValueError("Generated corpus differs from frozen corpus source")
    report = manifest(root, cases, views)
    if read_json(root / "manifest.json") != report:
        raise ValueError("Manifest differs from canonical source or generated views")
    expected_validation = {"status": "passed", "manifest_sha256": digest(root / "manifest.json"), "case_count": len(cases)}
    if read_json(root / "validation.json") != expected_validation:
        raise ValueError("Validation report differs from manifest")
    return {"status": "passed", **report}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", "--root", dest="root", type=Path, default=ROOT)
    parser.add_argument("--build", action="store_true", help="Regenerate gold views only; never reset response/result files")
    args = parser.parse_args()
    import json
    print(json.dumps(build(args.root) if args.build else check(args.root), ensure_ascii=False, indent=2))
