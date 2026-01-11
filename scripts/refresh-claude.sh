#!/bin/bash
# Refresh datalake with new Claude sessions
# Parses local ~/.claude/ sessions and optionally syncs to primary device

set -e

cd "$(dirname "$0")/.."

# Run incremental parse (only new sessions)
python3 parsers/claude_parser.py --incremental 2>&1 | logger -t datalake-refresh

# Source device role config
DEVICE_ROLE_CONFIG="$HOME/Programs/local-bootstrapping/device-role.conf"

if [[ -f "$DEVICE_ROLE_CONFIG" ]]; then
    source "$DEVICE_ROLE_CONFIG"
fi

# If secondary device, sync to primary
if [[ "$DEVICE_ROLE" == "secondary" ]]; then
    echo "Secondary device - syncing to primary" | logger -t datalake-refresh
    ./scripts/sync-to-primary.sh 2>&1 | logger -t datalake-refresh
fi
