#!/usr/bin/env bash
#
# DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
# Copyright (C) 2026, Slinky Software
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

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
