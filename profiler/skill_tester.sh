#!/usr/bin/env bash
# Test conversation-recall skill via Claude CLI and measure timing
#
# Usage:
#   ./skill_tester.sh "star trek"
#   ./skill_tester.sh "tapo camera" --json

set -euo pipefail

QUERY="${1:-tapo}"
OUTPUT_MODE="${2:-text}"

# Time the skill invocation
START_TIME=$(date +%s%N)

# Invoke Claude with the conversation-recall skill
# Note: This requires claude CLI to be installed and configured
RESULT=$(timeout 60 claude --print -p "Search for conversations about '$QUERY'. Use the conversation-recall skill." 2>&1 || true)

END_TIME=$(date +%s%N)

# Calculate duration in milliseconds
DURATION_NS=$((END_TIME - START_TIME))
DURATION_MS=$((DURATION_NS / 1000000))

# Extract session count from output
SESSION_COUNT=$(echo "$RESULT" | grep -c "Session:" || echo "0")

if [[ "$OUTPUT_MODE" == "--json" ]]; then
    cat << EOF
{
  "query": "$QUERY",
  "duration_ms": $DURATION_MS,
  "sessions_found": $SESSION_COUNT,
  "output_length": ${#RESULT}
}
EOF
else
    echo "Query: $QUERY"
    echo "Duration: ${DURATION_MS}ms"
    echo "Sessions found: $SESSION_COUNT"
    echo "Output length: ${#RESULT} chars"
    echo ""
    echo "--- Output Preview (first 500 chars) ---"
    echo "${RESULT:0:500}"
fi
