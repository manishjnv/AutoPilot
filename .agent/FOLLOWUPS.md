# Follow-ups

Reported by sessions; consumed by the auditor and replanner.

- [P07-T01] The full pytest suite was stopped at the 10-minute background limit before it finished; only 7 related test files ran here (130 passed). The orchestrator check run must confirm the rest.
- [P07-T01] Run the suite on WSL (docs/wsltest_self.sh, P07-T03); this session did not run it.
- [P07-T01] gate.py is outside the task's file list (by ADR 0004), so expect a scope warning.
- [P07-T02] Run the suite on WSL (docs/wsltest_self.sh, P07-T03); this session did not run it.
- [P07-T02] To turn N7 on by default: make the test fakes report new_files, then set gate.new_file_reasons: true. The P08-T01 cmd_init commands-regex bug drops the whole gate: block from project.yaml at init, so ap init or adopt cannot write the setting into a new project until P08-T01 is fixed.
- [P07-T02] autopilot/templates/agent/project.yaml is outside the task's file list, so expect a scope warning.
