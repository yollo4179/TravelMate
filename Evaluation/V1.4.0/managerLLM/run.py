"""Dialogue/control/memory evaluation view of the same agent."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.runner import main

if __name__ == "__main__":
    main("managerLLM")
