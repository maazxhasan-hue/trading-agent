#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/maazxhasan-hue/trading-agent.git}"
APP_DIR="${APP_DIR:-/opt/trading-agent}"

sudo apt-get update
sudo apt-get install -y ca-certificates curl git

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER" || true
fi

sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created $APP_DIR/.env from .env.example."
fi

docker compose build
docker compose up -d
docker compose ps
