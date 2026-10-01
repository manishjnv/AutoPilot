"""L3: a web-only research session per topic; coding sessions see only the written note."""
from autopilot.backends import SessionRequest, SessionResult
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, git, make_project

NO_AUDIT = {"audit": {"completion_audit": False}}


def plan(*tasks):
    return [{"id": "P01", "title": "One",
             "tasks": [{"id": f"P01-T0{i}", "title": f"task {i}", "risk": "medium", **t} for i, t in enumerate(tasks, 1)]}]


class Recorder(FakeBackend):
    def __init__(self, research_report=None, **kw):
        super().__init__(**kw)
        self.reqs, self.research_report = [], research_report

    def run(self, req):
        self.reqs.append(req)
        if self.research_report is not None and req.prompt.startswith("# Assignment: research"):
            self.calls.append(("research", req.model))
            return SessionResult(ok=True, report=self.research_report)
        return super().run(req)


def run(tmp_path, phases, fake=None, cfg=None):
    root = make_project(tmp_path, phases, {**NO_AUDIT, **(cfg or {})})
    fake = fake or Recorder()
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch.run() == "plan complete"
    return root, fake


def test_topic_is_researched_once_and_fed_to_the_coder(tmp_path):
    root, fake = run(tmp_path, plan({"research": ["Stripe webhooks"]}, {"research": ["Stripe webhooks"]}))
    assert [c[0] for c in fake.calls] == ["research", "P01-T01", "P01-T02"]  # the second task reuses the note
    req = fake.reqs[0]
    assert req.read_only and req.web_only and req.model == "sonnet" and req.effort == "medium"
    assert req.schema and "sources" in req.schema["required"]
    note = root / "docs" / "research" / "stripe-webhooks.md"
    text = note.read_text(encoding="utf-8")
    assert "# Research: Stripe webhooks" in text and "[Doc](https://example.com/doc)" in text
    for task_req in fake.reqs[1:]:
        assert "## Research for this task" in task_req.prompt and "notes on Stripe webhooks" in task_req.prompt
    assert "docs/research/stripe-webhooks.md" in git(root, "ls-files")
    assert "autopilot/research" not in git(root, "branch", "--list")


def test_tasks_without_topics_never_research(tmp_path):
    _, fake = run(tmp_path, plan({}))
    assert [c[0] for c in fake.calls] == ["P01-T01"] and "## Research for" not in fake.reqs[0].prompt


def test_research_feeds_the_decide_session(tmp_path):
    _, fake = run(tmp_path, plan({"risk": "high", "research": ["auth tokens"]}))
    assert [c[0] for c in fake.calls] == ["research", "decide", "P01-T01"]
    assert "notes on auth tokens" in fake.reqs[1].prompt


def test_empty_report_builds_without_a_note(tmp_path):
    root, fake = run(tmp_path, plan({"research": ["x"]}), Recorder(research_report={"topic": "x"}))
    assert [c[0] for c in fake.calls] == ["research", "P01-T01"]
    assert not (root / "docs" / "research").exists()


def test_disabled(tmp_path):
    _, fake = run(tmp_path, plan({"research": ["x"]}), cfg={"research": {"enabled": False}})
    assert [c[0] for c in fake.calls] == ["P01-T01"]


def test_web_only_denies_shell_and_subagents(tmp_path):
    b = ClaudeCLIBackend(Config.load(tmp_path))
    cmd = b.build_cmd(SessionRequest(prompt="x", model="sonnet", cwd=".", read_only=True, web_only=True))
    denied = cmd[cmd.index("--disallowedTools") + 1:]
    assert {"Bash", "Agent", "Task", "Edit", "Write"} <= set(denied)
    cmd = b.build_cmd(SessionRequest(prompt="x", model="sonnet", cwd=".", read_only=True))
    assert "Agent" not in cmd
