"""Generic backend: any CLI agent (Aider, Codex, a LiteLLM wrapper...). Prompt on stdin, report in stdout."""
from __future__ import annotations

import re
import shlex
from pathlib import Path

from ..proc import agent_env, run_proc
from . import SessionRequest, SessionResult, detect_limit, parse_report

# M4: documented invocations of other agent CLIs (docs checked 2026-10-01, not yet run live). Each gets a short argument and reads the
# real prompt from stdin (piped stdin is appended to the argument). Double quotes work in sh and cmd.exe alike.
# ponytail: no read-only variants; read-only sessions run on throwaway branches whose changes are dropped anyway.
_ASK = '"Your full instructions are on standard input. Follow them and end with the requested JSON report."'
PRESETS = {
    "codex": "codex exec --sandbox workspace-write --skip-git-repo-check{model_flag} " + _ASK,
    "gemini": "gemini --approval-mode=yolo{model_flag} -p " + _ASK,
    "opencode": "opencode run --auto{model_flag} " + _ASK,
}
CLAUDE_ALIASES = ("haiku", "sonnet", "opus")
SAFE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}")


def command_template(cfg) -> str:
    return cfg.get("agent.command") or PRESETS.get(str(cfg.get("agent.preset") or ""), "")


def model_flag(cfg, model: str) -> str:
    """` -m <model>` after `agent.model_map` (ladder names → this CLI's models); an unmapped Claude alias gets no
    flag, so the CLI uses its own default model."""
    m = str((cfg.get("agent.model_map", {}) or {}).get(model, model))
    if not SAFE_MODEL.fullmatch(m):  # the command runs through a shell (sh or cmd.exe): no quoting tricks needed
        raise ValueError(f"unsafe model name for agent.preset: {m!r}")
    return "" if m in CLAUDE_ALIASES else f" -m {m}"


class CommandBackend:
    def __init__(self, cfg):
        self.cfg = cfg
        self.template = command_template(cfg)

    def run(self, req: SessionRequest) -> SessionResult:
        cmd = self.template.format(model=shlex.quote(req.model), budget=req.budget_usd or 0,
                                   read_only=int(req.read_only), model_flag=model_flag(self.cfg, req.model))
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
