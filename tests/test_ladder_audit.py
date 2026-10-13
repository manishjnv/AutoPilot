"""W23: `ap audit --ladder` measures minutes, attempts and cost per model and risk, and proposes a ladder change."""
import yaml

from autopilot.cli import main as cli_main
from autopilot.commands.audit import ladder_table, propose, read_ladder
from autopilot.config import TEMPLATES, defaults
from autopilot.state import State

OLD = {"low": ["haiku", "sonnet", "opus"], "medium": ["sonnet", "sonnet", "opus"], "high": ["opus", "opus", "opus"],
       "critical": ["opus", "opus"]}
# task id, risk, [(kind, model, minutes, cost)], attempts
TASKS = [
    ("P01-T01", "low", [("task", "haiku", 20, 0.30), ("review", "opus", 2, 0.10)], 1),
    ("P01-T02", "low", [("task", "haiku", 14, 0.20), ("task", "sonnet", 14, 0.20)], 2),
    ("P01-T03", "low", [("task", "haiku", 30, 0.40)], 1),
    ("P01-T04", "medium", [("task", "sonnet", 6, 0.40)], 1),
    ("P01-T05", "medium", [("task", "sonnet", 5, 0.38)], 1),
    ("P01-T06", "medium", [("task", "sonnet", 7, 0.42)], 1),
]


def make_project(tmp_path, tasks=TASKS, ladder=OLD):
    root = tmp_path / "proj"
    (root / ".agent").mkdir(parents=True)
    (root / ".agent" / "project.yaml").write_text(yaml.safe_dump({"models": {"ladder": ladder}}), encoding="utf-8")
    plan = {"goal": "example", "phases": [{"id": "P01", "title": "One",
                                           "tasks": [{"id": t, "title": "x", "risk": r} for t, r, _, _ in tasks]}]}
    (root / ".agent" / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")
    st = State(root / ".agent" / "state.db")
    for tid, _, sessions, attempts in tasks:
        st.db.execute("INSERT INTO tasks(id, phase, status, attempts) VALUES(?, 'P01', 'done', ?)", (tid, attempts))
        for i, (kind, model, minutes, cost) in enumerate(sessions, 1):
            sid = st.start_session(kind, tid, "P01", i, model)
            st.end_session(sid, cost=cost, ok=True, duration_ms=minutes * 60000)
    st.db.execute("INSERT INTO tasks(id, phase, status, attempts) VALUES('P01-T09', 'P01', 'pending', 0)")
    st.db.commit()
    st.close()
    return root


def test_fixture_db_gives_the_table_and_one_proposal(tmp_path, capsys):
    root = make_project(tmp_path)
    assert cli_main(["audit", "--ladder", "-C", str(root)]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].split() == ["Model", "Risk", "Tasks", "Min/task", "Attempts", "Retried", "$/task"]
    haiku = next(x for x in lines if x.startswith("haiku"))
    assert haiku.split() == ["haiku", "low", "3", "28", "1.0", "33%", "0.40"]  # T02: 14 + 14 min, both sessions count
    sonnet = next(x for x in lines if x.startswith("sonnet"))
    assert sonnet.split() == ["sonnet", "medium", "3", "6", "1.0", "0%", "0.40"]
    assert [x for x in lines if x.startswith("propose:")] == [
        "propose: models.ladder.low: [sonnet, sonnet, opus] (haiku 28 min vs sonnet 6 min, same cost)"]


def test_rows_skip_unfinished_tasks_and_use_the_first_model(tmp_path):
    root = make_project(tmp_path)
    rows = read_ladder(root / ".agent" / "state.db", {"P01-T02": "low"})
    assert len(rows) == 6 and {r["model"] for r in rows} == {"haiku", "sonnet"}
    t02 = next(r for r in rows if r["model"] == "haiku" and r["attempts"] == 2)
    assert t02["minutes"] == 28 and abs(t02["cost"] - 0.40) < 1e-9
    assert read_ladder(tmp_path / "missing.db", {}) is None


def test_equal_tiers_give_no_proposal():
    row = {"tasks": 4, "minutes": 6.0, "attempts": 1.0, "retry": 0.0, "cost": 0.4}
    assert propose({("haiku", "low"): row, ("sonnet", "low"): dict(row)}, OLD) == []


def test_a_slower_but_cheaper_tier_or_too_few_tasks_gives_no_proposal():
    fast = {"tasks": 4, "minutes": 6.0, "attempts": 1.0, "retry": 0.0, "cost": 0.4}
    cheap = {**fast, "minutes": 24.0, "cost": 0.1}
    assert propose({("haiku", "low"): cheap, ("sonnet", "medium"): fast}, OLD) == []
    few = {**fast, "minutes": 24.0, "tasks": 1}
    assert propose({("haiku", "low"): few, ("sonnet", "medium"): fast}, OLD) == []


def test_a_dearer_slower_tier_names_both_costs():
    fast = {"tasks": 3, "minutes": 6.0, "attempts": 1.0, "retry": 0.0, "cost": 0.4}
    slow = {**fast, "minutes": 24.0, "cost": 0.8}
    assert propose({("haiku", "low"): slow, ("sonnet", "low"): fast}, OLD) == [
        "propose: models.ladder.low: [sonnet, sonnet, opus] (haiku 24 min vs sonnet 6 min, $0.80 vs $0.40 per task)"]


def test_ladder_table_medians():
    rows = [{"model": "opus", "risk": "high", "minutes": m, "attempts": a, "cost": 1.0}
            for m, a in ((25, 1), (47, 2), (30, 1), (40, 2), (26, 1))]
    t = ladder_table(rows)[("opus", "high")]
    assert t["tasks"] == 5 and t["minutes"] == 30 and t["attempts"] == 1 and t["retry"] == 0.4 and t["cost"] == 1.0


def test_no_finished_tasks_prints_one_line(tmp_path, capsys):
    root = make_project(tmp_path, tasks=[])
    assert cli_main(["audit", "--ladder", "-C", str(root)]) == 0
    assert capsys.readouterr().out.strip().startswith("No finished tasks")


def test_template_ladder_is_the_measured_one():
    ladder = yaml.safe_load((TEMPLATES / "agent" / "project.yaml").read_text(encoding="utf-8"))["models"]["ladder"]
    assert ladder["low"] == ["sonnet", "sonnet", "opus"] and ladder["high"] == ["sonnet", "opus", "opus"]
    assert ladder["medium"] == ["sonnet", "sonnet", "opus"] and ladder["critical"] == ["opus", "opus"]
    assert defaults()["models"]["ladder"] == ladder


def test_reference_model_table_matches_the_template():
    from pathlib import Path
    ref = (Path(__file__).resolve().parents[1] / "REFERENCE.md").read_text(encoding="utf-8")
    ladder = defaults()["models"]["ladder"]
    for risk, steps in ladder.items():
        row = (steps + [steps[-1]] * 3)[:3]
        assert f"| {risk} | {' | '.join(row)} |" in ref
