# Production Deployment Documentation Index

This index provides navigation to all production deployment documentation for DeviceVault.

## 📋 Quick Links

| Document | Purpose | Audience | Time |
|----------|---------|----------|------|
| [PRODUCTION_README.md](./PRODUCTION_README.md) | Overview & quick start | Everyone | 5 min |
| [PRODUCTION_DEPLOYMENT.md](./PRODUCTION_DEPLOYMENT.md) | Architecture & design | Architects, DevOps | 20 min |
| [PRODUCTION_CONFIG_EXAMPLES.md](./PRODUCTION_CONFIG_EXAMPLES.md) | Configuration reference | DevOps, SRE | 15 min |
| [PRODUCTION_OPERATIONS_RUNBOOK.md](./PRODUCTION_OPERATIONS_RUNBOOK.md) | Day-2 operations | On-call engineers | 30 min |

## 📦 Deployment Artifacts

```
scripts/
├── setup-prod-node1.sh              # Initialize primary node
├── setup-prod-node2.sh              # Initialize standby node
├── setup-prod-collector.sh          # Initialize collector nodes
└── failover-to-node2.sh             # Promote standby to primary

docker-build/
├── docker-compose.prod-node1.yaml       # Node 1 services
├── docker-compose.prod-node2.yaml       # Node 2 services
├── docker-compose.prod-collector-group1.yaml
└── docker-compose.prod-collector-group2.yaml
```

## 🏗️ Architecture Summary

**6-Node Production Deployment:**

1. **Node 1 (Primary)** — Active orchestration, DB, cache, broker
2. **Node 2 (Standby)** — Read replicas, cold standby application
3. **Nodes 3-4 (Group 1)** — Collector workers (3 workers each, 4 processes each)
4. **Nodes 5-6 (Group 2)** — Collector workers (3 workers each, 4 processes each)

**Total Concurrency:** 48 simultaneous collection processes (3 workers × 4 processes × 4 nodes)

## 🚀 Quick Start

### Step 1: Prepare Infrastructure
- [ ] 6 servers provisioned (4+ CPU, 8+ GB RAM, 100+ GB storage)
- [ ] Ubuntu 22.04 LTS or Debian 12 installed
- [ ] Docker & Docker Compose configured
- [ ] Internal network connectivity verified (10.0.0.0/24)
- [ ] DNS configured: node1.internal, node2.internal, etc.

### Step 2: Generate Configuration
```bash
# On Node 1
sudo bash scripts/setup-prod-node1.sh node1.internal <password> <cookie>

# On Node 2
sudo bash scripts/setup-prod-node2.sh node1.internal <password> <repl-pass> <cookie>

# On Nodes 3-6
sudo bash scripts/setup-prod-collector.sh group1 node1.internal node1.internal node1.internal
```

### Step 3: Deploy Services
```bash
# Node 1
cd /opt/devicevault/repo
docker compose -f docker-build/docker-compose.prod-node1.yaml up -d

# Node 2
docker compose -f docker-build/docker-compose.prod-node2.yaml up -d

# Nodes 3-6
docker compose -f docker-build/docker-compose.prod-collector-group1.yaml up -d
docker compose -f docker-build/docker-compose.prod-collector-group2.yaml up -d
```

### Step 4: Verify Deployment
```bash
# Health check
curl http://node1/api/health/ -H "Authorization: Bearer <token>"

# Replication status
docker exec postgres-1 psql -U devicevault -d devicevault -c \
  "SELECT * FROM pg_stat_replication;"

# Collector connections
curl -u guest:guest http://node1:15672/api/connections
```

### Step 5: Configure External Failover
- [ ] Set up keepalived or cloud load balancer for Node 1 ↔ Node 2 failover
- [ ] Configure health checks to monitor Node 1 availability
- [ ] Test failover by stopping Node 1 services

## 📚 Deep Dives

### For Architects
- Read: [PRODUCTION_DEPLOYMENT.md](./PRODUCTION_DEPLOYMENT.md)
- Focus: Design principles, scalability, HA strategy
- Key Sections:
  - Architecture diagram
  - High availability design (standby DB/cache/MQ)
  - Collector grouping and routing
  - Replication and failover model

### For DevOps/SREs
- Read: [PRODUCTION_CONFIG_EXAMPLES.md](./PRODUCTION_CONFIG_EXAMPLES.md)
- Read: [PRODUCTION_OPERATIONS_RUNBOOK.md](./PRODUCTION_OPERATIONS_RUNBOOK.md)
- Focus: Configuration, monitoring, incident response
- Key Topics:
  - Environment variables and secrets management
  - PostgreSQL replication setup
  - RabbitMQ clustering
  - Alerting and health checks
  - Failover procedures
  - Backup/restore strategies

### For Platform Engineers
- Read: [PRODUCTION_README.md](./PRODUCTION_README.md) (quick start)
- Read: [PRODUCTION_DEPLOYMENT.md](./PRODUCTION_DEPLOYMENT.md) (deployment phases)
- Focus: Scripting, automation, IaC
- Suggested Improvements:
  - Convert bash scripts to Terraform/CloudFormation
  - Automate failover with keepalived or cloud LB
  - Add Prometheus metrics scraping
  - Integrate with Ansible for multi-node deployment

## 🎯 Common Workflows

### Deploy Production
1. Follow "Quick Start" above (40 minutes)
2. Configure external failover (keepalived, LB)
3. Run smoke tests on collectors
4. Set up monitoring/alerting
5. Document production endpoints

### Scale Collectors
1. Add new node (OS install, Docker)
2. Run `setup-prod-collector.sh` with desired group
3. Deploy docker-compose for that group
4. Verify workers connected in Flower UI
5. Create devices in DeviceVault UI with matching group

### Failover to Node 2
1. Confirm Node 1 down
2. On Node 2: `sudo bash failover-to-node2.sh`
3. Update DNS to point to Node 2
4. Update load balancer backend to Node 2
5. Update collector configs to use Node 2 broker/cache
6. Restart collectors

### Upgrade DeviceVault
1. Update code: `git pull origin main`
2. Rebuild images: `docker compose build --no-cache`
3. Run migrations: `docker compose run --rm django python manage.py migrate`
4. Restart: `docker compose restart`
5. Verify: `curl http://localhost/api/health/`

### Enable Backup Encryption
1. Generate key: `python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"`
2. Edit `/etc/devicevault/node1/config.yaml`
3. Set `encryption.enabled: true` and add key
4. Restart Django: `docker compose restart django`

## 🔍 Monitoring & Alerting

### Key Dashboards
- **Django Admin**: http://node1/admin/
- **Flower (Celery)**: http://node1:5555/
- **RabbitMQ Admin**: http://node1:15672/ (guest/guest)
- **API Docs**: http://node1/api/

### Metrics to Monitor
| Metric | Source | Threshold | Action |
|--------|--------|-----------|--------|
| Replication Lag | PostgreSQL | > 1 hour | Investigate network, check node health |
| Queue Backlog | RabbitMQ | > 1000 msgs | Scale collectors, investigate slowness |
| Worker CPU | Docker | > 80% | Add workers or upgrade hardware |
| Memory Usage | Redis/Postgres | > 80% | Increase memory limit or trim cache |
| Collector Health | Flower | Unhealthy | Check logs, restart worker |

### Alerting (Example)
```yaml
# Prometheus alert rules
groups:
  - name: devicevault
    rules:
      - alert: HighReplicationLag
        expr: replication_lag > 3600
      - alert: HighQueueDepth
        expr: celery_queue_messages > 1000
      - alert: CollectorDown
        expr: up{job="celery"} == 0
```

## 🔧 Troubleshooting Index

| Issue | Symptom | Resolution |
|-------|---------|-----------|
| Collectors not connecting | Workers unhealthy, queue empty | Check network to broker, verify credentials, check Docker build |
| Database replication stuck | Replication lag increasing | Check network, restart replication, check disk space |
| Queue backlog | Tasks stuck, collectors idle | Scale workers, check network, investigate slow tasks |
| Application down | 502 gateway error | Check Django logs, verify DB connectivity |
| RabbitMQ node down | Cluster incomplete | Force forget node or restart |
| High CPU on collectors | Slow collection tasks | Reduce concurrency, upgrade hardware, optimize plugins |
| Out of memory | Container killed | Increase Docker memory limit |

See [PRODUCTION_OPERATIONS_RUNBOOK.md](./PRODUCTION_OPERATIONS_RUNBOOK.md) "Troubleshooting" section for detailed procedures.

## 🔐 Security Checklist

- [ ] Strong passwords generated for all services (DB, RabbitMQ, Django secret key)
- [ ] `/etc/devicevault/` owned by root, mode 750 (directories), 600 (files)
- [ ] Secrets stored in external management system (Vault, AWS Secrets Manager)
- [ ] TLS/SSL enabled for Nginx (if public-facing)
- [ ] RabbitMQ ports restricted to internal network
- [ ] PostgreSQL ports restricted to internal network
- [ ] Redis ports restricted to internal network
- [ ] Backup encryption enabled in config.yaml
- [ ] SSH key-based authentication only (no passwords)
- [ ] Firewall rules configured for each node
- [ ] Regular security updates applied
- [ ] Database backups encrypted at rest

## 📊 Capacity Planning

### Resource Requirements Per Node

| Node Type | CPU | RAM | Storage | Notes |
|-----------|-----|-----|---------|-------|
| Node 1 (Primary) | 4+ cores | 8+ GB | 100+ GB | Django, PostgreSQL (primary), Redis, RabbitMQ |
| Node 2 (Standby) | 4+ cores | 8+ GB | 100+ GB | PostgreSQL (replica), Redis (replica), RabbitMQ |
| Collector (Nodes 3-6) | 2+ cores | 4+ GB | 50+ GB | Celery workers only |

### Scalability Estimates

- **Collector Capacity**: 48 concurrent collections (3 workers × 4 processes × 4 nodes)
- **Collection Rate**: ~10-100 collections/hour per worker (depends on device complexity)
- **Max Devices per Group**: Thousands (limited by scheduler task rate, not worker capacity)
- **Horizontal Scaling**: Add collectors on new nodes (no app server scaling needed)

### Performance Tuning

| Bottleneck | Solution |
|------------|----------|
| Slow collections | Add workers, optimize device plugins |
| High queue backlog | Increase concurrency per worker, add workers |
| Database slow | Increase shared_buffers, work_mem, add indexes |
| Memory pressure | Increase container limits, trim Redis cache |
| Network congestion | Add network capacity, use VPC/overlay network |

## 🎓 Learning Resources

- **Celery Docs**: https://docs.celeryproject.io/
- **PostgreSQL Replication**: https://www.postgresql.org/docs/current/warm-standby.html
- **Redis Replication**: https://redis.io/docs/latest/operate/oss_and_stack/management/replication/
- **RabbitMQ Clustering**: https://www.rabbitmq.com/docs/clustering
- **Docker Compose**: https://docs.docker.com/compose/

## 📞 Support & Escalation

For issues or questions:

1. **First**: Check [PRODUCTION_OPERATIONS_RUNBOOK.md](./PRODUCTION_OPERATIONS_RUNBOOK.md) troubleshooting section
2. **Then**: Review service logs (`docker logs <container>`)
3. **Finally**: Contact DeviceVault team or open GitHub issue

**On-Call Rotation**: [Link to escalation policy]

**Incident Channel**: #devicevault-incidents

---

## Document Version & History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-10-17 | Initial production deployment guide |

---

**Last Updated**: 2026-10-17 | **Maintained By**: DeviceVault Team | **License**: GNU GPLv3
