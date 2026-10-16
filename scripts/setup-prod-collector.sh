#!/bin/bash
# Production Deployment - Collector Nodes Setup
# Usage: sudo bash setup-prod-collector.sh <group-id> <node1-host> <redis-host> <rabbitmq-host>

set -e

GROUP_ID=${1:-group1}
NODE1_HOST=${2:-node1.internal}
REDIS_HOST=${3:-node1.internal}
RABBITMQ_HOST=${4:-node1.internal}

DEVICEVAULT_DIR="/etc/devicevault/collectors/$GROUP_ID"
REPO_DIR="/opt/devicevault/repo"

echo "=========================================="
echo "DeviceVault Production - Collector Setup"
echo "=========================================="
echo "Group ID: $GROUP_ID"
echo "Primary Node: $NODE1_HOST"
echo "Config Dir: $DEVICEVAULT_DIR"
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "ERROR: This script must be run as root (use sudo)"
   exit 1
fi

# Create directory structure
echo "[1/3] Creating directory structure..."
mkdir -p "$DEVICEVAULT_DIR"
chmod 750 "$DEVICEVAULT_DIR"

# Generate environment file
echo "[2/3] Generating environment configuration..."
cat > "$DEVICEVAULT_DIR/.env" << EOF
# Collector Group $GROUP_ID Environment

POSTGRES_DB=devicevault
POSTGRES_USER=devicevault
POSTGRES_PASSWORD=changeme

# Point to primary node for database and cache
POSTGRES_HOST=$NODE1_HOST
POSTGRES_PORT=5432

DEVICEVAULT_CONFIG=/etc/devicevault/collectors/$GROUP_ID/config.yaml
DEBUG=False

# Broker and result backend
DEVICEVAULT_BROKER_URL=amqp://guest:guest@$RABBITMQ_HOST:5672//
DEVICEVAULT_REDIS_URL=redis://$REDIS_HOST:6379/1
DEVICEVAULT_BROKER_API=http://guest:guest@$RABBITMQ_HOST:15672/api/

PYTHONUNBUFFERED=1
TZ=Australia/Sydney
EOF
chmod 600 "$DEVICEVAULT_DIR/.env"

# Generate config.yaml for collector
echo "[3/3] Generating application configuration..."
cat > "$DEVICEVAULT_DIR/config.yaml" << EOF
database:
  engine: postgres
  host: $NODE1_HOST
  port: 5432
  name: devicevault
  user: devicevault
  password: changeme

redis:
  url: redis://$REDIS_HOST:6379/1

celery:
  broker: amqp://guest:guest@$RABBITMQ_HOST:5672//
  result_backend: redis://$REDIS_HOST:6379/1
  broker_api: http://guest:guest@$RABBITMQ_HOST:15672/api/

timezone: Australia/Sydney

collector:
  group_id: $GROUP_ID
  queue: collector.group.$GROUP_ID
  concurrency: 4
  timeout: 300
EOF
chmod 600 "$DEVICEVAULT_DIR/config.yaml"

echo ""
echo "=========================================="
echo "✓ Collector Group $GROUP_ID Setup Complete"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "1. Start collector workers:"
echo "   cd /opt/devicevault/repo && docker compose -f docker-build/docker-compose.prod-collector-$GROUP_ID.yaml up -d"
echo ""
echo "2. Verify workers are running:"
echo "   docker compose -f docker-build/docker-compose.prod-collector-$GROUP_ID.yaml ps"
echo ""
echo "3. Check worker logs:"
echo "   docker compose -f docker-build/docker-compose.prod-collector-$GROUP_ID.yaml logs -f"
echo ""
echo "4. Monitor workers in Flower:"
echo "   http://$NODE1_HOST:5555/"
echo ""
echo "Configuration saved to: $DEVICEVAULT_DIR/"
echo "Environment file: $DEVICEVAULT_DIR/.env"
echo "Config YAML: $DEVICEVAULT_DIR/config.yaml"
echo ""
