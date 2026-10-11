# Decision Log

Append-only. One line per decision: `- [date] [task] decision — reason`.
Every session reads the latest entries so later work stays consistent with earlier choices.

- [2026-10-11] [P01-T01] Task.status is '' when the key is absent; sync_plan applies 'done' only to new or pending rows
