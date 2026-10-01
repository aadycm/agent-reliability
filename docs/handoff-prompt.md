# Handoff prompts (copy-paste)

Two prompts. One hands work to the other assistant; one takes it back. Nothing else needs saying -
`HANDOFF.md` carries the state.

---

## A. Starting the other assistant (paste into ChatGPT)

```
You are taking over a project from another AI assistant. The repo is on my desktop at
C:\Users\User\Desktop\agent-reliability

Do this first, before anything else:
1. Read HANDOFF.md in the repo root. It is machine-generated and current.
2. Read README.md for the design, results and limitations.
3. Set the "Holder" line in HANDOFF.md to "ChatGPT, since <today's date and time>".

Then work through the "Next steps" list in HANDOFF.md, in order.

Rules, which the previous assistant also followed:
- Never invent numbers. Every figure in the README or a report must come from a real run in runs/.
  If a run has not happened, say so instead of estimating.
- Benchmark runs are resumable. Rerun the same command and finished tasks are skipped. Never delete
  runs/ data to "start clean".
- Runs that end in api_error are infrastructure failures, excluded from success rates, retried on
  the next run. They are not agent failures.
- No AI attribution lines in commit messages. The repo is public.
- Never commit .env or any API key.
- Do not push to GitHub - I push myself.
- Windows: run Python as .\.venv\Scripts\python.exe

When you stop, or when you are near your usage limit:
1. Update the "Next steps" list in scripts/handoff.py to reflect what is actually left.
2. Run: .\.venv\Scripts\python.exe scripts/handoff.py
3. Set the Holder line back to "(nobody - free)".
4. Tell me in one line what is done and what is next.
```

---

## B. Taking it back (paste into Claude Code)

```
Read HANDOFF.md, then continue from the Next steps list. Check what actually changed on disk
(git log, git status, runs/) before trusting any claim about what was done.
```

---

## Why there is no fully automatic version

The two assistants have no channel between them: neither can start or message the other, and an
assistant cannot reliably predict its own cutoff - the warning arrives as the limit hits, and
sometimes the turn simply ends. Automating the handoff would mean running an agent loop against an
API and giving it file-write access, which is a bigger and riskier project than this one.

What is automated is the expensive part - keeping the state current, so resuming costs one paste and
no explaining. A Claude Code Stop hook (`.claude/settings.json`) regenerates `HANDOFF.md` every time
Claude stops.

## The one rule that matters

**Only one assistant works at a time**, and the Baton section of HANDOFF.md says who. Two agents
editing the same repo at once produces conflicting edits, duplicate benchmark runs (which burn the
same API quota twice), and a git history neither of them understands.
