# Project variables
COMPOSE_FILE=docker-compose.yaml
GIT_BRANCH ?= master

# Core orchestration
build:
	docker compose -f $(COMPOSE_FILE) build --pull

up:
	docker compose -f $(COMPOSE_FILE) up -d

down:
	docker compose -f $(COMPOSE_FILE) down

restart:
	docker compose -f $(COMPOSE_FILE) down && docker compose -f $(COMPOSE_FILE) up -d

# Celery scaling
scale-celery:
	docker compose -f $(COMPOSE_FILE) up -d --scale celery=$(n)

# Django utilities in containers
migrate:
	docker compose -f $(COMPOSE_FILE) run --rm django python3 manage.py migrate

makemigrations:
	docker compose -f $(COMPOSE_FILE) run --rm django python3 manage.py makemigrations

shell:
	docker compose -f $(COMPOSE_FILE) run --rm django /opt/venv/bin/python3 manage.py shell

# Frontend utilities
build-frontend:
	docker compose -f $(COMPOSE_FILE) run --rm vue npm run build

watch-frontend:
	docker compose -f $(COMPOSE_FILE) run --rm vue npm run dev

# Debugging
logs:
	docker compose -f $(COMPOSE_FILE) logs -f

logs-celery:
	docker compose -f $(COMPOSE_FILE) logs -f celery

logs-django:
	docker compose -f $(COMPOSE_FILE) logs -f django

# Maintenance
clean-volumes:
	docker compose -f $(COMPOSE_FILE) down -v

prune:
	docker system prune -af --volumes

# Help (auto documents available commands)
help:
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:' $(MAKEFILE_LIST) | awk -F: '{print "  " $$1}'
