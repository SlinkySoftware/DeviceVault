# Production Deployment Index

## Scripts

- Build images: [build-prod-images.sh](../scripts/build-prod-images.sh)
- Deploy primary orchestrator: [setup-prod-orchestrator-primary.sh](../scripts/setup-prod-orchestrator-primary.sh)
- Deploy backup orchestrator: [setup-prod-orchestrator-backup.sh](../scripts/setup-prod-orchestrator-backup.sh)
- Deploy collector workers: [setup-prod-collector-worker.sh](../scripts/setup-prod-collector-worker.sh)
- Deploy storage workers: [setup-prod-storage-worker.sh](../scripts/setup-prod-storage-worker.sh)
- Promote backup orchestrator: [failover-to-node2.sh](../scripts/failover-to-node2.sh)

## Compose files

- [docker-compose.prod-orchestrator-primary.yaml](../docker-build/docker-compose.prod-orchestrator-primary.yaml)
- [docker-compose.prod-orchestrator-backup.yaml](../docker-build/docker-compose.prod-orchestrator-backup.yaml)
- [docker-compose.prod-collector-worker.yaml](../docker-build/docker-compose.prod-collector-worker.yaml)
- [docker-compose.prod-storage-worker.yaml](../docker-build/docker-compose.prod-storage-worker.yaml)

## Dockerfiles

- [Dockerfile.app](../docker-build/Dockerfile.app)
- [Dockerfile.nginx](../docker-build/Dockerfile.nginx)

## Guides

- Overview: [PRODUCTION_README.md](./PRODUCTION_README.md)
- Architecture: [PRODUCTION_DEPLOYMENT.md](./PRODUCTION_DEPLOYMENT.md)
- Config examples: [PRODUCTION_CONFIG_EXAMPLES.md](./PRODUCTION_CONFIG_EXAMPLES.md)
- Operations: [PRODUCTION_OPERATIONS_RUNBOOK.md](./PRODUCTION_OPERATIONS_RUNBOOK.md)
