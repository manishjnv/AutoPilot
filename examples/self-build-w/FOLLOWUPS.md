# Follow-ups

Reported by sessions; consumed by the auditor and replanner.

- [P11-T01] P11-T02/T03: switch claude_cli.py, doctor.py and gate.py from sandbox.enabled to config.sandbox_mode/allowlist_on
- [P11-T01] REFERENCE.md and CHANGELOG entry for sandbox.mode once the docker mode itself ships (P11-T02/T03)
- [P11-T01] Run wsltest_self.sh on WSL to confirm the full suite
- [P11-T02] tests/test_tour.py::test_make_tour_regenerates_the_same_file fails on HEAD without this change (Windows and WSL)
- [P11-T02] tests/test_sync.py::test_pr_mode_merges_on_github_when_ci_is_green and test_red_ci_closes_the_pr_and_retries_with_the_ci_output fail on HEAD without this change: the gh call sequence ends with 'pr ready' where 'pr merge' is expected (W6 draft PR flow)
- [P11-T02] tests/test_opening.py README word count fails on HEAD: README.md has 1252 words against a limit of 1200
- [P11-T02] Claude Code's nested bubblewrap sandbox (docker mode plus sandbox.enabled) may fail under Docker's default seccomp profile
- [P11-T02] The doctor row for docker and sandbox.image (P11-T03). Document that macOS keeps the login in the Keychain, so docker mode there needs CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY
- [P11-T02] An absolute mcp_config path outside the worktree is not visible inside the container
- [P12-T01] Pre-existing failures on HEAD (not caused by this task): tests/test_sync.py::test_pr_mode_merges_on_github_when_ci_is_green and ::test_red_ci_closes_the_pr_and_retries_with_the_ci_output (pr mode now calls 'pr ready', which the tests do not expect), and tests/test_tour.py::test_make_tour_regenerates_the_same_file (CRLF checkout of the tour events file)
- [P12-T01] openai_compat has no live token progress (on_tokens/on_context unused) and no 429 rate-limit handling (a 429 is a plain 4xx failure)
- [P12-T01] REFERENCE.md entry for agent.base_url / model_map / api_key_env and doctor/preflight rows for openai_compat are later P12 tasks
- [P12-T02] WSL run stopped at the first two failures (-x), so the rest of the suite did not run on WSL in this session. The Windows run of the openai_compat tests passed.
- [P12-T02] Pre-existing on HEAD: tests/test_tour.py::test_make_tour_regenerates_the_same_file (CRLF checkout of the tour events file)
- [P12-T02] Pre-existing on HEAD: tests/test_sync.py::test_pr_mode_merges_on_github_when_ci_is_green (pr mode now calls 'pr ready')
- [P12-T02] The endpoint row is only added in checks() when project.yaml names the backend (runner_chosen branch comes first); a project with agent.backend unset never sees it
- [P13-T01a] WSL suite stopped at the first failure (-x): tests/test_opening.py::test_readme_states_the_position_and_the_safety_block fails with 1203 words against a 1200-word limit on README.md. Trim README or raise the limit in a README task.
- [P13-T01a] The rest of the WSL suite after that failure did not run in this session.
- [P13-T01a] The port file is not removed when the run ends, so a stale port can remain; the extension must check the page answers before it uses the port.
- [P13-T01] vscode/package-lock.json is not committed; a later task may decide whether to keep one for vsce builds.
- [P13-T01] No icon, repository field or CI job for the extension yet; add them before the first publish.
- [P14-T01] The WSL suite was not run in this session.
- [P14-T02] examples/tour/events.jsonl and autopilot/templates/tour/events.jsonl are CRLF in the working copy but LF in the index; run git add --renormalize examples/tour autopilot/templates/tour (or re-checkout) so test_make_tour_regenerates_the_same_file passes on this machine
- [P14-T02] tests/test_steps.py::test_a_run_that_dies_at_the_runner_step_resumes_there_and_skips_the_rest fails on Windows: the second setup run does not print 'done autopilot:' / 'done python:'; not caused by this change
- [P14-T02] The WSL suite (docs/wsltest_self.sh) was not run
- [P14-T03] tests/test_opening.py::test_readme_states_the_position_and_the_safety_block fails on the current README: 1334 words against a 1200 limit. README was not changed in this task; the WSL run stopped at this failure (-x), so the rest of the suite was not run under WSL
- [P14-T03] The README has no plugin hook or Routine link; add them when the README is next trimmed
