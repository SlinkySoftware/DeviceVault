#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/production-common.sh"

SOURCE_DIR=""
REPO_URL="$PRODUCTION_DEFAULT_REPO_URL"
SOURCE_REF=""
IMAGE_PREFIX="devicevault"
IMAGE_TAG=""
PUSH_IMAGES=0

usage() {
    cat <<'EOF'
Usage: build-prod-images.sh [options]

Options:
  --source-dir <path>    Source checkout to build from.
  --repo-url <url>       Repository URL to clone when no checkout is available.
  --source-ref <ref>     Branch or tag to clone when a checkout must be created.
  --image-prefix <name>  Image prefix (default: devicevault).
  --image-tag <tag>      Image tag to build. Defaults to the current checkout ref.
  --push                 Push the built images after building.
  --help                 Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
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
        --image-prefix)
            IMAGE_PREFIX="$2"
            shift 2
            ;;
        --image-tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --push)
            PUSH_IMAGES=1
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

production_require_commands docker git

SOURCE_DIR="$(production_ensure_source_dir "$SOURCE_DIR" "/opt/devicevault" "$REPO_URL" "$SOURCE_REF")"

if [[ -z "$IMAGE_TAG" ]]; then
    IMAGE_TAG="$(production_derive_image_tag "$SOURCE_DIR")"
fi

APP_IMAGE="${IMAGE_PREFIX}/app:${IMAGE_TAG}"
NGINX_IMAGE="${IMAGE_PREFIX}/nginx:${IMAGE_TAG}"

echo "=========================================="
echo "DeviceVault Production Image Build"
echo "=========================================="
echo "Source directory: $SOURCE_DIR"
echo "App image:        $APP_IMAGE"
echo "Nginx image:      $NGINX_IMAGE"
echo ""

docker build -f "$SOURCE_DIR/docker-build/Dockerfile.app" -t "$APP_IMAGE" "$SOURCE_DIR"
docker build -f "$SOURCE_DIR/docker-build/Dockerfile.nginx" -t "$NGINX_IMAGE" "$SOURCE_DIR"

if [[ "$PUSH_IMAGES" == "1" ]]; then
    docker push "$APP_IMAGE"
    docker push "$NGINX_IMAGE"
fi

echo ""
echo "Build complete."
echo "Suggested deploy flags:"
echo "  --app-image $APP_IMAGE --nginx-image $NGINX_IMAGE"
