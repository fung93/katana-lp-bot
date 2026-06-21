#!/usr/bin/env bash
# One-shot setup for an Ubuntu VM (Oracle Always-Free, or any Ubuntu host).
# Runs the whole bot (commands + the 60s monitor loop) as a 24/7 systemd service.
#
# Usage, from the repo root after cloning:
#   git clone https://github.com/fung93/katana-lp-bot.git
#   cd katana-lp-bot && bash deploy/setup.sh
# First run: installs Python 3.12 + deps and creates .env (then you edit it).
# Second run: installs and starts the service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(whoami)"
cd "$REPO_DIR"

echo ">>> Installing Python 3.12 + git ..."
sudo apt-get update -y
sudo apt-get install -y software-properties-common git
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update -y
sudo apt-get install -y python3.12 python3.12-venv

echo ">>> Creating venv + installing deps ..."
[ -d .venv ] || python3.12 -m venv .venv
./.venv/bin/pip install --upgrade pip -q
./.venv/bin/pip install -r requirements.txt -q

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo ">>> Created .env from the template."
  echo ">>> Edit it with your secrets:   nano $REPO_DIR/.env"
  echo ">>> Then re-run:                  bash deploy/setup.sh"
  exit 0
fi

echo ">>> Installing systemd service (24/7, auto-restart) ..."
sudo tee /etc/systemd/system/katana-lp-bot.service >/dev/null <<UNIT
[Unit]
Description=Katana LP signal bot (commands + monitor)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO_DIR
Environment=INPROCESS_MONITOR=1
ExecStart=$REPO_DIR/.venv/bin/python -m app.bot
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now katana-lp-bot
sleep 2
echo
echo ">>> Done. The bot is running 24/7 with the 60s monitor loop."
echo ">>> Status:  sudo systemctl status katana-lp-bot --no-pager"
echo ">>> Logs:    journalctl -u katana-lp-bot -f"
