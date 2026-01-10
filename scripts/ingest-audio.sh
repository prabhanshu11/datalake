#!/usr/bin/env bash
# Ingest audio files into datalake
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_FILE="${DB_FILE:-$PROJECT_ROOT/datalake.db}"
DATA_DIR="${DATA_DIR:-$PROJECT_ROOT/data}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
LOG_FILE="$LOG_DIR/ingest-audio.log"

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

# Usage information
usage() {
    cat <<EOF
Usage: $0 <audio_file> [tags]

Arguments:
    audio_file    Path to the audio file to ingest
    tags          Optional comma-separated tags (e.g., "meeting,work")

Example:
    $0 recording.wav "meeting,important"

EOF
    exit 1
}

# Check arguments
if [[ $# -lt 1 ]]; then
    usage
fi

AUDIO_FILE="$1"
TAGS="${2:-}"

# Validate audio file exists
if [[ ! -f "$AUDIO_FILE" ]]; then
    log "ERROR" "Audio file not found: $AUDIO_FILE"
    exit 1
fi

# Check if database exists
if [[ ! -f "$DB_FILE" ]]; then
    log "ERROR" "Database not found. Run ./scripts/init.sh first"
    exit 1
fi

# Check if ffprobe is available
if ! command -v ffprobe &> /dev/null; then
    log "WARN" "ffprobe not found, metadata extraction will be limited"
    FFPROBE_AVAILABLE=false
else
    FFPROBE_AVAILABLE=true
fi

log "INFO" "Starting ingestion of: $AUDIO_FILE"

# Get file info
original_filename=$(basename "$AUDIO_FILE")
file_size=$(stat -c%s "$AUDIO_FILE")
file_extension="${original_filename##*.}"
created_timestamp=$(date -Iseconds)

# Create date-based directory structure
year=$(date +%Y)
month=$(date +%m)
day=$(date +%d)
dest_dir="$DATA_DIR/audio/$year/$month/$day"
mkdir -p "$dest_dir"

# Generate unique filename
timestamp=$(date +%H%M%S)
new_filename="${timestamp}_${original_filename}"
dest_path="$dest_dir/$new_filename"

# Relative path for database
relative_path="audio/$year/$month/$day/$new_filename"

# Copy file
log "INFO" "Copying file to: $dest_path"
if cp "$AUDIO_FILE" "$dest_path"; then
    log "INFO" "File copied successfully"
else
    log "ERROR" "Failed to copy file"
    exit 1
fi

# Set file permissions
chmod 644 "$dest_path"

# Extract metadata using ffprobe
duration_seconds=""
sample_rate=""
channels=""
format=""

if [[ "$FFPROBE_AVAILABLE" == true ]]; then
    log "INFO" "Extracting metadata with ffprobe"

    # Get duration
    duration_seconds=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$dest_path" 2>/dev/null || echo "")

    # Get format
    format=$(ffprobe -v error -show_entries format=format_name -of default=noprint_wrappers=1:nokey=1 "$dest_path" 2>/dev/null | cut -d',' -f1 || echo "$file_extension")

    # Get sample rate and channels
    sample_rate=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$dest_path" 2>/dev/null || echo "")
    channels=$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=noprint_wrappers=1:nokey=1 "$dest_path" 2>/dev/null || echo "")

    log "INFO" "Metadata: duration=${duration_seconds}s, format=$format, sample_rate=$sample_rate, channels=$channels"
else
    format="$file_extension"
    log "INFO" "Using file extension as format: $format"
fi

# Insert into database
log "INFO" "Inserting record into database"

sql_insert="INSERT INTO audio (file_path, filename, original_filename, duration_seconds, format, sample_rate, channels, size_bytes, tags, created_at) VALUES ("
sql_insert+="'$relative_path', "
sql_insert+="'$new_filename', "
sql_insert+="'$original_filename', "
sql_insert+="${duration_seconds:-NULL}, "
sql_insert+="'$format', "
sql_insert+="${sample_rate:-NULL}, "
sql_insert+="${channels:-NULL}, "
sql_insert+="$file_size, "
sql_insert+="'$TAGS', "
sql_insert+="'$created_timestamp'"
sql_insert+=");"

if sqlite3 "$DB_FILE" "$sql_insert"; then
    audio_id=$(sqlite3 "$DB_FILE" "SELECT last_insert_rowid();")
    log "INFO" "Record inserted successfully with ID: $audio_id"
else
    log "ERROR" "Failed to insert record into database"
    # Cleanup copied file on database error
    rm -f "$dest_path"
    exit 1
fi

log "INFO" "Ingestion complete!"
log "INFO" "  File: $dest_path"
log "INFO" "  Database ID: $audio_id"
log "INFO" "  Size: $file_size bytes"
if [[ -n "$duration_seconds" ]]; then
    log "INFO" "  Duration: $duration_seconds seconds"
fi
if [[ -n "$TAGS" ]]; then
    log "INFO" "  Tags: $TAGS"
fi

echo "Audio ingested successfully! Database ID: $audio_id"
