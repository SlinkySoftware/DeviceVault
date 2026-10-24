#!/bin/sh
# DeviceVault push receiver entrypoint.
#
# Required: DV_BROKER_URL, DV_REDIS_URL. The receiver registers with the
# orchestrator and, once approved as a receiver, listens on whatever its
# assignment enables (SCP/SFTP, TFTP).
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec python -m devicevault_receiver
