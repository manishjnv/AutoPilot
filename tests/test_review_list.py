"""W40: a failed review's findings are a numbered list; the retry fixes exactly it and the next review checks it first."""
import subprocess

from autopilot.backends import SessionResult
from autopilot.orchestrator import Orchestrator
from autopilot.plan import Plan
from test_autopilot import make_project
from test_review import ALL, NO_AUDIT, Reviewer, phases, reviews, run


def review_prompts(fake):
    return [r.prompt for r in fake.reqs if r.prompt.startswith("# Assignment: review task")]


FAIL = {"verdict": "fail", "summary": "bad", "findings": ["src/a.py:3 — no auth check — add one"]}


def test_retry_prompt_lists_the_findings_of_the_failed_review(tmp_path):
    fake = Reviewer(reviews=[FAIL, {"verdict": "pass", "listed": [{"n": 1, "status": "fixed"}]}])
    _, orch = run(tmp_path, phases({"risk": "medium"}), fake, cfg=ALL)
    retry = fake.prompts[-1][1]
    assert "Fix exactly these review findings, nothing else:" in retry
    assert "1. src/a.py:3 — no auth check — add one" in retry
    assert orch.state.get_meta("review_list:P01-T01") == []


def test_next_review_prompt_holds_the_list(tmp_path):
    fake = Reviewer(reviews=[FAIL, {"verdict": "pass", "listed": [{"n": 1, "status": "fixed"}]}])
    run(tmp_path, phases({"risk": "medium"}), fake, cfg=ALL)
    first, second = review_prompts(fake)
    assert "Findings of the last review" not in first
    assert "Findings of the last review (check these first)" in second
    assert "1. src/a.py:3 — no auth check — add one" in second


def test_new_defect_outside_the_criteria_goes_to_followups_and_the_task_merges(tmp_path):
    ok = {"verdict": "fail", "summary": "nit", "listed": [{"n": 1, "status": "fixed"}],
          "followups": ["src/b.py:9 — rename helper"]}
    fake = Reviewer(reviews=[FAIL, ok])
    root, orch = run(tmp_path, phases({"risk": "medium"}), fake, cfg=ALL)
    assert orch.state.task("P01-T01")["status"] == "done" and len(reviews(fake)) == 2
    assert "src/b.py:9 — rename helper" in (root / ".agent" / "FOLLOWUPS.md").read_text(encoding="utf-8")


def test_new_defect_that_breaks_a_criterion_fails_the_task(tmp_path):
    bad = {"verdict": "fail", "summary": "x", "listed": [{"n": 1, "status": "fixed"}],
           "findings": ["src/c.py:1 — criterion 'widget works' broken — fix"]}
    fake = Reviewer(reviews=[FAIL, bad, {"verdict": "pass", "listed": [{"n": 1, "status": "fixed"}]}])
    _, orch = run(tmp_path, phases({"risk": "medium"}), fake, cfg=ALL)
    assert orch.state.task("P01-T01")["attempts"] == 3
    third = fake.prompts[-1][1]
    assert "1. src/c.py:1 — criterion 'widget works' broken — fix" in third
    assert "no auth check" not in third


def test_open_listed_finding_fails_even_when_the_verdict_says_pass(tmp_path):
    still = {"verdict": "pass", "listed": [{"n": 1, "status": "open"}]}
    fake = Reviewer(reviews=[FAIL, still, {"verdict": "pass", "listed": [{"n": 1, "status": "fixed"}]}])
    _, orch = run(tmp_path, phases({"risk": "medium"}), fake, cfg=ALL)
    assert orch.state.task("P01-T01")["attempts"] == 3
    assert "1. src/a.py:3 — no auth check — add one" in fake.prompts[-1][1]


def test_large_medium_diff_says_split_signal_and_is_not_escalated(tmp_path):
    root = make_project(tmp_path, phases({"risk": "medium"}), {**NO_AUDIT, **ALL})
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "base"], cwd=root, check=True)
    orch = Orchestrator(root, backend=Reviewer(), sleep=lambda s: None)
    task = Plan.load(root / ".agent" / "plan.yaml").all_tasks()[0]
    (root / "src").mkdir(exist_ok=True)
    for i in range(9):
        (root / "src" / f"m{i}.py").write_text("x = 1" + chr(10))
    assert orch.split_signal(task).startswith("split signal: 9 files")
    assert orch.escalation(SessionResult(ok=True), None, True) == ""
    assert orch.escalation(SessionResult(ok=True), None).startswith("large change")
