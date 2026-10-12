"""autopilot CLI."""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path

import yaml

from . import AGENT_DIR, __version__

# J15: the same plain-words opening as the README; `ap --help` and the bare `autopilot` banner show it first.
DESCRIPTION = ("Autopilot builds your software project while you are away. You write what you want in plain words "
               "and start it once. You get working software, tested, with a record of every step. "
               "`ap` is the short name of `autopilot`.")
from .config import TEMPLATES, Config, load_yaml
from .plan import Plan, PlanError
from .proc import exclusive_lock

AGENT_FILES = ["project.yaml", "plan.yaml", "BRAIN.md", "DECISIONS.md", "HANDOFF.md"]


def setup_logging(root: Path, verbose: bool):
    logdir = root / AGENT_DIR / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(logdir / "autopilot.log", encoding="utf-8")]
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")


def detect_stack(root: Path) -> str:
    order = ["node", "python", "go", "rust", "java", "docker", "static"]
    for name in order:
        preset = load_yaml(TEMPLATES / "presets" / f"{name}.yaml")
        if any((root / f).exists() for f in preset.get("detect", [])):
            return name
    return "generic"


# ---------------------------------------------------------------- commands
def cmd_init(args):
    root = Path(args.path).resolve()
    ad = root / AGENT_DIR
    ad.mkdir(parents=True, exist_ok=True)
    stack = args.stack or detect_stack(root)
    for name in AGENT_FILES:
        dst = ad / name
        if dst.exists() and not args.force:
            print(f"keep     {dst.relative_to(root)}")
            continue
        shutil.copy(TEMPLATES / "agent" / name, dst)
        print(f"create   {dst.relative_to(root)}")
    # apply stack preset to project.yaml (text edit keeps the template's comments)
    proj_path = ad / "project.yaml"
    proj = load_yaml(proj_path)
    if args.force or proj.get("stack") in (None, "generic"):
        import re
        preset = load_yaml(TEMPLATES / "presets" / f"{stack}.yaml")
        name = args.name or (proj.get("name") if proj.get("name") not in (None, "my-project") else root.name)
        commands = {**(proj.get("commands") or {}), **preset.get("commands", {})}
        if stack == "python" and not shutil.which("ruff"):  # O2: one linter, decided here, never `ruff || flake8`
            commands["lint"] = ["python -m flake8 ."] if shutil.which("flake8") else []
            print("lint:    " + (commands["lint"][0] if commands["lint"] else "none (install ruff for a lint gate)"))
        cmd_block = yaml.safe_dump({"commands": commands}, sort_keys=False, width=200).rstrip() + "\n"
        text = proj_path.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^name:.*$", f"name: {name}", text, count=1)
        text = re.sub(r"(?m)^stack:[^#\n]*", f"stack: {stack}            ", text, count=1)
        text = re.sub(r"(?m)^commands:[ \t]*\n(?:[ \t]+[^\n]*\n)*", lambda m: cmd_block, text, count=1)
        proj_path.write_text(text, encoding="utf-8")
    # gitignore + CLAUDE.md pointer
    gi = root / ".gitignore"
    snippet = (TEMPLATES / "agent" / "gitignore").read_text(encoding="utf-8")
    if not gi.exists() or ".agent/state.db" not in gi.read_text(encoding="utf-8"):
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write(snippet)
    cm = root / "CLAUDE.md"
    cm_snip = (TEMPLATES / "agent" / "CLAUDE.md.snippet").read_text(encoding="utf-8")
    if not cm.exists():
        with open(cm, "a", encoding="utf-8") as fh:
            fh.write(cm_snip)
    elif "## Autopilot (autonomous sessions)" not in (t := cm.read_text(encoding="utf-8")) and "## AutoDev (autonomous sessions)" not in t:
        with open(cm, "a", encoding="utf-8") as fh:
            fh.write(cm_snip)
    elif "ap status" not in t:  # P08-T02: an older Autopilot section gets only the two command lines, once
        lines = cm_snip.rstrip("\n").splitlines()[-2:]
        with open(cm, "a", encoding="utf-8") as fh:
            fh.write(("" if t.endswith("\n") or not t else "\n") + "\n".join(lines) + "\n")
    write_ide_rules(root)  # N6
    from .mcp import register  # N9
    register(root)
    from .gate import write_baseline  # O2: file sizes on day one, so only new growth fails the gate
    if not (ad / "quality_baseline.json").exists():
        print(f"create   {AGENT_DIR}/quality_baseline.json ({write_baseline(root)} files)")
    print(f"\nstack: {stack}")
    if not getattr(args, "quiet", False):  # quickstart does these steps itself
        print("next:  autopilot onboard --plan-doc <your plan.md>   (or edit .agent/plan.yaml)\n"
              "       autopilot validate && autopilot run")


IDE_BEGIN = "<!-- autopilot:begin -->"


def write_ide_rules(root):
    """N6: one marked Autopilot block in the rule file of each IDE present; user text is never changed."""
    block = (TEMPLATES / "agent" / "ide_rules.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    targets = []  # (path, front matter for a new file)
    if (root / ".cursor").is_dir():
        targets.append((root / ".cursor" / "rules" / "autopilot.mdc", "---\ndescription: Autopilot project rules\nalwaysApply: true\n---\n"))
    if (root / ".kiro").is_dir():
        targets.append((root / ".kiro" / "steering" / "autopilot.md", "---\ninclusion: always\n---\n"))
    if (root / ".vscode").is_dir() and (root / ".github").is_dir():  # P10-T06: VS Code alone is not Copilot
        targets.append((root / ".github" / "copilot-instructions.md", ""))
    for name in ("GEMINI.md", "AGENTS.md"):
        if (root / name).is_file():
            targets.append((root / name, ""))
    for path, front in targets:
        old = path.read_bytes() if path.exists() else b""
        rel = path.relative_to(root).as_posix()
        if IDE_BEGIN.encode() in old:
            print(f"keep     {rel}")
            continue
        nl = "\r\n" if b"\r\n" in old else "\n"
        add = (("" if old.endswith(b"\n") else nl) + nl + block.replace("\n", nl)) if old else front + block
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as fh:
            fh.write(add.encode("utf-8"))
        print(f"{'append' if old else 'create'}   {rel}")


def cmd_onboard(args):
    from .backends import SessionRequest, get_backend
    from .context import discovery_pack, render

    root = Path(args.path).resolve()
    if not (root / AGENT_DIR / "project.yaml").exists():
        cmd_init(argparse.Namespace(path=str(root), stack=None, name=None, force=False, quiet=True))
    setup_logging(root, False)  # the session's live activity lines
    cfg = Config.load(root)
    plan_doc = Path(args.plan_doc).read_text(encoding="utf-8") if args.plan_doc else \
        "(no plan document — derive a sensible plan from the repository and README)"
    if len(plan_doc) > 150_000:
        plan_doc = plan_doc[:150_000] + "\n…(truncated)…"
    prompt = render("onboard.md", plan_doc=plan_doc, discovery=discovery_pack(root, cfg))  # N1: read before write
    before = untracked_files(root)
    system = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
    system += "\nFor THIS onboarding session you ARE allowed to edit the .agent files listed in the assignment."
    backend = get_backend(cfg)
    plan_journal(root, current="makes the task list")
    print(f"running onboarding session ({cfg.get('models.onboard', 'opus')}) …")
    res = backend.run(SessionRequest(prompt=prompt, model=cfg.get("models.onboard", "opus"), cwd=str(root),
                                     timeout_sec=int(cfg.get("agent.session_timeout_sec", 3600)),
                                     budget_usd=float(args.budget), system_append=system,
                                     effort=cfg.get("models.effort.onboard", ""), label="onboarding",
                                     log_path=str(root / AGENT_DIR / "logs" / "onboard.log")))
    print(res.report.get("summary") or res.text[-1500:] or res.error)
    new = sorted(untracked_files(root) - before)  # N1: no new document outside .agent/ and CLAUDE.md
    if new:
        print("WARN  onboarding created new files outside .agent/ and CLAUDE.md (kept, check them): " + ", ".join(new))
    if args.plan_doc:  # N13: later runs read this file; a change in it reaches the plan with no command
        remember_plan_source(root, Path(args.plan_doc))
    return cmd_validate(args)


def remember_plan_source(root: Path, doc: Path):
    """N13: `plan_source:` in plan.yaml names the plan document; .agent/plan_source.txt keeps the text last planned from."""
    plan = root / AGENT_DIR / "plan.yaml"
    try:
        rel = doc.resolve().relative_to(root).as_posix()
    except ValueError:
        rel = str(doc.resolve())
    text = plan.read_text(encoding="utf-8") if plan.exists() else ""
    if text and not any(ln.startswith("plan_source:") for ln in text.splitlines()):
        plan.write_text(text.rstrip("\n") + f"\nplan_source: {json.dumps(rel)}\n", encoding="utf-8")
    (root / AGENT_DIR / "plan_source.txt").write_text(doc.read_text(encoding="utf-8"), encoding="utf-8")


def untracked_files(root: Path) -> set:
    """N1: untracked files (git status) outside .agent/ and CLAUDE.md; empty when this is not a git repository."""
    from .proc import run_proc
    try:
        p = run_proc(["git", "status", "--porcelain", "-uall"], cwd=str(root), timeout=60)
    except (OSError, ValueError):
        return set()
    if p.rc != 0:
        return set()
    files = {ln[3:].strip().strip('"') for ln in p.stdout.splitlines() if ln.startswith("??")}
    return {f for f in files if not f.startswith(AGENT_DIR + "/") and f != "CLAUDE.md"}


def plan_journal(root: Path, **kw):
    """J4: while quickstart writes the plan and the tasks, .agent/run.json says so, and every view shows
    "ON · Plan" instead of "Idle". Only while the journal is in the Plan state: a run owns it afterwards."""
    from .state import now
    path = root / AGENT_DIR / "run.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if kw.get("status") != "running" and old.get("state") != "Plan":
            return
        path.write_text(json.dumps({**old, **kw, "updated_at": now()}, indent=1), encoding="utf-8")
    except (OSError, ValueError):
        pass


def cmd_quickstart(args):
    """M5: init → environment fixes → (claude CLI check) → onboard → doctor → optionally run, in one command."""
    from .state import now
    root = Path(args.path).resolve()
    if not (root / AGENT_DIR / "project.yaml").exists():
        cmd_init(argparse.Namespace(path=str(root), stack=None, name=None, force=False, quiet=True))
    if not preflight(Config.load(root)):  # don't start onboarding on a CLI that can't run a session
        return 1
    plan_journal(root, status="running", state="Plan", current="makes the plan", started_at=now(), outcome="",
                 task="", pid=os.getpid())
    try:
        return _quickstart(args, root)
    finally:  # no run started (or it failed before one): the status must not say ON for ever
        plan_journal(root, status="finished", state="Done", current="", outcome="plan ready")


def _quickstart(args, root: Path):
    if args.plan_doc and not Path(args.plan_doc).is_file():
        print(f"plan document not found: {args.plan_doc}")
        return 1
    if not args.plan_doc:  # no plan given: use the project's own, or have Claude write one from the owner's idea
        found = next((root / p for p in ("PLAN.md", "docs/PLAN.md") if (root / p).is_file()), None)
        if found:
            print(f"using {found.relative_to(root)}")
        else:
            idea = getattr(args, "idea", None) or ask_idea()
            if idea and Path(idea).is_file():
                idea = Path(idea).read_text(encoding="utf-8")
            if not (idea or "").strip():
                print("no PLAN.md here and no idea given: describe what to build with --idea \"...\" (or a file)")
                return 1
            found = write_plan(root, idea.strip(), args.budget)
            if not found:
                return 1
        args.plan_doc = str(found)
    if cmd_onboard(args):  # onboard ends with validate: 1 = the plan or config it wrote is invalid
        print("onboarding left an invalid plan or config: fix it (see above), then `autopilot doctor`")
        return 1
    print("\n--- doctor")
    if cmd_doctor(args):
        print("fix the FAIL lines, then `autopilot run`")
        return 1
    if not args.run:
        from .report import next_steps_text
        print("review .agent/plan.yaml and .agent/BRAIN.md (the cheapest moment to change the plan)")
        print(next_steps_text(root, running=False))
        return 0
    return cmd_run(argparse.Namespace(path=str(root), verbose=False, clear_stop=False, max_sessions=None))


def ask_idea(intro: str = "No PLAN.md found. Describe what you want to build: the product, who it is for, the main "
             "features, any\ntech you want. Claude turns it into a full plan. Finish with an empty line.") -> str:
    """Ask the owner in the terminal what to build (several lines, an empty line ends). '' when not interactive."""
    if not sys.stdin.isatty():
        return ""
    print(intro)
    lines = []
    while True:
        try:
            line = input("> " if not lines else "  ")
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines)


def write_plan(root: Path, idea: str, budget: str) -> Path | None:
    """One Claude Code session turns the owner's idea into a detailed PLAN.md (architecture + phased build plan)."""
    from .backends import SessionRequest, get_backend
    from .context import render
    setup_logging(root, False)
    cfg = Config.load(root)
    model = cfg.get("models.plan_writer", "") or cfg.get("models.onboard", "opus")
    print(f"writing PLAN.md from your idea ({model}) …")
    res = get_backend(cfg).run(SessionRequest(
        prompt=render("plan_writer.md", idea=idea), model=model, cwd=str(root), label="writing PLAN.md",
        timeout_sec=int(cfg.get("agent.session_timeout_sec", 3600)), budget_usd=float(budget),
        effort=cfg.get("models.effort.onboard", ""), log_path=str(root / AGENT_DIR / "logs" / "plan_writer.log")))
    plan = root / "PLAN.md"
    if not plan.is_file() or len(plan.read_text(encoding="utf-8", errors="replace")) < 500:
        print(f"the plan session did not write a usable PLAN.md: {res.error or res.text[-500:]}")
        return None
    print(res.report.get("summary") or "PLAN.md written")
    return plan


def preflight(cfg) -> bool:
    """Before quickstart or a run: fix the machine where possible (PATH, the claude CLI), then make sure the agent CLI
    can start. False = it can't, and the reason is printed."""
    from .doctor import FAIL, autofix, check_claude, check_path, check_runner_login
    if cfg is not None and not runner_set(cfg.root):
        if not pick_runner(cfg.root):
            return False
        cfg = Config.load(cfg.root)
    cli = cfg is None or cfg.get("agent.backend", "claude_cli") == "claude_cli"  # no project yet (H5): the default
    rows = [check_path()] + (check_claude(cfg) if cli else [])
    for line in autofix(rows):
        print(f"fix   {line}")
    if cli:
        bad = [r for r in check_claude(cfg) if r[0] == FAIL]
        if bad and bad[0][1] == "claude login" and login_now():  # H2: only here, at the start; never during a run
            bad = [r for r in check_claude(cfg) if r[0] == FAIL]
        if bad:
            print(f"FAIL  {bad[0][1]}: {bad[0][2]}")
            return False
    elif cfg is not None:  # N10: the other runner's own subscription login, before the first session
        level, name, detail = check_runner_login(cfg)
        print(f"{level:<5} {name}: {detail}")
        if level == FAIL:
            return False
    return install_deps(cfg) if cfg is not None else True


def install_deps(cfg) -> bool:
    """N2: project dependencies install without a question; system tools never (the exact command is printed and the
    run stops). Uses commands.setup when set; when empty, runs the standard command and writes it into commands.setup."""
    from .doctor import missing_deps, system_tool_hint
    from .gate import run_commands
    miss = missing_deps(cfg.root)
    if not miss:
        return True
    for m in miss:
        tool = m["tool"]
        if not (shutil.which(tool) or (tool == "python" and (shutil.which("python") or shutil.which("python3")))):
            from .rights import install_system_tool  # N8: through the rights the installer took; never a question
            if install_system_tool(tool, system_tool_hint(tool)):
                print(f"ok    {tool} installed")
                continue
            print(f"FAIL  {tool} is not installed. Install it with: {system_tool_hint(tool)}")
            return False
    setup = cfg.commands("setup")
    cmds = setup or list(dict.fromkeys(c for m in miss for c in venv_commands(cfg.root, m["command"])))
    note = logging.getLogger("autopilot.preflight")
    for cmd in cmds:
        print(f"setup {cmd}")
        note.info("preflight: installing project dependencies: %s", cmd)
        r = run_commands([cmd], cfg.root, int(cfg.get("verify_timeout_sec", 1200)))[0]
        note.info("preflight: %s -> exit %s", cmd, r.rc)
        if r.rc != 0:
            print(f"FAIL  {cmd} failed (exit {r.rc}):\n{r.output[-1500:]}")
            return False
    if not setup:
        remember_setup(cfg.root / AGENT_DIR / "project.yaml", cmds)
    return True


def venv_commands(root, cmd: str) -> list[str]:
    """A bare `pip install ...` never runs on the system Python: use the active venv, a project venv, or make .venv."""
    if not cmd.startswith("pip install "):
        return [cmd]
    pip = f"-m pip {cmd[4:]}"
    py = "python" if shutil.which("python") else "python3"
    if os.environ.get("VIRTUAL_ENV"):
        return [f"{py} {pip}"]
    sub = "Scripts\\python.exe" if os.name == "nt" else "bin/python"
    for n in (".venv", "venv", "env"):
        if (Path(root) / n / "pyvenv.cfg").is_file():
            return [f"{n}\\{sub} {pip}" if os.name == "nt" else f"{n}/{sub} {pip}"]
    return [f"{py} -m venv .venv", f".venv\\{sub} {pip}" if os.name == "nt" else f".venv/{sub} {pip}"]


def remember_setup(proj_path: Path, cmds: list[str]) -> None:
    """N2: write `commands.setup` as a text edit, so the comments of project.yaml stay (same approach as cmd_init)."""
    import re
    text = proj_path.read_text(encoding="utf-8")
    value = json.dumps(cmds)
    new, n = re.subn(r"(?m)^([ \t]+setup:)[ \t]*\[\]", lambda m: f"{m.group(1)} {value}", text, count=1)
    if not n:
        new, n = re.subn(r"(?m)^(commands:[ \t]*(?:#.*)?)$", lambda m: f"{m.group(1)}\n  setup: {value}", text, count=1)
    if n:
        proj_path.write_text(new, encoding="utf-8")
        print(f"setup saved in commands.setup of {proj_path.name}")


def runner_set(root: Path) -> bool:
    """N3: does the project's own project.yaml choose the agent CLI? One reader: `doctor.runner_chosen`."""
    from .doctor import runner_chosen
    return runner_chosen(root)


def pick_runner(root: Path) -> bool:
    """N3: no runner set -> write the first installed, logged-in agent CLI on PATH. False = none: the neutral list of
    every runner with its install command (Q1), never 'Install Claude Code' first. A claude that is installed but
    logged out stays the default with no write, so the H2 login offer still runs. The runner `ap setup` chose on this
    PC (Q3, `~/.autopilot/runner`) is written when it is installed and nothing else is logged in."""
    from .backends.claude_cli import ClaudeCLIBackend
    from .doctor import detect_runner, installed_runners, no_runner_text, runner
    if os.environ.get("AUTOPILOT_CLAUDE_BIN") or os.environ.get("AUTODEV_CLAUDE_BIN"):
        return True  # an explicit claude binary is a choice: keep the claude_cli default
    choice = detect_runner()
    if not choice:
        row = runner(setup_choice())
        if row is not None and row.which():
            choice = row.key
    if choice:
        if not remember_runner(Path(root) / AGENT_DIR / "project.yaml", choice):
            return False
        print(f"runner: {runner(choice).binary} (found on PATH)")
        return True
    if shutil.which(ClaudeCLIBackend.resolve_binary()):
        return True
    found = installed_runners()
    if found:  # installed, logged out: say which login is missing, nothing else
        row = found[0][0]
        print(f"FAIL  {row.binary} is installed but not logged in: run `{row.login}`, then start again")
        return False
    print(f"FAIL  {no_runner_text()}")
    return False


def setup_choice() -> str:
    """Q3: the runner `ap setup` chose on this PC (one word in `~/.autopilot/runner`), '' when none."""
    try:
        return (_recent_file().with_name("runner").read_text(encoding="utf-8").strip())
    except OSError:
        return ""


def remember_runner(proj_path: Path, choice: str) -> bool:
    """N3: write agent.backend (and agent.preset) as a text edit after the `agent:` line, so comments stay. The new
    text is parsed first: when it would not give exactly the wanted values, nothing is written."""
    import re
    want = {"backend": "claude_cli"} if choice == "claude_cli" else {"backend": "command", "preset": choice}
    text = proj_path.read_text(encoding="utf-8") if proj_path.exists() else ""
    m = re.search(r"(?m)^agent:[ \t]*(?:#.*)?$", text)
    if m:
        nxt = re.search(r"(?m)^([ \t]+)\S", text[m.end():])
        ind = nxt.group(1) if nxt else "  "
        new = text[:m.end()] + "".join(f"\n{ind}{k}: {v}" for k, v in want.items()) + text[m.end():]
    else:
        sep = "" if not text or text.endswith("\n") else "\n"
        new = text + sep + "agent:" + "".join(f"\n  {k}: {v}" for k, v in want.items()) + "\n"
    try:
        old_d, new_d = (yaml.safe_load(text) or {}), (yaml.safe_load(new) or {})
        old_a = old_d.get("agent") or {}
        ok = (isinstance(new_d.get("agent"), dict) and new_d["agent"] == {**old_a, **want}
              and {k: v for k, v in new_d.items() if k != "agent"} == {k: v for k, v in old_d.items() if k != "agent"})
    except (yaml.YAMLError, AttributeError, TypeError):
        ok = False
    if not ok:
        print("FAIL  set agent.backend in .agent/project.yaml (see REFERENCE.md)")
        return False
    proj_path.parent.mkdir(parents=True, exist_ok=True)
    proj_path.write_text(new, encoding="utf-8")
    return True


def login_now(row=None, *, env: dict | None = None, say=print) -> bool:
    """H2 + Q13: with a terminal, run the login of `row` (the claude row when None). The address and the code are printed
    as text in every case; a machine with no desktop (WSL, SSH, a container) runs the headless form. False = no terminal
    (never ask), the owner stops, or the login did not finish."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    from .doctor import runner
    from .login import login_runner
    row = row or runner("claude_cli")
    if row.key == "claude_cli":
        from .backends.claude_cli import ClaudeCLIBackend
        exe = shutil.which(ClaudeCLIBackend.resolve_binary()) or ClaudeCLIBackend.resolve_binary()  # AUTOPILOT_CLAUDE_BIN counts
    else:
        exe = row.which()
    if not exe:
        return False
    if row.key == "claude_cli":
        say("Claude Code is not logged in (a paid Claude plan is necessary). Ctrl+C stops.")
    try:
        return login_runner(row, exe, env=env, say=say)
    except (EOFError, KeyboardInterrupt, OSError):
        return False

def safe_folder(p: Path) -> str:
    """H5: why a folder must not hold a new project ('' = fine). Sessions run with no prompts, so they get the folder."""
    home = Path.home().resolve()
    if p == home:
        return "this is your home folder"
    if p.parent == p or home.is_relative_to(p):
        return "this folder contains your home folder, or is a drive or filesystem root"
    return ""


def ask_folder(offer: Path) -> Path:
    """H5: ask where the project goes until the answer is safe. Enter takes `offer`."""
    while True:
        raw = input(f"Folder for the project (Enter = {offer}): ").strip().strip('"')
        p = (Path.cwd() / Path(raw).expanduser()).resolve() if raw else offer.resolve()
        if why := safe_folder(p):
            print(f"not this one: {why}. Choose another.")
        elif p.is_file():
            print("not this one: it is a file. Choose another.")
        elif (p / AGENT_DIR / "project.yaml").exists():
            print(f"{p} already has an Autopilot project: the start continues it.")
            return p
        elif p.is_dir() and (items := sorted(x.name for x in p.iterdir())):
            print(f"{p} is not empty ({len(items)} entries): {', '.join(items[:10])}{' …' if len(items) > 10 else ''}")
            print("  1  use this folder\n  2  choose a different folder")
            if input("> ").strip() == "1":
                return p
        else:
            return p


CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".php",
                 ".sh", ".html", ".css", ".toml", ".json", ".yaml", ".yml"}


def idea_file(root: Path) -> str:
    """N5.5: the idea from a file: IDEA.md, or the one .md file (under 2000 words) in a folder with no code files
    and no subfolders. '' = none."""
    try:
        seen = [x for x in root.iterdir() if not x.name.startswith(".")]
        md = [x for x in seen if x.is_file() and x.suffix.lower() == ".md"]
        pick = next((x for x in md if x.name.lower() == "idea.md"), None)
        if pick is None and len(md) == 1 and not any(x.is_dir() or x.suffix.lower() in CODE_SUFFIXES for x in seen):
            pick = md[0]
        text = pick.read_text(encoding="utf-8", errors="replace").strip() if pick else ""
    except OSError:
        return ""
    return text if pick is not None and (pick.name.lower() == "idea.md" or len(text.split()) < 2000) else ""


def needs_you(plan: Plan) -> bool:
    """N5.5: does the plan hold a task for the owner or a critical one? Then the start keeps its question."""
    return any(t.owner_only or t.risk == "critical" for t in plan.all_tasks())


def three_lines(plan: Plan) -> str:
    """N5.5: done / open / next in three lines."""
    tasks = plan.all_tasks()
    done = sum(1 for t in tasks if t.status == "done")
    nxt = plan.next_ready({})
    return f"Done: {done} of {len(tasks)} tasks.\nOpen: {len(tasks) - done}.\n" + (
        f"Next: {nxt.id} {nxt.title}" if nxt else "Next: none yet.")


def guided_start(ask: bool = False) -> int:
    """H5: plain `autopilot` in a terminal, no project here: ask the idea and the folder, then quickstart and run.
    N5.5: the idea may come from a file; a plan with no owner or critical task starts at once, unless `ask`."""
    from .docs import slug
    try:
        idea = idea_file(Path.cwd())
        if idea:
            root = Path.cwd().resolve()
            if why := safe_folder(root):
                print(f"not building in this folder: {why}.")
                return -1
        else:
            idea = ask_idea("What do you want to build? The product, who it is for, the main features, any tech you "
                            "want.\nFinish with an empty line.").strip()
            if not idea:
                return -1
            root = ask_folder(Path.cwd() / slug((idea.splitlines()[0]), 30, "myapp"))
        if not preflight(None):  # the login is checked before anything is created
            return 1
        rc = cmd_quickstart(argparse.Namespace(path=str(root), plan_doc=None, budget="15", run=False, idea=idea))
        if rc:
            return rc
        plan = Plan.load(root / AGENT_DIR / "plan.yaml")
        print("\nThe plan:")
        for ph in plan.phases:
            print(f"  {ph.id}  {ph.title}  ({len(ph.tasks)} tasks)")
        print(f"  {len(plan.phases)} phases, {len(plan.all_tasks())} tasks")
        print("The build runs for hours. It uses your Claude plan.\nIt works without asking you.")
        if not ask and not needs_you(plan):  # N5.5
            print("Starting. Stop with ap stop.\n" + three_lines(plan))
            return cmd_run(argparse.Namespace(path=str(root), verbose=False, clear_stop=False, max_sessions=None))
        print("  1  start now\n  2  not now")
        if input("> ").strip() == "1":
            return cmd_run(argparse.Namespace(path=str(root), verbose=False, clear_stop=False, max_sessions=None))
        print(f"Start later with: autopilot run -C {root}")
        return 0
    except KeyboardInterrupt:
        print()
        return 130
    except EOFError:
        print()
        return 0


def folder_case(root: Path) -> str:
    """N4: what plain `ap` finds here: "agent" (.agent/project.yaml), "empty" (no entries but dotfiles, e.g. a bare
    git repo) or "code" (files or documents, no project)."""
    if (root / AGENT_DIR / "project.yaml").exists():
        return "agent"
    try:
        return "code" if any(not x.name.startswith(".") for x in root.iterdir()) else "empty"
    except OSError:
        return "empty"


def adopt_start(root: Path) -> int:
    """N4: plain `autopilot` in a terminal, code and no .agent/: init, read-first onboarding, one-screen summary, start?"""
    from .report import adopt_summary
    if why := safe_folder(root):
        print(f"not adopting this folder: {why}.")
        return -1
    try:
        if not preflight(None):  # the login is checked before anything is created
            return 1
        print(f"Found a project without Autopilot in {root}. Reading it …")
        cmd_init(argparse.Namespace(path=str(root), stack=None, name=None, force=False, quiet=True))
        rc = cmd_onboard(argparse.Namespace(path=str(root), plan_doc=None, budget="15", run=False, idea=None))
        if rc:
            return rc
        print("\n" + adopt_summary(root))
        print("The build runs for hours. It uses your Claude plan.\nIt works without asking you.")
        print("  1  start now\n  2  not now")
        if input("> ").strip() == "1":
            return cmd_run(argparse.Namespace(path=str(root), verbose=False, clear_stop=False, max_sessions=None))
        print(f"Start later with: autopilot run -C {root}")
        return 0
    except KeyboardInterrupt:
        print()
        return 130
    except EOFError:
        print()
        return 0


def cmd_validate(args):
    root = Path(args.path).resolve()
    cfg = Config.load(root)
    ok = True
    blocking = cfg.blocking_errors()
    for e in blocking:
        ok = False
        print(f"config  ERROR {e}")
    for e in cfg.validate():
        if e not in blocking:
            print(f"config  WARN  {e}")
    try:
        plan = Plan.load(root / AGENT_DIR / "plan.yaml")
        tasks = plan.all_tasks()
        print(f"plan    OK    {len(plan.phases)} phases, {len(tasks)} tasks")
        weak = [t.id for t in tasks if len(t.acceptance_criteria) < 1]
        if weak:
            print(f"plan    WARN  {len(weak)} tasks without acceptance criteria: {', '.join(weak[:10])}"
                  f"{' …' if len(weak) > 10 else ''}")
        wide = [t.id for t in tasks if not t.files_in_scope and not t.owner_only and t.status != "done"]
        if wide:  # O1: an empty scope means the whole repo, so the task runs alone and nothing is gated
            print(f"plan    WARN  {len(wide)} tasks without files_in_scope (whole repo, run alone): "
                  f"{', '.join(wide[:10])}{' …' if len(wide) > 10 else ''}")
    except PlanError as e:
        ok = False
        for err in e.errors:
            print(f"plan    ERROR {err}")
    except FileNotFoundError:
        ok = False
        print("plan    ERROR .agent/plan.yaml not found — run `autopilot init`")
    return 0 if ok else 1


def enable_vt() -> bool:
    """Can this terminal take escape codes? Windows consoles need virtual terminal mode switched on first."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel, mode = ctypes.windll.kernel32, ctypes.c_uint()
        handle = kernel.GetStdHandle(-11)  # stdout
        return bool(kernel.GetConsoleMode(handle, ctypes.byref(mode)) and kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:  # noqa: BLE001
        return False


class StatusBar:
    """G8: keeps one line on the terminal's bottom row and current, while normal output scrolls above it. The same
    line goes into the window title. Only on a real terminal: a pipe, a log file or AUTOPILOT_PLAIN=1 gets nothing,
    so no escape code ever lands in a file. `line(width)` gives the text; a failing `line` is skipped."""

    def __init__(self, line, out=None, every: float = 1.0, bold: bool = False, height: int = 1, title=None):
        self.line, self.out, self.every, self.bold = line, out or sys.stdout, every, bold
        self.height, self.title = height, title  # J5: `line` may give `height` rows (one for each "\n")
        self.on, self.rows, self.lock, self.done = False, 0, threading.Lock(), threading.Event()

    def _write(self, text: str):
        with self.lock:
            try:
                self.out.write(text)
                self.out.flush()
            except Exception:  # noqa: BLE001 — a status line must never break a run
                pass

    def start(self) -> bool:
        if os.environ.get("AUTOPILOT_PLAIN") or not self.out.isatty() or not enable_vt():
            return False
        self.on, self.rows = True, shutil.get_terminal_size().lines
        if self.rows < self.height + 6:  # a very small window: one row only
            self.height = 1
        h = self.height
        # fresh lines, then rows 1..n-h scroll and the cursor waits on the last of them; the rows below are the line's
        self._write("\n" * (h + 1) + f"\x1b[1;{self.rows - h}r\x1b[{self.rows - h};1H")
        if self.every:
            threading.Thread(target=self._loop, daemon=True).start()
        return True

    def _loop(self):
        while not self.done.wait(self.every):
            self.draw()

    def draw(self):
        if not self.on:
            return
        try:
            size = shutil.get_terminal_size()
            # only printable characters reach the terminal: a control code in the text must not act on it
            clean = lambda s: "".join(c for c in str(s) if c.isprintable())[:size.columns - 1]  # noqa: E731
            raw, h = str(self.line(size.columns - 1)), self.height
            texts = [clean(s) for s in (raw.split("\n") + [""] * h)[:h]] if h > 1 else [clean(raw)]
            title = clean(self.title()) if self.title else texts[0]
        except Exception:  # noqa: BLE001 — e.g. the plan is being rewritten right now: keep the last line
            return
        refit = ""
        if size.lines != self.rows:  # the window was resized: move the reserved rows
            # the old rows are now inside the part that scrolls: clear them, or their text stays behind new lines
            old = "".join(f"\x1b[{self.rows - i};1H\x1b[2K" for i in range(h))
            self.rows, refit = size.lines, f"\x1b7{old}\x1b[1;{size.lines - h}r\x1b8"
        # save the cursor, draw the bottom rows, put the cursor back; then the window title
        from .plain import tint
        # J3: each fact in a row has its color; the title stays plain
        rows = "".join(f"\x1b[{self.rows - h + 1 + i};1H\x1b[2K{tint(t, self.bold)}" for i, t in enumerate(texts))
        self._write(f"{refit}\x1b7{rows}\x1b8\x1b]0;{title}\x07")

    def stop(self):
        if not self.on:
            return
        self.done.set()
        self.on = False
        # whole-screen scrolling again, the rows cleared from the bottom up
        self._write("\x1b[r" + "".join(f"\x1b[{self.rows - i};1H\x1b[2K" for i in range(self.height)))


def status_reader(root: Path, words: bool = False):
    """line(width) for the project at `root`: the status line, read fresh from run.json and state.db on each call.
    It only reads, and keeps its own database connection, so use one reader per thread. `words`: in plain words."""
    from .report import run_journal, status_line, status_panel, status_words
    from .state import State
    box: dict = {}

    def line(width=None):
        plan_file = root / AGENT_DIR / "plan.yaml"
        stamp = plan_file.stat().st_mtime
        if box.get("stamp") != stamp:  # first call, or the plan gained tasks
            if "state" in box:
                box["state"].db.close()
            box.update(cfg=Config.load(root), plan=Plan.load(plan_file), state=State(root / AGENT_DIR / "state.db"),
                       stamp=stamp)
        if words == "panel":
            return "\n".join(status_panel(box["cfg"], box["plan"], box["state"], run_journal(root), width))
        if words:
            return status_words(box["cfg"], box["plan"], box["state"], run_journal(root))
        return status_line(box["cfg"], box["plan"], box["state"], run_journal(root), width)
    return line


def hints(root: Path, running: bool | None, color: bool) -> str:
    """The "What you can do next" text, with each command in color on a terminal (J3)."""
    from .plain import paint
    from .report import next_steps_text
    out = []
    for row in next_steps_text(root, running).split("\n"):
        cmd, gap, rest = row.strip().partition("  ")
        out.append(f"  {paint(cmd, 'cyan', color)}{gap}{rest}" if row.startswith("  ap ") else row)
    return "\n".join(out)


def cmd_preflight(args):
    """Phase 0: credentials the plan needs are set and work, else exit 1 (also called by `run`)."""
    from .commands.preflight import report_text, run_preflight
    root = Path(args.path).resolve()
    try:
        plan = Plan.load(root / AGENT_DIR / "plan.yaml")
    except (PlanError, FileNotFoundError) as e:
        print(f"preflight ERROR plan.yaml: {e}")
        return 1
    rows = run_preflight(plan, Config.load(root))
    print(report_text(rows))
    return 1 if any(r["status"] != "ok" for r in rows) else 0


def headless() -> bool:
    """N5.5: no screen to open a page on: SSH, no terminal, or Linux with no display."""
    return bool(os.environ.get("SSH_CONNECTION")) or not sys.stdout.isatty() or (
        sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")))


def open_page_once(root: Path, url: str):
    """N5.5: the first run in a project opens the status page; later runs and headless sessions do not."""
    marker = root / AGENT_DIR / "page_opened"
    if marker.exists() or headless():
        return
    import webbrowser
    try:  # on a machine without a browser this does nothing
        marker.write_text(url, encoding="utf-8")
        webbrowser.open(url, new=2)
    except Exception:  # noqa: BLE001
        pass


def cmd_run(args):
    from .orchestrator import Orchestrator, run_supervised

    root = Path(args.path).resolve()
    setup_logging(root, args.verbose)
    stop = root / AGENT_DIR / "STOP"
    if stop.exists() and args.clear_stop:
        stop.unlink()
    if run_active(root):  # a second `autopilot run` while one is going: show that run instead of failing
        print("a run is already active for this project; following it (Ctrl+C stops watching, not the run)\n")
        return cmd_watch(argparse.Namespace(path=str(root), lines=20))
    if not preflight(Config.load(root)):  # every session would fail: stop before the first one
        return 1
    if cmd_preflight(args):  # missing or broken credentials: stop before any work
        return 1
    url = "" if getattr(args, "no_page", False) else start_status_page(root)
    if url and not getattr(args, "no_browser", False) and not os.environ.get("AUTOPILOT_NO_BROWSER"):
        open_page_once(root, url)
    if not sys.stdout.isatty() and not getattr(args, "no_watch", False) and not os.environ.get("AUTOPILOT_NO_BROWSER"):
        how = open_watch_window(root)  # no terminal of our own: put `autopilot watch` on screen
        if how:
            print(f"opened a {how} with `ap watch`", flush=True)
    print(f"\nFollow this run: {url + ' in a browser, or ' if url else ''}`ap watch` in another terminal "
          f"(log: {root / AGENT_DIR / 'logs' / 'autopilot.log'})\n", flush=True)
    bar = StatusBar(status_reader(root))  # G8: the status line stays on the bottom row while the run prints above it
    bar.start()
    try:
        outcome = run_supervised(root, lambda: Orchestrator(root, max_sessions=args.max_sessions,
                                                            no_prod=getattr(args, "no_prod", False)))
    finally:
        bar.stop()
    print(f"\nrun finished: {outcome}\nreport: {root / AGENT_DIR / 'REPORT.md'}")
    from .report import next_steps_text
    print(next_steps_text(root, running=False))
    return 0


def _open_state(root: Path):
    from .state import State
    cfg = Config.load(root)
    plan = Plan.load(root / AGENT_DIR / "plan.yaml")
    state = State(root / AGENT_DIR / "state.db")
    state.sync_plan(plan)
    return cfg, plan, state


def cmd_status(args):
    from .report import build_report, run_journal, status_line
    cfg, plan, state = _open_state(Path(args.path).resolve())
    print(status_line(cfg, plan, state, run_journal(cfg.root),
                      shutil.get_terminal_size().columns - 1 if sys.stdout.isatty() else None) + "\n")
    print(build_report(cfg, plan, state))
    from .plain import colors_on
    print(hints(Path(args.path).resolve(), None, colors_on(sys.stdout)))


def cmd_stats(args):
    from .report import proof_stats
    cfg, plan, state = _open_state(Path(args.path).resolve())
    print(proof_stats(cfg, plan, state))


def watch_end(root: Path, run: dict, color: bool, hold: bool):
    """J8: the end of the simple view and of the dashboard: the end line, the status in short, the next steps.
    A window that the build opened (`hold`) stays until the person closes it."""
    from .plain import ending, paint, tint
    print("\n" + paint(ending(run.get("outcome")), "bold", color))
    try:
        for row in status_reader(root, words="panel")().split("\n"):
            print(tint(row, color))
    except Exception:  # noqa: BLE001 — no plan: the end line is enough
        pass
    print(hints(root, False, color))
    if hold and sys.stdin and sys.stdin.isatty():
        try:
            input(paint("\nPress Enter to close this window.", "dim", color))
        except (EOFError, KeyboardInterrupt):
            pass


def restarting(root: Path, wait: float = 90, sleep=None, clock=None) -> bool:
    """J14.9: a run that ended `interrupted` may be restarting itself after a crash. True when run.json turns
    `running` again within `wait` seconds."""
    import time

    from .report import run_journal
    sleep, clock = sleep or time.sleep, clock or time.monotonic
    if run_journal(root).get("outcome") != "interrupted":
        return False
    end = clock() + wait
    while clock() < end:
        sleep(1)
        if run_journal(root).get("status") == "running":
            return True
    return False


def watch_dashboard(root: Path, color: bool, hold: bool, tick: float = 1.0):
    """J9: the full-window dashboard (dash_term.frame) on the terminal's second screen, drawn again each second.
    Returns None when this terminal cannot show it (too small, no plan yet): the caller uses the scrolling view.
    A window made too small later shows one line that says so. Ctrl+C and the end of the build give the first
    screen back, with the end message on it."""
    import time

    from .dash_term import MIN_COLS, MIN_ROWS, frame
    from .dashboard import dashboard_data, is_utf, spinner
    from .report import run_journal
    from .state import State
    utf = is_utf(sys.stdout)  # J13/18: ASCII spinner on other consoles
    spin = None
    size = shutil.get_terminal_size()
    if size.columns < MIN_COLS or size.lines < MIN_ROWS:
        return None
    box: dict = {}

    def data() -> dict:
        plan_file = root / AGENT_DIR / "plan.yaml"
        stamp = plan_file.stat().st_mtime
        if box.get("stamp") != stamp:  # first call, or the plan gained tasks
            if "state" in box:
                box["state"].db.close()
            box.update(cfg=Config.load(root), plan=Plan.load(plan_file), state=State(root / AGENT_DIR / "state.db"),
                       stamp=stamp)
        return dashboard_data(box["cfg"], box["plan"], box["state"], run_journal(root))
    try:
        data()
    except Exception:  # noqa: BLE001 — no plan yet
        return None
    out, done, ended = sys.stdout, 0, False
    out.write("\x1b[?1049h\x1b[?25l\x1b[?7l")  # the second screen, no cursor, no line wrap
    try:
        while True:
            size = shutil.get_terminal_size()
            try:
                d = data()
                spin = d["spin"] = spinner(d, d["asof"]["mtime"], time.time(), spin, utf)
                rows = frame(d, size.columns, size.lines, color)
                title = "".join(c for c in f"{spin['text']} {d.get('line', '')}".strip() if c.isprintable())
                out.write("\x1b[H" + "\n".join(rows) + f"\x1b]0;{title}\x07")
            except ValueError:  # the window is too small now
                out.write("\x1b[2J\x1b[HThe window is too small for the dashboard. Make it larger, or run: ap watch --scroll")
            except Exception:  # noqa: BLE001 — e.g. the plan is being rewritten right now: keep the last picture
                pass
            out.flush()
            done = done + 1 if run_journal(root).get("status") == "finished" else 0
            if done >= 3 and restarting(root):
                done = 0
            if done >= 3:
                ended = True
                break
            time.sleep(tick)
    except KeyboardInterrupt:
        pass
    finally:
        out.write("\x1b[?7h\x1b[?25h\x1b[?1049l")
        out.flush()
        if "state" in box:
            box["state"].db.close()
    if ended:
        watch_end(root, run_journal(root), color, hold)
    return 0


def cmd_watch(args):
    """Follow a run from any terminal: progress, current step, then every live line until the run finishes."""
    import time

    from .plain import SimpleView, colors_on, paint
    from .report import next_steps_text, run_journal
    root = Path(args.path).resolve()
    log = root / AGENT_DIR / "logs" / "autopilot.log"
    # J1: plain words on a terminal; the technical lines with --detail, and when the output is not a terminal
    simple = bool(getattr(args, "simple", False)) or (sys.stdout.isatty() and not getattr(args, "detail", False))
    color = colors_on(sys.stdout)
    if (simple and color and sys.stdout.isatty() and not getattr(args, "scroll", False)
            and not getattr(args, "simple", False)):  # J9: the dashboard, when the window is large enough
        rc = watch_dashboard(root, color, bool(getattr(args, "hold", False)))
        if rc is not None:
            return rc
    names = {}
    try:
        cfg, plan, state = _open_state(root)
        from .context import progress_line
        ids = plan.all_tasks()
        names = {t.id: (i + 1, len(ids), t.title, t.description) for i, t in enumerate(ids)}
        print(f"{cfg.get('name', root.name)}: {progress_line(plan, state.status_map())}")
    except Exception:  # noqa: BLE001 — a project without a plan yet still has a log to show
        pass
    view = SimpleView(names, color)

    asked = [False]
    live, drawn = [False], [None]  # live: the pinned panel is on, so the terminal takes escape codes

    def show(text: str, final: bool = False):
        """J6: the lines that are final, then the group in work. A terminal draws that group again in place."""
        if not simple:
            print(text, end="" if text.endswith("\n") else "\n", flush=True)
            return
        if live[0]:
            view.width = shutil.get_terminal_size().columns - 1
        rows = [out for row in text.splitlines() for out in view.feed(row)]
        if final or not live[0]:
            rows += view.close() if final else []
            now = None
        else:
            now = view.open_line()
            if not rows and now == drawn[0]:
                return
        erase = "\x1b[1A\x1b[2K" if drawn[0] else ""  # the cursor is below the group line: go up, clear, write again
        drawn[0] = now
        if rows or now or erase:
            print(erase + "\n".join(rows + ([now] if now else [])), flush=True)
    run = run_journal(root)
    if simple:
        print(paint("Ctrl+C closes this view. The build continues.", "dim", color))
        print(hints(root, None, color))
    else:
        print(f"run: {run.get('status', 'no run yet')} · now: {run.get('current') or '-'}  (Ctrl+C stops watching, "
              "not the run)")
        print(next_steps_text(root))
    pos = 0
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        show("\n".join(lines[-(args.lines * 4 if simple else args.lines):]), final=True)
        pos = log.stat().st_size
    quiet = 0.0
    line = status_reader(root, words=simple)
    # G8: a terminal gets the status pinned to its bottom; J5: the simple view has four rows, one for each category
    panel = status_reader(root, words="panel")
    # a wide window needs fewer rows. A reader of its own: the bar reads on its thread, and a database connection
    # stays on one thread. ponytail: the height is set once; a window made narrow later cuts rows
    try:
        height = len(status_reader(root, words="panel")(shutil.get_terminal_size().columns - 1).split("\n"))
    except Exception:  # noqa: BLE001 — no plan yet
        height = 4
    bar = StatusBar(panel, bold=color, height=height, title=line) if simple else StatusBar(line)
    pinned, shown = bar.start(), [None]
    live[0] = pinned and simple

    def moved():  # not a terminal: print the line when the run moves on, and never an escape code
        now = run_journal(root)
        key = (now.get("status"), now.get("state"), now.get("task"))
        if not pinned and key != shown[0]:
            shown[0] = key
            try:
                print(line(), flush=True)
            except Exception:  # noqa: BLE001 — no plan yet: the log is still worth following
                pass
    moved()
    try:
        while True:
            time.sleep(1)
            moved()
            if log.exists() and log.stat().st_size > pos:
                with open(log, encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
                    pos = fh.tell()
                show(chunk)
                quiet = 0
                continue
            quiet += 1
            run = run_journal(root)
            if simple and not asked[0] and run.get("status") == "running" and (root / AGENT_DIR / "STOP").exists():
                asked[0], drawn[0] = True, None  # the line in work stays as it is; the notice goes below it
                print(paint("You asked for a stop. The build stops after the current session.", "yellow", color),
                      flush=True)
            if run.get("status") == "finished" and quiet >= 3 and restarting(root):
                quiet = 0
                continue
            if run.get("status") == "finished" and quiet >= 3:
                if simple:
                    show("", final=True)
                    bar.stop()  # J8: the panel goes; its facts stay on the screen as normal lines
                    watch_end(root, run, color, bool(getattr(args, "hold", False)))
                else:
                    print(f"\nrun finished: {run.get('outcome', '?')}")
                    print(next_steps_text(root, running=False))
                return 0
    except KeyboardInterrupt:
        return 0
    finally:
        bar.stop()


def open_watch_window(root: Path) -> str:
    """A run without its own terminal (started in the background, by a tool or another program) opens a separate
    terminal window running `autopilot watch`, so the live view is always on screen. Returns how, or '' when there is
    no desktop to open one on (a server, CI)."""
    import subprocess
    cmd = [sys.executable, "-m", "autopilot", "watch", "-C", str(root), "--hold"]
    # Claude Code sets NO_COLOR for its tools; that is not the user's wish for a new window of their own
    env = {k: v for k, v in os.environ.items() if not (k == "NO_COLOR" and os.environ.get("CLAUDECODE"))}
    try:
        if os.name == "nt":
            subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE, env=env)  # noqa: S603
            return "new console window"
        if sys.platform == "darwin":
            script = " ".join(f"'{c}'" for c in cmd)
            subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{script}"'])
            return "Terminal window"
        term = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("xterm")
        if term and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            subprocess.Popen([term, "--", *cmd] if term.endswith("gnome-terminal") else [term, "-e", *cmd], env=env)
            return "terminal window"
    except OSError:
        pass
    return ""


def start_detached(root: Path, argv: list[str]) -> int:
    """I4/H6: start this command again as its own process, then return. The run outlives the terminal or the Claude
    Code chat that started it (a background command in a chat stops after 2 hours at most)."""
    import subprocess
    if run_active(root):
        print(f"a run is already active for {root}; follow it with `ap watch`")
        return 0
    log = root / AGENT_DIR / "logs" / "detached.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "autopilot", *argv]
    out = open(log, "a", encoding="utf-8")  # noqa: SIM115 — the child keeps it open
    # PYTHONSAFEPATH: `-m` puts the cwd first on sys.path, so a project that has an `autopilot/` folder of its own (a
    # self-build clone) would be imported instead of the installed Autopilot (RCA 2026-10-11)
    kw = dict(stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, cwd=str(Path.cwd()),
              env={**os.environ, "PYTHONSAFEPATH": "1"})
    if os.name == "nt":  # a hidden console of its own (git and claude get no window each), out of the caller's job
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            p = subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)  # noqa: S603
        except OSError:  # the caller's job forbids breakaway
            p = subprocess.Popen(cmd, creationflags=flags, **kw)  # noqa: S603
    else:  # a new session: no hangup signal when the terminal or the chat closes
        p = subprocess.Popen(cmd, start_new_session=True, **kw)  # noqa: S603
    out.close()
    print(f"started in the background (process {p.pid}); it continues when this terminal or chat closes.\n"
          f"  follow: ap watch\n  stop:   ap stop\n  start again: ap start\n  output: {log}")
    return 0


def run_active(root: Path) -> bool:
    """Is an `autopilot run` going on for this project right now? (It holds .agent/run.lock.)"""
    lock = root / AGENT_DIR / "run.lock"
    if not lock.exists():
        return False
    try:
        with exclusive_lock(lock):
            return False
    except BlockingIOError:
        return True


def start_status_page(root: Path, port: int = 8765) -> str:
    """Start the read-only status page in the background for this process (loopback only). Returns its URL, or ''
    when no port is free. ponytail: tries 10 ports, then gives up quietly."""
    import threading

    from .report import status_server
    for p in range(port, port + 10):
        try:
            srv = status_server(root, "127.0.0.1", p, "", 10)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{p}/"
    return ""


def cmd_serve(args):
    import os

    from .report import status_server
    try:
        srv = status_server(Path(args.path).resolve(), args.host, args.port,
                            os.environ.get("AUTOPILOT_STATUS_TOKEN", ""), args.refresh)
    except (ValueError, OSError) as exc:
        print(f"cannot serve: {exc}")
        return 1
    print(f"status page: http://{args.host}:{srv.server_address[1]}/ (refreshes every {args.refresh}s; Ctrl+C stops)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


def doctor_runner(root: Path) -> int:
    """Q11: `ap doctor --runner`: send the one probe prompt through the runner of this project (or of this PC)."""
    from .commands.setup import PROBE_TIMEOUT, probe
    from .doctor import runner
    pj = root / AGENT_DIR / "project.yaml"
    cfg = Config.load(root) if pj.exists() else None
    key = (cfg.get("agent.preset") if cfg is not None else "") or setup_choice() or "claude_cli"
    row = runner(key) if key else None
    exe = row.which() if row else None
    if row is None or not exe:
        print("FAIL  runner         no runner is set up on this PC: run `ap setup`")
        return 1
    print(f"probe  {row.name}: sending one prompt, up to {PROBE_TIMEOUT} seconds")
    ok, sentence, fix = probe(row, exe, env={**os.environ, "CI": "1"})
    print(f"ok    {row.name} answered ready" if ok else f"FAIL  {sentence}\n      Run by hand: {fix or 'ap setup'}")
    return 0 if ok else 1


def cmd_doctor(args):
    from .doctor import FAIL, autofix, checks
    root = Path(args.path).resolve()
    if getattr(args, "runner", False):
        return doctor_runner(root)
    if not (root / AGENT_DIR / "project.yaml").exists():
        print(f"FAIL  project        no {AGENT_DIR}/project.yaml in {root}: run `autopilot init` first")
        return 1
    cfg = Config.load(root)
    rows = checks(cfg)
    if getattr(args, "fix", False):
        done = autofix(rows)
        for line in done:
            print(f"fix   {line}")
        if done:
            rows = checks(cfg)
            print()
    for level, name, detail in rows:
        print(f"{level:5s} {name:14s} {detail}")
    bad = sum(r[0] == FAIL for r in rows)
    print(f"\n{bad} problem(s) to fix before `autopilot run`" if bad else "\nready for `autopilot run`")
    return 1 if bad else 0


def cmd_next(args):
    cfg, plan, state = _open_state(Path(args.path).resolve())
    status = dict(state.status_map())
    policy = cfg.get("scheduling.phase_dependency", "soft")
    for i in range(args.n):
        t = plan.next_ready(status, policy)
        if not t:
            break
        ladder = cfg.get(f"models.ladder.{t.risk}")
        print(f"{i + 1:3d}. {t.id:14s} [{t.risk:8s} → {ladder[0]}] {t.title}")
        status[t.id] = "done"


def cmd_unblock(args):
    _, _, state = _open_state(Path(args.path).resolve())
    for tid in args.task_ids:
        if not state.task(tid):
            print(f"unknown task {tid}")
            continue
        state.set_task(tid, status="pending", attempts=0, last_error=None, note=args.note or "unblocked by user")
        state.set_meta(f"unstick:{tid}", False)
        print(f"{tid} -> pending")
    if args.note:
        print("note: add hints for the agent to the task description in plan.yaml or to .agent/BRAIN.md")


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask(prompt: str) -> str | None:
    """One line from the owner; None on Ctrl+C or end of input, so callers stop cleanly."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def _store_answer(state, did: str, text: str) -> int:
    if state.answer_decision(did, text):
        print(f"{did} answered; the run applies it on its next loop (or at the next `autopilot run`)")
        return 0
    row = state.decision(did)
    print(f"unknown decision {did}" if not row else f"{did} is not open (status {row['status']})")
    return 1


def cmd_answer(args):
    from .state import State
    state = State(Path(args.path).resolve() / AGENT_DIR / "state.db")  # no run lock: works while a run is active
    if args.decision_id and args.text is not None:
        return _store_answer(state, args.decision_id, args.text)
    usage = 'ap answer <id> "text"'
    if args.decision_id:
        if not _tty():
            print(f"usage: {usage}")
            return 1
        text = _ask(f"Your answer for {args.decision_id}: ")
        return _store_answer(state, args.decision_id, text) if text else 1
    rows = state.decisions("OPEN")[::-1]
    if not rows:
        print("No question waits for you.")
        return 0
    from .decisions import explain
    for r in rows:  # the same simple words as docs/NEEDS-YOU.md
        print(f"\n{r['id']}  {r['title']}")
        for line in explain(r):
            print("  " + line.replace("**", "").replace("`", ""))
    print("\nWrite each answer in your own words, as an instruction for the agent.")
    if not _tty():
        print(f"usage: {usage}")
        return 1
    from .decisions import CHOICES, SKIP
    print(f"Choices: {CHOICES}")
    for r in rows:
        sug = " ".join(str(r["suggestion"] or "").split())
        pick = _ask(f"{r['id']} choice (Enter = 1{': ' + sug if sug else ''}): ")
        if pick is None:
            break
        pick = pick.strip()
        text = sug if pick in ("", "1") else SKIP if pick == "2" else \
            (_ask(f"Your answer for {r['id']}: ") or "") if pick == "3" else pick  # other text = your own words
        if text:
            _store_answer(state, r["id"], text)
    return 0


def _plan_view(plan) -> dict:
    return {t.id: (t.title, t.description, list(t.acceptance_criteria)) for t in plan.all_tasks()}


def _change(orch, args, model) -> int:
    print(f"A plan change costs one replan session ({model}).")
    if not args.yes:
        if not _tty():
            print("no terminal: add --yes to start it")
            return 1
        if _ask("1 start, 2 stop> ") != "1":
            print("stopped; nothing changed")
            return 0
    orch.git.ensure_repo(orch.main)
    orch._prepare_repo()
    orch.reload_plan()
    before, head0, idea = _plan_view(orch.plan), orch.git.head(), " ".join(args.text.split())
    orch.docs.backlog_add(idea)
    orch._commit_main("[autopilot] backlog: plan change")  # committed first: the replan session starts with a git discard

    def undo():  # revert commits, not a reset: they may already be pushed. The idea leaves the backlog with them.
        if orch.git.head() != head0:
            orch.git.run("revert", "--no-edit", f"{head0}..HEAD")
            orch._push()
        orch.reload_plan()
    if not orch.replan("change", backlog=[idea]):
        undo()
        print("replan rejected or failed; nothing changed")
        return 1
    after = _plan_view(orch.plan)
    added, gone = [i for i in after if i not in before], [i for i in before if i not in after]
    changed = [i for i in after if i in before and after[i] != before[i]]
    for label, ids, view in (("added", added, after), ("changed", changed, after), ("removed", gone, before)):
        for i in ids:
            print(f"{label}: {i} {view[i][0]}")
    if not (added or changed or gone):
        print("no change")
    if not args.yes and _ask("1 keep, 2 undo> ") == "2":
        undo()
        for i in gone:  # sync_plan skipped the tasks the replan removed; they are back in the plan now
            orch.state.set_task(i, status="pending", note="plan change undone")
        print("undone; the plan is as it was before")
    return 0


def cmd_change(args):
    from .orchestrator import Orchestrator
    root = Path(args.path).resolve()
    setup_logging(root, False)
    orch = Orchestrator(root)
    try:
        with exclusive_lock(root / AGENT_DIR / "run.lock"):
            return _change(orch, args, orch.cfg.get("models.replanner", "opus"))
    except BlockingIOError:
        orch.docs.backlog_add(args.text)
        print("a run is active; the idea is in docs/BACKLOG.md and the run takes it at its next replan")
        return 0


def cmd_hint(args):
    _, plan, state = _open_state(Path(args.path).resolve())
    ok, msg = state.add_hint(plan, args.task_id, args.text)
    print(msg)
    return 0 if ok else 1


def cmd_skip(args):
    _, _, state = _open_state(Path(args.path).resolve())
    for tid in args.task_ids:
        state.set_task(tid, status="skipped", note="skipped by user")
        print(f"{tid} -> skipped")


def cmd_approve(args):
    import logging as _l
    from .orchestrator import Orchestrator
    root = Path(args.path).resolve()
    setup_logging(root, False)
    orch = Orchestrator(root)
    row = orch.state.phase(args.phase)
    if not row or row["prod_status"] != "awaiting_approval":
        print(f"phase {args.phase} is not awaiting approval")
        return 1
    try:
        with exclusive_lock(root / AGENT_DIR / "run.lock"):
            orch.reload_plan()
            print(orch.deploy_prod(args.phase, row["prod_ref"]))
    except BlockingIOError:
        d = root / AGENT_DIR / "approvals"
        d.mkdir(parents=True, exist_ok=True)
        (d / args.phase).write_text("approved\n")
        print(f"a run is active; it will deploy {args.phase} to prod before its next task")
    _l.shutdown()
    return 0


def cmd_uninstall(args, spawn=None):
    """N8: `ap uninstall --rights` removes the scheduled task / the sudoers file the installer created.
    T3: `ap uninstall --all` removes the rights, `~/.autopilot`, and the package itself (last, after this process has
    exited: `ap.exe` is locked while it runs). `--dry-run` lists the steps. Projects' `.agent/` folders and the AI CLIs stay."""
    from .rights import have_rights, remove_rights
    from .upgrade import detect_install, spawn_after_exit
    dry = getattr(args, "dry_run", False)
    if getattr(args, "all", False):
        say = (lambda s: print(("would " if dry else "") + s))
        if have_rights():
            say("remove the rights the installer took (scheduled task / sudoers file)")
            if not dry:
                for line in remove_rights():
                    print(line)
        home = _recent_file().parent
        say(f"delete {home} (recent projects, the install log, the runner choice)")
        if not dry and home.is_dir():
            shutil.rmtree(home, ignore_errors=True)
        kind = detect_install()
        cmd = {"uv": ["uv", "tool", "uninstall", "dev-autopilot"], "pip": [sys.executable, "-m", "pip", "uninstall", "-y", "dev-autopilot"]}.get(kind)
        if cmd is None:
            say("remove the package: this is a git checkout; run `pip uninstall dev-autopilot`, then delete the folder")
        else:
            say(f"remove the package ({kind}), after this command has exited: {' '.join(cmd)}")
            if not dry:
                (spawn or spawn_after_exit)(cmd)
        print("Kept: uv, Python, git, your AI CLI and its login, and each project's .agent/ folder (delete it to start clean).")
        return 0
    if not getattr(args, "rights", False):
        print("ap uninstall --rights   removes the rights the installer took (scheduled task / sudoers file)\n"
              "ap uninstall --all      removes the rights, ~/.autopilot and Autopilot itself (--dry-run lists the steps)")
        return 0
    for line in remove_rights():
        print(line)
    return 0


def cmd_mcp(args):
    from .mcp import serve
    serve(Path(args.path).resolve())


def cmd_stop(args):
    p = Path(args.path).resolve() / AGENT_DIR / "STOP"
    p.write_text("stop requested\n")
    print("the run will stop before its next session (remove with `autopilot resume`)")


def cmd_resume(args):
    p = Path(args.path).resolve() / AGENT_DIR / "STOP"
    if p.exists():
        p.unlink()
    print("stop flag cleared — start again with `autopilot run`")


def cmd_review(args):
    """Manual trigger for an audit or replan outside the normal cadence."""
    from .orchestrator import Orchestrator
    root = Path(args.path).resolve()
    setup_logging(root, args.verbose)
    orch = Orchestrator(root)
    orch.git.ensure_repo(orch.main)
    orch._prepare_repo()
    orch.reload_plan()
    if args.kind == "replan":
        print("replan accepted" if orch.replan("manual") else "replan rejected or failed")
    else:
        rep = orch.audit(args.kind)
        print(rep and {k: rep.get(k) for k in ("complete", "completion_pct", "summary", "_new_phase")})
    orch.write_report()


def cmd_report(args):
    from .report import build_report, tokens_report
    cfg, plan, state = _open_state(Path(args.path).resolve())
    print(tokens_report(state) if args.tokens else build_report(cfg, plan, state))


NEW_PROJECT = ("init", "onboard", "quickstart", "mcp")  # these make a project: with no -C they use this folder


def _recent_file() -> Path:
    return Path(os.environ.get("AUTOPILOT_HOME") or Path.home() / ".autopilot") / "recent"


def recent_projects() -> list[Path]:
    """Projects used on this PC, newest first; only folders that still hold a project."""
    try:
        rows = _recent_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [Path(r) for r in rows if r and (Path(r) / AGENT_DIR / "project.yaml").exists()]


def remember(root: Path):
    """J2: note this project as the last one used, so `ap status` works from any folder."""
    if not (root / AGENT_DIR / "project.yaml").exists():
        return
    try:
        rows = [str(root)] + [str(p) for p in recent_projects() if p != root]
        _recent_file().parent.mkdir(parents=True, exist_ok=True)
        _recent_file().write_text("\n".join(rows[:20]) + "\n", encoding="utf-8")
    except OSError:
        pass


def pick_project() -> str | None:
    """J2: no -C and this folder is not a project. One active build: that one. Several: ask (or list them when
    there is no terminal; never guess). None active: the last project used. Says which project it took."""
    known = recent_projects()
    active = [p for p in known if run_active(p)]
    if len(active) > 1:
        print("More than one build is active:")
        for i, p in enumerate(active, 1):
            print(f"  {i}. {p}")
        pick = _ask("Which one? Type its number: ") if _tty() else None
        if not (pick or "").isdigit() or not 1 <= int(pick) <= len(active):
            print("Name the project with -C <folder>.")
            return None
        active = [active[int(pick) - 1]]
    chosen = active[0] if active else known[0] if known else None
    if chosen is None:
        print("This folder is no Autopilot project, and no other project is known on this PC.\n"
              "Go to the project folder, or name it with -C <folder>. To start a new one: autopilot quickstart")
        return None
    print(f"this folder is no project, using the last one used: {chosen}")  # Q10: say why, not only which
    return str(chosen)


def _version_line():
    """Version plus short commit (N5.1); 'installed' outside a git checkout."""
    import subprocess
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).parent,
                             capture_output=True, text=True, timeout=5).stdout.strip() or "installed"
    except Exception:
        sha = "installed"
    return f"{__version__} ({sha})"


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    called = Path(sys.argv[0]).stem.lower() if argv is None else ""
    if called not in ("ap", "autopilot"):  # `python -m autopilot` arrives as `__main__`: never a name a user reads
        called = ""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["start"]:  # J2: one plain word to start or continue the build in the background
        argv[:1] = ["run", "--clear-stop", "--detach"]
    ap = argparse.ArgumentParser(prog="ap" if called == "ap" else "autopilot",
                                 description=DESCRIPTION)
    if argv[:1] in (["--help"], ["-h"]):  # J15: the plain-words opening is the first line of the help
        print(DESCRIPTION.rsplit(". ", 1)[0] + ".\n")
    if argv[:1] == ["--version"]:  # N5.1: git only runs here, never on a normal command
        print(f"{called or 'autopilot'} {_version_line()}")
        return 0
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--ask", action="store_true", help="ask before a new build starts (N5.5)")
    sub = ap.add_subparsers(dest="cmd")

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("-C", "--path", default=None,
                       help="project folder (default: this folder, or else the active or last project)")
        p.set_defaults(fn=fn)
        return p

    p = add("init", cmd_init, "create .agent/ contract (auto-detects stack)")
    p.add_argument("--stack"); p.add_argument("--name"); p.add_argument("--force", action="store_true")
    p = add("onboard", cmd_onboard, "AI session: write BRAIN.md, commands and plan.yaml from a plan doc")
    p.add_argument("--plan-doc"); p.add_argument("--budget", default="15")
    p = add("quickstart", cmd_quickstart, "one command: init, onboard from a plan doc, doctor, then optionally run")
    p.add_argument("--plan-doc"); p.add_argument("--budget", default="15")
    p.add_argument("--run", action="store_true", help="start the run when the doctor finds no problems")
    p.add_argument("--idea", help="no PLAN.md yet: what to build (text or a file); Claude writes PLAN.md from it")
    p.add_argument("--detach", action="store_true", help="start as a separate process that outlives this terminal")
    p.add_argument("--ask", action="store_true", help="keep the question before the build starts (N5.5)")
    add("preflight", cmd_preflight, "phase 0: check the credentials the plan needs (read-only); blocks the run on a problem")
    add("validate", cmd_validate, "validate project.yaml and plan.yaml")
    p = add("doctor", cmd_doctor, "check the claude CLI, git, gh, sandbox tools, notifications and config")
    p.add_argument("--fix", action="store_true", help="also fix what needs no person: PATH, reinstall the claude CLI")
    p.add_argument("--runner", action="store_true", help="send one test prompt through the runner and say if it answers")
    p = add("run", cmd_run, "run autonomously until the app is complete")
    p.add_argument("--max-sessions", type=int); p.add_argument("--clear-stop", action="store_true")
    p.add_argument("--no-page", action="store_true", help="don't start the live status page")
    p.add_argument("--no-browser", action="store_true", help="start the live page but don't open the browser")
    p.add_argument("--no-prod", action="store_true", help="run everything except the deploy to the production host (K)")
    p.add_argument("--no-watch", action="store_true",
                   help="when run without a terminal, don't open a window with `autopilot watch`")
    p.add_argument("--detach", action="store_true", help="start as a separate process that outlives this terminal")
    p.add_argument("-v", "--verbose", action="store_true")
    add("start", cmd_run, "start or continue the build in the background (= run --clear-stop --detach)")
    add("status", cmd_status, "progress, cost, blocked tasks, approvals")
    add("stats", cmd_stats, "the numbers of a run worth publishing (markdown table)")
    p = add("watch", cmd_watch, "follow a run live from any terminal, in plain words")
    p.add_argument("-n", "--lines", type=int, default=20, help="recent lines to show first")
    p.add_argument("--detail", action="store_true", help="the technical view: every log line as it is")
    p.add_argument("--simple", action="store_true", help="plain words, also when the output is not a terminal")
    p.add_argument("--hold", action="store_true", help="at the end of the build, wait for Enter (a window of its own)")
    p.add_argument("--scroll", action="store_true", help="the scrolling view in plain words, not the dashboard")
    p = add("serve", cmd_serve, "live read-only status page in the browser")
    p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8765)
    p.add_argument("--refresh", type=int, default=30, help="seconds between page reloads")
    p = add("next", cmd_next, "preview the next tasks in execution order"); p.add_argument("-n", type=int, default=15)
    p = add("unblock", cmd_unblock, "reset blocked task(s) to pending")
    p.add_argument("task_ids", nargs="+"); p.add_argument("--note")
    p = add("answer", cmd_answer, "answer an open decision from docs/NEEDS-YOU.md")
    p.add_argument("decision_id", nargs="?"); p.add_argument("text", nargs="?")
    p = add("change", cmd_change, "change the plan in plain words (one replan session; you can undo it)")
    p.add_argument("text"); p.add_argument("--yes", action="store_true", help="no questions: start and keep the result")
    p = add("hint", cmd_hint, "give a task advice for its next session (works while a run is active)")
    p.add_argument("task_id"); p.add_argument("text")
    p = add("skip", cmd_skip, "skip task(s)"); p.add_argument("task_ids", nargs="+")
    p = add("approve", cmd_approve, "deploy an approved phase to prod"); p.add_argument("phase")
    add("mcp", cmd_mcp, "MCP server on stdin/stdout for IDE chats: ap_status, ap_next, ap_start, ap_stop, ap_answer")
    p = add("uninstall", cmd_uninstall, "--rights: remove the rights the installer took; --all: remove Autopilot from this PC")
    p.add_argument("--rights", action="store_true"); p.add_argument("--all", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="list the steps, change nothing")
    from .upgrade import cmd_install, cmd_upgrade
    p = add("upgrade", cmd_upgrade, "get the newest Autopilot; --check only prints")
    p.add_argument("--check", action="store_true"); p.add_argument("--ref"); p.add_argument("--daily", action="store_true", help=argparse.SUPPRESS)
    p = add("install", cmd_install, "install or repair Autopilot for this user; --rights = the one rights step")
    p.add_argument("--rights", action="store_true")
    from .commands.setup import cmd_setup
    p = add("setup", cmd_setup, "find the AI you pay for, install its CLI, check the login, write the choice (one question at most)")
    p.add_argument("--dry-run", action="store_true", help="scan and print the plan; install and write nothing")
    p.add_argument("--runner", help="answer the question in advance: claude, copilot, codex, cursor or kiro")
    p.add_argument("--yes", action="store_true", help="take the default answer")
    p.add_argument("--skip-login", action="store_true", help="do not check or start a login")
    p.add_argument("--skip-probe", action="store_true", help="do not send the one test prompt (CI)")
    add("stop", cmd_stop, "graceful stop before the next session")
    add("resume", cmd_resume, "clear the stop flag")
    p = add("report", cmd_report, "the run report; --tokens = tokens and cost per step type")
    p.add_argument("--tokens", action="store_true", help="tokens and cost per step: build, retry, review, verify, audit, ...")
    p = add("audit", cmd_review, "run the completion audit now (the lean profile never runs it by itself)")
    p.set_defaults(kind="completion")
    p = add("review", cmd_review, "run an audit / completion audit / replan now")
    p.add_argument("--kind", choices=["periodic", "completion", "replan"], default="periodic")
    p.add_argument("-v", "--verbose", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd is None:  # plain `autopilot` in a project folder: follow its run when one is going
        if run_active(Path.cwd()):
            print("a run is active here; following it (Ctrl+C stops watching, not the run)\n")
            return cmd_watch(argparse.Namespace(path=".", lines=20))
        from .report import next_steps_text
        if sys.stdin.isatty() and sys.stdout.isatty() and (case := folder_case(Path.cwd())) != "agent":
            adopt = case == "code" and not idea_file(Path.cwd())  # N5.5: a folder with just the idea is a new project
            if (rc := adopt_start(Path.cwd().resolve()) if adopt else guided_start(args.ask)) >= 0:  # -1: the normal banner
                return rc
        print(f"autopilot {__version__}: {DESCRIPTION.split('. ')[0]}.")
        print(next_steps_text(Path.cwd()))
        return 0
    if args.cmd in ("upgrade", "install", "setup", "uninstall"):  # no project needed: nothing to find or remember
        return args.fn(args) or 0
    if args.path is None:  # J2: no -C
        found = "." if args.cmd in NEW_PROJECT or (Path.cwd() / AGENT_DIR / "project.yaml").exists() else pick_project()
        if found is None:
            return 1
        args.path = found
    remember(Path(args.path).resolve())
    if getattr(args, "detach", False):
        return start_detached(Path(args.path).resolve(), [a for a in (argv or sys.argv[1:]) if a != "--detach"])
    rc = args.fn(args) or 0
    from .upgrade import auto_update  # T2: after the command, once a day, never during a run

    line = auto_update(args.cmd, Path(args.path).resolve())
    if line:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
