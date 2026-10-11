# Handoff

Last completed: **P08-T02 — Config error lists all presets; an existing CLAUDE.md gets the `ap` lines** (2026-10-11)

The command-backend config error now lists every name in backends.command.PRESETS, so kiro, cursor and aider appear. An existing CLAUDE.md with the old Autopilot heading but no `ap status` gets the two command lines of the snippet appended once; user text stays byte-identical and a file that already has `ap status` is untouched. Targeted tests (20) in test_presets.py and test_ide_rules.py pass and ruff is clean. The full pytest run on this Windows machine finished with exit code 0 (no failures; two skips, not checked against the pre-change baseline), though its captured output has no summary line.

Files: autopilot/cli.py, autopilot/config.py, tests/test_ide_rules.py, tests/test_presets.py

Follow-ups noted:
- Run the full suite on WSL (wsltest_self.sh); the Windows full run passed with exit code 0 but gave no pass count, and the owner's WSL run is the real check
- Check whether the two skipped tests in the full run predate this change

Next planned task: (none)
