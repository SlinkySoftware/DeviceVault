**Celery Setup**

This document describes how to run the Celery workers and Flower for DeviceVault, the relevant configuration, and the recommended local Docker Compose services used for the broker/result store and Redis.

**Files**:
- **`backend/celery_app.py`**: centralized Celery application and connection config (preferred import point).
- **`backend/devicevault_worker.py`**: the worker task implementation (`device.collect`) — worker is DB-agnostic and publishes results to a Redis Stream.
- **`backend/devices/management/commands/consume_device_results.py`**: Django management command that consumes Redis Stream `device:results` and persists `DeviceBackupResult` rows.

Configuration sources (in order of precedence):
- Django settings (`backend/devicevault/settings.py`) — used when running under Django.
- Environment variables:
  - `DEVICEVAULT_BROKER_URL` — Celery broker URL (AMQP or Redis). Default: `amqp://guest:guest@localhost:5672//` (RabbitMQ).
  - `DEVICEVAULT_RESULT_BACKEND` — Celery result backend URL. Defaults to the broker URL.
  - `DEVICEVAULT_BROKER_API` — RabbitMQ management API URL for Flower. Default: `http://guest:guest@localhost:15672/api/`. Required for Flower to query broker statistics.
  - `DEVICEVAULT_REDIS_URL` — Redis URL used for locks and Streams. Default: `redis://localhost:6379/1`.
  - `DEVICEVAULT_RESULTS_STREAM` — Redis Stream name where workers XADD results. Default: `device:results`.

Recommended defaults for local development (provided by `dev-env/docker-compose.yaml`):
- RabbitMQ service on `localhost:5672` (AMQP) — recommended broker URL: `amqp://guest:guest@localhost:5672//`.
- Redis service on `redis:6379` — recommended Redis URL: `redis://redis:6379/1`.

Start required services using the local compose file (Dev environment):

```bash
docker compose -f dev-env/docker-compose.yaml up -d rabbitmq redis
```

Start a Celery worker (uses the centralized `celery_app` module):

```bash
# Activate virtualenv, change into backend, then run celery from PATH
source .venv/bin/activate
cd backend
export DEVICEVAULT_BROKER_URL=amqp://guest:guest@localhost:5672//
export DEVICEVAULT_REDIS_URL=redis://redis:6379/1
celery -A celery_app worker -Q default,collector.group.dmz,collector.group.test -l info --concurrency=4
```

Notes:
- Replace `collector.group.dmz,collector.group.test` with the group queue names used in your installation (the queue name convention is `collector.group.<rabbitmq_queue_name>` which are defined on the collector group front-end configuration).
- You can also start the worker as `-A devicevault_worker` (the module keeps compatibility), but `-A celery_app` is recommended because it centralizes broker settings.

Start Flower to inspect queues/tasks (optional):

```bash
# Activate virtualenv, change into backend, then run Flower from PATH
source .venv/bin/activate
cd backend
celery -A celery_app flower --broker-api=http://guest:guest@localhost:15672/api/ --port=5555
# then open http://localhost:5555
```

**Important:** The `--broker-api` argument must be passed to Flower on the command line to tell it where to find the RabbitMQ management API. Without this, Flower will attempt HTTP requests to the AMQP port (5672) instead of the management HTTP API (15672).

Orchestration notes (recommended architecture):
- Workers must not write to the main DB. They run plugins, return structured results, and publish those results to a Redis Stream.
- The Django orchestrator / consumer reads from Redis Stream `device:results` and persists `DeviceBackupResult` rows using the `consume_device_results` management command.

Run the consumer (Django process) to persist results:

```bash
# Activate virtualenv and change into backend, then run Django management command
source .venv/bin/activate
cd backend
python manage.py consume_device_results
```

Troubleshooting
- If tasks are not being received, verify:
  - Broker URL is reachable from the host where the worker runs.
  - Ensure you `cd backend` before starting the worker so the `celery_app` module is importable.
  - Queue names match (`collector.group.<id>`).
- If results are not persisting, check Redis stream contents:

```bash
redis-cli -n 1 XREVRANGE device:results + - COUNT 10
```

Security & production notes
- Use secure credentials and network restrictions for RabbitMQ and Redis in production.
- Consider running Celery workers with process supervision (systemd/container orchestrator) and configuring monitoring (Prometheus/Health checks/Flower).
