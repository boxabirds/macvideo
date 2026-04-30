#!/usr/bin/env bash
# Stop local editor servers on known ports. Used by dev and e2e launchers so
# each run starts from a clean process state.
set -euo pipefail

PORTS=("$@")
if [[ ${#PORTS[@]} -eq 0 ]]; then
  PORTS=(8000 5173)
fi

pids_for_port() {
  local port=$1
  lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true
}

wait_for_port_clear() {
  local port=$1
  local deadline=$((SECONDS + 3))

  while [[ ${SECONDS} -lt ${deadline} ]]; do
    if [[ -z "$(pids_for_port "${port}")" ]]; then
      return 0
    fi
    sleep 0.1
  done

  return 1
}

for port in "${PORTS[@]}"; do
  pids="$(pids_for_port "${port}")"
  if [[ -z "${pids}" ]]; then
    echo "[teardown] port ${port} already clear"
    continue
  fi

  echo "[teardown] stopping port ${port} listeners: ${pids//$'\n'/ }"
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true

  if ! wait_for_port_clear "${port}"; then
    pids="$(pids_for_port "${port}")"
    if [[ -n "${pids}" ]]; then
      echo "[teardown] force-stopping port ${port} listeners: ${pids//$'\n'/ }"
      # shellcheck disable=SC2086
      kill -9 ${pids} 2>/dev/null || true
      wait_for_port_clear "${port}" || true
    fi
  fi
done
