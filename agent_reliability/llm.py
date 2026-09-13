"""LLM backends.

The agent talks to a small `LLMBackend` interface instead of to Gemini directly:

    backend.start(system_prompt, tool_declarations) -> Conversation
    conversation.add_user_text(text)
    conversation.add_tool_results([(name, payload), ...])
    conversation.generate(use_tools=True) -> LLMResponse(text, function_calls, ...)

This keeps all Gemini-specific details (protos, retries, rate limits, finish reasons)
in this file, and lets tests use `ScriptedBackend` (fully offline, deterministic) to
exercise the agent loop without an API key.
"""

from __future__ import annotations

import random
import re
import threading
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import RetryConfig, get_api_key


@dataclass
class FunctionCall:
    name: str
    args: dict


@dataclass
class LLMResponse:
    text: str = ""
    function_calls: list[FunctionCall] = field(default_factory=list)
    finish_reason: str = "STOP"
    usage: dict = field(default_factory=dict)
    retries: int = 0
    latency_s: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not self.text.strip() and not self.function_calls


class LLMAPIError(Exception):
    """Unrecoverable API failure (non-retryable error, or retries exhausted)."""


class DailyQuotaExhausted(LLMAPIError):
    """A per-day quota is used up. Retrying minutes later is pointless, so the benchmark
    runner stops the whole run instead of marking every remaining task as api_error."""


class Conversation(Protocol):
    def add_user_text(self, text: str) -> None: ...
    def add_tool_results(self, results: list[tuple[str, dict]], followup_text: str | None = None) -> None: ...
    def generate(self, use_tools: bool = True) -> LLMResponse: ...


class LLMBackend(Protocol):
    model_name: str
    def start(self, system_prompt: str, tool_declarations: list[dict]) -> Conversation: ...


# ---------------------------------------------------------------------------
# Rate limiting + retry
# ---------------------------------------------------------------------------

class RateLimiter:
    """Client-side throttle: at most `rpm` requests per minute (evenly spaced)."""

    def __init__(self, rpm: float) -> None:
        self.interval = 60.0 / rpm if rpm > 0 else 0.0
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
            self._next = max(now, self._next) + self.interval


def _is_retryable(exc: Exception) -> bool:
    try:
        from google.api_core import exceptions as gexc
        retryable = (gexc.TooManyRequests, gexc.ResourceExhausted, gexc.ServiceUnavailable,
                     gexc.InternalServerError, gexc.DeadlineExceeded, gexc.GatewayTimeout)
        if isinstance(exc, retryable):
            return True
    except ImportError:
        pass
    return isinstance(exc, (TimeoutError, ConnectionError))


def _server_retry_delay(exc: Exception) -> float | None:
    """429 errors from Gemini often say how long to wait ('retry_delay { seconds: 17 }')."""
    m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", str(exc)) or re.search(r"retry in ([\d.]+)s", str(exc))
    return float(m.group(1)) if m else None


def call_with_retries(fn, retry: RetryConfig, limiter: RateLimiter | None = None, sleep=time.sleep):
    """Run fn() with exponential backoff + jitter. Returns (result, n_retries)."""
    attempt = 0
    while True:
        if limiter:
            limiter.wait()
        try:
            return fn(), attempt
        except Exception as exc:  # noqa: BLE001
            # Google's 429 for a daily quota still says "retry in 30s"; the quota_id tells the truth.
            daily = re.findall(r'quota_id:\s*"([^"]*PerDay[^"]*)"', str(exc))
            if daily:
                limit = re.search(r"quota_value:\s*(\d+)", str(exc))
                raise DailyQuotaExhausted(
                    f"daily quota exhausted ({daily[0]}, limit {limit.group(1) if limit else '?'} requests/day). "
                    "It resets daily; use another model or a paid tier to continue now.") from exc
            if not _is_retryable(exc) or attempt >= retry.max_retries:
                raise LLMAPIError(f"{type(exc).__name__}: {exc}"[:1000]) from exc
            delay = min(retry.max_delay, retry.base_delay * 2 ** attempt)
            delay = delay * (0.5 + random.random())  # jitter: 0.5x..1.5x
            server = _server_retry_delay(exc)
            if server is not None:
                delay = max(delay, server + 1)
            attempt += 1
            quota = sorted(set(re.findall(r'quota_id:\s*"([^"]+)"', str(exc)) + re.findall(r'quota_metric:\s*"([^"]+)"', str(exc))))
            print(f"  [retry {attempt}/{retry.max_retries}] {type(exc).__name__}"
                  + (f" quota={','.join(quota)}" if quota else "") + f"; sleeping {delay:.1f}s")
            sleep(delay)


# ---------------------------------------------------------------------------
# Gemini backend (google-generativeai SDK)
# ---------------------------------------------------------------------------

def _to_plain(value: Any) -> Any:
    """Convert proto MapComposite/RepeatedComposite into plain dicts/lists."""
    if hasattr(value, "items"):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) or type(value).__name__ == "RepeatedComposite":
        return [_to_plain(v) for v in value]
    return value


def _jsonable(payload: dict) -> dict:
    """protobuf Struct only holds JSON types. Stringify anything else (e.g. tuples, sets)."""
    import json
    return json.loads(json.dumps(payload, default=str))


class GeminiConversation:
    def __init__(self, backend: "GeminiBackend", system_prompt: str, tool_declarations: list[dict]):
        genai = backend.genai
        self.backend = backend
        tools = [{"function_declarations": tool_declarations}] if tool_declarations else None
        common = dict(
            model_name=backend.model_name,
            system_instruction=system_prompt,
            generation_config=genai.GenerationConfig(temperature=backend.temperature),
        )
        self._model_tools = genai.GenerativeModel(tools=tools, **common)
        # Reflection turns must not call tools, so they use a tool-less model over the same history.
        self._model_plain = genai.GenerativeModel(**common)
        # Automatic function calling is OFF: the SDK only runs tools for you inside ChatSession
        # with enable_automatic_function_calling=True. We manage history ourselves instead.
        self.history: list[Any] = []

    def add_user_text(self, text: str) -> None:
        self.history.append({"role": "user", "parts": [{"text": text}]})

    def add_tool_results(self, results: list[tuple[str, dict]], followup_text: str | None = None) -> None:
        # Every function_call in the model turn needs a matching function_response. Any
        # follow-up instruction goes in the SAME user turn, to avoid two user turns in a row.
        protos = self.backend.genai.protos
        parts = [protos.Part(function_response=protos.FunctionResponse(name=name, response=_jsonable(payload)))
                 for name, payload in results]
        if followup_text:
            parts.append(protos.Part(text=followup_text))
        self.history.append(protos.Content(role="user", parts=parts))

    def generate(self, use_tools: bool = True) -> LLMResponse:
        model = self._model_tools if use_tools else self._model_plain
        t0 = time.perf_counter()
        raw, retries = call_with_retries(
            lambda: model.generate_content(self.history, request_options={"timeout": 120}),
            self.backend.retry, self.backend.limiter,
        )
        resp = LLMResponse(retries=retries, latency_s=round(time.perf_counter() - t0, 3))
        um = getattr(raw, "usage_metadata", None)
        if um is not None:
            resp.usage = {"prompt_tokens": um.prompt_token_count, "output_tokens": um.candidates_token_count}
        if not raw.candidates:
            fb = getattr(raw, "prompt_feedback", None)
            resp.finish_reason = f"NO_CANDIDATES({fb.block_reason.name if fb else 'unknown'})"
            return resp
        cand = raw.candidates[0]
        resp.finish_reason = cand.finish_reason.name if cand.finish_reason else "UNSPECIFIED"
        texts = []
        for part in cand.content.parts:
            if "function_call" in part:
                fc = part.function_call
                resp.function_calls.append(FunctionCall(name=fc.name, args=_to_plain(fc.args) or {}))
            elif "text" in part and part.text:
                texts.append(part.text)
        resp.text = "\n".join(texts).strip()
        # Append the model's own Content object unchanged (rather than rebuilding it), so
        # any fields the server attached are sent back as-is on the next turn.
        if cand.content.parts:
            self.history.append(cand.content)
        return resp


class GeminiBackend:
    def __init__(self, model_name: str, temperature: float = 0.0, retry: RetryConfig | None = None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)  # the SDK prints a deprecation notice
            import google.generativeai as genai
        genai.configure(api_key=get_api_key())
        self.genai = genai
        self.model_name = model_name
        self.temperature = temperature
        self.retry = retry or RetryConfig()
        self.limiter = RateLimiter(self.retry.requests_per_minute)

    def start(self, system_prompt: str, tool_declarations: list[dict]) -> GeminiConversation:
        return GeminiConversation(self, system_prompt, tool_declarations)


# ---------------------------------------------------------------------------
# Scripted backend for offline tests
# ---------------------------------------------------------------------------

class ScriptedConversation:
    def __init__(self, script: list[LLMResponse | Exception]):
        self._script = script
        self.history: list[tuple[str, Any]] = []

    def add_user_text(self, text: str) -> None:
        self.history.append(("user", text))

    def add_tool_results(self, results: list[tuple[str, dict]], followup_text: str | None = None) -> None:
        self.history.append(("tool", results))
        if followup_text:
            self.history.append(("user", followup_text))

    def generate(self, use_tools: bool = True) -> LLMResponse:
        if not self._script:
            raise LLMAPIError("script exhausted")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        self.history.append(("model", item))
        return item


class ScriptedBackend:
    """Replays a fixed list of responses. Used in tests to check loop logic offline."""

    model_name = "scripted"

    def __init__(self, script: list[LLMResponse | Exception]):
        self.script = list(script)
        self.conversation: ScriptedConversation | None = None

    def start(self, system_prompt: str, tool_declarations: list[dict]) -> ScriptedConversation:
        self.conversation = ScriptedConversation(self.script)
        return self.conversation
