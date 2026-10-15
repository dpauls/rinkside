#!/usr/bin/env bash
# Reset narrative, Coach's Corner, and event log history on the Oracle Cloud VM
# and restart the tracker container so it generates a clean baseline.
set -euo pipefail

VM_HOST="${VM_HOST:-ubuntu@132.145.100.44}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/oracle_rinkside.key}"

echo "==> Clearing narrative, Coach's Corner, and event history on $VM_HOST..."
ssh -i "$SSH_KEY" "$VM_HOST" "sudo python3 -c '
import json, pathlib
for p in pathlib.Path(\"/home/ubuntu/rinkside/data/tournaments\").glob(\".*_live.json\"):
    d = json.loads(p.read_text())
    d[\"event_log\"] = []
    d.pop(\"_narrative\", None)
    d.pop(\"_coaches_corner\", None)
    d.pop(\"_tb_health\", None)
    p.write_text(json.dumps(d, indent=2))
    print(\"Cleared narrative history in\", p.name)
' && cd ~/rinkside && docker compose restart tracker"

echo "==> Narrative reset complete! The container is now regenerating a fresh baseline."
