#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROJECT_ROOT}"

source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-20}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

if [[ ! -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  echo "缺少 .venv，请先创建虚拟环境并安装 requirements.txt" >&2
  exit 1
fi

exec "${PROJECT_ROOT}/.venv/bin/python" "${PROJECT_ROOT}/ubtech_dialogue.py" "$@"

