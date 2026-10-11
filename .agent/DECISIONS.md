# Decision Log

Append-only. One line per decision: `- [date] [task] decision — reason`.
Every session reads the latest entries so later work stays consistent with earlier choices.

- [2026-10-11] [P01-T01] Task.status is '' when the key is absent; sync_plan applies 'done' only to new or pending rows
- [2026-10-11] [P01-T02] discovery_pack section caps are 8000 (git), 24000 (documents), 12000 (stack), 8000 (tests), 60000 total (PACK_CAP) — keeps the pack under ~60k; the truncation marker is appended after the cut
- [2026-10-11] [P01-T03] untracked_files(root) in cli.py uses `git status --porcelain -uall`; the new-file warning is skipped outside a git repository — it is a hint only, nothing is deleted
