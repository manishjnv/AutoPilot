"""W7: a signed receipt per closed phase. `write` hashes the phase files and signs them with a key in the home folder
(`~/.autopilot/receipt.key`, `AUTOPILOT_HOME` moves it); `check` finds a missing file, a changed hash or a bad signature.
The key never lives in the project, so it cannot be committed."""
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1
NAME = "receipt.json"


def key_path(home: Path | None = None) -> Path:
    return Path(os.environ.get("AUTOPILOT_HOME") or (home or Path.home()) / ".autopilot") / "receipt.key"  # same rule as steps.py


def load_key(home: Path | None = None) -> bytes:
    p = key_path(home)
    if p.exists():
        return p.read_bytes()
    p.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sign(body: dict) -> str:
    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(load_key(), data, hashlib.sha256).hexdigest()


def write(root: Path, phase_id: str, files, commit: str, hist: Path | None = None) -> Path:
    """Write `<history>/<phase>/receipt.json`. `files` are paths in the phase folder; the receipt keeps their names."""
    hist = hist or Path(root) / ".agent" / "history" / phase_id
    body = {"version": VERSION, "phase": phase_id, "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "commit": commit, "files": {Path(f).name: sha(Path(f)) for f in sorted(files, key=lambda f: Path(f).name)
                                        if Path(f).is_file() and Path(f).name != NAME}}
    body["sig"] = sign(body)
    out = hist / NAME
    out.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return out


def check(root: Path, path: Path) -> list[str]:
    """The problems of one receipt, or an empty list. `root` is kept for the call shape; files sit next to the receipt."""
    path = Path(path)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        sig = str(body.pop("sig", ""))
        files = dict(body["files"])
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{NAME} unreadable"]
    problems = []
    for name, digest in files.items():
        p = path.parent / name
        if not p.is_file():
            problems.append(f"{name} missing")
        elif sha(p) != digest:
            problems.append(f"{name}")
    try:
        if not hmac.compare_digest(sig, sign(body)):
            problems.append("bad signature")
    except OSError:
        problems.append("no key")
    return problems
