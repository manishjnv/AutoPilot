# Handoff

Last completed: **P04-T01 — One-screen adopt summary: done, open, next** (2026-10-11)

Added adopt_summary(root) in autopilot/report.py: from plan.yaml, or the state DB when it exists, it prints done/open counts, per-phase progress, the next ready task and open owner-only tasks, in at most about 20 plain lines. Four new tests in tests/test_adopt.py cover counts, the line limit with no escape codes, the no-state-DB case and owner tasks. The full pytest run on this machine exited 0 (2 skipped, no failures; the pass count line was not printed). Lint gate is clean.

Files: autopilot/report.py, tests/test_adopt.py

Follow-ups noted:
- Wire adopt_summary into plain `ap` for the code-without-.agent case (next N4 step)
- The WSL script (docs/wsltest_self.sh) was not run; the full suite ran on Windows only

Next planned task: P04-T02
