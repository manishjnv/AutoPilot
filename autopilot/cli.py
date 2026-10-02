"""autopilot CLI."""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import threading
from pathlib import Path

import yaml

from . import AGENT_DIR, __version__
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
        cmd_block = yaml.safe_dump({"commands": commands}, sort_keys=False, width=200).rstrip() + "\n"
        text = proj_path.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^name:.*$", f"name: {name}", text, count=1)
        text = re.sub(r"(?m)^stack:[^#\n]*", f"stack: {stack}            ", text, count=1)
        text = re.sub(r"(?ms)^commands:\n(?:[ \t]+.*\n)*", cmd_block, text, count=1)
        proj_path.write_text(text, encoding="utf-8")
    # gitignore + CLAUDE.md pointer
    gi = root / ".gitignore"
    snippet = (TEMPLATES / "agent" / "gitignore").read_text(encoding="utf-8")
    if not gi.exists() or ".agent/state.db" not in gi.read_text(encoding="utf-8"):
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write(snippet)
    cm = root / "CLAUDE.md"
    cm_snip = (TEMPLATES / "agent" / "CLAUDE.md.snippet").read_text(encoding="utf-8")
    if not cm.exists() or "## Autopilot (autonomous sessions)" not in (t := cm.read_text(encoding="utf-8")) and "## AutoDev (autonomous sessions)" not in t:
        with open(cm, "a", encoding="utf-8") as fh:
            fh.write(cm_snip)
    print(f"\nstack: {stack}\nnext:  autopilot onboard --plan-doc <your plan.md>   (or edit .agent/plan.yaml)\n"
          f"       autopilot validate && autopilot run")


def cmd_onboard(args):
    from .backends import SessionRequest, get_backend
    from .context import render

    root = Path(args.path).resolve()
    if not (root / AGENT_DIR / "project.yaml").exists():
        cmd_init(argparse.Namespace(path=str(root), stack=None, name=None, force=False))
    setup_logging(root, False)  # the session's live activity lines
    cfg = Config.load(root)
    plan_doc = Path(args.plan_doc).read_text(encoding="utf-8") if args.plan_doc else \
        "(no plan document — derive a sensible plan from the repository and README)"
    if len(plan_doc) > 150_000:
        plan_doc = plan_doc[:150_000] + "\n…(truncated)…"
    prompt = render("onboard.md", plan_doc=plan_doc)
    system = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
    system += "\nFor THIS onboarding session you ARE allowed to edit the .agent files listed in the assignment."
    backend = get_backend(cfg)
    print(f"running onboarding session ({cfg.get('models.onboard', 'opus')}) …")
    res = backend.run(SessionRequest(prompt=prompt, model=cfg.get("models.onboard", "opus"), cwd=str(root),
                                     timeout_sec=int(cfg.get("agent.session_timeout_sec", 3600)),
                                     budget_usd=float(args.budget), system_append=system,
                                     effort=cfg.get("models.effort.onboard", ""), label="onboarding",
                                     log_path=str(root / AGENT_DIR / "logs" / "onboard.log")))
    print(res.report.get("summary") or res.text[-1500:] or res.error)
    return cmd_validate(args)


def cmd_quickstart(args):
    """M5: init → environment fixes → (claude CLI check) → onboard → doctor → optionally run, in one command."""
    root = Path(args.path).resolve()
    if not (root / AGENT_DIR / "project.yaml").exists():
        cmd_init(argparse.Namespace(path=str(root), stack=None, name=None, force=False))
    if not preflight(Config.load(root)):  # don't start onboarding on a CLI that can't run a session
        return 1
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
    from .doctor import FAIL, autofix, check_claude, check_path
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
    return True


def login_now() -> bool:
    """H2: with a terminal, offer the Claude login and run it. False = no terminal (never ask), or the owner stops."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    print("Claude Code is not logged in. A paid Claude plan or an API key is necessary.\n"
          "  1  log in now (this opens the browser)\n  2  stop")
    try:
        if input("> ").strip() != "1":
            return False
        import subprocess

        from .backends.claude_cli import ClaudeCLIBackend
        subprocess.run([ClaudeCLIBackend.resolve_binary(), "auth", "login"], check=False)
    except (EOFError, KeyboardInterrupt, OSError):
        return False
    return True


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


def guided_start() -> int:
    """H5: plain `autopilot` in a terminal, no project here: ask the idea and the folder, then quickstart and run."""
    from .docs import slug
    try:
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

    def __init__(self, line, out=None, every: float = 1.0):
        self.line, self.out, self.every = line, out or sys.stdout, every
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
        # two fresh lines, then rows 1..n-1 scroll and the cursor waits on the last of them; row n is the line's
        self._write(f"\n\n\x1b[1;{self.rows - 1}r\x1b[{self.rows - 1};1H")
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
            text = "".join(c for c in str(self.line(size.columns - 1)) if c.isprintable())[:size.columns - 1]
        except Exception:  # noqa: BLE001 — e.g. the plan is being rewritten right now: keep the last line
            return
        refit = ""
        if size.lines != self.rows:  # the window was resized: move the reserved row
            self.rows, refit = size.lines, f"\x1b7\x1b[1;{size.lines - 1}r\x1b8"
        # save the cursor, draw the bottom row, put the cursor back; then the window title
        self._write(f"{refit}\x1b7\x1b[{self.rows};1H\x1b[2K{text}\x1b8\x1b]0;{text}\x07")

    def stop(self):
        if not self.on:
            return
        self.done.set()
        self.on = False
        self._write(f"\x1b[r\x1b[{self.rows};1H\x1b[2K")  # whole-screen scrolling again, the row cleared


def status_reader(root: Path):
    """line(width) for the project at `root`: the status line, read fresh from run.json and state.db on each call.
    It only reads, and keeps its own database connection, so use one reader per thread."""
    from .report import run_journal, status_line
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
        return status_line(box["cfg"], box["plan"], box["state"], run_journal(root), width)
    return line


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
    url = "" if getattr(args, "no_page", False) else start_status_page(root)
    if url and not getattr(args, "no_browser", False) and not os.environ.get("AUTOPILOT_NO_BROWSER"):
        import webbrowser
        try:  # the live view opens by itself; on a server without a browser this does nothing
            webbrowser.open(url, new=2)
        except Exception:  # noqa: BLE001
            pass
    if not sys.stdout.isatty() and not getattr(args, "no_watch", False) and not os.environ.get("AUTOPILOT_NO_BROWSER"):
        how = open_watch_window(root)  # no terminal of our own: put `autopilot watch` on screen
        if how:
            print(f"opened a {how} with `autopilot watch`", flush=True)
    print(f"\nFollow this run: {url + ' in a browser, or ' if url else ''}`autopilot watch` in another terminal "
          f"(log: {root / AGENT_DIR / 'logs' / 'autopilot.log'})\n", flush=True)
    bar = StatusBar(status_reader(root))  # G8: the status line stays on the bottom row while the run prints above it
    bar.start()
    try:
        outcome = run_supervised(root, lambda: Orchestrator(root, max_sessions=args.max_sessions))
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
    from .report import build_report, next_steps_text, run_journal, status_line
    cfg, plan, state = _open_state(Path(args.path).resolve())
    print(status_line(cfg, plan, state, run_journal(cfg.root),
                      shutil.get_terminal_size().columns - 1 if sys.stdout.isatty() else None) + "\n")
    print(build_report(cfg, plan, state))
    print(next_steps_text(Path(args.path).resolve()))


def cmd_stats(args):
    from .report import proof_stats
    cfg, plan, state = _open_state(Path(args.path).resolve())
    print(proof_stats(cfg, plan, state))


def cmd_watch(args):
    """Follow a run from any terminal: progress, current step, then every live line until the run finishes."""
    import time

    from .report import next_steps_text, run_journal
    root = Path(args.path).resolve()
    log = root / AGENT_DIR / "logs" / "autopilot.log"
    try:
        cfg, plan, state = _open_state(root)
        from .context import progress_line
        print(f"{cfg.get('name', root.name)}: {progress_line(plan, state.status_map())}")
    except Exception:  # noqa: BLE001 — a project without a plan yet still has a log to show
        pass
    run = run_journal(root)
    print(f"run: {run.get('status', 'no run yet')} · now: {run.get('current') or '-'}  (Ctrl+C stops watching, "
          "not the run)")
    print(next_steps_text(root))
    pos = 0
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-args.lines:]))
        pos = log.stat().st_size
    quiet = 0.0
    line = status_reader(root)
    bar = StatusBar(line)  # G8: a terminal gets the status line pinned to its bottom row
    pinned, shown = bar.start(), [None]

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
                print(chunk, end="", flush=True)
                quiet = 0
                continue
            quiet += 1
            run = run_journal(root)
            if run.get("status") == "finished" and quiet >= 3:
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
    cmd = [sys.executable, "-m", "autopilot", "watch", "-C", str(root)]
    try:
        if os.name == "nt":
            subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)  # noqa: S603
            return "new console window"
        if sys.platform == "darwin":
            script = " ".join(f"'{c}'" for c in cmd)
            subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{script}"'])
            return "Terminal window"
        term = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("xterm")
        if term and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            subprocess.Popen([term, "--", *cmd] if term.endswith("gnome-terminal") else [term, "-e", *cmd])
            return "terminal window"
    except OSError:
        pass
    return ""


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


def cmd_doctor(args):
    from .doctor import FAIL, autofix, checks
    root = Path(args.path).resolve()
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
    usage = 'autopilot answer <id> "text"'
    if args.decision_id:
        if not _tty():
            print(f"usage: {usage}")
            return 1
        text = _ask(f"{args.decision_id} answer> ")
        return _store_answer(state, args.decision_id, text) if text else 1
    rows = state.decisions("OPEN")[::-1]
    if not rows:
        print("no open questions")
        return 0
    for r in rows:
        q = " ".join((r["question"] or "").split())
        print(f"{r['id']}  {r['title']}\n    {q[:200]}" + (f"\n    suggestion: {r['suggestion']}" if r["suggestion"] else ""))
    if not _tty():
        print(f"usage: {usage}")
        return 1
    for r in rows:
        text = _ask(f"{r['id']} answer (empty = skip)> ")
        if text is None:
            break
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


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="autopilot", description="Autonomous plan-driven development with Claude Code")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("-C", "--path", default=".", help="project root (default: current dir)")
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
    add("validate", cmd_validate, "validate project.yaml and plan.yaml")
    p = add("doctor", cmd_doctor, "check the claude CLI, git, gh, sandbox tools, notifications and config")
    p.add_argument("--fix", action="store_true", help="also fix what needs no person: PATH, reinstall the claude CLI")
    p = add("run", cmd_run, "run autonomously until the app is complete")
    p.add_argument("--max-sessions", type=int); p.add_argument("--clear-stop", action="store_true")
    p.add_argument("--no-page", action="store_true", help="don't start the live status page")
    p.add_argument("--no-browser", action="store_true", help="start the live page but don't open the browser")
    p.add_argument("--no-watch", action="store_true",
                   help="when run without a terminal, don't open a window with `autopilot watch`")
    p.add_argument("-v", "--verbose", action="store_true")
    add("status", cmd_status, "progress, cost, blocked tasks, approvals")
    add("stats", cmd_stats, "the numbers of a run worth publishing (markdown table)")
    p = add("watch", cmd_watch, "follow a run live from any terminal (progress, current step, every step)")
    p.add_argument("-n", "--lines", type=int, default=20, help="recent lines to show first")
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
    add("stop", cmd_stop, "graceful stop before the next session")
    add("resume", cmd_resume, "clear the stop flag")
    p = add("review", cmd_review, "run an audit / completion audit / replan now")
    p.add_argument("--kind", choices=["periodic", "completion", "replan"], default="periodic")
    p.add_argument("-v", "--verbose", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd is None:  # plain `autopilot` in a project folder: follow its run when one is going
        if run_active(Path.cwd()):
            print("a run is active here; following it (Ctrl+C stops watching, not the run)\n")
            return cmd_watch(argparse.Namespace(path=".", lines=20))
        from .report import next_steps_text
        if sys.stdin.isatty() and sys.stdout.isatty() and not (Path.cwd() / AGENT_DIR / "project.yaml").exists():
            if (rc := guided_start()) >= 0:  # -1: no idea given, so the normal banner
                return rc
        print(f"autopilot {__version__}: builds your project with Claude Code, checks every step, never waits.")
        print(next_steps_text(Path.cwd()))
        return 0
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
