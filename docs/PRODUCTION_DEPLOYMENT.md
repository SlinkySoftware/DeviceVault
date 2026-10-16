# DeviceVault Production Deployment Architecture

## Overview

This document describes the recommended production deployment architecture for DeviceVault using Docker containers. The architecture is designed for high availability of backend services and horizontal scalability of collector workers.

### Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        PRODUCTION DEPLOYMENT (6 Nodes)                     │
└────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           NODE 1 - PRIMARY (Active)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐ │
│  │   Orchestration      │  │   PostgreSQL 17      │  │   Redis 7        │ │
│  │   (Django + Nginx)   │  │   (Primary Master)   │  │   (Primary)      │ │
│  │   Port: 80/443       │  │   Port: 5432         │  │   Port: 6379     │ │
│  │   :8000 (internal)   │  │   Replication: ON    │  │   Persistence: Y │ │
│  └──────────────────────┘  └──────────────────────┘  └──────────────────┘ │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │              RabbitMQ 4.x Cluster (Primary Node)                   │  │
│  │              Port: 5672 (AMQP), 15672 (Management UI)              │  │
│  │              Clustering: Enabled, Disk Node                        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Config: /etc/devicevault/node1/                                          │
│  Volumes: postgres-data-1, redis-data-1, rabbitmq-data-1                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                      NODE 2 - SECONDARY (Standby/Backup)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐ │
│  │   Orchestration      │  │   PostgreSQL 17      │  │   Redis 7        │ │
│  │   (Standby, cold)    │  │   (Replica - Read)   │  │   (Replica)      │ │
│  │   Port: 80/443       │  │   Port: 5432         │  │   Port: 6379     │ │
│  │   :8000 (internal)   │  │   Replication: OFF   │  │   Persistence: Y │ │
│  │   ⚠ DO NOT RUN       │  │   Standby Promote    │  │   Read-only      │ │
│  └──────────────────────┘  └──────────────────────┘  └──────────────────┘ │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │         RabbitMQ 4.x Cluster (Secondary Node - Memory Node)         │  │
│  │         Port: 5672 (AMQP), 15672 (Management UI)                    │  │
│  │         Clustering: Enabled, Memory Node (lower resource footprint) │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Config: /etc/devicevault/node2/                                          │
│  Volumes: postgres-data-2, redis-data-2, rabbitmq-data-2                  │
│  Activation: Use external monitoring (e.g., keepalived, Consul) to        │
│              promote this node if Node 1 fails                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│              NODES 3 & 4 - COLLECTOR GROUP 1 (Active Collectors)           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Node 3 & 4 (identical setup, each node runs multiple processes):          │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Celery Worker Container (group1-worker-1)                          │  │
│  │  Queue: collector.group.group1                                      │  │
│  │  Concurrency: 4 processes                                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Celery Worker Container (group1-worker-2)                          │  │
│  │  Queue: collector.group.group1                                      │  │
│  │  Concurrency: 4 processes                                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Celery Worker Container (group1-worker-3) [optional scaling]      │  │
│  │  Queue: collector.group.group1                                      │  │
│  │  Concurrency: 4 processes                                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Config: /etc/devicevault/collectors/group1/                              │
│  Broker: amqp://rabbitmq-broker:5672//                                   │
│  Result Backend: redis://redis-server:6379/1                             │
│                                                                             │
│  Purpose: Dedicated collection infrastructure for devices in Group 1      │
│  Queue Name: collector.group.group1                                       │
│  Router: API automatically routes collection tasks to this queue          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│              NODES 5 & 6 - COLLECTOR GROUP 2 (Active Collectors)           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Node 5 & 6 (identical setup, each node runs multiple processes):          │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Celery Worker Container (group2-worker-1)                          │  │
│  │  Queue: collector.group.group2                                      │  │
│  │  Concurrency: 4 processes                                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Celery Worker Container (group2-worker-2)                          │  │
│  │  Queue: collector.group.group2                                      │  │
│  │  Concurrency: 4 processes                                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Celery Worker Container (group2-worker-3) [optional scaling]      │  │
│  │  Queue: collector.group.group2                                      │  │
│  │  Concurrency: 4 processes                                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Config: /etc/devicevault/collectors/group2/                              │
│  Broker: amqp://rabbitmq-broker:5672//                                   │
│  Result Backend: redis://redis-server:6379/1                             │
│                                                                             │
│  Purpose: Dedicated collection infrastructure for devices in Group 2      │
│  Queue Name: collector.group.group2                                       │
│  Router: API automatically routes collection tasks to this queue          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Design Principles

### 1. **High Availability**
- **Node 1 (Primary)**: Active orchestration, primary database/cache/MQ.
- **Node 2 (Standby)**: Cold standby orchestration with read replicas of database/cache/MQ. Can be promoted to primary via external monitoring/failover orchestration.
- **Infrastructure Redundancy**: PostgreSQL with streaming replication, Redis replication, RabbitMQ clustering.

### 2. **Horizontal Scalability of Collectors**
- Collectors run on dedicated nodes grouped by Collection Group.
- Each group's collectors connect to a common RabbitMQ broker and Redis result backend (hosted on Nodes 1 & 2).
- Multiple Celery worker containers per node allow concurrent processing without node-level contention.
- New collector nodes can be added by deploying the same docker-compose configuration and updating DNS/load balancer.

### 3. **Configuration Externalization**
- All runtime configuration is stored in `/etc/devicevault/` (mounted into containers).
- No Docker image rebuilds required for configuration changes.
- Configuration is versioned and replicated across all nodes.
- Database credentials, API keys, encryption keys are stored in secure configuration files.

### 4. **Container Orchestration**
- Each node runs Docker daemon with docker-compose for local service management.
- Backup storage is mounted from shared infrastructure (NFS, S3, Git).
- Logs are centralized (syslog, ELK stack, Cloudwatch, etc.).

### 5. **No Orchestration HA**
- Django/Nginx application server is NOT highly available at the application level.
- Failover from Node 1 to Node 2 must be handled externally (keepalived, Consul, cloud provider LB).
- Database replication and message queue clustering provide data availability; application failover is manual or external.

## Deployment Steps

### Prerequisites
- 6 servers (physical or VMs) with 8+ GB RAM, 4+ CPUs, 100 GB+ storage.
- Debian 12 (Bookworm) or equivalent Linux distribution.
- Docker and Docker Compose installed on all nodes.
- Network connectivity between all nodes (internal network 10.0.0.0/24 recommended).
- External load balancer or keepalived for Node 1 ↔ Node 2 failover.
- Shared backup storage (NFS, S3, Git repository).

### Phase 1: Infrastructure Setup (Node 1)

1. **Prepare Node 1**:
   ```bash
   sudo mkdir -p /etc/devicevault/node1
   sudo chown -R <user>:<user> /etc/devicevault
   ```

2. **Create configuration files** (see Configuration Examples below):
   - `/etc/devicevault/node1/config.yaml` — Django settings, database, timezone, encryption.
   - `/etc/devicevault/node1/.env` — Environment overrides for database credentials, secret key, broker URL.

3. **Deploy Node 1 services**:
   ```bash
   cd /opt/devicevault
   docker compose -f docker-compose.prod-node1.yaml up -d
   ```

4. **Verify services**:
   ```bash
   docker compose -f docker-compose.prod-node1.yaml ps
   curl http://localhost:8000/api/health/ -H "Authorization: Bearer <token>"
   ```

### Phase 2: Replication Setup (Node 2)

1. **Prepare Node 2**:
   ```bash
   sudo mkdir -p /etc/devicevault/node2
   sudo chown -R <user>:<user> /etc/devicevault
   ```

2. **Copy configuration from Node 1** (modify for replication):
   - Database configuration points to Node 1 as primary.
   - Redis configuration enables replication (slave mode).
   - RabbitMQ joins Node 1's cluster.

3. **Deploy Node 2 services**:
   ```bash
   cd /opt/devicevault
   docker compose -f docker-compose.prod-node2.yaml up -d
   ```

4. **Verify replication**:
   ```bash
   # PostgreSQL replication status (from Node 1)
   docker exec postgres-1 psql -U devicevault -d devicevault -c "SELECT * FROM pg_stat_replication;"
   
   # Redis replication status
   docker exec redis-1 redis-cli INFO replication
   
   # RabbitMQ cluster status
   docker exec rabbitmq-1 rabbitmq-diagnostics -q cluster_status
   ```

### Phase 3: Collector Deployment (Nodes 3-6)

1. **Prepare Collector Nodes**:
   ```bash
   sudo mkdir -p /etc/devicevault/collectors/group{1,2}
   sudo chown -R <user>:<user> /etc/devicevault
   ```

2. **Create collector configuration** (see Configuration Examples):
   - `/etc/devicevault/collectors/group1/config.yaml`
   - `/etc/devicevault/collectors/group2/config.yaml`
   - Broker URLs point to Node 1 (or Node 2 for failover).

3. **Deploy collectors on Nodes 3-4** (Group 1):
   ```bash
   cd /opt/devicevault
   docker compose -f docker-compose.prod-collector-group1.yaml up -d
   ```

4. **Deploy collectors on Nodes 5-6** (Group 2):
   ```bash
   cd /opt/devicevault
   docker compose -f docker-compose.prod-collector-group2.yaml up -d
   ```

5. **Verify collector connectivity**:
   ```bash
   # Check RabbitMQ connections
   curl http://localhost:15672/api/connections -u guest:guest
   
   # Check Celery workers
   docker logs <worker-container>
   ```

### Phase 4: Failover & Monitoring Setup (External)

1. **Set up external monitoring** (keepalived, Consul, cloud LB):
   - Monitor Node 1 health (HTTP /health endpoint, database connectivity).
   - On Node 1 failure, promote Node 2 (DNS update, IP takeover, application start).
   - Ensure collector nodes reconnect to new broker leader automatically.

2. **Database failover**:
   - Promote Node 2's PostgreSQL replica to primary (remove replication).
   - Reconfigure Node 1 as read replica once recovered.

3. **Cache failover**:
   - Redis replication can be promoted manually; requires application reconfiguration.

4. **Message Queue failover**:
   - RabbitMQ cluster handles failover automatically; workers reconnect to available nodes.

## Configuration Examples

### Node 1 Configuration (`/etc/devicevault/node1/config.yaml`)

```yaml
database:
  engine: postgres
  host: localhost
  port: 5432
  name: devicevault
  user: devicevault
  password: <secure-password>

redis:
  url: redis://localhost:6379/1

celery:
  broker: amqp://guest:guest@localhost:5672//
  result_backend: redis://localhost:6379/1
  broker_api: http://guest:guest@localhost:15672/api/

timezone: Australia/Sydney

local_admin:
  username: admin
  encrypted_password: <bcrypt-hash>

auth:
  type: LDAP  # or Local, SAML, etc.
  ldap_server: ldap://ldap.internal:389

encryption:
  enabled: true
  key_provider: local
  default_key_id: mk-prod-1
  keys:
    mk-prod-1: <base64-encoded-32-byte-key>
    mk-prod-2: <base64-encoded-32-byte-key>
```

### Node 2 Configuration (`/etc/devicevault/node2/config.yaml`)

```yaml
database:
  engine: postgres
  host: node1.internal:5432  # Read-only replica, replicating from Node 1
  port: 5432
  name: devicevault
  user: devicevault
  password: <same-as-node1>

redis:
  url: redis://node1.internal:6379/1  # Replicating from Node 1

celery:
  broker: amqp://guest:guest@localhost:5672//  # Local RabbitMQ node
  result_backend: redis://node1.internal:6379/1
  broker_api: http://guest:guest@localhost:15672/api/

# ... rest identical to Node 1
```

### Collector Group 1 Configuration (`/etc/devicevault/collectors/group1/config.yaml`)

```yaml
database:
  engine: postgres
  host: node1.internal:5432  # Connect to primary orchestration DB
  port: 5432
  name: devicevault
  user: devicevault
  password: <same-as-node1>

redis:
  url: redis://node1.internal:6379/1

celery:
  broker: amqp://guest:guest@node1.internal:5672//  # Primary broker
  result_backend: redis://node1.internal:6379/1
  broker_api: http://guest:guest@node1.internal:15672/api/

timezone: Australia/Sydney

# Collector-specific settings
collector:
  queue: collector.group.group1
  concurrency: 4  # 4 processes per Celery worker container
  timeout: 300    # seconds
```

### Collector Group 2 Configuration (`/etc/devicevault/collectors/group2/config.yaml`)

```yaml
# Identical to group1, except:
collector:
  queue: collector.group.group2
  concurrency: 4
```

### Environment File (`.env` for docker-compose)

```bash
# Node 1
POSTGRES_DB=devicevault
POSTGRES_USER=devicevault
POSTGRES_PASSWORD=<secure-password>
POSTGRES_REPLICATION_USER=replicator
POSTGRES_REPLICATION_PASSWORD=<secure-password>

REDIS_PASSWORD=<secure-password>

RABBITMQ_DEFAULT_USER=guest
RABBITMQ_DEFAULT_PASS=guest
RABBITMQ_ERLANG_COOKIE=devicevault-cookie-<random>

DEVICEVAULT_SECRET_KEY=<secure-django-secret>
DEVICEVAULT_CONFIG=/etc/devicevault/node1/config.yaml
DEBUG=False
ALLOWED_HOSTS=node1.internal,10.0.0.1,*.example.com

# Celery
DEVICEVAULT_BROKER_URL=amqp://guest:guest@localhost:5672//
DEVICEVAULT_REDIS_URL=redis://localhost:6379/1
DEVICEVAULT_BROKER_API=http://guest:guest@localhost:15672/api/
```

## Scaling Collectors

To scale collectors for a given group, simply add more worker containers to the respective node:

### Scale Group 1 to 4 workers per node (Nodes 3-4):

```bash
# Modify docker-compose.prod-collector-group1.yaml to increase replicas or add containers
cd /opt/devicevault
docker compose -f docker-compose.prod-collector-group1.yaml up -d \
  --scale celery-worker=4
```

Alternatively, define multiple worker services in the compose file:

```yaml
services:
  celery-worker-1:
    # ...
  celery-worker-2:
    # ...
  celery-worker-3:
    # ...
  celery-worker-4:
    # ...
```

## Monitoring & Logging

### Flower UI (Celery Monitoring)
- Access at `http://node1:5555` (primary) or `http://node2:5555` (standby).
- Monitor worker health, task queue depth, task failures.

### Logs
- Centralize logs from all containers using syslog, Filebeat, or docker logging drivers.
- Logs should be searchable (ELK, Splunk, CloudWatch) for troubleshooting.

### Health Checks
- Django health endpoint: `GET /api/health/` (add if not present).
- Database connectivity: PostgreSQL replication lag.
- Redis connectivity: `redis-cli ping`.
- RabbitMQ connectivity: `rabbitmq-diagnostics ping`.

### Alerts
- Node 1 unavailable → trigger failover to Node 2.
- Database replication lag > threshold → alert.
- Collector queue backlog > threshold → trigger autoscaling.
- Worker CPU/memory > threshold → trigger alerting.

## Security Considerations

1. **Network Isolation**: Isolate internal networks (DB, cache, MQ) from public internet.
2. **TLS/SSL**: Enable TLS for all inter-node communication (PostgreSQL, Redis, RabbitMQ).
3. **Credentials**: Store in external secret management (Vault, AWS Secrets Manager, K8s Secrets).
4. **Backup Encryption**: Enable envelope encryption in DeviceVault config for backup data at rest.
5. **Access Control**: RBAC in Django/DeviceVault API; ACLs on file systems; IAM on cloud storage.

## Troubleshooting

### Node 1 Fails
1. Node 2 replication detects downtime.
2. External monitoring (keepalived, Consul) promotes Node 2 to primary.
3. Update DNS/load balancer to point to Node 2.
4. Collectors and users reconnect to Node 2 automatically.
5. Once Node 1 recovers, reconfigure as read replica.

### Collector Queue Backlog
1. Check Flower UI for stuck tasks.
2. Review logs for timeout or exception patterns.
3. Scale collectors (add more workers/containers).
4. Investigate device SSH/API latency.

### Database Replication Lag
1. Monitor `pg_stat_replication` on Node 1.
2. If lag > acceptable threshold, reduce workload or increase `max_wal_senders`.
3. Consider dedicated replication network.

## Maintenance

### Upgrading DeviceVault
1. Update Docker images on Node 1.
2. Run migrations (Django `migrate` command).
3. Verify on Node 1.
4. If needed, update Node 2 (read-only, no data changes).
5. Update collectors (rolling update, maintain queue coverage).

### Database Maintenance
1. Perform maintenance on Node 2 replica first (safely experimental).
2. VACUUM, ANALYZE on Node 1 during low-traffic windows.
3. Monitor replication lag during maintenance.

### Backup Strategy
1. DeviceVault stores device configs/backups in external storage (Git, S3, NFS).
2. Database backups: `pg_basebackup` from primary or use cloud snapshots.
3. Backup frequency: daily (database) + continuous archiving of WAL logs.
4. Test restore procedures regularly.

## References

- [DeviceVault Celery Integration](./CELERY_INTEGRATION.md)
- [DeviceVault Development Docker Integration](./DEVELOPMENT_DOCKER_INTEGRATION.md)
- PostgreSQL Replication: https://www.postgresql.org/docs/current/warm-standby.html
- Redis Replication: https://redis.io/topics/replication
- RabbitMQ Clustering: https://www.rabbitmq.com/clustering.html
