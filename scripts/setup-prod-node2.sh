#!/bin/bash
# Production Deployment - Node 2 (Standby) Setup
# Usage: sudo bash setup-prod-node2.sh <node1-hostname> <db-password> <replication-password> <rabbitmq-cookie>

set -e

NODE1_HOST=${1:-node1.internal}
DB_PASSWORD=${2:-changeme}
REPL_PASSWORD=${3:-$(openssl rand -base64 24)}
RABBITMQ_COOKIE=${4:-$(openssl rand -base64 32)}
DJANGO_SECRET=${5:-$(openssl rand -base64 32)}

DEVICEVAULT_DIR="/etc/devicevault/node2"
REPO_DIR="/opt/devicevault/repo"

echo "=========================================="
echo "DeviceVault Production - Node 2 Setup"
echo "=========================================="
echo "Primary Node: $NODE1_HOST"
echo "Config Dir: $DEVICEVAULT_DIR"
echo "Repository: $REPO_DIR"
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "ERROR: This script must be run as root (use sudo)"
   exit 1
fi

# Create directory structure
echo "[1/5] Creating directory structure..."
mkdir -p "$DEVICEVAULT_DIR"
chmod 750 "$DEVICEVAULT_DIR"

# Generate environment file
echo "[2/5] Generating environment configuration..."
cat > "$DEVICEVAULT_DIR/.env" << EOF
# Node 2 Production Environment (Standby Replica)
POSTGRES_DB=devicevault
POSTGRES_USER=devicevault
POSTGRES_PASSWORD=$DB_PASSWORD
POSTGRES_REPLICATION_USER=replicator
POSTGRES_REPLICATION_PASSWORD=$REPL_PASSWORD

REDIS_PASSWORD=

RABBITMQ_DEFAULT_USER=guest
RABBITMQ_DEFAULT_PASS=guest
RABBITMQ_ERLANG_COOKIE=$RABBITMQ_COOKIE

DEVICEVAULT_SECRET_KEY=$DJANGO_SECRET
DEVICEVAULT_CONFIG=/etc/devicevault/node2/config.yaml
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,node2.internal

# Point to Node 1's services for replication
NODE1_HOST=$NODE1_HOST

DEVICEVAULT_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
DEVICEVAULT_REDIS_URL=redis://$NODE1_HOST:6379/1
DEVICEVAULT_BROKER_API=http://guest:guest@rabbitmq:15672/api/

TZ=Australia/Sydney
EOF
chmod 600 "$DEVICEVAULT_DIR/.env"

# Generate config.yaml for standby
echo "[3/5] Generating application configuration (standby mode)..."
cat > "$DEVICEVAULT_DIR/config.yaml" << EOF
database:
  engine: postgres
  host: postgres
  port: 5432
  name: devicevault
  user: devicevault
  password: $DB_PASSWORD

redis:
  url: redis://$NODE1_HOST:6379/1

celery:
  broker: amqp://guest:guest@rabbitmq:5672//
  result_backend: redis://$NODE1_HOST:6379/1
  broker_api: http://guest:guest@rabbitmq:15672/api/

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
EOF
chmod 600 "$DEVICEVAULT_DIR/config.yaml"

# Generate PostgreSQL recovery configuration
echo "[4/5] Generating PostgreSQL standby recovery configuration..."
cat > "$DEVICEVAULT_DIR/postgres-recovery.conf" << EOF
# PostgreSQL 17 Standby Recovery Configuration
standby_mode = 'on'
primary_conninfo = 'host=$NODE1_HOST user=replicator password=$REPL_PASSWORD port=5432 sslmode=prefer'
recovery_target_timeline = 'latest'
restore_command = 'cp /var/lib/postgresql/archive/%f %p'
EOF
chmod 600 "$DEVICEVAULT_DIR/postgres-recovery.conf"

# Generate RabbitMQ configuration for cluster join
echo "[5/5] Generating RabbitMQ configuration (cluster node)..."
cat > "$DEVICEVAULT_DIR/rabbitmq.conf" << EOF
# RabbitMQ 4.0 Configuration for Cluster (Node 2 - Memory Node)

# Clustering (join cluster, memory node for lower resource usage)
cluster_partition_handling = autoheal
cluster_formation.peer_discovery_backend = rabbit_peer_discovery_classic_config
cluster_formation.classic_config.nodes.1 = rabbit@rabbitmq-1
cluster_formation.classic_config.nodes.2 = rabbit@rabbitmq-2

# Memory node (doesn't store all data, lower memory footprint)
disk_free_limit.absolute = 2GB

# Network
tcp_listen_options.backlog = 4096
tcp_listen_options.nodelay = true

# Memory limits
vm_memory_high_watermark.relative = 0.6
vm_memory_high_watermark_paging_ratio = 0.75

# Persistence
queue_master_locator = min-masters
EOF
chmod 600 "$DEVICEVAULT_DIR/rabbitmq.conf"

# Generate Nginx configuration for standby
echo "Generating Nginx reverse proxy configuration..."
cat > "$DEVICEVAULT_DIR/nginx.conf" << 'EOF'
user www-data;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';

    access_log /var/log/nginx/access.log main;
    sendfile on;
    tcp_nopush on;
    keepalive_timeout 65;
    gzip on;

    upstream django {
        server django:8000;
    }

    server {
        listen 80 default_server;
        listen [::]:80 default_server;
        server_name _;

        location / {
            proxy_pass http://django;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_redirect off;
            proxy_buffering off;
        }

        location /static/ {
            alias /app/static/;
            expires 30d;
            add_header Cache-Control "public, immutable";
        }

        location /health/ {
            access_log off;
            proxy_pass http://django;
        }
    }
}
EOF
chmod 600 "$DEVICEVAULT_DIR/nginx.conf"

echo ""
echo "=========================================="
echo "✓ Node 2 (Standby) Setup Complete"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "1. Start services (Django/Nginx will stay down until promoted):"
echo "   cd /opt/devicevault/repo && docker compose -f docker-build/docker-compose.prod-node2.yaml up -d"
echo ""
echo "2. Verify replication services are running:"
echo "   docker compose -f docker-build/docker-compose.prod-node2.yaml ps"
echo ""
echo "3. Monitor PostgreSQL replication status from Node 1:"
echo "   docker exec postgres-1 psql -U devicevault -d devicevault -c 'SELECT * FROM pg_stat_replication;'"
echo ""
echo "4. To promote Node 2 to primary (on Node 1 failure):"
echo "   docker exec postgres-2 touch /var/lib/postgresql/data/promote"
echo "   docker exec django-2 docker-compose up django nginx"
echo ""
echo "Configuration saved to: $DEVICEVAULT_DIR/"
echo "Environment file: $DEVICEVAULT_DIR/.env"
echo "Config YAML: $DEVICEVAULT_DIR/config.yaml"
echo ""
