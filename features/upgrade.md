# Feature contract: upgrade and uninstall

## What it does

`ap upgrade` moves an install to the latest release; `ap install` installs from a release. The daily check, the
auto-update and the update before a run keep a machine current. `ap uninstall` removes Autopilot. `scripts/bump.py`
makes a release (version bump, tag) and refuses to tag without CI green.

## Rules

- The install kind is detected (editable, pip, uv). A dirty checkout is not pulled; `--check` never installs.
- A wheel is installed only when its SHA256 matches the sums file; a mismatch refuses.
- The daily check asks once a day. Auto-update never runs during a run, in CI, for long commands or when off.
- Auto-update and update-before-run never raise; update-before-run relaunches the same command after an install.
- An editable checkout only gets a hint.
- `uninstall --all` lists the steps on a dry run; the real run spawns the package removal after exit.

## Files

- `autopilot/upgrade.py`
- `scripts/bump.py`

## Tests that guard it

- `tests/test_upgrade.py::test_detect_editable_and_pip_and_uv`
- `tests/test_upgrade.py::test_a_dirty_checkout_is_not_pulled`
- `tests/test_upgrade.py::test_a_hash_mismatch_refuses`
- `tests/test_upgrade.py::test_check_never_installs`
- `tests/test_upgrade.py::test_daily_check_asks_once`
- `tests/test_upgrade.py::test_auto_update_starts_the_reinstall_once_and_says_so`
- `tests/test_upgrade.py::test_auto_update_never_runs_during_a_run_in_ci_for_long_commands_or_when_off`
- `tests/test_upgrade.py::test_auto_update_never_raises`
- `tests/test_upgrade.py::test_uninstall_all_dry_run_lists_the_steps_and_the_real_run_spawns_the_package_removal`
- `tests/test_upgrade.py::test_update_before_run_installs_then_relaunches_the_same_command`
- `tests/test_upgrade.py::test_update_before_run_never_raises`

## Changes

- 2026-10-14: first contract, written from the code and the tests (W52).
