# DeviceVault Development Docker Services

This directory contains Docker Compose configurations for DeviceVault:

- **docker-compose.yaml** - Production-ready deployment with all services containerized
- **docker-compose.dev.yaml** - Development services (Redis & RabbitMQ only)

## Development Setup (Recommended)

For local development, use `docker-compose.dev.yaml` which provides only the backing services (Redis & RabbitMQ) while you run the application components natively.

### Quick Start

The easiest way to use the development setup is via the `devicevault.sh` script at the repository root:

```bash
# Start everything (Docker services + native Django/frontend/workers)
./devicevault.sh start

# Check status
./devicevault.sh status

# View logs
./devicevault.sh logs          # All logs
./devicevault.sh logs docker   # Just Docker services

# Stop everything
./devicevault.sh stop
```

### Manual Docker Service Management

If you prefer to manage Docker services separately:

```bash
# Start Redis & RabbitMQ
cd docker-build
docker compose -f docker-compose.dev.yaml up -d

# Check status
docker compose -f docker-compose.dev.yaml ps

# View logs
docker compose -f docker-compose.dev.yaml logs -f

# Stop services
docker compose -f docker-compose.dev.yaml down

# Stop and remove volumes (clean slate)
docker compose -f docker-compose.dev.yaml down -v
```

### Services Provided

- **Redis** (localhost:6379)
  - Used for Celery result backend and application caching
  - Data persisted in volume `devicevault-dev-redis-data`

- **RabbitMQ** (localhost:5672, Management UI: localhost:15672)
  - Message broker for Celery task queues
  - Management UI accessible at http://localhost:15672 (guest/guest)
  - Data persisted in volume `devicevault-dev-rabbitmq-data`

### Connection Details

The Django application expects these services at:

- Redis: `redis://localhost:6379/1`
- RabbitMQ AMQP: `amqp://guest:guest@localhost:5672//`
- RabbitMQ Management API: `http://guest:guest@localhost:15672/api/`

These are the default values configured in `backend/celery_app.py` and can be overridden via environment variables:

- `DEVICEVAULT_REDIS_URL`
- `DEVICEVAULT_BROKER_URL`
- `DEVICEVAULT_BROKER_API`

## Production Deployment

For production deployment, use the main `docker-compose.yaml` which includes:

- Nginx (reverse proxy)
- Django (application server)
- PostgreSQL (database)
- Redis (cache/result backend)
- Celery workers (background tasks)
- Flower (Celery monitoring)

```bash
cd docker-build
docker compose up -d
```

See the main documentation for full production deployment instructions.

## Troubleshooting

### Services won't start

```bash
# Check if ports are already in use
lsof -i :6379   # Redis
lsof -i :5672   # RabbitMQ AMQP
lsof -i :15672  # RabbitMQ Management

# Check Docker logs
docker compose -f docker-compose.dev.yaml logs
```

### Clean restart

```bash
# Stop and remove everything including volumes
docker compose -f docker-compose.dev.yaml down -v

# Start fresh
docker compose -f docker-compose.dev.yaml up -d
```

### Check service health

```bash
# Redis
docker exec devicevault-dev-redis redis-cli ping
# Should return: PONG

# RabbitMQ
docker exec devicevault-dev-rabbitmq rabbitmq-diagnostics ping
# Should return: Ping succeeded
```
