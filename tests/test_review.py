"""A critical task (W4: with review.scope all, every task above low risk) gets one read-only review of its diff after
the gate and before the merge."""
from pathlib import Path

import yaml

from autopilot.backends import SessionResult
from autopilot.config import TEMPLATES, Config, defaults
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


def run(tmp_path, plan, fake, cfg=None, done=True):
    root = make_project(tmp_path, plan, {**NO_AUDIT, **(cfg or {})})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    out = orch.run()
    assert not done or out == "plan complete"
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


def test_no_verdict_is_retried_once_then_the_task_fails(tmp_path):
    fake = Reviewer(reviews=[None, {"summary": "no verdict field"}] * 3)
    root, orch = run(tmp_path, phases({"risk": "critical"}), fake, done=False)
    assert orch.state.task("P01-T01")["status"] == "blocked"
    assert len(reviews(fake)) % 2 == 0 and len(reviews(fake)) >= 2
    assert "src/P01-T01.txt" not in git(root, "ls-files")
    assert any(e["kind"] == "review" for e in orch.state.events(20))


def test_verdict_on_the_second_try_merges(tmp_path):
    fake = Reviewer(reviews=[None, {"verdict": "pass"}])
    root, orch = run(tmp_path, phases({"risk": "critical"}), fake)
    assert len(reviews(fake)) == 2 and orch.state.task("P01-T01")["attempts"] == 1
    assert "src/P01-T01.txt" in git(root, "ls-files")


def test_review_report_schema_needs_a_verdict():
    assert REPORTS["review"]["required"] == ["verdict"]


# W4: review.scope
ALL = {"review": {"scope": "all"}}


def test_scope_all_reviews_a_medium_task_and_a_finding_blocks_the_merge(tmp_path):
    fake = Reviewer(reviews=[{"verdict": "fail", "summary": "bad", "findings": ["src/b.py:9 — wrong sum — fix it"]},
                             {"verdict": "pass"}])
    _, orch = run(tmp_path, phases({"risk": "medium"}), fake, cfg=ALL)
    assert orch.state.task("P01-T01")["attempts"] == 2 and orch.state.task("P01-T01")["status"] == "done"
    assert len(reviews(fake)) == 2
    assert "REVIEW of the medium task" in fake.prompts[-1][1] and "src/b.py:9 — wrong sum — fix it" in fake.prompts[-1][1]


def test_scope_critical_gives_a_medium_task_no_review(tmp_path):
    fake = Reviewer()
    run(tmp_path, phases({"risk": "medium"}), fake, cfg={"review": {"scope": "critical"}})
    assert not reviews(fake)


def test_scope_all_skips_a_low_task(tmp_path):
    fake = Reviewer()
    run(tmp_path, phases({"risk": "low"}), fake, cfg=ALL)
    assert not reviews(fake)


def test_review_prompt_has_the_spec_diff_and_tests_and_nothing_from_the_build_session(tmp_path):
    fake = Reviewer()
    root = make_project(tmp_path, phases({"risk": "medium", "acceptance_criteria": ["the widget example works"]}),
                        {**NO_AUDIT, **ALL})
    for name in ("DECISIONS.md", "HANDOFF.md"):
        p = root / ".agent" / name
        p.write_text((p.read_text(encoding="utf-8") if p.exists() else "") + "\n- SESSION note example\n", encoding="utf-8")
    assert Orchestrator(root, backend=fake, sleep=lambda s: None).run() == "plan complete"
    text = next(r.prompt for r in fake.reqs if r.prompt.startswith("# Assignment: review task"))
    build = fake.prompts[0][1].splitlines()[0]
    assert "the widget example works" in text and "src/P01-T01.txt" in text and "## Test output" in text
    assert "SESSION" not in text and "-task-P01-T01.log" not in text and build not in text


def test_scope_all_keeps_parallel_medium_tasks_reviewed(tmp_path):
    fake = Reviewer()
    _, orch = run(tmp_path, phases({"risk": "medium", "files_in_scope": ["src/P01-T01.txt"]},
                                   {"risk": "medium", "files_in_scope": ["src/P01-T02.txt"]}), fake, cfg=ALL)
    assert len(reviews(fake)) == 2
    assert all(orch.state.task(t)["status"] == "done" for t in ("P01-T01", "P01-T02"))


def test_review_scope_config_is_validated(tmp_path):
    def errors(review):
        root = tmp_path / str((review or {}).get("scope", "none"))
        (root / ".agent").mkdir(parents=True)
        cfg = {"name": "demo", "commands": {"test": ["echo ok"]}, **({"review": review} if review else {})}
        (root / ".agent" / "project.yaml").write_text(yaml.safe_dump(cfg))
        return [e for e in Config.load(root).validate() if "review.scope" in e]
    bad = errors({"scope": "sometimes"})
    assert bad and "review.scope must be critical or all" in bad[0] and "'sometimes'" in bad[0]
    assert not errors({"scope": "all"}) and not errors(None)
    assert defaults()["review"]["scope"] == "critical"
    assert "scope: all" in (TEMPLATES / "agent" / "project.yaml").read_text(encoding="utf-8")
