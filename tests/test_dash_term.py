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
    assert "csv2json" in out[-1] and "Task 21/21" in out[-1] and out[-1].startswith(" csv2json")


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
    assert "Status" in out and "Questions for you" in out and "Elapsed" in out


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
    assert "Left     : 10m" in left(frame(data(), 120, 30))


@pytest.mark.parametrize("label", ["Branch", "  Writes the code.", "Added", "Modified", "Blocked ", "Warnings", "Checks"])
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
    assert [f"P{i:02d}" in out for i in range(1, 10)] == [False] * 3 + [True] * 5 + [False]  # five, around P06
    assert "Phases" not in left(frame(data(), 120, 50))


def test_cut_order_at_100x24():
    out = left(frame(data(phases=PHASES), 100, 24))
    for kept in ("Status", "Questions for you", "── Now", "── Next"):
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
    assert "Run: ap watch" not in "\n".join(frame(d, 120, 30))  # no free row: no line
    assert "Run: ap" not in right(frame(data(), 120, 40))  # no data: no line
