"""Claude Code headless backend: `claude -p --output-format json`, one fresh session per call."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from ..proc import agent_env, run_proc
from . import SessionRequest, SessionResult, detect_limit, parse_report

READ_ONLY_DENY = ["Edit", "Write", "NotebookEdit"]


class ClaudeCLIBackend:
    def __init__(self, cfg):
        self.cfg = cfg
        self.binary = os.environ.get("AUTOPILOT_CLAUDE_BIN") or os.environ.get("AUTODEV_CLAUDE_BIN") or shutil.which("claude") or "claude"

    @property
    def shim(self) -> bool:
        """Windows .cmd/.bat shims go through cmd.exe, which mangles multi-line argv; the system text rides on stdin."""
        return self.binary.lower().endswith((".cmd", ".bat"))

    def build_cmd(self, req: SessionRequest) -> list[str]:
        c = self.cfg
        cmd = [self.binary, "-p", "--output-format", "json", "--model", req.model,
               "--permission-mode", c.get("agent.permission_mode", "bypassPermissions")]
        if req.budget_usd:
            cmd += ["--max-budget-usd", f"{req.budget_usd:.2f}"]
        if c.get("models.fallback"):
            cmd += ["--fallback-model", c.get("models.fallback")]
        if c.get("agent.effort"):
            cmd += ["--effort", c.get("agent.effort")]
        if req.system_append and not self.shim:
            cmd += ["--append-system-prompt", req.system_append]
        allowed = c.get("agent.allowed_tools", [])
        if allowed:
            cmd += ["--allowedTools", *allowed]
        denied = list(c.get("agent.disallowed_tools", []))
        if req.read_only:
            denied += READ_ONLY_DENY
        if denied:
            cmd += ["--disallowedTools", *denied]
        cmd += list(c.get("agent.extra_args", []))
        return cmd

    def run(self, req: SessionRequest) -> SessionResult:
        cmd = self.build_cmd(req)
        prompt = f"{req.system_append}\n\n---\n\n{req.prompt}" if req.system_append and self.shim else req.prompt
        try:
            p = run_proc(cmd, input=prompt, cwd=req.cwd, env=agent_env(self.cfg), timeout=req.timeout_sec)
        except OSError as exc:
            return SessionResult(ok=False, error=f"cannot start claude ({self.binary}): {exc}")
        if p.timed_out:
            return SessionResult(ok=False, error=f"session timed out after {req.timeout_sec}s", timed_out=True)

        raw = p.stdout.strip()
        if req.log_path:
            Path(req.log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(req.log_path).write_text(f"$ {' '.join(cmd[:8])} ...\n\nSTDOUT:\n{raw}\n\nSTDERR:\n{p.stderr}",
                                          encoding="utf-8")
        data = {}
        try:
            data = json.loads(raw.splitlines()[-1]) if raw else {}
        except (json.JSONDecodeError, IndexError):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {}
        text = str(data.get("result", "") or raw)
        cost = float(data.get("total_cost_usd") or data.get("cost_usd") or 0.0)
        is_error = bool(data.get("is_error")) or p.rc != 0 or not data
        err = "" if not is_error else (text or p.stderr)[-3000:]
        report = data.get("structured_output") if isinstance(data.get("structured_output"), dict) else parse_report(text)
        limited, reset_at = detect_limit(text + "\n" + p.stderr) if is_error else (False, None)
        return SessionResult(
            ok=not is_error, text=text, cost=cost, session_id=str(data.get("session_id", "")),
            report=report or {}, error=err,
            rate_limited=limited, reset_at=reset_at,
        )
