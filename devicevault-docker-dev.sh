#!/bin/bash

# DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
# Copyright (C) 2026, Slinky Software
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/dev-env/docker-compose.docker-dev.yaml"
DOCKERFILE_BACKEND="$SCRIPT_DIR/dev-env/Dockerfile.backend-dev"
ORCHESTRATOR_SCRIPT="$SCRIPT_DIR/dev-env/scripts/docker-dev-orchestrator.sh"

PROJECT_NAME="devicevault-docker-dev"
VAR_ROOT="$SCRIPT_DIR/var/docker-dev"
CONFIG_DIR="$VAR_ROOT/config"
CONFIG_FILE="$CONFIG_DIR/backend-config.yaml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

function print_status() {
    echo -e "${GREEN}[DeviceVault Docker Dev]${NC} $1"
}

function print_error() {
    echo -e "${RED}[DeviceVault Docker Dev]${NC} $1"
}

function print_warning() {
    echo -e "${YELLOW}[DeviceVault Docker Dev]${NC} $1"
}

function check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        print_error "Docker is not installed or not in PATH"
        return 1
    fi

    if ! docker compose version >/dev/null 2>&1; then
        print_error "Docker Compose plugin is not available"
        return 1
    fi

    return 0
}

function verify_required_files() {
    local missing=0
    for path in "$COMPOSE_FILE" "$DOCKERFILE_BACKEND" "$ORCHESTRATOR_SCRIPT"; do
        if [ ! -f "$path" ]; then
            print_error "Missing required file: $path"
            missing=1
        fi
    done

    if [ "$missing" -ne 0 ]; then
        return 1
    fi
}

function ensure_var_layout() {
    mkdir -p \
        "$CONFIG_DIR" \
        "$VAR_ROOT/logs/orchestrator" \
        "$VAR_ROOT/logs/collector-1" \
        "$VAR_ROOT/logs/collector-2" \
        "$VAR_ROOT/logs/storage-worker" \
        "$VAR_ROOT/logs/flower" \
        "$VAR_ROOT/logs/frontend" \
        "$VAR_ROOT/postgres/data" \
        "$VAR_ROOT/redis/data" \
        "$VAR_ROOT/rabbitmq/data" \
        "$VAR_ROOT/frontend/node_modules" \
        "$VAR_ROOT/storage/git" \
        "$VAR_ROOT/storage/fs"

    if [ ! -f "$CONFIG_FILE" ]; then
        cat > "$CONFIG_FILE" <<'EOF'
database:
  engine: postgres
  name: devicevault
  user: devicevault
  password: devicevault
  host: db
  port: '5432'

timezone: Australia/Sydney

local_admin:
  username: admin
  encrypted_password: ''

auth:
  type: Local
  local_enabled: true

redis:
  url: redis://redis:6379/1

celery:
  broker: amqp://guest:guest@rabbitmq:5672//
  result_backend: redis://redis:6379/1
  broker_api: http://guest:guest@rabbitmq:15672/api/

results_stream: device:results
storage_results_stream: storage:results
EOF
        print_status "Created default docker-dev backend config: $CONFIG_FILE"
    fi
}

function compose() {
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

function start() {
    check_docker
    verify_required_files
    ensure_var_layout

    print_status "Starting containerized DeviceVault development stack..."
    compose up -d --build

    print_status "Started successfully."
    print_status "Frontend (Vite): http://localhost:9000"
    print_status "Backend API: http://localhost:8000"
    print_status "Flower: http://localhost:5555"
    print_status "RabbitMQ Management: http://localhost:15672"
    print_status "PostgreSQL: localhost:5432"
    print_status "Redis: localhost:6379"
    print_status "RabbitMQ AMQP: localhost:5672"
}

function stop() {
    check_docker
    verify_required_files

    print_status "Stopping containerized DeviceVault development stack..."
    compose down
    print_status "Stopped."
}

function restart() {
    stop
    start
}

function reset() {
    check_docker
    verify_required_files

    echo ""
    print_warning "This will delete docker-dev runtime data under: $VAR_ROOT"
    print_warning "This includes database, Redis, RabbitMQ, logs, storage data, and frontend node_modules."
    read -r -p "Type YES to continue: " confirmation
    if [ "$confirmation" != "YES" ]; then
        print_status "Reset cancelled."
        return 0
    fi

    print_status "Resetting docker-dev stack (containers, networks, and persisted runtime data)..."
    compose down --volumes --remove-orphans

    if [ -d "$VAR_ROOT" ]; then
        print_status "Clearing persisted runtime directories under $VAR_ROOT..."
        docker run --rm -v "$VAR_ROOT:/var-root" alpine:3.20 sh -c \
            "rm -rf /var-root/postgres /var-root/redis /var-root/rabbitmq /var-root/logs /var-root/storage /var-root/frontend/node_modules"
    fi

    ensure_var_layout
    print_status "Reset complete. Existing config retained at: $CONFIG_FILE"
}

function status() {
    check_docker
    verify_required_files
    compose ps -a
}

function logs() {
    check_docker
    verify_required_files

    local follow=0
    local service=""

    while [ "$#" -gt 0 ]; do
        case "$1" in
            -f|--follow)
                follow=1
                ;;
            *)
                if [ -n "$service" ]; then
                    print_error "Only one service name can be passed to logs"
                    return 1
                fi
                service="$1"
                ;;
        esac
        shift
    done

    local compose_args=(logs --tail=100)
    if [ "$follow" -eq 1 ]; then
        compose_args+=(--follow)
    fi

    if [ -z "$service" ]; then
        compose "${compose_args[@]}"
    else
        compose "${compose_args[@]}" "$service"
    fi
}

function usage() {
    echo "DeviceVault Docker Development Script"
    echo ""
    echo "Usage: $0 {start|stop|restart|reset|status|logs [-f|--follow] [service]}"
    echo ""
    echo "Commands:"
    echo "  start     Build images and start all docker-dev services"
    echo "  stop      Stop and remove all docker-dev containers"
    echo "  restart   Restart the docker-dev stack"
    echo "  reset     Stop stack and delete persisted runtime data (keeps config)"
    echo "  status    Show container status"
    echo "  logs      Show logs (optionally specify a service); add -f to follow"
    echo ""
    echo "Available services for logs:"
    echo "  db, redis, rabbitmq, orchestrator, frontend,"
    echo "  collector-1, collector-2, storage-worker, flower"
    echo ""
    echo "Persistent data is stored under: $VAR_ROOT"
}

case "${1:-}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    reset)
        reset
        ;;
    status)
        status
        ;;
    logs)
        logs "${@:2}"
        ;;
    *)
        usage
        exit 1
        ;;
esac

exit 0
