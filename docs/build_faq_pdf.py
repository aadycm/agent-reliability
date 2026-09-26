# Builds the interview FAQ PDF. All numbers come from reports/gemma/summary.md (real runs).
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

OUT = str(__import__("pathlib").Path(__file__).with_name("agent-reliability-faq.pdf"))

INK = colors.HexColor("#0b0b0b")
INK2 = colors.HexColor("#52514e")
MUTED = colors.HexColor("#898781")
ACCENT = colors.HexColor("#2a78d6")
RULE = colors.HexColor("#e1e0d9")
BAND = colors.HexColor("#f4f4f1")

ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("title", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=22,
                            leading=26, textColor=INK, alignment=TA_LEFT, spaceAfter=4),
    "sub": ParagraphStyle("sub", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5,
                          leading=15, textColor=INK2, spaceAfter=10),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=13,
                         leading=16, textColor=INK, spaceBefore=14, spaceAfter=6),
    "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontName="Helvetica-Bold", fontSize=10,
                         leading=13, textColor=ACCENT, spaceBefore=10, spaceAfter=4),
    "q": ParagraphStyle("q", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=10.5,
                        leading=14, textColor=INK, spaceBefore=7, spaceAfter=2),
    "a": ParagraphStyle("a", parent=ss["Normal"], fontName="Helvetica", fontSize=10,
                        leading=14.5, textColor=INK2, spaceAfter=2, leftIndent=10),
    "body": ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica", fontSize=10,
                           leading=14.5, textColor=INK2, spaceAfter=5),
    "bullet": ParagraphStyle("bullet", parent=ss["Normal"], fontName="Helvetica", fontSize=10,
                             leading=14.5, textColor=INK2, leftIndent=12, bulletIndent=2, spaceAfter=3),
    "small": ParagraphStyle("small", parent=ss["Normal"], fontName="Helvetica", fontSize=8.5,
                            leading=11.5, textColor=MUTED),
}


def table(data, widths, align_right=()):
    t = Table(data, colWidths=widths, hAlign="LEFT")
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK2),
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]
    for c in align_right:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def qa(pairs):
    out = []
    for q, a in pairs:
        out.append(KeepTogether([Paragraph(q, S["q"]), Paragraph(a, S["a"])]))
    return out


story = []
story.append(Paragraph("agent-reliability: project FAQ", S["title"]))
story.append(Paragraph(
    "A tool-using LLM agent plus a framework for studying where it fails on multi-step tasks. "
    "Prepared as an interview and explanation aid. Every number here comes from real benchmark runs "
    "(Gemma 4 31B via the Gemini API, 12-13 September 2026); none are estimated.", S["sub"]))
story.append(Paragraph("github.com/aadycm/agent-reliability", S["small"]))

story.append(Paragraph("The 30-second summary", S["h2"]))
story.append(Paragraph(
    "I built an AI agent that solves multi-step problems by calling tools: a calculator, a sandboxed "
    "Python executor, a file reader and a search engine. Around it I built a framework to measure where "
    "such agents fail: 23 benchmark tasks with verified answers, full step-by-step traces, automatic "
    "failure classification, and on/off ablations of two common reliability techniques - reflection "
    "(plan before acting) and self-check (verify before answering). The study ran 92 real agent runs.",
    S["body"]))

story.append(Paragraph("Headline results", S["h2"]))
story.append(table([
    ["Condition", "Correct", "Model calls/task", "Tokens/task", "vs baseline", "Tool errors"],
    ["baseline", "23/23", "4.2", "6,331", "1.0x", "0"],
    ["self-check", "23/23", "5.3", "9,017", "1.4x", "0"],
    ["reflection", "23/23", "6.0", "14,090", "2.2x", "6 (in 5 tasks)"],
    ["reflection + self-check", "23/23", "7.0", "18,091", "2.9x", "5 (in 5 tasks)"],
], [42*mm, 17*mm, 26*mm, 21*mm, 20*mm, 28*mm], align_right=(1, 2, 3, 4)))
story.append(Spacer(1, 6))
story.append(Paragraph(
    "95% Wilson confidence interval for 23/23 is 85.7%-100%. 0 runs lost to API errors. "
    "Wall-clock time is dominated by rate-limit and retry waits, so cost is compared in tokens and model calls.",
    S["small"]))

story.append(Paragraph("The five findings", S["h2"]))
for i, (head, text) in enumerate([
    ("Ceiling effect: no failures to study.",
     "The agent solved every task in every condition, including the 5+ step tasks and the designed traps. "
     "The failure taxonomy had nothing to classify and the interventions had no room to improve accuracy. "
     "The honest conclusion is that this benchmark is too easy for this model."),
    ("Self-check cost tokens and changed nothing.",
     "Across 45 verification prompts the model re-submitted the same answer every time and never called a "
     "tool to re-verify. Cost: 1.4x baseline tokens."),
    ("Reflection made tool use worse without changing accuracy.",
     "In both reflection conditions the same 5 file-based tasks (T04, T08, T09, T10, T20) hit tool errors: "
     "planning before seeing any tool output, the model wrote Python that opened the CSV/log files directly, "
     "which the sandbox blocks. Without reflection it used the file-reader tool first, as intended. It "
     "recovered every time, but cost 2.2x baseline tokens. A plan written blind can pick the wrong mechanism."),
    ("The first self-check implementation silently failed - the most useful finding.",
     "Delivering the verification request as a text part beside the tool results produced empty model replies "
     "in 45 of 46 runs. Those runs still scored 23/23, because the loop nudged the model into re-submitting, "
     "so accuracy alone could never have revealed it. Only the traces did. Fixed by putting the request inside "
     "the final_answer tool result; reports now show 'self-checks answered / sent' so a skipped intervention "
     "is visible."),
    ("Minor format slips.",
     "2 of 92 runs answered in plain text instead of calling the final_answer tool. Both were graded correctly "
     "from their explicit final line. This also exposed a gap: self-check cannot trigger on plain-text answers."),
]):
    story.append(Paragraph(f"{i+1}. {head}", S["h3"]))
    story.append(Paragraph(text, S["body"]))

story.append(Paragraph("What the study does NOT show", S["h2"]))
for b in [
    "It does not show that reflection or self-check never help - only that they did not help on tasks this model already solves.",
    "23 tasks, one run per condition: a small sample with wide confidence intervals.",
    "One model, one prompt set. Results may not transfer to other models or prompt wordings.",
    "Tasks, grading rules and failure heuristics were written by the same author.",
    "Timing is not a fair efficiency measure because of API retries and throttling.",
]:
    story.append(Paragraph(b, S["bullet"], bulletText="\u2022"))

story.append(Spacer(1, 4))
story.append(Paragraph("How it works (the technical core)", S["h2"]))

story.append(Paragraph("The agent loop", S["h3"]))
story.append(Paragraph(
    "1. Send the task plus tool schemas to the model. &nbsp;2. The model replies with reasoning text and/or a "
    "structured function call, e.g. search(query=\"Veltrix Dynamics\"). &nbsp;3. The framework runs that tool and "
    "returns the result. &nbsp;4. Repeat until the model calls final_answer(...) or hits the 12-step limit. "
    "Runs can also end as step_limit, no_answer or api_error.", S["body"]))
for b in [
    "<b>Automatic function calling is off.</b> The SDK can run tools for you, but then individual steps cannot be "
    "logged or studied; running them in-framework is what makes the traces possible.",
    "<b>Tool errors are returned to the model</b> as {\"error\": ...} rather than crashing the run, so the agent can "
    "recover - and the evidence stays in the trace. All 11 tool errors in the study were recovered from.",
    "<b>A dedicated final_answer tool</b> yields a clean, gradable answer instead of parsing prose.",
    "<b>Interventions are hooks in the same loop:</b> reflection adds a tool-less planning call before execution; "
    "self-check intercepts the first final_answer and asks the model to verify it. The step limit is extended by "
    "the number of self-checks, so the ablation measures verification, not a smaller step budget.",
]:
    story.append(Paragraph(b, S["bullet"], bulletText="\u2022"))

story.append(Paragraph("Tools", S["h3"]))
story.append(table([
    ["Tool", "Purpose", "Engineering note"],
    ["calculator", "arithmetic", "AST walker, never eval()"],
    ["python_exec", "run a short program", "separate process, 10s timeout, blocked imports;\nnot a security boundary"],
    ["read_file / list_files", "read benchmark files", "path traversal rejected"],
    ["search", "mock knowledge base", "deterministic keyword scoring"],
], [34*mm, 40*mm, 80*mm]))
story.append(Spacer(1, 4))
story.append(Paragraph("New tools are registered with a decorator: a function, a description and a JSON schema.", S["small"]))

story.append(Paragraph("Benchmark design", S["h3"]))
for b in [
    "<b>23 tasks</b>: 10 easy (2 steps), 8 medium (3-4), 5 hard (5+ steps), where steps = tool calls in the canonical solution.",
    "<b>Fictional world</b> (invented companies, towns, people, currency): the model cannot know these facts from "
    "pretraining, so correct answers require real tool use and unsupported answers are detectably invented. This also "
    "rules out training-data contamination.",
    "<b>Deliberate traps</b>: two similarly named companies; an INFO log line containing the word ERROR; a recipe that "
    "serves 3 not 4; highest unit price versus highest total revenue.",
    "<b>Verified answers</b>: a test re-derives every answer with the real tools and checks that each declared "
    "intermediate value actually appears in the tool outputs.",
    "<b>Grading</b>: numeric tolerances; answers containing more than two numbers count as hedging and fail; "
    "whole-word matching so \"19\" does not satisfy \"9\"; free-text answers are graded on their final line.",
]:
    story.append(Paragraph(b, S["bullet"], bulletText="\u2022"))

story.append(Paragraph("Failure taxonomy (automatic, with manual override)", S["h3"]))
story.append(table([
    ["Category", "Primary heuristic signal"],
    ["infinite_loop", "step limit reached while repeating an identical call 3+ times"],
    ["gave_up_early", "no answer, or a refusal phrase such as \"cannot determine\""],
    ["hallucinated_tool_result", "answered without the information tools, or used a number no tool returned"],
    ["wrong_tool_choice", "a required tool never called while other tools were used"],
    ["bad_plan", "right tools but required information never retrieved, or correct facts combined with wrong logic"],
    ["execution_error", "near miss (<=2%), malformed answer, or unrecovered tool errors"],
], [46*mm, 108*mm]))
story.append(Spacer(1, 4))
story.append(Paragraph(
    "api_error is tracked separately as infrastructure, never as an agent failure. Manual labels override heuristics, "
    "and the report shows heuristic-vs-manual agreement.", S["small"]))

story.append(Paragraph("Reliability and statistics", S["h3"]))
for b in [
    "<b>Exponential backoff with jitter</b> on 429/5xx/timeouts, honouring the server's suggested retry delay, plus "
    "client-side rate limiting.",
    "<b>Daily-quota detection</b>: Google's per-day quota error still says \"retry in 30s\", so the code reads the quota "
    "id and stops the run cleanly instead of retrying all day.",
    "<b>Resumable runs</b>: each completed trace is written immediately, so an interrupted run continues where it stopped.",
    "<b>58 offline tests</b>, including a scripted fake LLM that exercises the loop, retries, self-check and failure "
    "heuristics with no API calls.",
    "<b>Wilson 95% intervals</b> (well behaved near 100%, unlike the normal approximation) and a <b>paired exact McNemar "
    "test</b> comparing conditions on the same tasks, counting only the tasks whose outcome flipped.",
]:
    story.append(Paragraph(b, S["bullet"], bulletText="\u2022"))

story.append(Spacer(1, 4))
story.append(Paragraph("Questions you may be asked, with answers", S["h2"]))

story.append(Paragraph("Basics", S["h3"]))
story.extend(qa([
    ("What is an AI agent, and how does it differ from a chatbot?",
     "A chatbot answers in a single reply. An agent runs in a loop: it chooses actions, calls tools, reads the results "
     "and continues until the task is done or a limit stops it."),
    ("What is function calling?",
     "You give the model a JSON schema for each tool; it returns structured calls with arguments instead of free text. "
     "Your code executes the tool and feeds the result back. It is far more reliable than parsing prose for commands."),
    ("Why Gemma rather than Gemini for the study?",
     "The Gemini Flash free tier allowed 20 requests per day and one condition needs roughly 100. Gemma 4 31B was free, "
     "supported function calling and is open-weights, which also helps reproducibility. The backend is one class, so "
     "switching models is a one-line change."),
]))

story.append(Paragraph("Design decisions", S["h3"]))
story.extend(qa([
    ("Why fictional data in the knowledge base?",
     "To prevent training-data contamination and to force genuine tool use. If the model answers without searching, the "
     "answer must be invented - which makes hallucination detectable rather than a judgement call."),
    ("Why not let the SDK call the tools automatically?",
     "Automatic function calling hides the individual steps. Running tools in the framework is what produces the traces "
     "the whole study depends on."),
    ("Why return tool errors to the model instead of failing the run?",
     "Real agents must recover from errors, and the failed call stays in the trace as evidence. Every tool error in the "
     "study was recovered from."),
    ("How do you know your benchmark answers are correct?",
     "A test re-derives all 23 answers using the real tools, and checks that each task's declared intermediate values "
     "appear in the tool outputs. No answer is hand-computed and unchecked."),
    ("How do you distinguish a bad plan from an execution error?",
     "Via the declared intermediates. If the needed facts were never retrieved, it is a bad plan; if they were retrieved "
     "and the final answer is still wrong, it is an execution error."),
    ("How can you detect a hallucinated tool result automatically?",
     "Two signals: an answer produced without ever calling the information tools, and numbers appearing in calculator or "
     "Python arguments that never appeared in any tool output or in the task text (ignoring small numbers and constants, "
     "and tolerating rounding)."),
]))

story.append(Paragraph("Results and statistics", S["h3"]))
story.extend(qa([
    ("Everything scored 100%. Is that a failed experiment?",
     "No. It is a valid, reportable result: the benchmark is too easy for this model. The study still produced real "
     "findings about intervention cost, reflection degrading tool use, and a silently broken intervention. The framework "
     "is ready for harder settings, which is the documented next step."),
    ("Why Wilson confidence intervals?",
     "The standard normal approximation gives a zero-width interval at 100%, which is misleading. Wilson gives "
     "85.7%-100% for 23/23 - honest about a small sample."),
    ("Why McNemar rather than comparing two percentages?",
     "The same tasks are run in both conditions, so the observations are paired. McNemar uses only the discordant pairs "
     "(tasks fixed or broken by the intervention), which is the correct test for paired binary outcomes."),
    ("So is reflection harmful?",
     "In this setting it cost 2.2x the tokens and introduced tool errors without improving accuracy. That does not "
     "generalise to harder tasks or other models, where planning may well help. The claim is scoped to what was measured."),
    ("How did you find the self-check bug?",
     "By reading the traces: self-check steps had been relabelled as nudges and had zero output tokens. Counting them gave "
     "45 of 46. Accuracy could not have revealed it, because it stayed at 100%."),
]))

story.append(Paragraph("Engineering", S["h3"]))
story.extend(qa([
    ("How did you handle rate limits and API failures?",
     "Client-side request spacing, exponential backoff with jitter, honouring server-suggested delays, distinguishing "
     "per-minute from per-day quotas, and resumable runs. Unrecoverable failures are recorded as api_error, excluded from "
     "success rates and retried on resume."),
    ("Is the Python sandbox secure?",
     "No, and the README says so plainly. It has an import/call blocklist, an isolated subprocess, a temp working "
     "directory, a 10s timeout, output truncation and POSIX resource limits. It protects against accidents, not a "
     "determined adversary; real isolation would need containers or a VM."),
    ("How do you test code that depends on an LLM?",
     "With a scripted backend that replays fixed responses, so the loop, retries, interventions and failure heuristics are "
     "tested deterministically and offline. 58 tests run with no API key."),
    ("What if the model answers in plain text instead of calling final_answer?",
     "The text is accepted but flagged as finish_mode=text_response and graded on its final line. It is a known gap: "
     "self-check cannot intercept that path. It happened in 2 of 92 runs."),
]))

story.append(Paragraph("Critical questions", S["h3"]))
story.extend(qa([
    ("Is 23 tasks not too small, and author-written?",
     "Yes on both counts, and both are listed as limitations. That is why confidence intervals and a paired test are "
     "reported rather than bare percentages, and why harder, more varied tasks are the stated next step."),
    ("What would you do differently next time?",
     "Pilot on a weaker model first to avoid the ceiling effect; verify that each intervention is actually delivered "
     "before running a full condition; use repeats at non-zero temperature to measure variance; and have a second "
     "annotator label failures to measure agreement."),
    ("How much of this did you build yourself?",
     "Answer honestly, including any AI assistance, then demonstrate understanding: walk through the loop, the trap tasks, "
     "and the self-check bug. Understanding the system is what the question is really testing."),
]))

story.append(Spacer(1, 10))
story.append(Paragraph(
    "Source: reports/gemma/summary.md and the raw per-task traces in runs/, both committed to the repository.", S["small"]))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20*mm, 12*mm, "agent-reliability - project FAQ")
    canvas.drawRightString(A4[0] - 20*mm, 12*mm, f"Page {doc.page}")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(20*mm, 15*mm, A4[0] - 20*mm, 15*mm)
    canvas.restoreState()


doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                      topMargin=18*mm, bottomMargin=20*mm,
                      title="agent-reliability: project FAQ", author="aadycm")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=footer)])
doc.build(story)
print("wrote", OUT)
