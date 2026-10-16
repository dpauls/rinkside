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
    echo "  ./scripts/sim-ptr.sh live [--s3]"
    echo ""
    echo "Commands:"
    echo "  0-8        Jump directly to simulation step (0=Pre-tourney, 1=Game 1 live, 2=Game 1 final,"
    echo "             3=Game 2 live tie, 4=Game 2 final/yellow GD, 5=Game 3 live trailing, 6=Pool play tiebreaker clinch,"
    echo "             7=Semifinals final, 8=Championship final 🏆)"
    echo "  restore    Reset all live scores, event log, and narrative back to pre-tournament baseline (mock mode)"
    echo "  live       Kick tracker out of test/mock mode and resume 100% LIVE OWHA/RAMP REST API polling"
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
IS_DEV=false

while [ $# -gt 0 ]; do
    case "$1" in
        --with-llm) WITH_LLM=true ;;
        --s3) USE_S3=true ;;
        --dev) USE_S3=true; IS_DEV=true ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
    shift
done

if [ "$CMD" = "live" ]; then
    USE_S3=true
fi

STORAGE_ARG="local"
DEV_FLAG=""
REMOTE_PREFIX="data"
LOCAL_TARGET_DIR="docs/data"

if [ "$USE_S3" = true ]; then
    STORAGE_ARG="s3"
    if [ "$IS_DEV" = true ]; then
        DEV_FLAG="--dev"
        REMOTE_PREFIX="data/dev"
        LOCAL_TARGET_DIR="docs/data/dev"
    fi
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
    
    if [ "$USE_S3" = true ]; then
        echo "==> Restoring pre-tournament baseline on Oracle Cloud VM (S3 storage)..."
        ssh -i "$HOME/.ssh/oracle_rinkside.key" -o StrictHostKeyChecking=no ubuntu@132.145.100.44 \
            "rm -f ~/rinkside/data/tournaments/.*_live.json ~/rinkside/data/.*_live.json ~/rinkside/docs/data/.*_live.json ~/rinkside/test/mock_responses_ptr/.mock_step && \
             cd ~/rinkside && git pull --ff-only origin main || true && git checkout -- data/tournaments/pink_the_rink_2026.json && \
             docker exec rinkside-tracker-1 python3 src/daemon.py \
                --tournament data/tournaments/pink_the_rink_2026.json \
                --mock-dir test/mock_responses_ptr \
                --mock-reset \
                --once \
                $NARRATIVE_ARG \
                --storage s3"
        
        echo "==> Syncing baseline state to local docs/data/..."
        mkdir -p docs/data
        curl -s -f "https://objectstorage.ca-toronto-1.oraclecloud.com/n/yzjspjx2rhjg/b/rinkside/o/data/state.json" -o docs/data/state.json || true
        curl -s -f "https://objectstorage.ca-toronto-1.oraclecloud.com/n/yzjspjx2rhjg/b/rinkside/o/data/scenarios.json" -o docs/data/scenarios.json || true
    else
        python3 src/daemon.py \
            --tournament "$PTR_DATA" \
            --mock-dir "$MOCK_DIR" \
            --mock-reset \
            --once \
            $NARRATIVE_ARG \
            --storage "local"
    fi

    echo "==> Clean baseline restored successfully!"
    exit 0
fi

if [ "$CMD" = "live" ]; then
    echo "==> Switching Pink the Rink tracker to 100% LIVE REST API tracking mode (with Gemini AI & Coach's Corner)..."
    rm -f "$MOCK_DIR/.mock_step"
    rm -f "$SHADOW_DATA"
    rm -f "docs/data/.state_pink_the_rink_2026_live.json"
    # Live production mode implies live AI narrative & Coach's Corner
    NARRATIVE_ARG=""

    if [ "$USE_S3" = true ]; then
        echo "==> Activating live REST tracker on Oracle Cloud VM..."
        ssh -i "$HOME/.ssh/oracle_rinkside.key" -o StrictHostKeyChecking=no ubuntu@132.145.100.44 \
            "rm -f ~/rinkside/data/tournaments/.*_live.json ~/rinkside/data/.*_live.json ~/rinkside/docs/data/.*_live.json ~/rinkside/test/mock_responses_ptr/.mock_step && \
             cd ~/rinkside && git pull --ff-only origin main || true && git checkout -- data/tournaments/pink_the_rink_2026.json && \
             docker compose restart tracker && \
             docker exec rinkside-tracker-1 python3 src/daemon.py \
                --tournament data/tournaments/pink_the_rink_2026.json \
                --once \
                $NARRATIVE_ARG \
                --storage s3"

        echo "==> Syncing live state to local docs/data/..."
        mkdir -p docs/data
        curl -s -f "https://objectstorage.ca-toronto-1.oraclecloud.com/n/yzjspjx2rhjg/b/rinkside/o/data/state.json" -o docs/data/state.json || true
        curl -s -f "https://objectstorage.ca-toronto-1.oraclecloud.com/n/yzjspjx2rhjg/b/rinkside/o/data/scenarios.json" -o docs/data/scenarios.json || true
        echo "==> Live REST mode activated! The tracker is actively polling OWHA/RAMP every 60s."
    else
        python3 src/daemon.py \
            --tournament "$PTR_DATA" \
            --once \
            $NARRATIVE_ARG \
            --storage "local"
        echo "==> Live REST mode executed locally!"
    fi
    exit 0
fi

if [[ "$CMD" =~ ^[0-8]$ ]]; then
    STEP_NUM="$CMD"
    echo "==> Simulating Pink the Rink Step $STEP_NUM (mock step $STEP_NUM, LLM=$WITH_LLM, Storage=$STORAGE_ARG)..."
    
    if [ "$USE_S3" = true ]; then
        if [ "$IS_DEV" = true ]; then
            echo "==> Executing Step $STEP_NUM in ISOLATED DEV MODE (data/dev/ in S3, Prod is untouched)..."
        else
            echo "==> Executing Step $STEP_NUM on LIVE PRODUCTION (data/ in S3)..."
        fi
        ssh -i "$HOME/.ssh/oracle_rinkside.key" -o StrictHostKeyChecking=no ubuntu@132.145.100.44 \
            "docker exec rinkside-tracker-1 python3 src/daemon.py \
                --tournament data/tournaments/pink_the_rink_2026.json \
                --mock-dir test/mock_responses_ptr \
                --mock-step $STEP_NUM \
                --once \
                $NARRATIVE_ARG \
                --storage s3 \
                $DEV_FLAG"

        echo "==> Syncing generated state to local $LOCAL_TARGET_DIR/..."
        mkdir -p "$LOCAL_TARGET_DIR"
        curl -s -f "https://objectstorage.ca-toronto-1.oraclecloud.com/n/yzjspjx2rhjg/b/rinkside/o/${REMOTE_PREFIX}/state.json" -o "${LOCAL_TARGET_DIR}/state.json" || true
        curl -s -f "https://objectstorage.ca-toronto-1.oraclecloud.com/n/yzjspjx2rhjg/b/rinkside/o/${REMOTE_PREFIX}/scenarios.json" -o "${LOCAL_TARGET_DIR}/scenarios.json" || true
    else
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
            --storage "local"
    fi

    echo "==> Step $STEP_NUM executed successfully!"
    if [ "$IS_DEV" = true ]; then
        echo "    🛠️  Dev Preview URL: https://rangers-live.pages.dev/?env=dev"
        echo "    🔒 Production remains 100% UNTOUCHED at: https://rangers-live.pages.dev"
    elif [ "$USE_S3" = true ]; then
        echo "    🔴 Production URL: https://rangers-live.pages.dev"
    else
        echo "    💻 Local Preview: http://localhost:8000 (docs/data/state.json)"
    fi
    exit 0
fi

usage
