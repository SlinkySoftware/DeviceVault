#!/usr/bin/env bash

set -euo pipefail

PRODUCTION_DEFAULT_REPO_URL="https://github.com/SlinkySoftware/DeviceVault.git"


production_repo_root_from_script() {
    local helper_dir repo_root

    helper_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    repo_root="$(git -C "$helper_dir/../.." rev-parse --show-toplevel 2>/dev/null || true)"

    if [[ -n "$repo_root" && -f "$repo_root/docker-build/Dockerfile.app" ]]; then
        printf '%s\n' "$repo_root"
    fi
}


production_require_root() {
    if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
        echo "ERROR: This script must be run as root (use sudo)." >&2
        exit 1
    fi
}


production_require_commands() {
    local command_name
    for command_name in "$@"; do
        if ! command -v "$command_name" >/dev/null 2>&1; then
            echo "ERROR: Required command not found: $command_name" >&2
            exit 1
        fi
    done
}


production_random_base64() {
    openssl rand -base64 "$1"
}


production_prompt() {
    local variable_name="$1"
    local prompt_text="$2"
    local default_value="${3:-}"
    local secret="${4:-0}"
    local current_value="${!variable_name:-}"
    local entered_value

    if [[ -n "$current_value" ]]; then
        return
    fi

    if [[ ! -t 0 ]]; then
        if [[ -n "$default_value" ]]; then
            printf -v "$variable_name" '%s' "$default_value"
            return
        fi
        echo "ERROR: Missing required value for $variable_name in non-interactive mode." >&2
        exit 1
    fi

    if [[ "$secret" == "1" ]]; then
        if [[ -n "$default_value" ]]; then
            read -r -s -p "$prompt_text [$default_value]: " entered_value
            echo
            printf -v "$variable_name" '%s' "${entered_value:-$default_value}"
        else
            while [[ -z "${!variable_name:-}" ]]; do
                read -r -s -p "$prompt_text: " entered_value
                echo
                printf -v "$variable_name" '%s' "$entered_value"
            done
        fi
        return
    fi

    if [[ -n "$default_value" ]]; then
        read -r -p "$prompt_text [$default_value]: " entered_value
        printf -v "$variable_name" '%s' "${entered_value:-$default_value}"
    else
        while [[ -z "${!variable_name:-}" ]]; do
            read -r -p "$prompt_text: " entered_value
            printf -v "$variable_name" '%s' "$entered_value"
        done
    fi
}


production_load_env_file() {
    local env_file="$1"

    if [[ -f "$env_file" ]]; then
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
    fi
}


production_clone_repo() {
    local repo_url="$1"
    local source_ref="$2"
    local target_dir="$3"

    if [[ -e "$target_dir" && ! -d "$target_dir/.git" ]]; then
        echo "ERROR: Cannot clone into $target_dir because it already exists and is not a git checkout." >&2
        exit 1
    fi

    if [[ -d "$target_dir/.git" ]]; then
        printf '%s\n' "$target_dir"
        return
    fi

    mkdir -p "$(dirname "$target_dir")"

    if [[ -n "$source_ref" ]]; then
        git clone --single-branch --branch "$source_ref" "$repo_url" "$target_dir"
    else
        git clone "$repo_url" "$target_dir"
    fi

    printf '%s\n' "$target_dir"
}


production_ensure_source_dir() {
    local requested_source_dir="$1"
    local deploy_root="$2"
    local repo_url="$3"
    local source_ref="$4"
    local current_repo_root clone_target

    if [[ -n "$requested_source_dir" ]]; then
        if [[ -f "$requested_source_dir/docker-build/Dockerfile.app" ]]; then
            printf '%s\n' "$requested_source_dir"
            return
        fi
        production_clone_repo "$repo_url" "$source_ref" "$requested_source_dir"
        return
    fi

    current_repo_root="$(production_repo_root_from_script)"
    if [[ -n "$current_repo_root" ]]; then
        printf '%s\n' "$current_repo_root"
        return
    fi

    clone_target="$deploy_root"
    production_clone_repo "$repo_url" "$source_ref" "$clone_target"
}


production_derive_image_tag() {
    local source_dir="$1"

    git -C "$source_dir" describe --tags --always --dirty 2>/dev/null \
        || git -C "$source_dir" rev-parse --short HEAD 2>/dev/null \
        || date +%Y%m%d%H%M%S
}


production_install_compose_asset() {
    local source_file="$1"
    local deploy_dir="$2"

    mkdir -p "$deploy_dir"
    cp "$source_file" "$deploy_dir/compose.yaml"
}


production_compose() {
    local deploy_dir="$1"
    shift

    docker compose --env-file "$deploy_dir/compose.env" -f "$deploy_dir/compose.yaml" "$@"
}
