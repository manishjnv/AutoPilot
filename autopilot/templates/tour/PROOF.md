# Proof: tour of a recorded run

- Outcome: VERIFIED
- Source: `examples/self-build` (9 phases, 19 tasks, 1 feature check), replayed from `events.jsonl`.
- How: `python scripts/make_tour.py` builds the recording from the real task history. Nothing runs live.

## Not proven
- This is a recording. The replay runs no tests and calls no agent.
- Only one feature (P06-F01) has a recorded functional check; the other phases were checked by tests only.
- Token counts are not recorded: usage has the cost of each task only.
