# Production Deployment Summary

## What changed

The production deployment flow no longer assumes:

- a nested checkout at `/opt/devicevault/repo`
- in-image `git clone`
- group-specific production compose files
- unresolved `${...}` placeholders inside `config.yaml`

## New production model

### Build

- [scripts/build-prod-images.sh](./scripts/build-prod-images.sh)
- [docker-build/Dockerfile.app](./docker-build/Dockerfile.app)
- [docker-build/Dockerfile.nginx](./docker-build/Dockerfile.nginx)

### Deploy

- [scripts/setup-prod-orchestrator-primary.sh](./scripts/setup-prod-orchestrator-primary.sh)
- [scripts/setup-prod-orchestrator-backup.sh](./scripts/setup-prod-orchestrator-backup.sh)
- [scripts/setup-prod-collector-worker.sh](./scripts/setup-prod-collector-worker.sh)
- [scripts/setup-prod-storage-worker.sh](./scripts/setup-prod-storage-worker.sh)

### Compose files

- [docker-build/docker-compose.prod-orchestrator-primary.yaml](./docker-build/docker-compose.prod-orchestrator-primary.yaml)
- [docker-build/docker-compose.prod-orchestrator-backup.yaml](./docker-build/docker-compose.prod-orchestrator-backup.yaml)
- [docker-build/docker-compose.prod-collector-worker.yaml](./docker-build/docker-compose.prod-collector-worker.yaml)
- [docker-build/docker-compose.prod-storage-worker.yaml](./docker-build/docker-compose.prod-storage-worker.yaml)

## Config contract

- infrastructure and secrets: `/etc/devicevault/<role>/.env`
- application/domain settings: `/etc/devicevault/<role>/config.yaml`
- deployed compose assets: `/opt/devicevault/deploy/<role>/`

## Runtime fix

[backend/devicevault/settings.py](./backend/devicevault/settings.py) now honors the documented `DEVICEVAULT_DB_*` overrides, plus `DEBUG` and `ALLOWED_HOSTS`.

## Starting points

- Production overview: [docs/PRODUCTION_README.md](./docs/PRODUCTION_README.md)
- Architecture: [docs/PRODUCTION_DEPLOYMENT.md](./docs/PRODUCTION_DEPLOYMENT.md)
- Config examples: [docs/PRODUCTION_CONFIG_EXAMPLES.md](./docs/PRODUCTION_CONFIG_EXAMPLES.md)
- Operations: [docs/PRODUCTION_OPERATIONS_RUNBOOK.md](./docs/PRODUCTION_OPERATIONS_RUNBOOK.md)
