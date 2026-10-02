"""L2: a read-only decide session weighs options before risky work and leaves an ADR the implementer follows."""
from autopilot.backends import SessionResult
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, git, make_project

NO_AUDIT = {"audit": {"completion_audit": False}}


def phases(*tasks):
    return [{"id": "P01", "title": "One",
             "tasks": [{"id": f"P01-T0{i}", "title": f"task {i}", **t} for i, t in enumerate(tasks, 1)]}]


class Recorder(FakeBackend):
    def __init__(self, decide_report=None, **kw):
        super().__init__(**kw)
        self.reqs, self.decide_report = [], decide_report

    def run(self, req):
        self.reqs.append(req)
        if self.decide_report is not None and req.prompt.startswith("# Assignment: decide"):
            self.calls.append(("decide", req.model))
            return SessionResult(ok=True, report=self.decide_report)
        return super().run(req)


def run(tmp_path, plan, fake=None, cfg=None):
    root = make_project(tmp_path, plan, {**NO_AUDIT, **(cfg or {})})
    fake = fake or Recorder()
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch.run() == "plan complete"
    return root, fake, orch


def test_high_risk_task_gets_an_adr_first(tmp_path):
    root, fake, orch = run(tmp_path, phases({"risk": "high"}))
    assert [c[0] for c in fake.calls] == ["decide", "P01-T01"]
    decide_req, task_req = fake.reqs
    assert decide_req.read_only and decide_req.model == "opus" and decide_req.effort == "high"
    assert decide_req.schema and "decision" in decide_req.schema["required"]
    adr = root / "docs" / "adr" / "0001-approach-for-p01-t01.md"
    text = adr.read_text(encoding="utf-8")
    for part in ("# 0001. Approach for P01-T01", "Status: accepted (decided by the Autopilot decide session)",
                 "## Considered options", "1. **A** (score 8/10)", "Chosen option: **A**, because simpler"):
        assert part in text
    assert "Approach decided for this task (follow it; ADR `docs/adr/0001-approach-for-p01-t01.md`)" in task_req.prompt
    assert "Chosen option: **A**" in task_req.prompt
    dec = (root / ".agent" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "[P01-T01] ADR: A → docs/adr/0001-approach-for-p01-t01.md" in dec
    assert "docs/adr/0001-approach-for-p01-t01.md" in git(root, "ls-files")  # committed on main
    assert "autopilot/decide" not in git(root, "branch", "--list")


def test_which_tasks_get_a_decide_session(tmp_path):
    plan = phases({"risk": "low"}, {"risk": "medium", "needs_decision": True}, {"risk": "critical"})
    root, fake, _ = run(tmp_path, plan)
    assert [c[0] for c in fake.calls] == ["P01-T01", "decide", "P01-T02", "decide", "P01-T03", "review"]  # critical: reviewed too
    assert sorted(f.name[:4] for f in (root / "docs" / "adr").iterdir()) == ["0001", "0002"]


def test_corrective_and_disabled_never_decide(tmp_path):
    fix = [{"id": "FIX001", "title": "Fix", "priority": True,
            "tasks": [{"id": "FIX001-T01", "title": "fix", "risk": "high", "acceptance_criteria": ["x"]}]}]
    _, fake, _ = run(tmp_path, fix)
    assert "decide" not in [c[0] for c in fake.calls]
    (tmp_path / "off").mkdir()
    _, fake, _ = run(tmp_path / "off", phases({"risk": "high"}), cfg={"decide": {"enabled": False}})
    assert "decide" not in [c[0] for c in fake.calls]


def test_no_decision_means_build_without_adr_and_no_second_try(tmp_path):
    fake = Recorder(decide_report={"title": "x"}, behaviours={"P01-T01": ["break", "ok"]})
    root, fake, orch = run(tmp_path, phases({"risk": "high"}), fake)
    assert [c[0] for c in fake.calls] == ["decide", "P01-T01", "P01-T01"]
    assert not (root / "docs" / "adr").exists() and "Approach decided" not in fake.reqs[1].prompt
    assert orch.state.get_meta("adr:P01-T01") == ""


def test_spec_unstick_writes_an_adr_used_by_the_retry(tmp_path):
    spec = {"class": "spec", "diagnosis": "unclear storage", "decision": "use SQLite",
            "options_considered": ["SQLite", "Postgres"]}
    fake = Recorder(behaviours={"P01-T01": ["nothing", "nothing", "ok"]}, unsticks={"P01-T01": spec})
    root, fake, _ = run(tmp_path, phases({"risk": "medium"}), fake)
    adr = next((root / "docs" / "adr").iterdir())
    text = adr.read_text(encoding="utf-8")
    assert "decided by the unstick review" in text and "1. **SQLite**" in text and "Chosen option: **use SQLite**" in text
    retry = [r.prompt for r in fake.reqs if "implement task P01-T01" in r.prompt][2]
    assert f"ADR `docs/adr/{adr.name}`" in retry
    dec = (root / ".agent" / "DECISIONS.md").read_text(encoding="utf-8")
    assert f"DECISION (auto): use SQLite (options considered: SQLite; Postgres) → docs/adr/{adr.name}" in dec
