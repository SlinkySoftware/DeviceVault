#!/usr/bin/env bash
# DeviceVault Production - Failover from the primary orchestrator to the backup orchestrator.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="/opt/devicevault/deploy/orchestrator-backup"

echo "=========================================="
echo "DeviceVault Production - Failover Script"
echo "=========================================="
echo ""
echo "⚠️  WARNING: This script will promote Node 2 to PRIMARY"
echo "⚠️  Ensure Node 1 is confirmed DOWN before proceeding"
echo ""
read -p "Continue? (yes/no): " -r
echo
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    exit 1
fi

NODE2_HOST=${1:-$(hostname -f 2>/dev/null || hostname)}

echo "[1/5] Promoting PostgreSQL standby to primary..."
docker compose --env-file "$DEPLOY_DIR/compose.env" -f "$DEPLOY_DIR/compose.yaml" exec -T postgres \
  bash -ec "pg_ctl -D \"\$PGDATA\" promote && pg_isready -U \"\$POSTGRES_USER\""
sleep 5

# Verify promotion
if docker compose --env-file "$DEPLOY_DIR/compose.env" -f "$DEPLOY_DIR/compose.yaml" exec -T postgres \
    psql -U devicevault -d devicevault -c "SELECT version();" > /dev/null 2>&1; then
    echo "✓ PostgreSQL promotion successful"
else
    echo "✗ PostgreSQL promotion failed"
    exit 1
fi

echo "[2/5] Promoting Redis replica to master..."
docker compose --env-file "$DEPLOY_DIR/compose.env" -f "$DEPLOY_DIR/compose.yaml" exec -T redis redis-cli REPLICAOF NO ONE
echo "✓ Redis promotion successful"

echo "[3/5] Starting promoted application services on the backup orchestrator..."
docker compose --env-file "$DEPLOY_DIR/compose.env" -f "$DEPLOY_DIR/compose.yaml" --profile promoted up -d
sleep 10
echo "✓ Promoted services started"

echo "[4/5] Verifying application health..."
if curl -f http://localhost:8000/api/health/ > /dev/null 2>&1; then
    echo "✓ Application health check passed"
else
    echo "✗ Application health check failed"
    echo "Check logs:"
    echo "  docker compose --env-file $DEPLOY_DIR/compose.env -f $DEPLOY_DIR/compose.yaml logs django"
    exit 1
fi

echo "[5/5] Updating DNS/Load Balancer (MANUAL STEP)"
echo "=========================================="
echo "✓ Node 2 Promotion Complete"
echo "=========================================="
echo ""
echo "Manual Tasks Required:"
echo "1. Update DNS to point to Node 2 ($NODE2_HOST or its IP)"
echo "2. Update load balancer to route to Node 2 (port 80/443)"
echo "3. Update collector and storage worker nodes to point to Node 2:"
echo "   - Edit: /etc/devicevault/collector-worker/.env and /etc/devicevault/storage-worker/.env"
echo "   - Change: DEVICEVAULT_BROKER_URL, DEVICEVAULT_REDIS_URL"
echo "   - Restart workers with their installed compose assets"
echo ""
echo "Service URLs (Node 2):"
echo "  Application: http://$NODE2_HOST/"
echo "  API: http://$NODE2_HOST/api/"
echo "  RabbitMQ Admin: http://$NODE2_HOST:15672/"
echo "  PostgreSQL: postgres://$NODE2_HOST:5432/devicevault"
echo ""
echo "Recovery Steps (When Node 1 Returns):"
echo "1. On Node 1, reconfigure as standby replica:"
echo "   - Copy configuration from Node 2"
echo "   - Start PostgreSQL replication from Node 2 (now primary)"
echo "   - Start other services in standby mode"
echo "   - Revert DNS to primary when operational"
echo ""
