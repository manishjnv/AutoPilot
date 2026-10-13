# Feature contract: the watch screen

## What it does

`ap watch` follows a run live. A window of at least 100x24 cells (`MIN_COLS`, `MIN_ROWS` in `dash_term.py`) shows the
dashboard; a smaller window shows the scrolling view with a status panel at the bottom. `dashboard.dashboard_data`
builds one plain dict from the state files; `dash_term.frame` draws it in the terminal and `dash_web` draws the same
dict as one self-contained HTML page (the status page). Ctrl+C stops the watch, not the run.

## Rules

- Panels: the left panel (Project, Branch, Started, Elapsed; `! Questions for you`; Now; Next; Size; Last commit;
  Agent; Phases), the middle column (the tasks panel on top, about 45 percent of the height, the live output below),
  the right column (Progress, Usage, Files, Issues) and one status bar on the last line.
- The Now card: its title line carries the running indicator; the one bold headline of the screen is
  `Task N of TOTAL: title`; then `Try N of M` (yellow from try 2, and on the last try), `Task time` ticking from the
  local clock with `data Ns old` behind it, and the model in blue.
- One colour, one meaning (`COLOUR_MEANING`): green done or ok, cyan running now, yellow warning, red blocked or failed,
  magenta cost and usage, blue model name, dim label, border, pending or zero, bright white a value the eye lands on,
  bold the one headline. A plain fact stays white. Every (colour, use) pair is listed in `_USES`; REFERENCE.md
  "Dashboard colours" is the same table.
- The stale rule: the running indicator turns only while the data file changes. After 30 s with no change it freezes
  and shows `no change 45s` (minutes after 60 s) in yellow, and the data age note says `data Ns old stale`. A run that
  ended shows `stopped HH:MM` in red. The project block says `No change for N min.` from 5 minutes (yellow from 10,
  red from 30). The browser page shows the same ring, paused when stale.
- No value appears in two panels; nothing wraps or overflows the window; every dynamic value on the web page goes
  through `html.escape`, and terminal text goes through `clean` (no control or wide characters).

## Files

- `autopilot/dash_term.py`
- `autopilot/dash_web.py`
- `autopilot/dashboard.py`

## Tests that guard it

- `tests/test_dash_term.py::test_exact_size`
- `tests/test_dash_term.py::test_unsafe_text`
- `tests/test_dash_term.py::test_now_and_try_colors`
- `tests/test_dash_term.py::test_data_age_and_stale`
- `tests/test_dash_term.py::test_stopped_run_shows_the_time_on_every_panel`
- `tests/test_dash_term.py::test_no_value_appears_in_two_panels`
- `tests/test_dash_term.py::test_every_colour_has_one_meaning_and_only_the_headline_is_bold`
- `tests/test_dash_term.py::test_colour_pairs_each_colour_has_one_meaning`
- `tests/test_dash_term.py::test_rendered_values_carry_the_colour_of_their_meaning`
- `tests/test_dash_term.py::test_spinner_turns_only_while_the_file_changes`
- `tests/test_dash_term.py::test_small_window_keeps_status_and_needs_you`
- `tests/test_dash_web.py::test_panels_and_bar`
- `tests/test_dash_web.py::test_escape_everywhere`
- `tests/test_dash_web.py::test_spinner_element_and_paused_class`
- `tests/test_dash_web.py::test_colour_map_classes`
- `tests/test_dashboard.py::test_data_is_plain_and_has_every_part`
- `tests/test_dashboard.py::test_a_frozen_state_file_shows_stale_within_30_seconds`

## Changes

- 2026-10-14: first contract, written from the code and the tests (W36).
