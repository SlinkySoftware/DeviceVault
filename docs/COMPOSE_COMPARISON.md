# Docker Compose Files Comparison

## Development

Use [docker-compose.dev.yaml](../docker-build/docker-compose.dev.yaml) when you are running:

- native Django
- native frontend
- native workers
- only Redis and RabbitMQ in containers

Typical entrypoint:

```bash
./devicevault.sh start
```

## General full-stack container run

Use [docker-compose.yaml](../docker-build/docker-compose.yaml) when you want one-host containerized app testing from a source checkout.

This file now builds from:

- [Dockerfile.app](../docker-build/Dockerfile.app)
- [Dockerfile.nginx](../docker-build/Dockerfile.nginx)

## Production role-based deployment

Use the role-specific compose files for real production deployment:

- [docker-compose.prod-orchestrator-primary.yaml](../docker-build/docker-compose.prod-orchestrator-primary.yaml)
- [docker-compose.prod-orchestrator-backup.yaml](../docker-build/docker-compose.prod-orchestrator-backup.yaml)
- [docker-compose.prod-collector-worker.yaml](../docker-build/docker-compose.prod-collector-worker.yaml)
- [docker-compose.prod-storage-worker.yaml](../docker-build/docker-compose.prod-storage-worker.yaml)

These are driven by the setup scripts documented in:

- [PRODUCTION_README.md](./PRODUCTION_README.md)
- [PRODUCTION_DEPLOYMENT.md](./PRODUCTION_DEPLOYMENT.md)
