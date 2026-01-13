# HA Datalake Dashboard Requirements

**Assigned to:** subagent2
**From:** main1
**Date:** 2026-01-14 03:45 IST

## Overview

We need a **high-availability control dashboard** that shows the state of services, nodes, and jobs across both laptop and desktop. This is for the HA datalake architecture where:
- **Laptop (omarchy-1):** Primary node with battery backup
- **Desktop (omarchy):** Replica node, subject to power cuts

## Dashboard Purpose

Users need to see **at a glance**:
1. Which nodes are online/offline
2. Which services are running/failing on each node
3. Where data is accessible from
4. What jobs are running and their progress
5. System health and replication status

## Core Requirements

### 1. Node Status Grid

**Layout:** 2-column grid showing both machines

**For each node (laptop/desktop), show:**
- Node name + Tailscale IP
- Role badge: `PRIMARY` or `REPLICA`
- Status indicator with color:
  - 🟢 **Green:** Online and healthy
  - 🟡 **Yellow:** Online but degraded (some services down)
  - 🔴 **Red:** Critical issues (major services failing)
  - ⚫ **Grey:** Offline/unreachable
- Last heartbeat: "2 seconds ago" / "5 minutes ago"
- Resource usage bars (CPU, RAM, Disk)
- Quick actions: "View logs", "SSH to node"

**Example:**
```
┌─────────────────────────────────────────────────────────────┐
│ LAPTOP (omarchy-1)              DESKTOP (omarchy)           │
│ 100.103.8.87                    100.92.71.80                │
│ [PRIMARY] 🟢 Online             [REPLICA] ⚫ Offline         │
│ Last seen: 2s ago               Last seen: 3 hours ago      │
│ CPU:  [▓▓▓░░░░░░░] 30%         CPU:  N/A                   │
│ RAM:  [▓▓▓▓▓░░░░░] 50%         RAM:  N/A                   │
│ Disk: [▓▓░░░░░░░░] 20%         Disk: N/A                   │
└─────────────────────────────────────────────────────────────┘
```

### 2. Service Status Table

**Columns:** Service Name | Laptop Status | Desktop Status | Description

**Services to track:**
- `datalake-api` (FastAPI REST API, port 8766)
- `datalake-web` (Flask Web UI, port 5050)
- `claude-memory-monitor` (Memory monitoring service)
- `voice-gateway` (AssemblyAI transcription gateway, port 8765)
- `hyprwhspr` (Voice typing widget)
- `datalake-worker` (Job queue processor - future Phase 2)
- `litestream` (Database replication - future Phase 2)

**Status colors:**
- 🟢 **Green:** Running + healthy (last health check passed)
- 🟡 **Yellow:** Running + degraded (warnings, slow responses)
- 🔴 **Red:** Stopped / crashed / failed health check
- ⚫ **Grey:** Not accessible (node offline or service not installed)

**Actions per service:**
- Click to view logs
- Restart button (with confirmation)
- Health check details on hover

**Example:**
```
Service                 | Laptop        | Desktop       | Description
------------------------|---------------|---------------|---------------------------
datalake-api           | 🟢 Running    | ⚫ Offline     | REST API (port 8766)
datalake-web           | 🔴 Stopped    | ⚫ Offline     | Web UI (port 5050)
claude-memory-monitor  | 🟢 Running    | 🟢 Running    | Monitors Claude RAM usage
voice-gateway          | 🟢 Running    | 🟢 Running    | Transcription service
hyprwhspr             | 🟢 Running    | 🟢 Running    | Voice typing widget
```

### 3. Active Jobs Panel

**Show running jobs from job queue** (Phase 2 feature, design now):

For each active job:
- Job type (e.g., "WhatsApp scraping", "Voice ingestion")
- Assigned node (laptop/desktop)
- Progress bar with percentage
- Elapsed time
- Checkpoint data summary ("450/1000 messages processed")
- Actions: "View details", "Cancel", "Migrate to other node"

**Example:**
```
┌─────────────────────────────────────────────────────────────┐
│ Active Jobs (2)                                             │
├─────────────────────────────────────────────────────────────┤
│ WhatsApp Scraping (Laptop)                                  │
│ [▓▓▓▓▓▓▓▓░░] 80% - 450/1000 messages - 12m elapsed         │
│ Last checkpoint: 2 seconds ago                              │
│ [View] [Cancel] [Migrate to Desktop]                       │
├─────────────────────────────────────────────────────────────┤
│ Voice Typing Ingestion (Desktop)                            │
│ [▓▓▓░░░░░░░] 30% - 15/50 recordings - 3m elapsed           │
│ Last checkpoint: 5 seconds ago                              │
│ [View] [Cancel] [Migrate to Laptop]                        │
└─────────────────────────────────────────────────────────────┘
```

### 4. Recent Failures Panel

**Show last 10 failures from job queue** (or events):

For each failure:
- Timestamp (relative: "5 minutes ago")
- Job type or event type
- Error message (truncated)
- Retry count (e.g., "Retry 2/3")
- Actions: "Retry now", "View full logs", "Mark as resolved"

**Example:**
```
Recent Failures (3)
---
[5m ago] Voice ingestion failed: API timeout (Retry 2/3)
  Error: AssemblyAI returned 503 Service Unavailable
  [Retry Now] [View Logs]

[1h ago] WhatsApp scraping failed: Network unreachable (Retry 3/3)
  Error: Connection to 100.92.71.80 timed out
  [Give Up] [View Logs]

[3h ago] Memory monitor crashed: Permission denied
  Error: Cannot create /var/log/claude-memory
  [Mark Resolved]
```

### 5. Data Sync Status

**Show replication health** (Phase 2 feature with Litestream):

- Replication lag: "0.5 seconds behind primary" or "In sync"
- Last successful sync: "2 seconds ago"
- Unsynced record count: "0 records pending"
- Sync errors: Show any errors with timestamps
- Manual sync trigger button

**Example:**
```
┌─────────────────────────────────────────────────────────────┐
│ Database Replication Status                                 │
├─────────────────────────────────────────────────────────────┤
│ Primary: Laptop (omarchy-1)                                 │
│ Replica: Desktop (omarchy) - ⚫ OFFLINE                      │
│                                                             │
│ Replication Lag: N/A (replica offline)                      │
│ Last Sync: 3 hours ago                                      │
│ Pending Records: Unknown                                    │
│                                                             │
│ [Force Sync When Desktop Returns]                           │
└─────────────────────────────────────────────────────────────┘
```

When desktop is online:
```
│ Replica: Desktop (omarchy) - 🟢 ONLINE                       │
│                                                             │
│ Replication Lag: 0.3 seconds                                │
│ Last Sync: 1 second ago                                     │
│ Pending Records: 0                                          │
```

## Technical Implementation Notes

### Auto-Refresh
- Poll `/api/v1/control/nodes` every 5 seconds
- Update indicators without full page reload
- Use AJAX or fetch API (no full framework needed unless you want)

### API Endpoints Needed

You already have some in `api/main.py`, but may need to add:

```python
GET /api/v1/control/nodes
# Returns: [{name, ip, role, status, last_heartbeat, resources}]

GET /api/v1/control/services
# Returns: [{service_name, status_laptop, status_desktop}]

GET /api/v1/control/jobs/active
# Returns: [{job_id, job_type, assigned_node, progress, elapsed}]

GET /api/v1/control/jobs/failures
# Returns: [{timestamp, job_type, error_msg, retry_count}]

POST /api/v1/control/jobs/{job_id}/cancel
# Cancels a running job

POST /api/v1/control/jobs/{job_id}/migrate?to=desktop
# Migrates job to another node

POST /api/v1/control/services/{service}/restart?node=laptop
# Restarts a service on specified node (via SSH)

GET /api/v1/control/sync-status
# Returns: {primary_node, replica_node, lag_seconds, last_sync, pending_count, errors}
```

### Data Sources

**Node status:**
- Create `node_status` table (or read from heartbeat file)
- Track last_heartbeat timestamp
- Detect offline when `NOW() - last_heartbeat > 60 seconds`

**Service status:**
- Query via SSH: `ssh laptop systemctl --user status datalake-api`
- Parse status: `active (running)` = green, `failed` = red, `inactive` = grey
- Health checks: HTTP GET to service health endpoints

**Job status (Phase 2):**
- Query `job_queue` table WHERE status='running'

**Sync status (Phase 2):**
- Query Litestream metrics or replica database timestamp

## Design Guidelines

**Color scheme:**
- Use consistent colors: Green=good, Yellow=warning, Red=critical, Grey=offline
- Dark mode friendly (check user's datalake theme)

**Responsiveness:**
- Should work on laptop screen (1920x1080 or similar)
- Desktop-first design (not mobile-critical)

**Performance:**
- Keep auto-refresh lightweight (<100ms per poll)
- Only fetch what changed (use timestamps)

**Error handling:**
- Show friendly errors if node unreachable
- Don't crash if SSH fails or API times out

## What You Should Build

**Phase 1 (Now):**
1. Create `web/templates/control_dashboard.html`
2. Implement basic node status grid (laptop/desktop)
3. Service status table (even if some services don't exist yet, show placeholders)
4. Wire up API endpoints for node/service status
5. Test with current services (datalake-api, claude-memory-monitor)

**Phase 2 (After HA implementation):**
1. Add job queue panels (active jobs + failures)
2. Add data sync status
3. Implement job migration actions
4. Add service restart actions via SSH

## Questions / Clarifications

If you need clarification on:
- How to detect node status (heartbeat mechanism)
- Service health check logic
- SSH automation for restarts
- Any design decisions

**Update this file with questions and main1 will respond.**

## Success Criteria

When done, user should be able to:
1. Open `http://localhost:5050/control` (or `/dashboard`)
2. See at a glance which nodes are online
3. See which services are running/failing
4. Click to view logs or restart services
5. Get accurate, real-time status updates

**The dashboard is the "mission control" for the entire HA system.**

---

**Your turn, subagent2!** You've already built great dashboards for memory monitoring. This is the next level - showing the entire distributed system state. Design it well, and remember: clarity and actionability over fancy animations.

Let main1 know via git commit when you're ready for review!
