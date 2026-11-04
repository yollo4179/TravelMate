"""Human review is required for meaning; literal source matches do not prove a claim."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


REVIEW_FIELDS = ["case_id", "record_sha256", "events_sha256", "criterion", "guidance", "question", "response_text",
                 "final_text", "plan_draft", "job_status", "tool_results", "citations", "supplied_evidence",
                 "review_candidates", "verdict", "reviewer", "rationale"]


def _json(value: Any) -> str:
    return "" if value is None else json.dumps(value, ensure_ascii=False)


def export_review(path: Path, scores: list[dict[str, Any]]) -> None:
    """response_text is the first line; on the LiLi path the answer under review is final_text and plan_draft."""
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for score in scores:
            final_text = score.get("job_response_text") or score.get("draft_dialogue_text") or ""
            for criterion in score["semantic_criteria"]:
                writer.writerow({"case_id": score["case_id"], "record_sha256": score["record_sha256"],
                                 "events_sha256": score["events_sha256"], "criterion": criterion["id"],
                                 "guidance": criterion["guidance"], "question": score["question"],
                                 "response_text": score["response_text"], "final_text": final_text,
                                 "plan_draft": _json(score.get("plan_draft")), "job_status": _json(score.get("job_status")),
                                 "tool_results": _json(score.get("tool_results")),
                                 "citations": _json(score["citations"]), "supplied_evidence": _json(score["supplied_evidence"]),
                                 "review_candidates": _json(score.get("review_candidates")),
                                 "verdict": "", "reviewer": "", "rationale": ""})


def summarize(scores: list[dict[str, Any]], *, expected_count: int, review_path: Path | None = None) -> dict[str, Any]:
    review = {}
    if review_path is not None:
        with review_path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                key = (row["case_id"], row["criterion"])
                if key in review:
                    raise ValueError("Duplicate semantic review criterion")
                review[key] = row
    reviewed_pass = 0
    reviewed_fail = 0
    for score in scores:
        verdicts = []
        for criterion in score["semantic_criteria"]:
            row = review.get((score["case_id"], criterion["id"]))
            if row is None or not row.get("verdict"):
                verdicts.append(None)
                continue
            if row["record_sha256"] != score["record_sha256"] or row["events_sha256"] != score["events_sha256"]:
                raise ValueError("Semantic review is bound to different actual records or evidence")
            if row["verdict"] not in {"PASS", "FAIL"} or not row.get("reviewer", "").strip() or not row.get("rationale", "").strip():
                raise ValueError("A semantic verdict requires PASS/FAIL, reviewer and rationale")
            verdicts.append(row["verdict"] == "PASS")
        semantic = "failed" if False in verdicts else "not_reviewed" if None in verdicts else "passed"
        score["semantic_status"] = semantic
        reviewed_fail += semantic == "failed"
        reviewed_pass += semantic == "passed" and score["quality_observed"] and score["automated_status"] == "passed" and score.get("plan_content", {}).get("status", "not_applicable") not in {"not_ready", "not_assessed", "failed"}
    if review_path is not None:
        expected_keys = {(score["case_id"], criterion["id"]) for score in scores for criterion in score["semantic_criteria"]}
        if set(review) - expected_keys:
            raise ValueError("Review contains unselected cases or criteria")
    return {"selected_case_count": expected_count, "observed_case_count": len(scores),
            "automated_pass_count": sum(score["automated_status"] == "passed" for score in scores),
            "automated_fail_count": sum(score["automated_status"] == "failed" for score in scores),
            "semantic_fail_count": reviewed_fail, "quality_pass_count": reviewed_pass,
            "all_quality_passed": expected_count > 0 and len(scores) == expected_count and reviewed_pass == expected_count,
            "note": "MOCK, missing observations and unreviewed reasons are never quality passes"}
