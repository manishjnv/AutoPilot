from __future__ import annotations

import re

from autopilot.dash_web import render

XSS = "<script>alert(1)</script>"


def data(**kw) -> dict:
    d = {
        "project": {"name": "demo", "branch": "main", "commit": "abc123", "model": "Haiku", "run_id": "r1",
                    "started": "2026-10-04 06:17", "status": "running", "state_words": "Writes the code.",
                    "elapsed": "12m", "eta": "10m", "attempt": 2},
        "progress": {"done": 1, "total": 3, "pct": 33, "phases_done": 0, "phases_total": 2, "blocked": 1,
                     "questions": 0, "warnings": 2},
        "tasks": [{"n": 1, "id": "a", "title": "One", "phase": "P1", "status": "done", "time": "1m", "detail": "x"},
                  {"n": 2, "id": "b", "title": XSS, "phase": "P1", "status": "running", "time": "2m", "detail": ""},
                  {"n": 3, "id": "c", "title": "Three", "phase": "P2", "status": "pending", "time": "", "detail": ""}],
        "live": [{"at": "10:00", "text": XSS, "kind": "note"}, {"at": "", "text": "", "kind": "blank"}],
        "usage": {"five": 0.12, "week": 0.72, "context": 0.34, "tokens_text": "1.2M", "cost": 8.41,
                  "models": [{"name": "Haiku", "tokens_text": "1M", "share": 0.8}]},
        "files": {"added": 3, "modified": 8, "deleted": 1},
        "health": {"git": "OK", "checks": "failed"},
        "next": [("ap status", "see progress")],
        "line": "Run <b> 1/3",
    }
    d.update(kw)
    return d


def test_panels_and_bar():
    h = render(data())
    assert h.startswith("<!doctype html>")
    for t in ("Project", "Tasks", "Live output", "Progress", "Usage", "Files", "Issues", "What you can do next"):
        assert f">{t}</h2>" in h or t == "What you can do next"
    assert "What you can do next" in h and "<code>ap status</code>" in h
    assert "<footer>" in h and "Task 2/3" in h and "Left 10m" in h and "$8.41" in h
    assert "<th scope=col>Task</th>" in h and "Attempt" in h
    assert "5-hour window" in h and "72 percent" in h


def test_escape_everywhere():
    h = render(data(), report_md=XSS)
    assert XSS not in h
    assert h.count("&lt;script&gt;alert(1)&lt;/script&gt;") == 3  # task, live, report
    assert "<title>Run &lt;b&gt; 1/3</title>" in h


def test_refresh_and_script():
    h = render(data(), refresh=7)
    assert "<noscript><meta http-equiv=refresh content=7></noscript>" in h
    assert "},7000)</script>" in h
    assert "innerHTML" not in h
    assert "<p id=off hidden>" in h
    assert not re.search(r"https?://", h)


def test_running_row_current():
    assert render(data()).count('aria-current="true"') == 1
    assert 'aria-current="true"' not in render(data(tasks=[]))


def test_idle_and_empty():
    d = data(project={"status": "idle", "state_words": "No build is active."}, tasks=[], live=[], next=[],
             usage={}, progress={}, health={})
    h = render(d)
    assert "No build is active." in h and "No output yet." in h
    assert "What you can do next" not in h and "Attempt" not in h
    assert render({}).startswith("<!doctype html>")


def test_optional_parts_omitted():
    d = data(files=None)
    d["usage"] = dict(d["usage"], five=None, week=None, context=None)
    h = render(d)
    assert ">Files</h2>" not in h
    assert "5-hour window" not in h and ">Week<" not in h and ">Context<" not in h
    assert "<details>" not in h
    assert "<details><summary>Full report</summary><pre>a &amp; b</pre></details>" in render(data(), report_md="a & b")


def test_bars_clamped():
    h = render(data(usage={"five": 7, "week": -1, "context": 0.5}))
    assert "5-hour window 100 percent" in h and "Week 0 percent" in h
