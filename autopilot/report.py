"""Human-readable status report (.agent/REPORT.md and `autopilot status`)."""
from __future__ import annotations

from .context import progress_line


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
