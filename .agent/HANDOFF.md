# Handoff

Last completed: **P02-T02 — Preflight installs project dependencies** (2026-10-11)

Preflight now installs missing project dependencies before a run: it uses commands.setup, or the standard command written back into project.yaml with a comment-preserving text edit. A missing system tool prints `FAIL  <tool> is not installed. Install it with: <hint>` and returns False without installing. Verified by three new tests with a fake npm on PATH (24 pass in tests/test_deps.py on Windows; 36 across deps, doctor and presets on WSL); ruff is clean.

Files: HOWTO.md, REFERENCE.md, autopilot/cli.py, tests/test_deps.py

Follow-ups noted:
- Bug in cmd_init: the regex `(?ms)^commands:\n(?:[ \t]+.*\n)*` has re.S so `.*\n` eats the rest of project.yaml; after `ap init --stack X` everything after the commands block (agent:, scheduling:, ...) is lost
- Run the full pytest suite and wsltest_self.sh (the script path was not found from Git Bash)

Next planned task: P03-T01
