# Datalake v2.0 - Progress (Internal)

## Current State (2026-01-11)

### Completed
- [x] Extended schema (schema_v2.sql) with:
  - Claude Code conversations (sessions, messages, subagents, history)
  - Email (Gmail) tables (accounts, threads, messages, attachments)
  - Voice typing sessions (links audio + transcript + context)
  - Terminal logging (Ghostty sessions and output)
  - Sync and device management tables
  - FTS5 full-text search for all text content
  - Views for common queries (v_recent_claude_sessions, v_voice_sessions, v_token_usage_daily)

- [x] Parser created (parsers/claude_parser.py):
  - Parses history.jsonl (user prompt history)
  - Parses session JSONL files (full conversations)
  - Extracts token usage, thinking content, tool calls
  - Tracks parent-child relationships for conversation trees
  - Detects subagents

- [x] Initial data ingestion:
  - **943 history entries** ingested
  - **60 sessions** parsed
  - **22,751 messages** stored
  - Top session: 3,518 messages, 376K tokens

### In Progress
- [ ] Laptop database setup (primary storage)
- [ ] Desktop → laptop sync mechanism

### Pending
- [ ] Voice typing log integration
- [ ] Web UI (search, navigation, expanding thinking)
- [ ] Rating/feedback system
- [ ] Ghostty terminal logging

## Architecture Decisions

### Storage Hierarchy
1. **Laptop** = Primary storage (always-on NAS-like role)
2. **Desktop** = Secondary with local cache (syncs to laptop)
3. **Future NAS** = Eventually replace laptop as primary

### Sync Strategy
- Local database on each device for fast queries
- Periodic sync to primary (laptop) via Tailscale
- Use device-specific flags in records (source_device column)

### Data Model Insights

**Claude Code Structure:**
```
~/.claude/
├── history.jsonl              # User prompts only (simple)
├── projects/{encoded-path}/
│   ├── {session_id}.jsonl     # Full conversation
│   ├── {session_id}/          # Session directory
│   │   └── agent-*.jsonl      # Subagent conversations
└── debug/{session_id}.txt     # Debug dumps (text)
```

**Message Types in JSONL:**
- `type: "summary"` - Auto-generated summary
- `type: "user"` - User message with images, pasted content
- `type: "assistant"` - Response with thinking, tool_use, usage stats

**Key Fields:**
- `parentUuid` / `uuid` - Conversation tree
- `isSidechain` - Branch detection
- `message.usage` - Token counts (input, output, cache)
- `message.model` - Which model was used
- `content[type=thinking]` - Extended thinking content

## Known Issues

1. **Some sessions not parsed** - 163 sessions found, only 60 ingested
   - Need to investigate empty/malformed JSONL files
   - Some may be subagent-only sessions

2. **Subagent parsing incomplete** - Shows 0 subagents
   - Directory structure exists but parsing needs refinement

## Session 2026-01-11 Progress

### Completed This Session
- [x] Laptop database initialized (38 sessions, 423 history entries)
- [x] Desktop database has 60 sessions, 943 history, 22,751 messages
- [x] Created sync script (scripts/sync-to-primary.sh)

### Next Session Tasks

1. Test and refine sync script
2. Test full-text search performance
3. Build minimal web UI
4. Integrate voice typing logs

## File Locations

- Schema: `~/Programs/datalake/schema_v2.sql`
- Parser: `~/Programs/datalake/parsers/claude_parser.py`
- Init script: `~/Programs/datalake/scripts/init-v2.sh`
- Database: `~/Programs/datalake/datalake.db`
