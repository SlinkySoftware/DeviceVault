#!/bin/bash
# DeviceVault Production - Failover from Node 1 to Node 2
# Run this script from Node 2 when Node 1 becomes unavailable
# Prerequisites: Node 2 is running with PostgreSQL, Redis, RabbitMQ replicas

set -e

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

NODE2_HOST=${1:-node2.internal}
DEVICES_DIR="/etc/devicevault/node2"

echo "[1/5] Promoting PostgreSQL standby to primary..."
docker exec postgres-2 bash -c "
  touch /var/lib/postgresql/data/promote
  sleep 2
  pg_ctl -D /var/lib/postgresql/data restart
"
sleep 5

# Verify promotion
if docker exec postgres-2 psql -U devicevault -d devicevault -c "SELECT version();" > /dev/null 2>&1; then
    echo "✓ PostgreSQL promotion successful"
else
    echo "✗ PostgreSQL promotion failed"
    exit 1
fi

echo "[2/5] Promoting Redis replica to master..."
docker exec redis-2 redis-cli SLAVEOF NO ONE
echo "✓ Redis promotion successful"

echo "[3/5] Starting Django application on Node 2..."
docker compose -f docker-build/docker-compose.prod-node2.yaml up -d django nginx
sleep 10
echo "✓ Django and Nginx started"

echo "[4/5] Verifying application health..."
if curl -f http://localhost:8000/api/health/ > /dev/null 2>&1; then
    echo "✓ Application health check passed"
else
    echo "✗ Application health check failed"
    echo "Check logs: docker logs django-2"
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
echo "3. Update collector nodes to point to Node 2:"
echo "   - Edit: /etc/devicevault/collectors/group{1,2}/.env"
echo "   - Change: DEVICEVAULT_BROKER_URL, DEVICEVAULT_REDIS_URL"
echo "   - Restart collectors: docker-compose restart"
echo ""
echo "Service URLs (Node 2):"
echo "  Application: http://$NODE2_HOST/"
echo "  API: http://$NODE2_HOST/api/"
echo "  Flower Monitor: http://$NODE2_HOST:5555/"
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
