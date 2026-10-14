# Feature contract: install and setup

## What it does

`ap setup` finds a coding-agent CLI (the runner table `doctor.RUNNERS`), installs one if needed, checks the login
and probes it. The install scripts (`install.sh`, `install.ps1`, `install.cmd`) install Autopilot and then call
`ap setup`. `install_errors` turns a raw install failure into three plain lines and logs the raw text.

## Rules

- A logged-in runner wins with no question and no install; with no terminal and no flag, setup exits 3 with the
  rerun line.
- `--dry-run` prints the plan and writes nothing.
- A failed step shows three plain lines; the raw text goes to the log, scrubbed of token values.
- Every catalogue line has a sample, and every sample hits its line; unknown text gets the generic line.
- Every runner row has a probe with the prompt slot; plan lines read from the table only.
- The scripts stay thin, pass options to `ap setup`, and pass exit 3 through with one hint.
- `install.cmd` only starts PowerShell.

## Files

- `autopilot/doctor.py`
- `autopilot/commands/setup.py`
- `autopilot/install_errors.py`
- `install.sh`
- `install.ps1`
- `install.cmd`

## Tests that guard it

- `tests/test_setup.py::test_logged_in_codex_wins_with_no_question_and_no_install`
- `tests/test_setup.py::test_no_terminal_and_no_flag_exits_3_with_the_rerun_line`
- `tests/test_setup.py::test_runner_flag_and_env_answer_in_advance_and_an_unknown_name_is_usage`
- `tests/test_setup.py::test_dry_run_prints_the_plan_and_writes_nothing`
- `tests/test_setup.py::test_a_failed_install_shows_three_plain_lines_and_the_raw_text_goes_to_the_log`
- `tests/test_setup.py::test_token_values_never_reach_the_log_or_the_screen`
- `tests/test_setup.py::test_plan_lines_read_from_the_table_only`
- `tests/test_setup.py::test_every_runner_row_has_a_probe_with_the_prompt_slot`
- `tests/test_install_errors.py::test_every_catalogue_line_has_a_sample_and_every_sample_hits_its_line`
- `tests/test_install_errors.py::test_unknown_text_gets_the_generic_line`
- `tests/test_install_errors.py::test_capture_logs_the_raw_text_and_shows_three_plain_lines`
- `tests/test_install_errors.py::test_log_is_scrubbed_of_token_values`
- `tests/test_install_errors.py::test_exit_codes_are_stable`
- `tests/test_install_scripts.py::test_scripts_stay_thin_and_keep_the_bump_lines`
- `tests/test_install_scripts.py::test_options_pass_through_to_ap_setup_and_bad_ones_are_usage`
- `tests/test_install_scripts.py::test_setup_exit_3_is_passed_through_with_one_hint`
- `tests/test_install_scripts.py::test_a_failed_step_prints_three_lines_and_logs_the_raw_text`
- `tests/test_install_scripts.py::test_install_ps1_parses`
- `tests/test_install_scripts.py::test_cmd_wrapper_only_starts_powershell`

## Changes

- 2026-10-14: first contract, written from the code and the tests (W52).
