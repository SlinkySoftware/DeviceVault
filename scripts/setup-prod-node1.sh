#!/bin/bash
# Production Deployment - Node 1 (Primary Orchestration) Setup
# Usage: sudo bash setup-prod-node1.sh <hostname> <db-password> <rabbitmq-cookie>

set -e

HOSTNAME=${1:-node1.internal}
DB_PASSWORD=${2:-changeme}
RABBITMQ_COOKIE=${3:-$(openssl rand -base64 32)}
DJANGO_SECRET=${4:-$(openssl rand -base64 32)}

DEVICEVAULT_DIR="/etc/devicevault/node1"
REPO_DIR="/opt/devicevault/repo"

echo "=========================================="
echo "DeviceVault Production - Node 1 Setup"
echo "=========================================="
echo "Hostname: $HOSTNAME"
echo "Config Dir: $DEVICEVAULT_DIR"
echo "Repository: $REPO_DIR"
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "ERROR: This script must be run as root (use sudo)"
   exit 1
fi

# Create directory structure
echo "[1/6] Creating directory structure..."
mkdir -p "$DEVICEVAULT_DIR"
chmod 750 "$DEVICEVAULT_DIR"

# Generate environment file
echo "[2/6] Generating environment configuration..."
cat > "$DEVICEVAULT_DIR/.env" << EOF
# Node 1 Production Environment
POSTGRES_DB=devicevault
POSTGRES_USER=devicevault
POSTGRES_PASSWORD=$DB_PASSWORD
POSTGRES_REPLICATION_USER=replicator
POSTGRES_REPLICATION_PASSWORD=$(openssl rand -base64 24)

REDIS_PASSWORD=

RABBITMQ_DEFAULT_USER=guest
RABBITMQ_DEFAULT_PASS=guest
RABBITMQ_ERLANG_COOKIE=$RABBITMQ_COOKIE

DEVICEVAULT_SECRET_KEY=$DJANGO_SECRET
DEVICEVAULT_CONFIG=/etc/devicevault/node1/config.yaml
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,$HOSTNAME,node1.internal

DEVICEVAULT_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
DEVICEVAULT_REDIS_URL=redis://redis:6379/1
DEVICEVAULT_BROKER_API=http://guest:guest@rabbitmq:15672/api/

TZ=Australia/Sydney
EOF
chmod 600 "$DEVICEVAULT_DIR/.env"

# Generate config.yaml
echo "[3/6] Generating application configuration..."
cat > "$DEVICEVAULT_DIR/config.yaml" << 'EOF'
database:
  engine: postgres
  host: postgres
  port: 5432
  name: devicevault
  user: devicevault
  password: ${POSTGRES_PASSWORD}

redis:
  url: redis://redis:6379/1

celery:
  broker: amqp://guest:guest@rabbitmq:5672//
  result_backend: redis://redis:6379/1
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

# Generate PostgreSQL replication configuration
echo "[4/6] Generating PostgreSQL replication configuration..."
cat > "$DEVICEVAULT_DIR/postgresql.conf" << 'EOF'
# PostgreSQL 17 Primary Configuration
# Streaming Replication Settings

max_wal_senders = 3
max_replication_slots = 3
wal_level = replica
wal_keep_size = 1GB

# Archiving (optional, for PITR)
# archive_mode = on
# archive_command = 'cp %p /var/lib/postgresql/archive/%f'
# archive_timeout = 300
EOF
chmod 600 "$DEVICEVAULT_DIR/postgresql.conf"

# Generate PostgreSQL initialization SQL for replication
echo "[5/6] Generating PostgreSQL replication setup SQL..."
cat > "$DEVICEVAULT_DIR/postgres-init.sql" << 'EOF'
-- Create replication user
DO
$do$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'replicator') THEN
    CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replication_password';
  END IF;
END
$do$;

-- Grant replication privileges
GRANT CONNECT ON DATABASE devicevault TO replicator;
EOF
chmod 600 "$DEVICEVAULT_DIR/postgres-init.sql"

# Generate RabbitMQ configuration
echo "[6/6] Generating RabbitMQ configuration..."
cat > "$DEVICEVAULT_DIR/rabbitmq.conf" << 'EOF'
# RabbitMQ 4.0 Configuration for Cluster

# Clustering
cluster_partition_handling = autoheal
cluster_formation.peer_discovery_backend = rabbit_peer_discovery_classic_config
cluster_formation.classic_config.nodes.1 = rabbit@rabbitmq-1
cluster_formation.classic_config.nodes.2 = rabbit@rabbitmq-2

# Disk node (stores all data)
disk_free_limit.absolute = 2GB

# Network
tcp_listen_options.backlog = 4096
tcp_listen_options.nodelay = true

# Management plugin
management.load_definitions = /etc/rabbitmq/definitions.json

# Memory limits
vm_memory_high_watermark.relative = 0.6
vm_memory_high_watermark_paging_ratio = 0.75

# Persistence
queue_master_locator = min-masters
EOF
chmod 600 "$DEVICEVAULT_DIR/rabbitmq.conf"

# Generate Nginx configuration
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

        # Redirect to HTTPS (if configured)
        # return 301 https://$server_name$request_uri;

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

    # HTTPS configuration (uncomment and configure for production)
    # server {
    #     listen 443 ssl http2 default_server;
    #     listen [::]:443 ssl http2 default_server;
    #     server_name _;
    #     
    #     ssl_certificate /etc/nginx/certs/server.crt;
    #     ssl_certificate_key /etc/nginx/certs/server.key;
    #     ssl_protocols TLSv1.2 TLSv1.3;
    #     ssl_ciphers HIGH:!aNULL:!MD5;
    #     ssl_prefer_server_ciphers on;
    #
    #     # ... rest of configuration
    # }
}
EOF
chmod 600 "$DEVICEVAULT_DIR/nginx.conf"

echo ""
echo "=========================================="
echo "✓ Node 1 (Primary) Setup Complete"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "1. Select the branch to deploy:"
echo "   export GIT_BRANCH=\${GIT_BRANCH:-master}"
echo ""
echo "2. Clone DeviceVault repository:"
echo "   git clone --single-branch --branch \"\$GIT_BRANCH\" https://github.com/SlinkySoftware/DeviceVault.git /opt/devicevault/repo"
echo ""
echo "3. Start services:"
echo "   cd /opt/devicevault/repo && docker compose -f docker-build/docker-compose.prod-node1.yaml up -d"
echo ""
echo "4. Verify services:"
echo "   docker compose -f docker-build/docker-compose.prod-node1.yaml ps"
echo ""
echo "5. Check Django health:"
echo "   curl http://localhost:8000/api/health/ -H 'Authorization: Bearer <token>'"
echo ""
echo "Configuration saved to: $DEVICEVAULT_DIR/"
echo "Environment file: $DEVICEVAULT_DIR/.env"
echo "Config YAML: $DEVICEVAULT_DIR/config.yaml"
echo ""
