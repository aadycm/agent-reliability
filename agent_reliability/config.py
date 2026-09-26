"""Configuration for the agent and the LLM backend.

Everything that changes agent behaviour lives in `AgentConfig`, and the config is
written into every trace, so a result can always be traced back to the exact settings
that produced it.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

from dotenv import load_dotenv

from . import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

# gemini-2.5-* models return 404 for new API users; 3.6-flash verified working with function calling.
DEFAULT_MODEL = "gemini-3.6-flash"


@dataclass
class RetryConfig:
    max_retries: int = 6          # attempts after the first failure
    base_delay: float = 2.0       # seconds; doubled each retry
    max_delay: float = 60.0       # cap on a single backoff sleep
    requests_per_minute: float = float(os.getenv("GEMINI_RPM", "10"))  # client-side throttle


@dataclass
class AgentConfig:
    model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    temperature: float = 0.0
    max_steps: int = 12           # max model calls inside the main loop (excludes reflection)
    # --- interventions (ablation toggles) ---
    self_check: bool = False      # verify the answer before finalizing
    max_self_checks: int = 1      # how many times self-check may intercept a final answer
    reflection: bool = False      # critique the plan before executing
    # --- stress conditions (degrade the environment, not the tasks; see stress.py) ---
    tool_failure_rate: float = 0.0   # chance each tool call returns a transient error
    degrade_search: bool = False     # search returns 1 truncated result instead of several
    stress_seed: int = 0             # makes the injected failures reproducible
    # --- robustness ---
    max_empty_response_nudges: int = 2
    retry: RetryConfig = field(default_factory=RetryConfig)

    @property
    def stress_name(self) -> str:
        parts = []
        if self.max_steps != AgentConfig.max_steps:
            parts.append(f"steps{self.max_steps}")
        if self.tool_failure_rate:
            parts.append(f"flaky{self.tool_failure_rate:g}")
        if self.degrade_search:
            parts.append("search1")
        return ",".join(parts)

    @property
    def condition_name(self) -> str:
        parts = []
        if self.reflection:
            parts.append("reflection")
        if self.self_check:
            parts.append("selfcheck")
        name = "+".join(parts) or "baseline"
        # Stress belongs in the condition name: otherwise a report could put a stressed run and a
        # normal run in the same column.
        return f"{name}[{self.stress_name}]" if self.stress_name else name

    def to_dict(self) -> dict:
        d = asdict(self)
        d["condition"] = self.condition_name
        return d


def get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Put it in a .env file at the project root "
            "(see .env.example) or export it in your shell."
        )
    return key
