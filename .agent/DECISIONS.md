# Decision Log

Append-only. One line per decision: `- [date] [task] decision — reason`.
Every session reads the latest entries so later work stays consistent with earlier choices.

- [2026-10-11] [P01-T01] Task.status is '' when the key is absent; sync_plan applies 'done' only to new or pending rows
- [2026-10-11] [P01-T02] discovery_pack section caps are 8000 (git), 24000 (documents), 12000 (stack), 8000 (tests), 60000 total (PACK_CAP) — keeps the pack under ~60k; the truncation marker is appended after the cut
- [2026-10-11] [P01-T03] untracked_files(root) in cli.py uses `git status --porcelain -uall`; the new-file warning is skipped outside a git repository — it is a hint only, nothing is deleted
- [2026-10-11] [P02-T01] missing_deps checks: node_modules/ (npm/pnpm/yarn); .venv/ or venv/ with pyvenv.cfg (uv, poetry; Poetry venv outside the project gives a false WARN); requirements*: project venv (.venv, venv, env) or an active venv; go.sum: non-empty GOMODCACHE (or GOPATH/pkg/mod) or vendor/; Cargo.lock: target/ or non-empty CARGO_HOME/registry. Yarn Berry (`__metadata:` in yarn.lock) gets `--immutable`. doctor row "dependencies" is WARN only
- [2026-10-11] [P02-T01] missing_deps presence checks: node_modules/ for npm/pnpm/yarn; .venv/ or venv/ for uv/poetry; project venv or active venv for requirements*; non-empty Go module cache or vendor/ for go.sum; target/ or cargo registry for Cargo.lock. Yarn Berry gets --immutable. Doctor row is WARN only.
- [2026-10-11] [P02-T02] install_deps(cfg) in cli.py runs after the agent CLI check; standard commands are de-duplicated, run one by one, and written to commands.setup as a JSON-style list by remember_setup (regex text edit, comments kept) — same approach as cmd_init
- [2026-10-11] [P02-T02] When commands.setup is set it is run as is and never rewritten
- [2026-10-11] [P03-T01] ADR: A: _MODEL_OPT per preset + {prompt_file} placeholder for aider; kiro on stdin only; cursor with _ASK + stdin → docs/adr/0001-presets-for-kiro-cursor-and-aider-a-model-option-f.md
