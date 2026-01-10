# Datalake

A personal data lake for managing audio recordings, transcripts, and screenshots with fast SQLite-based queries and organized filesystem storage.

## Features

- **SQLite Database**: Zero-server-overhead queries with full-text search
- **Filesystem Organization**: Human-readable date-based structure (YYYY/MM/DD)
- **Fast Access**: Optimized for <10ms queries with proper indexes
- **Full-Text Search**: Search transcripts using SQLite FTS5
- **Comprehensive Logging**: Structured logging with timestamps for all operations
- **Tested**: 35+ comprehensive tests ensuring reliability

## Directory Structure

```
~/Programs/datalake/
├── README.md                 # This file
├── schema.sql                # Database schema
├── datalake.db              # SQLite database
├── pyproject.toml           # Python project configuration
├── uv.lock                  # Dependency lock file
├── scripts/
│   ├── init.sh              # Initialize database and directories
│   ├── ingest-audio.sh      # Ingest audio files
│   └── query.sh             # Interactive query interface
├── tests/                   # Comprehensive test suite
│   ├── conftest.py
│   ├── test_database.py
│   ├── test_ingestion.py
│   ├── test_init_script.py
│   └── test_queries.py
├── logs/                    # Log files
│   ├── init.log
│   ├── ingest-audio.log
│   └── query.log
└── data/                    # Data storage (or symlink to SSD)
    ├── audio/YYYY/MM/DD/*.wav
    ├── transcripts/YYYY/MM/DD/*.txt
    └── screenshots/YYYY/MM/DD/*.png
```

## Database Schema

### Tables

#### `audio`
Stores audio file metadata.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| file_path | TEXT | Relative path from data directory |
| filename | TEXT | Current filename |
| original_filename | TEXT | Original filename before ingestion |
| duration_seconds | REAL | Audio duration in seconds |
| format | TEXT | Audio format (wav, mp3, flac, etc.) |
| sample_rate | INTEGER | Sample rate in Hz |
| channels | INTEGER | Number of audio channels |
| size_bytes | INTEGER | File size in bytes |
| tags | TEXT | Comma-separated tags |
| created_at | TEXT | ISO 8601 timestamp |
| ingested_at | TEXT | When file was added to datalake |
| metadata | TEXT | Additional JSON metadata |

#### `transcripts`
Stores transcript files and content.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| file_path | TEXT | Relative path from data directory |
| filename | TEXT | Transcript filename |
| audio_id | INTEGER | Foreign key to audio table |
| content | TEXT | Full transcript text |
| word_count | INTEGER | Number of words |
| language | TEXT | Language code (e.g., 'en') |
| confidence | REAL | Transcription confidence (0.0-1.0) |
| provider | TEXT | Provider (e.g., 'assemblyai', 'whisper') |
| size_bytes | INTEGER | File size in bytes |
| tags | TEXT | Comma-separated tags |
| created_at | TEXT | ISO 8601 timestamp |
| ingested_at | TEXT | When file was added to datalake |
| metadata | TEXT | Additional JSON metadata |

#### `screenshots`
Stores screenshot metadata.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| file_path | TEXT | Relative path from data directory |
| filename | TEXT | Screenshot filename |
| width | INTEGER | Image width in pixels |
| height | INTEGER | Image height in pixels |
| format | TEXT | Image format (png, jpg, etc.) |
| size_bytes | INTEGER | File size in bytes |
| tags | TEXT | Comma-separated tags |
| created_at | TEXT | ISO 8601 timestamp |
| ingested_at | TEXT | When file was added to datalake |
| metadata | TEXT | Additional JSON metadata |

#### `transcripts_fts`
FTS5 virtual table for full-text search on transcripts.

### Indexes

Optimized indexes for common queries:
- `idx_audio_created_at`: Fast queries by date
- `idx_audio_tags`: Fast tag filtering
- `idx_audio_format`: Filter by audio format
- `idx_transcripts_created_at`: Fast queries by date
- `idx_transcripts_audio_id`: Join optimization
- `idx_transcripts_tags`: Fast tag filtering
- `idx_screenshots_created_at`: Fast queries by date
- `idx_screenshots_tags`: Fast tag filtering

## Getting Started

### Prerequisites

- Bash shell
- SQLite3
- Python 3.13+ (for running tests)
- `uv` (Python package manager)
- `ffprobe` (optional, for audio metadata extraction)

### Installation

1. Clone or navigate to the datalake directory:
```bash
cd ~/Programs/datalake
```

2. Initialize the database and directory structure:
```bash
./scripts/init.sh
```

This will:
- Create the SQLite database from `schema.sql`
- Set up the data directory structure
- Set proper file permissions (755 for directories, 644 for files)
- Create log directories

### Basic Usage

#### Ingest Audio Files

```bash
# Basic ingestion
./scripts/ingest-audio.sh path/to/audio.wav

# With tags
./scripts/ingest-audio.sh recording.wav "meeting,work,important"
```

The script will:
1. Copy the file to `data/audio/YYYY/MM/DD/`
2. Extract metadata using `ffprobe` (if available)
3. Insert a record into the SQLite database
4. Log all operations

#### Query Data

```bash
./scripts/query.sh
```

This opens an interactive menu with options:
1. List recent audio (last 10)
2. List recent transcripts (last 10)
3. List recent screenshots (last 10)
4. Search transcripts (full-text)
5. Show audio by tags
6. Show statistics
7. Custom SQL query
8. Open SQLite shell

#### Direct SQLite Queries

```bash
# List all audio files
sqlite3 datalake.db "SELECT filename, duration_seconds, tags FROM audio ORDER BY created_at DESC LIMIT 10;"

# Search transcripts
sqlite3 datalake.db "SELECT t.filename, snippet(transcripts_fts, 0, '>>>', '<<<', '...', 40) FROM transcripts t JOIN transcripts_fts ON t.id = transcripts_fts.rowid WHERE transcripts_fts MATCH 'search terms';"

# Get statistics
sqlite3 datalake.db "SELECT COUNT(*) as total, ROUND(SUM(duration_seconds)/60, 2) as minutes FROM audio;"
```

## Running Tests

The project includes a comprehensive test suite with 35+ tests.

```bash
# Run all tests
uv run pytest -v

# Run specific test file
uv run pytest tests/test_database.py -v

# Run with coverage
uv run pytest --cov=. --cov-report=html
```

Test coverage includes:
- Database schema validation
- Audio ingestion workflow
- Query functionality
- Error handling
- File permissions
- Logging verification
- Full-text search
- Data integrity constraints

## Logging

All operations are logged with structured timestamps:

```
[2026-01-10T12:00:00+05:30] [INFO] Starting ingestion of: audio.wav
[2026-01-10T12:00:00+05:30] [INFO] File copied successfully
[2026-01-10T12:00:00+05:30] [INFO] Record inserted successfully with ID: 42
```

Log files are stored in `logs/`:
- `init.log`: Initialization operations
- `ingest-audio.log`: Audio ingestion operations
- `query.log`: Query operations

## Data Migration

### From omarchy-voice-typing

If you have existing data in `~/Programs/recordings/` and `~/Programs/transcripts/`, you can migrate it:

```bash
# Initialize datalake first
./scripts/init.sh

# Migrate audio files
for file in ~/Programs/recordings/*.wav; do
    ./scripts/ingest-audio.sh "$file" "migrated,voice-typing"
done

# TODO: Create similar script for transcripts and screenshots
```

### Manual Migration Script

Create a migration script:

```bash
#!/usr/bin/env bash
# migrate.sh - Migrate existing data to datalake

SOURCE_AUDIO=~/Programs/recordings
SOURCE_TRANSCRIPTS=~/Programs/transcripts

# Migrate audio
echo "Migrating audio files..."
for audio in "$SOURCE_AUDIO"/*.wav; do
    [ -f "$audio" ] || continue
    echo "Ingesting: $audio"
    ./scripts/ingest-audio.sh "$audio" "migrated"
done

# TODO: Add transcript and screenshot migration
echo "Migration complete!"
```

## Environment Variables

Scripts support environment variables for flexibility:

- `DATA_DIR`: Override data directory location (default: `./data`)
- `DB_FILE`: Override database file path (default: `./datalake.db`)
- `LOG_DIR`: Override log directory (default: `./logs`)
- `PROJECT_ROOT`: Override project root (default: script parent directory)
- `SCHEMA_FILE`: Override schema file path (default: `./schema.sql`)

Example:
```bash
# Use custom data directory on SSD
export DATA_DIR=/mnt/data-ssd/datalake
./scripts/init.sh
```

## Future Enhancements

- [ ] **Vector Search**: Add `sqlite-vss` extension for semantic search
- [ ] **REST API**: FastAPI/Flask wrapper for HTTP access
- [ ] **Web UI**: Simple dashboard for browsing and searching
- [ ] **Screenshot Ingestion**: Script for screenshot ingestion
- [ ] **Transcript Ingestion**: Script for transcript ingestion
- [ ] **Automatic Cleanup**: Script for managing old files
- [ ] **Backup/Restore**: Automated backup scripts
- [ ] **Loki Integration**: Centralized logging with Grafana Loki
- [ ] **Docker Container**: Containerized deployment with isolated environment

## Containerization (Planned)

To isolate environment variables and improve deployment:

```yaml
# docker-compose.yml (planned)
version: '3.8'
services:
  datalake:
    build: .
    environment:
      - DATA_DIR=/data
      - DB_FILE=/app/datalake.db
    volumes:
      - ./data:/data
      - ./logs:/app/logs
```

## Contributing

When making changes:

1. Update relevant tests in `tests/`
2. Run the full test suite: `uv run pytest -v`
3. Ensure all tests pass
4. Update this README if adding features
5. Follow the coding style in existing scripts

## License

Personal project - see owner information in CLAUDE.md

## Contact

- GitHub: prabhanshu11
- Email: mail.prabhanshu@gmail.com
