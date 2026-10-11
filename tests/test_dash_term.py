import re

import pytest

from autopilot.dash_term import frame, normalize

ANSI = re.compile(r"\x1b\[[0-9;]*m")
SIZES = [(100, 24), (120, 30), (133, 37), (190, 50)]


def data(n=21, running=18, files=True, **over):
    tasks = [{"n": i, "id": f"T{i}", "title": f"Task title {i}", "phase": "P1",
              "status": "done" if i < running else "running" if i == running else "pending",
              "time": "2m", "detail": "Haiku"} for i in range(1, n + 1)]
    d = {"project": {"name": "csv2json", "branch": "main", "commit": "4bac378", "model": "Haiku",
                     "run_id": "20261004-061714-9496", "started": "2026-10-04 06:17:14", "status": "running",
                     "state_words": "Writes the code.", "elapsed": "12m", "eta": "10m", "attempt": 1,
                     "tone": "good", "last_commit": "close phase FIX001", "last_commit_age": "7m", "next": "Next task",
                     "stale_min": 7, "stale": "warn",
                     "now": {"n": 21, "title": "Force replacement", "attempt": 2, "max_attempts": 3, "time": "2m",
                             "model": "Haiku"}},
         "progress": {"done": 18, "total": n, "pct": 85, "phases_done": 4, "phases_total": 5, "blocked": 1,
                      "questions": 1, "warnings": 2, "working": 1, "waiting": 0, "active": 21},
         "needs_you": [{"id": "D-001", "title": "A question for the owner"}],
         "blocked_why": {"id": "FIX001-T06", "why": "PROBLEM"},
         "size": {"code": 598, "tests": 1898, "docs": 1059, "test_count": 172, "run_lines": 246, "run_files": 13},
         "tasks": tasks,
         "live": [{"at": "06:17", "text": "Task 1 of 21: Skeleton", "kind": "heading"},
                  {"at": "", "text": "Goal: make it", "kind": "goal"},
                  {"at": "06:18", "text": "Changes cli.py.", "kind": "step"},
                  {"at": "", "text": "", "kind": "blank"},
                  {"at": "06:19", "text": "All checks passed.", "kind": "good"},
                  {"at": "06:20", "text": "The checks failed.", "kind": "bad"},
                  {"at": "06:21", "text": "Something odd.", "kind": "note"}],
         "usage": {"reset_in": "4h05m", "five": 0.12, "week": 0.72, "context": 0.34, "tokens_text": "21.8M", "cost": 8.41,
                   "models": [{"name": "Haiku", "tokens_text": "16.1M", "share": 0.74},
                              {"name": "Sonnet", "tokens_text": "5.7M", "share": 0.26}]},
         "files": {"added": 3, "modified": 8, "deleted": 1} if files else None,
         "health": {"git": "OK", "checks": "FAIL", "words": "The checks fail on main."}, "next": [], "line": "x"}
    d.update(over)
    return d


def strip(lines):
    return [ANSI.sub("", x) for x in lines]


@pytest.mark.parametrize("cols,rows", SIZES)
@pytest.mark.parametrize("color", [False, True])
def test_exact_size(cols, rows, color):
    out = frame(data(), cols, rows, color)
    assert len(out) == rows
    assert all(len(x) == cols for x in strip(out))


@pytest.mark.parametrize("cols,rows", SIZES)
def test_color_only_adds_codes(cols, rows):
    assert strip(frame(data(), cols, rows, True)) == frame(data(), cols, rows, False)
    assert "\x1b" not in "".join(frame(data(), cols, rows, False))
    assert "\x1b" in "".join(frame(data(), cols, rows, True))


@pytest.mark.parametrize("cols,rows", [(99, 30), (120, 23)])
def test_too_small(cols, rows):
    with pytest.raises(ValueError):
        frame(data(), cols, rows)


def test_running_task_in_window():
    out = "\n".join(frame(data(n=60, running=40), 120, 30))
    assert "Task title 40 " in out
    assert "Task title 1 " not in out


def test_empty_data():
    for odd in ({}, None, {"tasks": "x", "live": [1, None], "usage": [], "progress": {"done": "a"}, "files": 3}):
        out = frame(odd, 120, 30, True)
        assert len(out) == 30 and all(len(x) == 120 for x in strip(out))
    assert "No output yet." in "\n".join(frame({}, 120, 30))


@pytest.mark.parametrize("title", ["bad \x1b[2J title", "日本語 title", "tab\there\x00"])
def test_unsafe_text(title):
    d = data()
    d["tasks"][17]["title"] = title
    d["live"][2]["text"] = title
    d["project"]["name"] = title
    plain = frame(d, 120, 30)
    assert all(len(x) == 120 for x in plain) and "\x1b" not in "".join(plain)
    assert all(len(x) == 120 for x in strip(frame(d, 120, 30, True)))
    assert not any("日" in x for x in plain)


def test_files_box():
    assert "Files" not in "\n".join(frame(data(files=False), 120, 30))
    assert "Files" in "\n".join(frame(data(files=True), 120, 30))


def test_long_text_cut():
    d = data()
    d["tasks"][17]["title"] = "x" * 500
    d["live"][2]["text"] = "y" * 500
    d["project"]["state_words"] = "word " * 100
    out = frame(d, 100, 24, True)
    assert all(len(x) == 100 for x in strip(out))
    assert "..." in "\n".join(strip(out))


def test_status_bar_last():
    out = frame(data(), 120, 30)
    assert "Task 21/21" in out[-1] and out[-1].startswith(" Task") and "csv2json" not in out[-1]  # J13/14: seven keys
    assert "5h 12%" in out[-1]


NEW = ("needs_you", "blocked_why", "size")


def left(lines):
    return "\n".join(x[:36] for x in strip(lines))


def line_with(d, text, color=True, cols=120, rows=30):
    return next(x for x in frame(d, cols, rows, color) if text in ANSI.sub("", x))


def test_keys_missing():
    d = data()
    for k in NEW:
        d.pop(k)
    d["project"] = {"name": "x"}
    d["usage"].pop("reset_in")
    for cols, rows in SIZES:
        out = frame(d, cols, rows, True)
        assert len(out) == rows and all(len(x) == cols for x in strip(out))
        assert strip(out) == frame(d, cols, rows)


def test_needs_you():
    out = "\n".join(frame(data(), 120, 30))
    assert "Questions for you" in out and "ap answer" in out
    d = data(needs_you=[])
    assert "Questions for you" not in "\n".join(frame(d, 120, 30)) and "ap answer" not in "\n".join(frame(d, 120, 30))


def test_now_and_try_colors():
    out = "\n".join(frame(data(), 120, 40))
    assert "Now" in out and "Task 21 of 21" in out and "Try 2 of 3" in out
    assert "[33m" in line_with(data(), "Try 2 of 3", rows=40)
    d = data()
    d["project"]["now"]["attempt"] = 3
    assert "[31m" in line_with(d, "Try 3 of 3", rows=40)


def test_size():
    out = "\n".join(frame(data(), 120, 50))
    assert "Code" in out and "598 lines" in out and "172 tests" in out and "1,898" in out
    assert "Size" not in "\n".join(frame(data(size=None), 120, 50))


def test_usage_levels():
    d = data()
    d["usage"].update(five=0.05, week=0.74, context=0.95)
    assert "[32m" in line_with(d, "5h")
    assert "[33m" in line_with(d, "Week")
    assert "[31m" in line_with(d, "Context ")


def test_status_bar_task():
    assert "Task 21/21" in frame(data(), 120, 30)[-1]
    d = data()
    d["progress"]["active"] = 0
    assert "Done 18/21" in frame(d, 120, 30)[-1]


def test_project_panel_has_no_duplicates():
    out = left(frame(data(), 120, 40))
    assert "Tokens" not in out and "Cost" not in out and "Commit " not in out


def test_small_window_keeps_status_and_needs_you():
    out = left(frame(data(), 100, 24))
    assert "Branch" in out and "Questions for you" in out and "Elapsed" in out


# ---------- J11 ----------
PHASES = [{"id": "P01", "title": "a", "total": 4, "done": 4, "status": "done"},
          {"id": "FIX002", "title": "b", "total": 5, "done": 4, "status": "running"},
          {"id": "P05", "title": "c", "total": 3, "done": 0, "status": "pending"}]


def right(lines):
    return "\n".join(x[-30:] for x in strip(lines))


def test_normalize_keeps_phases_next_and_task_id():
    d = data(phases=PHASES, next=[("ap watch", "see the build"), ["ap stop"], "odd", 7])
    d["progress"]["warned"] = ["T1", "bad \x1b[2J id"] + [f"T{i}" for i in range(3, 12)]
    out = normalize(d)
    assert out["phases"][1] == {"id": "FIX002", "status": "running", "done": 4, "total": 5}
    assert out["next"] == [("ap watch", "see the build"), ("ap stop", "")]
    assert out["tasks"][0]["id"] == "T1"
    assert len(out["progress"]["warned"]) == 6 and "\x1b" not in "".join(out["progress"]["warned"])
    assert normalize({"phases": 3, "next": "x"})["phases"] == [] and normalize({"next": "x"})["next"] == []


def test_progress_has_no_percent_line_and_no_left_line():
    out = right(frame(data(), 120, 30))
    assert not any(x.strip("│ ") == "85%" for x in out.splitlines())
    assert "Left 10m" not in out and "85%" in out  # the bar still shows the percentage
    assert "Left" not in left(frame(data(), 120, 30)[:-1]) and "Left 10m" in frame(data(), 120, 30)[-1]


@pytest.mark.parametrize("label", ["Branch", "Added", "Modified", "Warnings", "Checks"])
def test_labels_and_state_sentence_are_not_dim(label):
    assert "\x1b[2m" + label not in line_with(data(), label)


def test_side_notes_and_zero_values_stay_dim():
    assert "\x1b[2mResets in 4h05m" in line_with(data(), "Resets in")
    d = data()
    d["progress"]["warnings"] = 0
    assert "\x1b[2m0" in line_with(d, "Warnings")


def test_group_rule_lines():
    out = left(frame(data(), 120, 40)).splitlines()
    for title in ("! Questions for you", "Now", "Next", "Size", "Last commit"):
        line = next(x for x in out if f"── {title} ─" in x)
        assert line == f"│ ── {title} " + "─" * (28 - len(title)) + " │"
    assert out[1].startswith("│ Project  : csv2json")  # the status group has no rule
    assert not any(x.strip("│ ") in ("", "Now", "Size") for x in out[1:20])  # no blank line, no title line
    assert "\x1b[1m" in line_with(data(), "── Now", rows=40) and "\x1b[2m── " in line_with(data(), "── Now", rows=40)


def test_warned_task_ids_below_the_count():
    d = data()
    d["progress"]["warned"] = ["P01-T02", "P02-T01"]
    out = right(frame(d, 120, 40)).splitlines()
    at = next(i for i, x in enumerate(out) if "Warnings" in x)
    assert "P01-T02 P02-T01" in out[at + 1]
    assert "P01-T02" not in right(frame(data(), 120, 40))


def test_phases_group():
    out = left(frame(data(phases=PHASES), 120, 50))
    assert "── Phases ─" in out and "✓ P01 4/4" in out and "▶ FIX002 4/5" in out and "○ P05 0/3" in out
    assert out.index("── Last commit") < out.index("── Phases")  # the last group
    many = [{"id": f"P{i:02d}", "total": 2, "done": 2 if i < 6 else 0,
             "status": "done" if i < 6 else "running" if i == 6 else "pending"} for i in range(1, 10)]
    out = left(frame(data(phases=many), 120, 50))
    assert all(f"P{i:02d}" in out for i in range(1, 10)) and "more" not in out  # J13/1: all nine fit
    assert "Phases" not in left(frame(data(), 120, 50))
    for rows in range(30, 50):  # not all fit: the last row counts the rest
        out = left(frame(data(phases=many), 120, rows))
        shown = sum(f"P{i:02d}" in out for i in range(1, 10))
        if 0 < shown < 9:
            break
    assert 0 < shown < 9 and f"… {9 - shown} more" in out
    lines = out.splitlines()
    assert "more" in lines[max(i for i, x in enumerate(lines) if "P0" in x or "more" in x)]  # it is the last row


def test_progress_count_and_phases_panel_agree():
    ph = [{"id": f"P{i}", "total": 2, "done": 2 if i <= 3 else 0, "status": "done" if i <= 3 else "pending"}
          for i in range(1, 8)]
    d = data(phases=ph)
    d["progress"].update(phases_done=3, phases_total=7)
    out = frame(d, 120, 50)
    assert "3 of 7" in right(out) and left(out).count("✓") == 3 and left(out).count("○") == 4


def test_this_run_is_two_rows_and_nothing_wraps():
    d = data()
    d["size"].update(run_lines=1234567, run_files=12345, code=9999999, tests=8888888, docs=7777777, test_count=666666)
    for cols, rows in SIZES:
        out = strip(frame(d, cols, rows + 20))
        assert all(len(x) == cols for x in out)
        at = next(i for i, x in enumerate(out) if "This run : +1,234,567 lines" in x)
        assert "12345 files" in out[at + 1][:36] and "..." not in out[at][:36]
        assert out[at][:2] == "│ " and out[at][34:36] == " │"


# ---------- J13 rows 11 and 14 ----------
def test_data_age_and_stale():
    def title(age):
        return strip(frame(data(asof={"age": age, "stopped": ""}), 120, 30))[0][:36]
    assert "data 3s old" in title(3) and "stale" not in title(3)
    assert "data 45s old stale" in title(45) and "\x1b[33mdata 45s old stale" in frame(
        data(asof={"age": 45, "stopped": ""}), 120, 30, True)[0]
    assert "data —" in title(None)
    assert "data" not in "".join(strip(frame(data(), 120, 30))[:1])  # no key in the data: no note


def test_stopped_run_shows_the_time_on_every_panel():
    out = "\n".join(strip(frame(data(asof={"age": 3, "stopped": "12:50"}), 120, 40)[:-1]))
    tops = [x for x in out.splitlines() if "┌─" in x]
    assert len(tops) >= 5 and all("stopped 12:50" in x for x in tops) and "data 3s" not in out
    small = strip(frame(data(asof={"age": 3, "stopped": "12:50"}), 100, 24, True))
    assert all(len(x) == 100 for x in small) and sum("stopped 12:50" in x for x in small) >= 4


def test_no_value_appears_in_two_panels():
    """One data dict, every panel and the bar: a key shows in one panel; only the bar repeats task, progress, left,
    blocked, tokens, cost and 5h."""
    d = data(asof={"age": 5, "stopped": ""}, phases=PHASES, next=[("ap watch", "see")])
    d["project"].update(name="NAMEZ", branch="BRANCHZ", started="2026-10-04 06:17:14", elapsed="ELAPSEDZ", eta="ETAZ",
                        last_commit="COMMITZ", next="NEXTZ", stale_min=57,
                        now={"n": 21, "title": "NOWZ", "attempt": 2, "max_attempts": 3, "time": "TASKTIMEZ", "model": "MODELZ"})
    d["progress"].update(done=141, working=143, blocked=147, waiting=153, questions=159, warnings=161, phases_done=167,
                         phases_total=171)
    d["usage"].update(tokens_text="TOKZ", cost=83.17, five=0.79, week=0.88, context=0.55)
    d["usage"]["models"] = [{"name": "SPLITZ", "tokens_text": "SPLITTOKZ", "share": 0.5}]
    d["size"].update(code=191919, tests=292929, docs=393939, test_count=494949)
    d["health"] = {"git": "GITZ", "checks": "CHECKZ", "words": ""}
    lines = strip(frame(d, 190, 60))
    assert len(lines) == 60
    bar = lines[-1]
    body = lines[:-1]
    # split the three columns, then the right column in its boxes
    cols = [[x[:36] for x in body], [x[36:-30] for x in body], [x[-30:] for x in body]]
    panels, cur = [], None
    for col in cols:
        for x in col:
            if x.startswith("┌"):
                cur = []
                panels.append(cur)
            if cur is not None:
                cur.append(x)
            if x.startswith("└"):
                cur = None
    texts = ["\n".join(p) for p in panels]
    assert len(texts) >= 7
    keys = ["NAMEZ", "BRANCHZ", "ELAPSEDZ", "ETAZ", "COMMITZ", "NEXTZ", "NOWZ", "TASKTIMEZ", "MODELZ", "SPLITZ",
            "GITZ", "CHECKZ", "191,919", "292,929", "393,939", "494,949", r"\b141\b", r"\b143\b", r"\b147\b", r"\b153\b",
            r"\b159\b", r"\b161\b", r"\b167\b", r"\b171\b", "TOKZ", r"83\.17", "79%", "88%", "55%", r"\b57 min"]
    import re
    for k in keys:
        n = sum(bool(re.search(k, t)) for t in texts)
        assert n <= 1, (k, n)
    for k in ("NAMEZ", "BRANCHZ", "ELAPSEDZ", "COMMITZ", "NOWZ", "MODELZ"):  # the bar repeats nothing outside the seven
        assert k not in bar
    assert "ETAZ" in bar and "TOKZ" in bar and "$83.17" in bar and "5h 79%" in bar and "Blocked 147" in bar


def test_cut_order_at_100x24():
    out = left(frame(data(phases=PHASES), 100, 24))
    for kept in ("Branch", "Questions for you", "── Now", "── Next"):
        assert kept in out
    assert "── Phases" not in out and "── Size" not in out


def test_start_time_in_status_block():
    out = left(frame(data(), 100, 24)).splitlines()
    at = next(i for i, x in enumerate(out) if "Started  : 2026-10-04 06:17 " in x)
    assert at < next(i for i, x in enumerate(out) if "Questions for you" in x)
    assert "Model" not in "\n".join(out[:at + 3])  # the model is in the Now group only


def test_group_that_does_not_fit_does_not_stop_the_next():
    d = data()
    d["project"].update(stale_min=0, last_commit_age="")
    out = left(frame(d, 100, 24))
    assert "── Size" not in out and "── Last commit" in out and "close phase FIX001" in out


def test_next_step_line_at_the_bottom_of_issues():
    d = data(next=[("ap watch", "see the build"), ("ap stop", "stop the build")])
    out = strip(frame(d, 120, 40))
    assert out[-3][-30:] == "│ " + "Run: ap watch".ljust(26) + " │"
    assert "[36m" in line_with(d, "Run: ap watch", rows=40)
    assert "ap stop" not in "\n".join(out)  # one line only
    assert "Run: ap watch" not in "\n".join(frame(d, 120, 24))  # no free row: no line
    assert "Run: ap" not in right(frame(data(), 120, 40))  # no data: no line
