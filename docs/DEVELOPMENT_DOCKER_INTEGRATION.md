# DeviceVault Development Docker Integration - Summary

## What Was Created

### 1. New Docker Compose File
**File**: `docker-build/docker-compose.dev.yaml`

A lightweight development-focused Docker Compose configuration that provides only:
- **Redis** (port 6379) - for caching and Celery result backend
- **RabbitMQ** (ports 5672, 15672) - for message queuing and task management

### 2. Updated devicevault.sh Script

The main orchestration script now includes Docker service management:

**New Functions:**
- `check_docker()` - Validates Docker and Docker Compose availability
- `start_docker_services()` - Starts Redis & RabbitMQ containers
- `stop_docker_services()` - Stops Docker containers
- `status_docker_services()` - Shows Docker service status
- `logs_docker_services()` - Displays Docker service logs

**Updated Functions:**
- `start()` - Now starts Docker services first, then application services
- `stop()` - Stops application services, then Docker services
- `status()` - Includes Docker service status
- `logs()` - Accepts "docker" as a service name
- `usage()` - Updated help text

### 3. Documentation
**File**: `docker-build/README.dev.md`

Comprehensive guide covering:
- Development vs production setup
- Quick start with devicevault.sh
- Manual Docker management
- Service connection details
- Troubleshooting tips

## How It Works

### Startup Flow
```
./devicevault.sh start
  ↓
1. Check requirements (Python, Node.js, venv)
2. Start Docker services (Redis & RabbitMQ)
3. Start Django backend
4. Start Quasar frontend
5. Start Celery backup worker
6. Start Celery storage worker
7. Start backup result consumer
8. Start storage result consumer
9. Start Flower monitoring
```

### Graceful Degradation
If Docker is not available, the script:
- Prints a warning
- Continues with native services
- Assumes Redis/RabbitMQ are available elsewhere (or will fail gracefully when workers try to connect)

## Key Features

1. **Isolated Development Services**: Only Redis & RabbitMQ run in Docker, everything else runs natively for easier debugging

2. **Persistent Data**: Docker volumes preserve data across restarts:
   - `devicevault-dev-redis-data`
   - `devicevault-dev-rabbitmq-data`

3. **Health Checks**: Both services include health checks for reliable startup

4. **Named Containers**: Easy identification with `devicevault-dev-` prefix

5. **Integrated Management**: Single `devicevault.sh` command manages all services

## Usage Examples

```bash
# Full development environment
./devicevault.sh start

# Check everything
./devicevault.sh status

# View all logs
./devicevault.sh logs

# View just Docker services
./devicevault.sh logs docker

# Stop everything cleanly
./devicevault.sh stop

# Restart everything
./devicevault.sh restart
```

## Service URLs

After starting:
- Frontend: http://localhost:9000
- Backend API: http://localhost:8000
- RabbitMQ Management: http://localhost:15672 (guest/guest)
- Flower Monitoring: http://localhost:5555

## Architecture

```
┌─────────────────────────────────────────────────┐
│           DeviceVault Development               │
├─────────────────────────────────────────────────┤
│                                                 │
│  Native Services (via devicevault.sh):         │
│  ┌─────────────────────────────────────┐       │
│  │ Django Backend      (port 8000)     │       │
│  │ Quasar Frontend     (port 9000)     │       │
│  │ Celery Backup Worker                │       │
│  │ Celery Storage Worker               │       │
│  │ Backup Consumer                     │       │
│  │ Storage Consumer                    │       │
│  │ Flower Monitor      (port 5555)     │       │
│  └─────────────────────────────────────┘       │
│                    ↓ ↓ ↓                        │
│  Docker Services (docker-compose.dev.yaml):    │
│  ┌─────────────────────────────────────┐       │
│  │ Redis              (port 6379)      │       │
│  │ RabbitMQ           (port 5672)      │       │
│  │ RabbitMQ Mgmt      (port 15672)     │       │
│  └─────────────────────────────────────┘       │
└─────────────────────────────────────────────────┘
```

## Comparison: Dev vs Production

| Aspect | Development (dev.yaml) | Production (yaml) |
|--------|----------------------|-------------------|
| Services | Redis, RabbitMQ only | Full stack with Nginx, Django, PostgreSQL, Celery |
| Django/Frontend | Native (easier debugging) | Containerized |
| Database | SQLite (native) | PostgreSQL (container) |
| Purpose | Local development | Production deployment |
| Management | devicevault.sh script | docker compose or Makefile |

## Environment Variables

The application looks for these environment variables (with defaults):

```bash
DEVICEVAULT_BROKER_URL=amqp://guest:guest@localhost:5672//
DEVICEVAULT_REDIS_URL=redis://localhost:6379/1
DEVICEVAULT_BROKER_API=http://guest:guest@localhost:15672/api/
```

These match the ports exposed by `docker-compose.dev.yaml`.

## Next Steps

1. Run `./devicevault.sh start` to test the integration
2. Access RabbitMQ management UI to verify queue creation
3. Check Flower UI to monitor Celery workers
4. Use `./devicevault.sh logs docker` to debug service issues

## Troubleshooting

**Problem**: Docker services fail to start
- **Solution**: Check if ports 6379, 5672, or 15672 are already in use
- **Command**: `lsof -i :6379 && lsof -i :5672 && lsof -i :15672`

**Problem**: Workers can't connect to broker
- **Solution**: Verify RabbitMQ is running
- **Command**: `docker exec devicevault-dev-rabbitmq rabbitmq-diagnostics ping`

**Problem**: Need to reset everything
- **Solution**: Stop and remove volumes
- **Command**: `cd docker-build && docker compose -f docker-compose.dev.yaml down -v`
