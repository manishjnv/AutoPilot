# Sandboxed runner: agents get bypassPermissions only inside this container.
#   docker build -t autodev -f deploy/Dockerfile .
#   docker run -d --name autodev-myapp --env-file myapp.env -v /srv/projects/myapp:/work autodev
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates nodejs npm \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/autodev
RUN pip install --no-cache-dir /opt/autodev pytest ruff

RUN useradd -m -u 1000 autodev && git config --system --add safe.directory /work
USER autodev
ENV IS_SANDBOX=1
WORKDIR /work
CMD ["autodev", "run"]
