# DeviceVault developer entry point. Every target runs in a container, so the
# only host requirements are Docker and make. CI pipelines should call these
# targets rather than duplicating the commands.

DEV_IMAGE ?= devicevault-dev
NODE_IMAGE ?= node:24-alpine
IMAGE_TAG ?= latest

# Containers run as you, so files they write to the tree are yours.
export DV_UID := $(shell id -u)
export DV_GID := $(shell id -g)

DOCKER_RUN = docker run --rm -v $(CURDIR):/workspace -u $(DV_UID):$(DV_GID) -e HOME=/tmp
PY = $(DOCKER_RUN) -w /workspace $(DEV_IMAGE)
NODE = $(DOCKER_RUN) -w /workspace/frontend $(NODE_IMAGE)
DEV_COMPOSE = docker compose -f deploy/dev/compose.yaml

PY_PACKAGES = protocol worker receiver orchestrator

FRONTEND_DEPS = frontend/node_modules/.package-lock.json

.PHONY: help dev-image lock lint fmt test test-postgres check frontend-install frontend-lint frontend-test frontend-build \
	images version set-version dev-up dev-down dev-start dev-stop dev-status dev-reset dev-ps dev-logs dev-seed dev-approve

help:
	@echo "Quality:   lint fmt test test-postgres frontend-lint frontend-test check"
	@echo "Deps:      lock dev-image frontend-install"
	@echo "Build:     frontend-build images (IMAGE_TAG=$(IMAGE_TAG))"
	@echo "Release:   version set-version V=X.Y.Z"
	@echo "Dev stack: dev-up dev-down dev-start dev-stop dev-status dev-reset dev-ps dev-logs dev-seed dev-approve"

dev-image:
	docker build -q -f docker/Dockerfile --target dev -t $(DEV_IMAGE) .

lock: dev-image
	$(PY) uv lock

version:
	@cat VERSION

# VERSION is the source; every package's metadata (and so uv.lock) carries a copy.
set-version: dev-image
	@echo '$(V)' | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$$' \
		|| { echo 'usage: make set-version V=X.Y.Z' >&2; exit 1; }
	echo '$(V)' > VERSION
	$(PY) sed -i -E 's/^version = ".*"/version = "$(V)"/' $(PY_PACKAGES:%=%/pyproject.toml)
	$(NODE) npm version --no-git-tag-version --allow-same-version '$(V)'
	$(PY) uv lock

lint: dev-image
	$(PY) sh -c 'ruff check . && ruff format --check .'

fmt: dev-image
	$(PY) sh -c 'ruff check --fix . && ruff format .'

test: dev-image
	$(PY) sh -c 'set -e; for pkg in $(PY_PACKAGES); do (cd $$pkg && pytest); done'

# The orchestrator suite against PostgreSQL (the config search index is PostgreSQL-specific).
PG_TEST = devicevault-test-postgres
test-postgres: dev-image
	docker rm -f $(PG_TEST) >/dev/null 2>&1 || true
	docker run -d --name $(PG_TEST) -e POSTGRES_USER=devicevault -e POSTGRES_PASSWORD=test-only \
		-e POSTGRES_DB=devicevault postgres:18-alpine >/dev/null
	until docker exec $(PG_TEST) pg_isready -q -U devicevault -h 127.0.0.1; do sleep 1; done
	$(DOCKER_RUN) --network container:$(PG_TEST) -e DV_TEST_POSTGRES_HOST=127.0.0.1 \
		-w /workspace/orchestrator $(DEV_IMAGE) pytest -q; \
		status=$$?; docker rm -f $(PG_TEST) >/dev/null; exit $$status

check: lint test test-postgres frontend-lint frontend-test frontend-build

# Reinstall only when the lockfile changes.
$(FRONTEND_DEPS): frontend/package.json frontend/package-lock.json
	$(NODE) npm ci --no-audit --no-fund

frontend-install: $(FRONTEND_DEPS)

frontend-lint: frontend-install
	$(NODE) sh -c 'npm run -s lint && npm run -s typecheck'

frontend-test: frontend-install
	$(NODE) npm run -s test

frontend-build: frontend-install
	$(NODE) npx quasar build

images:
	docker build -f docker/Dockerfile --target orchestrator -t devicevault-orchestrator:$(IMAGE_TAG) .
	docker build -f docker/Dockerfile --target worker -t devicevault-worker:$(IMAGE_TAG) .
	docker build -f docker/Dockerfile --target receiver -t devicevault-receiver:$(IMAGE_TAG) .
	docker build -f docker/web.Dockerfile -t devicevault-web:$(IMAGE_TAG) .

dev-up: dev-image
	$(DEV_COMPOSE) up -d

dev-down:
	$(DEV_COMPOSE) down

dev-start: dev-up

dev-stop: dev-down

# Container state plus the API health probe (the process is serving and the database is reachable).
dev-status:
	$(DEV_COMPOSE) ps -a
	@printf "platform: "; curl -fsS --max-time 5 "http://localhost:$${DV_DEV_API_PORT:-8000}/api/health/" || echo "unavailable"; echo

dev-reset:
	$(DEV_COMPOSE) down --volumes --remove-orphans

dev-ps:
	$(DEV_COMPOSE) ps -a

dev-logs:
	$(DEV_COMPOSE) logs --follow --tail=100 $(SERVICE)

dev-seed:
	$(DEV_COMPOSE) exec api dv-orchestrator manage seed_demo
	$(MAKE) dev-approve

# Approve the dev stack's workers (they register as pending on first start).
dev-approve:
	$(DEV_COMPOSE) exec api dv-orchestrator manage approve_worker 'collector-*' --role collector --all-groups
	$(DEV_COMPOSE) exec api dv-orchestrator manage approve_worker storage-1 --role storage --all-targets
	$(DEV_COMPOSE) exec api dv-orchestrator manage approve_worker receiver-1 --role receiver
