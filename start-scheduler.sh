#!/bin/bash
# DeviceVault Backup Scheduler Startup Script
# Starts the scheduler daemon that processes configured backup schedules
# 
# Features:
# - Automatic cleanup of stale locks on startup
# - Graceful shutdown on SIGTERM/SIGINT
# - Lock status checking for debugging

set -e

cd "$(dirname "$0")"
source .venv/bin/activate
cd backend

export DEVICEVAULT_CONFIG="${DEVICEVAULT_CONFIG:-config/config.yaml}"

# Check for stale locks and clear if necessary
if [ "$1" = "--clear-lock" ]; then
    python -m backups.scheduler --clear-lock
    exit 0
fi

if [ "$1" = "--check-lock" ]; then
    python -m backups.scheduler --check-lock
    exit 0
fi

# Start scheduler daemon
# Scheduler will automatically clean up lock on exit via signal handlers
python -m backups.scheduler
