# DeviceVault developer entry point. Every target runs in a container, so the
# only host requirements are Docker and make. CI pipelines should call these
# targets rather than duplicating the commands.

DEV_IMAGE ?= devicevault-dev
NODE_IMAGE ?= node:24-bookworm-slim

DOCKER_RUN = docker run --rm -v $(CURDIR):/workspace -u $$(id -u):$$(id -g) -e HOME=/tmp
PY = $(DOCKER_RUN) -w /workspace $(DEV_IMAGE)
PY_ORCH = $(DOCKER_RUN) -w /workspace/orchestrator $(DEV_IMAGE)
NODE = $(DOCKER_RUN) -w /workspace/frontend $(NODE_IMAGE)

.PHONY: help dev-image lock lint fmt test check frontend-install frontend-build \
	dev-up dev-down dev-restart dev-reset dev-status dev-logs

help:
	@echo "Quality:   lint fmt test check"
	@echo "Deps:      lock dev-image frontend-install"
	@echo "Build:     frontend-build"
	@echo "Dev stack: dev-up dev-down dev-restart dev-reset dev-status dev-logs"

dev-image:
	docker build -q -t $(DEV_IMAGE) -f dev-env/Dockerfile.backend-dev .

lock: dev-image
	$(PY) uv lock

lint: dev-image
	$(PY) sh -c 'ruff check . && ruff format --check .'

fmt: dev-image
	$(PY) sh -c 'ruff check --fix . && ruff format .'

test: dev-image
	$(PY_ORCH) pytest

check: lint test frontend-build

frontend-install:
	$(NODE) npm ci --no-audit --no-fund

frontend-build: frontend-install
	$(NODE) npx quasar build

dev-up:
	./devicevault-docker-dev.sh start

dev-down:
	./devicevault-docker-dev.sh stop

dev-restart:
	./devicevault-docker-dev.sh restart

dev-reset:
	./devicevault-docker-dev.sh reset

dev-status:
	./devicevault-docker-dev.sh status

dev-logs:
	./devicevault-docker-dev.sh logs
