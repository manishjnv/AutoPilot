"""Q3 `ap setup`: scan the machine (read-only), print the plan, choose one runner, install that one CLI, check its
login, write the choice. A footprint (`~/.claude`, a `gh` login, an extension folder) suggests a runner; it never
installs one by itself. Every command runs through `install_errors.capture`: raw text to the log, plain words on screen.
Exit codes: 0 ok, 1 a step failed, 2 bad usage, 3 a choice is needed (no terminal and no answer)."""
from __future__ import annotations

import datetime
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .. import AGENT_DIR, profile
from ..doctor import RUNNERS, Runner, _logged_in, runner
from ..install_errors import (
    EXIT_CHOICE,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    capture,
    explain,
    log_path,
    os_name,
)
from ..proc import run_proc

QUESTION = "Which AI do you pay for?"
PROBE_PROMPT = "Reply with the single word ready."
PROBE_TIMEOUT = 60  # Q11: seconds; a test patches it


@dataclass
class Scan:
    """What the read-only scan found. Token values are never stored: only the names that are set."""
    runners: list = field(default_factory=list)   # (row, exe or '', logged_in)
    tokens: list = field(default_factory=list)    # names of the token variables that are set
    footprints: dict = field(default_factory=dict)  # row.key -> [paths found]
    gh_ok: bool = False                           # `gh auth status` exit 0
    vscode_copilot: bool = False                  # a github.copilot* folder under the VS Code extensions
    tools: dict = field(default_factory=dict)     # uv, python, node, git -> version line or ''
    git_user: tuple = ("", "")


def _ver(exe: str, run, args=("--version",)) -> str:
    try:
        p = run([exe, *args], timeout=20)
    except OSError:
        return ""
    return ((p.stdout or p.stderr or "").strip().splitlines() or [""])[0][:60] if p.rc == 0 else ""


def scan(env: dict | None = None, home: Path | None = None, which=None, run=run_proc) -> Scan:
    """Step 1: read-only. Runners on PATH with their login state, token names, footprints, gh, tools, git identity."""
    env = dict(os.environ if env is None else env)
    home = Path(home or env.get("HOME") or env.get("USERPROFILE") or Path.home())
    path = env.get("PATH", "")
    which = which or (lambda n: shutil.which(n, path=path))
    s = Scan()
    for row in RUNNERS:
        exe = next((which(n) for n in row.names if which(n)), "")
        s.runners.append((row, exe, bool(exe) and _logged_in(exe, row, env)))
        s.footprints[row.key] = [str(home / f) for f in row.footprints if (home / f).exists()]
    s.tokens = sorted({t for row in RUNNERS for t in row.tokens if env.get(t)})
    gh = which("gh")
    if gh:
        try:
            s.gh_ok = run([gh, "auth", "status"], env={**env, "CI": "1"}, timeout=20).rc == 0
        except OSError:
            s.gh_ok = False
    ext = home / ".vscode" / "extensions"
    try:
        s.vscode_copilot = ext.is_dir() and any(p.name.lower().startswith("github.copilot") for p in ext.iterdir())
    except OSError:
        s.vscode_copilot = False
    for tool in ("uv", "python3", "python", "node", "git"):
        exe = which(tool)
        s.tools[tool] = _ver(exe, run) if exe else ""
    git = which("git")
    if git:
        name, email = (_ver(git, run, ("config", "--get", k)) for k in ("user.name", "user.email"))
        s.git_user = (name, email)
    return s


def default_runner(s: Scan) -> Runner | None:
    """Step 3 default: a logged-in runner; else an installed one; else the one clear signal (a token, a gh login, the
    Copilot extension -> copilot; a footprint -> its runner), in table order; None when nothing points anywhere."""
    for row, exe, ok in s.runners:
        if ok:
            return row
    for row, exe, ok in s.runners:
        if exe:
            return row
    signals = []
    if s.tokens or s.gh_ok or s.vscode_copilot:
        signals.append(runner("copilot"))
    signals += [runner(k) for k in s.footprints if s.footprints[k]]
    return next((r for r in signals if r is not None), None)


def plan_lines(s: Scan, choice: Runner | None, platform: str | None = None) -> list[str]:
    """Step 2: `found`, `will install`, `skipped because` lines, one per item, then the runner line."""
    out = []
    for tool in ("uv", "python3", "node", "git"):
        ver = s.tools.get(tool) or (s.tools.get("python") if tool == "python3" else "")
        out.append(f"found     {ver}" if ver else f"skipped   {tool}: not installed (not needed for a runner)")
    if s.git_user[0] and s.git_user[1]:
        out.append(f"found     git identity {s.git_user[0]} <{s.git_user[1]}>")
    for row, exe, ok in s.runners:
        if exe:
            out.append(f"found     {row.name} ({exe}): {'logged in' if ok else 'not logged in'}")
    for name in s.tokens:
        out.append(f"found     token variable {name} (set; the value is never read)")
    if s.gh_ok:
        out.append("found     gh login (GitHub CLI)")
    if s.vscode_copilot:
        out.append("found     Copilot in VS Code (a companion, not a runner)")
    for key, paths in s.footprints.items():
        for p in paths:
            out.append(f"found     {p} (a footprint of {runner(key).name}; it installs nothing by itself)")
    for row, exe, ok in s.runners:
        if row is not choice and not exe:
            out.append(f"skipped   {row.name}: not installed, not chosen")
    if choice is None:
        out.append("runner    none found: one question follows")
    elif next(exe for row, exe, _ in s.runners if row is choice):
        out.append(f"runner    {choice.name} (installed)")
    else:
        out.append(f"will install  {choice.name}: {choice.install_cmd(platform)}")
    return out


def ask_tty(prompt: str) -> str | None:
    """One line from the person, read from the terminal itself (/dev/tty, or CON on Windows), so a piped install
    (`curl ... | bash`) still asks. None when there is no terminal."""
    dev = "CON" if os.name == "nt" else "/dev/tty"
    try:
        with open(dev, encoding="utf-8", errors="replace") as tty:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            line = tty.readline()
    except (OSError, ValueError):
        return None
    return line.strip() if line else None


def choose(s: Scan, *, wanted: str = "", yes: bool = False, ask=None, say=print) -> tuple[Runner | None, int]:
    """Step 3. (row, exit code). `wanted` (--runner / AUTOPILOT_RUNNER) answers in advance; `yes` takes the default;
    no terminal and no answer -> the list is printed and exit 3 with the exact rerun line."""
    if wanted:
        row = runner(wanted)
        if row is None:
            say(f"unknown runner `{wanted}`. One of: {', '.join(r.name for r in RUNNERS)}")
            return None, EXIT_USAGE
        return row, EXIT_OK
    default = default_runner(s)
    if default is not None and any(exe for row, exe, _ in s.runners if row is default):
        return default, EXIT_OK  # installed (logged in or not): no question, nothing installs
    if yes and default is not None:
        return default, EXIT_OK
    say(QUESTION)
    for i, row in enumerate(RUNNERS, 1):
        mark = "  (default)" if row is default else ""
        say(f"  {i}. {row.name:<8} {row.plan}{mark}")
    say(f"  {runner('copilot').plan.capitalize()} in VS Code counts: it is the same subscription as the Copilot CLI.")
    ask = ask or ask_tty
    hint = "Enter" if default is not None else "a number"
    answer = ask(f"Type the number ({hint}{' for the default' if default is not None else ''}): ")
    if answer is None:
        say("No terminal to ask on. Run again with the runner named, for example: "
            f"ap setup --runner {default.name if default else 'copilot'}")
        return None, EXIT_CHOICE
    if not answer and default is not None:
        return default, EXIT_OK
    if answer.isdigit() and 1 <= int(answer) <= len(RUNNERS):
        return RUNNERS[int(answer) - 1], EXIT_OK
    row = runner(answer.strip().lower())
    if row is not None:
        return row, EXIT_OK
    say(f"`{answer}` is not in the list. Run again with: ap setup --runner <name>")
    return None, EXIT_CHOICE


def install_runner(row: Runner, *, env: dict, platform: str | None, run=run_proc, say=print, home=None) -> int:
    """Step 4: install this one CLI with the row's command for this OS, the native route first, npm after it. The
    command runs through `capture` (log, three lines). Returns an exit code."""
    cmd = row.install_cmd(platform)
    if cmd.startswith("https://"):  # a download page, no script (kiro on Windows)
        say(f"{row.name} has no install script on this system. Download it here, then run `ap setup` again: {cmd.split()[0]}")
        return EXIT_CHOICE
    say(f"install   {row.name}: {cmd}")
    shell_cmd = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd]
                 if os_name(platform) == "windows" else ["bash", "-o", "pipefail", "-c", cmd])
    rc = capture(f"install {row.name}", shell_cmd, env=env, run=run, say=say, platform=platform, home=home)
    if rc != 0 and row.npm and shutil.which("npm", path=env.get("PATH")):
        say(f"install   {row.name}: trying the npm route: {row.npm}")
        rc = capture(f"install {row.name} (npm)", row.npm, shell=True, env=env, run=run, say=say, platform=platform, home=home)
    return EXIT_OK if rc == 0 else EXIT_FAILED


def remember_choice(root: Path | None, row: Runner, say=print) -> None:
    """Step 5: the project's project.yaml (when `root` is a project) and the PC default `~/.autopilot/runner`."""
    from ..cli import _recent_file, remember_runner
    pj = Path(root) / AGENT_DIR / "project.yaml" if root is not None else None
    if pj is not None and pj.exists() and remember_runner(pj, row.key):
        say(f"written   agent.{'backend' if row.key == 'claude_cli' else 'preset'}: {row.name} in {AGENT_DIR}/project.yaml")
    try:
        f = _recent_file().with_name("runner")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(row.key + "\n", encoding="utf-8")
    except OSError:
        pass


def probe(row: Runner, exe: str, *, env: dict, run=run_proc, platform: str | None = None) -> tuple[bool, str, str]:
    """Q11: send one prompt through the real runner in an empty temporary folder. (ok, sentence, next command).
    Pass = the word `ready` is in the answer within PROBE_TIMEOUT seconds. A failure is parsed by the Q4 catalogue."""
    argv = [exe, *[a.replace("{prompt}", PROBE_PROMPT) for a in row.probe]]
    with tempfile.TemporaryDirectory(prefix="ap-probe-") as tmp:
        try:
            p = run(argv, env=env, cwd=tmp, timeout=PROBE_TIMEOUT)
        except OSError as exc:
            text, rc, slow = str(exc), 127, False
        else:
            text, rc, slow = (p.stdout or "") + "\n" + (p.stderr or ""), p.rc, bool(getattr(p, "timed_out", False))
    if not slow and re.search(r"\bready\b", text, re.IGNORECASE) and rc == 0:
        return True, "", ""
    if slow:
        text = "probe_slow"
    _, sentence, fix = explain(text, platform, rc if rc else None)
    if sentence.startswith("The step did not finish"):  # no catalogue line fits: the runner answered something else
        _, sentence, fix = explain("probe_no_ready", platform)
    return False, sentence, fix


def write_verified(root: Path | None, date: str, home: Path | None = None) -> None:
    """Q11: `verified: <date>` in the machine profile and in `agent:` of the project config (a text edit, comments stay)."""
    profile.update({"verified": date}, home)
    pj = Path(root) / AGENT_DIR / "project.yaml" if root is not None else None
    if pj is None or not pj.exists():
        return
    import yaml
    text = pj.read_text(encoding="utf-8")
    if re.search(r"(?m)^[ \t]+verified:", text):
        new = re.sub(r"(?m)^([ \t]+)verified:.*$", rf'\g<1>verified: "{date}"', text, count=1)
    else:
        m = re.search(r"(?m)^agent:[ \t]*(?:#.*)?$", text)
        if not m:
            return
        nxt = re.search(r"(?m)^([ \t]+)\S", text[m.end():])
        new = text[:m.end()] + f'\n{nxt.group(1) if nxt else "  "}verified: "{date}"' + text[m.end():]
    try:
        ok = isinstance(yaml.safe_load(new).get("agent"), dict)
    except (yaml.YAMLError, AttributeError):
        ok = False
    if ok:
        pj.write_text(new, encoding="utf-8")


def run_setup(root: Path | None = None, *, dry_run: bool = False, wanted: str = "", yes: bool = False,
              skip_login: bool = False, skip_probe: bool = False, env: dict | None = None, home: Path | None = None,
              platform: str | None = None, which=None, run=run_proc, ask=None, say=print, login=None) -> int:
    """The whole command. Every dependency can be replaced by a test (fake PATH, fake run, fake terminal)."""
    env = dict(os.environ if env is None else env)
    wanted = wanted or env.get("AUTOPILOT_RUNNER", "")
    s = scan(env, home, which, run)
    row, rc = (default_runner(s), EXIT_OK) if dry_run and not wanted else choose(s, wanted=wanted, yes=yes, ask=ask, say=say)
    if rc != EXIT_OK:
        return rc
    for line in plan_lines(s, row, platform):
        say(line)
    from .precheck import apply, check, gather
    snap = gather(env, home, which, run, cwd=str(root) if root else None)
    snap.platform = platform or snap.platform
    for id_, status, text in apply(check(snap), snap, run=run, dry_run=dry_run):
        say(f"{status:<9} {text}")
    if root is not None:  # Q15: why a project in OneDrive, on a share or under /mnt hurts, and the one command
        from ..move import warning
        for n, line in enumerate(warning(Path(root), env=env, platform=platform, home=home)):
            say(f"{'found' if n == 0 else 'next':<9} {line}")
    if dry_run:
        say("dry run: nothing installed, nothing written")
        return EXIT_OK
    if row is None:
        return EXIT_CHOICE
    exe = next(exe for r, exe, _ in s.runners if r is row)
    logged = next(ok for r, _, ok in s.runners if r is row)
    if not exe:
        rc = install_runner(row, env=env, platform=platform, run=run, say=say, home=home)
        if rc != EXIT_OK:
            return rc
        path = env.get("PATH", "") + os.pathsep + str(Path(home or Path.home()) / ".local" / "bin")
        exe = row.which(path) or ""
        if not exe:
            say(f"FAILED  {row.name} installed, but `{row.binary}` is not on PATH yet. Open a new terminal, then run `ap setup` again.")
            say(f"        details: {log_path(home)}")
            return EXIT_FAILED
        logged = _logged_in(exe, row, {**env, "PATH": path})
    if logged:
        say(f"login     {row.name}: logged in")
    elif skip_login:
        say(f"login     {row.name}: not logged in (skipped). Run `{row.login}` before the first build.")
    else:
        say(f"login     {row.name}: not logged in. Run `{row.login}`, then start the build. You need {row.plan}.")
        if login is not None and login(row):  # Q13: every runner; the address and code are printed as text
            logged = _logged_in(exe, row, {**env, "PATH": env.get("PATH", "") + os.pathsep + str(Path(home or Path.home()) / ".local" / "bin")})
    remember_choice(root, row, say)
    from ..rights import describe
    say(f"rights    {describe(platform)}")
    if skip_probe:
        return EXIT_OK
    if not logged:
        say("probe     skipped: log in first, then run `ap setup` again to prove the runner answers.")
        return EXIT_OK
    say(f"probe     {row.name}: sending one prompt, up to {PROBE_TIMEOUT} seconds")
    ok, sentence, fix = probe(row, exe, env={**env, "CI": "1"}, run=run, platform=platform)
    if ok:
        date = datetime.date.today().isoformat()
        write_verified(root, date, home)
        say(f"verified  {row.name}: answered ready ({date})")
        return EXIT_OK
    say(f"FAILED  probe {row.name}")
    say(f"        {sentence}")
    say(f"        Run by hand: {fix or 'ap doctor --runner'}")
    return EXIT_FAILED


def cmd_setup(args) -> int:
    from ..cli import login_now
    root = Path(args.path).resolve() if getattr(args, "path", None) else Path.cwd()
    return run_setup(root, dry_run=getattr(args, "dry_run", False), wanted=getattr(args, "runner", "") or "",
                     yes=getattr(args, "yes", False), skip_login=getattr(args, "skip_login", False),
                     skip_probe=getattr(args, "skip_probe", False), login=login_now)
