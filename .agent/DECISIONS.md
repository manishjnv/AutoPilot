# Decision Log

Append-only. One line per decision: `- [date] [task] decision — reason`.
Every session reads the latest entries so later work stays consistent with earlier choices.

- [2026-10-11] [P01-T01] Task.status is '' when the key is absent; sync_plan applies 'done' only to new or pending rows
- [2026-10-11] [P01-T02] discovery_pack section caps are 8000 (git), 24000 (documents), 12000 (stack), 8000 (tests), 60000 total (PACK_CAP) — keeps the pack under ~60k; the truncation marker is appended after the cut
- [2026-10-11] [P01-T03] untracked_files(root) in cli.py uses `git status --porcelain -uall`; the new-file warning is skipped outside a git repository — it is a hint only, nothing is deleted
- [2026-10-11] [P02-T01] missing_deps checks: node_modules/ (npm/pnpm/yarn); .venv/ or venv/ with pyvenv.cfg (uv, poetry; Poetry venv outside the project gives a false WARN); requirements*: project venv (.venv, venv, env) or an active venv; go.sum: non-empty GOMODCACHE (or GOPATH/pkg/mod) or vendor/; Cargo.lock: target/ or non-empty CARGO_HOME/registry. Yarn Berry (`__metadata:` in yarn.lock) gets `--immutable`. doctor row "dependencies" is WARN only
- [2026-10-11] [P02-T01] missing_deps presence checks: node_modules/ for npm/pnpm/yarn; .venv/ or venv/ for uv/poetry; project venv or active venv for requirements*; non-empty Go module cache or vendor/ for go.sum; target/ or cargo registry for Cargo.lock. Yarn Berry gets --immutable. Doctor row is WARN only.
- [2026-10-11] [P02-T02] install_deps(cfg) in cli.py runs after the agent CLI check; standard commands are de-duplicated, run one by one, and written to commands.setup as a JSON-style list by remember_setup (regex text edit, comments kept) — same approach as cmd_init
- [2026-10-11] [P02-T02] When commands.setup is set it is run as is and never rewritten
- [2026-10-11] [P03-T01] ADR: A: _MODEL_OPT per preset + {prompt_file} placeholder for aider; kiro on stdin only; cursor with _ASK + stdin → docs/adr/0001-presets-for-kiro-cursor-and-aider-a-model-option-f.md
- [2026-10-11] [P03-T01] aider preset uses --message-file {prompt_file} (temp file outside the worktree, removed after the run) because aider has no stdin prompt and /dev/stdin fails on Windows; model option is --model for kiro/cursor/aider (_MODEL_OPT; aider -m = --message), -m for the others
- [2026-10-11] [P03-T01] cursor preset relies on undocumented stdin plus short _ASK; kiro preset has no positional argument (a positional argument disables stdin)
- [2026-10-11] [P03-T01] aider preset uses --message-file {prompt_file}; CommandBackend writes a temp file (system temp dir) only when the template contains {prompt_file}, still pipes stdin, and deletes the file afterwards — aider has no stdin prompt and /dev/stdin fails on Windows
- [2026-10-11] [P03-T01] model option is --model for kiro/cursor/aider via _MODEL_OPT, -m for the others — aider -m means --message
- [2026-10-11] [P03-T01] kiro preset has no positional _ASK (a positional argument disables stdin); cursor keeps _ASK + undocumented stdin
- [2026-10-11] [P03-T02] ADR: A: RUNNERS table + key-first check + status argv via run_proc; check_login reused with a new timeout kwarg → docs/adr/0002-table-driven-detect-runner-in-doctor-py-key-variab.md
- [2026-10-11] [P03-T02] detect_runner checks key variables before running any status command; an empty key does not count; a status command counts only with rc 0, no timeout and no LOGGED_OUT wording — exit codes are undocumented
- [2026-10-11] [P03-T02] doctor.LOGIN_TIMEOUT (10 s) is the single timeout for login checks; tests lower it with monkeypatch
- [2026-10-11] [P03-T03] ADR: A: code default in config.defaults() + raw-file check + insert after `agent:` → docs/adr/0003-preflight-writes-the-detected-runner-raw-file-chec.md
