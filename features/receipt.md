# Feature contract: the signed receipt

## What it does

When a phase closes, `receipt.write` signs a receipt of the phase files (PROOF.md and the others) with a key kept in
the home folder. `ap verify` checks each receipt offline. The close also writes `proof.svg` (a card with counts, cost
and date) and `BADGE.md` (the README line that shows the card).

## Rules

- The key lives in the home folder, never in the project.
- A changed file gives `changed`, a missing file is reported, a wrong key gives a bad signature.
- A phase close writes a receipt that `ap verify` accepts.
- `proof.svg` holds only folder names and counts, never a path; a title with `<` or `&` still parses as XML.
- `BADGE.md` is one Markdown image line that points at `proof.svg`.

## Files

- `autopilot/receipt.py`
- `autopilot/card.py`
- `autopilot/docs.py`
- `autopilot/orchestrator.py`

## Tests that guard it

- `tests/test_receipt.py::test_write_then_check_is_ok`
- `tests/test_receipt.py::test_key_is_in_home_not_in_project`
- `tests/test_receipt.py::test_edit_proof_is_changed`
- `tests/test_receipt.py::test_missing_file_is_reported`
- `tests/test_receipt.py::test_wrong_key_is_bad_signature`
- `tests/test_receipt.py::test_a_phase_close_writes_a_receipt_that_ap_verify_accepts`
- `tests/test_docs.py::test_phase_close_writes_a_parseable_card_with_counts_cost_and_date`
- `tests/test_docs.py::test_a_title_with_angle_bracket_and_ampersand_still_parses`
- `tests/test_docs.py::test_badge_md_has_one_markdown_image_line_pointing_at_proof_svg`

## Changes

- 2026-10-14: first contract, written from the code and the tests (W52).
