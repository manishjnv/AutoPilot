#!/usr/bin/env bash
# One-command VPS setup for one project (M5). Run as root from an Autopilot checkout:
#   sudo deploy/install.sh <name> <git-url-of-your-project>
# It touches only Autopilot's own things, so other apps on a shared server are left alone:
#   the `autopilot` docker image, the `autopilot` user, /srv/autopilot/<name>, /etc/autopilot/<name>.env and
#   the autopilot@.service unit. It never starts the service: log in to Claude first (printed at the end).
set -euo pipefail

name="${1:-}"; repo="${2:-}"
if [[ -z "$name" || -z "$repo" || ! "$name" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "usage: sudo $0 <name: a-z 0-9 _ -> <git-url>" >&2; exit 2
fi
[[ $EUID -eq 0 ]] || { echo "run as root (sudo)" >&2; exit 2; }
command -v docker >/dev/null || { echo "docker is not installed" >&2; exit 1; }
here="$(cd "$(dirname "$0")/.." && pwd)"

echo "== image"
docker build -t autopilot -f "$here/deploy/Dockerfile" "$here"

echo "== user"
id autopilot >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin autopilot
usermod -aG docker autopilot

echo "== project checkout"
dir="/srv/autopilot/$name"
if [[ -d "$dir/.git" ]]; then
  echo "keep $dir (already cloned)"
else
  mkdir -p /srv/autopilot
  git clone "$repo" "$dir"
fi
chown -R 1000:1000 "$dir"   # uid of the container user (deploy/Dockerfile)

echo "== secrets file"
env="/etc/autopilot/$name.env"
mkdir -p /etc/autopilot && chmod 700 /etc/autopilot
if [[ -f "$env" ]]; then
  echo "keep $env"
else
  install -m 600 /dev/null "$env"
  cat > "$env" <<'EOF'
# Autopilot secrets for this project (mode 600). Uncomment what you use.
# ANTHROPIC_API_KEY=            # only with usage.billing: api; a subscription login needs nothing here
# AUTOPILOT_TG_TOKEN=           # Telegram bot token (notifications, chat commands)
# AUTOPILOT_TG_CHAT=            # your Telegram user id
# AUTOPILOT_NTFY_TOPIC=
# GH_TOKEN=                     # for git push / gh (intake, PR mode); use a token scoped to this repo
EOF
fi

echo "== systemd unit"
install -m 644 "$here/deploy/autopilot@.service" /etc/systemd/system/autopilot@.service
systemctl daemon-reload

cat <<EOF

Done. Next (the project must already contain .agent/: run \`autopilot quickstart\` on your PC and push):
  1. Log in to Claude once (subscription):
       docker run -it --rm -v autopilot-claude-$name:/home/autopilot/.claude autopilot claude
       then type /login and exit
  2. Fill in $env (notifications, GH_TOKEN for pushing)
  3. Check:  docker run --rm --env-file $env -v $dir:/work -v autopilot-claude-$name:/home/autopilot/.claude autopilot autopilot doctor
  4. Start:  systemctl enable --now autopilot@$name     (logs: journalctl -u autopilot@$name -f)
EOF
