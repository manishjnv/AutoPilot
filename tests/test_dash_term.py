import re

import pytest

from autopilot.dash_term import frame

ANSI = re.compile(r"\x1b\[[0-9;]*m")
SIZES = [(100, 24), (120, 30), (133, 37), (190, 50)]


def data(n=21, running=18, files=True, **over):
    tasks = [{"n": i, "id": f"T{i}", "title": f"Task title {i}", "phase": "P1",
              "status": "done" if i < running else "running" if i == running else "pending",
              "time": "2m", "detail": "Haiku"} for i in range(1, n + 1)]
    d = {"project": {"name": "csv2json", "branch": "main", "commit": "4bac378", "model": "Haiku",
                     "run_id": "20261004-061714-9496", "started": "2026-10-04 06:17:14", "status": "running",
                     "state_words": "Writes the code.", "elapsed": "12m", "eta": "10m", "attempt": 1},
         "progress": {"done": 18, "total": n, "pct": 85, "phases_done": 4, "phases_total": 5, "blocked": 1,
                      "questions": 0, "warnings": 2},
         "tasks": tasks,
         "live": [{"at": "06:17", "text": "Task 1 of 21: Skeleton", "kind": "heading"},
                  {"at": "", "text": "Goal: make it", "kind": "goal"},
                  {"at": "06:18", "text": "Changes cli.py.", "kind": "step"},
                  {"at": "", "text": "", "kind": "blank"},
                  {"at": "06:19", "text": "All checks passed.", "kind": "good"},
                  {"at": "06:20", "text": "The checks failed.", "kind": "bad"},
                  {"at": "06:21", "text": "Something odd.", "kind": "note"}],
         "usage": {"five": 0.12, "week": 0.72, "context": 0.34, "tokens_text": "21.8M", "cost": 8.41,
                   "models": [{"name": "Haiku", "tokens_text": "16.1M", "share": 0.74},
                              {"name": "Sonnet", "tokens_text": "5.7M", "share": 0.26}]},
         "files": {"added": 3, "modified": 8, "deleted": 1} if files else None,
         "health": {"git": "OK", "checks": "OK"}, "next": [], "line": "x"}
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
    assert "csv2json" in out[-1] and "Task 18/21" in out[-1] and out[-1].startswith(" csv2json")
