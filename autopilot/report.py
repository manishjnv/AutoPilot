"""Human-readable status report (.agent/REPORT.md and `autopilot status`)."""
from __future__ import annotations

import datetime as dt
import json
import time

from .context import progress_line
from .docs import not_verified, warned_tasks

VERIFY_KINDS = ("fixer", "audit", "unstick", "review")


def _n(v: int) -> str:
    return f"{v / 1e6:.1f}M" if v >= 1_000_000 else f"{v / 1e3:.0f}k" if v >= 1000 else str(v)


def _shares(state, since: int):
    """(grand total, per-model rows, per-kind rows, verification share 0..1)."""
    models, kinds = state.token_totals("model", since), state.token_totals("kind", since)
    total = sum(v["total"] for _, v in kinds) or sum(v["total"] for _, v in models)
    verif = sum(v["total"] for k, v in kinds if k in VERIFY_KINDS)
    return total, models, kinds, (verif / total if total else 0.0)


def token_footer(state, since_session: int = 0) -> str:
    total, models, _, verif = _shares(state, since_session)
    if not total:
        return "Tokens: none recorded"
    parts = [f"{m} {_n(v['total'])} {round(100 * v['total'] / total)}%" for m, v in models]
    return f"Tokens: {_n(total)} total — " + " · ".join(parts + [f"verification {round(100 * verif)}%"])


def open_window(state, hours: float = 5) -> dict:
    """G1: the five-hour figure {pct, reset} the CLI last reported, if it is for a window still open; else {}.
    A reset further away than a window lasts means a wrong clock, so that figure is ignored as well."""
    five = (state.get_meta("window_seen", {}) or {}).get("five_hour") or {}
    left = float(five.get("reset") or 0) - time.time()
    return five if "pct" in five and 0 < left <= hours * 3600 + 600 else {}


def window_line(state) -> str:
    """G1: the usage window as the CLI last reported it, or '' when there is no figure for a window still open."""
    five = open_window(state)
    if not five:
        return ""
    week = (state.get_meta("window_seen", {}) or {}).get("seven_day") or {}
    text = (f"Usage window: {round(100 * five['pct'])}% of the 5-hour window "
            f"(resets {dt.datetime.fromtimestamp(five['reset']):%H:%M})")
    return text + (f" · {round(100 * week['pct'])}% of the weekly limit" if "pct" in week else "")


def _run_file(cfg) -> dict:
    try:
        return json.loads((cfg.agent_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def digest(cfg, plan, state) -> str:
    """G3: the run in plain words for the owner: what is built, what is stuck, what needs them, and about how much
    is left (remaining tasks x this run's average per finished task, and only after three finished tasks)."""
    run, status, tasks = _run_file(cfg), state.status_map(), plan.all_tasks()
    count = lambda n: f"{n} task{'' if n == 1 else 's'}"  # noqa: E731
    done = sum(1 for t in tasks if status.get(t.id) == "done")
    here = [r for r in state.tasks("done") if (r["finished_at"] or "") >= (run.get("started_at") or "")]
    lines = [f"Built: {count(len(here))} this run, {done} of {len(tasks)} in total." if run
             else f"Built: {done} of {count(len(tasks))}."]
    # G11: what no check covered. ponytail: reads each task's history file on every call; keep a count in the state
    # if a plan grows to thousands of tasks.
    checked = state.get_meta("features", {}) or {}
    closed = [p for p in plan.phases if (state.phase(p.id) or {"status": "open"})["status"] != "open"]
    gap = not_verified(sum(len(warned_tasks(cfg, p)) for p in plan.phases),
                       sum(1 for p in closed for f in p.features if f["id"] not in checked))
    if gap:
        lines.append(gap)
    blocked = [t.id for t in tasks if status.get(t.id) == "blocked"]
    if blocked:
        lines.append(f"Blocked: {', '.join(blocked)}.")
    asked = sorted(d["id"] for d in state.decisions("OPEN"))
    if asked:
        lines.append(f"Needs you: {', '.join(asked)} (see {cfg.get('needs_you.path', 'docs/NEEDS-YOU.md')}).")
    left = sum(1 for t in tasks if status.get(t.id, "pending") in ("pending", "running"))
    if not left:
        lines.append("Left: nothing.")
    elif run and len(here) >= 3:
        ms, cost = state.db.execute("SELECT COALESCE(SUM(duration_ms),0), COALESCE(SUM(cost),0) FROM sessions "
                                    "WHERE id >= ?", (int(run.get("first_session") or 0),)).fetchone()
        mins = left * ms / len(here) / 60000
        took = f"{round(mins)} min" if mins < 90 else f"{mins / 60:.1f} h"
        lines.append(f"Left: {count(left)}, about {took} and ${left * cost / len(here):.2f} at this run's pace.")
    else:
        lines.append(f"Left: {count(left)}.")
    return "\n".join(lines)


SEP = " │ "
MODEL_SHORT = {"haiku": "Hai", "sonnet": "Son", "opus": "Opus"}
LINE_ORDER = ("state", "task", "tasks", "phases", "blocked", "tok", "models", "cost", "win", "health")
LINE_DROP = ("health", "runtime", "models", "cost", "tok", "win", "task")  # what goes first when the line is too wide


def _runtime(started) -> str:
    try:
        secs = (dt.datetime.now() - dt.datetime.fromisoformat(started)).total_seconds()
    except (TypeError, ValueError):
        return ""
    return "" if secs < 0 else f"{int(secs // 3600)}h{int(secs % 3600 // 60):02d}m" if secs >= 3600 else f"{int(secs // 60)}m"


STATE_WORDS = {"Plan": "Makes the plan.", "Code": "Writes the code.",
               "Test": "Runs the checks.", "Review": "Reviews the work.",
               "Fix": "Repairs a problem.", "Commit": "Saves the work.",
               "Wait": "Waits.", "Block": "Waits for your answer."}


MODEL_NAMES = {"haiku": "Haiku", "sonnet": "Sonnet", "opus": "Opus"}


def _bar(share: float, cells: int = 8) -> str:
    """A bar and the percentage: '███░░░░░ 34%'."""
    share = min(max(float(share), 0.0), 1.0)
    full = round(share * cells)
    return "█" * full + "░" * (cells - full) + f" {round(100 * share)}%"


def status_panel(cfg, plan, state, run: dict, width: int | None = None) -> list[str]:
    """J5: the status by category for the watch window: build, progress, usage, health. Short words. Categories
    share a row while they fit in `width`, so a wide window needs two rows and a narrow one four."""
    status, tasks = state.status_map(), plan.all_tasks()
    done = sum(1 for t in tasks if status.get(t.id) == "done")
    blocked = sum(1 for t in tasks if status.get(t.id) == "blocked")
    live, ids = run.get("status") == "running", [t.id for t in tasks]
    if not live:
        build = ["No build active" if run.get("status") != "finished" else "Complete" if done == len(tasks) else "Stopped"]
    else:
        build = []
        if run.get("task") in ids:
            phases = [p.id for p in plan.phases]
            phase = tasks[ids.index(run["task"])].phase_id
            build = [f"Ph {phases.index(phase) + 1}/{len(phases)}"] if phase in phases else []
            build.append(f"Task {ids.index(run['task']) + 1}/{len(ids)}")
        build.append(STATE_WORDS.get(str(run.get("state") or ""), "Works.").rstrip("."))
        if int(run.get("attempt") or 1) > 1:
            build.append(f"Try {int(run['attempt'])}")
        used = int(run.get("context_tokens") or 0)
        if used:  # ponytail: the limit is a guess from the size (200k, or 1M for a larger session), not a CLI figure
            build.append(f"Context {_bar(used / (200_000 if used <= 200_000 else 1_000_000))}")
    phases_done = sum(1 for p in plan.phases if p.tasks and all(status.get(t.id) == "done" for t in p.tasks))
    asked = len(state.decisions("OPEN"))
    progress = [f"Tasks {done}/{len(tasks)} ({100 * done // len(tasks) if tasks else 0}%)",
                f"Phases {phases_done}/{len(plan.phases)}", f"{blocked} blocked", f"{asked} question{'' if asked == 1 else 's'}"]
    here = [r for r in state.tasks("done") if (r["finished_at"] or "") >= (run.get("started_at") or "")]
    left = sum(1 for t in tasks if status.get(t.id, "pending") in ("pending", "running"))
    if live and left and len(here) >= 3:  # the same pace rule as the digest (G3)
        ms = state.db.execute("SELECT COALESCE(SUM(duration_ms),0) FROM sessions WHERE id >= ?",
                              (int(run.get("first_session") or 0),)).fetchone()[0]
        mins = left * ms / len(here) / 60000
        progress.append(f"~{round(mins)}m left" if mins < 90 else f"~{mins / 60:.1f}h left")
    total, models, _, _ = _shares(state, 0)
    five, week = open_window(state), (state.get_meta("window_seen", {}) or {}).get("seven_day") or {}
    name = lambda m: next((s for k, s in MODEL_NAMES.items() if k in str(m).lower()), str(m))  # noqa: E731
    top = sorted(((m, v["total"]) for m, v in models if v["total"]), key=lambda x: -x[1])[:3]
    usage = [f"5h {_bar(five['pct'])}" if five else "",
             f"Week {_bar(week['pct'])}" if five and "pct" in week else "",
             f"Tok {_n(total)} (" + ", ".join(f"{name(m)} {_n(n)} {round(100 * n / total)}%" for m, n in top) + ")" if total else "Tok 0",
             f"${state.cost():.2f}"]
    health = [f"Git {run['git']}", f"Checks {run['build']}"] if live and run.get("git") and run.get("build") else []
    health.append(_runtime(run.get("started_at")) if live else "")
    cells = [f"{label}: " + " · ".join(x for x in parts if x) for label, parts in
             (("Build", build), ("Progress", progress), ("Usage", usage), ("Health", health)) if any(parts)]
    rows = [cells[0]]
    for cell in cells[1:]:  # side by side while the window is wide enough
        if width and len(rows[-1]) + len(SEP) + len(cell) <= width:
            rows[-1] += SEP + cell
        else:
            rows.append(cell)
    return rows


def status_words(cfg, plan, state, run: dict) -> str:
    """J1: the status line as ASD-STE100 sentences, for the simple view: the work now, the task, the progress."""
    status, tasks = state.status_map(), plan.all_tasks()
    done = sum(1 for t in tasks if status.get(t.id) == "done")
    blocked = sum(1 for t in tasks if status.get(t.id) == "blocked")
    tail = f"{done} of {len(tasks)} tasks complete. " + (
        "No problems." if not blocked else "1 task is blocked." if blocked == 1 else f"{blocked} tasks are blocked.")
    if run.get("status") != "running":
        return ("No build is active. " if run.get("status") != "finished" else
                "Build complete. " if done == len(tasks) else "The build stopped. ") + tail
    head = STATE_WORDS.get(str(run.get("state") or ""), "Works.")
    ids = [t.id for t in tasks]
    if run.get("task") in ids:
        attempt = int(run.get("attempt") or 1)
        head += f" Task {ids.index(run['task']) + 1} of {len(ids)}" + (f", attempt {attempt}." if attempt > 1 else ".")
    time = _runtime(run.get("started_at"))
    return " ".join(x for x in (head, tail, f"Time: {time}." if time else "") if x)


def status_line(cfg, plan, state, run: dict, width: int | None = None) -> str:
    """G8: the state of a run in one line, the same in every view (bottom row of `run` and `watch`, window title,
    live page, `status`). Too wide for `width`: parts go in the order of LINE_DROP; the state word, tasks, phases and
    blocked always stay. `run` is .agent/run.json."""
    status, tasks = state.status_map(), plan.all_tasks()
    done = sum(1 for t in tasks if status.get(t.id) == "done")
    live = run.get("status") == "running"
    total, models, _, _ = _shares(state, 0)
    top = sorted(((m, v["total"]) for m, v in models if v["total"]), key=lambda x: -x[1])[:2]
    short = lambda m: next((s for k, s in MODEL_SHORT.items() if k in str(m).lower()), str(m)[:4])  # noqa: E731
    five = open_window(state)
    parts = {
        "head": "ON" if live else "Done" if run.get("status") == "finished" else "Idle",
        "runtime": _runtime(run.get("started_at")) if live else "",
        "state": str(run.get("state") or "") if live else "",
        "task": f"{run['task']} Try {run.get('attempt') or 1}/{run.get('max_attempts') or '?'}" if live and run.get("task") else "",
        "tasks": f"Task {done}/{len(tasks)} {100 * done // len(tasks) if tasks else 0}%",
        "phases": f"Ph {sum(1 for p in plan.phases if p.tasks and all(status.get(t.id) == 'done' for t in p.tasks))}"
                  f"/{len(plan.phases)}",
        "blocked": f"Blk {sum(1 for t in tasks if status.get(t.id) == 'blocked')}",
        "tok": f"Tok {_n(total + (int(run.get('live_tokens') or 0) if live else 0))}",
        "models": " ".join(f"{short(m)} {round(100 * n / total)}%" for m, n in top),
        "cost": f"Cost ${state.cost():.2f}",
        "win": f"Win {round(100 * five['pct'])}%" if five else "",
        "health": f"Git {run['git']} Bld {run['build']}" if live and run.get("git") and run.get("build") else "",
    }

    def render(skip):
        p = {k: v for k, v in parts.items() if v and k not in skip}
        return SEP.join([" ".join(x for x in (p["head"], p.get("runtime")) if x)] + [p[k] for k in LINE_ORDER if k in p])
    line, skip = render(()), []
    for name in LINE_DROP:
        if width is None or len(line) <= width:
            break
        skip.append(name)
        line = render(skip)
    return line


def _tokens_section(state) -> list[str]:
    total, models, kinds, verif = _shares(state, 0)
    if not total:
        return ["", "## Tokens", "", "(none recorded)"]
    out = ["", "## Tokens", "", "| Model | Input | Output | Cache read | Cache write | Total | Share | Cost |",
           "|---|---|---|---|---|---|---|---|"]
    out += [f"| {m} | {_n(v['input'])} | {_n(v['output'])} | {_n(v['cache_read'])} | {_n(v['cache_write'])} | "
            f"{_n(v['total'])} | {round(100 * v['total'] / total)}% | ${v['cost']:.2f} |" for m, v in models]
    out += ["", "| Kind | Total | Share |", "|---|---|---|"]
    out += [f"| {k} | {_n(v['total'])} | {round(100 * v['total'] / total)}% |" for k, v in kinds]
    out += ["", f"Verification share (fixer, audit, unstick, review): {round(100 * verif)}%"]
    if verif > 0.2:
        out.append("Verification share is above 20%: checks are using more than intended.")
    return out


# ---------- U8: quality telemetry ----------
def task_quality(plan, state) -> dict[str, list[dict]]:
    """risk -> one row per finished (done or blocked) task still in the plan: first model, attempts, first-try pass,
    tokens. Everything comes from the sessions and tasks tables; nothing extra is stored."""
    first = {}
    for r in state.db.execute("SELECT task_id, model FROM sessions WHERE kind='task' AND attempt=1 ORDER BY id"):
        first.setdefault(r["task_id"], r["model"])
    toks = {r[0]: int(r[1] or 0) for r in state.db.execute(
        "SELECT task_id, SUM(tokens_in + tokens_out + tokens_cache_read + tokens_cache_write) FROM sessions "
        "WHERE task_id IS NOT NULL GROUP BY task_id")}
    out: dict[str, list[dict]] = {}
    for r in state.tasks():
        t = plan.task_by_id.get(r["id"])
        if t and r["status"] in ("done", "blocked"):
            a = int(r["attempts"] or 0)
            out.setdefault(t.risk, []).append({"id": t.id, "model": first.get(t.id) or r["model"] or "?", "attempts": a,
                                               "first_try": r["status"] == "done" and a <= 1, "tokens": toks.get(t.id, 0)})
    return out


def cache_share(state) -> tuple[float, int]:
    """(cache reads / all input-side tokens, input-side total)."""
    i, rd, w = state.db.execute("SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_cache_read),0), "
                                "COALESCE(SUM(tokens_cache_write),0) FROM sessions").fetchone()
    total = int(i) + int(rd) + int(w)
    return (int(rd) / total if total else 0.0), total


def quality_tips(cfg, plan, state, min_tasks: int = 5) -> list[str]:
    """Rule-based model ladder suggestions from the finished tasks. Advice only: the owner edits project.yaml."""
    from collections import Counter

    from .config import RISKS
    from .orchestrator import model_rank
    tips = []
    for risk, rows in sorted(task_quality(plan, state).items(), key=lambda kv: RISKS.index(kv[0])):
        if len(rows) < min_tasks:
            continue
        rate = sum(r["first_try"] for r in rows) / len(rows)
        model = Counter(r["model"] for r in rows).most_common(1)[0][0]
        head = f"{risk}: {round(100 * rate)}% of {len(rows)} tasks passed on the first try with {model}"
        if rate >= 0.9 and model_rank(model) > 0:
            tips.append(f"{head}; a cheaper first model may hold (models.ladder.{risk})")
        elif rate < 0.5 and model_rank(model) < 2:
            tips.append(f"{head}; failed attempts cost more than starting stronger (models.ladder.{risk})")
    share, total = cache_share(state)
    ttl = cfg.get("agent.cache_ttl", "")
    if total >= 1_000_000 and share < 0.5:
        tips.append(f"cache reads are only {round(100 * share)}% of input tokens"
                    + ("; the pricier 1h cache writes may not pay off (agent.cache_ttl)" if ttl == "1h"
                       else "; agent.cache_ttl: 1h may help when sessions alternate models"))
    return tips


def _quality_section(cfg, plan, state) -> list[str]:
    rows = task_quality(plan, state)
    if not rows:
        return []
    from .config import RISKS
    out = ["", "## Quality", "", "| Risk | Finished | First try | Avg attempts | Avg tokens |", "|---|---|---|---|---|"]
    for risk in sorted(rows, key=RISKS.index):
        r = rows[risk]
        out.append(f"| {risk} | {len(r)} | {round(100 * sum(x['first_try'] for x in r) / len(r))}% | "
                   f"{sum(x['attempts'] for x in r) / len(r):.1f} | {_n(sum(x['tokens'] for x in r) // len(r))} |")
    share, total = cache_share(state)
    if total:
        out += ["", f"Cache reads: {round(100 * share)}% of input tokens."]
    tips = quality_tips(cfg, plan, state)
    return out + (["", "Suggestions:"] + [f"- {t}" for t in tips] if tips else [])


def config_line(cfg_meta) -> str:
    """I1: one line on what sessions load from the user's Claude config; '' when no session reported it."""
    if not isinstance(cfg_meta, dict) or not cfg_meta:
        return ""
    mcp = cfg_meta.get("mcp") or {}
    n_mcp = int(mcp.get("connected", 0)) + int(mcp.get("other", 0))
    return (f"Sessions load from your Claude config: {len(cfg_meta.get('plugins') or [])} plugins, {n_mcp} MCP servers "
            f"({int(mcp.get('connected', 0))} connected), {int(cfg_meta.get('hooks', 0))} startup hooks")


def _this_run(cfg, plan, state) -> list[str]:
    try:
        run = json.loads((cfg.agent_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    first = int(run.get("first_session") or 0)
    status = state.status_map()
    done = [r for r in state.tasks("done") if (r["finished_at"] or "") >= (run.get("started_at") or "")]
    open_d = state.decisions("OPEN")
    nxt = plan.next_ready(status, cfg.get("scheduling.phase_dependency", "soft"))
    if nxt:
        action = f"{nxt.id} {nxt.title}"
    elif open_d:
        action = f"answer {sorted(d['id'] for d in open_d)[0]} in {cfg.get('needs_you.path', 'docs/NEEDS-YOU.md')}"
    elif any(v == "pending" for v in status.values()):
        action = "pending tasks wait on blocked work: unblock or replan"
    else:
        action = "none: plan complete"
    sessions = state.db.execute("SELECT COUNT(*) FROM sessions WHERE id >= ?", (first,)).fetchone()[0]
    return ["", "## This run", "", f"- Started: {run.get('started_at', '?')} ({run.get('status', '?')})",
            f"- Outcome: {run.get('outcome') or 'still running'}", f"- Tasks done this run: {len(done)}",
            f"- Sessions this run: {sessions}", f"- Open decisions: {len(open_d)}", f"- Next action: {action}",
            f"- {token_footer(state, first)}"] + [f"- {w}" for w in (window_line(state), config_line(state.get_meta("config_load"))) if w]


def build_report(cfg, plan, state) -> str:
    status = state.status_map()
    lines = [f"# Autopilot report — {cfg.get('name', cfg.root.name)}", "",
             f"**Progress:** {progress_line(plan, status)}",
             f"**Cost:** total ${state.cost():.2f} · today ${state.cost(today=True):.2f} · "
             f"sessions {state.session_count()}", "", *[f"- {x}" for x in digest(cfg, plan, state).splitlines()],
             "", "## Phases", "",
             "| Phase | Title | Done | Blocked | Pending | Status | Deploy |", "|---|---|---|---|---|---|---|"]
    for p in plan.phases:
        s = [status.get(t.id, "pending") for t in p.tasks]
        row = state.phase(p.id)
        dep = ""
        if row:
            dep = " ".join(x for x in [("staging ✓" if row["staging_ref"] else ""),
                                       (f"prod {row['prod_status']}" if row["prod_status"] else "")] if x)
        lines.append(f"| {p.id}{' ⚑' if p.priority else ''} | {p.title[:40]} | {s.count('done')} | "
                     f"{s.count('blocked')} | {s.count('pending') + s.count('running')} | "
                     f"{row['status'] if row else 'open'} | {dep} |")
    lines += _this_run(cfg, plan, state) + _tokens_section(state) + _quality_section(cfg, plan, state)
    open_d = state.decisions("OPEN")
    lines += ["", f"## Needs you ({len(open_d)} open)", ""]
    lines += [f"- **{d['id']}** {d['title']}: {' '.join((d['question'] or '').split())[:250]}" for d in open_d] or ["(none)"]
    blocked = state.tasks("blocked")
    lines += ["", f"## Blocked tasks ({len(blocked)})", ""]
    for r in blocked:
        reason = (r["last_error"] or "").strip().splitlines()
        lines.append(f"- **{r['id']}** (attempts {r['attempts']}, ${r['cost'] or 0:.2f}): "
                     f"{(reason[0] if reason else '')[:250]}")
    if not blocked:
        lines.append("(none)")
    approvals = [p.id for p in plan.phases if (state.phase(p.id) or {}) and
                 state.phase(p.id)["prod_status"] == "awaiting_approval"]
    lines += ["", "## Awaiting prod approval", "", ", ".join(approvals) or "(none)", "", "## Recent events", ""]
    for e in state.events(15):
        lines.append(f"- {e['ts']} `{e['kind']}` {e['message'][:200]}")
    return "\n".join(lines) + "\n"


# ---------- M3: public proof numbers ----------
def proof_stats(cfg, plan, state) -> str:
    """The numbers worth publishing after a run, as one markdown table: tasks finished and stuck, first-try rate,
    cost, tokens, wall-clock and agent time, and what the owner had to do. Hours a human spent can't be measured;
    the owner actions are the closest proxy (fill in your own hours when publishing)."""
    status = state.status_map()
    total = len([t for p in plan.phases for t in p.tasks])
    done = sum(v == "done" for v in status.values())
    rows = [r for rs in task_quality(plan, state).values() for r in rs]
    first = sum(r["first_try"] for r in rows)
    t0, t1, n, ms = state.db.execute("SELECT MIN(started_at), MAX(ended_at), COUNT(*), COALESCE(SUM(duration_ms), 0) "
                                     "FROM sessions").fetchone()
    tokens = sum(v["total"] for _, v in state.token_totals("kind"))
    answered = state.decisions("ANSWERED")
    by_user = state.db.execute("SELECT COUNT(*) FROM tasks WHERE note LIKE '%by user%'").fetchone()[0]
    approvals = state.db.execute("SELECT COUNT(*) FROM phases WHERE prod_status IS NOT NULL "
                                 "AND prod_status != 'awaiting_approval'").fetchone()[0]

    def hours(a, b):
        try:
            return f"{(dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 3600:.1f} h"
        except (TypeError, ValueError):
            return "?"
    pct = (lambda a, b: f"{round(100 * a / b)}%" if b else "n/a")
    out = [f"## Autopilot run: {cfg.get('name', cfg.root.name)}", "", "| Measure | Value |", "|---|---|",
           f"| Tasks finished | {done} of {total} ({pct(done, total)}) |",
           f"| Tasks stuck (blocked) | {sum(v == 'blocked' for v in status.values())} |",
           f"| Passed the gate on the first try | {first} of {len(rows)} ({pct(first, len(rows))}) |",
           f"| Agent sessions | {n} |",
           f"| Cost (CLI estimate) | ${state.cost():.2f} |",
           f"| Tokens | {_n(tokens)} |",
           f"| Wall-clock, first to last session | {hours(t0, t1)} |",
           f"| Agent time (sum of sessions) | {ms / 3.6e6:.1f} h |",
           f"| Owner: decisions asked / answered | {len(state.decisions())} / {len(answered)} |",
           f"| Owner: tasks unblocked or skipped | {by_user} |",
           f"| Owner: prod deploys approved or run | {approvals} |",
           "| Owner: hours spent | (fill in) |"]
    return "\n".join(out) + "\n\n" + token_footer(state) + "\n"


# ---------- on-screen help: what the owner can do next ----------
def next_steps(root, running: bool | None = None) -> list[str]:
    """Short, situation-aware hints: no project yet, ready to run, running, decisions waiting, blocked tasks, done."""
    from pathlib import Path

    from . import AGENT_DIR
    root = Path(root)
    if not (root / AGENT_DIR / "project.yaml").exists():
        return ["autopilot quickstart            set up this folder; asks what to build if there is no PLAN.md",
                "autopilot quickstart --idea \"...\"   or describe it in one go"]
    if running is None:
        running = run_journal(root).get("status") == "running"
    tips = []
    try:
        from .config import Config
        from .plan import Plan
        from .state import State
        cfg, plan = Config.load(root), Plan.load(root / AGENT_DIR / "plan.yaml")
        state = State(root / AGENT_DIR / "state.db")
        status, open_d = state.status_map(), state.decisions("OPEN")
        blocked = state.tasks("blocked")
        pending = sum(1 for t in plan.all_tasks() if status.get(t.id, "pending") in ("pending", "running"))
        state.db.close()
    except Exception:  # noqa: BLE001 — no plan yet, or a plan being rewritten
        return ["autopilot quickstart            turn your plan or idea into tasks"]
    path = cfg.get("needs_you.path", "docs/NEEDS-YOU.md")
    if open_d:
        first = sorted(d["id"] for d in open_d)[0]
        tips.append(f"{len(open_d)} question(s) for you in {path}: autopilot answer {first} \"your answer\"")
    if blocked:
        tips.append(f"{len(blocked)} task(s) blocked: fix the spec in .agent/plan.yaml, then autopilot unblock "
                    f"{blocked[0]['id']}")
    if running:
        tips += ["ap watch                        follow the build live (Ctrl+C closes the view only)",
                 "ap stop                         stop before the next session; ap start continues later"]
    elif pending:
        tips += [f"ap start                        build the {pending} remaining task(s)  (ap next: the order)"]
    else:
        tips += ["ap stats                        the results of the build",
                 f"add ideas to {cfg.get('docs.backlog', 'docs/BACKLOG.md')} (one '- idea' per line), then "
                 "autopilot run"]
    return tips + ["ap status                       progress, cost and blocked tasks · ap -h: all commands"]


def next_steps_text(root, running: bool | None = None) -> str:
    return "\nWhat you can do next:\n" + "\n".join(f"  {t}" for t in next_steps(root, running)) + "\n"


# ---------- live view: `autopilot watch` and the "Now" section of the status page ----------
def run_journal(root) -> dict:
    from pathlib import Path

    from . import AGENT_DIR
    try:
        return json.loads((Path(root) / AGENT_DIR / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def live_section(root, lines: int = 25, plan=None) -> str:
    """J7: what the run does now, in the same plain words as the watch window: the last lines of the simple view."""
    from pathlib import Path

    from . import AGENT_DIR
    from .plain import SimpleView, ending
    run = run_journal(root)
    log = Path(root) / AGENT_DIR / "logs" / "autopilot.log"
    ids = plan.all_tasks() if plan is not None else []
    view = SimpleView({t.id: (i + 1, len(ids), t.title, t.description) for i, t in enumerate(ids)})
    # ponytail: reads the full log on each page load (every 30 s); read only the end if a log grows to many MB
    raw = log.read_text(encoding="utf-8", errors="replace").splitlines()[-400:] if log.exists() else []
    tail = ([out for row in raw for out in view.feed(row)] + view.close())[-lines:]
    state = run.get("status", "no run yet")
    head = [f"## Now ({state})", "",
            f"- Start: {str(run.get('started_at', '-')).replace('T', ' ')}. Last update: "
            f"{str(run.get('updated_at', '-')).replace('T', ' ')}."]
    if state == "finished":
        head.append(f"- {ending(run.get('outcome'))}")
    return "\n".join(head + ["", "```"] + tail + ["```", ""]
                     + ["## What you can do next", ""] + [f"- `{t}`" for t in next_steps(root, state == "running")]
                     + [""])


# ---------- P5: live status page ----------
def html_page(md: str, refresh: int = 30, title: str = "Autopilot status") -> str:
    """The report as one self-refreshing HTML page. ponytail: escaped markdown in <pre>, no renderer dependency.
    J8: a small script gets the new text; when the server is gone (the build ended), the last status stays on the
    page below a notice. The script only sets text, never HTML. Without scripts, the page reloads as before."""
    import html
    script = ("setInterval(async()=>{const off=document.getElementById('off');try{"
              "const r=await fetch(location.href,{cache:'no-store'});if(!r.ok)throw 0;"
              "const d=new DOMParser().parseFromString(await r.text(),'text/html');"
              "document.querySelector('pre').textContent=d.querySelector('pre').textContent;"
              "document.title=d.title;off.hidden=true}catch(e){off.hidden=false}}," + str(int(refresh) * 1000) + ")")
    return ("<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<noscript><meta http-equiv=refresh content={int(refresh)}></noscript><title>{html.escape(title)}</title>"
            "<style>:root{color-scheme:light dark}body{margin:16px;font:14px/1.5 ui-monospace,Consolas,monospace}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}"
            "#off{padding:8px 12px;border:2px solid #c80;border-radius:6px;font-weight:bold}</style></head>"
            "<body><p id=off hidden>The build stopped, or the status server is off. This page shows the last status. "
            "For the status now, run: ap status</p>"
            f"<pre>{html.escape(md)}</pre><script type=module>{script}</script></body></html>")


def is_loopback(host: str) -> bool:
    import ipaddress
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def status_server(root, host: str = "127.0.0.1", port: int = 8765, token: str = "", refresh: int = 30):
    """Read-only HTTP server: GET / rebuilds the report from plan.yaml + state.db on every request.
    A non-loopback bind needs a token (?token=...). Raises ValueError when that is missing."""
    import hmac
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path
    from urllib.parse import parse_qs, urlsplit

    from . import AGENT_DIR
    from .config import Config
    from .plan import Plan
    from .state import State

    if not token and not is_loopback(host):
        raise ValueError(f"refusing to serve on {host} without AUTOPILOT_STATUS_TOKEN (the report shows errors "
                         "and decisions); bind to 127.0.0.1 and use an SSH tunnel, or set a token")
    root = Path(root)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlsplit(self.path)
            if url.path != "/":
                return self._send(404, "not found", "text/plain")
            if token:
                given = parse_qs(url.query).get("token", [""])[0]
                if not hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
                    return self._send(403, "forbidden", "text/plain")
            elif not is_loopback(urlsplit("//" + self.headers.get("Host", "")).hostname or ""):
                return self._send(403, "forbidden", "text/plain")  # DNS rebinding: a web page posing as localhost
            try:
                cfg, plan = Config.load(root), Plan.load(root / AGENT_DIR / "plan.yaml")
                state = State(root / AGENT_DIR / "state.db")
                try:
                    run = run_journal(root)  # G8: the status line is the page's first line and the tab's title
                    body = html_page(status_line(cfg, plan, state, run) + "\n\n"
                                     + "\n".join(status_panel(cfg, plan, state, run)) + "\n\n"  # J5: by category
                                     + live_section(root, plan=plan) + "\n"
                                     + build_report(cfg, plan, state), refresh, status_line(cfg, plan, state, run, 0))
                finally:
                    state.db.close()
            except Exception as exc:  # noqa: BLE001  a half-written plan mid-replan must not kill the server
                return self._send(500, f"report unavailable: {type(exc).__name__}", "text/plain")
            self._send(200, body, "text/html")

        def _send(self, code, body, ctype):
            data = body.encode("utf-8")
            self.send_response(code)
            for k, v in (("Content-Type", f"{ctype}; charset=utf-8"), ("Content-Length", str(len(data))),
                         ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                         ("Referrer-Policy", "no-referrer")):  # the token rides in the URL
                self.send_header(k, v)
            try:
                self.end_headers()
                self.wfile.write(data)
            except ConnectionError:  # the browser closed the tab or reloaded mid-write
                pass

        def log_message(self, *a):  # quiet: the URL holds the token
            pass

    return HTTPServer((host, port), Handler)
