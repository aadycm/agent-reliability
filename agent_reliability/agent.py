"""The tool-using agent loop.

How one run works
-----------------
                ┌───────────────────────────────────────────────────────────┐
  task ──► [optional REFLECTION: plan → critique → revised plan, no tools]  │
                │                                                           │
                ▼                                                           │
        ┌──► model.generate(history, tools) ──► response                   │
        │        │                                                          │
        │        ├─ empty / malformed ──► nudge ("continue") ───────────────┤
        │        ├─ function_call(s) to normal tools ──► run each tool,     │
        │        │      append function_response(s) to history ─────────────┘
        │        ├─ function_call final_answer(answer)
        │        │      ├─ [optional SELF-CHECK, once]: hold the answer back, ask the
        │        │      │   model to verify against tool outputs ──► loop again
        │        │      └─ otherwise ──► DONE (status=answered)
        │        └─ plain text, no call ──► DONE (answered, finish_mode=text_response)
        └── until max_steps ──► DONE (status=step_limit)
  any unrecoverable API error (after retries) ──► DONE (status=api_error)

Everything is recorded in a `Trace`: the model's text (its stated reasoning) at every
step, each tool call with args/output/error/timing, token usage, and retries.

Design choices worth knowing about
- We turn off the SDK's automatic function calling and run tools ourselves. That's what
  lets us log, count, and study every step.
- Tool failures never crash the loop. They go back to the model as {"error": ...}, which
  is realistic (agents must recover from errors) and leaves evidence for failure analysis.
- Finishing through a dedicated `final_answer` tool gives a clean string to grade, instead
  of parsing free text.
- A self-check adds one model call, so the step limit grows by the number of self-checks
  used. The ablation measures the intervention, not a smaller step budget.
"""

from __future__ import annotations

from typing import Callable

from . import prompts
from .config import AgentConfig
from .llm import DailyQuotaExhausted, GeminiBackend, LLMAPIError, LLMBackend
from .tools import DEFAULT_REGISTRY, ToolRegistry
from .trace import ToolCallRecord, Trace

Printer = Callable[[str], None]


def _preview(value, n: int = 300) -> str:
    s = str(value).replace("\n", " ⏎ ")
    return s if len(s) <= n else s[:n] + "…"


class Agent:
    def __init__(self, config: AgentConfig | None = None, tools: ToolRegistry | None = None,
                 backend: LLMBackend | None = None, verbose: bool = False, printer: Printer = print):
        self.config = config or AgentConfig()
        self.tools = tools or DEFAULT_REGISTRY
        if self.config.tool_failure_rate or self.config.degrade_search:
            from .stress import StressRegistry
            self.tools = StressRegistry(self.tools, self.config.tool_failure_rate,
                                        self.config.degrade_search, self.config.stress_seed)
        self.backend = backend or GeminiBackend(self.config.model, self.config.temperature, self.config.retry)
        self.verbose = verbose
        self._print = printer

    def _log(self, msg: str) -> None:
        if self.verbose:
            self._print(msg)

    # ------------------------------------------------------------------
    def run(self, task: str, task_id: str = "adhoc") -> Trace:
        cfg = self.config
        if hasattr(self.tools, "begin_run"):
            self.tools.begin_run(task_id)  # reproducible stress failures for this task
        trace = Trace(task_id=task_id, task=task, condition=cfg.condition_name,
                      config=cfg.to_dict(), model=getattr(self.backend, "model_name", cfg.model))
        declarations = self.tools.declarations() + [prompts.FINAL_ANSWER_DECLARATION]
        conv = self.backend.start(prompts.SYSTEM_PROMPT, declarations)
        self._log(f"\n=== Task [{task_id}] ({cfg.condition_name}) ===\n{task}")

        try:
            # ---- Intervention (b): reflection before executing ------------------
            if cfg.reflection:
                conv.add_user_text(prompts.REFLECTION_PROMPT.format(
                    task=task, tool_names=", ".join(self.tools.names())))
                r = conv.generate(use_tools=False)
                trace.reflection_plan = r.text
                trace.add_step("reflection", reasoning=r.text, usage=r.usage,
                               retries=r.retries, latency_s=r.latency_s)
                self._log(f"\n[reflection]\n{r.text}")
                conv.add_user_text(prompts.AFTER_REFLECTION)
            else:
                conv.add_user_text(f"Task: {task}")

            self_checks_used = 0
            nudges_used = 0
            model_steps = 0
            next_kind = "model"

            # ---- Main loop --------------------------------------------------------
            while model_steps < cfg.max_steps + self_checks_used:
                model_steps += 1
                r = conv.generate(use_tools=True)
                step = trace.add_step(next_kind, reasoning=r.text, usage=r.usage,
                                      retries=r.retries, latency_s=r.latency_s)
                if r.finish_reason not in ("STOP", "UNSPECIFIED"):
                    step.note = f"finish_reason={r.finish_reason}"
                next_kind = "model"
                self._log(f"\n[step {model_steps}] {step.kind}"
                          + (f"  ({step.note})" if step.note else "")
                          + (f"\n  thought: {_preview(r.text)}" if r.text else ""))

                # (1) Empty or malformed response: nudge the model a couple of times.
                if r.is_empty:
                    if nudges_used < cfg.max_empty_response_nudges:
                        nudges_used += 1
                        # Keep the step's kind (e.g. self_check). Overwriting it would hide an
                        # intervention the model silently ignored.
                        step.nudged = True
                        conv.add_user_text(prompts.NUDGE_EMPTY)
                        self._log("  (empty response → nudging)")
                        continue
                    trace.finish("no_answer", error=f"empty responses ({r.finish_reason})")
                    return trace

                final_calls = [fc for fc in r.function_calls if fc.name == "final_answer"]
                tool_calls = [fc for fc in r.function_calls if fc.name != "final_answer"]

                # (2) Run every ordinary tool call the model asked for in this turn
                #     (Gemini may request several calls in parallel).
                results: list[tuple[str, dict]] = []
                for fc in tool_calls:
                    res = self.tools.execute(fc.name, fc.args)
                    step.tool_calls.append(ToolCallRecord(
                        name=fc.name, args=fc.args, output=res.output, error=res.error,
                        duration_s=round(res.duration_s, 4)))
                    results.append((fc.name, res.to_model_payload()))
                    self._log(f"  → {fc.name}({_preview(fc.args, 200)})")
                    self._log(f"    ← {'ERROR: ' + res.error if res.error else _preview(res.output)}")

                # (3) The model wants to finish.
                if final_calls:
                    answer = str(final_calls[-1].args.get("answer", "")).strip()
                    step.proposed_answer = answer
                    self._log(f"  → final_answer({answer!r})")

                    # ---- Intervention (a): self-check before finalizing -----------
                    if cfg.self_check and self_checks_used < cfg.max_self_checks:
                        self_checks_used += 1
                        # The verification request is the final_answer tool's *result*. A separate text
                        # part next to function responses made Gemma 4 return empty replies (0 tokens),
                        # so the check never actually happened in the first study.
                        results.append(("final_answer", {
                            "status": "NOT ACCEPTED YET: verification required",
                            "instructions": prompts.SELF_CHECK_PROMPT.format(answer=answer, task=task),
                        }))
                        conv.add_tool_results(results)
                        next_kind = "self_check"
                        self._log("  (self-check: asking the model to verify before accepting)")
                        continue

                    trace.finish("answered", final_answer=answer, finish_mode="final_answer_tool")
                    self._log(f"\n=== DONE: {answer!r} ===")
                    return trace

                # (4) Tools were called: return results and let the model continue.
                if tool_calls:
                    conv.add_tool_results(results)
                    continue

                # (5) Plain text and no tool call: treat the text as the answer (flagged).
                trace.finish("answered", final_answer=r.text, finish_mode="text_response")
                self._log(f"\n=== DONE (text response): {_preview(r.text)} ===")
                return trace

            trace.finish("step_limit", error=f"reached max_steps={cfg.max_steps}")
            self._log(f"\n=== STOPPED: step limit ({cfg.max_steps}) ===")
            return trace

        except DailyQuotaExhausted:
            raise  # not a per-task outcome: the runner stops the whole benchmark
        except LLMAPIError as e:
            trace.finish("api_error", error=str(e))
            self._log(f"\n=== API ERROR: {e} ===")
            return trace
