---
name: conversation-recall
description: Search through Claude Code conversation history to find and summarize past sessions on a topic, with resume commands. Use when user asks to "find conversations", "recall past sessions", "what did we discuss", "resume work on", or "search history".
allowed-tools:
  - Bash
  - Grep
  - Read
---

# Conversation Recall Skill

## ⚠️ TWO CRITICAL RULES ⚠️

### Rule 1: ONE find-conversations call ONLY

**You get exactly ONE `find-conversations` call. Make it count with a compound OR query.**

### Rule 2: MAX 3 get-messages calls TOTAL

**After searching, drill into AT MOST 3 sessions. Not 4, not 5, not 6. Three.**

### The Budget

```
find-conversations     → 1 call
get-messages-from-current → 2-3 calls IN PARALLEL
TOTAL TOOL CALLS      → 3-4 calls
API TURNS             → 3 max (search, parallel get-messages, respond)
```

### Why These Limits?

- Sequential calls = slow (6s+ thinking per call)
- Parallel calls = fast (ONE thinking phase for all calls)
- Target: 20-30 seconds total

### How to Follow This

1. **Extract ALL keywords** - 10+ terms with OR
2. **ONE compound search** (turn 1)
3. **Pick TOP 2-3 sessions** from summaries
4. **Call ALL get-messages IN PARALLEL** (turn 2) - send 2-3 calls at once!
5. **Present findings** (turn 3) - done!

---

## Correct Example

Query: "Find multi-agent orchestration conversations"

**Turn 1 - Search:**
```bash
find-conversations "subagent OR orchestration OR controller OR worker OR Task OR parallel OR spawn" --limit 15
```

**Turn 2 - PARALLEL get-messages (call ALL at once in single response):**
```bash
# These 3 calls go in ONE message - parallel execution!
get-messages-from-current --session TOP_SESSION_1 --user-only --last 40
get-messages-from-current --session TOP_SESSION_2 --user-only --last 40
get-messages-from-current --session TOP_SESSION_3 --user-only --last 40
```

**Turn 3 - Present findings with resume commands. DONE.**

**Total: 3 turns, 4 tool calls. Target time: 20-30 seconds.**

---

## ❌ WRONG - Never Do This

```bash
# WRONG: Multiple separate searches
find-conversations "subagent"       # ← FORBIDDEN after first search
find-conversations "Task"           # ← FORBIDDEN

# WRONG: Sequential get-messages (wastes ~15s of thinking time!)
# Turn 2: get-messages --session AAA  # ← 6s thinking
# Turn 3: get-messages --session BBB  # ← 6s thinking
# Turn 4: get-messages --session CCC  # ← 6s thinking
# Total: 18s of unnecessary thinking!

# RIGHT: Parallel get-messages (ONE turn for all calls)
# Turn 2: get-messages AAA + BBB + CCC  # ← ALL in one response!

# WRONG: More than 3 sessions
get-messages-from-current --session DDD  # ✗ Over budget!

# WRONG: Duplicates
get-messages-from-current --session ABC --last 20
get-messages-from-current --session ABC --last 50  # ← Already called!
```

---

## Quick Reference: find-conversations

```bash
# COMPOUND search (PREFERRED - use for multi-concept queries)
find-conversations "tapo OR camera OR monitor OR stream" --limit 10

# Single keyword (only for simple queries)
find-conversations "git" --limit 5

# With date filter
find-conversations "voice OR typing" --since 2026-01-10 --limit 10

# Project filter
find-conversations "datalake OR sync" --project Programs --limit 10

# JSON output
find-conversations "error OR bug OR fix" --json --limit 10
```

## Quick Reference: get-messages-from-current

```bash
# User messages only (use --last 40 for sufficient context)
get-messages-from-current --session SESSION_ID --user-only --last 40

# Full messages (use --last 30-50)
get-messages-from-current --session SESSION_ID --last 40

# JSON output
get-messages-from-current --session SESSION_ID --json --last 40
```

---

## Output Format

Present findings as:

```
## Found N conversations about [TOPIC]

---

**Session:** 3b8ed381-5df8-4b4f-9c11-83bed0f9357c
**Date:** 2026-01-09 17:14:17
**Project:** /home/prabhanshu/Programs
**Messages:** 150 | **Duration:** 45m 30s
**Summary:** [Brief description from search results]

**Resume Command:**
```bash
claude --resume 3b8ed381-5df8-4b4f-9c11-83bed0f9357c
```

**Key User Messages:**
[Show 3-5 most relevant user messages from get-messages-from-current output]

---
```

---

## FTS5 Query Syntax

```bash
# OR - Match any term (USE THIS FOR MULTI-KEYWORD)
find-conversations "git OR commit OR push OR merge"

# AND (implicit with space)
find-conversations "tapo camera"  # Must have BOTH words

# Exact phrase
find-conversations '"star trek"'

# Prefix matching
find-conversations "data*"  # Matches data, database, datalake

# NOT - Exclude term
find-conversations "git NOT merge"
```

---

## Fallback: Grep (if datalake unavailable)

Only use if `find-conversations` command not found:

```bash
# Compound grep pattern (same principle - ONE search, multiple keywords)
grep -i "keyword1\|keyword2\|keyword3" ~/.claude/history.jsonl | \
  grep -oP '"sessionId":"[^"]+' | \
  cut -d'"' -f4 | \
  sort -u
```

---

## Best Practices

1. **Extract ALL keywords first** - 10+ terms with OR
2. **ONE compound search** - Never multiple find-conversations calls
3. **MAX 3 get-messages** - Pick top sessions from summaries, ignore rest
4. **4 tool calls total** - Budget strictly: 1 search + 3 drill-downs
5. **Include resume commands** - User wants to continue work
6. **Summarize findings** - Don't dump raw output

---

## Example: Complex Query

User: "Find conversations where I worked on voice typing issues after the reboot"

**Step 1: Keywords (10+ terms):**
voice, typing, hyprwhspr, transcription, whisper, audio, reboot, boot, startup, speech

**Step 2: ONE compound search (call 1/4):**
```bash
find-conversations "voice OR typing OR hyprwhspr OR transcription OR whisper OR reboot OR startup" --limit 10
```

**Step 3: Pick TOP 2-3 from summaries shown**

**Step 4: Get details (calls 2-4/4):**
```bash
get-messages-from-current --session BEST_SESSION --user-only --last 40
get-messages-from-current --session SECOND_BEST --user-only --last 40
# STOP - budget used
```

**Step 5: Present summary with resume commands. DONE.**

**Total: 3 tool calls. Budget remaining: 1 call (unused).**
