# Handoff

Last completed: **P08-T01 — `ap init --stack` keeps every block after `commands:`** (2026-10-11)

Fixed the cmd_init commands-block regex in cli.py: removed the re.S flag, match one line with [^\n]*, and substitute through a lambda. Two regression tests in tests/test_presets.py cover the template keys, the python preset commands, the scheduling comment line, and force twice. After the fix all 13 tests in tests/test_presets.py pass and ruff is clean. A wider run of the init-related test files (started before I corrected my own test) gave 269 passed, 1 skipped and 1 failure, the failure being my old test assertion that was fixed afterwards. That wider set was not re-run after the fix.

Files: autopilot/cli.py, tests/test_presets.py

Follow-ups noted:
- Run the full suite on WSL; this session did not run it.
- gate.new_file_reasons can now be written into a new project by ap init, since the gate: block survives.

Next planned task: P08-T02
