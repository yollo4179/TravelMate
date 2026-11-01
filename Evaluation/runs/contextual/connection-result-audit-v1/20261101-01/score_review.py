"""수동 의미 판정표와 저장 순위만으로 같은 정답표의 지표를 계산한다."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import IntEnum, StrEnum
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from Evaluation.common.metrics.ranking import ranking_metrics


class RelevanceGrade(IntEnum):
    UNSUPPORTED = 0
    ROUTE_ONLY = 1
    SUPPORTED = 2


class ConnectionStatus(StrEnum):
    POSITIVE = "positive-connection"
    BLOCKED = "blocked-route"
    ABSENT = "no-connection-evidence"


class TravelMode(StrEnum):
    VEHICLE = "vehicle-only"
    WALKING = "walking"
    STAIRS = "walking-stairs"
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class ReviewedGroup:
    group_id: str
    match_quote: str
    grade: RelevanceGrade
    status: ConnectionStatus
    travel_mode: TravelMode
    rationale: str

    def is_applicable(self, packet: dict[str, Any]) -> bool:
        quotations = [packet["raw_quote"], *(relation["evidence"]["quote"] for relation in packet["relations"])]
        return self.match_quote in quotations


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assign_judgments(
    packets: list[dict[str, Any]],
    groups: list[ReviewedGroup],
) -> dict[str, dict[str, Any]]:
    judgments = {}
    for packet in packets:
        applicable = [group for group in groups if group.is_applicable(packet)]
        if len(applicable) != 1:
            raise ValueError("각 패킷은 정확히 하나의 검수된 의미 판정에 속해야 합니다")
        group, = applicable
        judgments[packet["evidence_key"]] = {
            "evidence_key": packet["evidence_key"],
            "chunk_id": packet["chunk_id"],
            "context_version": packet["context_version"],
            "group_id": group.group_id,
            "grade": group.grade,
            "status": group.status,
            "travel_mode": group.travel_mode,
            "rationale": group.rationale,
        }
    return judgments


def main() -> None:
    output = Path(__file__).resolve().parent
    packets = json.loads((output / "evidence-packets.json").read_text(encoding="utf-8"))
    saved_rows = json.loads((output / "saved-rows.json").read_text(encoding="utf-8"))
    review = json.loads((output / "reviewed-groups.json").read_text(encoding="utf-8"))
    groups = [
        ReviewedGroup(
            group_id=group["group_id"],
            match_quote=group["match_quote"],
            grade=RelevanceGrade(group["grade"]),
            status=ConnectionStatus(group["status"]),
            travel_mode=TravelMode(group["travel_mode"]),
            rationale=group["rationale"],
        )
        for group in review["groups"]
    ]
    judgments = assign_judgments(packets, groups)
    by_phase: dict[str, list[dict[str, Any]]] = defaultdict(list)
    place_grades: dict[int, int] = defaultdict(int)
    for row in saved_rows:
        selected = [judgments[key] for key in row["evidence_keys"]]
        representative = judgments[row["representative_evidence_key"]]
        supplied_grade = max(judgment["grade"] for judgment in selected)
        place_grades[row["place_id"]] = max(place_grades[row["place_id"]], supplied_grade)
        by_phase[row["phase"]].append({
            **row,
            "representative_grade": representative["grade"],
            "representative_status": representative["status"],
            "representative_group": representative["group_id"],
            "representative_travel_mode": representative["travel_mode"],
            "returned_evidence_grade": supplied_grade,
        })
    relevant = {place_id for place_id, grade in place_grades.items() if grade >= RelevanceGrade.SUPPORTED}
    summaries = {}
    for phase, rows in by_phase.items():
        rows.sort(key=lambda row: row["rank"])
        identifiers = [row["place_id"] for row in rows]
        if len(identifiers) != len(set(identifiers)) or [row["rank"] for row in rows] != list(range(1, len(rows) + 1)):
            raise ValueError("순위가 연속적이고 장소 후보가 유일해야 합니다")
        a_rank = next(row["rank"] for row in rows if row["place_id"] == 101)
        ahead = [row for row in rows if row["rank"] < a_rank]
        summaries[phase] = {
            "pooled_place_metrics": ranking_metrics(identifiers, dict(place_grades)),
            "pooled_precision_at_20": len(set(identifiers[:20]) & relevant) / 20,
            "pooled_recall_at_30": len(set(identifiers[:30]) & relevant) / len(relevant),
            "representative_supported_at_20": sum(row["representative_grade"] >= RelevanceGrade.SUPPORTED for row in rows[:20]) / 20,
            "representative_supported_count": sum(row["representative_grade"] >= RelevanceGrade.SUPPORTED for row in rows),
            "returned_evidence_supported_count": sum(row["returned_evidence_grade"] >= RelevanceGrade.SUPPORTED for row in rows),
            "representative_status_counts": dict(Counter(row["representative_status"] for row in rows)),
            "a_rank": a_rank,
            "ahead_of_a_count": len(ahead),
            "ahead_of_a_supported_count": sum(row["representative_grade"] >= RelevanceGrade.SUPPORTED for row in ahead),
            "ahead_of_a_group_counts": dict(Counter(row["representative_group"] for row in ahead)),
            "audited_row_count": len(rows),
            "serialized_direction_or_restriction_distortions": sum(not row["direction_and_restrictions_preserved"] for row in rows),
        }
    result = {
        "reviewed_commit": "b35afbab",
        "pool_places": len(place_grades),
        "pool_relevant_places": len(relevant),
        "pool_qrels": {str(place_id): grade for place_id, grade in sorted(place_grades.items())},
        "evidence_group_counts": dict(Counter(judgment["group_id"] for judgment in judgments.values())),
        "phases": summaries,
        "reviewer": review["reviewer"],
        "blind": review["blind"],
        "new_searches": 0,
        "new_model_calls": 0,
        "production_database_writes": 0,
    }
    write_json(output / "judgments.json", list(judgments.values()))
    write_json(output / "row-judgments.json", [row for rows in by_phase.values() for row in rows])
    write_json(output / "metrics.json", result)
    table = ["# 저장 결과 60행의 원문 근거 판정", "", "등급: 2=긍정 연결 근거, 1=차단 경로 언급만 있음, 0=선택 근거에 연결 내용 없음.", "", "대표/전체는 대표 description의 근거 등급과 실제 전달된 근거 집합의 최고 등급이다. 원문은 evidence-packets.json의 해당 chunk_id로 대조할 수 있다.", ""]
    packet_by_key = {packet["evidence_key"]: packet for packet in packets}
    for phase, rows in by_phase.items():
        table.extend([f"**{phase}**", "", "| 순위 | 장소 ID | 대표/전체 등급 | 이동수단 | 원문에 명시된 방향 | 원문 제한 | 대표 chunk_id |", "|---:|---:|---|---|---|---|---|"])
        for row in rows:
            packet = packet_by_key[row["representative_evidence_key"]]
            directions = "; ".join(
                relation["origin"]["name"] + " → " + relation["destination"]["name"]
                for relation in packet["relations"]
            ) or "연결 미기재"
            conditions = "; ".join(
                condition["quote"] for relation in packet["relations"] for condition in relation["conditions"]
            ) or "명시 없음"
            table.append(f"| {row['rank']} | {row['place_id']} | {row['representative_grade']}/{row['returned_evidence_grade']} | {row['representative_travel_mode']} | {directions} | {conditions} | {packet['chunk_id']} |")
        table.append("")
    (output / "review-table.md").write_text("\n".join(table), encoding="utf-8")
    tracked = ["rubric.json", "reviewed-groups.json", "evidence-packets.json", "saved-rows.json", "judgments.json", "row-judgments.json", "metrics.json", "provenance.json", "prepare_evidence.py", "score_review.py", "review-table.md", "REPORT.md"]
    write_json(output / "publication.json", {
        "evaluated_commit": "b35afbab",
        "file_sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in tracked},
        "metric_implementation": "Evaluation/common/metrics/ranking.py",
        "metric_implementation_sha256": hashlib.sha256((ROOT / "Evaluation/common/metrics/ranking.py").read_bytes()).hexdigest(),
        "lf_normalized_sha256": {name: hashlib.sha256((output / name).read_text(encoding="utf-8").encode("utf-8")).hexdigest() for name in tracked},
        "hash_basis": "file_sha256는 실행 당시 로컬 바이트 기준. lf_normalized_sha256는 CRLF를 LF로 정규화한 UTF-8 텍스트 기준.",
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
