#!/usr/bin/env bash
# Script de deploiement pour MLE Heatmap Wrapper

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"
ENV_FILE="${PROJECT_DIR}/.env"
ENV_EXAMPLE_FILE="${PROJECT_DIR}/.env.example"

echo "========================================"
echo "MLE Heatmap Wrapper - Deployment Script"
echo "========================================"
echo "Project directory: ${PROJECT_DIR}"

echo "Creating required directories..."
mkdir -p \
  "${PROJECT_DIR}/logs" \
  "${PROJECT_DIR}/output/metrics" \
  "${PROJECT_DIR}/temp" \
  "${PROJECT_DIR}/data/in"

if [ ! -d "${VENV_DIR}" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "${VENV_DIR}"
fi

echo "Activating virtual environment..."
source "${VENV_DIR}/bin/activate"

echo "Upgrading pip..."
python -m pip install --upgrade pip

echo "Installing project dependencies..."
python -m pip install -e "${PROJECT_DIR}"

if [ ! -f "${ENV_FILE}" ]; then
  if [ -f "${ENV_EXAMPLE_FILE}" ]; then
    echo "Creating .env from .env.example..."
    cp "${ENV_EXAMPLE_FILE}" "${ENV_FILE}"
  else
    echo "Creating minimal .env file..."
    cat > "${ENV_FILE}" <<'EOF'
LOG_LEVEL=INFO
CONSOLE_LOG=true
OUTPUT_DIR=output
TEMP_DIR=temp
ENABLE_OP_DATA=false
EOF
  fi
  echo "Edit ${ENV_FILE} if needed."
fi

echo "Setting execution permissions..."
chmod +x "${PROJECT_DIR}/run_daily.sh"
chmod +x "${PROJECT_DIR}/usage_examples.py"

echo
echo "========================================"
echo "Installation completed successfully"
echo "========================================"
echo "Quick checks:"
echo "  source ${VENV_DIR}/bin/activate"
echo "  mle-heatmap --list-configs"
echo
echo "Batch example:"
echo "  mle-heatmap --input-dir data/in/mlx --part-number 362 --supplier MLX --output output"
echo
echo "Cron example (daily at 02:00):"
echo "  0 2 * * * ${PROJECT_DIR}/run_daily.sh"