#!/usr/bin/env bash
set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get not found; this script is intended for Debian-based systems." >&2
  exit 1
fi

echo "Updating apt and installing OS packages (may require sudo)..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    git python3 python3-pip python3-venv libpq-dev gcc ca-certificates \
    default-libmysqlclient-dev libpq-dev pkg-config python3-dev \
    libldap2-dev libsasl2-dev libsasl2-2

sudo apt-get clean
sudo rm -rf /var/lib/apt/lists/*

echo "OS dependencies installed."
