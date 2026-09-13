"""agent-reliability: a tool-using LLM agent and a framework for studying its failures."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = PROJECT_ROOT / "runs"

__version__ = "0.1.0"
