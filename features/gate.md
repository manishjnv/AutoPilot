# Feature contract: the gate

## What it does

`gate.task_gate` decides whether a task's staged change may merge. It runs the guards first, then the scope check,
then the project commands (build, lint, test). Any problem fails the attempt; `GateResult.report()` gives the problems
and the red output (capped at 6000 characters) to the retry. `gate.main_gate` runs the commands on main at a phase
close. Python decides; the agent's report never overrides a guard.

## Rules

- The guards of REFERENCE.md "Gate guards", each one a failed attempt: a deleted test file, a test renamed to a
  non-test path, fewer test functions, fewer assertions, a new skip or focus marker (a platform `skipif` too), a new
  collection hook in `conftest.py`, an added, changed or deleted CI file (`gate.ci_files`), a removed test setting or an
  added `--ignore`, `--deselect` or `-k`, a protected file (plan, settings, questions file, backlog, `gate.protected`),
  an added line that looks like a secret, an empty change (unless `allow_no_changes: true`).
- Kill by name (`kill_guard.kill_commands`): a Bash or PowerShell tool call in the Claude Code session log that runs
  `taskkill`, `pkill`, `killall` or `Stop-Process`, also behind `sudo`, `env`, `cmd /c` or `powershell -c` and after
  `&&`, `||`, `;`, `|`. Text in messages and a kill by pid do not count. Every Claude Code session gets the four deny
  rules even when `agent.disallowed_tools` sets its own list.
- Scope: a file outside `files_in_scope` fails (`outside files_in_scope`), except the always-free files (tests,
  `gate.scope_always` docs); from attempt 2 a file named under `scope_additions` with a reason passes.
- The kept-diff rule: an attempt that fails only on scope lines or only on a failed test command keeps its branch and
  changes, and the retry prompt says "The diff is kept". A protected file, a secret, a kill by name, a test-tamper
  finding, a review finding, a timed-out or stuck session, an escalation, an unstick session and a park still reset
  the code to the state before the attempt.
- Secret findings are redacted in the report; a finding's hint appears once however many findings there are.
- W65: a deleted non-test file outside `.agent/` and `features/` needs a reason in the report field `deleted_files` (renames
  excepted; `gate.delete_reasons: false` turns it off). The clean after a failed attempt or a review keeps the
  files that were untracked before the session started.

## Files

- `autopilot/gate.py`
- `autopilot/kill_guard.py`

## Tests that guard it

- `tests/test_gate.py::test_clean_and_additions_not_flagged`
- `tests/test_w65.py::test_deleted_file_needs_a_reason`
- `tests/test_w65.py::test_discard_keeps_the_owners_files`
- `tests/test_gate.py::test_deleted_test_file`
- `tests/test_gate.py::test_renamed_to_non_test`
- `tests/test_gate.py::test_count_drop`
- `tests/test_gate.py::test_emptied_test_body_flagged`
- `tests/test_gate.py::test_skip_marker`
- `tests/test_gate.py::test_platform_skipif_still_fails_and_the_hint_says_so`
- `tests/test_gate.py::test_conftest_collection_hook_flagged`
- `tests/test_gate.py::test_new_ci_workflow_flagged`
- `tests/test_gate.py::test_addopts_k_added`
- `tests/test_gate.py::test_needs_you_file_is_protected`
- `tests/test_gate.py::test_secret_positive`
- `tests/test_gate.py::test_secret_messages_redacted_and_placeholders_skipped`
- `tests/test_gate.py::test_task_gate_fails_a_file_outside_scope_unless_declared`
- `tests/test_gate.py::test_each_hint_appears_once_however_many_findings`
- `tests/test_kill_guard.py::test_kill_commands_reads_tool_calls_only`
- `tests/test_kill_guard.py::test_gate_fails_a_kill_by_name_and_names_it`
- `tests/test_kill_guard.py::test_gate_passes_text_mentions_and_kill_by_pid`
- `tests/test_kill_guard.py::test_build_cmd_always_denies_kill_by_name`
- `tests/test_keep_diff.py::test_scope_failure_keeps_the_diff_and_the_retry_only_adds_the_reason`
- `tests/test_keep_diff.py::test_test_failure_keeps_the_files_and_shows_the_test_output`
- `tests/test_keep_diff.py::test_protected_file_failure_still_discards`

## Changes

- 2026-10-14: first contract, written from the code and the tests (W36).
- 2026-10-15: W65 adds the deleted-file reason and the owner-file keep on the clean (`tests/test_w65.py`).
