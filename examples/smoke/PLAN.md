# Plan: wordstats (smoke test for Autopilot)

A tiny Python command-line tool that reports statistics about a text file. Standard library only, tested with
pytest. Small on purpose: the whole plan should finish in a handful of sessions.

## Phase 1: core counts
1. A package `wordstats` with a function `count(text) -> dict` that returns `lines`, `words` and `chars`.
   Acceptance: empty text gives all zeros; "a b\nc" gives 2 lines, 3 words, 5 chars; tests in `tests/`.
2. A command `python -m wordstats FILE` that prints the three counts, one per line, as `name: value`.
   Acceptance: a missing file prints an error to stderr and exits with code 1; a test covers both paths.

## Phase 2: top words
3. An option `--top N` that also prints the N most common words (case-insensitive, punctuation stripped), ties
   broken alphabetically. Acceptance: tests for ties, punctuation and N larger than the number of distinct words.
