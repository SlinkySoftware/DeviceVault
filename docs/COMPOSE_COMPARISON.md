# Docker Compose Files Comparison

## docker-compose.yaml (Production)
**Purpose**: Full production deployment  
**Services**: 6 services (nginx, django, postgres, redis, rabbitmq, flower)  
**Use Case**: Deploy entire application stack in containers

```yaml
services:
  nginx          # Reverse proxy (port 80)
  django         # Application server (port 8000)
  postgres       # Database
  redis          # Cache/result backend
  # celery      # Background workers (commented)
  flower         # Celery monitoring (port 5555)
```

**Volumes**: 
- pgdata (PostgreSQL data)
- redisdata (Redis data)
- backupstorage (backup files)

**Key Features**:
- Full application stack
- Production-ready with Nginx
- PostgreSQL for production database
- Requires building custom Docker images
- Higher resource usage

---

## docker-compose.dev.yaml (Development) ⭐ NEW
**Purpose**: Lightweight development backing services only  
**Services**: 2 services (redis, rabbitmq)  
**Use Case**: Support local development with native Django/frontend

```yaml
services:
  redis          # Cache/result backend (port 6379)
  rabbitmq       # Message broker (ports 5672, 15672)
```

**Volumes**:
- redis-dev-data (Redis data)
- rabbitmq-dev-data (RabbitMQ data)

**Key Features**:
- Minimal resource footprint
- Uses official Alpine images (no custom builds)
- Named containers for easy identification
- Health checks for reliability
- Integrated with devicevault.sh script
- RabbitMQ management UI included

---

## When to Use Which

### Use docker-compose.dev.yaml when:
✅ Developing locally  
✅ Need to debug Django code  
✅ Want fast iteration cycles  
✅ Testing frontend changes  
✅ Running via `./devicevault.sh`  

### Use docker-compose.yaml when:
✅ Deploying to production  
✅ Testing full containerized stack  
✅ CI/CD pipeline deployment  
✅ Server/cloud deployment  

---

## Integration Points

### Development Flow (docker-compose.dev.yaml)
```
devicevault.sh start
  ↓
docker-compose.dev.yaml up -d (Redis + RabbitMQ)
  ↓
Native Django (localhost:8000)
  ↓
Native Quasar (localhost:9000)
  ↓
Native Celery workers
  ↓
Native consumers
```

### Production Flow (docker-compose.yaml)
```
docker compose up -d
  ↓
All services containerized
  ↓
Nginx (port 80) → Django (internal)
  ↓
PostgreSQL for database
  ↓
Redis + Celery for tasks
```

---

## Port Mapping Comparison

| Service | Development | Production |
|---------|------------|------------|
| Frontend | localhost:9000 (native) | localhost:80 (nginx) |
| Backend | localhost:8000 (native) | internal only |
| Redis | localhost:6379 | internal only |
| RabbitMQ AMQP | localhost:5672 | not included* |
| RabbitMQ Mgmt | localhost:15672 | not included* |
| Flower | localhost:5555 (native) | localhost:5555 |
| PostgreSQL | N/A (SQLite) | internal only |

*Note: Production compose currently uses Redis for Celery broker (RabbitMQ not included in production yaml)

---

## Resource Requirements

### Development (docker-compose.dev.yaml)
- **RAM**: ~200MB for containers
- **CPU**: Minimal
- **Disk**: ~100MB base images + volumes

### Production (docker-compose.yaml)
- **RAM**: ~1-2GB for all containers
- **CPU**: Moderate to high
- **Disk**: ~500MB-1GB images + volumes + backups
