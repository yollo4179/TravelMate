"""Check or launch the evaluation Spring process, using the shared source tree."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
from typing import Mapping
from urllib.parse import urlsplit

from common.dataset.io import read_json
from common.paths import EVALUATION_ROOT


def endpoint_identity(address: str, *, default_port: int) -> tuple[str, int]:
    parsed = urlsplit("//" + address.strip())
    host = (parsed.hostname or "").lower()
    host = "loopback" if host in {"localhost", "127.0.0.1", "::1"} else host
    return host, parsed.port or default_port


def isolated_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Do not let generic production property overrides take precedence over the test profile."""
    prefixes = ("SPRING_", "SERVER_", "OPENAI_", "OLLAMA_", "LLM_", "EMBEDDING_", "TRAVELMATE_", "JWT_", "OTEL_")
    return {**{name: value for name, value in environment.items() if not name.startswith(prefixes)},
            "SPRING_PROFILES_ACTIVE": "evaluation"}


def validate_environment(environment: Mapping[str, str]) -> None:
    required = ("EVAL_DB_URL", "EVAL_DB_USERNAME", "EVAL_DB_PASSWORD", "EVAL_JWT_SECRET",
                "EVAL_REDIS_HOST", "EVAL_REDIS_PORT", "EVAL_KAFKA_BOOTSTRAP_SERVERS",
                "EVAL_EMBEDDING_SERVER_URL", "EVAL_LLM_PROVIDER", "EVAL_OBSERVATION_DIRECTORY",
                "EVAL_PRODUCTION_DB_URL", "EVAL_PRODUCTION_REDIS_ADDRESS", "EVAL_PRODUCTION_KAFKA_SERVERS",
                "EVAL_PRODUCTION_SERVER_PORT", "EVAL_PRODUCTION_EMBEDDING_URL")
    if any(not environment.get(name, "").strip() for name in required):
        missing = [name for name in required if not environment.get(name, "").strip()]
        raise ValueError("Missing evaluation environment variable names: " + ", ".join(missing))
    comparisons = (
        (environment["EVAL_DB_URL"], environment["EVAL_PRODUCTION_DB_URL"]),
        (environment["EVAL_REDIS_HOST"] + ":" + environment["EVAL_REDIS_PORT"], environment["EVAL_PRODUCTION_REDIS_ADDRESS"]),
        (environment["EVAL_KAFKA_BOOTSTRAP_SERVERS"], environment["EVAL_PRODUCTION_KAFKA_SERVERS"]),
        (environment.get("EVAL_SERVER_PORT", "18080"), environment["EVAL_PRODUCTION_SERVER_PORT"]),
        (environment["EVAL_EMBEDDING_SERVER_URL"].rstrip("/"), environment["EVAL_PRODUCTION_EMBEDDING_URL"].rstrip("/")),
    )
    if any(evaluation == production for evaluation, production in comparisons):
        raise ValueError("Evaluation DB, Redis, Kafka, server port and search endpoint must be separate from production")
    if endpoint_identity(environment["EVAL_REDIS_HOST"] + ":" + environment["EVAL_REDIS_PORT"], default_port=6379) == endpoint_identity(environment["EVAL_PRODUCTION_REDIS_ADDRESS"], default_port=6379):
        raise ValueError("Redis hostname aliases still refer to the same service")
    evaluation_brokers = {endpoint_identity(value, default_port=9092) for value in environment["EVAL_KAFKA_BOOTSTRAP_SERVERS"].split(",")}
    production_brokers = {endpoint_identity(value, default_port=9092) for value in environment["EVAL_PRODUCTION_KAFKA_SERVERS"].split(",")}
    if evaluation_brokers & production_brokers:
        raise ValueError("Evaluation and production Kafka brokers must not overlap")
    database = environment["EVAL_DB_URL"]
    if not database.startswith("jdbc:postgresql://") or not urlsplit(database[5:]).path.endswith("_evaluation"):
        raise ValueError("Use a dedicated PostgreSQL database name ending in _evaluation")
    if len(environment["EVAL_JWT_SECRET"].encode("utf-8")) < 32:
        raise ValueError("Evaluation JWT secret must be at least 32 bytes")
    if environment["EVAL_LLM_PROVIDER"] not in {"OPENAI", "QWEN"}:
        raise ValueError("Select the existing OPENAI or QWEN implementation")
    if not 1024 <= int(environment.get("EVAL_SERVER_PORT", "18080")) <= 65535:
        raise ValueError("Invalid evaluation server port")
    if environment["EVAL_LLM_PROVIDER"] == "OPENAI":
        policy_path = Path(environment.get("EVAL_OPENAI_BUDGET_FILE", ""))
        policy = read_json(policy_path)
        ledger = (policy_path.resolve().parent / policy["ledgerFile"]).resolve()
        if not ledger.is_relative_to(policy_path.resolve().parent) or ledger == policy_path.resolve() or ledger.exists():
            raise ValueError("Budget needs a new ledger inside the policy directory; never delete an old ledger")
        if policy.get("model") != environment.get("EVAL_OPENAI_MODEL"):
            raise ValueError("Evaluation model differs from its budget policy")
    # Command-line or JSON overrides could silently undo profile separation.
    if environment.get("SPRING_APPLICATION_JSON") or environment.get("JAVA_TOOL_OPTIONS") or environment.get("JDK_JAVA_OPTIONS"):
        raise ValueError("Remove implicit JVM/Spring overrides before launching the evaluation server")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-file", type=Path, help="Explicit UTF-8 JSON containing EVAL_* values; never archived by the runner")
    parser.add_argument("--start", action="store_true", help="Explicitly build/run the separate evaluation process in the foreground")
    arguments = parser.parse_args()
    environment = dict(os.environ)
    if arguments.environment_file is not None:
        supplied = read_json(arguments.environment_file)
        if not isinstance(supplied, dict) or any(not name.startswith("EVAL_") or not isinstance(value, str) for name, value in supplied.items()):
            raise ValueError("The explicit environment file accepts EVAL_* string settings only")
        environment.update(supplied)
    validate_environment(environment)
    print("Evaluation profile and separate configured targets checked; no connection or model call performed")
    if not arguments.start:
        return
    server = EVALUATION_ROOT.parent / "Server/TravelMate"
    # The repository tracks gradlew as 100644; Unix launch must not rely on chmod outside Git.
    wrapper = ["gradlew.bat"] if os.name == "nt" else ["bash", "./gradlew"]
    environment = isolated_environment(environment)
    subprocess.run([*wrapper, "bootRun", "--args=--spring.profiles.active=evaluation"], cwd=server, env=environment, check=True)


if __name__ == "__main__":
    main()
