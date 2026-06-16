#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/monitor-$(date +%Y%m%d).log"

if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

export TZ="${TZ:-Europe/Zagreb}"

if [[ -d "$PROJECT_DIR/venv/bin" ]]; then
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/venv/bin/activate"
fi

{
  echo "=== $(date '+%d.%m.%Y. %H:%M:%S') ==="
  python3 monitor.py
  echo ""
} >> "$LOG_FILE" 2>&1