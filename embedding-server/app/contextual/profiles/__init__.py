"""Explicit, immutable identities for previously archived local request settings."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Any

from app.enrichment.contracts import fingerprint
from ..prompts import PromptVersion, resolve_prompt


class ExecutionProfileId(StrEnum):
    V1_LOCAL = "v1_local_2d365e87c12314cb"


PROFILE_DIGESTS = {
    ExecutionProfileId.V1_LOCAL: "2d365e87c12314cb64278e024c8d794438d6f0f65a136ed06794c3c11a34186f",
}


@dataclass(frozen=True)
class ExecutionProfile:
    profile_id: ExecutionProfileId
    original_prompt_version: PromptVersion
    request_settings: dict[str, Any]

    def settings_for(self, prompt_version: str) -> dict[str, Any]:
        prompt = resolve_prompt(prompt_version)
        settings = deepcopy(self.request_settings)
        # Preserve the exact local instructions when reading the original version.
        if prompt.version != self.original_prompt_version:
            settings["instructions"] = prompt.instructions
        return settings

    def validate_request(
        self,
        payload: dict[str, Any],
        canonical: dict[str, Any],
        prompt_version: str,
    ) -> None:
        settings = {key: value for key, value in payload.items() if key != "input"}
        if settings != self.settings_for(prompt_version):
            raise ValueError("Request differs from its registered execution profile")
        if not isinstance(payload.get("input"), str):
            raise ValueError("Profile input must be the preserved JSON string")
        if json.loads(payload["input"]) != json.loads(canonical["input"]):
            raise ValueError("Profile input differs from preserved sources, places or spans")
        for key in ("model", "preset"):
            if payload.get(key) != canonical.get(key):
                raise ValueError("Profile model selection differs from execution settings")


def resolve_execution_profile(profile_id: str) -> ExecutionProfile:
    try:
        identifier = ExecutionProfileId(profile_id)
    except ValueError as exception:
        raise ValueError("Unsupported contextual execution profile") from exception
    path = Path(__file__).with_name(f"{identifier.value}.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    digest = fingerprint(document["request_settings"])
    if (
        document["profile_id"] != identifier
        or digest != PROFILE_DIGESTS[identifier]
        or digest != document["request_settings_sha256"]
        or document["original_prompt_version"] != PromptVersion.V1
    ):
        raise ValueError("Registered execution profile identity changed")
    return ExecutionProfile(identifier, PromptVersion(document["original_prompt_version"]), document["request_settings"])
