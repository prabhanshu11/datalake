# Datalake

A personal data lake for managing audio recordings, transcripts, and screenshots with fast SQLite-based queries and organized filesystem storage.

## Features

- **SQLite Database**: Zero-server-overhead queries with full-text search
- **Filesystem Organization**: Human-readable date-based structure (YYYY/MM/DD)
- **Fast Access**: Optimized for <10ms queries with proper indexes
- **Full-Text Search**: Search transcripts using SQLite FTS5
- **Comprehensive Logging**: Structured logging with timestamps for all operations
- **Tested**: 35+ comprehensive tests ensuring reliability
- **Containerized**: Docker support with isolated environment variables

## Quick Start (Docker - Recommended)

The datalake runs as a Docker container with both a REST API (for network access) and CLI tools.

### Automated Setup (via local-bootstrapping)

**On Laptop (where database runs):**
```bash
cd ~/Programs/local-bootstrapping
./scripts/setup-datalake.sh
```

This will:
- Set up the Datalake API service on port **8766**
- Configure auto-start on login
- Enable self-healing (restarts if crashes)
- Run health checks every 5 minutes

The API will be available at:
- **Local**: `http://localhost:8766`
- **Network**: `http://192.168.29.137:8766` (or your laptop IP)
- **Tailscale**: `http://100.103.8.87:8766`

### Manual Setup

### Prerequisites
- Docker
- Docker Compose

### Setup

1. **Build the container:**
```bash
docker-compose build
```

2. **Initialize the database:**
```bash
./docker-init.sh
```

3. **Start the API server:**
```bash
docker-compose up -d
```

The API will be running on port **8766**.

4. **Ingest audio files:**
```bash
./docker-ingest.sh path/to/audio.wav "meeting,important"
```

5. **Query data (CLI):**
```bash
./docker-query.sh
```

6. **Query data (API):**
```bash
curl http://localhost:8766/api/v1/audio
curl http://localhost:8766/api/v1/stats
```

7. **Run tests:**
```bash
./docker-test.sh
```

### Docker Helper Scripts

- **`docker-init.sh`** - Initialize database and directory structure
- **`docker-ingest.sh <file> [tags]`** - Ingest audio files into the datalake
- **`docker-query.sh`** - Open interactive query interface
- **`docker-test.sh [args]`** - Run pytest tests in container

### Docker Environment Variables

The container uses isolated environment variables (defined in `Dockerfile` and `docker-compose.yml`):

```yaml
DATA_DIR=/data              # Persistent data storage (Docker volume)
DB_FILE=/data/datalake.db   # SQLite database location
LOG_DIR=/app/logs           # Log files (Docker volume)
PROJECT_ROOT=/app           # Application root
SCHEMA_FILE=/app/schema.sql # Database schema
```

### Docker Volumes

Three persistent volumes are created:
- **`datalake-data`** - Audio, transcripts, screenshots, and database
- **`datalake-logs`** - Application logs
- **`datalake-db`** - Reserved for future use

To inspect volumes:
```bash
docker volume ls | grep datalake
docker volume inspect datalake-data
```

To backup data:
```bash
docker run --rm -v datalake-data:/data -v $(pwd):/backup alpine tar czf /backup/datalake-backup.tar.gz /data
```

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

## REST API Access

The datalake runs a FastAPI server on port **8766** providing network access to the database.

### API Endpoints

**Base URL**: `http://localhost:8766` (or laptop IP for network access)

**Interactive Documentation:**
- Swagger UI: `http://localhost:8766/docs`
- ReDoc: `http://localhost:8766/redoc`

**Core Endpoints:**
```bash
# Health check
GET /health

# List audio files (with pagination and filtering)
GET /api/v1/audio?limit=10&offset=0&tags=meeting

# Get specific audio file
GET /api/v1/audio/{id}

# List transcripts
GET /api/v1/transcripts?limit=10&offset=0

# Get specific transcript
GET /api/v1/transcripts/{id}

# Search transcripts (FTS5 full-text search)
GET /api/v1/search/transcripts?q=search_term&limit=10

# Get database statistics
GET /api/v1/stats

# List screenshots
GET /api/v1/screenshots?limit=10&offset=0
```

**Example Usage:**
```bash
# From desktop, access laptop database
curl http://100.103.8.87:8766/api/v1/audio | jq

# Search transcripts
curl "http://100.103.8.87:8766/api/v1/search/transcripts?q=meeting" | jq

# Get stats
curl http://100.103.8.87:8766/api/v1/stats | jq
```

### Network Access

**From Desktop to Laptop:**
- **Tailscale**: `http://100.103.8.87:8766`
- **Local Network**: `http://192.168.29.137:8766` (find IP with `ip addr`)

**CORS**: Enabled for all origins (suitable for local network use)

### Managing the Service

**If set up via local-bootstrapping (auto-start enabled):**
```bash
# Check status
systemctl --user status datalake.service

# Restart service
systemctl --user restart datalake.service

# Stop service
systemctl --user stop datalake.service

# Start service
systemctl --user start datalake.service

# View service logs
systemctl --user logs -f datalake.service

# View container logs
cd ~/Programs/datalake
docker-compose logs -f

# Disable auto-start
systemctl --user disable datalake.service
```

**Manual Docker management:**
```bash
# Start server
docker-compose up -d

# Stop server
docker-compose down

# Restart server
docker-compose restart

# View logs
docker-compose logs -f

# Rebuild and restart
docker-compose build && docker-compose up -d
```

## Web UI

The datalake includes a Flask-based web interface on port **5050** for browsing data and monitoring.

### Starting the Web UI

**Automated (via systemd):**
```bash
# Enable and start
systemctl --user enable --now datalake-web.service

# Check status
systemctl --user status datalake-web.service

# View logs
journalctl --user -u datalake-web.service -f
```

**Manual:**
```bash
cd ~/Programs/datalake
uv run python3 -m web.app --port 5050
```

### Web UI Endpoints

| URL | Description |
|-----|-------------|
| `http://localhost:5050/` | Home page with stats |
| `http://localhost:5050/sessions` | Browse Claude sessions |
| `http://localhost:5050/voice` | Voice typing sessions |
| `http://localhost:5050/chatgpt` | ChatGPT conversations |
| `http://localhost:5050/search` | Full-text search |
| `http://localhost:5050/memory` | Memory monitoring dashboard |
| `http://localhost:5050/memory/events` | Memory event timeline |

---

## Memory Monitoring

Monitor Claude Code memory usage with real-time charts and alerts.

### Overview

The memory monitoring system collects RAM metrics from Claude processes and stores them in the datalake for visualization and analysis.

**Data sources:**
- `/var/log/claude-memory/metrics.jsonl` - Time-series RAM data (every 10 seconds)
- `/var/log/claude-memory/events.jsonl` - Memory events (warnings, kills, restarts)

### Database Tables

```sql
-- Memory metrics (time-series RAM data)
memory_metrics (
    pid, session_id, rss_mb, memory_rate_mb_min,
    timestamp, source_device
)

-- Memory events (warnings, kills, restarts)
memory_events (
    event_type, pid, severity, message,
    details, timestamp
)
```

### Dashboard Features

**Memory Dashboard** (`/memory`):
- Real-time RAM usage chart (per PID)
- Rate of change graph (MB/min)
- Active sessions list with current RAM
- Low-memory mode toggle per session

**Event Timeline** (`/memory/events`):
- Chronological event list
- Filter by event type
- Color-coded by severity

### API Endpoints

**Flask Web UI (port 5050):**
```bash
# Get chart data (for AJAX updates)
GET /api/memory/chart-data

# List active sessions
GET /api/memory/sessions

# Toggle low-memory mode for a session
POST /api/memory/sessions/{pid}/low-memory-mode
# Body: {"enabled": true}
```

**FastAPI REST (port 8766):**
```bash
# Get today's metrics
GET /api/v1/memory/metrics/today

# Get metrics for date range
GET /api/v1/memory/metrics/range?start=2026-01-01&end=2026-01-14

# Get today's events
GET /api/v1/memory/events/today

# Get events for date range
GET /api/v1/memory/events/range?start=2026-01-01&end=2026-01-14

# List sessions
GET /api/v1/memory/sessions

# Toggle low-memory mode
POST /api/v1/memory/sessions/{pid}/low-memory-mode?enabled=true
```

### Ingesting Memory Data

**From desktop (via SSH):**
```bash
# One-time ingestion
./scripts/ingest-memory.sh --once

# Watch mode (continuous)
./scripts/ingest-memory.sh --watch

# Check connectivity
./scripts/ingest-memory.sh --check
```

**Direct parser usage:**
```bash
# Parse local log files
uv run python3 -m parsers.memory_parser --log-dir /var/log/claude-memory

# Parse from specific device
uv run python3 -m parsers.memory_parser --device desktop

# Test mode (dry run)
uv run python3 -m parsers.memory_parser --test
```

### Low-Memory Mode

When enabled for a session, creates a control file at:
```
/var/log/claude-memory/low-memory-mode/{pid}
```

The Claude memory monitoring hook reads this file and injects low-memory guidance.

---

## Getting Started (CLI Tools)

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

- [x] **Docker Container**: Containerized deployment with isolated environment ✅
- [x] **REST API**: FastAPI wrapper for HTTP access (port 8766) ✅
- [x] **Web UI**: Flask dashboard for browsing and searching (port 5050) ✅
- [x] **Memory Monitoring**: Claude Code RAM tracking with charts ✅
- [ ] **Vector Search**: Add `sqlite-vss` extension for semantic search
- [ ] **Screenshot Ingestion**: Script for screenshot ingestion with metadata
- [ ] **Transcript Ingestion**: Script for transcript ingestion with word count
- [ ] **Automatic Cleanup**: Script for managing old files and log rotation
- [ ] **Backup/Restore**: Automated backup scripts with compression
- [ ] **Loki Integration**: Centralized logging with Grafana Loki
- [ ] **S3 Backend**: Optional S3-compatible storage backend
- [ ] **Encryption**: At-rest encryption for sensitive recordings

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
