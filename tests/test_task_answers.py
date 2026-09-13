"""Re-derive every benchmark answer with the real tools, so the 'known answers' are
verified rather than hand-computed. For each task this also checks that the declared
intermediates really appear in the tool outputs of the reference solution."""

import csv
import io
import re
from collections import Counter

import pytest

from agent_reliability.benchmark import grade, load_tasks
from agent_reliability.tools import DEFAULT_REGISTRY as REG

TASKS = {t.id: t for t in load_tasks()}


class Recorder:
    def __init__(self):
        self.outputs = []

    def __call__(self, name, **args):
        res = REG.execute(name, args)
        assert res.error is None, res.error
        self.outputs.append(str(res.output))
        return res.output

    def kb(self, query, title):
        hits = self("search", query=query, top_k=5)
        doc = next(h for h in hits if h["title"] == title)
        return doc["snippet"]


def num_after(pattern, text):
    m = re.search(pattern, text)
    assert m, (pattern, text)
    return float(m.group(1).replace(",", ""))


def solve(task_id, r: Recorder):
    if task_id == "T01_rev_per_employee":
        s = r.kb("Veltrix Dynamics revenue employees", "Veltrix Dynamics")
        return round(r("calculator", expression=f"{num_after(r'revenue: ([\d.]+) million', s)}e6 / {num_after(r'Employees \(2023\): ([\d,]+)', s)}"))
    if task_id == "T02_founding_gap":
        v = r.kb("Veltrix Dynamics", "Veltrix Dynamics"); q = r.kb("Quorra Biotech", "Quorra Biotech")
        return num_after(r"founded in (\d{4})", q) - num_after(r"founded in (\d{4})", v)
    if task_id == "T03_province_density":
        s = r.kb("Varnholt province", "Varnholt province")
        return round(r("calculator", expression=f"{num_after(r'population of ([\d,]+)', s)} / {num_after(r'covering ([\d,]+)', s)}"), 1)
    if task_id == "T04_north_units":
        rows = list(csv.DictReader(io.StringIO(r("read_file", path="sales_q3.csv"))))
        return sum(int(x["units"]) for x in rows if x["region"] == "North")
    if task_id == "T05_train_time":
        s = r.kb("Brightwater Rail", "Brightwater Rail")
        return round(num_after(r"Length: (\d+)", s) / num_after(r"speed: (\d+)", s), 2)
    if task_id == "T06_founder_age":
        v = r.kb("Veltrix Dynamics founder", "Veltrix Dynamics"); m = r.kb("Mira Osterfeld", "Mira Osterfeld")
        return num_after(r"founded in (\d{4})", v) - num_after(r"born (\d{4})", m)
    if task_id == "T07_combined_hq_population":
        r.kb("Veltrix Dynamics", "Veltrix Dynamics"); r.kb("Quorra Biotech", "Quorra Biotech")
        hp = r.kb("Harlow Pike", "Harlow Pike"); lb = r.kb("Lindell Bay", "Lindell Bay")
        return num_after(r"census\): ([\d,]+)", hp) + num_after(r"census\): ([\d,]+)", lb)
    if task_id in ("T08_top_product", "T20_south_revenue_ratio"):
        rows = list(csv.DictReader(io.StringIO(r("read_file", path="sales_q3.csv"))))
        if task_id == "T08_top_product":
            rev = Counter()
            for x in rows:
                rev[x["product"]] += int(x["units"]) * int(x["unit_price_ekr"])
            return rev.most_common(1)[0][0]
        south_ekr = sum(int(x["units"]) * int(x["unit_price_ekr"]) for x in rows if x["region"] == "South")
        rate = num_after(r"1 EKR = ([\d.]+)", r.kb("Estmark crown exchange rate", "Estmark crown (EKR) exchange rate"))
        v = r.kb("Veltrix Dynamics revenue", "Veltrix Dynamics")
        rpe = num_after(r"revenue: ([\d.]+) million", v) * 1e6 / num_after(r"Employees \(2023\): ([\d,]+)", v)
        return round(south_ekr * rate / rpe, 2)
    if task_id == "T09_avg_eng_salary":
        rows = list(csv.DictReader(io.StringIO(r("read_file", path="employees.csv"))))
        sal = [int(x["salary_usd"]) for x in rows if x["department"] == "Engineering"]
        return round(sum(sal) / len(sal))
    if task_id == "T10_log_errors":
        lines = r("read_file", path="server.log").splitlines()
        errs = [ln.split()[3] for ln in lines if ln.split()[2] == "ERROR"]
        return f"{len(errs)}, {Counter(errs).most_common(1)[0][0]}"
    if task_id == "T11_memo_leader_birthplace":
        memo = r("read_file", path="memo_2024.txt")
        assert "CEO of Quorra Biotech" in memo.replace("\n", " ")
        q = r.kb("Quorra Biotech CEO", "Quorra Biotech")
        ceo = re.search(r"CEO: ([A-Z]\w+ [A-Z]\w+)", q).group(1)
        return re.search(r"born \d{4} in ([A-Z]\w+ [A-Z]\w+)", r.kb(ceo, ceo)).group(1)
    if task_id == "T12_kestrel_usd":
        k = r.kb("Kestrel-9 price", "Kestrel-9 drone")
        rate = num_after(r"1 EKR = ([\d.]+)", r.kb("Estmark crown exchange rate", "Estmark crown (EKR) exchange rate"))
        return r("calculator", expression=f"{num_after(r'List price: ([\d,]+)', k)} * {rate}")
    if task_id == "T13_orin_cup_estmark":
        cup = r.kb("Orin Cup winners", "Orin Cup")
        winners = re.findall(r"(\d{4}) ([A-Z]\w+ [A-Z]\w+) \w+", cup)
        count = 0
        for _, town in winners:
            if "Estmark province" in r.kb(town, town):
                count += 1
        return count
    if task_id == "T14_recipe_scaling":
        recipe = r("read_file", path="recipe.txt")
        rows = list(csv.DictReader(io.StringIO(r("read_file", path="employees.csv"))))
        people = sum(1 for x in rows if int(x["start_year"]) < 2015)
        return num_after(r"(\d+) g flour", recipe) / num_after(r"Serves (\d+)", recipe) * people
    if task_id == "T15_fib_mod_elevation":
        elev = int(num_after(r"Elevation: (\d+) m", r.kb("Carrow Falls", "Carrow Falls")))
        out = r("python_exec", code=f"a,b=1,1\nfor _ in range(28): a,b=b,a+b\nprint(b % {elev})")
        return int(out.strip())
    if task_id == "T16_rev_per_employee_gap":
        n = r.kb("Nimbic Foods", "Nimbic Foods"); q = r.kb("Quorra Biotech", "Quorra Biotech")
        n_rpe = num_after(r"revenue: ([\d.]+) billion", n) * 1e9 / num_after(r"Employees \(2023\): ([\d,]+)", n)
        q_rpe = num_after(r"revenue: ([\d.]+) million", q) * 1e6 / num_after(r"Employees \(2023\): ([\d,]+)", q)
        return round(abs(n_rpe - q_rpe))
    if task_id == "T17_lantern_budget_per_engineer":
        memo = r("read_file", path="memo_2024.txt")
        rate = num_after(r"1 EKR = ([\d.]+)", r.kb("Estmark crown exchange rate", "Estmark crown (EKR) exchange rate"))
        rows = list(csv.DictReader(io.StringIO(r("read_file", path="employees.csv"))))
        eng = sum(1 for x in rows if x["department"] == "Engineering")
        return round(num_after(r"phase one is ([\d,]+)", memo) * rate / eng)
    if task_id == "T18_highest_hq":
        best = None
        for company in ("Veltrix Dynamics", "Quorra Biotech", "Nimbic Foods"):
            town = re.search(r"Headquarters: ([A-Z]\w+ [A-Z]\w+)", r.kb(company, company)).group(1)
            elev = num_after(r"Elevation: (\d+) m", r.kb(town, town))
            if best is None or elev > best[1]:
                best = (company, elev)
        return f"{best[0]}, {int(best[1])}"
    if task_id == "T19_round_trips":
        q = r.kb("Quorra Biotech CEO", "Quorra Biotech")
        ceo = re.search(r"CEO: ([A-Z]\w+ [A-Z]\w+)", q).group(1)
        assert "Harlow Pike" in r.kb(ceo, ceo)
        return num_after(r"Length: (\d+)", r.kb("Brightwater Rail", "Brightwater Rail")) * 4
    if task_id == "T21_birth_year_sum":
        total = 0
        for company, role in (("Veltrix Dynamics", r"founded in \d{4} by ([A-Z]\w+ [A-Z]\w+)"),
                              ("Quorra Biotech", r"CEO: ([A-Z]\w+ [A-Z]\w+)"),
                              ("Nimbic Foods", r"CEO: ([A-Z]\w+ [A-Z]\w+)")):
            person = re.search(role, r.kb(company, company)).group(1)
            total += num_after(r"born (\d{4})", r.kb(person, person))
        return total - num_after(r"founded in (\d{4})", r.kb("Nimbic Foods", "Nimbic Foods"))
    if task_id == "T22_veltrix_confusion":
        v = r.kb("Veltrix Dynamics", "Veltrix Dynamics"); vr = r.kb("Veltrix Robotics", "Veltrix Robotics")
        return num_after(r"[Ff]ounded in (\d{4})", vr) - num_after(r"founded in (\d{4})", v)
    if task_id == "T23_lantern_total_usd":
        memo = r("read_file", path="memo_2024.txt")
        rate = num_after(r"1 EKR = ([\d.]+)", r.kb("Estmark crown exchange rate", "Estmark crown (EKR) exchange rate"))
        p1 = num_after(r"phase one is ([\d,]+)", memo)
        pct = num_after(r"(\d+)% more", memo)
        return round((p1 + p1 * (1 + pct / 100)) * rate)
    raise KeyError(f"no reference solution for {task_id}")


@pytest.mark.parametrize("task_id", sorted(TASKS))
def test_reference_solution_matches_known_answer(task_id):
    task = TASKS[task_id]
    r = Recorder()
    derived = solve(task_id, r)
    ok, why = grade(task, str(derived))
    assert ok, f"{task_id}: derived {derived!r} vs known {task.answer!r} ({why})"
    joined = re.sub(r"(?<=\d),(?=\d)", "", " ".join(r.outputs).replace("\n", " "))
    for inter in task.intermediates:
        assert re.sub(r"(?<=\d),(?=\d)", "", inter) in joined, f"{task_id}: intermediate {inter!r} not in tool outputs"


def test_task_count_and_difficulty_spread():
    assert 15 <= len(TASKS) <= 25
    buckets = Counter(t.difficulty for t in TASKS.values())
    assert all(buckets[b] >= 4 for b in buckets) and len(buckets) == 3


def test_grader_edge_cases():
    t = t01 = TASKS["T01_rev_per_employee"]
    assert grade(t, "$191,628")[0]
    assert grade(t, "191628 USD")[0]
    assert not grade(t, "191,627.9 or 191,628 or 191,629")[0]  # hedging across many numbers
    assert not grade(t, "I could not determine this")[0]
    t10 = TASKS["T10_log_errors"]
    assert grade(t10, "9, E502")[0] and not grade(t10, "10, E502")[0] and not grade(t10, "19, E502")[0]
    t18 = TASKS["T18_highest_hq"]
    assert grade(t18, "Nimbic Foods, 540 m")[0] and not grade(t18, "Veltrix Dynamics, 540")[0]
    assert grade(t18, "Nimbic Foods, 540m")[0]
    # Free-text answers are graded on their conclusion, not on everything mentioned in the reasoning.
    listing = "Elevations:\n- Veltrix Dynamics: 312 m\n- Nimbic Foods: 540 m\n\nfinal_answer: Veltrix Dynamics, 312"
    assert not grade(t18, listing)[0]
    real_gemma_output = ("The elevations are:\n- Harlow Pike (Veltrix Dynamics): 312 m\n- Carrow Falls (Nimbic Foods): 540 m\n\n"
                         "The company with the highest headquarters elevation is Nimbic Foods.\n\nfinal_answer: Nimbic Foods, 540m")
    assert grade(t18, real_gemma_output)[0]
    assert grade(t01, "Revenue is 412 million over 2,150 staff.\nFinal answer: 191,628")[0]
