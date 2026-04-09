#!/usr/bin/env bash
# Execution quotidienne MLE Heatmap (mode batch)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"
LOG_DIR="${PROJECT_DIR}/logs"
EXECUTION_LOG="${LOG_DIR}/cron_execution_$(date +%Y%m%d).log"

mkdir -p "${LOG_DIR}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${EXECUTION_LOG}"
}

log "========================================"
log "MLE Heatmap - Daily Execution Started"
log "========================================"

if [ ! -d "${VENV_DIR}" ]; then
  log "ERROR: virtual environment not found: ${VENV_DIR}"
  exit 1
fi

log "Activating virtual environment..."
source "${VENV_DIR}/bin/activate"

if [ -f "${PROJECT_DIR}/.env" ]; then
  log "Loading .env configuration..."
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_DIR}/.env"
  set +a
fi

# Defaults can be overridden in .env
DAILY_PART_NUMBER="${DAILY_PART_NUMBER:-362}"
DAILY_SUPPLIER="${DAILY_SUPPLIER:-MLX}"
DAILY_INPUT_DIR="${DAILY_INPUT_DIR:-${PROJECT_DIR}/data/in/mlx}"
DAILY_OUTPUT_DIR="${DAILY_OUTPUT_DIR:-${PROJECT_DIR}/output}"
DAILY_METRICS="${DAILY_METRICS:-widthness,tangent,chords,thickness_extrados,thickness_intrados}"
DAILY_NOMINAL_FILE="${DAILY_NOMINAL_FILE:-}"

if [ ! -d "${DAILY_INPUT_DIR}" ]; then
  log "ERROR: input directory not found: ${DAILY_INPUT_DIR}"
  exit 1
fi

mkdir -p "${DAILY_OUTPUT_DIR}"

log "Part number: ${DAILY_PART_NUMBER}"
log "Supplier: ${DAILY_SUPPLIER}"
log "Input dir: ${DAILY_INPUT_DIR}"
log "Output dir: ${DAILY_OUTPUT_DIR}"
log "Metrics: ${DAILY_METRICS}"

cmd=(
  mle-heatmap
  --input-dir "${DAILY_INPUT_DIR}"
  --part-number "${DAILY_PART_NUMBER}"
  --supplier "${DAILY_SUPPLIER}"
  --output "${DAILY_OUTPUT_DIR}"
)

IFS=', ' read -r -a metrics_array <<< "${DAILY_METRICS}"
if [ ${#metrics_array[@]} -gt 0 ] && [ -n "${metrics_array[0]}" ]; then
  cmd+=(--metrics "${metrics_array[@]}")
fi

if [ -n "${DAILY_NOMINAL_FILE}" ]; then
  if [ ! -f "${DAILY_NOMINAL_FILE}" ]; then
    log "ERROR: nominal file not found: ${DAILY_NOMINAL_FILE}"
    exit 1
  fi
  cmd+=(--nominal "${DAILY_NOMINAL_FILE}")
fi

log "Executing command:"
log "  ${cmd[*]}"

if "${cmd[@]}" >> "${EXECUTION_LOG}" 2>&1; then
  log "Batch execution: SUCCESS"
  status=0
else
  log "Batch execution: ERROR"
  status=1
fi

find "${LOG_DIR}" -name "cron_execution_*.log" -mtime +30 -delete 2>/dev/null || true

log "========================================"
log "MLE Heatmap - Daily Execution Finished"
log "========================================"

exit "${status}"