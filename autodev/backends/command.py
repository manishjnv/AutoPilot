"""Generic backend: any CLI agent (Aider, Codex, a LiteLLM wrapper...). Prompt on stdin, report in stdout."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from . import RATE_LIMIT_RX, SessionRequest, SessionResult, parse_report


class CommandBackend:
    def __init__(self, cfg):
        self.cfg = cfg
        self.template = cfg.get("agent.command")

    def run(self, req: SessionRequest) -> SessionResult:
        cmd = self.template.format(model=shlex.quote(req.model), budget=req.budget_usd or 0,
                                   read_only=int(req.read_only))
        env = {**os.environ, **{k: str(v) for k, v in (self.cfg.get("agent.env", {}) or {}).items()},
               "AUTODEV_MODEL": req.model, "AUTODEV_READ_ONLY": str(int(req.read_only)),
               "AUTODEV_SYSTEM_APPEND": req.system_append}
        try:
            p = subprocess.run(cmd, shell=True, input=req.prompt, cwd=req.cwd, capture_output=True,
                               text=True, timeout=req.timeout_sec, env=env)
        except subprocess.TimeoutExpired:
            return SessionResult(ok=False, error=f"session timed out after {req.timeout_sec}s", timed_out=True)
        out = p.stdout
        if req.log_path:
            Path(req.log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(req.log_path).write_text(f"$ {cmd}\n\nSTDOUT:\n{out}\n\nSTDERR:\n{p.stderr}", encoding="utf-8")
        err = "" if p.returncode == 0 else (p.stderr or out)[-3000:]
        return SessionResult(ok=p.returncode == 0, text=out, report=parse_report(out), error=err,
                             rate_limited=bool(err) and bool(RATE_LIMIT_RX.search(err)))
