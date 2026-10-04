"""Git operations. The orchestrator owns git; agent sessions never commit or switch branches."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .github_util import identity_env

# Agent sessions can write .git/ and the user's git config. Nothing they plant may run inside the orchestrator's own
# git calls: hooks and fsmonitor are switched off per call, filters are removed after each session (guard_config).
SAFE = ["-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false"]
FILTER_RX = r"^filter\..+\.(clean|smudge|process)$"

# Never committed, whatever the project's .gitignore says (written to .git/info/exclude).
JUNK = ["__pycache__/", "*.py[cod]", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", "*.egg-info/",
        "node_modules/", ".next/", ".turbo/", ".DS_Store", "*.swp", ".coverage", "coverage/", "htmlcov/",
        ".venv/", "venv/", ".env", ".env.*", "!.env.example", "target/debug/", "target/release/"]


class GitError(RuntimeError):
    pass


class Git:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.new_tags: set[str] = set()   # pushed explicitly; tags an agent creates are never pushed

    def run(self, *args: str, check: bool = True) -> str:
        p = self._git(args)
        if p.returncode != 0 and self._clear_stale_lock(p.stderr):  # heal: a crashed git left index.lock behind
            p = self._git(args)
        if check and p.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
        return p.stdout.strip()

    def _git(self, args):
        return subprocess.run(["git", *SAFE, *args], cwd=self.root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env={**os.environ, **identity_env()})

    def _clear_stale_lock(self, stderr: str, min_age: float = 60) -> bool:
        """`index.lock': File exists` from a git process that died (crash, reboot): remove the lock once it is older
        than `min_age` seconds. A live git holds it for milliseconds, so an old lock is a dead one."""
        import time
        lock = self.root / ".git" / "index.lock"
        if "index.lock" not in (stderr or "") or not lock.exists() or time.time() - lock.stat().st_mtime < min_age:
            return False
        lock.unlink(missing_ok=True)
        return True

    def ok(self, *args: str) -> bool:
        return subprocess.run(["git", *SAFE, *args], cwd=self.root, capture_output=True,
                              encoding="utf-8", errors="replace").returncode == 0

    # ---------- config guard (around agent sessions) ----------
    def config_text(self) -> str:
        p = self.root / ".git" / "config"
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

    def guard_config(self, before: str) -> list[str]:
        """Undo .git/config edits and remove clean/smudge filters (git-lfs excepted) planted at any config level.
        Returns what was undone, for the log."""
        undone = []
        if self.config_text() != before:
            (self.root / ".git" / "config").write_text(before, encoding="utf-8")
            undone.append(".git/config restored")
        out = self.run("config", "--show-origin", "--get-regexp", FILTER_RX, check=False)
        for line in out.splitlines():
            origin, _, rest = line.partition("\t")
            key = rest.split(" ", 1)[0]
            if key.startswith("filter.lfs.") or not origin.startswith("file:"):
                continue
            self.run("config", "--file", origin[5:], "--unset-all", key, check=False)
            undone.append(f"removed {key} from {origin[5:]}")
        return undone

    # ---------- setup ----------
    def ensure_repo(self, main: str):
        if not (self.root / ".git").exists():
            self.run("init", "-q", "-b", main)
        if not identity_env():  # no GitHub identity known: old local fallback (env vars win when it is known)
            if not self.ok("config", "user.email"):
                self.run("config", "user.email", "autopilot@localhost")
            if not self.ok("config", "user.name"):
                self.run("config", "user.name", "Autopilot")
        exclude = self.root / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if "# autopilot junk" not in current and "# autodev junk" not in current:
            exclude.write_text(current + "\n# autopilot junk\n" + "\n".join(JUNK) + "\n", encoding="utf-8")
        if not self.ok("rev-parse", "--verify", "HEAD"):
            self.run("add", "-A")
            self.run("commit", "-q", "--allow-empty", "-m", "[autopilot] initial commit")
        if not self.ok("rev-parse", "--verify", main):
            self.run("branch", main)

    # ---------- queries ----------
    def head(self) -> str:
        return self.run("rev-parse", "HEAD")

    def ref(self, name: str, check: bool = True) -> str:
        return self.run("rev-parse", "--verify", "-q", f"refs/heads/{name}", check=check)

    def set_ref(self, name: str, sha: str):
        self.run("update-ref", f"refs/heads/{name}", sha)

    def branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")

    def is_clean(self) -> bool:
        return self.run("status", "--porcelain") == ""

    def staged_files(self) -> list[str]:
        self.run("add", "-A")
        out = self.run("diff", "--cached", "--name-only")
        return [l for l in out.splitlines() if l.strip()]

    def staged_added_lines(self) -> list[str]:
        out = self.run("diff", "--cached", "-U0", "--no-color", "--no-textconv", "--no-ext-diff")
        return [l[1:] for l in out.splitlines() if l.startswith("+") and not l.startswith("+++")]

    def change_size(self) -> tuple[list[str], int]:
        """(files, added + deleted lines) of all uncommitted work. Stages it, like staged_files()."""
        files, lines = self.staged_files(), 0
        for row in self.run("diff", "--cached", "--numstat").splitlines():
            added, deleted = (row.split("\t") + ["", ""])[:2]
            lines += int(added) + int(deleted) if added.isdigit() and deleted.isdigit() else 0  # binary: "-"
        return files, lines

    def log_oneline(self, n: int = 15) -> str:
        return self.run("log", f"-{n}", "--oneline", check=False)

    # ---------- task branch lifecycle ----------
    def checkout_main(self, main: str):
        self.run("checkout", "-q", "-f", main)

    def start_branch(self, name: str, main: str) -> str:
        self.checkout_main(main)
        self.discard()
        self.run("checkout", "-q", "-B", name, main)
        return self.head()

    def normalize_after_session(self, branch: str, base_sha: str):
        """Undo anything the agent did to git itself: keep file changes, drop its commits/branch moves."""
        if self.branch() != branch:
            self.run("checkout", "-q", branch, check=False)
        if self.head() != base_sha:
            self.run("reset", "-q", "--soft", base_sha)

    def discard(self):
        self.run("reset", "-q", "--hard")
        self.run("clean", "-q", "-fd")

    def stash_all(self, message: str):
        self.run("reset", "-q")
        self.run("stash", "push", "--include-untracked", "-m", message)

    def commit_all(self, message: str) -> str | None:
        if not self.staged_files():
            return None
        self.run("commit", "-q", "-m", message)
        return self.head()

    def merge(self, branch: str, main: str, message: str) -> str:
        self.checkout_main(main)
        try:
            self.run("merge", "-q", "--no-ff", "-m", message, branch)
        except GitError:
            self.run("merge", "--abort", check=False)
            raise
        return self.head()

    def add_worktree(self, path, branch: str, base: str):
        """A separate checkout of `base` on a fresh `branch` (P3). Clears a leftover of the same name first."""
        self.drop_worktree(path, branch)
        self.run("worktree", "add", "-q", "-B", branch, str(path), base)

    def drop_worktree(self, path, branch: str):
        self.run("worktree", "remove", "--force", str(path), check=False)
        shutil.rmtree(path, ignore_errors=True)
        self.run("worktree", "prune", check=False)
        self.delete_branch(branch)

    def delete_branch(self, name: str):
        self.run("branch", "-q", "-D", name, check=False)

    def reset_hard(self, ref: str):
        self.run("reset", "-q", "--hard", ref)

    def restore_file(self, path: str, ref: str = "HEAD"):
        self.run("checkout", ref, "--", path, check=False)

    def tag(self, name: str, ref: str = "HEAD"):
        self.run("tag", "-f", name, ref)
        self.new_tags.add(name)

    def has_remote(self, remote: str) -> bool:
        return self.ok("remote", "get-url", remote)

    def sync(self, remote: str, main: str) -> str:
        """Bring local `main` up to `remote/main` (fast-forward only; must be on a clean main).
        -> 'same' | 'ahead' (local has commits to push) | 'pulled'. Raises GitError when they diverged."""
        self.run("fetch", "-q", remote, f"refs/heads/{main}")
        theirs, ours = self.run("rev-parse", "FETCH_HEAD"), self.ref(main)
        if theirs == ours:
            return "same"
        if self.ok("merge-base", "--is-ancestor", theirs, ours):
            return "ahead"
        if not self.ok("merge-base", "--is-ancestor", ours, theirs):
            raise GitError(f"{main} and {remote}/{main} have diverged")
        self.checkout_main(main)
        self.run("merge", "-q", "--ff-only", theirs)
        return "pulled"

    def rebase_on_fetched(self, main: str):
        """Heal a diverged main: replay the local-only commits on top of the fetched remote main (run sync() first).
        On a conflict the rebase is aborted, main is left as it was, and GitError is raised."""
        self.checkout_main(main)
        try:
            self.run("-c", "user.name=Autopilot", "-c", "user.email=autopilot@localhost", "rebase", "-q", "FETCH_HEAD")
        except GitError:
            self.run("rebase", "--abort", check=False)
            raise

    def push(self, remote: str, main: str):
        self.run("push", "-q", remote, f"refs/heads/{main}:refs/heads/{main}")
        if self.new_tags:  # force: a phase redeploy moves its tag
            self.run("push", "-q", "-f", remote, *(f"refs/tags/{t}:refs/tags/{t}" for t in sorted(self.new_tags)))
            self.new_tags.clear()
