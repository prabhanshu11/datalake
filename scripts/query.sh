#!/usr/bin/env bash
# Interactive query interface for datalake
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_FILE="${DB_FILE:-$PROJECT_ROOT/datalake.db}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
LOG_FILE="$LOG_DIR/query.log"

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date -Iseconds)
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
}

# Initialize logging
mkdir -p "$LOG_DIR"

# Check if database exists
if [[ ! -f "$DB_FILE" ]]; then
    echo "ERROR: Database not found. Run ./scripts/init.sh first"
    exit 1
fi

# SQLite command with nice formatting
sqlite_query() {
    sqlite3 -column -header "$DB_FILE" "$@"
}

# Show menu
show_menu() {
    cat <<EOF

╔══════════════════════════════════════════════╗
║         Datalake Query Interface             ║
╔══════════════════════════════════════════════╝

Common Queries:
  1. List recent audio (last 10)
  2. List recent transcripts (last 10)
  3. List recent screenshots (last 10)
  4. Search transcripts (full-text)
  5. Show audio by tags
  6. Show statistics
  7. Custom SQL query
  8. Open SQLite shell
  0. Exit

EOF
    read -p "Select an option: " choice
    echo
    log "INFO" "User selected option: $choice"
}

# Query functions
list_recent_audio() {
    echo "Recent Audio Files (last 10):"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    sqlite_query "
        SELECT
            id,
            filename,
            duration_seconds || 's' as duration,
            format,
            tags,
            datetime(created_at) as created
        FROM audio
        ORDER BY created_at DESC
        LIMIT 10;
    "
}

list_recent_transcripts() {
    echo "Recent Transcripts (last 10):"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    sqlite_query "
        SELECT
            t.id,
            t.filename,
            t.word_count || ' words' as words,
            t.language,
            t.tags,
            datetime(t.created_at) as created
        FROM transcripts t
        ORDER BY t.created_at DESC
        LIMIT 10;
    "
}

list_recent_screenshots() {
    echo "Recent Screenshots (last 10):"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    sqlite_query "
        SELECT
            id,
            filename,
            width || 'x' || height as resolution,
            format,
            tags,
            datetime(created_at) as created
        FROM screenshots
        ORDER BY created_at DESC
        LIMIT 10;
    "
}

search_transcripts() {
    read -p "Enter search terms: " search_terms
    echo
    echo "Searching transcripts for: $search_terms"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "INFO" "Full-text search: $search_terms"

    sqlite_query "
        SELECT
            t.id,
            t.filename,
            snippet(transcripts_fts, 0, '>>>', '<<<', '...', 40) as snippet,
            datetime(t.created_at) as created
        FROM transcripts t
        JOIN transcripts_fts ON t.id = transcripts_fts.rowid
        WHERE transcripts_fts MATCH '$search_terms'
        ORDER BY rank;
    "
}

show_audio_by_tags() {
    read -p "Enter tag to search: " tag
    echo
    echo "Audio files tagged with: $tag"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "INFO" "Tag search: $tag"

    sqlite_query "
        SELECT
            id,
            filename,
            duration_seconds || 's' as duration,
            format,
            tags,
            datetime(created_at) as created
        FROM audio
        WHERE tags LIKE '%$tag%'
        ORDER BY created_at DESC;
    "
}

show_statistics() {
    echo "Datalake Statistics:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    echo -e "\nAudio Statistics:"
    sqlite_query "
        SELECT
            COUNT(*) as total_files,
            ROUND(SUM(duration_seconds) / 60.0, 2) || ' min' as total_duration,
            ROUND(SUM(size_bytes) / 1024.0 / 1024.0, 2) || ' MB' as total_size,
            COUNT(DISTINCT format) as formats
        FROM audio;
    "

    echo -e "\nTranscript Statistics:"
    sqlite_query "
        SELECT
            COUNT(*) as total_transcripts,
            SUM(word_count) as total_words,
            ROUND(AVG(word_count), 0) as avg_words,
            ROUND(SUM(size_bytes) / 1024.0 / 1024.0, 2) || ' MB' as total_size
        FROM transcripts;
    "

    echo -e "\nScreenshot Statistics:"
    sqlite_query "
        SELECT
            COUNT(*) as total_screenshots,
            ROUND(SUM(size_bytes) / 1024.0 / 1024.0, 2) || ' MB' as total_size,
            COUNT(DISTINCT format) as formats
        FROM screenshots;
    "

    echo -e "\nOverall Storage:"
    sqlite_query "
        SELECT
            ROUND((
                (SELECT COALESCE(SUM(size_bytes), 0) FROM audio) +
                (SELECT COALESCE(SUM(size_bytes), 0) FROM transcripts) +
                (SELECT COALESCE(SUM(size_bytes), 0) FROM screenshots)
            ) / 1024.0 / 1024.0, 2) || ' MB' as total_storage;
    "
}

custom_query() {
    read -p "Enter SQL query: " query
    echo
    echo "Executing query..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "INFO" "Custom query: $query"

    if sqlite_query "$query"; then
        echo -e "\nQuery executed successfully"
    else
        echo -e "\nQuery failed"
        log "ERROR" "Custom query failed: $query"
    fi
}

open_sqlite_shell() {
    echo "Opening SQLite shell..."
    echo "Type .quit to exit"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "INFO" "Opened SQLite shell"
    sqlite3 -column -header "$DB_FILE"
}

# Main loop
main() {
    log "INFO" "Query interface started"

    while true; do
        show_menu

        case $choice in
            1) list_recent_audio ;;
            2) list_recent_transcripts ;;
            3) list_recent_screenshots ;;
            4) search_transcripts ;;
            5) show_audio_by_tags ;;
            6) show_statistics ;;
            7) custom_query ;;
            8) open_sqlite_shell ;;
            0)
                echo "Goodbye!"
                log "INFO" "Query interface exited"
                exit 0
                ;;
            *)
                echo "Invalid option. Please try again."
                ;;
        esac

        echo
        read -p "Press Enter to continue..."
    done
}

main
