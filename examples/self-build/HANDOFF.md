# Handoff

Last completed: **P09-T01 — Template turns the new-file guard on; old project.yaml stays off** (2026-10-11)

The project.yaml template now sets gate.new_file_reasons to true, so `ap init` (with or without --stack) writes it on, with the reworded comment kept. config.defaults() is built from the template, so I pinned the code default to False there. A project.yaml without the key stays off. Verified with the new tests, the related test files (new_file_gate, runner_detect, adopt, autofix, presets: 73 passed, 1 skipped) and ruff. The full-suite background run was stopped at its time limit, so the full suite is not verified here.

Files: REFERENCE.md, autopilot/config.py, autopilot/templates/agent/project.yaml, tests/test_new_file_gate.py

Follow-ups noted:
- config.py is outside the listed scope but the one-line change was required
- Run the full suite on WSL (P07-T03); the full Windows run was stopped at its time limit in this session

Next planned task: (none)
