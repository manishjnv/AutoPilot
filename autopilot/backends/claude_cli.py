"""Claude Code headless backend: `claude -p --output-format stream-json`, one session per call (fresh or resumed)."""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import time
from pathlib import Path

from ..proc import agent_env, stream_proc
from . import SessionRequest, SessionResult, detect_infra, detect_limit, parse_report, since

progress = logging.getLogger("autopilot")
READ_ONLY_DENY = ["Edit", "Write", "NotebookEdit"]
# Deny-list, not --tools: --tools might also drop the synthetic tool that --json-schema relies on.
WEB_ONLY_DENY = ["Bash", "Agent", "Task"]
# Untrusted issue text: nothing to read (it could copy secrets into a committed task), run or fetch.
NO_TOOLS_DENY = READ_ONLY_DENY + WEB_ONLY_DENY + [
    "Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch", "NotebookRead", "TodoWrite", "MultiEdit", "BashOutput",
    "KillShell", "Skill", "SlashCommand", "ExitPlanMode", "ListMcpResourcesTool", "ReadMcpResourceTool"]
WEB_TOOLS = ["WebFetch", "WebSearch"]
FILE_READ_TOOLS = ["Read", "Glob", "Grep", "LS", "NotebookRead"]


def _num(v, kind=int):
    try:
        return kind(v or 0)
    except (TypeError, ValueError):
        return kind(0)


def parse_usage(data: dict, model: str) -> dict:
    """model -> token counts and cost from the CLI's JSON result; {} when absent or odd."""
    try:
        mu = data.get("modelUsage")
        if isinstance(mu, dict) and mu:
            return {str(m): {"input": _num(u.get("inputTokens")), "output": _num(u.get("outputTokens")),
                             "cache_read": _num(u.get("cacheReadInputTokens")),
                             "cache_write": _num(u.get("cacheCreationInputTokens")), "cost": _num(u.get("costUSD"), float)}
                    for m, u in mu.items() if isinstance(u, dict)}
        u = data.get("usage")
        if isinstance(u, dict):
            return {model: {"input": _num(u.get("input_tokens")), "output": _num(u.get("output_tokens")),
                            "cache_read": _num(u.get("cache_read_input_tokens")),
                            "cache_write": _num(u.get("cache_creation_input_tokens")),
                            "cost": _num(data.get("total_cost_usd"), float)}}
    except Exception:  # noqa: BLE001  odd shapes never break a run
        pass
    return {}


# ponytail: list prices per MTok (input, output) on 2026-10-01; cache reads 0.1x and cache writes 1.25x input.
# Only used to estimate killed sessions (no result event); update when prices change.
PRICES = {"opus": (4.0, 20.0), "sonnet": (2.0, 10.0), "haiku": (1.0, 5.0)}


def partial_usage(raw: str, model: str) -> dict:
    """model -> tokens and estimated cost of a session killed before its `result` event (stuck, timeout), from the
    assistant messages' Messages-API `usage`. Undocumented in stream-json, so missing fields count as 0. A message
    split over several events repeats its usage: the last one per message id counts."""
    last = {}
    for i, ev in enumerate(_events(raw)):
        msg = ev.get("message") if ev.get("type") == "assistant" else None
        if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
            last[msg.get("id") or i] = (str(msg.get("model") or model), msg["usage"])
    out: dict = {}
    for m, u in last.values():
        r = out.setdefault(m, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0})
        for k, src in (("input", "input_tokens"), ("output", "output_tokens"),
                       ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens")):
            r[k] += _num(u.get(src))
    for m, r in out.items():  # unknown model: priced as opus, so the window budget errs on the safe side
        pin, pout = next((p for k, p in PRICES.items() if k in m.lower()), PRICES["opus"])
        r["cost"] = round((r["input"] * pin + r["output"] * pout + r["cache_read"] * pin * 0.1
                           + r["cache_write"] * pin * 1.25) / 1e6, 6)
    return out


def usage_meter():
    """G8: a running token total for one stream, fed line by line (the fields `partial_usage` reads). A message
    split over several events repeats its usage, so the last one per message id counts. `feed.context` is the size
    of the newest message of the main agent: how full the session's context is now (J5)."""
    last: dict = {}

    def feed(line: str) -> int:
        try:
            ev = json.loads(line)
        except ValueError:
            ev = None
        msg = ev.get("message") if isinstance(ev, dict) and ev.get("type") == "assistant" else None
        if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
            last[msg.get("id") or len(last)] = sum(_num(msg["usage"].get(k)) for k in (
                "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            if not ev.get("parent_tool_use_id"):  # a helper agent has a context of its own
                feed.context = last[msg.get("id") or len(last) - 1]
        return sum(last.values())
    feed.context = 0
    return feed


def _events(raw: str):
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            yield ev


def result_event(raw: str) -> dict:
    """The final `result` event of a stream-json run (or a plain JSON result); {} when there is none."""
    for ev in reversed(list(_events(raw))):
        if ev.get("type", "result") == "result":
            return ev
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def window_info(raw: str) -> dict:
    """G1: the usage window as the CLI reports it in the stream's last `rate_limit_event`:
    {five_hour: {pct, reset}, seven_day: {pct, reset}, status}; pct is 0..1, reset is unix seconds. The field names
    are observed, not documented, so anything missing or odd gives {} and the caller keeps its own estimate."""
    info = next((ev.get("rate_limit_info") for ev in reversed(list(_events(raw)))
                 if ev.get("type") == "rate_limit_event"), None)
    wins = info.get("unifiedWindows") if isinstance(info, dict) else None
    out = {}
    for name in ("five_hour", "seven_day"):
        w = wins.get(name) if isinstance(wins, dict) else None
        pct, reset = (w.get("utilization"), w.get("resetsAt")) if isinstance(w, dict) else (None, None)
        real = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (pct, reset))
        if real and 0 <= pct <= 1 and 0 < reset < 4e9:  # another scale, NaN, a broken clock: not trusted
            out[name] = {"pct": float(pct), "reset": float(reset)}
    if out:
        out["status"] = str(info.get("status") or "")
    return out


def config_load(raw: str) -> dict:
    """I1: what the session loaded from the user's own Claude config, from the first `init` event and the SessionStart
    hook events: {plugins: [names], mcp: {connected, other}, mcp_names: [names], hooks: n}. Names and counts only (never
    paths, versions or settings). {} when the CLI says nothing about it (an older CLI)."""
    evs = list(_events(raw))
    init = next((e for e in evs if e.get("type") == "system" and e.get("subtype") == "init"), None)
    if not init or not any(k in init for k in ("plugins", "mcp_servers")):
        return {}

    def named(key):
        items = init.get(key)
        return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
    mcp = named("mcp_servers")
    connected = sum(1 for m in mcp if m.get("status") == "connected")
    return {"plugins": [str(p.get("name")) for p in named("plugins") if p.get("name")],
            "mcp": {"connected": connected, "other": len(mcp) - connected},
            "mcp_names": [str(m.get("name")) for m in mcp if m.get("name")],
            "hooks": sum(1 for e in evs if e.get("subtype") == "hook_started" and e.get("hook_event") == "SessionStart")}


def first_session_id(raw: str) -> str:
    return next((str(ev["session_id"]) for ev in _events(raw) if ev.get("session_id")), "")


def activity(line: str) -> str:
    """What a stream-json line shows the session doing: Claude's short text, or one entry per tool call such as
    `Edit src/app/cli.py`. The live sign that a session is working ('' for anything else)."""
    if '"assistant"' not in line:
        return ""
    ev = next(_events(line), {})
    content = (ev.get("message") or {}).get("content") if ev.get("type") == "assistant" else None
    out = []
    for c in content if isinstance(content, list) else []:
        if isinstance(c, dict) and c.get("type") == "text" and str(c.get("text") or "").strip():
            text = " ".join(str(c["text"]).split())  # Claude's own short status line, as Claude Code shows it
            out.append(f'"{text[:110]}{"…" if len(text) > 110 else ""}"')
        elif isinstance(c, dict) and c.get("type") == "tool_use":
            inp = c.get("input") if isinstance(c.get("input"), dict) else {}
            what = next((inp[k] for k in ("file_path", "command", "pattern", "url", "query", "description")
                         if inp.get(k)), "")
            out.append(f"{c.get('name')} {' '.join(str(what).split())[:100]}".rstrip())
    return "; ".join(out)


def stuck_watch(limit: int):
    """on_line hook: a reason once the agent makes the same tool call `limit` times in a row (0 = never)."""
    last, count = [None], [0]

    def watch(line: str) -> str:
        if not limit or '"tool_use"' not in line:
            return ""
        ev = next(_events(line), {})
        content = (ev.get("message") or {}).get("content") if ev.get("type") == "assistant" else None
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                key = json.dumps([c.get("name"), c.get("input")], sort_keys=True, default=str)
                count[0] = count[0] + 1 if key == last[0] else 1
                last[0] = key
                if count[0] >= limit:
                    return (f"stuck: the agent repeated the same action {limit} times in a row: "
                            f"{c.get('name')} {json.dumps(c.get('input'), default=str)[:300]}")
        return ""
    return watch


def sandbox_settings(cfg) -> dict:
    """P5 egress allowlist on Claude Code's own sandbox: shell commands reach only `sandbox.allowed_domains`, with
    no retry outside the sandbox and no silent fallback when bubblewrap/socat are missing."""
    return {"sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
                        "network": {"allowedDomains": [str(d) for d in cfg.get("sandbox.allowed_domains", [])]}}}


class ClaudeCLIBackend:
    supports_resume = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.binary = self.resolve_binary()

    @staticmethod
    def resolve_binary() -> str:
        found = os.environ.get("AUTOPILOT_CLAUDE_BIN") or os.environ.get("AUTODEV_CLAUDE_BIN") or shutil.which("claude")
        if not found:  # H3: the native installer's folder; a terminal opened before the install has no PATH entry for it
            native = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
            found = str(native) if native.is_file() else None
        if found and found.lower().endswith((".cmd", ".bat")):  # npm's Windows shim only calls this exe: skip cmd.exe
            exe = Path(found).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
            if exe.is_file():
                return str(exe)
        return found or "claude"

    @property
    def shim(self) -> bool:
        """Windows .cmd/.bat shims go through cmd.exe, which mangles multi-line argv; the system text rides on stdin."""
        return self.binary.lower().endswith((".cmd", ".bat"))

    def env(self) -> dict:
        """agent_env plus the Claude Code knobs Autopilot sets: subagent model (U5), prompt cache TTL (U7)."""
        env = agent_env(self.cfg)
        for key, name in (("models.subagent", "CLAUDE_CODE_SUBAGENT_MODEL"),
                          ("agent.cache_ttl", "CLAUDE_CODE_PROMPT_CACHE_TTL")):
            if self.cfg.get(key):
                env[name] = str(self.cfg.get(key))
        if not self.cfg.get("agent.user_config"):  # I2: no claude.ai connectors; --setting-sources can't drop them
            env.setdefault("ENABLE_CLAUDEAI_MCP_SERVERS", "false")
        return env

    def build_cmd(self, req: SessionRequest) -> list[str]:
        c = self.cfg
        cmd = [self.binary, "-p", "--output-format", "stream-json", "--verbose", "--model", req.model,
               "--permission-mode", c.get("agent.permission_mode", "bypassPermissions")]
        if req.resume:
            cmd += ["--resume", req.resume]
        if req.mcp_config:  # only these servers, not the project's own .mcp.json
            cmd += ["--mcp-config", req.mcp_config, "--strict-mcp-config"]
        elif req.no_tools or c.get("sandbox.enabled"):  # no MCP servers at all (they'd run outside the sandbox)
            cmd += ["--strict-mcp-config"]
        if int(c.get("agent.max_turns", 0) or 0):
            cmd += ["--max-turns", str(int(c.get("agent.max_turns")))]
        if req.budget_usd:
            cmd += ["--max-budget-usd", f"{req.budget_usd:.2f}"]
        if c.get("models.fallback"):
            cmd += ["--fallback-model", c.get("models.fallback")]
        if req.effort or c.get("agent.effort"):
            cmd += ["--effort", req.effort or c.get("agent.effort")]
        if req.system_append and not self.shim:
            cmd += ["--append-system-prompt", req.system_append]
        if req.schema and not self.shim:  # quotes through cmd.exe are fragile; the report is then parsed from text
            cmd += ["--json-schema", json.dumps(req.schema, separators=(",", ":"))]
        allowed = c.get("agent.allowed_tools", [])
        if allowed:
            cmd += ["--allowedTools", *allowed]
        denied = list(c.get("agent.disallowed_tools", []))
        if req.read_only:
            denied += READ_ONLY_DENY
        if req.web_only:  # research reads untrusted pages: no shell, no subagents (removed even under bypass)
            denied += WEB_ONLY_DENY
        if req.no_tools:
            denied += NO_TOOLS_DENY
        if c.get("sandbox.enabled"):
            cmd += ["--settings", json.dumps(sandbox_settings(c), separators=(",", ":"))]
            # The sandbox covers shell commands only, so a session gets the web or the repo, never both.
            denied += FILE_READ_TOOLS if req.web_only else WEB_TOOLS
        if denied:
            cmd += ["--disallowedTools", *denied]
        extra = list(c.get("agent.extra_args", []))
        if not c.get("agent.user_config") and not any(str(a).split("=")[0] == "--setting-sources" for a in extra):
            # I2: no user settings, plugins, hooks or MCP servers, so a run acts the same on every PC (smoke plan:
            # ~27k fewer context tokens and ~40 s less per session). The project's own settings and .mcp.json, the
            # --settings flag (sandbox) and the user's CLAUDE.md (not a setting) still load.
            cmd += ["--setting-sources", "project,local"]
        cmd += extra
        return cmd

    def run(self, req: SessionRequest) -> SessionResult:
        cmd = self.build_cmd(req)
        prompt = f"{req.system_append}\n\n---\n\n{req.prompt}" if req.system_append and self.shim else req.prompt
        watch = stuck_watch(int(self.cfg.get("agent.stuck_repeats", 4) or 0))
        started = time.monotonic()
        log = None
        if req.log_path:  # written live: `tail -f` shows what a running session does
            Path(req.log_path).parent.mkdir(parents=True, exist_ok=True)
            log = open(req.log_path, "w", encoding="utf-8")  # noqa: SIM115
            log.write(f"$ {' '.join(cmd[:10])} ...\n\nSTDOUT:\n")

        meter, told = usage_meter(), [float("-inf")]

        def on_line(line: str) -> str:
            if log:
                log.write(line)
                log.flush()
            if req.on_tokens:  # G8: the status line counts this session's tokens while it runs (every 5 s at most)
                tokens = meter(line)
                if tokens and time.monotonic() - told[0] >= 5:
                    told[0] = time.monotonic()
                    if req.on_context:
                        req.on_context(meter.context)
                    req.on_tokens(tokens)
            act = activity(line)
            if act:
                secs = int(time.monotonic() - started)
                progress.info("  ▸ %s · %s · %dm%02ds", req.label or "session", act, secs // 60, secs % 60)
            return watch(line)

        p = None
        try:
            p = stream_proc(cmd, input=prompt, cwd=req.cwd, env=self.env(), timeout=req.timeout_sec, on_line=on_line)
        except OSError as exc:
            return SessionResult(ok=False, error=f"cannot start claude ({self.binary}): {exc}", infra="cli")
        finally:
            if log:
                log.write(f"\n\nSTDERR:\n{p.stderr if p else ''}")
                log.close()
        if p.timed_out or p.stopped:  # killed: no result event, so tokens come from the messages seen so far
            usage = partial_usage(p.stdout, req.model)
            killed = dict(ok=False, session_id=first_session_id(p.stdout), usage=usage,
                          cost=round(sum(u["cost"] for u in usage.values()), 6), window=window_info(p.stdout),
                          config=config_load(p.stdout))
            if p.timed_out:
                return SessionResult(error=f"session timed out after {req.timeout_sec}s", timed_out=True, **killed)
            return SessionResult(error=p.stopped, stuck=True, **killed)

        raw = p.stdout.strip()
        data = result_event(raw)
        text = str(data.get("result", "") or ("" if data else raw))  # never the whole event stream as "text"
        cost = float(data.get("total_cost_usd") or data.get("cost_usd") or 0.0)
        sub = str(data.get("subtype") or "")  # e.g. error_max_turns, error_max_budget_usd
        is_error = bool(data.get("is_error")) or sub.startswith("error") or p.rc != 0 or not data
        err = "" if not is_error else ((f"{sub}: " if sub.startswith("error") else "") + (text or p.stderr))[-3000:]
        report = data.get("structured_output") if isinstance(data.get("structured_output"), dict) else parse_report(text)
        limited, reset_at = detect_limit(text + "\n" + p.stderr) if is_error else (False, None)
        infra = ""
        if is_error and not limited:  # no output at all = a CLI that can't run (seen: a broken npm install)
            infra = detect_infra(text + "\n" + p.stderr) or ("cli" if not raw and not p.stderr.strip() else "")
        totals = {"cost": cost, "usage": parse_usage(data, req.model),
                  "num_turns": _num(data.get("num_turns")), "duration_ms": _num(data.get("duration_ms"))}
        own = since(totals, req.resume_totals) if req.resume else totals
        return SessionResult(
            ok=not is_error, text=text, cost=own["cost"], session_id=str(data.get("session_id", "")),
            report=report or {}, error=err or (f"{infra} failure" if infra else ""), rate_limited=limited, reset_at=reset_at, infra=infra,
            usage=own["usage"],
            num_turns=own["num_turns"], duration_ms=own["duration_ms"], totals=totals, window=window_info(raw),
            config=config_load(raw),
        )
