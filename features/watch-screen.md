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
- Liveness (W18a): the spinner turns while the newest of the data file and the runner heartbeat (`heartbeat_at` in
  `run.json`, written from the CLI stream at most every 10 s, and during a gate the `beat_at` of the run process)
  moves. It pauses (yellow) after 30 s without either. A gate or the start check writes its line to the journal
  (`gate: tests (<command>)`, `gate: merge`, `start check: tests on main (<command>)`) and the window shows that text
  in place of `no change`. A dead process stays red (W37 `run_alive`).
- The Elapsed and Task time values tick from the window clock each second. The Now panel has a `Waiting for:` line:
  the last tool and its running time, or the gate and its time. The Project panel shows the version
  (`Autopilot <version> (<sha>) from <folder>`) and `Run N (since HH:MM) · total ... since HH:MM`. The error line and
  the Issues text carry the error age (`3d ago`) and turn dim after the next successful session.
- The panel screen needs a terminal (`isatty`, `enable_vt`) and nothing else. With `NO_COLOR` it draws with bold and
  dim only. The window size is read on every tick: a small window shows the scroll view and the line
  `Widen the window for the panels.`, and the panels start on the first tick that fits.
- No value appears in two panels; nothing wraps or overflows the window; every dynamic value on the web page goes
  through `html.escape`, and terminal text goes through `clean` (no control or wide characters).

## Files

- `autopilot/dash_term.py`
- `autopilot/dash_web.py`
- `autopilot/dashboard.py`
- `autopilot/dash_live.py`

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
- `tests/test_watch_liveness.py::test_run_file_holds_the_gate_line_while_a_slow_test_runs`
- `tests/test_watch_liveness.py::test_a_fake_runner_streaming_every_2_s_keeps_heartbeat_at_moving`
- `tests/test_watch_liveness.py::test_a_heartbeat_40_s_old_shows_the_pause_and_a_fresh_one_keeps_it_turning`
- `tests/test_watch_liveness.py::test_watch_with_no_color_draws_the_panels_in_bold_and_dim_only`
- `tests/test_watch_liveness.py::test_a_small_window_that_grows_gets_the_panels_on_the_next_tick`

## Changes

- 2026-10-14: W18a: liveness (gate journal lines, runner heartbeat, ticking clock, `Waiting for:`, error age,
  version, run number, size read on every tick, NO_COLOR panels). Kept every rule above; the Task time `data Ns old`
  now counts from the data file, not from the heartbeat. New tests: `tests/test_watch_liveness.py`.
- 2026-10-14: first contract, written from the code and the tests (W36).
