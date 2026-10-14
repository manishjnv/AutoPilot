"""W59: the usage bars of a Claude login, read live from the OAuth usage endpoint (undocumented), cached per login,
with a kill switch. The token is read from the login's `.credentials.json`, sent only to api.anthropic.com and never
logged or returned."""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

URL = "https://api.anthropic.com/api/oauth/usage"
BETA = "oauth-2025-04-20"
CACHE_SEC = 60  # one call per login at most this often; the watch loop and the status page reuse the cached row
_cache: dict[str, tuple[float, dict]] = {}


def config_dir(folder: str = "") -> Path:
    """The Claude config folder of a login: `folder` (an `agent.env` CLAUDE_CONFIG_DIR), else the environment's, else
    `~/.claude`."""
    if folder and folder != "default":
        return Path(folder)
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def read_token(folder: str = "") -> str:
    """The OAuth access token of the login in `folder`, or ''. Keep it out of every log and print."""
    try:
        creds = json.loads((config_dir(folder) / ".credentials.json").read_text(encoding="utf-8"))
        return str((creds.get("claudeAiOauth") or {}).get("accessToken") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _when(s) -> float:
    """An ISO time to unix seconds, 0 when it does not parse."""
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _bar(percent, resets_at) -> dict | None:
    """{pct 0..1, reset unix seconds} from a percent 0..100 and an ISO time; None for anything odd (same trust rules as
    `claude_cli.window_info`)."""
    if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not math.isfinite(percent):
        return None
    reset = _when(resets_at)
    if not 0 <= percent <= 100 or not 0 < reset < 4e9:
        return None
    return {"pct": float(percent) / 100, "reset": reset}


def parse(body) -> dict:
    """The bars from the endpoint answer (live shape probed 2026-10-14): `limits[]` rows of kind `session`,
    `weekly_all` and `weekly_scoped` (per model, named by `scope.model.display_name`), and `seven_day_breakdown.rows`
    per surface. Returns {five_hour: {pct, reset}, seven_day: {pct, reset}, models: {name: {pct, reset}}, surfaces:
    {key: pct}}; every key is optional and an odd value is dropped."""
    out: dict = {"models": {}, "surfaces": {}}
    if not isinstance(body, dict):
        return out
    for row in body.get("limits") or []:
        if not isinstance(row, dict):
            continue
        bar = _bar(row.get("percent"), row.get("resets_at"))
        if bar is None:
            continue
        kind = row.get("kind")
        if kind == "session":
            out["five_hour"] = bar
        elif kind == "weekly_all":
            out["seven_day"] = bar
        elif kind == "weekly_scoped":
            scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
            model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
            if model.get("display_name"):
                out["models"][str(model["display_name"]).lower()] = bar
    for name in ("five_hour", "seven_day"):  # the flat objects, when the limits list says nothing
        flat = body.get(name)
        if name not in out and isinstance(flat, dict):
            bar = _bar(flat.get("utilization"), flat.get("resets_at"))
            if bar:
                out[name] = bar
    breakdown = body.get("seven_day_breakdown")
    for row in (breakdown.get("rows") if isinstance(breakdown, dict) else None) or []:
        pct = row.get("percent") if isinstance(row, dict) else None
        if row.get("key") and isinstance(pct, (int, float)) and not isinstance(pct, bool) and 0 <= pct <= 100:
            out["surfaces"][str(row["key"])] = float(pct) / 100
    return out


def _open(url, headers):
    import urllib.request  # W47: lazy

    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15)


def fetch(folder: str = "", *, cfg=None, urlopen=_open, now=time.time, cache=_cache) -> dict:
    """The live bars of one login (`parse` output plus `at`, the fetch time), at most one call per CACHE_SEC per login.
    {} when `usage.live` is false, the login has no token, the call fails or the shape is unknown: the caller then
    keeps the CLI stream figures and marks them `(cli)`. Never raises."""
    if (cfg is not None and cfg.get("usage.live", True) is False) or os.environ.get("AUTOPILOT_NO_LIVE_USAGE"):
        return {}  # the kill switch: the config key, or the variable (tests and CI never call the endpoint)
    key = str(config_dir(folder))
    hit = cache.get(key)
    if hit and now() - hit[0] < CACHE_SEC:
        return hit[1]
    token = read_token(folder)
    bars: dict = {}
    if token:
        try:
            with urlopen(URL, {"Authorization": "Bearer " + token, "anthropic-beta": BETA,
                               "User-Agent": "autopilot-usage"}) as r:
                bars = parse(json.loads(r.read(1 << 20).decode("utf-8")))
        except Exception:  # noqa: BLE001  any HTTP, network or JSON fault: the CLI figures stay the source
            bars = {}
        if bars.get("five_hour") or bars.get("seven_day"):
            bars["at"] = now()
        else:
            bars = {}
    cache[key] = (now(), bars)
    return bars


# ---------- W59 part 2: one figure set per login, the model headroom, the one line everywhere ----------
META = "usage_live"  # state meta key (per login: `usage_live@<folder>`): the last live bars, shared by every process


def figures(state, cfg=None, acct: str = "default", *, now=time.time, live_fetch=None) -> dict:
    """The bars of one login: the live endpoint figures when they are fresh (at most one call per CACHE_SEC, the row
    is kept in state meta so the watch, the status page and the run share it), else the CLI stream figures marked
    `cli`. {five_hour, seven_day, models, surfaces, source: live|cli|'', check}. `check` is set when the live and the
    learned 5-hour percent differ by over 5 points at the same reset (W59 owner acceptance)."""
    folder = "" if acct == "default" else acct
    key = META if acct == "default" else f"{META}@{acct}"
    row = state.get_meta(key, {}) or {}
    bars = row.get("bars") or {}
    if not row or now() - float(row.get("at") or 0) >= CACHE_SEC:
        bars = (live_fetch or fetch)(folder, cfg=cfg, now=now)
        state.set_meta(key, {"at": now(), "bars": bars})
    wkey = "window_seen" if acct == "default" else f"window_seen@{acct}"
    cli = state.get_meta(wkey, {}) or {}
    out = {"models": {}, "surfaces": {}, "source": "", "check": False}
    if bars.get("five_hour"):
        out.update({k: (dict(v) if isinstance(v, dict) else v) for k, v in bars.items() if k != "at"}, source="live")
        out["models"] = {m: dict(b) for m, b in (bars.get("models") or {}).items()}  # a copy: marks never touch the cache
        five_cli = cli.get("five_hour") or {}
        if "pct" in five_cli and abs(float(five_cli.get("reset") or 0) - bars["five_hour"]["reset"]) < 120:
            out["check"] = abs(float(five_cli["pct"]) - bars["five_hour"]["pct"]) > 0.05
    elif cli.get("five_hour"):
        five = cli["five_hour"]
        if 0 < float(five.get("reset") or 0) - now() <= 6 * 3600:  # the same open-window rule as report.open_window
            out.update(five_hour=five, source="cli")
            if "pct" in (cli.get("seven_day") or {}):
                out["seven_day"] = cli["seven_day"]
    # W61 rule 4: a model marked out by a limit answer stays out until its reset; a live bar that is newer than the
    # mark and shows room clears it
    mkey = MARKS if acct == "default" else f"{MARKS}@{acct}"
    marks = dict(state.get_meta(mkey, {}) or {})
    if marks:
        reserve = float(cfg.get("usage.model_reserve_pct", 95) or 95) if cfg is not None else 95.0
        live_at = float(bars.get("at") or 0) if out["source"] == "live" else 0.0
        changed = False
        for model, mark in list(marks.items()):
            reset = float(mark.get("reset") or 0)
            live = _model_bar({"models": out["models"]}, model)
            if reset <= now() or (live_at > float(mark.get("at") or 0) and live and live["pct"] * 100 < reserve):
                marks.pop(model)
                changed = True
                continue
            out["models"][str(model)] = {"pct": 1.0, "reset": reset}
        if changed:
            state.set_meta(mkey, marks)
    return out


MARKS = "usage_out"  # state meta (per login): {model: {reset, at}} from limit answers (W61 rule 4)
COOLDOWN = 600  # a limit answer with no reset time: out for this long, not a lockout


def mark_out(state, model: str, reset: float = 0.0, acct: str = "default", *, now=time.time) -> float:
    """W61 rule 4: mark `model` out until `reset` (a parsed time), else for COOLDOWN seconds. Returns the time."""
    until = float(reset) if reset and reset > now() else now() + COOLDOWN
    mkey = MARKS if acct == "default" else f"{MARKS}@{acct}"
    marks = dict(state.get_meta(mkey, {}) or {})
    marks[str(model).lower()] = {"reset": until, "at": now()}
    state.set_meta(mkey, marks)
    return until


def step_up_room(figs: dict, model: str, reserve_pct: float = 95) -> str:
    """W61 rule 1: '' when a step up to `model` has room on this login, else the bar that blocks it, for the row text:
    the model's own weekly bar, the all-models weekly bar or the 5-hour bar at or over `reserve_pct`."""
    bar = _model_bar(figs, model)
    if bar and bar["pct"] * 100 >= reserve_pct:
        return f"{model} week {round(100 * bar['pct'])}%"
    for key, label in (("seven_day", "week"), ("five_hour", "5h")):
        b = figs.get(key) or {}
        if "pct" in b and float(b["pct"]) * 100 >= reserve_pct:
            return f"{label} {round(100 * float(b['pct']))}%"
    return ""


def expected_share(costs: list, capacity_usd: float) -> float:
    """W61 rule 2: the 75th percentile of this run's task session costs of one risk tier, as a share of the 5-hour
    window (`capacity_usd`); 0 when either is unknown."""
    rows = sorted(float(c) for c in costs if c)
    if not rows or not capacity_usd or capacity_usd <= 0:
        return 0.0
    p75 = rows[min(len(rows) - 1, max(0, int(round(0.75 * (len(rows) - 1)))))]
    return min(1.0, p75 / float(capacity_usd))


def _model_bar(figs: dict, model: str) -> dict:
    """The weekly bar of `model` (a ladder alias such as `opus`, or a full id) among the per-model bars, else {}."""
    name = str(model or "").lower()
    for key, bar in (figs.get("models") or {}).items():
        if key in name or name in key:
            return bar
    return {}


def out_until(figs: dict, model: str, reserve_pct: float = 95) -> float:
    """The reset time when `model` is out (its weekly bar at or over `reserve_pct`), else 0."""
    bar = _model_bar(figs, model)
    return float(bar["reset"]) if bar and bar["pct"] * 100 >= float(reserve_pct) else 0.0


def pick(model: str, ladder: list, figs: dict, reserve_pct: float, rank) -> tuple[str, str]:
    """(model, why): `model` when it has weekly room, else the next model DOWN the ladder (a lower `rank`) with room,
    never up; when none has room the lowest model and a `why` that names the wait. '' why = no change."""
    if not out_until(figs, model, reserve_pct):
        return model, ""
    down = sorted({m for m in ladder if rank(m) < rank(model)}, key=rank, reverse=True)
    for m in down:
        if not out_until(figs, m, reserve_pct):
            return m, f"{model} is out until {_hm(out_until(figs, model, reserve_pct))}, running on {m}"
    lowest = min(ladder, key=rank) if ladder else model
    return lowest, f"every model of the ladder is out until {_hm(earliest_reset(figs, ladder))}"


def earliest_reset(figs: dict, models) -> float:
    """The earliest reset among the models that have a weekly bar, 0 when none is known."""
    resets = [float(_model_bar(figs, m)["reset"]) for m in models if _model_bar(figs, m)]
    return min(resets) if resets else 0.0


def _hm(t: float) -> str:
    return f"{datetime.fromtimestamp(t):%a %H:%M}" if t else "?"


def balances(cfg) -> dict:
    """The hand-entered credits from project.yaml: {cloud: {usd, entered, expires}, api: {...}} (missing = {})."""
    out = {}
    for name in ("cloud", "api"):
        row = cfg.get(f"usage.{name}_credit") if cfg is not None else None
        if isinstance(row, dict) and isinstance(row.get("usd"), (int, float)):
            out[name] = {"usd": float(row["usd"]), "entered": str(row.get("entered") or ""),
                         "expires": str(row.get("expires") or "")}
    return out


def balance_text(cfg, billing: str = "subscription") -> str:
    """The balance that pays for the session: the subscription, or the API credit with its entry date."""
    api = balances(cfg).get("api")
    if billing == "api":
        if not api:
            return "api key"
        return f"api credit ${api['usd']:g} (entered {api['entered']})" + (f", expires {api['expires']}" if api["expires"] else "")
    return "subscription"


def now_line(figs: dict, model: str, login: str = "default", balance: str = "subscription") -> str:
    """The one line of W59, the same on the watch screen, the status page, `ap status`, the digest and the alerts:
    `now: <model> (login <name>) · 5h N% · week N% [· <model> week N%] · <balance> · resets <t> [· check]`. '' when
    no figure is known."""
    five, week = figs.get("five_hour") or {}, figs.get("seven_day") or {}
    if not model and not five:
        return ""
    tag = " (cli)" if figs.get("source") == "cli" else ""
    parts = [f"now: {model or '?'} (login {login})"]
    if five:
        parts.append(f"5h {round(100 * five['pct'])}%{tag}")
    if week:
        parts.append(f"week {round(100 * week['pct'])}%")
    bar = _model_bar(figs, model) if model else {}
    if bar:
        parts.append(f"{str(model).lower()} week {round(100 * bar['pct'])}%")
    parts.append(balance)
    if five:
        parts.append(f"resets {_hm(five['reset'])}")
    if figs.get("check"):
        parts.append("check")
    return " · ".join(parts)


def write_balance(path, name: str, usd: float, expires: str = "", entered: str = "") -> bool:
    """`ap budget --cloud-credit / --api-credit`: set `usage.<name>_credit: {usd, entered, expires}` in project.yaml
    with a one-line text edit that keeps every comment (the same way as `forecast.write_total`)."""
    import re
    import tempfile
    from datetime import date

    import yaml

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return False
    key = f"{name}_credit"
    when = entered or date.today().isoformat()  # quoted, so YAML keeps the dates as text
    val = "{" + f"usd: {usd:g}, entered: '{when}'" + (f", expires: '{expires}'" if expires else "") + "}"
    head = re.search(r"(?m)^usage:[ \t]*(?:#.*)?$", text)
    if head:
        end = re.search(r"(?m)^\S", text[head.end():])
        stop = head.end() + end.start() if end else len(text)
        block = text[head.end():stop]
        kid = re.search(r"(?m)^([ \t]+)[^\s#]", block)
        m = kid and re.search(rf"(?m)^{re.escape(kid.group(1))}{key}:[ \t]*([^#\n]*?)[ \t]*(?:#.*)?$", block)
        if m:
            block = block[:m.start(1)] + val + block[m.end(1):]
        else:
            block = f"\n{kid.group(1) if kid else '  '}{key}: {val}" + block
        new = text[:head.end()] + block + text[stop:]
    else:
        sep = "" if not text or text.endswith("\n") else "\n"
        new = f"{text}{sep}usage:\n  {key}: {val}\n"
    try:
        got = (yaml.safe_load(new) or {}).get("usage", {}).get(key, {})
        if not isinstance(got, dict) or got.get("usd") != usd:
            return False
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".project-", suffix=".yaml")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, path)
    except (OSError, yaml.YAMLError):
        return False
    return True


# ---------- W60: the source planner (spend every credit before it expires, switch sources on purpose) ----------
REASONS = ("expires soon", "window idle", "cheapest", "limit", "owner")  # the five fixed reason words (greppable)
CLI_ROLES = ("docs", "research", "triage", "unstick", "helper")  # W61 rule 3: the roles a free CLI preset may run
IDLE_DAYS = 2 * 86400  # a weekly window counts as idle only in its last two days
EXPIRY_DAYS = 3 * 86400  # one alert this long before a credit with room expires


def _login_name(folder: str) -> str:
    return "default" if folder in ("", "default") else folder.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def sources(cfg, state, *, now=time.time) -> list:
    """The SOURCES table: one row per login (`login:default`, `login:<name>` for each `agent.fallback` entry with a
    CLAUDE_CONFIG_DIR), `api` (the entered API credit; `needs backend` until an api backend exists) and `cloud` (the
    entered cloud credit; Routine runs only, the planner suggests and never starts one). Each row: {name, kind, folder,
    room (0..1, None = unknown), week (0..1), resets, expires, usd, can_run, off, note}."""
    off = set(str(x) for x in (cfg.get("usage.sources_off") or []))
    rows = []
    folders = [""] + [f for f in (_entry_folder(e) for e in (cfg.get("agent.fallback") or [])) if f]
    for folder in folders:
        name = _login_name(folder)
        figs = figures(state, cfg, folder or "default", now=now)
        five, week = figs.get("five_hour") or {}, figs.get("seven_day") or {}
        room = None
        if five or week:
            room = 1 - max(float(five.get("pct") or 0), float(week.get("pct") or 0))
        rows.append({"name": f"login:{name}", "kind": "login", "folder": folder, "room": room,
                     "five": float(five["pct"]) if five else None,
                     "week": float(week["pct"]) if week else None,
                     "resets": min(x for x in (float(five.get("reset") or 0), float(week.get("reset") or 0)) if x) if (five or week) else 0.0,
                     "week_resets": float(week.get("reset") or 0) if week else 0.0,
                     "expires": 0.0, "usd": 0.0, "can_run": True, "off": f"login:{name}" in off, "note": ""})
    for role in CLI_ROLES:  # W61 rule 3
        value = str(cfg.get(f"models.{role}") or "")
        if ":" in value and f"cli:{value}" not in {r["name"] for r in rows}:
            rows.append({"name": f"cli:{value}", "kind": "cli", "folder": "", "room": None, "five": None, "week": None,
                         "resets": 0.0, "week_resets": 0.0, "expires": 0.0, "usd": 0.0, "can_run": True,
                         "off": f"cli:{value}" in off, "note": "side sessions only, never sleeps the run"})
    for kind in ("api", "cloud"):
        credit = balances(cfg).get(kind)
        usd = float(credit["usd"]) if credit else 0.0
        rows.append({"name": kind, "kind": kind, "folder": "", "room": 1.0 if usd > 0 else 0.0, "five": None, "week": None,
                     "resets": 0.0, "week_resets": 0.0,
                     "expires": _day(credit["expires"]) if credit and credit["expires"] else 0.0, "usd": usd,
                     "can_run": False, "off": kind in off,
                     "note": "needs backend" if kind == "api" else "Routine runs only: the planner suggests and counts"})
    return rows


def _entry_folder(entry) -> str:
    if not isinstance(entry, dict):
        return ""
    env = next(iter(entry.values()), None)
    return str(env.get("CLAUDE_CONFIG_DIR") or "") if isinstance(env, dict) else ""


def _day(s) -> float:
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except (ValueError, TypeError):
        return 0.0


def reason_text(reason: str, row: dict) -> str:
    """One of the five fixed sentences for the log and the screen."""
    name = row["name"].split(":", 1)[-1]
    if reason == "expires soon":
        return f"{row['kind']} credit ${row['usd']:g} expires {datetime.fromtimestamp(row['expires']):%b %d}"
    if reason == "window idle":
        return f"login {name} week {round(100 * (row['week'] or 0))}% used, resets {_hm(row['week_resets'])}"
    if reason == "cheapest":
        return f"login {name} has the most room"
    if reason == "limit":
        return f"login {name} is at its limit until {_hm(row['resets'])}"
    return f"login {name} chosen by the owner"


def plan_source(rows: list, current: str = "login:default", idle_pct: float = 50, *, need: float = 0.0, now=time.time) -> dict:
    """The planner: {source, reason, text} for the next task, or {} to stay. Order: a runnable credit that expires
    soonest with room; a login whose weekly window would reset unused (week under `idle_pct` in its last two days);
    else the current login when it has room (nothing to say); else the login with the most room (`cheapest`), or
    `limit` when the current one is out. Never a source marked off, never `cloud` (Routine runs only)."""
    on = [r for r in rows if not r["off"]]
    cur = next((r for r in on if r["name"] == current), None)
    credits = sorted((r for r in on if r["kind"] in ("api", "cloud") and r["expires"] and r["usd"] > 0 and r["can_run"]),
                     key=lambda r: r["expires"])
    if credits and credits[0]["name"] != current:
        return {"source": credits[0]["name"], "reason": "expires soon", "text": reason_text("expires soon", credits[0])}
    idle = [r for r in on if r["kind"] == "login" and r["name"] != current and r["week"] is not None and r["week_resets"]
            and r["week"] < idle_pct / 100 and 0 < r["week_resets"] - now() <= IDLE_DAYS and (r["room"] or 0) > 0]
    if idle:
        best = min(idle, key=lambda r: r["week"])
        return {"source": best["name"], "reason": "window idle", "text": reason_text("window idle", best)}
    if need and cur is not None and not _fits(cur, need):  # W61 rule 2: the next task would not fit here
        fit = [r for r in on if r["kind"] == "login" and r["name"] != current and _fits(r, need)]
        if fit:
            best = max(fit, key=lambda r: r["room"] or 0)
            left = min(1 - float(b) for b in (cur["five"], cur["week"]) if b is not None)
            return {"source": best["name"], "reason": "limit", "text": f"task needs ~{round(100 * need)}%, {round(100 * left)}% left"}
    if cur is not None and (cur["room"] is None or cur["room"] > 0):
        return {}
    logins = [r for r in on if r["kind"] == "login" and r["name"] != current and (r["room"] or 0) > 0]
    if logins:
        best = max(logins, key=lambda r: r["room"] or 0)
        reason = "limit" if cur is not None and cur["room"] == 0 else "cheapest"
        return {"source": best["name"], "reason": reason, "text": reason_text(reason, best)}
    return {}


def _fits(row: dict, need: float) -> bool:
    """W61 rule 2: every known bar of the login leaves at least `need`."""
    bars = [float(b) for b in (row.get("five"), row.get("week")) if b is not None]
    return all(1 - b >= need for b in bars) if bars else True


def suggest_line(pick: dict) -> str:
    """The one suggestion line: `suggest: switch to login claude-2 (window idle: ...); say ap source claude-2`."""
    if not pick:
        return ""
    name = pick["source"].split(":", 1)[-1]
    return f"suggest: switch to {pick['source']} ({pick['reason']}: {pick['text']}); say ap source {name}"


def expiring(cfg, *, now=time.time) -> list:
    """The credits with room that expire within EXPIRY_DAYS: [(kind, usd, expires)], for the 3-day alert."""
    out = []
    for kind, credit in balances(cfg).items():
        exp = _day(credit["expires"]) if credit["expires"] else 0.0
        if credit["usd"] > 0 and exp and 0 < exp - now() <= EXPIRY_DAYS:
            out.append((kind, credit["usd"], credit["expires"]))
    return out


def expiry_text(kind: str, usd: float, expires: str) -> str:
    return (f"cloud credit ${usd:g} expires {expires}: schedule a Routine run" if kind == "cloud"
            else f"api credit ${usd:g} expires {expires}: set usage.switch auto to use it for low-risk tasks")
