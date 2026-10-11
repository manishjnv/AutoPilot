# Follow-ups

Reported by sessions; consumed by the auditor and replanner.

- [P07-T01] The full pytest suite was stopped at the 10-minute background limit before it finished; only 7 related test files ran here (130 passed). The orchestrator check run must confirm the rest.
- [P07-T01] Run the suite on WSL (docs/wsltest_self.sh, P07-T03); this session did not run it.
- [P07-T01] gate.py is outside the task's file list (by ADR 0004), so expect a scope warning.
