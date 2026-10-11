# Handoff

Last completed: **P07-T01 — New-file rule and reasons in the commit message** (2026-10-11)

Added the NEW_FILE_RULE constant to gate.py and the same text, word for word, as a bullet in system.md. task.md now asks for an optional `new_files` [{path, reason}] report field, and the task report schema accepts it without requiring it. A new helper, new_file_lines(report) in orchestrator.py, adds one `new file <path>: <reason>` line per entry to the task commit message on both the sequential and the parallel path; it drops bad entries and keeps every reason on one line. The 5 new tests pass (one runs a fake command-backend agent end to end), 130 tests across the related files pass, and ruff is clean; the full suite was stopped at the 10-minute background limit and the WSL script was not run.

Files: ARCHITECTURE.md, autopilot/gate.py, autopilot/orchestrator.py, autopilot/prompts/system.md, autopilot/prompts/task.md, autopilot/schemas.py, tests/test_new_file_gate.py

Follow-ups noted:
- The full pytest suite was stopped at the 10-minute background limit before it finished; only 7 related test files ran here (130 passed). The orchestrator check run must confirm the rest.
- Run the suite on WSL (docs/wsltest_self.sh, P07-T03); this session did not run it.
- gate.py is outside the task's file list (by ADR 0004), so expect a scope warning.

Next planned task: P07-T02
