"""W18b: the Now card, the progress total with the end steps, the end screen and the active row."""
import datetime as dt
import os
import re

from autopilot import dash_card, dash_live
from autopilot.dash_term import frame, normalize
from autopilot.dashboard import dashboard_data
from test_dash_term import PHASES, strip
from test_dash_term import data as term_data
from test_watch_liveness import BASE, built, make_project, phases_basic  # noqa: F401

T = 1_000_000.0
LONG = "Doctor endpoint line and the local-model docs and a very long tail of words " * 3


def card(**over):
    c = {"kind": "task", "n": 17, "title": LONG, "model": "Haiku", "attempt": 1, "max_attempts": 3, "work": 246.0,
         "work_at": T, "first_start": "", "eta": {"lo": 420.0, "mid": 500.0, "hi": 600.0, "basis": "median of 6 Haiku low"},
         "steps": list(dash_live.STEPS), "step": 2, "since": T - 100, "weights": [0.15, 0.3, 0.3, 0.2, 0.05],
         "step_eta": 300.0, "diff": {"plus": 31, "minus": 2, "files": 2, "tests": 1}, "tokens": 400_000, "cost": 0.12,
         "wait": {"kind": "tool", "text": "Bash (pytest -q)", "since": T - 120, "secs": 120}, "why": ""}
    return {**c, **over}


def with_card(**over):
    d = term_data()
    d["card"] = card(**over)
    d["spin"] = {"kind": "run", "text": "⠋", "age": 1, "data_age": 1, "clock": T, "utf": True}
    d["progress"]["total"] = 22
    return d


def box(cols, **over):
    return dash_card.box(normalize(with_card(**over)), cols, False)


def test_the_card_has_one_line_count_per_width_step():
    assert [len(box(c)) for c in (80, 130, 170)] == [7, 6, 4]  # border + 5 / border + 4 / border + 2, and the bottom line
    for cols in (80, 130, 170):
        assert all(len(x) == cols for x in box(cols))
    assert dash_card.height(normalize(with_card()), 119) == 0  # under 120 the card is a group of the left column


def test_the_title_is_cut_with_an_ellipsis_and_the_border_text_stays_in_its_row():
    wide = box(170)
    assert "..." in wide[0] and "Task 17 of 22" in wide[0] and "Haiku · try 1/3" in wide[0]  # facts kept, title cut
    assert "data 1s ⠋ ┐" in wide[0] and wide[0].startswith("┌─ Now ")
    mid = box(130)
    assert LONG[:20] in mid[1] and "..." in mid[1] and "Task 17 of 22" in mid[0] and LONG[:20] not in mid[0]
    for lines in (wide, mid, box(80)):
        assert lines[0].count("┌") == 1 and lines[0].endswith("┐")  # one row, a frame corner at each end
        assert lines[1].startswith("│ ") and lines[1].endswith(" │")  # the first inner row is the next row
    assert "..." in box(80)[1] and box(80)[1].startswith("│ Task 17 of 22 · ")


def test_the_bar_never_reaches_100_before_the_merge():
    c = normalize(with_card(step=4, since=T - 99_999, step_eta=10.0))["card"]  # the merge runs far beyond its ETA
    assert dash_card.progress(c, T)[2] == 99 and dash_card.progress(c, T)[1] <= 0.95
    text = "".join(t for t, _ in dash_card.bar(c, 80, T, True))
    assert "░" in text.split("merge")[-1] and "about 100" not in text  # the last cell of the running segment stays empty
    done = [x for x in range(5) if dash_card.progress({**c, "step": x}, T)[2] >= 100]
    assert done == []
    ascii_bar = "".join(t for t, _ in dash_card.bar(c, 80, T, False))
    assert "[" in ascii_bar and ">" in ascii_bar and "]" in ascii_bar  # the ASCII form [====>   ]


def test_the_running_segment_fills_by_time_and_the_shimmer_moves_each_second():
    c = normalize(with_card(step=1, since=T - 150, step_eta=300.0))["card"]
    a, b = ("".join(t for t, _ in dash_card.bar(c, 70, T + s, True)) for s in (0, 1))
    assert a != b and a.count("▓") == 1 and b.count("▓") == 1 and a.replace("▓", "█") == b.replace("▓", "█")  # only the cell moves
    assert dash_card.progress(c, T)[1] == 0.5


def project(tmp_path, extra=None):
    orch = built(tmp_path)
    return orch


def live_run(**over):
    return {"status": "running", "pid": os.getpid(), "state": "Review", "task": "", "attempt": 1, "model": "opus",
            "current": "audit completion", "session_at": dt.datetime.now().isoformat(timespec="seconds"),
            "started_at": "2026-01-01T00:00:00", **over}


def test_all_tasks_done_is_not_100_percent_while_the_audit_runs(tmp_path):
    orch = built(tmp_path)
    orch.cfg.data["audit"].update(enabled=True, completion_audit=True)
    d = dashboard_data(orch.cfg, orch.plan, orch.state, live_run())
    total = len(orch.plan.all_tasks())
    assert d["progress"]["done"] == total and 0 < d["progress"]["pct"] < 100  # the end steps are in the total
    assert d["progress"]["end_steps"] >= 1 and d["progress"]["word"] == "Checking the whole plan"
    assert d["card"]["kind"] == "end" and d["card"]["title"] == "Completion audit" and d["card"]["steps"] == ["read", "tests", "report"]
    plain = "\n".join(frame(d, 133, 37))
    assert "Completion audit" in plain and "do not close" in plain and "Checking the whole plan" in plain
    ended = dashboard_data(orch.cfg, orch.plan, orch.state, {"status": "finished", "word": "VERIFIED"})
    assert ended["progress"]["pct"] == 100  # 100 means the run ended


def test_the_row_says_how_many_tasks_the_audit_added(tmp_path):
    orch = built(tmp_path)
    orch.state.event("audit", "completion audit added 3 tasks")
    d = dashboard_data(orch.cfg, orch.plan, orch.state, live_run(started_at="2000-01-01T00:00:00"))
    assert d["progress"]["audit_added"] == 3
    assert "audit added 3 tasks" in "\n".join(frame(d, 133, 37))


def test_the_end_screen_names_the_outcome_and_lists_what_is_pending(tmp_path):
    orch = built(tmp_path)
    orch.state.set_task("P02-T01", status="blocked", last_error="boom")
    for word, sym in (("VERIFIED", "✓"), ("BLOCKED", "⏸"), ("FAILED", "✗"), ("STOPPED", "⏸"), ("BUDGET_STOP", "⏸")):
        d = dashboard_data(orch.cfg, orch.plan, orch.state, {"status": "finished", "word": word,
                                                              "updated_at": "2026-10-13T10:13:00"})
        assert d["project"]["end_title"] == f"{sym} {word} 10:13" and d["card"]["kind"] == "ended"
    plain = "\n".join(frame(d, 133, 37))
    assert "Run ended ── BUDGET_STOP" in plain and "ap unblock P02-T01" in plain  # the border and the pending command
    green = frame(dashboard_data(orch.cfg, orch.plan, orch.state, {"status": "finished", "word": "VERIFIED"}), 133, 37, True)
    assert "\x1b[32mVERIFIED" in "".join(green)
    assert "\x1b[31mFAILED" in "".join(frame(dashboard_data(orch.cfg, orch.plan, orch.state, {"status": "finished", "word": "FAILED"}), 133, 37, True))
    small = "\n".join(strip(frame(d, 110, 30)))
    assert "Run ended: BUDGET_STOP" in small  # under 120 columns the end block is a group of the left column
    page = __import__("autopilot.dash_web", fromlist=["render"]).render(d)
    assert "Run ended" in page and "ap unblock P02-T01" in page


def test_the_card_work_time_is_the_table_time_and_names_the_first_start(tmp_path):
    orch = built(tmp_path)
    tid = "P02-T01"
    first = (dt.datetime.now() - dt.timedelta(hours=3)).isoformat(timespec="seconds")
    orch.state.db.execute("DELETE FROM sessions WHERE task_id=?", (tid,))
    orch.state.db.execute("INSERT INTO sessions(kind, task_id, phase, attempt, model, started_at, ended_at) "
                          "VALUES('task', ?, 'P02', 1, 'sonnet', ?, ?)",
                          (tid, first, (dt.datetime.fromisoformat(first) + dt.timedelta(seconds=300)).isoformat(timespec="seconds")))
    start = (dt.datetime.now() - dt.timedelta(seconds=130)).isoformat(timespec="seconds")
    orch.state.db.execute("INSERT INTO sessions(kind, task_id, phase, attempt, model, started_at) "
                          "VALUES('task', ?, 'P02', 2, 'sonnet', ?)", (tid, start))
    orch.state.set_task(tid, status="running", started_at=first)
    run = {"status": "running", "pid": os.getpid(), "state": "Code", "task": tid, "attempt": 2, "model": "sonnet",
           "session_at": start, "max_attempts": 3}
    d = dashboard_data(orch.cfg, orch.plan, orch.state, run)
    row = next(t for t in d["tasks"] if t["id"] == tid)
    c = d["card"]
    assert c["kind"] == "task" and row["time"] == dash_live_dur(c["work"])  # 7m: the same count as the Tasks table
    assert c["first_start"] == first[11:16]  # the wall clock is 3 h, the work 7 m: the first start is named
    d["spin"] = {"kind": "run", "text": "⠋", "age": 1, "data_age": 1, "clock": c["work_at"] + 5, "utf": True}
    plain = "\n".join(strip(frame(d, 133, 37)))
    n = normalize(d)["card"]
    shown = dash_card.work_text(n, c["work_at"] + 5)
    assert shown.startswith(f"{int(c['work'] + 5) // 60}m{int(c['work'] + 5) % 60:02d}s") and f"first start {first[11:16]}" in plain


def dash_live_dur(secs):
    from autopilot.dashboard import _dur
    return _dur(secs)


def test_the_task_time_has_one_data_age_at_the_card_and_none_beside_the_time():
    d = with_card()
    d["asof"] = {"age": 3, "stopped": "", "live": True, "mtime": 1.0}
    plain = "\n".join(strip(frame(d, 133, 37)))
    assert plain.count("data 1s") == 1 and "data 3s old" not in plain and "Task time" not in plain


def test_the_version_is_one_line_cut_with_an_ellipsis():
    d = term_data(phases=PHASES)
    d["project"]["version"] = "Autopilot 0.7.1 (a1b2c3d) from " + "very-long-folder-name" * 3
    lines = [x[:36] for x in strip(frame(d, 133, 50))]
    hits = [x for x in lines if "Autopilot 0.7.1" in x]
    assert len(hits) == 1 and hits[0].rstrip(" │").endswith("...")
    assert not any("very-long-folder-name" in x for x in lines[lines.index(hits[0]) + 1:lines.index(hits[0]) + 2])


def test_the_build_group_drops_before_the_phases():
    many = [{"id": f"P{i:02d}", "title": "t", "total": 3, "done": 3 if i < 4 else 0,
             "status": "done" if i < 4 else "pending"} for i in range(1, 9)]
    d = term_data(phases=many)
    d["project"].update(version="Autopilot 0.7.1 (a1b2c3d)", run_line="Run 2 (since 06:59)")
    short = "\n".join(x[:36] for x in strip(frame(d, 133, 45)))
    assert "Build" not in short and all(f"P{i:02d}" in short for i in range(1, 9)) and "more" not in short  # every phase kept
    tall = "\n".join(x[:36] for x in strip(frame(d, 133, 70)))
    assert "Build" in tall and "Autopilot 0.7.1" in tall and "P08" in tall


def test_the_active_row_has_a_filled_background_the_spinner_and_bold_only_there():
    d = with_card()
    out = frame(d, 190, 60, True)
    row = next(x for x in out if "Task title 18" in x)
    assert "\x1b[1;30;46m" in row
    plain = next(x for x in strip(out) if "Task title 18" in x)
    assert "⠋18 Task title 18" in plain
    mono = "".join(frame(d, 190, 60, "mono"))
    assert not re.search(r"\x1b\[(1;30;46|3[0-7]|9[0-7])m", mono)  # NO_COLOR: bold and dim only


def test_every_state_of_the_card_draws_at_exact_size_and_without_a_card_nothing_changes():
    for kind in ("task", "end", "ended"):
        d = with_card(kind=kind, title="Completion audit", what="checks the plan", then="then the run ends", word="VERIFIED",
                      sym="✓", tone="green", at="10:13", done=22, total=22, retries=3, elapsed="6h44m",
                      steps=["read", "tests", "report"] if kind == "end" else list(dash_live.STEPS),
                      weights=[1 / 3] * 3 if kind == "end" else [0.15, 0.3, 0.3, 0.2, 0.05], step=0,
                      pending=[{"what": "Nothing is pushed", "how": "git push"}] * 9)
        for cols, rows in ((100, 24), (120, 24), (133, 37), (160, 30), (200, 50)):
            for color in (False, True, "mono"):
                out = frame(d, cols, rows, color)
                assert len(out) == rows and all(len(x) == cols for x in strip(out)), (kind, cols)
    plain = term_data()
    assert normalize(plain)["card"] is None and "Task 21 of 21" in "\n".join(frame(plain, 120, 40))  # the old Now group stays
