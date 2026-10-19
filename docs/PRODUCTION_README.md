# DeviceVault Production Deployment

This production workflow is now **image-first** and **role-based**:

- deployment hosts do **not** need a nested `/opt/devicevault/repo` checkout
- the production compose files are split by role
- runtime infrastructure and secrets live in `/etc/devicevault/<role>/.env`
- application/domain settings live in `/etc/devicevault/<role>/config.yaml`
- deployment assets are installed into `/opt/devicevault/deploy/<role>/`

## Production roles

DeviceVault now ships four production role definitions:

1. **Orchestrator Primary**
2. **Orchestrator Backup**
3. **Collector Worker**
4. **Storage Worker**

The compose files for those roles live in [docker-build/](../docker-build):

- [docker-compose.prod-orchestrator-primary.yaml](../docker-build/docker-compose.prod-orchestrator-primary.yaml)
- [docker-compose.prod-orchestrator-backup.yaml](../docker-build/docker-compose.prod-orchestrator-backup.yaml)
- [docker-compose.prod-collector-worker.yaml](../docker-build/docker-compose.prod-collector-worker.yaml)
- [docker-compose.prod-storage-worker.yaml](../docker-build/docker-compose.prod-storage-worker.yaml)

## Scripts

### Build

Use [build-prod-images.sh](../scripts/build-prod-images.sh) to build production images from the current checkout:

```bash
scripts/build-prod-images.sh
```

It builds:

- `devicevault/app:<tag>`
- `devicevault/nginx:<tag>`

You can override the source checkout, tag, prefix, and optionally push the images:

```bash
scripts/build-prod-images.sh \
  --source-dir /opt/devicevault \
  --image-prefix registry.example.com/devicevault \
  --image-tag 2026.10.19 \
  --push
```

### Per-role deployment

Use one setup/deploy script per role:

- [setup-prod-orchestrator-primary.sh](../scripts/setup-prod-orchestrator-primary.sh)
- [setup-prod-orchestrator-backup.sh](../scripts/setup-prod-orchestrator-backup.sh)
- [setup-prod-collector-worker.sh](../scripts/setup-prod-collector-worker.sh)
- [setup-prod-storage-worker.sh](../scripts/setup-prod-storage-worker.sh)

Each script:

- reuses existing values from `/etc/devicevault/<role>/` when present
- prompts for missing required values
- installs compose assets into `/opt/devicevault/deploy/<role>/`
- deploys with `docker compose up -d` by default
- supports `--skip-start` for config-only runs

## Recommended deployment flow

### 1. Build images

```bash
scripts/build-prod-images.sh --image-prefix registry.example.com/devicevault
```

### 2. Deploy the primary orchestrator

```bash
sudo scripts/setup-prod-orchestrator-primary.sh \
  --app-image registry.example.com/devicevault/app:2026.10.19 \
  --nginx-image registry.example.com/devicevault/nginx:2026.10.19
```

### 3. Deploy the backup orchestrator

```bash
sudo scripts/setup-prod-orchestrator-backup.sh \
  --primary-host node1.internal \
  --app-image registry.example.com/devicevault/app:2026.10.19 \
  --nginx-image registry.example.com/devicevault/nginx:2026.10.19
```

### 4. Deploy collector workers

```bash
sudo scripts/setup-prod-collector-worker.sh \
  --orchestrator-host node1.internal \
  --collector-queues collector.group.group1,collector.group.group2 \
  --replicas 2 \
  --app-image registry.example.com/devicevault/app:2026.10.19
```

### 5. Deploy storage workers

```bash
sudo scripts/setup-prod-storage-worker.sh \
  --orchestrator-host node1.internal \
  --storage-host-path /srv/devicevault/storage \
  --replicas 2 \
  --app-image registry.example.com/devicevault/app:2026.10.19
```

## Backward compatibility

The legacy wrapper scripts still exist:

- [setup-prod-node1.sh](../scripts/setup-prod-node1.sh)
- [setup-prod-node2.sh](../scripts/setup-prod-node2.sh)
- [setup-prod-collector.sh](../scripts/setup-prod-collector.sh)

They now forward into the new role-based scripts and print a deprecation warning.

## More detail

- Architecture and workflow: [PRODUCTION_DEPLOYMENT.md](./PRODUCTION_DEPLOYMENT.md)
- Config examples: [PRODUCTION_CONFIG_EXAMPLES.md](./PRODUCTION_CONFIG_EXAMPLES.md)
- Operations: [PRODUCTION_OPERATIONS_RUNBOOK.md](./PRODUCTION_OPERATIONS_RUNBOOK.md)
- Document index: [PRODUCTION_DEPLOYMENT_INDEX.md](./PRODUCTION_DEPLOYMENT_INDEX.md)
