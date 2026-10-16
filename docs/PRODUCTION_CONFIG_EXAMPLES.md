# Production Deployment Configuration Examples

This directory contains example configuration files for the 6-node production deployment of DeviceVault.

## Directory Structure

```
/etc/devicevault/
├── node1/                           # Primary Orchestration Node
│   ├── config.yaml                  # Django/Application config
│   ├── .env                         # Environment variables (secrets)
│   ├── postgresql.conf              # PostgreSQL replication settings
│   ├── postgres-init.sql            # Replication user setup
│   ├── rabbitmq.conf                # RabbitMQ cluster configuration
│   └── nginx.conf                   # Reverse proxy configuration
│
├── node2/                           # Secondary Standby Node
│   ├── config.yaml                  # Django/Application config (reads from Node 1)
│   ├── .env                         # Environment variables
│   ├── postgres-recovery.conf       # PostgreSQL standby recovery settings
│   ├── rabbitmq.conf                # RabbitMQ cluster join configuration
│   └── nginx.conf                   # Reverse proxy (inactive until promoted)
│
└── collectors/
    ├── group1/                      # Collector Group 1 (Nodes 3-4)
    │   ├── config.yaml
    │   └── .env
    └── group2/                      # Collector Group 2 (Nodes 5-6)
        ├── config.yaml
        └── .env
```

## Configuration File Descriptions

### config.yaml

Main application configuration file. Controls:
- Database connection (PostgreSQL, MySQL, SQLite)
- Redis cache/result backend
- Celery broker and task routing
- Application timezone
- Authentication backend (Local, LDAP, SAML, OAuth)
- Backup encryption settings
- Admin user credentials

**Example (Node 1 - Primary):**
```yaml
database:
  engine: postgres
  host: postgres              # Docker service name
  port: 5432
  name: devicevault
  user: devicevault
  password: <secure-password>

redis:
  url: redis://redis:6379/1   # Docker service name

celery:
  broker: amqp://guest:guest@rabbitmq:5672//
  result_backend: redis://redis:6379/1
  broker_api: http://guest:guest@rabbitmq:15672/api/

timezone: Australia/Sydney
```

**Example (Node 2 - Standby):**
```yaml
database:
  engine: postgres
  host: node1.internal        # Read-only replica from Node 1
  port: 5432
  # ... same as Node 1

redis:
  url: redis://node1.internal:6379/1  # Replicating from Node 1
```

**Example (Collector Nodes):**
```yaml
database:
  engine: postgres
  host: node1.internal        # Primary node
  port: 5432
  # ... rest same

redis:
  url: redis://node1.internal:6379/1

celery:
  broker: amqp://guest:guest@node1.internal:5672//
  result_backend: redis://node1.internal:6379/1
  broker_api: http://guest:guest@node1.internal:15672/api/

collector:
  group_id: group1
  queue: collector.group.group1
  concurrency: 4              # Processes per worker container
  timeout: 300
```

### .env

Environment file containing secrets and runtime configuration. Format: `KEY=VALUE` pairs.

**Important Security Notes:**
- Store in `/etc/devicevault/` with mode `600` (owner read/write only)
- Use external secret management in production (Vault, AWS Secrets Manager, Kubernetes Secrets)
- Rotate passwords and secrets regularly
- Never commit `.env` files to version control

**Example Node 1:**
```bash
# Database
POSTGRES_DB=devicevault
POSTGRES_USER=devicevault
POSTGRES_PASSWORD=<strong-password>
POSTGRES_REPLICATION_USER=replicator
POSTGRES_REPLICATION_PASSWORD=<strong-password>

# Redis
REDIS_PASSWORD=<optional>

# RabbitMQ
RABBITMQ_DEFAULT_USER=guest
RABBITMQ_DEFAULT_PASS=guest
RABBITMQ_ERLANG_COOKIE=<random-string>

# Django
DEVICEVAULT_SECRET_KEY=<django-secret>
DEVICEVAULT_CONFIG=/etc/devicevault/node1/config.yaml
DEBUG=False
ALLOWED_HOSTS=node1.internal,10.0.0.1,example.com

# Celery URLs
DEVICEVAULT_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
DEVICEVAULT_REDIS_URL=redis://redis:6379/1
DEVICEVAULT_BROKER_API=http://guest:guest@rabbitmq:15672/api/

TZ=Australia/Sydney
```

**Example Node 2 (Points to Node 1 for data):**
```bash
# Same as Node 1, but with replication config
POSTGRES_HOST=node1.internal
REDIS_URL=redis://node1.internal:6379/1
DEVICEVAULT_REDIS_URL=redis://node1.internal:6379/1
```

**Example Collector (Points to orchestration nodes):**
```bash
DEVICEVAULT_BROKER_URL=amqp://guest:guest@node1.internal:5672//
DEVICEVAULT_REDIS_URL=redis://node1.internal:6379/1
DEVICEVAULT_BROKER_API=http://guest:guest@node1.internal:15672/api/
```

### postgresql.conf & postgres-recovery.conf

PostgreSQL replication configuration.

**postgres-init.sql (Node 1 Primary):**
```sql
-- Create replication user
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '<password>';

-- Grant privileges
GRANT CONNECT ON DATABASE devicevault TO replicator;

-- Create replication slot (optional, for safer replication)
SELECT * FROM pg_create_physical_replication_slot('replica_slot');
```

**postgres-recovery.conf (Node 2 Standby):**
```bash
standby_mode = 'on'
primary_conninfo = 'host=node1.internal user=replicator password=<password> port=5432'
recovery_target_timeline = 'latest'
```

### rabbitmq.conf

RabbitMQ cluster configuration. Enables inter-node communication and load balancing.

**Node 1 (Disk Node - Stores All Data):**
```
cluster_partition_handling = autoheal
cluster_formation.peer_discovery_backend = rabbit_peer_discovery_classic_config
cluster_formation.classic_config.nodes.1 = rabbit@rabbitmq-1
cluster_formation.classic_config.nodes.2 = rabbit@rabbitmq-2

disk_free_limit.absolute = 2GB
vm_memory_high_watermark.relative = 0.6
```

**Node 2 (Memory Node - Lower Resource Footprint):**
```
# Same clustering config, but RabbitMQ will join as memory node
# Join happens via RABBITMQ_CLUSTER_NODES env var or hostname resolution
```

### nginx.conf

Reverse proxy and web server configuration.

**Key Features:**
- Proxies requests to Django backend
- Serves static files
- Health check endpoint
- Optional HTTPS/TLS
- Request logging and compression

**Example:**
```nginx
upstream django {
    server django:8000;
}

server {
    listen 80 default_server;

    location / {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /app/static/;
        expires 30d;
    }

    location /health/ {
        proxy_pass http://django;
        access_log off;
    }
}
```

## Configuration Generation Scripts

Use the provided setup scripts to generate configurations:

```bash
# Node 1 (Primary)
sudo bash setup-prod-node1.sh node1.internal <db-password> <rabbitmq-cookie>

# Node 2 (Standby)
sudo bash setup-prod-node2.sh node1.internal <db-password> <replication-password> <rabbitmq-cookie>

# Collectors
sudo bash setup-prod-collector.sh group1 node1.internal node1.internal node1.internal
sudo bash setup-prod-collector.sh group2 node1.internal node1.internal node1.internal
```

## Environment Variable Override Priority

DeviceVault respects this priority order for configuration:

1. **Environment variables** (highest priority) — Set via `.env` or docker-compose
2. **config.yaml values** — Application-level YAML configuration
3. **Hardcoded defaults** (lowest priority) — Built-in sensible defaults

Example: `DEVICEVAULT_BROKER_URL` env var overrides `config.yaml` `celery.broker` setting.

## Security Best Practices

1. **Passwords & Secrets**
   - Use strong, random passwords (e.g., `openssl rand -base64 24`)
   - Store in `/etc/devicevault/` with restrictive permissions (`600` or `700`)
   - Use external secret management systems (HashiCorp Vault, AWS Secrets Manager)

2. **Database Credentials**
   - Change default PostgreSQL password immediately
   - Use strong, unique replication user password
   - Enable SSL/TLS for database connections

3. **Django Secret Key**
   - Generate unique secret key per deployment: `python -c "import secrets; print(secrets.token_urlsafe(50))"`
   - Store securely, rotate periodically

4. **RabbitMQ Erlang Cookie**
   - Random cookie per cluster: `openssl rand -base64 32`
   - Keep identical across cluster nodes
   - Store securely

5. **TLS/SSL Certificates**
   - Use trusted CA certificates in production
   - Implement HTTPS on Nginx (configure `ssl_certificate` and `ssl_certificate_key`)
   - Use strong cipher suites (TLSv1.2+)

6. **Network Isolation**
   - Restrict access to internal services (PostgreSQL, Redis, RabbitMQ) to authorized networks
   - Use firewall rules or security groups
   - Require authentication for all services (e.g., RabbitMQ credentials)

## Monitoring & Validation

After deploying configurations:

1. **Health Checks**
   ```bash
   # Django API
   curl http://node1:8000/api/health/
   
   # PostgreSQL
   psql -h node1 -U devicevault -d devicevault -c "SELECT 1;"
   
   # Redis
   redis-cli -h node1 ping
   
   # RabbitMQ
   rabbitmq-diagnostics -q cluster_status
   ```

2. **Replication Status**
   ```bash
   # PostgreSQL replication lag
   psql -h node1 -U devicevault -d devicevault -c "SELECT * FROM pg_stat_replication;"
   
   # Redis replication
   redis-cli -h node1 INFO replication
   
   # RabbitMQ cluster
   rabbitmq-diagnostics -q cluster_status
   ```

3. **Logs**
   - Django: `docker logs django-1`
   - PostgreSQL: `docker logs postgres-1`
   - RabbitMQ: `docker logs rabbitmq-1`
   - Celery: `docker logs celery-*-worker-*`

## Common Configuration Scenarios

### Scenario 1: Enable Backup Encryption

Edit `config.yaml` on Node 1:
```yaml
encryption:
  enabled: true
  key_provider: local
  default_key_id: mk-prod-1
  keys:
    mk-prod-1: <base64-encoded-32-byte-key>
  chunk_size_bytes: 1048576
```

Generate key: `python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"`

### Scenario 2: Enable LDAP Authentication

Edit `config.yaml`:
```yaml
auth:
  type: LDAP
  ldap_server: ldap://ldap.company.com:389
  ldap_search_base: ou=users,dc=company,dc=com
  ldap_search_filter: (uid=%(user)s)
```

### Scenario 3: Use External PostgreSQL (Cloud RDS)

Edit `config.yaml`:
```yaml
database:
  engine: postgres
  host: devicevault-db.xxxxx.rds.amazonaws.com
  port: 5432
  name: devicevault
  user: admin
  password: <from-secrets-manager>
```

### Scenario 4: Increase Collector Concurrency

Edit `/etc/devicevault/collectors/groupX/config.yaml`:
```yaml
collector:
  concurrency: 8  # Increase from default 4
  timeout: 600    # Increase timeout for longer-running collections
```

Or via docker-compose override:
```yaml
celery-worker-1:
  command: >
    celery -A backend.celery_app worker
    --concurrency=8
    --queues=collector.group.group1
```

## References

- [Production Deployment Architecture](./PRODUCTION_DEPLOYMENT.md)
- [Celery Integration Guide](./CELERY_INTEGRATION.md)
- PostgreSQL Replication: https://www.postgresql.org/docs/17/warm-standby.html
- Redis Replication: https://redis.io/docs/latest/operate/oss_and_stack/management/replication/
- RabbitMQ Clustering: https://www.rabbitmq.com/docs/clustering
