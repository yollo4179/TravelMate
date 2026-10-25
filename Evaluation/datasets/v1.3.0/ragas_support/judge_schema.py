"""Structured output for the existing 0–3 relevance rubric."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JudgeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_place_id: str
    field: Literal["name", "description", "region", "city", "category", "source_category"]
    quote: str = Field(min_length=1)


class PlaceJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place_id: str
    score: int = Field(strict=True, ge=0, le=3)
    reason: str = Field(min_length=1)
    evidence: list[JudgeEvidence] = Field(min_length=1)
    missing_requirements: list[str]


class PlaceJudgmentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judgments: list[PlaceJudgment]
