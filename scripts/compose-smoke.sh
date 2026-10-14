#!/usr/bin/env bash
# Compose smoke test (KAN-164). Health only, no secrets: uses docker-compose.yml defaults
# (fake local values, same as .env.example).
#
#   scripts/compose-smoke.sh up         build and start the stack, wait for healthchecks
#   scripts/compose-smoke.sh healthy    assert frontend /api/health is 200 {"status":"ok"} and backend /health is 200
#   scripts/compose-smoke.sh degraded   stop the backend, assert frontend /api/health is a generic 503
#   scripts/compose-smoke.sh down       remove containers and volumes
#   scripts/compose-smoke.sh all        up, healthy, degraded, then down (the default)
set -euo pipefail

cd "$(dirname "$0")/.."
FRONTEND="http://localhost:${FRONTEND_PORT:-3000}"
BACKEND="http://localhost:${BACKEND_PORT:-8000}"

# On Linux (CI) the checkout is owned by the runner's uid; the frontend container must run as it
# (docker-compose.yml: user). Elsewhere the compose default (1000) is kept.
if [ "$(uname -s)" = Linux ]; then
  export DEV_UID="${DEV_UID:-$(id -u)}" DEV_GID="${DEV_GID:-$(id -g)}"
fi

fail() { echo "::error::$*" >&2; exit 1; }

# status_of URL -> prints the HTTP status, or 000 when nothing answers.
status_of() { curl --silent --output /dev/null --write-out '%{http_code}' --max-time 15 "$1" || true; }

# wait_for_status URL CODE -> polls until URL answers CODE or ~90 s pass.
wait_for_status() {
  local url="$1" want="$2" got=""
  for _ in $(seq 1 30); do
    got="$(status_of "$url")"
    [ "$got" = "$want" ] && return 0
    sleep 3
  done
  fail "$url answered $got, expected $want"
}

up() {
  docker compose up --build --detach --wait --wait-timeout 600 \
    || { docker compose ps || true; docker compose logs --tail 80 || true; fail "docker compose up did not become healthy"; }
}

healthy() {
  wait_for_status "$FRONTEND/api/health" 200
  body="$(curl --silent --max-time 15 "$FRONTEND/api/health")"
  [ "$body" = '{"status":"ok"}' ] || fail "frontend /api/health body was: $body"
  wait_for_status "$BACKEND/health" 200
  echo "healthy: frontend /api/health 200 ok, backend /health 200"
}

degraded() {
  docker compose stop backend
  wait_for_status "$FRONTEND/api/health" 503
  body="$(curl --silent --max-time 15 "$FRONTEND/api/health")"
  # Generic body only: no backend URL, hostname, or error text may leak.
  [ "$body" = '{"status":"unavailable"}' ] || fail "frontend 503 body was not generic: $body"
  [ "$(status_of "$BACKEND/health")" != 200 ] || fail "backend /health still answers 200 after stop"
  echo "degraded: frontend /api/health 503 generic, backend /health down"
}

down() { docker compose down --volumes --remove-orphans; }

case "${1:-all}" in
  up) up ;;
  healthy) healthy ;;
  degraded) degraded ;;
  down) down ;;
  all) trap down EXIT; up; healthy; degraded ;;
  *) fail "usage: $0 {up|healthy|degraded|down|all}" ;;
esac
