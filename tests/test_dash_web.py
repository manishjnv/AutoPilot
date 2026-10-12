from __future__ import annotations

import re

from autopilot.dash_web import render

XSS = "<script>alert(1)</script>"


def data(**kw) -> dict:
    d = {
        "project": {"name": "demo", "branch": "main", "commit": "abc123", "model": "Haiku", "run_id": "r1", "tone": "good",
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
    assert "<footer>" in h and "Done 1/3" in h and "Left 10m" in h and "$8.41" in h
    assert "<th scope=col>Task</th>" in h and "Run id" not in h
    assert "5-hour window" in h and "72 percent" in h


def test_escape_everywhere():
    h = render(data(), report_md=XSS)
    assert XSS not in h
    assert h.count("&lt;script&gt;alert(1)&lt;/script&gt;") == 3  # task, live, report
    d = data(needs_you=[{"id": "D", "title": XSS}], blocked_why={"id": "T", "why": XSS},
             health={"words": XSS}, size=None)
    d["project"] = dict(d["project"], last_commit=XSS, now={"n": 2, "title": XSS, "attempt": 1})
    h = render(d)
    assert XSS not in h and h.count("&lt;script&gt;alert(1)&lt;/script&gt;") == 7
    assert "<title>Run &lt;b&gt; 1/3 · Autopilot builds your software project while you are away</title>" in h


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


def test_needs_you():
    h = render(data(needs_you=[{"id": "D-1", "title": "Q one"}]))
    assert 'id="needs"' in h and "Questions for you" in h and "ap answer" in h and "1 question waits for you." in h
    assert "2 questions wait for you." in render(data(needs_you=[{"title": "a"}, {"title": "b"}]))
    assert 'id="needs"' not in render(data(needs_you=[]))


def test_now_and_size():
    d = data(size={"code": 598, "tests": 1898, "docs": 1059, "test_count": 172, "run_lines": 246, "run_files": 13})
    d["project"] = dict(d["project"], now={"n": 21, "title": "T", "attempt": 2, "max_attempts": 3, "time": "2m",
                                           "model": "Haiku"})
    d["progress"] = dict(d["progress"], total=21)
    h = render(d)
    assert "Task 21 of 21" in h and "Try 2 of 3" in h and "598 lines" in h and "1,898 lines, 172 tests" in h
    assert "+246 lines" in h and "<dd>13 files</dd>" in h and "Task time" in h  # J13: two rows

    stale = render(dict(d, asof={"age": 45, "stopped": ""}))
    assert 'class="w">data 45s old stale' in stale and "data 3s old" in render(dict(d, asof={"age": 3, "stopped": ""}))
    assert "stopped 12:50" in render(dict(d, asof={"age": 3, "stopped": "12:50"}))
    assert "data —" in render(dict(d, asof={"age": None, "stopped": ""})) and "data " not in render(d).split("<main")[-1][:300]
    assert render(d).count("Time left") == 0 and "Left 10m" in render(d)  # the bar is the only place for Left
    assert "Size</h3>" not in render(data(size=None))


def test_usage_levels_and_footer():
    h = render(data(usage={"five": 0.05, "week": 0.80, "context": 0.95}))  # J13/17: magenta, yellow over 75, red over 90
    assert 'class="bar use" role="img" aria-label="5-hour window' in h
    assert 'class="bar warn" role="img" aria-label="Week' in h
    assert 'class="bar bad" role="img" aria-label="Context' in h
    d = data()
    d["progress"] = dict(d["progress"], active=21, total=21, done=20)
    assert "Task 21/21" in render(d)
    d["progress"]["active"] = 0
    assert "Done 20/21" in render(d)


def test_spinner_element_and_paused_class():
    from autopilot.dashboard import spinner
    d = data(asof={"age": 3, "stopped": "", "live": True, "mtime": 1000.0})
    fresh = render(dict(d, spin=spinner(d, 1000.0, 1003)))
    body = fresh.split("</style>")[1].split("<script")[0]
    assert '<span class="spin run" data-m="1000.0"' in body and "paused" not in body
    stale = render(dict(d, spin=spinner(d, 1000.0, 1045)))
    assert 'class="spin stale paused"' in stale and "⏸ no change 45s" in stale
    d["asof"].update(live=False, stopped="12:50")
    stopped = render(dict(d, spin=spinner(d, 1000.0, 5000)))
    assert 'class="spin stopped paused"' in stopped and "✗ stopped 12:50" in stopped
    assert 'class="spin' not in render(d)  # no spin key: no element
    assert "animation-play-state:paused" in render(d) and "classList.add('paused')" in render(d)
    assert render(d).count("@keyframes") == 1  # J13/18: the ring is the only animation


def test_colour_map_classes():
    d = data()
    d["tasks"][0].update(risk="critical", tries=2, slow=True, detail="Haiku · 2 tries")
    d["tasks"][1].update(risk="high")
    d["project"] = dict(d["project"], login="Max", resets="14:30", last_error="boom", commit_stalled=True,
                        last_commit="c", last_commit_age="12m",
                        now={"n": 2, "title": "T", "attempt": 3, "max_attempts": 3})
    d["size"] = {"code": 1, "tests": 1, "docs": 1, "test_count": 1, "run_lines": 5, "run_files": 1}
    d["usage"] = dict(d["usage"], five=0.8, week=0.95, context=0.2)
    h = render(d)
    assert '<td class="w">1m</td>' in h  # a slow time
    assert '<td class="bad">critical</td>' in h and '<td class="w">high</td>' in h and '<td class="w">2</td>' in h
    assert '<span class="bl">Haiku</span> · 2 tries' in h
    assert '<dd class="good">Max</dd>' in h and '<dd class="mg">14:30</dd>' in h and '<dd class="bad">boom</dd>' in h
    assert '<dd class="good">+5 lines</dd>' in h and '<span class="w">12m ago</span>' in h and 'class="w">Try 3 of 3' in h
    assert 'class="bar warn"' in h and 'class="bar bad"' in h and 'class="bar use"' in h and 'class="bar ok"' in h
    assert '<span class="bl">Haiku</span>' in h and 'class="mg">$8.41' in h
    login = render(dict(d, project=dict(d["project"], login="—")))
    assert '<dd class="w">not checked</dd>' in login
    assert '<dd class="bad">free</dd>' in render(dict(d, project=dict(d["project"], login="free")))
    live = render(dict(d, live=[{"at": "1", "text": "Runs the tests.", "kind": "step"},
                                {"at": "2", "text": "Changes a.py.", "kind": "step"}]))
    assert 'class="l step test"' in live and '<b class="v">Changes</b> a.py.' in live


def test_new_keys_missing():
    d = data()
    for k in ("needs_you", "blocked_why", "size"):
        d.pop(k, None)
    assert render(d).startswith("<!doctype html>")
    assert render({"project": {"now": None}, "progress": None}).startswith("<!doctype html>")
