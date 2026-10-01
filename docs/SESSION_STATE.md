# Session state

## 2026-10-01: Review, research and roadmap; renamed to Autopilot; public repo

**Headline:** The whole codebase was reviewed and the findings verified, with research on best practice. The plan of record is [ROADMAP.md](ROADMAP.md), and the system is explained in [ARCHITECTURE.md](ARCHITECTURE.md). The project is renamed **Autopilot** (code rename pending, step R) and published at https://github.com/manishjnv/AutoPilot. **No code changed.**

**Commits**
- `c1acddb` docs: rename to Autopilot, add architecture guide and roadmap
- (this commit) docs: session handoff

**Tests:** not applicable, since there were no code changes. The suite cannot load on Windows yet (`fcntl`, ROADMAP P1). With a stand-in lock module, 11 of 13 tests pass; the 2 failures come from POSIX shell commands in the tests.

**Next action:** close VS Code, run `Rename-Item E:\code\AutoDev AutoPilot`, then in a new session in `E:\code\AutoPilot`, implement ROADMAP step **R** (rename the code), then **P1** (Windows first).

**Open questions (owner)**
1. Subscription terms: Pro/Max login may not be meant for unattended VPS runs. Check the Consumer Terms or use an API key before deploying (ROADMAP open question).
2. The first commit `1ead5af` shows a personal gmail address publicly. Rewrite it to the noreply address with a force-push?

### Decisions made this session
- **Name:** Autopilot. PyPI `dev-autopilot` (plain `autopilot` is taken). Command `autopilot`. The `.agent/` folder name stays.
- **Repo:** public. Unfixed security gaps are worded generally in public docs; the details are kept privately.
- **Owner's design rules** (now the ROADMAP principles):
  - features first;
  - one check per level (task gate, phase functional check, one completion audit);
  - when stuck: research, decide, and otherwise write `docs/NEEDS-YOU.md` and move on, never waiting.
- **Deploy:** no new deploy code. GitHub is the source of truth, and prod deploys from GitHub Actions; git sync is ROADMAP P4.
- **Verified facts:**
  - `claude -p` still uses the subscription's 5-hour and weekly limits; the June 15 credit change is paused.
  - Opus 5.5 costs $4/$20 per MTok, Sonnet 5.5 $2/$10, Haiku 4.5 $1/$5, so Opus is about 2x Sonnet.

### Work done
1. Read and reviewed all ~2,000 lines. Ran the tests: they cannot load on Windows; 11 of 13 pass with a stand-in lock module.
2. Verification: a Sonnet audit checked 16 code findings (14 confirmed, 2 partly), and a Sonnet fact-check covered the research claims (1 wrong benchmark figure dropped).
3. Research (3 parallel Sonnet runs):
   - usage limits and token fields;
   - model routing and prices;
   - lifecycle practice (RCA, ADR, research, functional tests, bug intake).
4. Wrote ROADMAP.md: objective, 13-row coverage matrix, R, P1, S, V, P2, P3, L1-L7, U1-U8, P4, P5, and the build order.
5. Updated the README, wrote ARCHITECTURE.md (Sonnet draft, with 5 overstated lines corrected), created the GitHub repo (private, then public at the owner's request) and pushed.
6. The folder rename failed because VS Code had the folder open; the owner will do it. Claude memory is already copied to the new path key.

### Routing telemetry
- Sonnet · review of current agent techniques · reworked: N (1 wrong statistic caught by the fact-check)
- Sonnet · audit of code findings · reworked: N
- Sonnet · research fact-check · reworked: N
- Sonnet · usage-limit research · reworked: N (Opus re-verified the policy claim: the change is paused)
- Sonnet · model-routing research · reworked: N
- Sonnet · lifecycle research · reworked: N
- Sonnet · ARCHITECTURE.md draft · reworked: Y (5 overstated git-safety lines fixed by Opus)

### Agent utilization
- Opus: ~375k tokens (~34%). Code review, finding verification, plan, roadmap, README, doc review, repo setup, handoff.
- Sonnet: ~712k tokens (~66%), 7 runs: 4 research, 1 code audit, 1 fact-check, 1 architecture draft.
- Haiku: n/a. There were no bulk-grep or verification sweeps; the codebase was small enough to read directly.
- codex:rescue: n/a. These were docs-only changes with no security or auth code.
