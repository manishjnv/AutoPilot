"""Generic backend: any CLI agent (Aider, Codex, a LiteLLM wrapper...). Prompt on stdin, report in stdout."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import tempfile
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
    # P03-T01 (N3): docs checked 2026-10-11, not yet run live. Sources: https://kiro.dev/docs/cli/headless/ ,
    # https://cursor.com/docs/cli/headless , https://cursor.com/docs/cli/reference/parameters ,
    # https://aider.chat/docs/config/options.html , https://aider.chat/docs/scripting.html
    # kiro: no _ASK, because a positional argument stops kiro-cli from reading the prompt on stdin.
    # cursor: stdin is not documented (the Chief project, PR #48, uses it), so the short _ASK argument stays. The binary
    # is `agent` since the rename (docs checked 2026-10-12); `command_template` falls back to an installed `cursor-agent`.
    # aider: no stdin prompt, so it reads {prompt_file} (a temp file outside the worktree); git stays with the orchestrator.
    # --trust-all-tools (kiro) and --force (cursor) approve every tool, not only the workspace (like gemini yolo).
    "kiro": "kiro-cli chat --no-interactive --trust-all-tools{model_flag}",
    "cursor": "agent -p --force --trust{model_flag} " + _ASK,
    "aider": "aider --message-file {prompt_file} --yes-always --no-auto-commits --no-dirty-commits --no-gitignore"
             " --no-check-update --no-analytics --no-pretty --no-stream{model_flag}",
    # Q2 copilot: docs checked 2026-10-12, not run live (the live task is Q9). Sources: https://docs.github.com/en/copilot
    # /how-tos/use-copilot-agents/use-copilot-cli . `-p` takes the prompt as an argument (stdin is not documented), so the
    # prompt goes to a temp file outside the worktree (the aider pattern) and `--add-dir` lets copilot read that folder.
    # --allow-all-tools and --no-ask-user approve every tool and never wait for a person; -s is the silent output.
    "copilot": 'copilot -p "Your full instructions are in the file {prompt_path}. Read it, follow it, end with the '
               'requested JSON report." --allow-all-tools --no-ask-user -s --add-dir {prompt_dir}{model_flag}',
}
_MODEL_OPT = {"kiro": "--model", "cursor": "--model", "aider": "--model", "copilot": "--model"}  # aider -m = --message
CLAUDE_ALIASES = ("haiku", "sonnet", "opus")
# Q2: a preset's own names for the ladder aliases, used when agent.model_map does not map them. Copilot accepts Claude
# model names (docs checked 2026-10-12, not run live: only `claude-haiku-4.5` is named in the docs; sonnet and opus stay
# unmapped = Copilot's default model until Q9 records the exact names).
DEFAULT_MODEL_MAP = {"copilot": {"haiku": "claude-haiku-4.5"}}
_FILE_KEYS = ("{prompt_file}", "{prompt_path}", "{prompt_dir}")
SAFE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}")


def command_template(cfg) -> str:
    """The shell template: `agent.command`, or the preset. When the preset's binary is not on PATH but an older name
    of it is (the doctor table's aliases, for example `cursor-agent`), that name is used."""
    own = cfg.get("agent.command")
    if own:
        return own
    preset = str(cfg.get("agent.preset") or "")
    tpl = PRESETS.get(preset, "")
    if tpl:
        from ..doctor import runner
        row = runner(preset)
        if row is not None and not shutil.which(row.binary):
            alias = next((a for a in row.aliases if shutil.which(a)), "")
            if alias:
                tpl = alias + tpl[len(row.binary):]
    return tpl


def model_flag(cfg, model: str) -> str:
    """` -m <model>` (` --model <model>` for kiro, cursor, aider) after `agent.model_map` (ladder names → this CLI's
    models); an unmapped Claude alias gets no flag, so the CLI uses its own default model."""
    preset = str(cfg.get("agent.preset") or "")
    own = (cfg.get("agent.model_map", {}) or {})
    m = str(own.get(model, DEFAULT_MODEL_MAP.get(preset, {}).get(model, model)))
    if not SAFE_MODEL.fullmatch(m):  # the command runs through a shell (sh or cmd.exe): no quoting tricks needed
        raise ValueError(f"unsafe model name for agent.preset: {m!r}")
    opt = _MODEL_OPT.get(preset, "-m")
    return "" if m in CLAUDE_ALIASES else f" {opt} {m}"


class CommandBackend:
    def __init__(self, cfg):
        self.cfg = cfg
        self.template = command_template(cfg)

    def run(self, req: SessionRequest) -> SessionResult:
        # the project context lives in system_append (U7); a generic CLI has no system prompt, so it leads the prompt
        prompt = f"{req.system_append}\n\n---\n\n{req.prompt}" if req.system_append else req.prompt
        pf = ""
        if any(k in self.template for k in _FILE_KEYS):  # P03-T01: CLIs without a stdin prompt (aider, copilot); outside the worktree
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="autopilot-prompt-", suffix=".md",
                                             delete=False) as f:
                f.write(prompt)
            pf = f.name
        try:
            return self._run(req, prompt, pf)
        finally:
            if pf: Path(pf).unlink(missing_ok=True)

    def _run(self, req: SessionRequest, prompt: str, pf: str) -> SessionResult:
        cmd = self.template.format(model=shlex.quote(req.model), budget=req.budget_usd or 0,
                                   read_only=int(req.read_only), model_flag=model_flag(self.cfg, req.model),
                                   prompt_file=f'"{pf}"', prompt_path=pf, prompt_dir=f'"{os.path.dirname(pf)}"')
        env = {**agent_env(self.cfg), "AUTOPILOT_MODEL": req.model, "AUTOPILOT_READ_ONLY": str(int(req.read_only)),
               "AUTOPILOT_SYSTEM_APPEND": req.system_append}
        env.update({"AUTODEV_" + k[10:]: v for k, v in list(env.items()) if k.startswith("AUTOPILOT_")})
        try:
            p = run_proc(cmd, shell=True, input=prompt, cwd=req.cwd, env=env, timeout=req.timeout_sec)
        except OSError as exc:
            return SessionResult(ok=False, error=f"cannot start agent command: {exc}")
        if p.timed_out:
            return SessionResult(ok=False, error=f"session timed out after {req.timeout_sec}s", timed_out=True)
        out = p.stdout
        if req.log_path:
            Path(req.log_path).parent.mkdir(parents=True, exist_ok=True)
            from ..signals import redact  # lazy: signals imports this package
            Path(req.log_path).write_text(redact(f"$ {cmd}\n\nSTDOUT:\n{out}\n\nSTDERR:\n{p.stderr}"), encoding="utf-8")
        if p.stopped:  # W39: `ap stop --now` ended it
            return SessionResult(ok=False, error=p.stopped, text=out)
        err = "" if p.rc == 0 else (p.stderr or out)[-3000:]
        limited, reset_at = detect_limit(p.stderr) if p.rc else (False, None)
        return SessionResult(ok=p.rc == 0, text=out, report=parse_report(out), error=err,
                             rate_limited=limited, reset_at=reset_at)
