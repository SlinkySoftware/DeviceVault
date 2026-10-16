# Production Deployment Operations Runbook

This runbook provides step-by-step procedures for common operations in a DeviceVault production deployment.

## Table of Contents

1. [Initial Deployment](#initial-deployment)
2. [Service Management](#service-management)
3. [Monitoring & Alerting](#monitoring--alerting)
4. [Failover Procedures](#failover-procedures)
5. [Backup & Recovery](#backup--recovery)
6. [Scaling & Performance](#scaling--performance)
7. [Troubleshooting](#troubleshooting)
8. [Maintenance Windows](#maintenance-windows)

---

## Initial Deployment

### Prerequisites

- [ ] 6 servers with Ubuntu/Debian, Docker, Docker Compose
- [ ] Network connectivity between nodes (internal 10.0.0.0/24)
- [ ] External load balancer or keepalived for failover
- [ ] Shared backup storage (NFS, S3, or Git repository)
- [ ] SSL/TLS certificates (if enabling HTTPS)
- [ ] DNS records for node1.internal, node2.internal, etc.

### Phase 1: Deploy Node 1 (Primary)

**Timeline: ~30 minutes**

```bash
# On Node 1
sudo bash /path/to/setup-prod-node1.sh node1.internal <db-password> <rabbitmq-cookie>

# Verify configuration
ls -la /etc/devicevault/node1/

# Clone repository
sudo mkdir -p /opt/devicevault
sudo chown $(whoami):$(whoami) /opt/devicevault
git clone https://github.com/SlinkySoftware/DeviceVault.git /opt/devicevault/repo

# Start services
cd /opt/devicevault/repo
docker compose -f docker-build/docker-compose.prod-node1.yaml up -d

# Wait for services to stabilize
sleep 30

# Verify services
docker compose -f docker-build/docker-compose.prod-node1.yaml ps
docker logs django-1 | tail -20
```

**Verification Checklist:**

```bash
# Health checks
curl http://localhost:8000/api/health/ -H "Authorization: Bearer <token>"
docker exec postgres-1 psql -U devicevault -d devicevault -c "SELECT version();"
docker exec redis-1 redis-cli ping
docker exec rabbitmq-1 rabbitmq-diagnostics -q ping
curl -u guest:guest http://localhost:15672/api/overview
```

✅ All health checks pass → Proceed to Phase 2

### Phase 2: Deploy Node 2 (Standby)

**Timeline: ~30 minutes**

```bash
# On Node 2
sudo bash /path/to/setup-prod-node2.sh node1.internal <db-password> <replication-password> <rabbitmq-cookie>

# Copy repository
git clone https://github.com/SlinkySoftware/DeviceVault.git /opt/devicevault/repo

# Start services (Django/Nginx will stay down)
cd /opt/devicevault/repo
docker compose -f docker-build/docker-compose.prod-node2.yaml up -d

# Wait for replication to initialize
sleep 60
```

**Verification Checklist:**

```bash
# Verify replication services are running
docker compose -f docker-build/docker-compose.prod-node2.yaml ps

# Check PostgreSQL replication status (from Node 1)
docker exec postgres-1 psql -U devicevault -d devicevault \
  -c "SELECT client_addr, state, write_lag FROM pg_stat_replication;"

# Check Redis replication
docker exec redis-2 redis-cli INFO replication | grep role

# Check RabbitMQ cluster status
docker exec rabbitmq-1 rabbitmq-diagnostics -q cluster_status
```

✅ Replication running → Proceed to Phase 3

### Phase 3: Deploy Collector Nodes

**Timeline: ~20 minutes per group**

```bash
# On Node 3 (Group 1, Worker 1)
sudo bash /path/to/setup-prod-collector.sh group1 node1.internal node1.internal node1.internal

# On Node 4 (Group 1, Worker 2)
sudo bash /path/to/setup-prod-collector.sh group1 node1.internal node1.internal node1.internal

# On Node 5 (Group 2, Worker 1)
sudo bash /path/to/setup-prod-collector.sh group2 node1.internal node1.internal node1.internal

# On Node 6 (Group 2, Worker 2)
sudo bash /path/to/setup-prod-collector.sh group2 node1.internal node1.internal node1.internal

# Start collectors
cd /opt/devicevault/repo
docker compose -f docker-build/docker-compose.prod-collector-group1.yaml up -d
docker compose -f docker-build/docker-compose.prod-collector-group2.yaml up -d
```

**Verification Checklist:**

```bash
# Check collectors are connected
curl -u guest:guest http://node1:15672/api/connections

# View workers in Flower
curl http://node1:5555/api/workers

# Check queue status
curl -u guest:guest http://node1:15672/api/queues | jq '.[] | {name, messages}'
```

✅ All collectors connected → Deployment complete

---

## Service Management

### Start All Services (Node 1)

```bash
cd /opt/devicevault/repo
docker compose -f docker-build/docker-compose.prod-node1.yaml up -d
```

### Stop All Services (Node 1)

```bash
docker compose -f docker-build/docker-compose.prod-node1.yaml down
```

### Restart Specific Service (Node 1)

```bash
# Restart Django application
docker compose -f docker-build/docker-compose.prod-node1.yaml restart django

# Restart RabbitMQ
docker compose -f docker-build/docker-compose.prod-node1.yaml restart rabbitmq

# Restart PostgreSQL
docker compose -f docker-build/docker-compose.prod-node1.yaml restart postgres
```

### View Logs

```bash
# Last 50 lines
docker logs django-1

# Follow logs in real-time
docker logs -f django-1

# Logs for specific service
docker logs celery-backup-worker-1 | tail -50
```

### Scale Celery Workers (Collector Nodes)

```bash
# On Collector Node (e.g., Node 3)
# Edit docker-compose.prod-collector-group1.yaml to add more workers

# Redeploy with new configuration
docker compose -f docker-compose.prod-collector-group1.yaml up -d

# Verify new workers are running
docker compose -f docker-compose.prod-collector-group1.yaml ps
```

---

## Monitoring & Alerting

### Dashboard URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| Django Admin | http://node1/admin/ | admin/password |
| API Docs | http://node1/api/ | (Token auth) |
| Flower (Celery) | http://node1:5555/ | (public) |
| RabbitMQ Admin | http://node1:15672/ | guest/guest |
| Prometheus (if added) | http://node1:9090/ | (public) |

### Key Metrics to Monitor

```bash
# 1. Database Health
docker exec postgres-1 psql -U devicevault -d devicevault -c \
  "SELECT datname, numbackends, size FROM pg_stat_databases WHERE datname='devicevault';"

# 2. Replication Lag (PostgreSQL)
docker exec postgres-1 psql -U devicevault -d devicevault -c \
  "SELECT NOW() - pg_last_xact_replay_timestamp() AS replication_lag;"

# 3. Redis Memory Usage
docker exec redis-1 redis-cli INFO memory | grep used_memory_human

# 4. RabbitMQ Queue Depth
curl -s -u guest:guest http://node1:15672/api/queues | \
  jq '.[] | select(.name | startswith("collector")) | {name, messages}'

# 5. Celery Task Status
curl -s http://node1:5555/api/tasks | jq '.tasks | length'

# 6. Collector Connection Count
curl -s -u guest:guest http://node1:15672/api/connections | jq '. | length'
```

### Set Up Alerting (Example: Prometheus)

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'postgres'
    static_configs:
      - targets: ['node1:5432']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance

  - job_name: 'redis'
    static_configs:
      - targets: ['node1:6379']

  - job_name: 'celery'
    static_configs:
      - targets: ['node1:5555']
```

### Alert Examples

**Alert Rule: Database Replication Lag > 1 hour**

```yaml
alert: HighPostgresReplicationLag
expr: replication_lag > 3600
for: 5m
annotations:
  summary: "PostgreSQL replication lag exceeding 1 hour on {{ $labels.instance }}"
  action: "Check network connectivity between nodes, investigate slow nodes"
```

**Alert Rule: Collector Queue Backlog**

```yaml
alert: HighCeleryQueueDepth
expr: celery_queue_messages > 1000
for: 10m
annotations:
  summary: "Celery queue has {{ $value }} messages"
  action: "Scale collectors or investigate slow collection tasks"
```

---

## Failover Procedures

### Automatic vs. Manual Failover

- **Automatic**: Use keepalived or cloud-native LB (recommended for 24/7 operations)
- **Manual**: Use `failover-to-node2.sh` script when Node 1 is confirmed down

### Manual Failover to Node 2

**Prerequisites:**
- Node 1 confirmed down
- Node 2 fully replicated and healthy

**Steps:**

```bash
# 1. On Node 2, run failover script
sudo bash /path/to/failover-to-node2.sh

# 2. Monitor promotion
docker compose -f docker-compose.prod-node2.yaml logs -f postgres

# 3. Update external services (DNS, load balancer)
# - Update DNS A record for orchestration to point to Node 2 IP
# - Update load balancer backend to Node 2 (port 80/443)

# 4. Update collector nodes to point to Node 2
# Edit /etc/devicevault/collectors/groupX/.env on each collector:
#   DEVICEVAULT_BROKER_URL=amqp://guest:guest@node2.internal:5672//
#   DEVICEVAULT_REDIS_URL=redis://node2.internal:6379/1

# 5. Restart collectors
docker compose -f docker-compose.prod-collector-group1.yaml restart
docker compose -f docker-compose.prod-collector-group2.yaml restart

# 6. Verify collectors are connected to Node 2
curl -u guest:guest http://node2:15672/api/connections
```

**Verification:**

```bash
# Test application
curl http://node2/api/health/ -H "Authorization: Bearer <token>"

# Verify all collectors connected
curl http://node2:5555/api/workers
```

### Failback to Node 1 (After Recovery)

Once Node 1 is repaired:

```bash
# 1. On Node 1, start services in standby mode
cd /opt/devicevault/repo
docker compose -f docker-compose.prod-node1.yaml up -d postgres redis rabbitmq

# 2. PostgreSQL will connect as standby to Node 2 (now primary)
docker logs postgres-1 | tail -50 | grep "standby"

# 3. Once Node 1 is fully caught up, promote back (if desired)
# This requires stopping Node 2 services and manual promotion
# Alternative: Keep Node 2 as primary for stability
```

---

## Backup & Recovery

### Automated PostgreSQL Backups

```bash
# On Node 1, set up daily backups
# Schedule: 2 AM daily

# Create backup directory
sudo mkdir -p /backups/postgres
sudo chmod 700 /backups/postgres

# Create backup script
cat > /usr/local/bin/backup-postgres.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/backups/postgres"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/devicevault_$DATE.sql.gz"

docker exec postgres-1 pg_dump -U devicevault devicevault | gzip > $BACKUP_FILE
echo "Backup saved: $BACKUP_FILE"

# Keep only 7 days of backups
find $BACKUP_DIR -type f -name "*.sql.gz" -mtime +7 -delete
EOF

chmod +x /usr/local/bin/backup-postgres.sh

# Schedule with cron
crontab -e
# Add: 0 2 * * * /usr/local/bin/backup-postgres.sh
```

### Restore from Backup

```bash
# On Node 1 (or Node 2 if primary)
BACKUP_FILE="/backups/postgres/devicevault_20240115_020000.sql.gz"

# Stop application
docker compose -f docker-compose.prod-node1.yaml stop django nginx

# Restore
gunzip < $BACKUP_FILE | docker exec -i postgres-1 \
  psql -U devicevault -d devicevault

# Restart application
docker compose -f docker-compose.prod-node1.yaml start django nginx

# Verify
curl http://localhost:8000/api/health/
```

### Redis Data Persistence

Redis is configured with AOF (Append-Only File) for persistence:

```bash
# View Redis persistence
docker exec redis-1 redis-cli INFO persistence | grep aof

# Force AOF rewrite
docker exec redis-1 redis-cli BGREWRITEAOF

# Check AOF file size
docker exec redis-1 ls -lh /data/appendonly.aof
```

### DeviceVault Backup Storage

DeviceVault stores device configs/backups in external storage (mounted to `/backupstorage`):

```bash
# View backup storage usage
du -sh /backupstorage/

# Check NFS mount status
df -h /backupstorage/

# List recent backups
ls -ltr /backupstorage/ | tail -20
```

---

## Scaling & Performance

### Scale Collectors for Group 1

```bash
# On Nodes 3-4, modify docker-compose.prod-collector-group1.yaml
# Add more worker containers (e.g., worker-4, worker-5, etc.)

# Redeploy
docker compose -f docker-compose.prod-collector-group1.yaml up -d

# Verify workers are running
docker compose -f docker-compose.prod-collector-group1.yaml ps
```

### Increase Database Performance

```bash
# Increase shared_buffers and work_mem
docker exec postgres-1 psql -U devicevault -c \
  "ALTER SYSTEM SET shared_buffers = '4GB';"

docker exec postgres-1 psql -U devicevault -c \
  "ALTER SYSTEM SET work_mem = '256MB';"

# Restart PostgreSQL
docker compose -f docker-compose.prod-node1.yaml restart postgres
```

### Increase Redis Memory Limit

```bash
# Edit docker-compose.prod-node1.yaml
redis:
  command: ["redis-server", "--maxmemory", "4gb"]

# Redeploy
docker compose -f docker-compose.prod-node1.yaml up -d redis
```

### Load Testing

```bash
# Use Apache Bench to test API performance
ab -n 1000 -c 10 -H "Authorization: Bearer <token>" http://node1/api/devices/

# Monitor during test
watch -n 1 'docker stats --no-stream'
```

---

## Troubleshooting

### Collector Workers Not Starting

**Symptom:** Workers show unhealthy or don't connect to broker

```bash
# Check logs
docker logs collector-group1-worker-1

# Common issues:
# 1. Network connectivity to broker
docker exec collector-group1-worker-1 ping node1.internal

# 2. Broker credentials incorrect
curl -u guest:guest http://node1:15672/api/overview

# 3. Docker image build failed
docker build -f docker-build/Dockerfile.celery -t devicevault-celery .

# 4. Restart worker
docker restart collector-group1-worker-1
```

### PostgreSQL Replication Stuck

**Symptom:** Replication lag keeps increasing, not catching up

```bash
# Check replication status
docker exec postgres-1 psql -U devicevault -d devicevault -c \
  "SELECT slot_name, restart_lsn, confirmed_flush_lsn FROM pg_replication_slots;"

# Check network between nodes
docker exec postgres-1 nc -zv node2.internal 5432

# Restart replication
docker exec postgres-2 docker-compose restart postgres

# Or reset standby (warning: will re-sync)
docker exec postgres-2 rm -rf /var/lib/postgresql/data/*
docker compose -f docker-compose.prod-node2.yaml restart postgres
```

### RabbitMQ Cluster Node Down

**Symptom:** One node unavailable, messages stuck in queue

```bash
# Check cluster status
docker exec rabbitmq-1 rabbitmq-diagnostics -q cluster_status

# Force node forget (if permanently down)
docker exec rabbitmq-1 rabbitmqctl forget_cluster_node rabbit@rabbitmq-2

# Restart node
docker compose -f docker-compose.prod-nodeX.yaml restart rabbitmq

# Wait for rejoin
sleep 30
docker exec rabbitmq-1 rabbitmq-diagnostics -q cluster_status
```

### Application OutOfMemory (Django)

**Symptom:** Django container crashes with OOM

```bash
# Check memory usage
docker stats django-1

# Increase Docker container memory limit
# Edit docker-compose.prod-node1.yaml:
django:
  deploy:
    resources:
      limits:
        memory: 4G

# Redeploy
docker compose -f docker-compose.prod-node1.yaml up -d
```

### High CPU on Celery Workers

**Symptom:** Collection tasks slow, CPU maxed out

```bash
# Monitor worker processes
docker top collector-group1-worker-1

# Reduce concurrency (fewer parallel processes)
# Edit docker-compose.prod-collector-group1.yaml:
command: celery worker --concurrency=2 --queues=...

# Add more workers on additional nodes
# Or upgrade node hardware (CPU cores, RAM)
```

---

## Maintenance Windows

### Planned Downtime for Upgrades

**Duration: 1-2 hours for full stack upgrade**

1. **Announce maintenance**
   - Notify users of 1-hour service window
   - Reschedule collection tasks outside maintenance window

2. **Backup database**
   ```bash
   sudo /usr/local/bin/backup-postgres.sh
   ```

3. **Stop application**
   ```bash
   docker compose -f docker-compose.prod-node1.yaml stop django nginx
   ```

4. **Pull latest code**
   ```bash
   cd /opt/devicevault/repo
   git fetch origin
   git checkout <new-version-tag>
   ```

5. **Rebuild images**
   ```bash
   docker compose -f docker-compose.prod-node1.yaml build --no-cache
   ```

6. **Run migrations**
   ```bash
   docker compose -f docker-compose.prod-node1.yaml run --rm django \
     python manage.py migrate
   ```

7. **Start services**
   ```bash
   docker compose -f docker-compose.prod-node1.yaml up -d
   ```

8. **Verify**
   ```bash
   curl http://localhost:8000/api/health/
   ```

9. **Announ ce completion**
   - Service is restored

### Zero-Downtime Upgrade (Using Blue-Green Deployment)

1. **Prepare Node 2 with new code (while Node 1 active)**
   ```bash
   # On Node 2
   docker compose -f docker-compose.prod-node2.yaml stop django
   cd /opt/devicevault/repo && git checkout <new-version>
   docker compose -f docker-compose.prod-node2.yaml build --no-cache django
   docker compose -f docker-compose.prod-node2.yaml up -d django
   ```

2. **Test Node 2**
   ```bash
   curl http://node2/api/health/
   ```

3. **Switch traffic to Node 2**
   ```bash
   # Update load balancer/DNS
   # Clients routed to Node 2 automatically
   ```

4. **Upgrade Node 1 (while offline)**
   ```bash
   # Node 1 can be upgraded safely while Node 2 serves traffic
   ```

5. **Failback when ready**
   ```bash
   # Switch traffic back to Node 1
   ```

---

## Contact & Escalation

- **Application Owner**: [Team Name]
- **On-Call Schedule**: [Link to escalation policy]
- **Incident Channel**: #devicevault-incidents
- **Documentation**: https://github.com/SlinkySoftware/DeviceVault/tree/main/docs

---

## Quick Reference

### Critical Commands

```bash
# Health check (from any node)
curl http://node1/api/health/ -H "Authorization: Bearer <token>"

# Check service status
docker-compose ps

# View logs
docker logs <container>

# Failover
sudo bash /path/to/failover-to-node2.sh

# Restart service
docker-compose restart <service>

# Scale collectors
docker-compose up -d --scale celery-worker=5

# Database backup
sudo /usr/local/bin/backup-postgres.sh
```

### Emergency Contacts

- Database Admin: [Name] - [Phone]
- Infrastructure: [Name] - [Phone]
- DeviceVault Developer: [Name] - [Slack]

