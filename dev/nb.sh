#!/usr/bin/env bash
# Development helper: runs NetBox management commands against a local NetBox checkout
# with this plugin installed in editable mode. Paths come from dev/.env.local (not versioned):
#
#   NETBOX_DIR=/path/to/netbox      # NetBox git checkout (contains netbox/manage.py)
#   VENV=/path/to/venv              # virtualenv with NetBox requirements, the plugin (-e) and ruff
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PLUGIN_DIR}/dev/.env.local"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: ${ENV_FILE} is missing." >&2
  echo "Create it with NETBOX_DIR=<NetBox checkout> and VENV=<virtualenv> (see the header of dev/nb.sh)." >&2
  exit 1
fi
# shellcheck source=/dev/null
source "${ENV_FILE}"
: "${NETBOX_DIR:?NETBOX_DIR not set in ${ENV_FILE}}"
: "${VENV:?VENV not set in ${ENV_FILE}}"

PYTHON="${VENV}/bin/python"
MANAGE="${NETBOX_DIR}/netbox/manage.py"

manage() {
  "${PYTHON}" "${MANAGE}" "$@"
}

lint() {
  (cd "${PLUGIN_DIR}" && "${VENV}/bin/ruff" check . && "${VENV}/bin/ruff" format --check .)
}

run_tests() {
  manage test --keepdb --parallel 1 "${@:-inventory_monitor}"
}

cmd="${1:-}"
shift || true

case "${cmd}" in
  test)
    run_tests "$@"
    ;;
  lint)
    lint
    ;;
  migrations)
    manage makemigrations inventory_monitor "$@"
    ;;
  check)
    lint
    manage makemigrations inventory_monitor --check --dry-run
    run_tests
    ;;
  runserver)
    manage runserver 127.0.0.1:8001 --insecure "$@"
    ;;
  manage)
    manage "$@"
    ;;
  *)
    echo "usage: dev/nb.sh {test [label...]|lint|migrations|check|runserver|manage <args...>}" >&2
    exit 2
    ;;
esac
