# DeviceVault Production Deployment Architecture

## Design goals

This production layout is designed around the decisions captured during the refactor:

- **images preferred** for production deployment
- **optional source checkout** only when deployment assets must be cloned locally
- **single checkout only** if a clone is needed; no nested `/opt/devicevault/repo`
- **`.env` authoritative for infrastructure and secrets**
- **`config.yaml` authoritative for application/domain settings**
- **four reusable production compose files**
- **stable deploy asset directories** in `/opt/devicevault/deploy/<role>/`

## Production roles

### 1. Orchestrator Primary

Runs the central control plane:

- PostgreSQL
- Redis
- RabbitMQ
- Django API
- Nginx / frontend
- backup result consumer
- storage result consumer
- a small local collector worker
- a small local storage worker

Compose file:

- [docker-compose.prod-orchestrator-primary.yaml](../docker-build/docker-compose.prod-orchestrator-primary.yaml)

### 2. Orchestrator Backup

Runs a warm-standby layout:

- PostgreSQL replica bootstrap
- Redis replica
- RabbitMQ standby
- Django + Nginx via the `warm-standby` profile
- result consumers and small local workers via the `promoted` profile

Compose file:

- [docker-compose.prod-orchestrator-backup.yaml](../docker-build/docker-compose.prod-orchestrator-backup.yaml)

### 3. Collector Worker

Generic worker nodes that process collection queues only.

Compose file:

- [docker-compose.prod-collector-worker.yaml](../docker-build/docker-compose.prod-collector-worker.yaml)

### 4. Storage Worker

Generic worker nodes that process storage queues only and mount a storage path.

Compose file:

- [docker-compose.prod-storage-worker.yaml](../docker-build/docker-compose.prod-storage-worker.yaml)

## Build process

Build production images with [build-prod-images.sh](../scripts/build-prod-images.sh):

```bash
scripts/build-prod-images.sh \
  --image-prefix registry.example.com/devicevault \
  --image-tag 2026.10.19
```

This builds:

- an application image from [Dockerfile.app](../docker-build/Dockerfile.app)
- an nginx/frontend image from [Dockerfile.nginx](../docker-build/Dockerfile.nginx)

The application image is reused for:

- Django
- result consumers
- collector workers
- storage workers

## Deployment process

Each setup script installs:

- `/etc/devicevault/<role>/.env`
- `/etc/devicevault/<role>/config.yaml`
- role-specific support files such as nginx or PostgreSQL bootstrap files
- `/opt/devicevault/deploy/<role>/compose.yaml`
- `/opt/devicevault/deploy/<role>/compose.env`

### Example: primary orchestrator

```bash
sudo scripts/setup-prod-orchestrator-primary.sh \
  --app-image registry.example.com/devicevault/app:2026.10.19 \
  --nginx-image registry.example.com/devicevault/nginx:2026.10.19
```

### Example: backup orchestrator

```bash
sudo scripts/setup-prod-orchestrator-backup.sh \
  --primary-host node1.internal \
  --app-image registry.example.com/devicevault/app:2026.10.19 \
  --nginx-image registry.example.com/devicevault/nginx:2026.10.19
```

### Example: collector worker

```bash
sudo scripts/setup-prod-collector-worker.sh \
  --orchestrator-host node1.internal \
  --collector-queues collector.group.group1 \
  --replicas 2 \
  --app-image registry.example.com/devicevault/app:2026.10.19
```

### Example: storage worker

```bash
sudo scripts/setup-prod-storage-worker.sh \
  --orchestrator-host node1.internal \
  --storage-host-path /srv/devicevault/storage \
  --replicas 2 \
  --app-image registry.example.com/devicevault/app:2026.10.19
```

## Configuration contract

### `.env`

`/etc/devicevault/<role>/.env` is now the home for:

- database host, port, user, password
- broker and Redis URLs
- Django secret key
- RabbitMQ credentials
- queue selections
- storage mount paths

### `config.yaml`

`/etc/devicevault/<role>/config.yaml` is now the home for:

- timezone
- auth mode
- local admin seed info
- encryption settings
- future application-level feature settings

## Runtime settings support

[settings.py](../backend/devicevault/settings.py) now honors:

- `DEVICEVAULT_DB_*`
- `POSTGRES_*`
- `MYSQL_*`
- `DEBUG`
- `ALLOWED_HOSTS`
- `DEVICEVAULT_SECRET_KEY`

That means the documented environment-variable override path now matches real runtime behavior.

## Source-checkout fallback

The scripts prefer image deployment, but can still source assets from a checkout:

- if you already cloned the repository into `/opt/devicevault`, that checkout is used
- if you pass `--source-dir`, that checkout is used
- if no checkout is available, the helper may clone once into the deployment root

It never assumes a second checkout inside `/opt/devicevault/repo`.

## Warm standby and promotion

The backup orchestrator uses:

- `warm-standby` profile for Django + Nginx
- `promoted` profile for consumers and local workers

Promotion helper:

- [failover-to-node2.sh](../scripts/failover-to-node2.sh)

See [PRODUCTION_OPERATIONS_RUNBOOK.md](./PRODUCTION_OPERATIONS_RUNBOOK.md) for operational commands.
