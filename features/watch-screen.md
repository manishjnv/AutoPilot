# Feature contract: the watch screen

## What it does

`ap watch` follows a run live. A window of at least 100x24 cells (`MIN_COLS`, `MIN_ROWS` in `dash_term.py`) shows the
dashboard; a smaller window shows the scrolling view with a status panel at the bottom. `dashboard.dashboard_data`
builds one plain dict from the state files; `dash_term.frame` draws it in the terminal and `dash_web` draws the same
dict as one self-contained HTML page (the status page). Ctrl+C stops the watch, not the run.

## Rules

- Panels: the left panel (Project, Branch, Started, Elapsed; `! Questions for you`; Now; Next; Size; Last commit;
  Agent; Phases), the middle column (the tasks panel on top, about 45 percent of the height, the live output below),
  the right column (Progress, AI, Files, Issues) and one status bar on the last line. The AI box (W62) holds three
  groups: LIMITS (one row per source: name, a state word from `usage.STATES`, the bar or the dollar figure, the
  reset), NEXT (one line, mode first) and SPEND (tokens, per-model text, cost, rate). The one coloured bar is the
  planner's limit; every other bar is dim; a credit is a dollar figure, never a bar; at a small height the box
  collapses in the order per-model spend, OFF/DISABLED/MANUAL rows, cli rows, spend, and keeps the ACTIVE row, the
  limiting bar and NEXT. Without source rows the old Usage box draws.
- The Now card (W18b, `dash_card.py`; data from `dash_live.task_card`, `end_card`, `ended_card`): full width at the top
  under the title bar from 120 columns (160 and wider: two inner lines, title in the border; 120 to 159: four lines,
  title on the first line); under 120 it is a group of the left column (a rule line, then six lines). The border row
  holds `Now`, the stable facts centred (`Task N of TOTAL`, title cut with `...`, `model · try N/M`) and at the right
  end `data Ns` plus the spinner; it never wraps into the first inner row. Lines: time (the work time like the Tasks
  table, ticking on the window clock, `(first start HH:MM)` when the wall clock is over 2x the work), the ETA range
  (middle half of past tasks with the same model and risk, basis named), `why:` on a retry; the segmented bar
  `read · write · tests · gate · merge` (end phase: `read · tests · report`), widths from median step times else equal,
  the running segment fills by its time against its ETA and never completes (the percent stops at 99, the last cell stays
  empty), one brighter cell slides across the fill each second (ASCII `[==>  ]`); `So far:` the open diff, tokens, cost;
  the last tool or the gate with its running time. The `data Ns old` text lives only at the card's right end. The old
  Now group stays only for data that has no card.
- The end: the card shows `Run ended ── WORD` with the counts and what is still pending, each with its command or
  person (owner tasks, blocked tasks, questions, an audit with no report, Not proven items, deploy, merge-back, push,
  release). The window title is `✓ VERIFIED hh:mm`, `⏸ BLOCKED`, `✗ FAILED` (STOPPED and BUDGET_STOP are `⏸`) and the
  window stays until Enter. The progress total counts the end steps (audit, functional check, docs): 100 only when the
  run ended; `audit added N tasks` shows when the audit adds tasks.
- The running task row has a filled background and bold text (`active`, the one accent); the spinner starts that row.
  `Build` (version) drops before `Phases` in a short panel; the version is one line cut with `...`.
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
- `autopilot/dash_card.py`

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
- `tests/test_now_card.py::test_the_card_has_one_line_count_per_width_step`
- `tests/test_now_card.py::test_the_bar_never_reaches_100_before_the_merge`
- `tests/test_now_card.py::test_all_tasks_done_is_not_100_percent_while_the_audit_runs`
- `tests/test_now_card.py::test_the_end_screen_names_the_outcome_and_lists_what_is_pending`
- `tests/test_now_card.py::test_the_card_work_time_is_the_table_time_and_names_the_first_start`
- `tests/test_now_card.py::test_the_build_group_drops_before_the_phases`

## Changes

- 2026-10-15: W62: the AI box replaces the Usage box when source rows exist (`dash_term.ai_box`, the same groups on
  the status page, `ap status` prints the ACTIVE row and NEXT); new `_USES` rows for its colours. Rules kept. New
  tests: `tests/test_w62.py`.
- 2026-10-14: W48a screen: `ap watch` has one input row above the status bar when stdin is a terminal (Enter sends
  through `inbox.submit` in a thread, Esc clears; keys are read without blocking, redraw at once). One line above the
  Now card shows `You: <text>  Reply: <reply>` for 60 s after the last inbox line (the card has no free inner line, so
  the line is above it, not inside it); the status page shows the same line, read-only. W18b fixes: an ended or stopped
  run has no active row and no spinner mark before a row number; the ended bar shows `✓ VERIFIED hh:mm` (outcome symbol,
  word, colour), never a red `✗ stopped` for a complete plan. Rules kept. New files `autopilot/watch_input.py`,
  `tests/test_watch_input.py`.
- 2026-10-14: W18b: the Now card, the progress total with end steps, the end screen, the active row. Replaced the rule
  "Now card: Task time with `data Ns old`" (the time is now the work time, the age is at the card's right end) and the
  `COLOUR_MEANING` map gained `active`. New files `autopilot/dash_card.py`, `tests/test_now_card.py`.
- 2026-10-14: W18a: liveness (gate journal lines, runner heartbeat, ticking clock, `Waiting for:`, error age,
  version, run number, size read on every tick, NO_COLOR panels). Kept every rule above; the Task time `data Ns old`
  now counts from the data file, not from the heartbeat. New tests: `tests/test_watch_liveness.py`.
- 2026-10-14: first contract, written from the code and the tests (W36).
