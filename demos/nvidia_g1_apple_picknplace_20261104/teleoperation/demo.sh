#!/usr/bin/env bash
set -euo pipefail
export DEMO_DIR
DEMO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
set -a
source "$DEMO_DIR/config.env"
if [[ -f "$DEMO_DIR/.env" ]]; then
    source "$DEMO_DIR/.env"
fi
set +a
exec python3 "$DEMO_DIR/scripts/demo.py" "$@"
