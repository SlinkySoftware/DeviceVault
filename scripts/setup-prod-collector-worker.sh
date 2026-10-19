#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/production-common.sh"

ROLE_NAME="collector-worker"
CONFIG_DIR="/etc/devicevault/${ROLE_NAME}"
DEPLOY_ROOT="/opt/devicevault/deploy"
DEPLOY_DIR="${DEPLOY_ROOT}/${ROLE_NAME}"
SOURCE_DIR=""
REPO_URL="$PRODUCTION_DEFAULT_REPO_URL"
SOURCE_REF=""
IMAGE_TAG=""
APP_IMAGE=""
SKIP_START=0
FORCE=0

ORCHESTRATOR_HOST="node1.internal"
TIMEZONE="${TZ:-Australia/Sydney}"

POSTGRES_DB="devicevault"
POSTGRES_USER="devicevault"
POSTGRES_PASSWORD=""

RABBITMQ_DEFAULT_USER="devicevault"
RABBITMQ_DEFAULT_PASS=""

DEVICEVAULT_COLLECTOR_QUEUES="collector.group.default"
DEVICEVAULT_COLLECTOR_CONCURRENCY="4"
DEVICEVAULT_WORKER_REPLICAS="1"

usage() {
    cat <<'EOF'
Usage: setup-prod-collector-worker.sh [options]

Options:
  --orchestrator-host <name>        Orchestrator hostname used for DB, Redis, and RabbitMQ endpoints.
  --config-dir <path>               Configuration directory (default: /etc/devicevault/collector-worker)
  --deploy-root <path>              Deployment asset root (default: /opt/devicevault/deploy)
  --source-dir <path>               Source checkout to copy compose assets from.
  --repo-url <url>                  Repository URL to clone when no checkout is available.
  --source-ref <ref>                Branch or tag to clone when a checkout must be created.
  --app-image <ref>                 Application image reference to deploy.
  --image-tag <tag>                 Tag to derive the app image from when not supplied.
  --db-password <value>             PostgreSQL password.
  --rabbitmq-user <value>           RabbitMQ username.
  --rabbitmq-password <value>       RabbitMQ password.
  --collector-queues <csv>          Collector queue list handled by this node.
  --collector-concurrency <n>       Per-container Celery concurrency (default: 4).
  --replicas <n>                    Number of collector-worker containers to run (default: 1).
  --skip-start                      Prepare files but do not run docker compose up.
  --force                           Regenerate config.yaml.
  --help                            Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --orchestrator-host)
            ORCHESTRATOR_HOST="$2"
            shift 2
            ;;
        --config-dir)
            CONFIG_DIR="$2"
            shift 2
            ;;
        --deploy-root)
            DEPLOY_ROOT="$2"
            shift 2
            ;;
        --source-dir)
            SOURCE_DIR="$2"
            shift 2
            ;;
        --repo-url)
            REPO_URL="$2"
            shift 2
            ;;
        --source-ref)
            SOURCE_REF="$2"
            shift 2
            ;;
        --app-image)
            APP_IMAGE="$2"
            shift 2
            ;;
        --image-tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --db-password)
            POSTGRES_PASSWORD="$2"
            shift 2
            ;;
        --rabbitmq-user)
            RABBITMQ_DEFAULT_USER="$2"
            shift 2
            ;;
        --rabbitmq-password)
            RABBITMQ_DEFAULT_PASS="$2"
            shift 2
            ;;
        --collector-queues)
            DEVICEVAULT_COLLECTOR_QUEUES="$2"
            shift 2
            ;;
        --collector-concurrency)
            DEVICEVAULT_COLLECTOR_CONCURRENCY="$2"
            shift 2
            ;;
        --replicas)
            DEVICEVAULT_WORKER_REPLICAS="$2"
            shift 2
            ;;
        --skip-start)
            SKIP_START=1
            shift
            ;;
        --force)
            FORCE=1
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

DEPLOY_DIR="${DEPLOY_ROOT}/${ROLE_NAME}"
ENV_FILE="${CONFIG_DIR}/.env"

production_require_root
production_require_commands docker git openssl

mkdir -p "$CONFIG_DIR"
chmod 750 "$CONFIG_DIR"

production_load_env_file "$ENV_FILE"
production_load_env_file "$DEPLOY_DIR/compose.env"

SOURCE_DIR="$(production_ensure_source_dir "$SOURCE_DIR" "/opt/devicevault" "$REPO_URL" "$SOURCE_REF")"
IMAGE_TAG="${IMAGE_TAG:-$(production_derive_image_tag "$SOURCE_DIR")}"
APP_IMAGE="${APP_IMAGE:-devicevault/app:${IMAGE_TAG}}"
RABBITMQ_DEFAULT_PASS="${RABBITMQ_DEFAULT_PASS:-$(production_random_base64 24)}"

production_prompt ORCHESTRATOR_HOST "Orchestrator hostname" "$ORCHESTRATOR_HOST"
production_prompt TIMEZONE "Display timezone" "$TIMEZONE"
production_prompt APP_IMAGE "Application image reference" "$APP_IMAGE"
production_prompt POSTGRES_PASSWORD "PostgreSQL password" "${POSTGRES_PASSWORD:-}" 1
production_prompt RABBITMQ_DEFAULT_USER "RabbitMQ username" "$RABBITMQ_DEFAULT_USER"
production_prompt RABBITMQ_DEFAULT_PASS "RabbitMQ password" "$RABBITMQ_DEFAULT_PASS" 1
production_prompt DEVICEVAULT_COLLECTOR_QUEUES "Collector queues for this node" "$DEVICEVAULT_COLLECTOR_QUEUES"
production_prompt DEVICEVAULT_COLLECTOR_CONCURRENCY "Per-container collector concurrency" "$DEVICEVAULT_COLLECTOR_CONCURRENCY"
production_prompt DEVICEVAULT_WORKER_REPLICAS "Number of collector worker containers" "$DEVICEVAULT_WORKER_REPLICAS"

cat >"$ENV_FILE" <<EOF
POSTGRES_DB=$POSTGRES_DB
POSTGRES_USER=$POSTGRES_USER
POSTGRES_PASSWORD=$POSTGRES_PASSWORD

DEVICEVAULT_CONFIG=$CONFIG_DIR/config.yaml
DEBUG=False
TZ=$TIMEZONE

DEVICEVAULT_DB_ENGINE=postgres
DEVICEVAULT_DB_NAME=$POSTGRES_DB
DEVICEVAULT_DB_USER=$POSTGRES_USER
DEVICEVAULT_DB_PASSWORD=$POSTGRES_PASSWORD
DEVICEVAULT_DB_HOST=$ORCHESTRATOR_HOST
DEVICEVAULT_DB_PORT=5432

DEVICEVAULT_BROKER_URL=amqp://$RABBITMQ_DEFAULT_USER:$RABBITMQ_DEFAULT_PASS@$ORCHESTRATOR_HOST:5672//
DEVICEVAULT_REDIS_URL=redis://$ORCHESTRATOR_HOST:6379/1
DEVICEVAULT_RESULT_BACKEND=redis://$ORCHESTRATOR_HOST:6379/1
DEVICEVAULT_BROKER_API=http://$RABBITMQ_DEFAULT_USER:$RABBITMQ_DEFAULT_PASS@$ORCHESTRATOR_HOST:15672/api/
DEVICEVAULT_RESULTS_STREAM=device:results
DEVICEVAULT_STORAGE_RESULTS_STREAM=storage:results

DEVICEVAULT_COLLECTOR_QUEUES=$DEVICEVAULT_COLLECTOR_QUEUES
DEVICEVAULT_COLLECTOR_CONCURRENCY=$DEVICEVAULT_COLLECTOR_CONCURRENCY
DEVICEVAULT_WORKER_REPLICAS=$DEVICEVAULT_WORKER_REPLICAS
EOF
chmod 600 "$ENV_FILE"

if [[ ! -f "$CONFIG_DIR/config.yaml" || "$FORCE" == "1" ]]; then
    cat >"$CONFIG_DIR/config.yaml" <<EOF
timezone: $TIMEZONE

local_admin:
  username: collector-worker
  encrypted_password: ''

auth:
  type: Local
  local_enabled: true

encryption:
  enabled: false
  key_provider: local
  keys: {}
  chunk_size_bytes: 1048576
  allow_plaintext_fallback: true
EOF
    chmod 600 "$CONFIG_DIR/config.yaml"
fi

production_install_compose_asset "$SOURCE_DIR/docker-build/docker-compose.prod-collector-worker.yaml" "$DEPLOY_DIR"
cat >"$DEPLOY_DIR/compose.env" <<EOF
COMPOSE_PROJECT_NAME=devicevault-collector-worker
DEVICEVAULT_ENV_FILE=$ENV_FILE
DEVICEVAULT_CONFIG_DIR=$CONFIG_DIR
DEVICEVAULT_APP_IMAGE=$APP_IMAGE
EOF
chmod 600 "$DEPLOY_DIR/compose.env"

if [[ "$SKIP_START" == "0" ]]; then
    production_compose "$DEPLOY_DIR" up -d --scale collector-worker="$DEVICEVAULT_WORKER_REPLICAS"
fi

echo ""
echo "=========================================="
echo "DeviceVault Production - Collector Worker"
echo "=========================================="
echo "Config directory: $CONFIG_DIR"
echo "Deploy assets:    $DEPLOY_DIR"
echo "App image:        $APP_IMAGE"
echo "Queues:           $DEVICEVAULT_COLLECTOR_QUEUES"
echo "Replicas:         $DEVICEVAULT_WORKER_REPLICAS"
echo ""
if [[ "$SKIP_START" == "1" ]]; then
    echo "Services were not started (--skip-start)."
else
    echo "Collector workers deployed with docker compose."
fi
echo "Run status:"
echo "  docker compose --env-file $DEPLOY_DIR/compose.env -f $DEPLOY_DIR/compose.yaml ps"
