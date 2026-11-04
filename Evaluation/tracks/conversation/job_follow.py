"""Follow the job a conversation turn queued until it ends, within the run's read cap and a fixed time limit."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any
import uuid

from common.execution.control import ExecutionSettings, Operation, RunControl, RunMode
from common.experiments.contracts import ModuleContext

TERMINAL_JOB_STATUSES = frozenset({"SUCCEEDED", "FAILED"})
OK = 200


class FollowedJobKind(StrEnum):
    RECOMMENDATION = "RECOMMENDATION"
    PLANNING = "PLANNING"


@dataclass(frozen=True)
class JobFollower:
    kind: FollowedJobKind
    response_type: str
    status_path: str
    wait_seconds: int
    poll_seconds: int
    plan_creation_only: bool
    # A finished planning job names its draft; the draft itself is the completed result, not the job receipt.
    result_path: str | None = None

    def supports(self, native_type: str | None, case: dict[str, Any]) -> bool:
        return native_type == self.response_type and (not self.plan_creation_only or bool(case.get("creates_plan")))


JOB_FOLLOWERS = (
    JobFollower(FollowedJobKind.RECOMMENDATION, "RECOMMENDATION_JOB", "/api/v1/recommendation-jobs/", 180, 2, False),
    # A plan job searched for 26 s and generated for 6 s in the first live run; 240 s leaves room without waiting forever.
    JobFollower(FollowedJobKind.PLANNING, "PLANNING_JOB", "/api/v1/planning-jobs/", 240, 3, True, "/api/v1/plans/"),
)


def select_follower(native: dict[str, Any], case: dict[str, Any]) -> JobFollower | None:
    matching = [follower for follower in JOB_FOLLOWERS if follower.supports(native.get("type"), case)]
    if len(matching) > 1:
        raise ValueError(f"More than one job follower supports {native.get('type')}")
    return matching[0] if matching else None


async def follow_job(
    record: dict[str, Any],
    case: dict[str, Any],
    context: ModuleContext,
    control: RunControl,
    settings: ExecutionSettings,
) -> dict[str, Any]:
    native = record.get("native_response")
    if settings.mode != RunMode.LIVE or not isinstance(native, dict):
        return record
    follower = select_follower(native, case)
    if follower is None:
        return record
    job_id = (native.get("data") or {}).get("jobId")
    if not job_id:
        return {**record, "followed_job": {"kind": follower.kind.value, "job": None, "result": None,
                                           "polls": 0, "wait_ms": 0.0, "timed_out": False}}
    case_id = case["case_id"]

    async def read(path: str) -> dict[str, Any] | None:
        request = {"method": "GET", "url": context.server_url + path}

        async def fetch() -> dict[str, Any]:
            response = await context.client.get(request["url"], headers={"Authorization": "Bearer " + context.access_token})
            return {"status_code": response.status_code, "raw_body": response.text}

        response = await control.execute(Operation.RUNTIME_READ, case_id, request, fetch)
        return json.loads(response["raw_body"]) if response["status_code"] == OK else None

    loop = asyncio.get_running_loop()
    started = loop.time()
    polls = 0
    job = None
    while loop.time() - started < follower.wait_seconds:
        job = await read(follower.status_path + str(uuid.UUID(job_id)))
        polls += 1
        if job is not None and job.get("status") in TERMINAL_JOB_STATUSES:
            break
        await asyncio.sleep(follower.poll_seconds)
    finished = job is not None and job.get("status") in TERMINAL_JOB_STATUSES
    result = None
    if follower.result_path and finished and job.get("status") == "SUCCEEDED" and job.get("planId") is not None:
        result = await read(follower.result_path + str(int(job["planId"])))
    return {**record, "followed_job": {"kind": follower.kind.value, "job": job, "result": result, "polls": polls,
                                       "wait_ms": round((loop.time() - started) * 1000, 1), "timed_out": not finished}}
