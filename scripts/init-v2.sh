#!/usr/bin/env bash
# Initialize datalake v2.0 with extended schema
# Supports Claude Code conversations, voice typing, and email

set -euo pipefail

# Configuration
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(dirname "$(readlink -f "$0")")")}"
SCHEMA_FILE="${SCHEMA_FILE:-$PROJECT_ROOT/schema_v2.sql}"
DB_FILE="${DB_FILE:-$PROJECT_ROOT/datalake.db}"
DATA_DIR="${DATA_DIR:-$PROJECT_ROOT/data}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"

# Logging
log() {
    echo "[$(date -Iseconds)] [INFO] $*" | tee -a "$LOG_DIR/init-v2.log"
}

error() {
    echo "[$(date -Iseconds)] [ERROR] $*" | tee -a "$LOG_DIR/init-v2.log" >&2
}

# Create directories
mkdir -p "$LOG_DIR"
mkdir -p "$DATA_DIR"/{audio,transcripts,screenshots,claude,email,terminal}/{2026,2025}/{01,02,03,04,05,06,07,08,09,10,11,12}

log "Initializing datalake v2.0"
log "Project root: $PROJECT_ROOT"
log "Database: $DB_FILE"
log "Data directory: $DATA_DIR"

# Check if schema file exists
if [[ ! -f "$SCHEMA_FILE" ]]; then
    error "Schema file not found: $SCHEMA_FILE"
    exit 1
fi

# Backup existing database if present
if [[ -f "$DB_FILE" ]]; then
    BACKUP_FILE="${DB_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    log "Backing up existing database to: $BACKUP_FILE"
    cp "$DB_FILE" "$BACKUP_FILE"
fi

# Initialize database
log "Creating database from schema..."
sqlite3 "$DB_FILE" < "$SCHEMA_FILE"

# Verify tables were created
TABLE_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
log "Created $TABLE_COUNT tables"

# Verify FTS tables
FTS_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE '%_fts';")
log "Created $FTS_COUNT FTS tables"

# Set permissions
chmod 644 "$DB_FILE"
find "$DATA_DIR" -type d -exec chmod 755 {} \;

# Register this device
HOSTNAME=$(hostname)
DEVICE_NAME="${DEVICE_NAME:-$(echo "$HOSTNAME" | tr '[:upper:]' '[:lower:]')}"

log "Registering device: $DEVICE_NAME"
sqlite3 "$DB_FILE" "INSERT OR REPLACE INTO devices (device_name, hostname, last_seen_at) VALUES ('$DEVICE_NAME', '$HOSTNAME', datetime('now'));"

# Show schema version
VERSION=$(sqlite3 "$DB_FILE" "SELECT value FROM metadata WHERE key='schema_version';")
log "Schema version: $VERSION"

log "Initialization complete!"

# Print summary
echo ""
echo "=== Datalake v2.0 Initialized ==="
echo "Database: $DB_FILE"
echo "Tables: $TABLE_COUNT"
echo "FTS Tables: $FTS_COUNT"
echo "Device: $DEVICE_NAME"
echo ""
echo "Next steps:"
echo "1. Run: python parsers/claude_parser.py --stats-only"
echo "2. Ingest: python parsers/claude_parser.py --device $DEVICE_NAME"
echo ""
