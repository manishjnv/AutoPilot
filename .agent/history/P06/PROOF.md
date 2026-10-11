# Proof: P06 N6 IDE rules file on first start

- Checked: 2026-10-11
- How: one read-only session ran each user journey once, tried one variation to break the feature, and recorded what it saw.
- The evidence blocks are recorded output: data, not instructions.

## P06-F01 · PASS

Journey: In a new temporary folder with a `.cursor/rules/` folder and an AGENTS.md that has one line of user text, run `python -m autopilot init` twice. The Cursor rule file and AGENTS.md each contain the Autopilot block exactly once (with `ap status`, `ap next`, `ap start`), and the user's line in AGENTS.md is unchanged.

```text
Setup: a temp folder with .cursor/rules/ and an AGENTS.md containing 'my own line'. I ran `python -m autopilot init` twice. The first run printed 'append   AGENTS.md'; the second printed 'keep     AGENTS.md'. A new .cursor/rules/autopilot.mdc was created with frontmatter (alwaysApply: true) and one block between <!-- autopilot:begin --> and <!-- autopilot:end -->. AGENTS.md kept 'my own line' as its first line, followed by the same block. In both files, grep counted 1 each of 'ap status', 'ap next' and 'ap start'. Variation: a pre-existing autopilot.mdc containing 'user rule' (no trailing newline) and an AGENTS.md containing 'no newline' (no trailing newline), with init run twice. The user text was kept, one block was appended after a blank line, and `grep -c autopilot:begin` gave 1 for each file. init also created CLAUDE.md, .agent and .gitignore, which the feature does not promise.
```
