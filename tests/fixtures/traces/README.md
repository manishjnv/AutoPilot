# Failure traces

One scrubbed `unknown.jsonl` line per real failure goes here, one file per release (`YYYY-MM-DD.jsonl`).
Each line has `text` (already scrubbed, no path, no secret) and `cause` (what `signals.cause_of` must return).
`tests/test_w51.py` loads every file and checks that each line still gives the same cause.
When a release turns an unknown wording into a catalogue line, change its `cause` here in the same commit.
