"""Launch the normal embedding-server source with isolated evaluation connections."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
from common.dataset.io import read_json
from common.experiments.server import validate_environment
from common.paths import EVALUATION_ROOT


def search_environment(environment: dict[str, str]) -> tuple[dict[str, str], int]:
    validate_environment(environment)
    required = ("EVAL_EMBEDDING_DATABASE_URL", "EVAL_EMBEDDING_DEVICE", "EVAL_RERANKER_DEVICE")
    if any(not environment.get(key) for key in required):
        raise ValueError("Set an evaluation-only DATABASE_URL and explicit model devices")
    database = urlsplit(environment["EVAL_EMBEDDING_DATABASE_URL"])
    spring_database = urlsplit(environment["EVAL_DB_URL"][5:])
    if database.scheme not in {"postgresql", "postgres"} or (database.hostname, database.port or 5432, database.path) != (spring_database.hostname, spring_database.port or 5432, spring_database.path):
        raise ValueError("Evaluation Spring and search must target the same dedicated database")
    endpoint = urlsplit(environment["EVAL_EMBEDDING_SERVER_URL"])
    if endpoint.hostname not in {"127.0.0.1", "localhost"} or endpoint.scheme != "http" or not endpoint.port:
        raise ValueError("Launch the evaluation search process on an explicit loopback port")
    translations = {
        "DATABASE_URL": "EVAL_EMBEDDING_DATABASE_URL", "KAFKA_BOOTSTRAP_SERVERS": "EVAL_KAFKA_BOOTSTRAP_SERVERS",
        "MODEL_DEVICE_EMBEDDING": "EVAL_EMBEDDING_DEVICE", "MODEL_DEVICE_RERANKER": "EVAL_RERANKER_DEVICE",
        "RERANK_BATCH_SIZE": "EVAL_RERANKER_BATCH_SIZE", "CONTEXTUAL_RERANK_EVIDENCE_PER_PLACE": "EVAL_CONTEXTUAL_RERANK_EVIDENCE_PER_PLACE",
        "CONTEXTUAL_RELATION_RETRIEVAL": "EVAL_CONTEXTUAL_RELATION_RETRIEVAL", "PRESERVED_ORIGINAL_EVIDENCE": "EVAL_PRESERVED_ORIGINAL_EVIDENCE",
    }
    isolated = {key: value for key, value in environment.items() if not key.startswith(("KAFKA_", "CONTEXTUAL_", "DATABASE_", "MODEL_", "EMBEDDING_", "RERANK_", "RERANKER_", "PRESERVED_"))}
    isolated.update({target: environment[source] for target, source in translations.items() if source in environment})
    isolated.update({"KAFKA_PLACE_CHANGES_TOPIC": "travelmate.evaluation.place-changes.v1",
                     "KAFKA_RECOMMENDATION_REQUESTS_TOPIC": "travelmate.evaluation.recommendation-requests.v1",
                     "KAFKA_RECOMMENDATION_RESULTS_TOPIC": "travelmate.evaluation.recommendation-results.v1"})
    return isolated, endpoint.port


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-file", type=Path, required=True)
    parser.add_argument("--start", action="store_true")
    arguments = parser.parse_args()
    supplied = read_json(arguments.environment_file)
    if not isinstance(supplied, dict) or any(not key.startswith("EVAL_") or not isinstance(value, str) for key, value in supplied.items()):
        raise ValueError("Only EVAL_* string settings are supported")
    environment, port = search_environment({**os.environ, **supplied})
    print("Shared search source and isolated configured targets checked; models have not been loaded")
    if arguments.start:
        subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                       cwd=EVALUATION_ROOT.parent / "embedding-server", env=environment, check=True)


if __name__ == "__main__":
    main()
