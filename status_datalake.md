# Datalake Integration Status

**Assigned to:** subagent2 (Jr. SWE from IIT-Bombay)
**Coordinator:** main1 (General Engineer/Architect on desktop)
**Last updated:** 2026-01-14 04:40 IST
**Location:** Running on LAPTOP to save desktop RAM

## Current Status
**PHASE 3 COMPLETE** - HA Control Dashboard deployed ✅

## UPDATE FROM subagent2 (2026-01-14 04:40 IST) - HA CONTROL DASHBOARD LIVE!

**Phase 3 implementation complete:**
- ✅ Created `/control` route with node status grid
- ✅ Created `control_dashboard.html` template with dark theme
- ✅ Implemented `/api/control/nodes` endpoint (CPU/RAM/Disk for local, ping for remote)
- ✅ Implemented `/api/control/services` endpoint (systemd + docker status)
- ✅ Auto-refresh every 5 seconds via JavaScript
- ✅ All services detected correctly on both nodes

**Dashboard features:**
- Node status grid showing laptop (PRIMARY) and desktop (REPLICA)
- Resource usage bars (CPU, RAM, Disk) for local node
- Service status table with live status indicators
- Color-coded status: green=running, red=stopped, grey=offline

**Tested and working:**
- `http://localhost:5050/control` - Dashboard renders correctly
- `/api/control/nodes` - Returns both nodes with status
- `/api/control/services` - Returns all 5 services with status on both nodes

**Services detected:**
- datalake-api (Docker)
- datalake-web (systemd-user) - Running on laptop
- claude-memory-monitor (systemd-user) - Running on laptop
- voice-gateway (systemd-user) - Running on both
- hyprwhspr (systemd-user) - Running on both

## UPDATE FROM subagent2 (2026-01-14 03:52 IST) - MEMORY DASHBOARD LIVE!

**All systems operational:**
- ✅ Flask Web UI running on port 5050 via systemd (`datalake-web.service`)
- ✅ Auto-recovery configured (Restart=always)
- ✅ Dashboard accessible at http://localhost:5050/memory
- ✅ 3 metrics loaded from desktop test
- ✅ Timezone bug fixed (SQLite date queries now use localtime)

**Services status:**
- `datalake-web.service`: Active (running) with auto-recovery
- Docker API (port 8766): Running with auto-recovery

**Bug fixes this session:**
1. Template None handling - fixed format filters for None values
2. Timezone issue - SQLite `date('now')` → `date('now', 'localtime')`

## 🎉 UPDATE FROM main1 (2026-01-14 03:40 IST) - PHASE 1B DEPLOYED!

**Phase 1A+1B are COMPLETE on desktop:**
- ✅ 8GB SSD swap deployed (12GB total with zram)
- ✅ `/var/log/claude-memory/` directory created and active
- ✅ `claude-memory-monitor.service` running (systemd user service)
- ✅ Memory metrics logging every 10 seconds
- ✅ Your ingestion tested successfully: 3 metrics + 3 events ingested
- ✅ Memory calculation bug fixed (was 20x overreporting, now accurate)

**Real data is flowing:** Desktop is logging metrics.jsonl + events.jsonl

**Flask Web UI Issue (needs your decision):**
- FastAPI (port 8766): Running with auto-recovery ✅
- Flask Web UI (port 5050): NOT running with auto-recovery ⚠️
- Your memory dashboard at `/memory` requires Flask
- Decision needed: Add Flask to Docker? Separate systemd service? Manual start?

## UPDATE FROM subagent2 (2026-01-14 03:05 IST)

**ALL CODE IS READY!** The following has been implemented:

### Files Created/Modified:
1. `scripts/migrate-add-memory.sql` - Schema migration (APPLIED)
2. `parsers/memory_parser.py` - JSONL parser for metrics and events (TESTED)
3. `api/main.py` - Added 6 memory API endpoints
4. `web/templates/memory.html` - Dashboard with Chart.js charts
5. `web/templates/memory_events.html` - Event timeline view
6. `web/app.py` - Added memory routes
7. `scripts/ingest-memory.sh` - Remote ingestion script

### What's Ready:
- ✅ Database tables: `memory_metrics`, `memory_events` (with indexes)
- ✅ Parser tested with mock data (2 metrics, 1 event parsed successfully)
- ✅ Dashboard UI with RAM charts, rate of change graph, session list
- ✅ Event timeline with filtering by type
- ✅ All API endpoints implemented
- ✅ Remote ingestion script (SSH to desktop, copy logs, parse)

### What's Working Now:
- ✅ `/var/log/claude-memory/` exists with real data on desktop
- ✅ Ingestion tested: `python3 parsers/memory_parser.py --device desktop` works
- ✅ Database populated with metrics and events
- ✅ Dashboard UI templates exist

### Flask Auto-Recovery Decision Needed:
Current state:
- FastAPI REST API (port 8766): Auto-recovers via Docker `unless-stopped`
- Flask Web UI (port 5050): Manual start only

Options:
1. **Add Flask to existing Docker container** (recommended for simplicity)
2. **Create separate systemd service** `datalake-web.service` (better isolation)
3. **Keep manual** (run when needed: `cd ~/Programs/datalake && uv run python3 -m web.app`)

**Your call - pick what fits your architecture best!**

## UPDATE FROM main1 (2026-01-14)

**The /var/log/claude-memory/ directory doesn't exist yet - this is expected!**

The Claude memory monitoring service (Phase 1B) will be deployed by main1 soon. Until then:

**Your tasks (do these in parallel):**
1. ✅ Set up datalake project structure (if it doesn't exist) - **DONE**
2. ✅ Design database schema for Claude memory data - **DONE**
3. ✅ Create ingestion pipeline code (it will work once logs exist) - **DONE**
4. ✅ Build dashboard UI mockup/prototype - **DONE**
5. ⏸️ Wait for /var/log/claude-memory/ to appear before testing ingestion

**Timeline:**
- Phase 1A (swap setup): Being deployed by subagent3 (20-30 min)
- Phase 1B (monitoring service): Will be deployed by main1 after Phase 1A (~1 hour)
- Once Phase 1B is done, /var/log/claude-memory/ will exist with real data
- Then you can test your ingestion pipeline

**Action:** Focus on project setup, schema design, and building the pipeline. Don't wait idle - get the code ready so when the logs appear, you can immediately start ingesting.

## Coordination Protocol

**IMPORTANT - You are running on the laptop, main1 is on desktop:**
- Desktop: `100.92.71.80` (omarchy)
- Laptop: `100.103.8.87` (omarchy-1)
- SSH from laptop to desktop: `ssh prabhanshu@100.92.71.80`
- SSH from desktop to laptop: `ssh prabhanshu@100.103.8.87`

**Status Check Frequency:**
- **You (subagent2):** Check this file for updates from main1 **every 30 minutes**
- **main1:** Will check this file periodically via SSH from desktop
- Use git commits with descriptive messages for timeline tracking

**When to commit:**
- After completing each implementation task
- After making architectural decisions
- After hitting blockers
- Before requesting input from main1

**Commit message format:**
```
[datalake] Brief description

- Detailed point 1
- Detailed point 2
- Status: [In Progress/Blocked/Needs Review]
```

**Flexibility Note:**
If datalake project doesn't exist or isn't set up, focus on:
1. Creating the project structure first
2. Setting up basic ingestion
3. Documenting what's needed
main1 will pivot to other tasks if this takes longer than expected.

## Task Overview

Integrate Claude Code memory monitoring logs into the datalake project to create a unified dashboard for RAM tracking, event monitoring, and session control.

## Requirements

### Data Sources to Ingest

1. **`/var/log/claude-memory/metrics.jsonl`** - Time-series RAM data
   - Updated every 10 seconds by claude-memory-monitor service
   - Contains: timestamp, PID, RSS, memory rate (MB/min), session info
   - Format: One JSON object per line

2. **`/var/log/claude-memory/events.jsonl`** - Structured event log
   - Hook triggers (warn/block)
   - Skill invocations
   - Process kills (PID, command)
   - Restart events (reason, timestamp)
   - Format: One JSON object per line

### Dashboard Views Required

#### View 1: Today's RAM Usage Chart
- X-axis: Time (00:00 to 23:59)
- Y-axis: RAM usage (MB)
- Multiple lines: One per Claude session (by PID)
- Update in real-time or near-real-time

#### View 2: Rate of Change Graph
- X-axis: Time
- Y-axis: Memory growth rate (MB/min)
- Shows velocity of memory consumption
- Alert threshold line at 250 MB/min

#### View 3: Custom Date Range Selector
- Allow user to select start and end dates
- Display RAM usage and events for selected range
- Export functionality (CSV/JSON)

#### View 4: Claude Sessions List
For each detected Claude session, show:
- **PID** - Process ID
- **RAM Usage** - Current RSS in MB
- **Conversation Title** - Extract from `~/.claude/history.jsonl` (initial user prompt)
- **Plan Summary** - If session has a plan file, show brief summary
- **Last Messages** - Last user message and last Claude response
- **Status** - Active/Terminated
- **Low Memory Mode Toggle** - Button to enable/disable

#### View 5: Event Timeline
- Chronological list of events from events.jsonl
- Filter by type: hooks, kills, restarts, skills
- Click to see event details
- Color-coded by severity (warning=yellow, critical=red)

### API Endpoints to Implement

```
GET /api/sessions
- Returns list of all Claude sessions with metadata

POST /api/sessions/{pid}/low-memory-mode
- Toggles low-memory mode for a specific session
- Body: {"enabled": true/false}

GET /api/metrics/today
- Returns today's RAM chart data (JSON array)

GET /api/metrics/range?start=YYYY-MM-DD&end=YYYY-MM-DD
- Returns metrics for date range

GET /api/events/today
- Returns today's events (JSON array)

GET /api/events/range?start=YYYY-MM-DD&end=YYYY-MM-DD
- Returns events for date range
```

## Approach

### Step 1: Review Datalake Architecture
```bash
cd ~/Programs/datalake
tree -L 2 -h
cat README.md
```

Understand:
- What tech stack is datalake using? (Python/Node.js/Go?)
- Database: PostgreSQL/SQLite/MongoDB?
- Frontend: React/Vue/TUI?
- How are logs currently ingested?

### Step 2: Design Schema
Create schema for Claude memory data:

**Tables/Collections needed:**
- `claude_sessions` - Session metadata
- `memory_metrics` - Time-series RAM data
- `memory_events` - Event log entries

Document schema in `docs/claude-memory-schema.md`

### Step 3: Create Ingestion Pipeline
Implement log tailing and parsing:

1. Tail `/var/log/claude-memory/metrics.jsonl` continuously
2. Parse each line (JSON)
3. Insert into database
4. Handle log rotation gracefully

Possible implementation:
- Systemd service that runs ingestion script
- Or integrate into existing datalake ingestion

### Step 4: Implement Dashboard UI
Based on datalake's existing UI framework:

1. Create RAM chart component (use charting library like Chart.js, D3.js, or terminal charts)
2. Create event timeline component
3. Create sessions list with controls
4. Wire up to API endpoints

### Step 5: Add Session Control API
Implement the API endpoints listed above.

For low-memory mode toggle:
- API writes to `/var/log/claude-memory/low-memory-mode/{pid}`
- Hook reads this file and injects guidance into Claude conversation

### Step 6: Testing
1. Generate test data (simulate Claude sessions)
2. Verify ingestion works
3. Verify dashboard displays correctly
4. Test API endpoints with curl

## Tasks

- [x] Review datalake architecture and tech stack
- [x] Design schema for Claude memory data
- [x] Create ingestion pipeline for metrics.jsonl
- [x] Create ingestion pipeline for events.jsonl
- [x] Implement Dashboard UI - RAM chart
- [x] Implement Dashboard UI - Rate of change graph
- [x] Implement Dashboard UI - Events timeline
- [x] Implement Dashboard UI - Sessions list
- [x] Implement API endpoint: GET /api/sessions
- [x] Implement API endpoint: POST /api/sessions/{pid}/low-memory-mode
- [x] Implement API endpoint: GET /api/metrics/today
- [x] Implement API endpoint: GET /api/metrics/range
- [x] Implement API endpoint: GET /api/events/today
- [x] Implement API endpoint: GET /api/events/range
- [ ] Test ingestion with real Claude session (waiting for data source)
- [ ] Test dashboard rendering with real data
- [ ] Test session control (low-memory mode toggle)
- [ ] Document setup in datalake/README.md

## Completed

- Schema migration applied
- Parser created and tested
- Dashboard UI created
- API endpoints implemented
- Ingestion script created

## UPDATE FROM main1 (2026-01-14 04:20 IST) - NEW TASK

**Phase 2 is COMPLETE - great work on the memory dashboard!**

**Phase 3 Task: Build HA Control Dashboard**

See detailed requirements in `DASHBOARD_REQUIREMENTS.md` (created at 3:40am).

**What to build:**
1. Control dashboard at `/control` showing laptop + desktop nodes
2. Service status table (which services are running on each machine)
3. Node status grid with health indicators
4. API endpoints for node/service status

**Key difference from Phase 2:**
- Phase 2: Memory dashboard (Claude RAM usage) - **DONE** ✅
- Phase 3: HA control dashboard (laptop/desktop services, replication status)

**Start with:**
1. Read `DASHBOARD_REQUIREMENTS.md` carefully
2. Create basic `/control` route in `web/app.py`
3. Create `web/templates/control_dashboard.html` with node status grid
4. Implement `/api/v1/control/nodes` endpoint

**Don't wait - start building Phase 3 now!** The requirements are all documented.

## Previous Blockers (RESOLVED)

- ~~Waiting for `/var/log/claude-memory/`~~ - **RESOLVED** by main1 ✅
- ~~Flask auto-recovery decision~~ - **RESOLVED** (systemd service created) ✅

## Next Steps

1. Review datalake codebase structure
2. Document tech stack and architecture
3. Propose schema design (update this file with schema)
4. Get approval from main1 before implementing

## Schema Design (IMPLEMENTED)

```sql
-- Memory metrics (time-series RAM data from metrics.jsonl)
CREATE TABLE IF NOT EXISTS memory_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid INTEGER NOT NULL,
    session_id TEXT,
    rss_bytes INTEGER NOT NULL,
    rss_mb REAL NOT NULL,
    memory_rate_mb_min REAL,
    command TEXT,
    timestamp TEXT NOT NULL,
    timestamp_unix INTEGER NOT NULL,
    source_device TEXT NOT NULL DEFAULT 'desktop',
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Memory events (from events.jsonl)
CREATE TABLE IF NOT EXISTS memory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    pid INTEGER,
    session_id TEXT,
    severity TEXT DEFAULT 'info',
    message TEXT,
    details TEXT,
    timestamp TEXT NOT NULL,
    timestamp_unix INTEGER NOT NULL,
    source_device TEXT NOT NULL DEFAULT 'desktop',
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes applied for fast queries
```

## Tech Stack (DOCUMENTED)

**Backend:** Python 3.13+ with Flask (web UI on port 5000) + FastAPI (REST API on port 8766)
**Frontend:** Jinja2 templates + Chart.js for charting
**Database:** SQLite with FTS5 full-text search
**Deployment:** Docker containerized (or local via `uv run`)

## Communication with main1

If you encounter blockers or have questions:
1. Update the "Blocked On" section above
2. main1 will check this file periodically
3. Continue with unblocked tasks in the meantime

## Notes for subagent2

- You are a Jr. SWE from IIT-Bombay
- Focus on clean, maintainable code
- Follow datalake's existing patterns and conventions
- Document your design decisions
- Update this file frequently with progress
- Commit your changes incrementally
- Ask questions if you're unsure about approach
