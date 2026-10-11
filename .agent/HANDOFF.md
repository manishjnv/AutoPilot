# Handoff

Last completed: **P07-T02 — Gate: a new file with no reason gets a retry with the rule quoted** (2026-10-11)

I added missing_reasons(cfg, git, report) to gate.py. A file added in the staged diff (except test files, .agent/ and renames) with no non-empty new_files reason produces one gate problem that quotes NEW_FILE_RULE at the end. task_gate takes an optional report=None and runs the check only when a report is passed and gate.new_file_reasons is true; the orchestrator passes res.report at all three gate calls. Verified: the 14 new tests pass, 7 related test files gave 137 passed and 1 failure (a typo in my own new test, fixed, and the fixed test passed alone), the 6 large orchestrator test files gave 81 passed, and ruff is clean. The full suite was not run on WSL.

Files: ARCHITECTURE.md, REFERENCE.md, autopilot/gate.py, autopilot/orchestrator.py, autopilot/templates/agent/project.yaml, tests/test_new_file_gate.py

Follow-ups noted:
- Run the suite on WSL (docs/wsltest_self.sh, P07-T03); this session did not run it.
- To turn N7 on by default: make the test fakes report new_files, then set gate.new_file_reasons: true. The P08-T01 cmd_init commands-regex bug drops the whole gate: block from project.yaml at init, so ap init or adopt cannot write the setting into a new project until P08-T01 is fixed.
- autopilot/templates/agent/project.yaml is outside the task's file list, so expect a scope warning.

Next planned task: P08-T01
