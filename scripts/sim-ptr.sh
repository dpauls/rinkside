#!/usr/bin/env bash
# sim-ptr.sh: Interactive Pink the Rink tournament simulation runner
# Allows testing any of the 9 tournament steps (0 through 8) locally or live on OCI.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

usage() {
    echo "Usage:"
    echo "  ./scripts/sim-ptr.sh <0-8> [--with-llm] [--s3]"
    echo "  ./scripts/sim-ptr.sh restore [--s3]"
    echo ""
    echo "Commands:"
    echo "  0-8        Jump directly to simulation step (0=Pre-tourney, 1=Game 1 live, 2=Game 1 final,"
    echo "             3=Game 2 live tie, 4=Game 2 final/yellow GD, 5=Game 3 live trailing, 6=Pool play tiebreaker clinch,"
    echo "             7=Semifinals final, 8=Championship final 🏆)"
    echo "  restore    Reset all live scores, event log, and narrative back to pre-tournament baseline"
    echo ""
    echo "Options:"
    echo "  --with-llm  Enable live Gemini API narrative & Coach's Corner commentary (default: skipped for speed)"
    echo "  --s3        Publish state directly to OCI Object Storage so you can test on your phone/browser"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

CMD="$1"
shift

WITH_LLM=false
USE_S3=false

while [ $# -gt 0 ]; do
    case "$1" in
        --with-llm) WITH_LLM=true ;;
        --s3) USE_S3=true ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
    shift
done

STORAGE_ARG="local"
if [ "$USE_S3" = true ]; then
    STORAGE_ARG="s3"
fi

NARRATIVE_ARG="--skip-narrative"
if [ "$WITH_LLM" = true ]; then
    NARRATIVE_ARG=""
fi

PTR_DATA="data/tournaments/pink_the_rink_2026.json"
SHADOW_DATA="data/tournaments/.pink_the_rink_2026_live.json"
MOCK_DIR="test/mock_responses_ptr"

if [ "$CMD" = "restore" ]; then
    echo "==> Restoring Pink the Rink pre-tournament baseline (0 games played)..."
    rm -f "$MOCK_DIR/.mock_step"
    rm -f "$SHADOW_DATA"
    rm -f "docs/data/.state_pink_the_rink_2026_live.json"
    
    python3 src/daemon.py \
        --tournament "$PTR_DATA" \
        --mock-dir "$MOCK_DIR" \
        --mock-reset \
        --once \
        $NARRATIVE_ARG \
        --storage "$STORAGE_ARG"
    
    echo "==> Clean baseline restored successfully!"
    exit 0
fi

if [[ "$CMD" =~ ^[0-8]$ ]]; then
    STEP_NUM="$CMD"
    echo "==> Simulating Pink the Rink Step $STEP_NUM (mock step $STEP_NUM, LLM=$WITH_LLM, Storage=$STORAGE_ARG)..."
    
    # Reset to clean data if step 0, otherwise ensure shadow file exists
    if [ "$STEP_NUM" -eq 0 ]; then
        rm -f "$SHADOW_DATA"
        rm -f "docs/data/.state_pink_the_rink_2026_live.json"
    fi

    python3 src/daemon.py \
        --tournament "$PTR_DATA" \
        --mock-dir "$MOCK_DIR" \
        --mock-step "$STEP_NUM" \
        --once \
        $NARRATIVE_ARG \
        --storage "$STORAGE_ARG"

    echo "==> Step $STEP_NUM executed successfully!"
    echo "    Local state: docs/data/state.json"
    if [ "$USE_S3" = true ]; then
        echo "    Live OCI: https://objectstorage.ca-toronto-1.oraclecloud.com/n/yzjspjx2rhjg/b/rinkside/o/data/state.json"
    fi
    exit 0
fi

usage
