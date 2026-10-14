"""W62: the AI box: every model and source in one place, the limit that stops the next task first."""
import re

from autopilot import usage
from autopilot.dash_term import STATE_STYLE, ai_box, frame
from autopilot.dash_web import render
from test_dash_term import data, strip
from test_usage import BODY

NOW = 1_800_000_000.0


def test_parse_keeps_the_scoped_cap_and_the_used_share():
    bars = usage.parse(BODY)
    assert bars["models"]["fable"]["cap"] == 0.5 and bars["models"]["fable"]["used"] == 0.11
    body = dict(BODY, weekly_scoped_shares=[{"limit_index": 9, "used_percent_of_weekly": 1, "allowance_percent_of_weekly": 50}])
    assert "cap" not in usage.parse(body)["models"]["fable"]  # an index outside the limits list is dropped


def rows_for(figs_table, fallback=("/logins/two",), off=()):
    """Source rows from fake figures: table[folder] = (five, week, models{name: pct})."""
    def figs(folder):
        five, week, models = figs_table.get("" if folder == "default" else folder, (0.1, 0.1, {}))
        return {"five_hour": {"pct": five, "reset": NOW + 3600}, "seven_day": {"pct": week, "reset": NOW + 86400},
                "models": {k: {"pct": v, "reset": NOW + 86400, "cap": 0.5} for k, v in models.items()}, "source": "live"}
    rows = [{"name": "login:default", "kind": "login", "folder": "", "room": 1 - max(figs_table[""][0], figs_table[""][1]),
             "five": figs_table[""][0], "week": figs_table[""][1], "resets": NOW + 3600, "week_resets": NOW + 86400, "expires": 0.0,
             "usd": 0.0, "can_run": True, "off": "login:default" in off, "note": ""}]
    for f in fallback:
        five, week, _ = figs_table.get(f, (0.1, 0.1, {}))
        rows.append({"name": f"login:{f.rsplit('/', 1)[-1]}", "kind": "login", "folder": f, "room": 1 - max(five, week),
                     "five": five, "week": week, "resets": NOW + 3600, "week_resets": NOW + 86400, "expires": 0.0, "usd": 0.0,
                     "can_run": True, "off": f"login:{f.rsplit('/', 1)[-1]}" in off, "note": ""})
    rows.append({"name": "api", "kind": "api", "folder": "", "room": 1.0, "five": None, "week": None, "resets": 0.0, "week_resets": 0.0,
                 "expires": 0.0, "usd": 109.0, "can_run": False, "off": False, "note": "needs backend"})
    rows.append({"name": "cloud", "kind": "cloud", "folder": "", "room": 1.0, "five": None, "week": None, "resets": 0.0,
                 "week_resets": 0.0, "expires": 0.0, "usd": 149.0, "can_run": False, "off": "cloud" in off, "note": "Routine runs only"})
    return usage.with_states(rows, "default", 95, figs, model="sonnet"), figs


def test_every_state_word_comes_from_the_one_table_and_fits_its_row():
    rows, _ = rows_for({"": (0.54, 0.42, {"fable": 0.27}), "/logins/two": (1.0, 0.3, {})}, off=("cloud",))
    by = {r["name"]: r for r in rows}
    assert {r["state"] for r in rows} <= set(usage.STATES) and set(STATE_STYLE) == set(usage.STATES)
    assert by["login:default"]["state"] == "ACTIVE" and by["login:default"]["model"] == "sonnet"
    assert by["fable"]["kind"] == "share" and by["fable"]["state"] == "STANDBY" and by["fable"]["cap"] == 0.5
    assert by["login:two"]["state"] == "LIMITED" and by["login:two"]["limit"].startswith("5h resets ")
    assert by["api"]["state"] == "DISABLED" and by["cloud"]["state"] == "OFF"
    assert by["login:default"]["bar"]["kind"] == "5h" and by["login:default"]["bar"]["pct"] == 0.54  # the closest bar


def test_the_coloured_bar_is_the_planners_limit_not_the_highest_and_a_credit_has_no_bar():
    rows, _ = rows_for({"": (0.54, 0.42, {"fable": 0.96}), "/logins/two": (0.98, 0.3, {})})
    nxt = usage.next_fields(rows, {"source": "login:two", "reason": "limit", "text": "x"}, "suggest", "default")
    assert nxt["limit"] == "5h" and nxt["pct"] == 0.54 and nxt["text"] == "suggest: ap source two (default 5h 54%)"
    assert usage.next_fields(rows, {"source": "login:two"}, "auto", "default")["text"] == "switch: two when default 5h 54% hits 54% (auto)"
    assert usage.next_fields(rows, {}, "auto", "default")["text"] == "no switch planned"
    u = data()["usage"]
    u.update(sources=[{"name": r["name"], "kind": r["kind"], "state": r["state"], "pct": (r.get("bar") or {}).get("pct"),
                       "bar_kind": (r.get("bar") or {}).get("kind", ""), "reset_in": "1h", "limit": r.get("limit", ""),
                       "usd": r["usd"], "cap": r.get("cap"), "model": r.get("model", ""), "note": r["note"],
                       "limiting": r["state"] == "ACTIVE" and (r.get("bar") or {}).get("kind") == nxt["limit"]} for r in rows],
             next=nxt, eta="", cost_text="$8.41")
    lines = ai_box(u, 40)
    text = ["".join(x[0] if isinstance(x, tuple) else x for x in ln) if isinstance(ln, list) else ln for ln in lines]
    colours = [[x[1] for x in ln if isinstance(x, tuple)] if isinstance(ln, list) else [] for ln in lines]
    active = next(i for i, l in enumerate(text) if l.startswith("default") and "ACTIVE" in l)
    fable = next(i for i, l in enumerate(text) if l.startswith("fable"))
    two = next(i for i, l in enumerate(text) if l.startswith("two"))
    assert "magenta" in colours[active] and "dim" in colours[fable] and "dim" in colours[two]  # one coloured bar: the 5h bar at 54%
    assert "red" in colours[fable] and "red" in colours[two]  # 96 and 98 percent texts still red
    api = next(l for l in text if l.startswith("api"))
    assert "$109" in api and "█" not in api and "░" not in api  # a credit: a dollar figure, never a bar
    assert "27% of its" not in "".join(text) and any("of its 50% cap" in l for l in text)
    assert any(l.startswith("suggest: ap source two") for l in text)


def test_a_small_box_collapses_in_the_stated_order():
    rows, _ = rows_for({"": (0.54, 0.42, {}), "/logins/two": (0.3, 0.3, {}), "/logins/three": (0.3, 0.2, {})},
                       fallback=("/logins/two", "/logins/three"), off=("cloud",))
    rows.append({"name": "cli:gemini:flash", "kind": "cli", "state": "STANDBY", "pct": None, "usd": 0.0, "note": "side sessions only"})
    nxt = usage.next_fields(rows, {}, "suggest", "default")
    u = data()["usage"]
    u.update(sources=[{"name": r["name"], "kind": r["kind"], "state": r["state"], "pct": (r.get("bar") or {}).get("pct") if r["kind"] != "cli" else None,
                       "bar_kind": (r.get("bar") or {}).get("kind", ""), "reset_in": "1h", "limit": r.get("limit", ""), "usd": r.get("usd", 0.0),
                       "cap": None, "model": r.get("model", ""), "note": r.get("note", ""),
                       "limiting": r.get("state") == "ACTIVE"} for r in rows], next=nxt, eta="", cost_text="$8.41")
    full = ai_box(u, 99)
    flat = lambda lines: ["".join(x[0] if isinstance(x, tuple) else x for x in ln) if isinstance(ln, list) else ln for ln in lines]  # noqa: E731
    f = flat(full)
    assert any(l.startswith("Haiku") for l in f) and any(l.startswith("api") for l in f) and any(l.startswith("gemini") for l in f)
    steps = [flat(ai_box(u, n)) for n in (len(full) - 2, len(full) - 4, len(full) - 5, len(full) - 8, 4)]  # 13 lines: -2 spend models, -2 quiet rows, -1 cli, -3 spend
    assert not any(l.startswith("Haiku") for l in steps[0]) and any(l.startswith("api") for l in steps[0])  # per-model spend first
    assert not any(l.startswith(("api", "cloud")) for l in steps[1]) and any(l.startswith("gemini") for l in steps[1])  # then OFF/DISABLED/MANUAL
    assert not any(l.startswith("gemini") for l in steps[2]) and any(l.startswith("Tokens") for l in steps[2])  # then cli rows
    assert not any(l.startswith("Tokens") for l in steps[3])  # then SPEND
    last = steps[4]
    assert last[0].startswith("default") and "ACTIVE" in last[0] and any(l.startswith("no switch planned") for l in last)  # never fewer
    assert not any(l.startswith(("two", "three")) for l in last)


def test_the_frame_shows_the_ai_box_and_the_web_page_the_three_groups():
    rows, _ = rows_for({"": (0.54, 0.42, {}), "/logins/two": (1.0, 0.3, {})})
    nxt = usage.next_fields(rows, {"source": "login:two", "reason": "limit", "text": "x"}, "suggest", "default")
    src = [{"name": r["name"], "kind": r["kind"], "state": r["state"], "pct": (r.get("bar") or {}).get("pct"),
            "bar_kind": (r.get("bar") or {}).get("kind", ""), "reset_in": "1h", "limit": r.get("limit", ""), "usd": r["usd"],
            "cap": None, "model": r.get("model", ""), "note": r["note"], "limiting": r["state"] == "ACTIVE"} for r in rows]
    d = data()
    d["usage"].update(sources=src, next=nxt, eta="5h ends in ~40 min at this rate")
    out = strip(frame(d, 190, 60))
    joined = "\n".join(out)
    assert "─ AI " in joined and "Usage" not in joined.split("─ AI ")[1].split("─ Files")[0]
    assert "suggest: ap source two" in joined and "5h ends in ~40 min" in joined and "LIMITED" in joined
    from test_dash_web import data as wdata
    w = wdata()
    w["usage"].update(sources=src, next=nxt, eta="")
    html = render(w)
    assert ">Limits<" in html and ">Next<" in html and ">Spend<" in html and "ACTIVE" in html and "54% used" in html
    assert "suggest: ap source two (default 5h 54%)" in html


def test_ap_status_prints_the_active_row_and_next_as_one_line():
    rows, _ = rows_for({"": (0.54, 0.42, {}), "/logins/two": (0.3, 0.3, {})})
    nxt = usage.next_fields(rows, {"source": "login:two", "reason": "window idle", "text": "x"}, "suggest", "default")
    line = usage.ai_line(rows, nxt)
    assert line.startswith("AI: login:default ACTIVE sonnet · 5h 54% used, resets ") and line.endswith("· suggest: ap source two (default 5h 54%)")
    assert usage.ai_line([r for r in rows if r["state"] != "ACTIVE"], nxt) == ""


def test_the_rate_needs_two_live_fetches_of_the_same_bar():
    class St:
        def __init__(self):
            self.meta = {}

        def get_meta(self, k, d=None):
            return self.meta.get(k, d)

        def set_meta(self, k, v):
            self.meta[k] = v
    st = St()
    first = {"five_hour": {"pct": 0.40, "reset": NOW + 7200}, "seven_day": {"pct": 0.1, "reset": NOW + 86400}, "models": {}, "surfaces": {}, "at": NOW}
    figs = usage.figures(st, None, "default", now=lambda: NOW, live_fetch=lambda *a, **k: first)
    assert "five_eta" not in figs
    second = {**first, "five_hour": {"pct": 0.50, "reset": NOW + 7200}, "at": NOW + 600}
    figs = usage.figures(st, None, "default", now=lambda: NOW + 600, live_fetch=lambda *a, **k: second)
    assert round(figs["five_eta"]) == 3000  # 10 points in 600 s: 50 points left take 3000 s
    assert usage.eta_text(figs["five_eta"]) == "5h ends in ~50 min at this rate" and usage.eta_text(0) == ""
    assert re.fullmatch(r"5h ends in ~2\.0 h at this rate", usage.eta_text(7200))
