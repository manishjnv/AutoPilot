# Feature contract: the outcome word

## What it does

At the end of a run Autopilot shows one word: VERIFIED, BLOCKED, STOPPED, BUDGET_STOP, STALLED or FAILED.
`orchestrator.outcome_word` picks it in Python. PROOF.md of each phase ends its header with a `## Not proven` list of
the open items, so a green word never hides a gap.

## Rules

- A `Stop` names its word at the raise site: fatal gives FAILED, a limit the owner set gives BUDGET_STOP, a stop by
  hand gives STOPPED.
- A fatal or crashed outcome gives FAILED; a parked task or open decision gives BLOCKED.
- Only a complete plan gives VERIFIED; any other end gives STALLED.
- A new run clears the old word. `ap status` prints the word only when it is set.
- The dashboard data and the terminal bottom bar carry the same word; a complete plan never shows an error mark.
- `## Not proven` lists each criterion without a test and each task without a check command. When nothing is open it
  holds one sentence.

## Files

- `autopilot/orchestrator.py`
- `autopilot/docs.py`
- `autopilot/dash_term.py`

## Tests that guard it

- `tests/test_outcome.py::test_complete_plan_is_verified`
- `tests/test_outcome.py::test_parked_task_is_blocked`
- `tests/test_outcome.py::test_budget_cap_is_budget_stop`
- `tests/test_outcome.py::test_stop_file_is_stopped`
- `tests/test_outcome.py::test_outcome_word_rules`
- `tests/test_outcome.py::test_new_run_clears_the_word_and_title_without_word`
- `tests/test_outcome.py::test_status_prints_outcome_only_when_set`
- `tests/test_outcome.py::test_dashboard_data_and_bar_carry_the_word`
- `tests/test_now_card.py::test_the_ended_bar_shows_the_outcome_word_and_the_time_never_an_x_for_a_complete_plan`
- `tests/test_docs.py::test_a_criterion_without_a_test_is_listed_with_its_task_id`
- `tests/test_docs.py::test_a_fully_tested_phase_prints_the_one_sentence`
- `tests/test_tour.py::test_tour_proof_has_outcome_and_not_proven`

## Changes

- 2026-10-14: first contract, written from the code and the tests (W52).
