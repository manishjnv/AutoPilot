"""W6: a task with warnings or an untested criterion opens a draft PR with a Not proven body (fake gh, no network)."""
from types import SimpleNamespace

from autopilot.orchestrator import Orchestrator


def _run(tmp_path, warnings, criteria=()):
    calls = []
    o = object.__new__(Orchestrator)
    o.root, o.main = tmp_path, "main"
    o.cfg = SimpleNamespace(root=tmp_path, get=lambda k, d=None: d, agent_dir=tmp_path / ".agent")
    o.git = SimpleNamespace(run=lambda *a, **k: None, checkout_main=lambda m: None, sync=lambda r, m: None, head=lambda: "abc")
    o._gh = lambda *a, **k: calls.append(list(a)) or SimpleNamespace(rc=0, stdout="", stderr="", timed_out=False)
    task = SimpleNamespace(id="T1", title="x", acceptance_criteria=list(criteria))
    phase = SimpleNamespace(id="P1", tasks=[task])
    o._merge_pr(task, "br", phase, warnings)
    return next(c for c in calls if c[:2] == ["pr", "create"]), calls


def test_a_task_with_a_gate_warning_opens_a_draft_pr_listing_it(tmp_path):
    create, calls = _run(tmp_path, ["scope: touched extra.py"])
    assert "--draft" in create
    body = create[create.index("--body") + 1]
    assert "## Not proven" in body and "touched extra.py" in body
    assert ["pr", "ready", "br"] in calls


def test_a_clean_task_opens_a_ready_pr(tmp_path):
    create, calls = _run(tmp_path, [])
    assert "--draft" not in create
    assert create[create.index("--body") + 1].endswith("Nothing")
    assert ["pr", "ready", "br"] not in calls


def test_a_criterion_without_a_test_makes_the_pr_a_draft(tmp_path):
    create, _ = _run(tmp_path, [], ["the widget renders blue"])
    assert "--draft" in create
    assert "the widget renders blue" in create[create.index("--body") + 1]
