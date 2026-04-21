#!/usr/bin/env bash
# Shared shell helper for POC scripts. Source this file from a POC script.
#
#   source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../_lib/poc_helpers.sh"
#   setup_run_dir "$POC_ROOT"
#   echo "run dir: $RUN_DIR"
#
# After sourcing, these vars are exported:
#   TS        — timestamp used
#   RUN_DIR   — fresh timestamped output dir for this run

setup_run_dir() {
  local poc_root="$1"
  if [[ -z "$poc_root" ]]; then
    echo "setup_run_dir: missing poc_root argument" >&2
    return 1
  fi
  TS="$(date +%Y%m%d-%H%M%S)"
  RUN_DIR="$poc_root/outputs/$TS"
  mkdir -p "$RUN_DIR"
  ln -sfn "$TS" "$poc_root/outputs/latest"
  export TS RUN_DIR
}

# Write a JSON file, escaping via python. Usage: save_json "$RUN_DIR/prompts.json" "$json_string"
save_json() {
  local path="$1"
  local content="$2"
  printf '%s' "$content" > "$path"
}
