---
name: conversation-recall
description: Search through Claude Code conversation history to find and summarize past sessions on a topic, with resume commands
---

# Conversation Recall Skill

Find and summarize previous Claude Code conversations on any topic, providing session IDs with resume commands for easy continuation.

## When to Use This Skill

Use this skill when the user asks:
- "Find my conversations about X"
- "What did we discuss about Y?"
- "Show me past sessions on Z"
- "Resume work on [project/topic]"
- Any request to recall or find previous Claude Code sessions

## How It Works

1. **Search History**
   - Use `grep` to search `~/.claude/history.jsonl` for keywords
   - Extract unique session IDs related to the topic
   - Get timestamps and project paths

2. **Analyze Each Session**
   - Read first few messages to understand context
   - Extract key activities and outcomes
   - Create concise one-line summaries

3. **Present Results**
   - Format as numbered list with:
     - Session ID
     - Timestamp (human-readable)
     - One-line summary
     - Resume command: `claude --resume {session_id}`
   - Sort chronologically (oldest to newest)

## Output Format

For each conversation found, present:

```
## Found N conversations about [TOPIC]

---

**Session:** 3b8ed381-5df8-4b4f-9c11-83bed0f9357c
**Date:** 2026-01-09 17:14:17
**Project:** /home/prabhanshu
**Summary:** Discussion about LP/GP in startups and trade policy

**Resume Command:**
```bash
claude --resume 3b8ed381-5df8-4b4f-9c11-83bed0f9357c
```

**User Questions/Messages:**
[Display ALL user messages from the conversation using this command]
```bash
grep "\"sessionId\":\"<session_id>\"" ~/.claude/history.jsonl | jq -r '.display' | head -20
```

**Conversation Analysis:**
[For short conversations (< 10 messages): 2-3 lines summarizing main points]
[For longer conversations: Detailed analysis with:]
- Main topics discussed
- Direction changes/pivots in the conversation
- Key decisions or outcomes
- Salient points and directions given by user
- [Discoveries/clarifications in brackets] - anything ambiguous in user's prompt that was discovered/clarified during conversation

**Subagents:**
[Check for subagents directory - these are spawned agents during the conversation]

**Forks:**
[Check for conversation branches - separate conversations forked from this one]

---
```

## Search Strategy

### Step 1: Extract Session IDs
```bash
# Search for topic keywords and extract unique session IDs
grep -i "keyword1\|keyword2" ~/.claude/history.jsonl | \
  grep -oP '"sessionId":"[^"]+' | \
  cut -d'"' -f4 | \
  sort -u
```

### Step 2: Get Session Metadata
```bash
# For each session, get timestamp and project path
for session in {session_ids}; do
  grep "\"sessionId\":\"$session\"" ~/.claude/history.jsonl | \
    head -1 | \
    jq -r '"\(.timestamp | tonumber / 1000 | strftime("%Y-%m-%d %H:%M:%S")) - \(.project)"'
done
```

### Step 3: Extract ALL User Messages
```bash
# Get ALL user messages to show conversation flow
# Adjust head limit based on conversation length (use -20 for short, more for long)
grep "\"sessionId\":\"$session\"" ~/.claude/history.jsonl | \
  jq -r '.display' | \
  head -20
```

### Step 4: Analyze Conversation Length and Direction
```bash
# Count total messages in conversation
message_count=$(grep "\"sessionId\":\"$session\"" ~/.claude/history.jsonl | wc -l)

# If < 10 messages: brief analysis
# If >= 10 messages: detailed analysis with topics, pivots, and user directions
```

### Step 5: Check for Subagents
```bash
# Look for subagents spawned during conversation
find ~/.claude/projects/ -type d -path "*$session*/subagents" 2>/dev/null

# If found, count and list subagent files
ls ~/.claude/projects/*/$session/subagents/*.jsonl 2>/dev/null | wc -l
```

### Step 6: Check for Conversation Forks
```bash
# Forks are separate conversation branches
# Check if this conversation was resumed from another or has branches
# (Implementation TBD - need to understand Claude's fork mechanism)
```

## Conversation Analysis Guidelines

### For Short Conversations (< 10 messages)
- Provide 2-3 lines summarizing the main topic and outcome
- List key user directions or requests

### For Long Conversations (10+ messages)
Provide detailed analysis including:
1. **Main Topics Discussed** - List the primary subjects
2. **Direction Changes** - Note where the conversation pivoted or forked
3. **User's Salient Points** - Key directions, preferences, or constraints given by user
4. **Discoveries/Clarifications** - Use [brackets] to note things that were:
   - Ambiguous in user's prompt but clarified during conversation
   - Discovered through research (e.g., user said "Chamath" → discovered full name "Chamath Palihapitiya")
   - Inferred from context (e.g., "the video" → identified specific YouTube URL)
   - Expanded from abbreviations or partial information
5. **Outcomes** - What was accomplished or decided

**Example of discoveries in analysis:**
"User requested analysis of Chamath interview [discovered: Chamath Palihapitiya] about LP/GP concepts [clarified: Limited Partner / General Partner]. Downloaded video transcript [found: "Howard Lutnick: All-In in DC" from the All-In podcast, id: 182ckTL2KBA]."

### Detecting Subagents and Forks

**Subagents** are spawned agents during a conversation (Task tool usage):
```bash
# Check if conversation has subagents
ls ~/.claude/projects/-home-prabhanshu-*/[session-id]/subagents/ 2>/dev/null
```

If subagents exist, report: "This conversation spawned N subagents"

**Forks** are separate conversations branched from this one:
```bash
# Check conversation history for branching/resume patterns
# This needs to be determined by analyzing if this session was resumed from another
# or if other sessions resumed from this one
```

If forks exist, ask user: "This conversation has forks/branches. Would you like me to show the fork structure?"

If yes, display:
```
**Conversation Structure:**
Main conversation: [session-id] - [brief summary]
├─ Subagent 1: [what it worked on]
├─ Subagent 2: [what it worked on]
└─ Branch/Fork: [forked-session-id] - [brief summary]
```

## Best Practices

1. **Always Show User Messages**
   - Display ALL user questions/messages using the grep + jq command
   - This gives the user a quick view of their own conversation flow

2. **Smart Summaries**
   - Focus on WHAT was accomplished, not just what was discussed
   - Mention key files created or modified
   - Note if session ended with errors/incomplete work

3. **Chronological Order**
   - Always sort by timestamp (oldest first)
   - Helps user understand progression of work

4. **Include Context**
   - Mention project directory if relevant
   - Note if it's part of a series of related sessions

## Example Usage

User: "Find my conversations about tapo"