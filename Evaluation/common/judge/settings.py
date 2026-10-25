"""Explicit environment loading; evaluator credentials never enter run metadata."""
from __future__ import annotations
from dataclasses import dataclass, field
import os
from pathlib import Path
from common.dataset.io import read_json


@dataclass(frozen=True)
class JudgeSettings:
    model: str
    api_key: str = field(repr=False)

    @classmethod
    def load(cls, root: Path, env_file: Path | None) -> JudgeSettings:
        if env_file is not None:
            if not env_file.is_file():
                raise ValueError("The explicit --env-file does not exist")
            from dotenv import load_dotenv
            load_dotenv(env_file, override=False)
        config = read_json(root / "source/judge_config.json")
        model = os.getenv("RAGAS_JUDGE_MODEL", config["judge_model"]).strip()
        if not model:
            raise ValueError("Evaluator model name must not be empty")
        return cls(
            model=model,
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        )
