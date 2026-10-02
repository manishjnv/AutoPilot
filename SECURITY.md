# Security policy

Autopilot runs a coding agent that has shell access. A fault in its guards can damage a computer or leak a secret.

## What to report

- A way for a session to get past the [trust boundary](ARCHITECTURE.md#10-trust-boundary). Examples are a commit, a
  push, a change to git hooks, or a read of an environment variable that is not on the allowlist.
- A way for a session to change the files that only Autopilot writes, for example `.agent/plan.yaml`.
- A secret that Autopilot writes to git, to a log, or to the status page.
- A way to read the status page from a different computer without the token.

## How to report

> [!WARNING]
> Do not open a public issue for a security fault.

1. Open the [private report form](https://github.com/manishjnv/AutoPilot/security/advisories/new).
2. Give the version or the commit, the steps to show the fault, and the result.

## What to expect

- This project has one maintainer. You get a first reply in approximately one week.
- Fixes go to the `main` branch. Older versions get no fixes.
- The advisory names you, unless you ask for no name.
- There is no payment for reports.
