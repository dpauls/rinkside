#!/usr/bin/env bash
# test-push.sh: Inspect subscribers and fire live test Web Push notifications
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

KEY="$HOME/.ssh/oracle_rinkside.key"
HOST="ubuntu@132.145.100.44"

usage() {
    echo "Usage:"
    echo "  ./scripts/test-push.sh --list"
    echo "  ./scripts/test-push.sh --test [--title \"...\"] [--body \"...\"]"
    echo ""
    echo "Commands:"
    echo "  --list   List all registered devices in OCI Object Storage"
    echo "  --test   Broadcast a live test push notification to all registered devices"
    echo ""
    echo "Options:"
    echo "  --title  Custom notification title (default: '🏒 Rinkside Test Alert')"
    echo "  --body   Custom notification body text"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

CMD_ARGS="$*"

echo "==> Running Web Push Manager on Oracle Cloud VM..."
ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST" \
    "docker exec rinkside-tracker-1 python3 src/push.py $CMD_ARGS"
