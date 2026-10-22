# DeviceVault Production Config Examples

This file shows the new production configuration contract:

- infrastructure and secrets in `/etc/devicevault/<role>/.env`
- application/domain settings in `/etc/devicevault/<role>/config.yaml`

## Orchestrator Primary

### `/etc/devicevault/orchestrator-primary/.env`

```bash
POSTGRES_DB=devicevault
POSTGRES_USER=devicevault
POSTGRES_PASSWORD=<strong-password>
POSTGRES_REPLICATION_USER=replicator
POSTGRES_REPLICATION_PASSWORD=<strong-replication-password>

RABBITMQ_DEFAULT_USER=devicevault
RABBITMQ_DEFAULT_PASS=<strong-rabbitmq-password>
RABBITMQ_ERLANG_COOKIE=<long-random-cookie>

DEVICEVAULT_SECRET_KEY=<django-secret>
DEVICEVAULT_CONFIG=/etc/devicevault/orchestrator-primary/config.yaml
DEBUG=False
ALLOWED_HOSTS=node1.internal,devicevault.example.com
TZ=Australia/Sydney

DEVICEVAULT_DB_ENGINE=postgres
DEVICEVAULT_DB_NAME=devicevault
DEVICEVAULT_DB_USER=devicevault
DEVICEVAULT_DB_PASSWORD=<strong-password>
DEVICEVAULT_DB_HOST=postgres
DEVICEVAULT_DB_PORT=5432

DEVICEVAULT_BROKER_URL=amqp://devicevault:<strong-rabbitmq-password>@rabbitmq:5672//
DEVICEVAULT_REDIS_URL=redis://redis:6379/1
DEVICEVAULT_RESULT_BACKEND=redis://redis:6379/1
DEVICEVAULT_BROKER_API=http://devicevault:<strong-rabbitmq-password>@rabbitmq:15672/api/

DEVICEVAULT_COLLECTOR_QUEUES=default
DEVICEVAULT_LOCAL_COLLECTOR_CONCURRENCY=1
DEVICEVAULT_STORAGE_QUEUES=storage.fs,storage.git
DEVICEVAULT_LOCAL_STORAGE_CONCURRENCY=1
DEVICEVAULT_STORAGE_HOST_PATH=/srv/devicevault/storage
DEVICEVAULT_STORAGE_CONTAINER_PATH=/srv/devicevault/storage
```

### `/etc/devicevault/orchestrator-primary/config.yaml`

```yaml
timezone: Australia/Sydney

local_admin:
  username: admin
  encrypted_password: ''

auth:
  type: Local
  local_enabled: true

encryption:
  enabled: false
  key_provider: local
  keys: {}
  chunk_size_bytes: 1048576
  allow_plaintext_fallback: true
```

## Orchestrator Backup

### `/etc/devicevault/orchestrator-backup/.env`

```bash
POSTGRES_DB=devicevault
POSTGRES_USER=devicevault
POSTGRES_PASSWORD=<strong-password>
POSTGRES_REPLICATION_USER=replicator
POSTGRES_REPLICATION_PASSWORD=<strong-replication-password>

RABBITMQ_DEFAULT_USER=devicevault
RABBITMQ_DEFAULT_PASS=<strong-rabbitmq-password>
RABBITMQ_ERLANG_COOKIE=<same-cookie-as-primary>

DEVICEVAULT_PRIMARY_HOST=node1.internal

DEVICEVAULT_SECRET_KEY=<django-secret>
DEVICEVAULT_CONFIG=/etc/devicevault/orchestrator-backup/config.yaml
DEBUG=False
ALLOWED_HOSTS=node2.internal
TZ=Australia/Sydney

DEVICEVAULT_DB_ENGINE=postgres
DEVICEVAULT_DB_NAME=devicevault
DEVICEVAULT_DB_USER=devicevault
DEVICEVAULT_DB_PASSWORD=<strong-password>
DEVICEVAULT_DB_HOST=postgres
DEVICEVAULT_DB_PORT=5432

DEVICEVAULT_BROKER_URL=amqp://devicevault:<strong-rabbitmq-password>@rabbitmq:5672//
DEVICEVAULT_REDIS_URL=redis://redis:6379/1
DEVICEVAULT_RESULT_BACKEND=redis://redis:6379/1
DEVICEVAULT_BROKER_API=http://devicevault:<strong-rabbitmq-password>@rabbitmq:15672/api/
```

## Collector Worker

### `/etc/devicevault/collector-worker/.env`

```bash
POSTGRES_DB=devicevault
POSTGRES_USER=devicevault
POSTGRES_PASSWORD=<strong-password>

DEVICEVAULT_CONFIG=/etc/devicevault/collector-worker/config.yaml
DEBUG=False
TZ=Australia/Sydney

DEVICEVAULT_DB_ENGINE=postgres
DEVICEVAULT_DB_NAME=devicevault
DEVICEVAULT_DB_USER=devicevault
DEVICEVAULT_DB_PASSWORD=<strong-password>
DEVICEVAULT_DB_HOST=node1.internal
DEVICEVAULT_DB_PORT=5432

DEVICEVAULT_BROKER_URL=amqp://devicevault:<strong-rabbitmq-password>@node1.internal:5672//
DEVICEVAULT_REDIS_URL=redis://node1.internal:6379/1
DEVICEVAULT_RESULT_BACKEND=redis://node1.internal:6379/1
DEVICEVAULT_BROKER_API=http://devicevault:<strong-rabbitmq-password>@node1.internal:15672/api/

DEVICEVAULT_COLLECTOR_QUEUES=collector.group.group1,collector.group.group2
DEVICEVAULT_COLLECTOR_CONCURRENCY=4
DEVICEVAULT_WORKER_REPLICAS=2
```

## Storage Worker

### `/etc/devicevault/storage-worker/.env`

```bash
POSTGRES_DB=devicevault
POSTGRES_USER=devicevault
POSTGRES_PASSWORD=<strong-password>

DEVICEVAULT_CONFIG=/etc/devicevault/storage-worker/config.yaml
DEBUG=False
TZ=Australia/Sydney

DEVICEVAULT_DB_ENGINE=postgres
DEVICEVAULT_DB_NAME=devicevault
DEVICEVAULT_DB_USER=devicevault
DEVICEVAULT_DB_PASSWORD=<strong-password>
DEVICEVAULT_DB_HOST=node1.internal
DEVICEVAULT_DB_PORT=5432

DEVICEVAULT_BROKER_URL=amqp://devicevault:<strong-rabbitmq-password>@node1.internal:5672//
DEVICEVAULT_REDIS_URL=redis://node1.internal:6379/1
DEVICEVAULT_RESULT_BACKEND=redis://node1.internal:6379/1
DEVICEVAULT_BROKER_API=http://devicevault:<strong-rabbitmq-password>@node1.internal:15672/api/

DEVICEVAULT_STORAGE_QUEUES=storage.fs,storage.git
DEVICEVAULT_STORAGE_CONCURRENCY=2
DEVICEVAULT_WORKER_REPLICAS=2
DEVICEVAULT_STORAGE_HOST_PATH=/srv/devicevault/storage
DEVICEVAULT_STORAGE_CONTAINER_PATH=/srv/devicevault/storage
```

## Script examples

```bash
sudo scripts/setup-prod-orchestrator-primary.sh
sudo scripts/setup-prod-orchestrator-backup.sh --primary-host node1.internal
sudo scripts/setup-prod-collector-worker.sh --orchestrator-host node1.internal
sudo scripts/setup-prod-storage-worker.sh --orchestrator-host node1.internal
```
