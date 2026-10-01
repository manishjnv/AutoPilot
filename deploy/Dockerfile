# Sandboxed runner: agents get bypassPermissions only inside this container.
# Build, then run it through the systemd unit (deploy/autopilot@.service):
#   docker build -t autopilot -f deploy/Dockerfile .
FROM python:3.12-slim

# Pinned Claude Code version: bump deliberately, after testing.
ARG CLAUDE_CODE_VERSION=2.1.286

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates nodejs npm \
    && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/autopilot
RUN pip install --no-cache-dir /opt/autopilot pytest ruff

RUN useradd -m -u 1000 autopilot && git config --system --add safe.directory /work
USER autopilot
# the container is the sandbox
ENV IS_SANDBOX=1
WORKDIR /work
VOLUME /work
CMD ["autopilot", "run"]
