"""GitHub noreply identity: `<id>+<login>@users.noreply.github.com`, read once from `gh api user`."""
from __future__ import annotations

import json
import subprocess

_cache: tuple[str, str] | None = None   # (name, noreply email); only a success is cached


def set_github_user(login: str, uid: int | str | None = None):
    """Fallback when `gh` fails: the owner answered with a username. Without an id the legacy `<login>@users...` form."""
    global _cache
    _cache = (login, f"{uid}+{login}@users.noreply.github.com" if uid else f"{login}@users.noreply.github.com")


def github_identity() -> tuple[str, str] | None:
    """(name, noreply email) or None when gh is missing / not logged in and nobody gave a username."""
    global _cache
    if _cache is None:
        try:
            p = subprocess.run(["gh", "api", "user"], capture_output=True, text=True, encoding="utf-8", timeout=20)
            if p.returncode == 0:
                d = json.loads(p.stdout)
                set_github_user(d["login"], d["id"])
                _cache = (d.get("name") or d["login"], _cache[1])
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass
    return _cache


def identity_env() -> dict[str, str]:
    """Env vars that make author AND committer the noreply identity (empty when unknown). Never reads user.email."""
    ident = github_identity()
    if not ident:
        return {}
    n, e = ident
    return {"GIT_AUTHOR_NAME": n, "GIT_AUTHOR_EMAIL": e, "GIT_COMMITTER_NAME": n, "GIT_COMMITTER_EMAIL": e}
