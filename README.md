# DeviceVault

A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.

## License

This project is licensed under the terms of the **GNU General Public License v3.0** (GPLv3) or later version.

You can find the full text of the license in the [LICENSE](LICENSE.md) file or read it online at the [GNU Operating System website](https://www.gnu.org/licenses/gpl-3.0.html).

## Features

- **Plugin-Based Backup Methods**: Extensible architecture for supporting multiple device types
- **Flexible Connectivity**: SSH, API, and TFTP backup reception
- **Multiple Storage Backends**: Git (default), Local Filesystem, S3, Azure, GCS
- **RBAC**: Role-based access control with device group-based visibility
- **Authentication**: LDAP, SAML, Entra ID, and Local Auth support
- **Retention Policies**: Configurable backup retention by count, time, or size
- **Audit Logging**: Complete audit trail of all activities
- **Dashboard**: Real-time statistics and backup success rate charts
- **Backup Comparison**: Side-by-side diff view of configuration changes
- **Distributed Storage Pipeline**: Celery workers offload backup storage to Git or filesystem backends with strict worker routing and synchronous retrieval

## Architecture Documentation

- **[Storage Pipeline](docs/STORAGE_PIPELINE.md)**: Device collection → storage → retrieval workflow with Celery worker routing
- **[Celery Integration](docs/CELERY_INTEGRATION.md)**: Task queue architecture and worker routing
- **[Celery Setup](docs/CELERY_SETUP.md)**: Detailed Celery configuration and startup instructions
- **[Authentication](docs/AUTHENTICATION.md)**: Auth methods (Local, LDAP, SAML, Entra ID)
- **[Timezone Implementation](docs/TIMEZONE_IMPLEMENTATION.md)**: Timezone handling and configuration

## Technology Stack

- **Backend**: Python 3.13+ with Django 6.0
- **Frontend**: Vue 3 with Quasar Framework
- **Database**: SQLite (default), PostgreSQL, or MySQL
- **API**: Django REST Framework

## Quick Start

```bash
# Start the application
./devicevault.sh start

# Access at http://localhost:9000
# Login: admin / admin
```

## Installation

See detailed installation instructions below.

### Prerequisites

On Debian Linux 13:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.13
sudo apt install python3 python3-pip python3-venv -y

# Install Node.js 18+ and npm
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs -y

# Verify installations
python3 --version  # Should be 3.13+
node --version     # Should be 18+
npm --version
```

### Application Setup

0. **Clone the repository**
```bash
# clone into /opt/devicevault (requires sudo to write to /opt)
sudo git clone https://github.com/SlinkySoftware/DeviceVault.git /opt/devicevault
cd /opt/devicevault
```

1. **Set Up Python Virtual Environment**
```bash
cd /opt/devicevault
python3 -m venv .venv
source .venv/bin/activate
```

2. **Install Python Dependencies**
```bash
cd backend
pip install -r requirements.txt
```

3. **Install Frontend Dependencies**
```bash
cd ../frontend
npm install
npm install -g @quasar/cli
```

4. **Initialize Database**
```bash
cd ../backend
python manage.py migrate --run-syncdb
```

5. **Create Admin User**
```bash
# Preferred: run the supplied idempotent helper (from repo root)
chmod +x setup/create-initial-configuration.sh
./setup/create-initial-configuration.sh

# Alternatively (manual):
cd backend
python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', 'admin@example.com', 'admin') if not User.objects.filter(username='admin').exists() else print('Admin user already exists')"
```

## Running the Application

### Using the Management Script (Recommended)

The `devicevault.sh` script provides a comprehensive management interface for all services:

```bash
cd /opt/devicevault

# Start all services (frontend, backend, workers, consumers, flower)
./devicevault.sh start

# Check status of all services
./devicevault.sh status

# View logs (all services or specific service)
./devicevault.sh logs              # All logs
./devicevault.sh logs backend      # Backend only
./devicevault.sh logs frontend     # Frontend only
./devicevault.sh logs backup-worker       # Backup worker
./devicevault.sh logs storage-worker      # Storage worker
./devicevault.sh logs backup-consumer     # Backup consumer
./devicevault.sh logs storage-consumer    # Storage consumer
./devicevault.sh logs flower              # Flower monitoring

# Restart all services
./devicevault.sh restart

# Stop all services
./devicevault.sh stop
```

#### What the Management Script Starts

The `./devicevault.sh start` command automatically starts:

1. **Django Backend** (`http://localhost:8000`) — REST API and admin interface
2. **Frontend (Quasar)** (`http://localhost:9000`) — SPA web interface
3. **Backup Worker** — Celery worker for device backup collection (queues: `default`, `collector.group.*`)
4. **Storage Worker** — Celery worker for backup storage operations (queues: `storage.fs`, `storage.git`)
5. **Backup Consumer** — Django management command that consumes backup results from Redis Stream (`device:results`)
6. **Storage Consumer** — Django management command that consumes storage results from Redis Stream (`storage:results`)
7. **Flower Monitoring** (`http://localhost:5555`) — Celery task monitoring interface

All services are managed as background processes with PID files stored in `.pids/`.

### Running Individual Services Manually

For development or debugging, start individual services:

```bash
# Activate virtual environment (required for all commands)
source .venv/bin/activate
cd backend

# Start Django development server only
python manage.py runserver 0.0.0.0:8000

# Start Backup Worker (in separate terminal)
celery -A celery_app worker \
  -Q default,collector.group.dmz_zone_queue,collector.group.secure_zone_queue \
  -l info --concurrency=1

# Start Storage Worker (in separate terminal)
celery -A celery_app worker \
  -Q storage.fs,storage.git \
  -l info --concurrency=1 \
  -n storage-worker@%h

# Start Backup Consumer (in separate terminal)
python manage.py consume_device_results

# Start Storage Consumer (in separate terminal)
python manage.py consume_storage_results

# Start Flower monitoring (in separate terminal)
celery -A celery_app flower --broker-api=http://guest:guest@localhost:15672/api/ --port=5555
```

Convenience scripts are also provided in the repository root:
- `start-backup-worker.sh` — Quick start for backup worker
- `start-storage-worker.sh` — Quick start for storage worker
- `start-flower.sh` — Quick start for Flower monitoring

## Accessing the Application

- **Frontend**: http://localhost:9000
- **Backend API**: http://localhost:8000/api/
- **Django Admin**: http://localhost:8000/admin/
- **Flower Monitoring**: http://localhost:5555 (Celery task monitor)

**Default Credentials:**
- Username: `admin`
- Password: `admin`

## Configuration

### Backend Configuration File

The backend reads configuration from `backend/config/config.yaml`. This file controls:

```yaml
# Database engine: sqlite, postgres, or mysql
database:
  engine: sqlite
  name: devicevault.sqlite3      # SQLite file path
  # For postgres/mysql, also configure:
  # user: dbuser
  # password: dbpass
  # host: localhost
  # port: 5432

# Application timezone (for display; database stores UTC)
# Valid values: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
timezone: Australia/Sydney

# Local admin user seed
local_admin:
  username: admin
  encrypted_password: ''

# Authentication settings
auth:
  type: Local                     # Options: Local, LDAP, SAML, EntraID
  local_enabled: true
```

### Environment Variables

Key environment variables for configuration (override config.yaml settings):

```bash
# Django settings
export DEVICEVAULT_CONFIG=backend/config/config.yaml
export DEVICEVAULT_SECRET_KEY=your-secret-key

# Database (overrides config.yaml)
export DEVICEVAULT_DB_ENGINE=postgres
export DEVICEVAULT_DB_NAME=devicevault
export DEVICEVAULT_DB_USER=dbuser
export DEVICEVAULT_DB_PASSWORD=dbpass
export DEVICEVAULT_DB_HOST=localhost
export DEVICEVAULT_DB_PORT=5432

# Celery / Message Broker (RabbitMQ)
export DEVICEVAULT_BROKER_URL=amqp://guest:guest@localhost:5672//

# Redis (for locks and result streams)
export DEVICEVAULT_REDIS_URL=redis://localhost:6379/1

# Celery result backend
export DEVICEVAULT_RESULT_BACKEND=redis://localhost:6379/1

# RabbitMQ management API (for Flower monitoring)
export DEVICEVAULT_BROKER_API=http://guest:guest@localhost:15672/api/

# Result stream names (Redis Streams for worker-to-django communication)
export DEVICEVAULT_RESULTS_STREAM=device:results
export DEVICEVAULT_STORAGE_RESULTS_STREAM=storage:results

# Logging
export DEVICEVAULT_LOG_LEVEL=INFO
```

### Required Services for Full Operation

DeviceVault requires the following services when running with Celery workers:

1. **RabbitMQ** (or Redis) — Message broker for Celery tasks
   - Default: `amqp://guest:guest@localhost:5672//`
   - Management UI: `http://localhost:15672` (default credentials: guest/guest)

2. **Redis** — Distributed locking and result streams
   - Default: `redis://localhost:6379`
   - Database 1 is used by default for results

3. **Database** — SQLite (default), PostgreSQL, or MySQL
   - Default: `devicevault.sqlite3` in backend directory

To start RabbitMQ and Redis quickly:

```bash
# Using the dev-env docker-compose
docker compose -f dev-env/docker-compose.yaml up -d rabbitmq redis

# Or individual commands (if Docker is installed)
docker run -d -p 5672:5672 -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=guest \
  -e RABBITMQ_DEFAULT_PASS=guest \
  rabbitmq:management

docker run -d -p 6379:6379 redis:7
```

## Admin Pages

1. **Dashboard** - Statistics, charts, and recent activity
2. **Devices** - Device management with filtering
3. **Device Types** - Manage device type categories
4. **Backup Methods** - View available backup method plugins
5. **Credentials** - Credential storage and management
6. **Backup Locations** - Configure storage backends
7. **Retention Policies** - Define backup retention rules

## Docker-Based Setup

### Using Docker Compose

For containerized deployment with automatic service orchestration:

```bash
cd docker-build

# Build all images
make build

# Start all services (nginx, django, postgres, redis, flower)
make up

# Stop all services
make down

# Restart services
make restart

# View logs
make logs

# Celery-specific
make logs-celery
make logs-django

# Run Django management commands in container
make migrate
make makemigrations
make shell
```

Available Makefile targets:
```
build              - Build all Docker images
up                 - Start all services
down               - Stop all services
restart            - Restart all services
scale-celery       - Scale Celery workers (usage: make scale-celery n=5)
migrate            - Run Django migrations
makemigrations     - Create new migrations
shell              - Open Django shell
build-frontend     - Build frontend for production
watch-frontend     - Watch and rebuild frontend on changes
logs               - View logs (all services)
logs-celery        - View Celery worker logs
logs-django        - View Django logs
clean-volumes      - Remove volumes (full reset)
prune              - Remove unused Docker resources
clean-build        - Clean Docker build cache
```

### Docker Services

The `docker-build/docker-compose.yaml` includes:

- **nginx** — Reverse proxy and static file server
- **django** — Django application server
- **postgres** — PostgreSQL database (default for Docker)
- **redis** — Redis for caching and result storage
- **flower** — Celery task monitoring UI (optional, commented out by default)

## Troubleshooting

### View Logs

```bash
# View all logs
./devicevault.sh logs

# View specific service logs
./devicevault.sh logs backend
./devicevault.sh logs frontend
./devicevault.sh logs backup-worker
./devicevault.sh logs storage-worker

# Follow logs in real-time (Docker)
cd docker-build && make logs
```

### Restart Services

```bash
# Using management script
./devicevault.sh restart

# Or individually stop and start
./devicevault.sh stop
./devicevault.sh start

# Using Docker
cd docker-build && make restart
```

### Database Issues

```bash
# Run migrations (local development)
cd backend
source ../.venv/bin/activate
python manage.py migrate --run-syncdb

# Run migrations (Docker)
cd docker-build && make migrate
```

### Worker Connection Issues

If workers are not processing tasks:

1. **Check RabbitMQ/Redis connectivity**:
   ```bash
   # Test RabbitMQ
   rabbitmq-diagnostics -q ping
   
   # Test Redis
   redis-cli ping
   ```

2. **Check Redis streams** (worker-to-django communication):
   ```bash
   # View pending backup results
   redis-cli -n 1 XREVRANGE device:results + - COUNT 10
   
   # View pending storage results
   redis-cli -n 1 XREVRANGE storage:results + - COUNT 10
   ```

3. **Verify workers are running**:
   ```bash
   ./devicevault.sh status
   ```

### Celery / Flower Issues

- **Flower not showing tasks**: Ensure `DEVICEVAULT_BROKER_API` points to RabbitMQ management API (port 15672, not 5672)
- **Workers not receiving tasks**: Check queue names match device collection group configurations
- **Tasks stuck in queue**: Check worker logs: `./devicevault.sh logs backup-worker`

## Running in Production

This project is developed for local and container-based development. For production deployments follow these concise notes:

- Build the frontend with Quasar and serve the compiled files from nginx.
	```bash
	# from repo root
	cd frontend
	npm ci
	npm run build
	# Quasar produces a `dist/` tree (commonly `dist/spa` for SPA mode).
	```

- Build and run a WSGI server for Django (recommended: `gunicorn`) and ensure static files are collected.
	```bash
	# in a Python virtualenv on the host or container
	pip install -r backend/requirements.txt gunicorn
	cd backend
	python manage.py collectstatic --noinput
	gunicorn --bind 0.0.0.0:8000 devicevault.wsgi:application
	```

- Nginx should serve the frontend build directory as static files and reverse-proxy API and admin endpoints to the Django WSGI server.
	Example (minimal) nginx site config:
	```nginx
	server {
			listen 80;
			server_name example.com;

			root /opt/devicevault/frontend/dist/spa; # adjust to actual quasar dist path
			index index.html;

			location /api/ {
					proxy_pass http://127.0.0.1:8000/api/;
					proxy_set_header Host $host;
					proxy_set_header X-Real-IP $remote_addr;
					proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
					proxy_set_header X-Forwarded-Proto $scheme;
			}

			location /admin/ {
					proxy_pass http://127.0.0.1:8000/admin/;
					proxy_set_header Host $host;
					proxy_set_header X-Real-IP $remote_addr;
					proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
					proxy_set_header X-Forwarded-Proto $scheme;
			}

			# Serve the SPA (fallback to index.html for history mode)
			location / {
					try_files $uri $uri/ /index.html;
			}
	}
	```

- Notes and recommendations:
	- Run Django behind a process manager (systemd, supervisord) or container orchestrator.
	- Use HTTPS in front of nginx (Let's Encrypt + certbot recommended).
	- If serving static media from object storage (S3/GCS), configure storage backends in `backend/config/config.yaml` and in `backend/settings.py` as needed.
	- Verify `frontend/quasar.config.js` for router mode (`history`) — nginx fallback to `index.html` is required for SPA routes.
