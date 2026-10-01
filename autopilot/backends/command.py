"""Generic backend: any CLI agent (Aider, Codex, a LiteLLM wrapper...). Prompt on stdin, report in stdout."""
from __future__ import annotations

import shlex
from pathlib import Path

from ..proc import agent_env, run_proc
from . import SessionRequest, SessionResult, detect_limit, parse_report


class CommandBackend:
    def __init__(self, cfg):
        self.cfg = cfg
        self.template = cfg.get("agent.command")

    def run(self, req: SessionRequest) -> SessionResult:
        cmd = self.template.format(model=shlex.quote(req.model), budget=req.budget_usd or 0,
                                   read_only=int(req.read_only))
        env = {**agent_env(self.cfg), "AUTOPILOT_MODEL": req.model, "AUTOPILOT_READ_ONLY": str(int(req.read_only)),
               "AUTOPILOT_SYSTEM_APPEND": req.system_append}
        env.update({"AUTODEV_" + k[10:]: v for k, v in list(env.items()) if k.startswith("AUTOPILOT_")})
        try:
            # the project context lives in system_append (U7); a generic CLI has no system prompt, so it leads the prompt
            prompt = f"{req.system_append}\n\n---\n\n{req.prompt}" if req.system_append else req.prompt
            p = run_proc(cmd, shell=True, input=prompt, cwd=req.cwd, env=env, timeout=req.timeout_sec)
        except OSError as exc:
            return SessionResult(ok=False, error=f"cannot start agent command: {exc}")
        if p.timed_out:
            return SessionResult(ok=False, error=f"session timed out after {req.timeout_sec}s", timed_out=True)
        out = p.stdout
        if req.log_path:
            Path(req.log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(req.log_path).write_text(f"$ {cmd}\n\nSTDOUT:\n{out}\n\nSTDERR:\n{p.stderr}", encoding="utf-8")
        err = "" if p.rc == 0 else (p.stderr or out)[-3000:]
        limited, reset_at = detect_limit(p.stderr) if p.rc else (False, None)
        return SessionResult(ok=p.rc == 0, text=out, report=parse_report(out), error=err,
                             rate_limited=limited, reset_at=reset_at)
