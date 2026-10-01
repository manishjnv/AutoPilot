"""U8: one quality line per finished task, a Quality section in the report, ladder suggestions every N tasks."""
from autopilot.orchestrator import Orchestrator
from autopilot.report import build_report, quality_tips
from test_autopilot import FakeBackend, make_project, phases_basic

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "unstick": {"enabled": False}}


def five(risk="medium"):
    return [{"id": "P01", "title": "One",
             "tasks": [{"id": f"P01-T0{i}", "title": f"t{i}", "risk": risk} for i in range(1, 6)]}]


def run(tmp_path, phases, fake, cfg=None):
    orch = Orchestrator(make_project(tmp_path, phases, {**BASE, **(cfg or {})}), backend=fake, sleep=lambda s: None)
    assert orch.run() in ("plan complete", "stalled: waiting on 1 decisions (see docs/NEEDS-YOU.md)")
    return orch


def lines(orch, kind="quality"):
    return [e["message"] for e in reversed(orch.state.events(500)) if e["kind"] == kind]


def test_one_line_per_finished_task(tmp_path):
    orch = run(tmp_path, phases_basic()[:1], FakeBackend({"P01-T01": ["break", "ok"], "P01-T02": ["blocked"]}))
    got = lines(orch)
    assert got[0].startswith("P01-T01 · ") and "attempts 2 · reworked Y" in got[0]
    assert got[1].startswith("P01-T02 · ") and "reworked Y" in got[1]  # parked counts as reworked
    report = build_report(orch.cfg, orch.plan, orch.state)
    assert "## Quality" in report and "| low | 1 | 0% | 2.0 |" in report and "| medium | 1 | 0% | 3.0 |" in report


def test_all_first_try_on_sonnet_suggests_a_cheaper_start(tmp_path):
    orch = run(tmp_path, five(), FakeBackend(), {"quality": {"every": 5}})
    (msg,) = lines(orch, "quality")[-1:]
    assert "after 5 tasks" in msg and "medium: 100% of 5 tasks passed on the first try with sonnet" in msg
    assert "cheaper first model" in msg


def test_mostly_failing_first_tries_suggest_a_stronger_start(tmp_path):
    fake = FakeBackend({f"P01-T0{i}": ["break", "ok"] for i in range(1, 6)})
    orch = run(tmp_path, five(), fake, {"quality": {"every": 0}})
    assert not any(m.startswith("after") for m in lines(orch))  # every: 0 = no suggestion notice
    (tip,) = quality_tips(orch.cfg, orch.plan, orch.state)
    assert tip.startswith("medium: 0% of 5 tasks") and "starting stronger" in tip


def test_too_few_tasks_or_cheapest_model_gives_no_tip(tmp_path):
    orch = run(tmp_path, five("low"), FakeBackend())  # low starts on haiku: nothing cheaper to suggest
    assert quality_tips(orch.cfg, orch.plan, orch.state) == []
