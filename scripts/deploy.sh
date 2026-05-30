#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="vpn-client-admin"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-vpn_client_admin}"
CHECK_ONLY="false"

for arg in "$@"; do
  case "$arg" in
    --check|--dry-run)
      CHECK_ONLY="true"
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: bash scripts/deploy.sh [--check]" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
if [[ -z "${DEPLOY_ROOT:-}" ]]; then
  APP_PARENT="$(cd -- "${APP_DIR}/.." && pwd)"
  if [[ "$(basename -- "$APP_PARENT")" == "releases" ]]; then
    DEPLOY_ROOT="$(cd -- "${APP_PARENT}/.." && pwd)"
  else
    DEPLOY_ROOT="$APP_PARENT"
  fi
fi
SHARED_ENV="${DEPLOY_ENV_FILE:-${DEPLOY_ROOT}/shared/.env}"
LOCAL_ENV="${APP_DIR}/.env"
COMPOSE_FILE="${APP_DIR}/docker-compose.yml"

cd "$APP_DIR"

log() {
  printf '[%s] %s\n' "$APP_NAME" "$*"
}

fail() {
  printf '[%s] ERROR: %s\n' "$APP_NAME" "$*" >&2
  exit 1
}

show_logs_on_error() {
  local exit_code=$?
  if [[ "$exit_code" -ne 0 && "$CHECK_ONLY" != "true" ]] && command -v docker >/dev/null 2>&1; then
    echo
    log "Last app logs:"
    COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" docker compose -f "$COMPOSE_FILE" logs --tail=80 app || true
  fi
  exit "$exit_code"
}

trap show_logs_on_error EXIT

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    fail "Docker is not installed. Install Docker Engine and the Compose plugin, then run this script again: https://docs.docker.com/engine/install/"
  fi
  if ! docker compose version >/dev/null 2>&1; then
    fail "Docker Compose plugin is not available. Install docker-compose-plugin, then run this script again."
  fi
}

prepare_env() {
  if [[ -f "$SHARED_ENV" ]]; then
    ln -sfn "$SHARED_ENV" "$LOCAL_ENV"
    log "Using shared env: $SHARED_ENV"
    return
  fi

  if [[ -f "$LOCAL_ENV" ]]; then
    log "Using local env: $LOCAL_ENV"
    return
  fi

  fail "Production .env not found. Create it at $SHARED_ENV before deploying."
}

require_docker
prepare_env

export COMPOSE_PROJECT_NAME

log "Validating Docker Compose configuration"
docker compose -f "$COMPOSE_FILE" config >/dev/null

if [[ "$CHECK_ONLY" == "true" ]]; then
  log "Validation completed"
  exit 0
fi

log "Pulling remote images when available"
docker compose -f "$COMPOSE_FILE" pull || true

log "Building application image"
docker compose -f "$COMPOSE_FILE" build

log "Starting database"
docker compose -f "$COMPOSE_FILE" up -d postgres

log "Waiting for database health"
DB_CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps -q postgres)"
for attempt in {1..60}; do
  DB_HEALTH="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' "$DB_CONTAINER" 2>/dev/null || true)"
  if [[ "$DB_HEALTH" == "healthy" || "$DB_HEALTH" == "unknown" ]]; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    fail "PostgreSQL did not become healthy in time"
  fi
  sleep 2
done

log "Running database migrations"
docker compose -f "$COMPOSE_FILE" run --rm app alembic upgrade head

log "Starting services"
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

log "Current service status"
docker compose -f "$COMPOSE_FILE" ps

log "Deploy completed"
