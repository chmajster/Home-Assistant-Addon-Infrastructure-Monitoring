#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1
export MONITORING_CENTER_OPTIONS="${MONITORING_CENTER_OPTIONS:-/data/options.json}"
export MONITORING_CENTER_HOST="${MONITORING_CENTER_HOST:-0.0.0.0}"
export MONITORING_CENTER_PORT="${MONITORING_CENTER_PORT:-8099}"

mkdir -p /data
exec /opt/monitoring-center/bin/python -m monitoring_center.main
