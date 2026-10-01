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


# ---------- P5: live status page ----------
def html_page(md: str, refresh: int = 30) -> str:
    """The report as one self-refreshing HTML page. ponytail: escaped markdown in <pre>, no renderer dependency."""
    import html
    return ("<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta http-equiv=refresh content={int(refresh)}><title>Autopilot status</title>"
            "<style>:root{color-scheme:light dark}body{margin:16px;font:14px/1.5 ui-monospace,Consolas,monospace}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head>"
            f"<body><pre>{html.escape(md)}</pre></body></html>")


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
                    body = html_page(build_report(cfg, plan, state), refresh)
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
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):  # quiet: the URL holds the token
            pass

    return HTTPServer((host, port), Handler)
