# Project Brain

> Read at the start of every autonomous session. Keep it short (< 300 lines) and current.

## Product
This repository IS Autopilot (`dev-autopilot` on PyPI, commands `autopilot` and `ap`). It is a Python orchestrator
that runs hundreds of fresh CLI-agent sessions (Claude Code by default) back to back to build a phased plan
(`.agent/plan.yaml`). Python decides what to keep: it runs the checks, owns git, picks models and keeps the budget.
The agent only writes code for one task at a time.

Current roadmap step: **section N** — adopt a half-built project, run under any agent CLI, start with one `ap`
command. Principles of N: one word to learn (`ap`); read before write; done work stays done; a new file needs a
reason; the IDE is not the runner, the CLI is.

Owner documents (link, do not copy): `README.md`, `GUIDE.md` (tutorial), `HOWTO.md` (tasks, install),
`REFERENCE.md` (all commands and settings), `ARCHITECTURE.md` (why and how), `SECURITY.md`. The roadmap
(`docs/ROADMAP.md`) is private: `docs/` is git-ignored here.

## Architecture
Package `autopilot/` (setuptools packages: `autopilot`, `autopilot.backends`, `autopilot.commands`):
- `cli.py` — argparse entry `main()`; subcommands `init`, `onboard`, `quickstart`, `preflight`, `validate`, `doctor`,
  `run`/`start`, `status`, `watch`, `serve`, `next`, `answer`, `change`, `hint`, `skip`, `approve`, `stop`, ...
  Also `preflight(cfg)` (machine check before quickstart/run), `cmd_init` (writes `.agent/` from
  `templates/agent/`, applies a stack preset, appends the CLAUDE.md snippet, `write_ide_rules(root)`),
  `cmd_onboard` (one onboarding session with `prompts/onboard.md` + `context.discovery_pack`).
  N2: `install_deps(cfg)` runs the standard install commands of `doctor.missing_deps` after the agent CLI check
  and `remember_setup` writes them to `commands.setup` (an existing `commands.setup` runs as is, never rewritten).
  N3: `remember_runner(proj_path, choice)` inserts the detected runner after `agent:` only when the raw
  project.yaml sets none of backend/command/preset (`AUTOPILOT_CLAUDE_BIN` set = explicit claude, no detection).
  N4: plain `ap` with a terminal: `folder_case(root)` -> `agent` | `empty` | `code` (dot entries do not count);
  `empty` -> `guided_start()` (H5), `code` -> `adopt_start(root)` (refuses home/filesystem root via
  `safe_folder`), then `report.adopt_summary` (done / open / next; reads plan.yaml, never creates state.db).
  N6: `write_ide_rules(root)` appends one `<!-- autopilot:begin -->` block (template `ide_rules.md`) to the rule
  file of each IDE present (`.cursor/rules/autopilot.mdc`, `.kiro/steering/autopilot.md`,
  `.github/copilot-instructions.md`, `GEMINI.md`, `AGENTS.md`); skipped when the marker exists.
  Known bug (P08-T01): the `commands:` regex in `cmd_init` has re.S and drops every block after it.
- `orchestrator.py` — the autonomous loop: `run_setup()` runs `commands.setup` at start; `repair_env()` starts one
  session that fixes tooling; task sessions, gate, retry ladder, diagnosis, phase checks, audits, deploys.
- `gate.py` — `task_gate(cfg, git, task)`: no-change, protected files, test-tamper, secret scan, scope warning, then
  the project commands. `main_gate()` for main.
- `plan.py` — `Plan.from_dict` validation (unique ids, known deps, no cycles), `next_ready()` ordering. Task status
  lives in the state DB, not in plan.yaml, except N1 `status: done` on a task (work already in the code or git
  log): `sync_plan` records it as done; any other status value is an error. `owner_only` tasks never run in the loop and stay pending, so a phase
  that depends on a phase with a pending owner task never starts.
- `state.py` — SQLite state (`.agent/state.db`): tasks, sessions, costs, phases, decisions. `sync_plan` adds tasks.
- `context.py` — renders prompts (`render(name, **vars)` fills `{{var}}`) and the context pack of each session;
  `discovery_pack(root, cfg)` (N1: git log, documents, stack files, test result) for onboarding.
- `backends/` — `claude_cli.py` (Claude Code headless, stream-json) and `command.py` (any CLI: prompt on stdin,
  JSON report in stdout; `PRESETS` for codex, gemini, opencode, kiro, cursor, aider; `_MODEL_OPT` = `--model`
  for kiro/cursor/aider, else `-m`; a `{prompt_file}` placeholder writes a temp prompt file outside the worktree
  (aider). The default `agent.backend: claude_cli` lives in `config.defaults()`, not the template).
  `get_backend(cfg)` picks by `agent.backend`.
- `doctor.py` — machine checks `(level, name, detail)` rows with OK/WARN/FAIL; `autofix` repairs PATH and the
  Claude CLI only. `RUNNERS` table + `detect_runner(env)` (N3: key variables first, then status command with rc 0
  and no logged-out wording; `LOGIN_TIMEOUT` 10 s). `missing_deps(root)` (N2: lock file -> install command; the
  doctor row is WARN only).
- `commands/preflight.py` — `ap preflight`: read-only credential checks for plan `infra` steps.
- `schemas.py` — JSON Schemas of session reports (passed to Claude as `--json-schema`). A new report field must be
  added here too. N7 (P07) adds an optional `new_files` [{path, reason}] to the task report; the gate then needs
  a reason for each added non-test file (`task_gate(..., report=None)`, problems quoted to the retry).
- `prompts/*.md` — session prompts (`system.md` rules of every session, `task.md`, `onboard.md`, `verify.md` = phase
  functional check, `review.md`, ...).
- `templates/agent/` — files `ap init` copies (`project.yaml`, `plan.yaml`, `BRAIN.md`, `CLAUDE.md.snippet`, ...);
  `templates/presets/<stack>.yaml` — `detect` files and default `commands` per stack.
- Dashboard: `dashboard.py` (data), `dash_term.py`, `dash_web.py`; `report.py` (status text, `next_steps_text`).
- Install: `install.sh` (Linux/macOS/WSL, run with `| bash`: it uses bash features), `install.ps1` (Windows);
  both use `AUTOPILOT_REF` and `DEFAULT_REF` (still `main`: no release tag yet, owner task P05-T03), install
  Python with `uv python install 3.12` when no Python >= 3.10 exists, check `ap` on PATH, and end with the line
  "Open a project folder and type `ap`." HOWTO checksums must be refreshed with the release tag. Claude Code plugin in `plugin/` and `.claude-plugin/`.

## Stack & conventions
- Python >= 3.10 (CI: 3.10 and 3.13 on Ubuntu and Windows). One runtime dependency: PyYAML. Tests: pytest.
- Tests in `tests/test_*.py`, one file per area (e.g. `test_preflight.py`, `test_presets.py`, `test_gate.py`).
  Fake agents are scripts set through `agent.backend: command` + `agent.command`; real CLIs are never called.
  `tests/conftest.py` sets `AUTOPILOT_NO_AUTOFIX`, `AUTOPILOT_NO_BROWSER`, `AUTOPILOT_HOME` for every test.
  Build fixture repositories in `tmp_path` inside the test (no binary fixtures in the repo).
- Code style: compact, many one-line helpers, comments name the roadmap item (`# H5:`, `# J2:`, `# N1:`).
  Keep that density; no new framework. Prefer extending the file that owns the behavior over new modules.
- Text edits of YAML that users read keep comments (see `cmd_init`: regex edits, not `yaml.safe_dump`), except
  plan.yaml which is rewritten with `yaml.safe_dump`.
- Screen text is plain, short English (ASD-STE100 style, see `plain.py`). Docs are linted by Vale in CI.
- External commands go through `proc.run_proc` / `doctor._run` (UTF-8, timeouts). Shell commands must work in sh
  and cmd.exe (double quotes, no single quotes).
- Lint gate: only real-error ruff rules (`E9,F63,F7,F82`). The full ruff set reports ~58 style findings
  (E701/E702 one-line statements are house style): do not "fix" them.

## Invariants (never break)
- The agent's "done" is never trusted: the orchestrator runs the commands. Sessions never commit, push or switch
  branches; the orchestrator owns git.
- Never weaken the gate: test-tamper guard, secret scan, protected files (`.agent/plan.yaml`, `.agent/project.yaml`,
  the questions file) stay.
- No test is deleted, skipped or weakened; no CI file or pytest setting is edited. Test data uses `example`, `dummy`
  or `fake` values.
- Secrets only from environment variables; never logged (`log_scrub.py`).
- System tools (Python, Node, git, an agent CLI) are never installed by a run; Autopilot prints the exact install
  command. The only exception: the installer script may install Python (N5). Project dependencies install without
  a question (N2).
- Never overwrite the user's own files (CLAUDE.md, IDE rule files): append a marked block once, idempotently.
- Backwards compatible config: existing `project.yaml` / `plan.yaml` files keep working; new keys are optional.
- Tests run on WSL/Linux with the project test command; do not add a Windows-only test runner. Never add `skipif`.

## How to run
- Setup: `python -m pip install -e ".[dev]" ruff`
- Test: `python -m pytest -q` (507 tests collected at onboarding; the owner runs them on WSL)
- Lint: `python -m ruff check --select E9,F63,F7,F82 .`
- Try the CLI: `python -m autopilot --help`, `ap doctor`, `ap validate -C <project>`.
- Platform-only test parts: guard them with a plain `if` inside the test (e.g. bash present), keep the text checks
  running everywhere. There is no WSL script in the repo (`docs/` is git-ignored): sessions run pytest on the host
  and list "run on WSL" as a followup; the owner runs the suite on WSL (P07-T03).
