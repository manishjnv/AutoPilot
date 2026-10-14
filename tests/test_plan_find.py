"""W35: the plan document is found by its content (checkboxes, steps, plan headings), not by its name."""
import argparse
import os

from autopilot import cli
from autopilot.context import discovery_pack
from autopilot.plan_find import choose_plan, plan_candidates, score_text

PLAN = "# Architecture\n" + "".join(f"## Phase {i}\n- [ ] build part {i}\n- [x] design part {i}\n"
                                     for i in range(1, 13))
SMALL = "# Notes\n## Phase 1\n- [ ] one\n- [ ] two\n"


def quickstart(root, monkeypatch, idea=None):
    seen = {}
    monkeypatch.setattr(cli, "cmd_onboard", lambda a: seen.setdefault("plan", a.plan_doc) and 1)
    monkeypatch.setattr(cli, "write_plan", lambda r, i, b: seen.setdefault("idea", i) and None)
    cli._quickstart(argparse.Namespace(path=str(root), plan_doc=None, idea=idea, budget="15", run=False), root)
    return seen


def test_a_plan_in_docs_architecture_wins_and_says_why(tmp_path, monkeypatch, capsys):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text(PLAN)
    (tmp_path / "README.md").write_text(SMALL)
    seen = quickstart(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert seen == {"plan": str(tmp_path / "docs" / "architecture.md")}
    assert "plan found: docs/architecture.md (24 checkboxes, 12 phase headings)" in out


def test_two_close_candidates_give_one_question_with_the_top_three(tmp_path, monkeypatch, capsys):
    for name in ("a.md", "b.md", "c.txt", "d.rst"):
        (tmp_path / name).write_text(PLAN)
    asked = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: asked.append(q) or "2")
    seen = quickstart(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert len(asked) == 1 and seen["plan"] == str(tmp_path / "b.md")
    assert "1. a.md" in out and "2. b.md" in out and "3. c.txt" in out and "d.rst" not in out


def test_close_candidates_with_no_terminal_take_the_top_one_and_print_it(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.md").write_text(PLAN)
    (tmp_path / "b.md").write_text(PLAN)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda q: (_ for _ in ()).throw(AssertionError("asked")))
    assert choose_plan(tmp_path) == tmp_path / "a.md"
    assert "plan found: a.md" in capsys.readouterr().out


def test_an_empty_answer_takes_the_default(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text(PLAN)
    (tmp_path / "b.md").write_text(PLAN)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: "")
    assert choose_plan(tmp_path) == tmp_path / "a.md"


def test_no_candidate_keeps_the_idea_path(tmp_path, monkeypatch, capsys):
    (tmp_path / "README.md").write_text("# App\nA todo app.\n\n1. install\n2. run\n")
    seen = quickstart(tmp_path, monkeypatch, idea="a todo app")
    assert plan_candidates(tmp_path) == [] and seen == {"idea": "a todo app"}
    assert "plan found" not in capsys.readouterr().out


def test_a_prose_plan_md_is_still_used_by_name(tmp_path, monkeypatch, capsys):
    (tmp_path / "PLAN.md").write_text("# Plan\nA todo app.\n")
    seen = quickstart(tmp_path, monkeypatch)
    assert seen == {"plan": str(tmp_path / "PLAN.md")} and "using PLAN.md" in capsys.readouterr().out


def test_node_modules_and_friends_are_never_entered(tmp_path, monkeypatch):
    for d in ("node_modules/pkg", ".git", ".venv", "venv", ".agent", "dist", "build"):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / "PLAN.md").write_text(PLAN)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "roadmap.md").write_text(SMALL)
    visited, real = [], os.walk

    def walk(top, *a, **k):
        for dp, dns, fns in real(top, *a, **k):
            visited.append(os.path.relpath(dp, tmp_path))
            yield dp, dns, fns
    monkeypatch.setattr("autopilot.plan_find.os.walk", walk)
    assert [c.path for c in plan_candidates(tmp_path)] == ["src/roadmap.md"]
    assert sorted(visited) == [".", "src"]


def test_score_reads_checkboxes_steps_and_headings():
    score, reason = score_text("Sprint 1\nSprint 2\n1. a\n2. b\n- [ ] c\n")
    assert score > 0 and reason == "1 checkboxes, 2 sprint headings, 2 numbered steps"
    assert score_text("# Readme\nsome prose\n") == (0, "")


def test_large_files_are_read_only_to_200_kb(tmp_path):
    (tmp_path / "big.md").write_text("x\n" * 150_000 + "## Phase 9\n- [ ] late\n- [ ] later\n")
    assert plan_candidates(tmp_path) == []


def test_the_discovery_pack_lists_the_top_three_with_scores_and_first_lines(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text(PLAN)
    monkeypatch.setattr("autopilot.context._test_section", lambda root, cfg: "")
    pack = discovery_pack(tmp_path, None)
    sec = pack.split("## Plan candidates")[1]
    assert "- docs/architecture.md (score" in sec and "24 checkboxes, 12 phase headings" in sec
    assert "# Architecture" in sec
