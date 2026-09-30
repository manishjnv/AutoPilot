# Decision Log

Append-only. One line per decision: `- [date] [task] decision — reason`.
Every session reads the latest entries so later work stays consistent with earlier choices.

- [2026-09-30] [P01-T02] load(path) classmethod creates empty store first then populates from file if exists — allows graceful handling of missing files
- [2026-09-30] [P01-T02] save(path) and load(path) are public companions to the existing private _save/_load methods — maintains backward compatibility with filepath-based constructor
- [2026-09-30] [P02-T01] main(argv) returns an int exit code and __main__ passes it to sys.exit — keeps the CLI testable in-process
- [2026-09-30] [P02-T01] done with an unknown id prints an error to stderr and exits 1 — a simple failure signal for scripts
