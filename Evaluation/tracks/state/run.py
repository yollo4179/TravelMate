"""state evaluation entry point for recorded single-agent responses."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.runs.runner import main


if __name__ == "__main__":
    main("state")
