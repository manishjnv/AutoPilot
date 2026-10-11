# Handoff

Last completed: **P02-T01 — Detect missing project dependencies and the standard install command** (2026-10-11)

Added missing_deps, system_tool_hint and a 'dependencies' WARN doctor row to autopilot/doctor.py; new tests/test_deps.py covers every lock file, both OS hints and the doctor row. test_deps.py and test_doctor.py pass (29) and ruff is clean; the full suite and WSL script were not run.

Files: .agent/DECISIONS.md, REFERENCE.md, autopilot/doctor.py, tests/test_deps.py

Follow-ups noted:
- A Poetry venv outside the project gives a false WARN; consider poetry env info -p or POETRY_VIRTUALENVS_IN_PROJECT
- Run the full pytest suite and the WSL script

Next planned task: P02-T02
