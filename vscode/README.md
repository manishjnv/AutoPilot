# Autopilot for VS Code

A thin side panel for [Autopilot](../README.md). It has no chat participant.

## Commands

- `Autopilot: Start` sends `ap start` to a terminal named Autopilot.
- `Autopilot: Answer` sends `ap answer`.
- `Autopilot: Stop` sends `ap stop`.

The terminal is reused when it is open. The Autopilot view in the Explorer side bar shows the status page of the run. It reads the port from `.agent/status.port` (default 8765). When nothing answers, it says to run `ap` first.

## Build and publish

```
cd vscode
npm install
npx tsc --noEmit
npx vsce package
npx ovsx publish
```

Publishing needs a publisher token. This repository does not publish.
