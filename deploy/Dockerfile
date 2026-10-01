# Sandboxed runner: agents get bypassPermissions only inside this container.
#   docker build -t autopilot -f deploy/Dockerfile .
#   docker run -d --name autopilot-myapp --env-file myapp.env -v /srv/projects/myapp:/work autopilot
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates nodejs npm \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/autopilot
RUN pip install --no-cache-dir /opt/autopilot pytest ruff

RUN useradd -m -u 1000 autopilot && git config --system --add safe.directory /work
USER autopilot
ENV IS_SANDBOX=1
WORKDIR /work
CMD ["autopilot", "run"]
