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

PY_PACKAGES = protocol worker orchestrator

FRONTEND_DEPS = frontend/node_modules/.package-lock.json

.PHONY: help dev-image lock lint fmt test check frontend-install frontend-lint frontend-test frontend-build \
	images dev-up dev-down dev-reset dev-ps dev-logs dev-seed dev-approve

help:
	@echo "Quality:   lint fmt test frontend-lint frontend-test check"
	@echo "Deps:      lock dev-image frontend-install"
	@echo "Build:     frontend-build images (IMAGE_TAG=$(IMAGE_TAG))"
	@echo "Dev stack: dev-up dev-down dev-reset dev-ps dev-logs dev-seed dev-approve"

dev-image:
	docker build -q -f docker/Dockerfile --target dev -t $(DEV_IMAGE) .

lock: dev-image
	$(PY) uv lock

lint: dev-image
	$(PY) sh -c 'ruff check . && ruff format --check .'

fmt: dev-image
	$(PY) sh -c 'ruff check --fix . && ruff format .'

test: dev-image
	$(PY) sh -c 'set -e; for pkg in $(PY_PACKAGES); do (cd $$pkg && pytest); done'

check: lint test frontend-lint frontend-test frontend-build

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
	docker build -f docker/web.Dockerfile -t devicevault-web:$(IMAGE_TAG) .

dev-up: dev-image
	$(DEV_COMPOSE) up -d

dev-down:
	$(DEV_COMPOSE) down

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
	$(DEV_COMPOSE) exec api dv-orchestrator manage approve_worker storage-1 --role storage --backends fs git
