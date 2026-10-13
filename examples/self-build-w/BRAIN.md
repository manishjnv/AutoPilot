# Project Brain

> Read at the start of every autonomous session. Keep it short (< 300 lines) and current.

## Product
This repository IS Autopilot (`dev-autopilot` on PyPI, commands `autopilot` and `ap`). It is a Python orchestrator
that runs hundreds of fresh CLI-agent sessions (Claude Code by default) back to back to build a phased plan
(`.agent/plan.yaml`). Python decides what to keep: it runs the checks, owns git, picks models and keeps the budget.
The agent only writes code for one task at a time.

Current roadmap step: **section W** (2026-10-13): make a run visible, trusted and found. Built (P01-P10): W3 outcome
word + Not proven list, W2 `ap tour`, W4 review on every task, W7 signed receipts + `ap verify`, W6 draft PR, W9
proof card + badge, W8 `ap audit --history`, W1 README position + Safety, W5 plugin Stop hook, W10 Routine page.
Open: `sandbox.mode: docker` (W11, P11), local models (W13, P12), VS Code extension (W12, P13), follow-ups (P14).
Sections N, O, Q and T are built and merged (see git log).

Owner documents (link, do not copy): `README.md`, `GUIDE.md` (tutorial), `HOWTO.md` (tasks, install),
`REFERENCE.md` (all commands and settings), `ARCHITECTURE.md` (why and how), `SECURITY.md`. The roadmap
(`docs/ROADMAP.md`) is private: `docs/` is git-ignored here.

## Architecture
Package `autopilot/` (setuptools packages: `autopilot`, `autopilot.backends`, `autopilot.commands`):
- `cli.py` — argparse entry `main()`; subcommands `init`, `onboard`, `quickstart`, `preflight`, `validate`, `doctor`,
  `run`/`start`, `status`, `watch`, `serve`, `next`, `answer`, `change`, `hint`, `skip`, `approve`, `stop`,
  `verify`, `tour`, `audit`, ... `ap audit` runs the completion audit session (`cmd_review`, kind=completion);
  W8 `ap audit --history [--days] [--home]` is offline (`commands/audit.py`, RATES dict, no project needed). No-project commands (`upgrade`, `install`, `setup`,
  `uninstall`, `tour`) are routed in `main()` before `pick_project`/`remember`. `start_status_page` (8765, tries 10
  ports) starts the loopback status page of a run (P13-T01a will write the port to `.agent/status.port`).
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
  P08-T01: `cmd_init --stack` replaces only the indented lines of the `commands:` block; every later block
  (gate:, agent:, models:, ...) and its comments stay. P08-T02: a CLAUDE.md with the old Autopilot heading but no
  `ap status` gets the last two snippet lines (Commands + plan files) appended once; `ap status` is the marker.
- `orchestrator.py` — the autonomous loop: `run_setup()` runs `commands.setup` at start; `repair_env()` starts one
  session that fixes tooling; task sessions, gate, retry ladder, diagnosis, phase checks, audits, deploys.
  W3: `outcome_word(outcome, parked, stop)` is the only classifier (VERIFIED, BLOCKED, BUDGET_STOP, STALLED,
  FAILED); a `Stop(..., word=...)` names its word at the raise site; `Orchestrator._end_word()` is the only writer
  (state, run.json `word`, notification first token). `run()` catches `Stop` only: a Ctrl+C end has no word yet
  (P14-T01). W4: `review_due(task)` is the one rule for a review (`review.scope`: defaults() = critical, template =
  all); `review_tests(gate)` feeds the gate's test output to the review prompt. Phase close order: `phase_done` docs
  -> close commit -> `docs_phase` -> `write_receipt` (W7, signs every file in `.agent/history/<phase>/`, own
  commit, a failure only logs). W6: pr mode opens `--draft` when warnings or untested criteria exist, then
  `gh pr ready` after green CI and before merge.
- `gate.py` — `task_gate(cfg, git, task)`: no-change, protected files, test-tamper, secret scan, scope warning, then
  the project commands. `main_gate()` for main.
- `plan.py` — `Plan.from_dict` validation (unique ids, known deps, no cycles), `next_ready()` ordering. Task status
  lives in the state DB, not in plan.yaml, except N1 `status: done` on a task (work already in the code or git
  log): `sync_plan` records it as done; any other status value is an error. `owner_only` tasks never run in the loop and stay pending, so a phase
  that depends on a phase with a pending owner task never starts.
- `state.py` — SQLite state (`.agent/state.db`): tasks, sessions, costs, phases, decisions. `sync_plan` adds tasks.
- `context.py` — renders prompts (`render(name, **vars)` fills `{{var}}`) and the context pack of each session;
  `discovery_pack(root, cfg)` (N1: git log, documents, stack files, test result) for onboarding.
- `backends/` — `claude_cli.py` (Claude Code headless, stream-json; `sandbox.enabled` = Claude Code's own sandbox
  with the egress allowlist via `--settings`, `sandbox_settings(cfg)`) and `command.py` (any CLI: prompt on stdin,
  JSON report in stdout; `PRESETS` for codex, gemini, opencode, kiro, cursor, aider (the config error lists `PRESETS` keys); `_MODEL_OPT` = `--model`
  for kiro/cursor/aider, else `-m`; a `{prompt_file}` placeholder writes a temp prompt file outside the worktree
  (aider). The default `agent.backend: claude_cli` lives in `config.defaults()`, not the template).
  `get_backend(cfg)` picks by `agent.backend`; `config.validate` accepts only `claude_cli` and `command` today
  (P12 adds `openai_compat` in `backends/openai_compat.py`, stdlib urllib). `claude_cli.py` is ~370 lines: new
  sandbox code goes in `backends/docker_box.py` (P11-T02). Sandbox readers of `sandbox.enabled` (claude_cli,
  doctor, gate, config) move to `config.sandbox_mode(cfg)` / `config.allowlist_on(cfg)` (P11-T01 contract). `parse_report(text)` in `backends/__init__.py` parses the JSON report of text backends.
- `doctor.py` — machine checks `(level, name, detail)` rows with OK/WARN/FAIL; `autofix` repairs PATH and the
  Claude CLI only. `RUNNERS` table + `detect_runner(env)` (N3: key variables first, then status command with rc 0
  and no logged-out wording; `LOGIN_TIMEOUT` 10 s). `missing_deps(root)` (N2: lock file -> install command; the
  doctor row is WARN only).
- `commands/preflight.py` — `ap preflight`: read-only credential checks for plan `infra` steps.
- `schemas.py` — JSON Schemas of session reports (passed to Claude as `--json-schema`). A new report field must be
  added here too. N7: optional `new_files` [{path, reason}] in the task report. `gate.NEW_FILE_RULE` is the rule
  text (system.md repeats it word for word, a test pins it; import it, never copy). `gate.missing_reasons` is
  called by `task_gate(..., report=None)` only when `gate.new_file_reasons` is true: one problem line with up to
  20 paths, then the rule. Test files and `.agent/` need no reason. Code default off: `config.defaults()` pins
  `gate.new_file_reasons: False`; the template sets `true` for new projects. `orchestrator.new_file_lines(report)` builds
  the commit-message reason lines for both commit paths.
- `docs.py` — history files, PHASE.md (`Documenter.phase_done`), PROOF.md (`Documenter.proof`, W3 `## Not proven` from
  `not_proven` / `untested_criteria` / `task_not_proven`: a criterion is covered when a 3-word window appears in the
  task's changed test files, read from the history file's `## Files changed`). `receipt.py` (W7): HMAC key in
  `~/.autopilot/receipt.key` (`AUTOPILOT_HOME`), `write` / `check`; `ap verify`. W9: `Documenter.proof_card` writes
  `proof.svg` + `BADGE.md` (one image line) next to PHASE.md; `card.py` builds the text (stdlib). docs.py is ~367
  lines: put new docs code in a helper module.
- `commands/tour.py` (W2): `ap tour` replays `autopilot/templates/tour/events.jsonl` (package data) through the
  watch renderer; `examples/tour/` is a documented copy pinned equal by a test; `scripts/make_tour.py` rebuilds it.
- `prompts/*.md` — session prompts (`system.md` rules of every session, `task.md`, `onboard.md`, `verify.md` = phase
  functional check, `review.md`, ...).
- `templates/agent/` — files `ap init` copies (`project.yaml`, `plan.yaml`, `BRAIN.md`, `CLAUDE.md.snippet`, ...);
  `templates/presets/<stack>.yaml` — `detect` files and default `commands` per stack.
- Dashboard: `dashboard.py` (data), `dash_term.py`, `dash_web.py`; `report.py` (status text, `next_steps_text`).
- Install: `install.sh` (Linux/macOS/WSL, run with `| bash`: it uses bash features), `install.ps1` (Windows);
  both use `AUTOPILOT_REF` and `DEFAULT_REF` (still `main`: no release tag yet, owner task P05-T03), install
  Python with `uv python install 3.12` when no Python >= 3.10 exists, check `ap` on PATH, and end with the line
  "Open a project folder and type `ap`." HOWTO checksums must be refreshed with the release tag. Claude Code plugin: `plugin/.claude-plugin/plugin.json`, `plugin/commands/autopilot.md`;
  W5 Stop hook `plugin/hooks/hooks.json` (timeout 330 s) -> `plugin/scripts/seal.py` (runs the test command, 300 s;
  blocks at most 5 times per session, counter file in the temp folder; tests `tests/test_plugin_hook.py`);
  root `.claude-plugin/marketplace.json` lists `./plugin`. W10: HOWTO Routine section + `examples/routine/prompt.md`
  (`tests/test_routine.py` checks each `ap` command it names via `python -m autopilot <cmd> --help`). `deploy/Dockerfile` = runner image (pinned Claude CLI,
  git, bubblewrap, socat, user 1000, /work).

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
- Test: `python -m pytest -q` (the owner runs them on WSL; on Windows a few older `skipif(win32)` tests skip)
- Lint: `python -m ruff check --select E9,F63,F7,F82 .`
- Try the CLI: `python -m autopilot --help`, `ap doctor`, `ap validate -C <project>`.
- Platform-only test parts: guard them with a plain `if` inside the test (e.g. bash present), keep the text checks
  running everywhere. There is no WSL script in the repo (`docs/` is git-ignored): sessions run pytest on the host
  and list "run on WSL" as a followup; the owner runs the suite on WSL (P07-T03).
