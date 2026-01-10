#!/usr/bin/env bash
# Initialize datalake database and directory structure
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$SCRIPT_DIR")}"
SCHEMA_FILE="${SCHEMA_FILE:-$PROJECT_ROOT/schema.sql}"
DB_FILE="${DB_FILE:-$PROJECT_ROOT/datalake.db}"
DATA_DIR="${DATA_DIR:-$PROJECT_ROOT/data}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
LOG_FILE="$LOG_DIR/init.log"

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date -Iseconds)
    echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

# Initialize logging
mkdir -p "$LOG_DIR"
log "INFO" "Starting datalake initialization"

# Check if schema file exists
if [[ ! -f "$SCHEMA_FILE" ]]; then
    log "ERROR" "Schema file not found: $SCHEMA_FILE"
    exit 1
fi

# Create data directory structure
log "INFO" "Creating data directory structure at: $DATA_DIR"
mkdir -p "$DATA_DIR"/{audio,transcripts,screenshots}

# Set proper permissions (755 for dirs, 644 for files)
find "$DATA_DIR" -type d -exec chmod 755 {} \;
log "INFO" "Set directory permissions to 755"

# Initialize SQLite database
if [[ -f "$DB_FILE" ]]; then
    log "WARN" "Database already exists at: $DB_FILE"
    read -p "Do you want to reinitialize? This will backup the existing database. (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        backup_file="${DB_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
        mv "$DB_FILE" "$backup_file"
        log "INFO" "Backed up existing database to: $backup_file"
    else
        log "INFO" "Keeping existing database, skipping initialization"
        exit 0
    fi
fi

log "INFO" "Creating database from schema: $SCHEMA_FILE"
if sqlite3 "$DB_FILE" < "$SCHEMA_FILE"; then
    log "INFO" "Database created successfully at: $DB_FILE"
else
    log "ERROR" "Failed to create database"
    exit 1
fi

# Set database file permissions
chmod 644 "$DB_FILE"
log "INFO" "Set database permissions to 644"

# Verify database structure
log "INFO" "Verifying database structure"
table_count=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';")
log "INFO" "Database contains $table_count tables"

# Show database info
log "INFO" "Database tables:"
sqlite3 "$DB_FILE" "SELECT name FROM sqlite_master WHERE type='table';" | while read -r table; do
    log "INFO" "  - $table"
done

log "INFO" "Datalake initialization complete!"
log "INFO" "Database: $DB_FILE"
log "INFO" "Data directory: $DATA_DIR"

# Display usage information
cat <<EOF

Datalake initialized successfully!

Database: $DB_FILE
Data directory: $DATA_DIR

Next steps:
1. Ingest audio files: ./scripts/ingest-audio.sh <audio_file> [tags]
2. Query data: ./scripts/query.sh
3. View logs: tail -f logs/init.log

EOF
