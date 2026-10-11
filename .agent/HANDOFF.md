# Handoff

Last completed: **P04-T02 — Plain `ap`: adopt a project that has code and no .agent/** (2026-10-11)

Plain `ap` in a terminal now decides the case from the folder. An empty folder or one with only dotfiles gets the idea prompt. A folder with code and no .agent/project.yaml is adopted: preflight, quiet init, onboarding with no plan doc, adopt_summary, then the 1/2 start choice. A folder with .agent/ keeps the old banner behavior. Verified by new tests for all three cases, including no questions without a terminal; the quickstart and adopt tests pass (30 passed, 3 skipped), ruff clean, WSL script not run.

Files: GUIDE.md, README.md, autopilot/cli.py, tests/test_quickstart.py

Follow-ups noted:
- The WSL script docs/wsltest_self.sh was not run; the tests ran on Windows only
- test_folder_safety was changed to create its `full` folder under tmp_path, because a file in the work folder now counts as the adopt case

Next planned task: P07-T01
