"""Claude Code headless backend: `claude -p --output-format stream-json`, one session per call (fresh or resumed)."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from ..proc import agent_env, stream_proc
from . import SessionRequest, SessionResult, detect_limit, parse_report, since

READ_ONLY_DENY = ["Edit", "Write", "NotebookEdit"]
# Deny-list, not --tools: --tools might also drop the synthetic tool that --json-schema relies on.
WEB_ONLY_DENY = ["Bash", "Agent", "Task"]


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


def first_session_id(raw: str) -> str:
    return next((str(ev["session_id"]) for ev in _events(raw) if ev.get("session_id")), "")


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


class ClaudeCLIBackend:
    supports_resume = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.binary = os.environ.get("AUTOPILOT_CLAUDE_BIN") or os.environ.get("AUTODEV_CLAUDE_BIN") or shutil.which("claude") or "claude"

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
        return env

    def build_cmd(self, req: SessionRequest) -> list[str]:
        c = self.cfg
        cmd = [self.binary, "-p", "--output-format", "stream-json", "--verbose", "--model", req.model,
               "--permission-mode", c.get("agent.permission_mode", "bypassPermissions")]
        if req.resume:
            cmd += ["--resume", req.resume]
        if req.mcp_config:  # only these servers, not the project's own .mcp.json
            cmd += ["--mcp-config", req.mcp_config, "--strict-mcp-config"]
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
        if denied:
            cmd += ["--disallowedTools", *denied]
        cmd += list(c.get("agent.extra_args", []))
        return cmd

    def run(self, req: SessionRequest) -> SessionResult:
        cmd = self.build_cmd(req)
        prompt = f"{req.system_append}\n\n---\n\n{req.prompt}" if req.system_append and self.shim else req.prompt
        watch = stuck_watch(int(self.cfg.get("agent.stuck_repeats", 4) or 0))
        log = None
        if req.log_path:  # written live: `tail -f` shows what a running session does
            Path(req.log_path).parent.mkdir(parents=True, exist_ok=True)
            log = open(req.log_path, "w", encoding="utf-8")  # noqa: SIM115
            log.write(f"$ {' '.join(cmd[:10])} ...\n\nSTDOUT:\n")

        def on_line(line: str) -> str:
            if log:
                log.write(line)
                log.flush()
            return watch(line)

        p = None
        try:
            p = stream_proc(cmd, input=prompt, cwd=req.cwd, env=self.env(), timeout=req.timeout_sec, on_line=on_line)
        except OSError as exc:
            return SessionResult(ok=False, error=f"cannot start claude ({self.binary}): {exc}")
        finally:
            if log:
                log.write(f"\n\nSTDERR:\n{p.stderr if p else ''}")
                log.close()
        if p.timed_out:
            return SessionResult(ok=False, error=f"session timed out after {req.timeout_sec}s", timed_out=True)
        if p.stopped:
            return SessionResult(ok=False, error=p.stopped, stuck=True, session_id=first_session_id(p.stdout))

        raw = p.stdout.strip()
        data = result_event(raw)
        text = str(data.get("result", "") or ("" if data else raw))  # never the whole event stream as "text"
        cost = float(data.get("total_cost_usd") or data.get("cost_usd") or 0.0)
        sub = str(data.get("subtype") or "")  # e.g. error_max_turns, error_max_budget_usd
        is_error = bool(data.get("is_error")) or sub.startswith("error") or p.rc != 0 or not data
        err = "" if not is_error else ((f"{sub}: " if sub.startswith("error") else "") + (text or p.stderr))[-3000:]
        report = data.get("structured_output") if isinstance(data.get("structured_output"), dict) else parse_report(text)
        limited, reset_at = detect_limit(text + "\n" + p.stderr) if is_error else (False, None)
        totals = {"cost": cost, "usage": parse_usage(data, req.model),
                  "num_turns": _num(data.get("num_turns")), "duration_ms": _num(data.get("duration_ms"))}
        own = since(totals, req.resume_totals) if req.resume else totals
        return SessionResult(
            ok=not is_error, text=text, cost=own["cost"], session_id=str(data.get("session_id", "")),
            report=report or {}, error=err, rate_limited=limited, reset_at=reset_at, usage=own["usage"],
            num_turns=own["num_turns"], duration_ms=own["duration_ms"], totals=totals,
        )
