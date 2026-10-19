# DeviceVault Production Operations Runbook

## Primary orchestrator

Status:

```bash
docker compose \
  --env-file /opt/devicevault/deploy/orchestrator-primary/compose.env \
  -f /opt/devicevault/deploy/orchestrator-primary/compose.yaml \
  ps
```

Logs:

```bash
docker compose \
  --env-file /opt/devicevault/deploy/orchestrator-primary/compose.env \
  -f /opt/devicevault/deploy/orchestrator-primary/compose.yaml \
  logs -f
```

Restart a service:

```bash
docker compose \
  --env-file /opt/devicevault/deploy/orchestrator-primary/compose.env \
  -f /opt/devicevault/deploy/orchestrator-primary/compose.yaml \
  restart django
```

## Backup orchestrator

Warm-standby status:

```bash
docker compose \
  --env-file /opt/devicevault/deploy/orchestrator-backup/compose.env \
  -f /opt/devicevault/deploy/orchestrator-backup/compose.yaml \
  --profile warm-standby \
  ps
```

Start promoted services:

```bash
docker compose \
  --env-file /opt/devicevault/deploy/orchestrator-backup/compose.env \
  -f /opt/devicevault/deploy/orchestrator-backup/compose.yaml \
  --profile promoted \
  up -d
```

## Collector workers

Scale out:

```bash
docker compose \
  --env-file /opt/devicevault/deploy/collector-worker/compose.env \
  -f /opt/devicevault/deploy/collector-worker/compose.yaml \
  up -d --scale collector-worker=4
```

## Storage workers

Scale out:

```bash
docker compose \
  --env-file /opt/devicevault/deploy/storage-worker/compose.env \
  -f /opt/devicevault/deploy/storage-worker/compose.yaml \
  up -d --scale storage-worker=4
```

## Rolling image updates

Re-run the role script with new image references, or edit the role's `compose.env` and then run:

```bash
docker compose --env-file /opt/devicevault/deploy/<role>/compose.env \
  -f /opt/devicevault/deploy/<role>/compose.yaml \
  up -d
```

## Failover

Run the promotion helper on the backup node:

```bash
sudo scripts/failover-to-node2.sh
```

After promotion:

1. move DNS / LB traffic to the backup node
2. update worker endpoints if they pointed at the old primary hostname
3. start any promoted profiles that should remain active
