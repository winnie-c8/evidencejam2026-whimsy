#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec python3 build/build.py "${1:-site/}" "${@:2}"
