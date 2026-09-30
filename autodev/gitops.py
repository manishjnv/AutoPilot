"""Git operations. The orchestrator owns git; agent sessions never commit or switch branches."""
from __future__ import annotations

import subprocess
from pathlib import Path


# Never committed, whatever the project's .gitignore says (written to .git/info/exclude).
JUNK = ["__pycache__/", "*.py[cod]", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", "*.egg-info/",
        "node_modules/", ".next/", ".turbo/", ".DS_Store", "*.swp", ".coverage", "coverage/", "htmlcov/",
        ".venv/", "venv/", ".env", ".env.*", "!.env.example", "target/debug/", "target/release/"]


class GitError(RuntimeError):
    pass


class Git:
    def __init__(self, root: Path):
        self.root = Path(root)

    def run(self, *args: str, check: bool = True) -> str:
        p = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        if check and p.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
        return p.stdout.strip()

    def ok(self, *args: str) -> bool:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True).returncode == 0

    # ---------- setup ----------
    def ensure_repo(self, main: str):
        if not (self.root / ".git").exists():
            self.run("init", "-q", "-b", main)
        if not self.ok("config", "user.email"):
            self.run("config", "user.email", "autodev@localhost")
        if not self.ok("config", "user.name"):
            self.run("config", "user.name", "AutoDev")
        exclude = self.root / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        current = exclude.read_text() if exclude.exists() else ""
        if "# autodev junk" not in current:
            exclude.write_text(current + "\n# autodev junk\n" + "\n".join(JUNK) + "\n")
        if not self.ok("rev-parse", "--verify", "HEAD"):
            self.run("add", "-A")
            self.run("commit", "-q", "--allow-empty", "-m", "[autodev] initial commit")
        if not self.ok("rev-parse", "--verify", main):
            self.run("branch", main)

    # ---------- queries ----------
    def head(self) -> str:
        return self.run("rev-parse", "HEAD")

    def branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")

    def is_clean(self) -> bool:
        return self.run("status", "--porcelain") == ""

    def staged_files(self) -> list[str]:
        self.run("add", "-A")
        out = self.run("diff", "--cached", "--name-only")
        return [l for l in out.splitlines() if l.strip()]

    def staged_added_lines(self) -> list[str]:
        out = self.run("diff", "--cached", "-U0", "--no-color")
        return [l[1:] for l in out.splitlines() if l.startswith("+") and not l.startswith("+++")]

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

    def delete_branch(self, name: str):
        self.run("branch", "-q", "-D", name, check=False)

    def reset_hard(self, ref: str):
        self.run("reset", "-q", "--hard", ref)

    def restore_file(self, path: str, ref: str = "HEAD"):
        self.run("checkout", ref, "--", path, check=False)

    def tag(self, name: str, ref: str = "HEAD"):
        self.run("tag", "-f", name, ref)

    def push(self, remote: str, main: str):
        self.run("push", "-q", remote, main)
        self.run("push", "-q", "-f", remote, "--tags")
