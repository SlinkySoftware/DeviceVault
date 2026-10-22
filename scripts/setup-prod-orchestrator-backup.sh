#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/production-common.sh"

ROLE_NAME="orchestrator-backup"
CONFIG_DIR="/etc/devicevault/${ROLE_NAME}"
DEPLOY_ROOT="/opt/devicevault/deploy"
DEPLOY_DIR="${DEPLOY_ROOT}/${ROLE_NAME}"
SOURCE_DIR=""
REPO_URL="$PRODUCTION_DEFAULT_REPO_URL"
SOURCE_REF=""
IMAGE_TAG=""
APP_IMAGE=""
NGINX_IMAGE=""
SKIP_START=0
FORCE=0

PRIMARY_HOST="node1.internal"
HOSTNAME_VALUE=""
TIMEZONE="${TZ:-Australia/Sydney}"
ADMIN_USERNAME="admin"
ALLOWED_HOSTS=""

POSTGRES_DB="devicevault"
POSTGRES_USER="devicevault"
POSTGRES_PASSWORD=""
POSTGRES_REPLICATION_USER="replicator"
POSTGRES_REPLICATION_PASSWORD=""

RABBITMQ_DEFAULT_USER="devicevault"
RABBITMQ_DEFAULT_PASS=""
RABBITMQ_ERLANG_COOKIE=""

DEVICEVAULT_SECRET_KEY=""
DEVICEVAULT_COLLECTOR_QUEUES="default"
DEVICEVAULT_LOCAL_COLLECTOR_CONCURRENCY="1"
DEVICEVAULT_STORAGE_QUEUES="storage.fs,storage.git"
DEVICEVAULT_LOCAL_STORAGE_CONCURRENCY="1"
DEVICEVAULT_STORAGE_HOST_PATH="/srv/devicevault/storage"
DEVICEVAULT_STORAGE_CONTAINER_PATH="/srv/devicevault/storage"

usage() {
    cat <<'EOF'
Usage: setup-prod-orchestrator-backup.sh [options]

Options:
  --primary-host <name>             Primary orchestrator hostname (default: node1.internal)
  --config-dir <path>               Configuration directory (default: /etc/devicevault/orchestrator-backup)
  --deploy-root <path>              Deployment asset root (default: /opt/devicevault/deploy)
  --source-dir <path>               Source checkout to copy compose assets from.
  --repo-url <url>                  Repository URL to clone when no checkout is available.
  --source-ref <ref>                Branch or tag to clone when a checkout must be created.
  --app-image <ref>                 Application image reference to deploy.
  --nginx-image <ref>               Nginx image reference to deploy.
  --image-tag <tag>                 Tag to derive image references from when not supplied.
  --hostname <name>                 Backup orchestrator hostname.
  --allowed-hosts <csv>             Django ALLOWED_HOSTS value.
  --db-password <value>             PostgreSQL password.
  --replication-password <value>    PostgreSQL replication password.
  --rabbitmq-user <value>           RabbitMQ username.
  --rabbitmq-password <value>       RabbitMQ password.
  --rabbitmq-cookie <value>         RabbitMQ Erlang cookie.
  --secret-key <value>              Django secret key.
  --collector-queues <csv>          Queue list for promoted local collector worker.
  --storage-queues <csv>            Queue list for promoted local storage worker.
  --storage-host-path <path>        Host path to mount for promoted storage-capable workers.
  --storage-container-path <path>   Container path for mounted storage.
  --skip-start                      Prepare files but do not run docker compose up.
  --force                           Regenerate config.yaml and support files.
  --help                            Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --primary-host)
            PRIMARY_HOST="$2"
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
        --nginx-image)
            NGINX_IMAGE="$2"
            shift 2
            ;;
        --image-tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --hostname)
            HOSTNAME_VALUE="$2"
            shift 2
            ;;
        --allowed-hosts)
            ALLOWED_HOSTS="$2"
            shift 2
            ;;
        --db-password)
            POSTGRES_PASSWORD="$2"
            shift 2
            ;;
        --replication-password)
            POSTGRES_REPLICATION_PASSWORD="$2"
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
        --rabbitmq-cookie)
            RABBITMQ_ERLANG_COOKIE="$2"
            shift 2
            ;;
        --secret-key)
            DEVICEVAULT_SECRET_KEY="$2"
            shift 2
            ;;
        --collector-queues)
            DEVICEVAULT_COLLECTOR_QUEUES="$2"
            shift 2
            ;;
        --storage-queues)
            DEVICEVAULT_STORAGE_QUEUES="$2"
            shift 2
            ;;
        --storage-host-path)
            DEVICEVAULT_STORAGE_HOST_PATH="$2"
            shift 2
            ;;
        --storage-container-path)
            DEVICEVAULT_STORAGE_CONTAINER_PATH="$2"
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
NGINX_IMAGE="${NGINX_IMAGE:-devicevault/nginx:${IMAGE_TAG}}"

HOSTNAME_VALUE="${HOSTNAME_VALUE:-$(hostname -f 2>/dev/null || hostname)}"
ALLOWED_HOSTS="${ALLOWED_HOSTS:-localhost,127.0.0.1,${HOSTNAME_VALUE}}"
POSTGRES_REPLICATION_PASSWORD="${POSTGRES_REPLICATION_PASSWORD:-$(production_random_base64 24)}"
RABBITMQ_DEFAULT_PASS="${RABBITMQ_DEFAULT_PASS:-$(production_random_base64 24)}"
RABBITMQ_ERLANG_COOKIE="${RABBITMQ_ERLANG_COOKIE:-$(production_random_base64 32)}"
DEVICEVAULT_SECRET_KEY="${DEVICEVAULT_SECRET_KEY:-$(production_random_base64 32)}"

production_prompt PRIMARY_HOST "Primary orchestrator hostname" "$PRIMARY_HOST"
production_prompt HOSTNAME_VALUE "Backup orchestrator hostname" "$HOSTNAME_VALUE"
production_prompt ALLOWED_HOSTS "Django ALLOWED_HOSTS (comma-separated)" "$ALLOWED_HOSTS"
production_prompt TIMEZONE "Display timezone" "$TIMEZONE"
production_prompt APP_IMAGE "Application image reference" "$APP_IMAGE"
production_prompt NGINX_IMAGE "Nginx image reference" "$NGINX_IMAGE"
production_prompt POSTGRES_PASSWORD "PostgreSQL password" "${POSTGRES_PASSWORD:-}" 1
production_prompt POSTGRES_REPLICATION_PASSWORD "PostgreSQL replication password" "$POSTGRES_REPLICATION_PASSWORD" 1
production_prompt RABBITMQ_DEFAULT_USER "RabbitMQ username" "$RABBITMQ_DEFAULT_USER"
production_prompt RABBITMQ_DEFAULT_PASS "RabbitMQ password" "$RABBITMQ_DEFAULT_PASS" 1
production_prompt RABBITMQ_ERLANG_COOKIE "RabbitMQ Erlang cookie" "$RABBITMQ_ERLANG_COOKIE" 1
production_prompt DEVICEVAULT_SECRET_KEY "Django secret key" "$DEVICEVAULT_SECRET_KEY" 1
production_prompt DEVICEVAULT_COLLECTOR_QUEUES "Promoted local collector worker queues" "$DEVICEVAULT_COLLECTOR_QUEUES"
production_prompt DEVICEVAULT_STORAGE_QUEUES "Promoted local storage worker queues" "$DEVICEVAULT_STORAGE_QUEUES"
production_prompt DEVICEVAULT_STORAGE_HOST_PATH "Host storage path for promoted local storage worker" "$DEVICEVAULT_STORAGE_HOST_PATH"
production_prompt DEVICEVAULT_STORAGE_CONTAINER_PATH "Container storage path for promoted local storage worker" "$DEVICEVAULT_STORAGE_CONTAINER_PATH"

cat >"$ENV_FILE" <<EOF
POSTGRES_DB=$POSTGRES_DB
POSTGRES_USER=$POSTGRES_USER
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_REPLICATION_USER=$POSTGRES_REPLICATION_USER
POSTGRES_REPLICATION_PASSWORD=$POSTGRES_REPLICATION_PASSWORD

RABBITMQ_DEFAULT_USER=$RABBITMQ_DEFAULT_USER
RABBITMQ_DEFAULT_PASS=$RABBITMQ_DEFAULT_PASS
RABBITMQ_ERLANG_COOKIE=$RABBITMQ_ERLANG_COOKIE

DEVICEVAULT_PRIMARY_HOST=$PRIMARY_HOST

DEVICEVAULT_SECRET_KEY=$DEVICEVAULT_SECRET_KEY
DEVICEVAULT_CONFIG=$CONFIG_DIR/config.yaml
DEBUG=False
ALLOWED_HOSTS=$ALLOWED_HOSTS
TZ=$TIMEZONE

DEVICEVAULT_DB_ENGINE=postgres
DEVICEVAULT_DB_NAME=$POSTGRES_DB
DEVICEVAULT_DB_USER=$POSTGRES_USER
DEVICEVAULT_DB_PASSWORD=$POSTGRES_PASSWORD
DEVICEVAULT_DB_HOST=postgres
DEVICEVAULT_DB_PORT=5432

DEVICEVAULT_BROKER_URL=amqp://$RABBITMQ_DEFAULT_USER:$RABBITMQ_DEFAULT_PASS@rabbitmq:5672//
DEVICEVAULT_REDIS_URL=redis://redis:6379/1
DEVICEVAULT_RESULT_BACKEND=redis://redis:6379/1
DEVICEVAULT_BROKER_API=http://$RABBITMQ_DEFAULT_USER:$RABBITMQ_DEFAULT_PASS@rabbitmq:15672/api/
DEVICEVAULT_RESULTS_STREAM=device:results
DEVICEVAULT_STORAGE_RESULTS_STREAM=storage:results

DEVICEVAULT_COLLECTOR_QUEUES=$DEVICEVAULT_COLLECTOR_QUEUES
DEVICEVAULT_LOCAL_COLLECTOR_CONCURRENCY=$DEVICEVAULT_LOCAL_COLLECTOR_CONCURRENCY
DEVICEVAULT_STORAGE_QUEUES=$DEVICEVAULT_STORAGE_QUEUES
DEVICEVAULT_LOCAL_STORAGE_CONCURRENCY=$DEVICEVAULT_LOCAL_STORAGE_CONCURRENCY
DEVICEVAULT_STORAGE_HOST_PATH=$DEVICEVAULT_STORAGE_HOST_PATH
DEVICEVAULT_STORAGE_CONTAINER_PATH=$DEVICEVAULT_STORAGE_CONTAINER_PATH
EOF
chmod 600 "$ENV_FILE"

if [[ ! -f "$CONFIG_DIR/config.yaml" || "$FORCE" == "1" ]]; then
    cat >"$CONFIG_DIR/config.yaml" <<EOF
timezone: $TIMEZONE

local_admin:
  username: $ADMIN_USERNAME
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

if [[ ! -f "$CONFIG_DIR/rabbitmq.conf" || "$FORCE" == "1" ]]; then
    cat >"$CONFIG_DIR/rabbitmq.conf" <<'EOF'
listeners.tcp.default = 5672
management.tcp.port = 15672
loopback_users.guest = false
EOF
    chmod 600 "$CONFIG_DIR/rabbitmq.conf"
fi

if [[ ! -f "$CONFIG_DIR/nginx.conf" || "$FORCE" == "1" ]]; then
    cat >"$CONFIG_DIR/nginx.conf" <<'EOF'
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://django:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /admin/ {
        proxy_pass http://django:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        proxy_pass http://django:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
    chmod 600 "$CONFIG_DIR/nginx.conf"
fi

production_install_compose_asset "$SOURCE_DIR/docker-build/docker-compose.prod-orchestrator-backup.yaml" "$DEPLOY_DIR"
cat >"$DEPLOY_DIR/compose.env" <<EOF
COMPOSE_PROJECT_NAME=devicevault-orchestrator-backup
DEVICEVAULT_ENV_FILE=$ENV_FILE
DEVICEVAULT_CONFIG_DIR=$CONFIG_DIR
DEVICEVAULT_APP_IMAGE=$APP_IMAGE
DEVICEVAULT_NGINX_IMAGE=$NGINX_IMAGE
DEVICEVAULT_PRIMARY_HOST=$PRIMARY_HOST
DEVICEVAULT_PRIMARY_REDIS_PORT=6379
DEVICEVAULT_STORAGE_HOST_PATH=$DEVICEVAULT_STORAGE_HOST_PATH
DEVICEVAULT_STORAGE_CONTAINER_PATH=$DEVICEVAULT_STORAGE_CONTAINER_PATH
EOF
chmod 600 "$DEPLOY_DIR/compose.env"

mkdir -p "$DEVICEVAULT_STORAGE_HOST_PATH"

if [[ "$SKIP_START" == "0" ]]; then
    production_compose "$DEPLOY_DIR" up -d --profile warm-standby
fi

echo ""
echo "=========================================="
echo "DeviceVault Production - Orchestrator Backup"
echo "=========================================="
echo "Config directory: $CONFIG_DIR"
echo "Deploy assets:    $DEPLOY_DIR"
echo "App image:        $APP_IMAGE"
echo "Nginx image:      $NGINX_IMAGE"
echo ""
if [[ "$SKIP_START" == "1" ]]; then
    echo "Services were not started (--skip-start)."
else
    echo "Warm-standby services deployed with docker compose."
fi
echo "Warm-standby status:"
echo "  docker compose --env-file $DEPLOY_DIR/compose.env -f $DEPLOY_DIR/compose.yaml --profile warm-standby ps"
echo "Promotion command:"
echo "  docker compose --env-file $DEPLOY_DIR/compose.env -f $DEPLOY_DIR/compose.yaml --profile promoted up -d"
