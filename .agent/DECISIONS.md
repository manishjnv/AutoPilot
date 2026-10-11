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
- [2026-10-11] [P03-T03] default agent.backend (claude_cli) lives in config.defaults(), not the template; preflight decides "unset" from the raw project.yaml (no backend/command/preset); remember_runner inserts after `agent:` (or appends an agent block) and writes only when yaml.safe_load of the new text gives exactly the old values plus the new keys
- [2026-10-11] [P03-T03] no runner detected but claude installed (logged out) -> no write, claude_cli default, so the H2 login offer runs; AUTOPILOT_CLAUDE_BIN set -> detection skipped (explicit claude choice)
- [2026-10-11] [P03-T03] default agent.backend claude_cli lives in config.defaults(), not the template; preflight decides 'unset' from the raw project.yaml (none of backend/command/preset) — every cfg.get reader stays unchanged
- [2026-10-11] [P03-T03] remember_runner inserts after `agent:` (or appends an agent block) and writes only when yaml.safe_load of the new text gives the old values plus the new keys — a project.yaml is never broken
- [2026-10-11] [P03-T03] no runner detected but claude installed -> no write, claude_cli default (the H2 login offer still runs); AUTOPILOT_CLAUDE_BIN set -> detection skipped as an explicit claude choice
- [2026-10-11] [P05-T01] Python install is part of step 4 (still 5 steps) and its dry-run text avoids the words 'would install' — existing tests count exactly 3 of them
- [2026-10-11] [P05-T01] The Python install uses `uv python install 3.12`; the check looks for python3, python (and py on Windows) with version >= 3.10
- [2026-10-11] [P05-T02] The Linux/macOS/WSL README line uses `| bash`, not `| sh`: install.sh uses `set -o pipefail` and `$'\n'`, which dash rejects. HOWTO explains this and install.sh is unchanged.
- [2026-10-11] [P06-T01] IDE block uses <!-- autopilot:begin --> markers; new Cursor/Kiro files get front matter first, existing files only get the block appended; skip if the begin marker is present — keeps the user's text byte-identical and init idempotent
- [2026-10-11] [P06-T01] CLAUDE.md is not marked: the existing heading check stays, the snippet only gained the ap command lines
- [2026-10-11] [D-001] It still fails after a diagnosis and a retry. How should we proceed? → Retry on sonnet. Call the final report once at the end. Keep all 12 tests in tests/test_adopt.py, add, do not remove.
- [2026-10-11] [P04-T01] adopt_summary reads plan.yaml and only opens state.db when it exists, so it never creates a DB — keeps a plain adopt side-effect free
- [2026-10-11] [P04-T01] adopt_summary emits no color; no escape codes by construction — color can be added later behind a parameter
- [2026-10-11] [P04-T02] folder_case(root) in cli.py returns agent, empty or code; entries that start with a dot do not count as content, so a bare git repo is empty — matches the 'only dotfiles / bare git repo' rule
- [2026-10-11] [P04-T02] adopt_start refuses to adopt the home folder or a filesystem root (safe_folder) and falls back to the banner — sessions run without prompts, so the folder must be safe
- [2026-10-11] [P07-T01] ADR: A: NEW_FILE_RULE constant in gate.py, same text in system.md pinned by a test, shared new_file_lines(report) helper in orchestrator.py → docs/adr/0004-p07-t01-new-file-rule-constant-in-gate-py-mirrored.md
- [2026-10-11] [P07-T01] NEW_FILE_RULE lives in gate.py and system.md repeats it word for word; a test checks that the two match. P07-T02 should import the constant and must not copy the text.
- [2026-10-11] [P07-T01] new_file_lines(report) in orchestrator.py is the only builder of commit lines for both commit paths. It keeps only dict entries with a non-empty path, joins whitespace into one line, cuts the reason at 300 characters and uses '(no reason given)' when the reason is empty, because text-only backends do not check reports against the schema.
- [2026-10-11] [P07-T01] The schema field new_files is optional (not in the required list), so old reports stay valid.
- [2026-10-11] [P07-T02] ADR: A: missing_reasons(cfg, git, report) helper in gate.py, called from task_gate(..., report=None) → docs/adr/0005-missing-reasons-helper-in-gate-py-with-an-optional.md
