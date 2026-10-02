"""A critical task gets one read-only review of its diff after the gate and before the merge."""
from pathlib import Path

from autopilot.backends import SessionResult
from autopilot.orchestrator import Orchestrator
from autopilot.schemas import REPORTS
from test_autopilot import FakeBackend, git, make_project

NO_AUDIT = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}


def phases(*tasks):
    return [{"id": "P01", "title": "One",
             "tasks": [{"id": f"P01-T0{i}", "title": f"task {i}", **t} for i, t in enumerate(tasks, 1)]}]


class Reviewer(FakeBackend):
    """Answers each review session with the next entry of `reviews` (a report, None = no report, or "scribble")."""

    def __init__(self, reviews=None, **kw):
        super().__init__(**kw)
        self.reviews, self.reqs = list(reviews or []), []

    def run(self, req):
        self.reqs.append(req)
        if req.prompt.startswith("# Assignment: review task"):
            self.calls.append(("review", req.model))
            item = self.reviews.pop(0) if self.reviews else {"verdict": "pass"}
            if item == "git":  # the reviewer has Bash: it moves git itself
                cwd = Path(req.cwd)
                branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
                git(cwd, "checkout", "-q", "--detach")
                git(cwd, "branch", "-D", branch)
                (cwd / "nested").mkdir()
                git(cwd / "nested", "init", "-q")
                (cwd / "nested" / "x.txt").write_text("x")
                item = {"verdict": "pass"}
            if item == "scribble":
                (Path(req.cwd) / "src" / "P01-T01.txt").write_text("TAMPERED")
                (Path(req.cwd) / "REVIEWER_NEW.txt").write_text("untracked")
                item = {"verdict": "pass"}
            if item is None:
                return SessionResult(ok=False, error="reviewer crashed")
            return SessionResult(ok=True, cost=0.2, report=item)
        return super().run(req)


def run(tmp_path, plan, fake, cfg=None):
    root = make_project(tmp_path, plan, {**NO_AUDIT, **(cfg or {})})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch.run() == "plan complete"
    return root, orch


def reviews(fake):
    return [c for c in fake.calls if c[0] == "review"]


def test_critical_task_passes_review_and_merges_without_a_snapshot_commit(tmp_path):
    fake = Reviewer()
    root, _ = run(tmp_path, phases({"risk": "critical"}), fake)
    assert len(reviews(fake)) == 1 and reviews(fake)[0][1] == "opus"
    req = next(r for r in fake.reqs if r.prompt.startswith("# Assignment: review task"))
    assert req.read_only and req.effort == "high" and "src/P01-T01.txt" in req.prompt
    assert "impl P01-T01" in git(root, "show", "main:src/P01-T01.txt")
    assert "review snapshot" not in git(root, "log", "main", "--format=%s")


def test_review_finding_fails_the_attempt_and_the_retry_sees_it(tmp_path):
    fake = Reviewer(reviews=[{"verdict": "fail", "summary": "bad", "findings": ["src/a.py:3 — no auth check — add one"]},
                             {"verdict": "pass"}])
    root, orch = run(tmp_path, phases({"risk": "critical"}), fake)
    assert orch.state.task("P01-T01")["attempts"] == 2 and orch.state.task("P01-T01")["status"] == "done"
    assert len(reviews(fake)) == 2
    second = fake.prompts[-1][1]
    assert "src/a.py:3 — no auth check — add one" in second
    assert "review snapshot" not in git(root, "log", "main", "--format=%s")


def test_reviewer_edits_are_dropped_and_the_work_is_kept(tmp_path):
    fake = Reviewer(reviews=["scribble"])
    root, _ = run(tmp_path, phases({"risk": "critical"}), fake)
    assert "impl P01-T01" in git(root, "show", "main:src/P01-T01.txt")
    assert "REVIEWER_NEW.txt" not in git(root, "ls-files")
    assert not (root / "REVIEWER_NEW.txt").exists()


def test_reviewer_git_moves_are_undone(tmp_path):
    fake = Reviewer(reviews=["git"])
    root, orch = run(tmp_path, phases({"risk": "critical"}), fake)
    assert orch.state.task("P01-T01")["status"] == "done"
    assert "impl P01-T01" in git(root, "show", "main:src/P01-T01.txt")
    assert not any(f.startswith("nested") for f in git(root, "ls-tree", "-r", "--name-only", "main").splitlines())


def test_review_prompt_fence_outlasts_backticks_in_the_diff(tmp_path):
    _, orch = run(tmp_path, phases({"risk": "critical"}), Reviewer())
    task = orch.plan.all_tasks()[0]
    text = orch.ctx.review_prompt(task, "+x = '``````'\n")
    assert "```````diff" in text and "untrusted" in text


def test_medium_task_gets_no_review(tmp_path):
    fake = Reviewer()
    run(tmp_path, phases({"risk": "medium"}), fake)
    assert not reviews(fake)


def test_review_can_be_switched_off(tmp_path):
    fake = Reviewer()
    run(tmp_path, phases({"risk": "critical"}), fake, cfg={"review": {"enabled": False}})
    assert not reviews(fake)


def test_no_usable_verdict_merges_and_records_an_event(tmp_path):
    fake = Reviewer(reviews=[None])
    root, orch = run(tmp_path, phases({"risk": "critical"}), fake)
    assert orch.state.task("P01-T01")["status"] == "done"
    assert "src/P01-T01.txt" in git(root, "ls-files")
    assert any(e["kind"] == "review" for e in orch.state.events(20))


def test_review_report_schema_needs_a_verdict():
    assert REPORTS["review"]["required"] == ["verdict"]
