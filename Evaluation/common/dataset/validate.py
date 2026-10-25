"""Read-only dataset validation entry point."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.dataset.build import check
from common.paths import DEFAULT_DATASET


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    print(json.dumps(check(args.dataset), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
