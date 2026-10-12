"""N5.2: `ap upgrade` (get the newest release) and `ap install` (install or repair Autopilot for this user)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from . import __version__
from .proc import run_proc

REPO = "manishjnv/AutoPilot"
API = f"https://api.github.com/repos/{REPO}/releases"
RIGHTS_CMD = {"win": "irm https://raw.githubusercontent.com/manishjnv/AutoPilot/main/install.ps1 | iex",
              "posix": "curl -fsSL https://raw.githubusercontent.com/manishjnv/AutoPilot/main/install.sh | bash"}
UV_LINE = "curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh"


def _open(url):
    """Default `urlopen`: https only, 60 s timeout."""
    if not url.startswith("https://"):
        raise ValueError(f"not an https url: {url}")
    return urllib.request.urlopen(url, timeout=60)


def checkout_root(file=None) -> Path | None:
    """The git checkout the package runs from (a `.git` and a `pyproject.toml` above the package), else None."""
    pkg = Path(file or __import__("autopilot").__file__).resolve().parent
    root = pkg.parent
    return root if (root / "pyproject.toml").is_file() and any((p / ".git").exists() for p in (root, *root.parents)) else None


def detect_install(file=None, which=shutil.which, run=run_proc) -> str:
    """'editable' (git checkout), 'uv' (a uv tool) or 'pip'."""
    if checkout_root(file):
        return "editable"
    if which("uv"):
        try:
            if "dev-autopilot" in run(["uv", "tool", "list"], timeout=30).stdout:
                return "uv"
        except OSError:
            pass
    return "pip"


def _get(url, urlopen) -> bytes:
    with urlopen(url) as r:
        return r.read()


def latest_release(ref=None, run=run_proc, urlopen=_open, which=shutil.which) -> dict:
    """{'tag', 'wheel_url', 'sha256'} of the latest release (or of `ref`). `gh` when installed, else the public API."""
    data = None
    if which("gh"):
        p = run(["gh", "release", "view", *([ref] if ref else []), "-R", REPO, "--json", "tagName,assets"], timeout=60)
        if p.rc == 0:
            raw = json.loads(p.stdout)
            data = {"tag": raw["tagName"], "assets": {a["name"]: a["url"] for a in raw["assets"]}}
    if data is None:
        raw = json.loads(_get(f"{API}/tags/{ref}" if ref else f"{API}/latest", urlopen))
        data = {"tag": raw["tag_name"], "assets": {a["name"]: a["browser_download_url"] for a in raw["assets"]}}
    wheel = next((n for n in data["assets"] if n.endswith(".whl")), None)
    if not wheel or "SHA256SUMS" not in data["assets"]:
        raise ValueError(f"release {data['tag']} has no wheel or no SHA256SUMS")
    sums = _get(data["assets"]["SHA256SUMS"], urlopen).decode("utf-8", "replace")
    want = next((ln.split()[0] for ln in sums.splitlines() if ln.split()[-1:] and Path(ln.split()[-1].lstrip("*")).name == wheel), "")
    if not want:
        raise ValueError(f"SHA256SUMS has no line for {wheel}")
    return {"tag": data["tag"], "wheel_url": data["assets"][wheel], "sha256": want.lower()}


def fetch_wheel(rel: dict, urlopen=_open) -> Path | None:
    """Download the wheel to a temp folder; None (and one line) when its SHA256 differs from SHA256SUMS."""
    blob = _get(rel["wheel_url"], urlopen)
    got = hashlib.sha256(blob).hexdigest()
    if got != rel["sha256"]:
        print(f"refused: the wheel hash {got[:12]} is not the SHA256SUMS hash {rel['sha256'][:12]}")
        return None
    path = Path(tempfile.mkdtemp(prefix="autopilot-")) / rel["wheel_url"].rsplit("/", 1)[-1]
    path.write_bytes(blob)
    return path


def _ver(s: str) -> tuple:
    return tuple(int(x) for x in s.lstrip("v").split(".") if x.isdigit())


def _editable(root: Path, check: bool, run) -> int:
    if check:
        print(f"ap {__version__} runs from a git checkout: {root}")
        return 0
    if run(["git", "-C", str(root), "status", "--porcelain"], timeout=60).stdout.strip():
        print(f"the checkout has changes; commit them, then run: git -C {root} pull --ff-only")
        return 1
    p = run(["git", "-C", str(root), "pull", "--ff-only"], timeout=300)
    if p.rc != 0:
        print(f"git pull failed: {(p.stderr or p.stdout).strip()[:200]}")
        return 1
    print(f"updated {root}; run `ap --version` for the new version")
    return 0


def cmd_upgrade(args, run=run_proc, urlopen=_open, detect=detect_install, root=None) -> int:
    """`ap upgrade [--check] [--ref vX.Y.Z]`: install the newest release; --check only prints."""
    check = getattr(args, "check", False)
    if getattr(args, "daily", False):  # for the plugin: prints one line when a newer release exists, at most one lookup a day
        line = check_once_per_day(run=run, urlopen=urlopen)
        if line:
            print(line)
        return 0
    kind = detect()
    if kind == "editable":
        return _editable(root or checkout_root(), check, run)
    try:
        rel = latest_release(getattr(args, "ref", None), run=run, urlopen=urlopen)
    except (OSError, ValueError, KeyError) as e:
        print(f"cannot read the release: {e}")
        return 1
    if _ver(rel["tag"]) == _ver(__version__) and not getattr(args, "ref", None):
        print(f"ap {__version__} is the latest")
        return 0
    print(f"ap {__version__} -> {rel['tag']}")
    if check:
        print("run `ap upgrade` to install it")
        return 0
    wheel = fetch_wheel(rel, urlopen)
    if wheel is None:
        return 1
    cmd = (["uv", "tool", "install", "--reinstall", str(wheel)] if kind == "uv"
           else [sys.executable, "-m", "pip", "install", "--upgrade", str(wheel)])
    p = run(cmd, timeout=600)
    if p.rc != 0:
        print(f"install failed: {(p.stderr or p.stdout).strip()[:200]}")
        return 1
    print(f"installed {rel['tag']}")
    return 0


def cmd_install(args, run=run_proc, urlopen=_open, which=shutil.which) -> int:
    """`ap install [--rights]`: uv, then Autopilot at the latest tag; --rights = the one rights step."""
    if getattr(args, "rights", False):  # N5.4: the one rights step lives here, not in the install scripts
        from .rights import have_rights, setup_rights
        for line in setup_rights():
            print(line)
        return 0 if have_rights() else 1
    if not which("uv"):
        cmd = [sys.executable, "-m", "pip", "install", "--user", "uv"]
        print("run: " + " ".join(cmd))
        if run(cmd, timeout=600).rc != 0 or not which("uv"):
            print(f"uv is not on PATH; install it with: {UV_LINE}")
            return 1
    try:
        rel = latest_release(getattr(args, "ref", None), run=run, urlopen=urlopen)
    except (OSError, ValueError, KeyError) as e:
        print(f"cannot read the release: {e}")
        return 1
    wheel = fetch_wheel(rel, urlopen)
    if wheel is None:
        return 1
    if run(["uv", "tool", "install", "--reinstall", str(wheel)], timeout=600).rc != 0:
        print("uv tool install failed")
        return 1
    print(f"installed {rel['tag']}. Open a project folder and type ap")
    return 0


def _stamp() -> Path:
    base = os.environ.get("LOCALAPPDATA") if sys.platform.startswith("win") else os.environ.get("XDG_CACHE_HOME")
    return Path(base or Path.home() / ".cache") / "autopilot" / "upgrade-check"


def check_once_per_day(run=run_proc, urlopen=_open, stamp=None, now=time.time) -> str:
    """One line when a newer release exists, else ''. Asks the network at most once a day (stamp file)."""
    f = stamp or _stamp()
    try:
        if now() - f.stat().st_mtime < 86400:
            return f.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        tag = latest_release(run=run, urlopen=urlopen)["tag"]
        line = f"ap {tag} is out (you have {__version__}); run `ap upgrade`" if _ver(tag) > _ver(__version__) else ""
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(line, encoding="utf-8")
        return line
    except (OSError, ValueError, KeyError):
        return ""
