#!/usr/bin/env bash
set -e

HOST="ubuntu@132.145.100.44"
KEY="$HOME/.ssh/oracle_rinkside.key"

echo "==> Ensuring local commits are pushed to GitHub..."
git push origin main || true

if [ -f .env ]; then
    echo "==> Syncing .env credentials to Oracle Cloud VM..."
    scp -i "$KEY" -o StrictHostKeyChecking=no .env "$HOST":~/rinkside/.env
fi

echo "==> Syncing and rebuilding on Oracle Cloud VM ($HOST)..."
ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST" "
    set -e
    cd ~/rinkside
    git pull origin main
    docker compose build
    docker compose up -d tracker
    echo '==> Recent container logs:'
    docker compose logs --tail=15 tracker
"

echo "==> Rinkside daemon is live on Oracle Cloud!"
