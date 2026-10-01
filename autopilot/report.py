"""Human-readable status report (.agent/REPORT.md and `autopilot status`)."""
from __future__ import annotations

import json

from .context import progress_line

VERIFY_KINDS = ("fixer", "audit", "unstick")


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
    out += ["", f"Verification share (fixer, audit, unstick): {round(100 * verif)}%"]
    if verif > 0.2:
        out.append("Verification share is above 20%: checks are using more than intended.")
    return out


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
            f"- {token_footer(state, first)}"]


def build_report(cfg, plan, state) -> str:
    status = state.status_map()
    lines = [f"# Autopilot report — {cfg.get('name', cfg.root.name)}", "",
             f"**Progress:** {progress_line(plan, status)}",
             f"**Cost:** total ${state.cost():.2f} · today ${state.cost(today=True):.2f} · "
             f"sessions {state.session_count()}", "", "## Phases", "",
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
    lines += _this_run(cfg, plan, state) + _tokens_section(state)
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
