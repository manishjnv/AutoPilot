
## 2026-10-13
# Follow-ups

Reported by sessions; consumed by the auditor and replanner.

- [P01-T01] A test_steps upgrade test writes into the real repository when the suite runs on Windows (.gitignore line, .agent/backup-legacy/). It should use tmp_path.
- [P01-T01] A Ctrl+C end ('interrupted') sets no word.
- [P01-T01] The dash_term bottom-bar 'Stopped' cell does not show the word; that needs a key in dashboard.py.
- [P01-T02] Run the full suite on WSL (only the three related test files ran on the host).
- [P01-T02] Scope-added lines appear both in the PROOF header and in the Not proven section.
- [P02-T01] Run the full test suite on WSL
- [P02-T01] The ap tour command (next tasks) should read this format and print examples/tour/PROOF.md at the end
- [P02-T02] Run the full test suite on WSL (the CRLF failure of test_make_tour_regenerates_the_same_file should not occur there)
- [P02-T02] Consider a .gitattributes entry (`examples/tour/* text eol=lf`) so the byte-compare test also passes on Windows checkouts
- [P03-T01] Drop the unused phase_goal/decisions arguments and the DECISIONS.md read from context.review_prompt
- [P03-T01] Review inside parallel worktrees to bring back parallelism under scope all
- [P03-T01] Fix the CRLF byte-compare failure of tests/test_tour.py::test_make_tour_regenerates_the_same_file on Windows checkouts (.gitattributes eol=lf)
- [P04-T01] Run the full suite on WSL (only tests/test_receipt.py and ruff were run here)
- [P04-T01] No test drives close_phase end to end to check that receipt.json appears
- [P04-T01] Receipt files not listed at signing time (a file added to the phase folder later) are not flagged by check
- [P05-T01] Run the full suite on WSL (only tests/test_pr_mode.py and ruff were run here)

## 2026-10-13
# Follow-ups

Reported by sessions; consumed by the auditor and replanner.

- [P06-T01] Run the full suite on WSL with wsltest_self.sh: only test_docs, test_receipt, test_pr_mode and test_orchestrator were run here; the background full-suite run was killed at its time limit
- [P07-T01] Run the full suite on WSL with wsltest_self.sh
- [P08-T01] Run wsltest_self.sh on WSL to confirm the full suite
- [P08-T01] Run vale README.md once vale is installed; the plain-words check was not run
- [P08-T01] Sentence length under 20 words was checked by reading, not by script
- [P09-T01] Run wsltest_self.sh on WSL to confirm the full suite
- [P09-T01] REFERENCE.md has no plugin hook entry yet; add one if a plugin section exists
- [P10-T01] Run wsltest_self.sh on WSL to confirm the full suite.
- [P10-T01] Confirm uv is present in the Routine environment; the prompt's step 1 depends on it.
- [P10-T01] Run the routine once live and update the HOWTO 'not run live' note and checklist after the first result.
