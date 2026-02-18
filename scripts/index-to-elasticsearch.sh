#!/bin/bash
# Bulk index existing data to Elasticsearch

set -e

cd "$(dirname "$0")/.."

echo "=== Elasticsearch Bulk Indexing ==="
echo "Starting at: $(date)"

# Check if Elasticsearch is running
if ! curl -s http://localhost:9200/_cluster/health >/dev/null 2>&1; then
    echo "Error: Elasticsearch not running at http://localhost:9200"
    echo "Start it with: docker-compose up -d elasticsearch"
    exit 1
fi

echo "✓ Elasticsearch is running"

# Run the indexing Python script
python3 - <<'EOF'
import sqlite3
import sys
import os
from search.es_client import DatalakeSearch

# Initialize Elasticsearch client
es = DatalakeSearch()

if not es.available:
    print("Error: Elasticsearch not available")
    sys.exit(1)

print("✓ Connected to Elasticsearch")

# Create indices
print("\n=== Creating Indices ===")
if es.create_indices():
    print("✓ Indices created/verified")
else:
    print("Error: Failed to create indices")
    sys.exit(1)

# Find database file
db_path = os.path.expanduser('~/Programs/datalake/datalake.db')
if not os.path.exists(db_path):
    print(f"Error: Database not found at {db_path}")
    sys.exit(1)

# Connect to database
db = sqlite3.connect(db_path)
db.row_factory = sqlite3.Row

# Index Claude messages
print("\n=== Indexing Claude Messages ===")
cursor = db.execute("SELECT COUNT(*) FROM claude_messages")
total_claude = cursor.fetchone()[0]
print(f"Found {total_claude} Claude messages")

indexed_claude = 0
failed_claude = 0
for row in db.execute("SELECT * FROM claude_messages"):
    msg = dict(row)
    if es.index_claude_message(msg):
        indexed_claude += 1
        if indexed_claude % 1000 == 0:
            print(f"  Indexed {indexed_claude}/{total_claude} Claude messages...")
    else:
        failed_claude += 1

print(f"✓ Indexed {indexed_claude} Claude messages ({failed_claude} failed)")

# Index ChatGPT messages
print("\n=== Indexing ChatGPT Messages ===")
cursor = db.execute("SELECT COUNT(*) FROM chatgpt_messages")
total_chatgpt = cursor.fetchone()[0]
print(f"Found {total_chatgpt} ChatGPT messages")

indexed_chatgpt = 0
failed_chatgpt = 0
for row in db.execute("SELECT * FROM chatgpt_messages"):
    msg = dict(row)
    if es.index_chatgpt_message(msg):
        indexed_chatgpt += 1
        if indexed_chatgpt % 1000 == 0:
            print(f"  Indexed {indexed_chatgpt}/{total_chatgpt} ChatGPT messages...")
    else:
        failed_chatgpt += 1

print(f"✓ Indexed {indexed_chatgpt} ChatGPT messages ({failed_chatgpt} failed)")

# Index voice transcripts
print("\n=== Indexing Voice Transcripts ===")
cursor = db.execute("SELECT COUNT(*) FROM transcripts")
total_voice = cursor.fetchone()[0]
print(f"Found {total_voice} voice transcripts")

indexed_voice = 0
failed_voice = 0
for row in db.execute("SELECT * FROM transcripts"):
    transcript = dict(row)
    if es.index_voice_transcript(transcript):
        indexed_voice += 1
        if indexed_voice % 100 == 0:
            print(f"  Indexed {indexed_voice}/{total_voice} voice transcripts...")
    else:
        failed_voice += 1

print(f"✓ Indexed {indexed_voice} voice transcripts ({failed_voice} failed)")

db.close()

# Summary
print("\n=== Indexing Summary ===")
print(f"Claude messages:    {indexed_claude}/{total_claude} ({failed_claude} failed)")
print(f"ChatGPT messages:   {indexed_chatgpt}/{total_chatgpt} ({failed_chatgpt} failed)")
print(f"Voice transcripts:  {indexed_voice}/{total_voice} ({failed_voice} failed)")
print(f"Total indexed:      {indexed_claude + indexed_chatgpt + indexed_voice}")
print(f"\nCompleted at: {__import__('datetime').datetime.now()}")
EOF

echo ""
echo "=== Verification ==="
echo "Index counts:"
curl -s http://localhost:9200/datalake-claude-messages/_count | python3 -m json.tool
curl -s http://localhost:9200/datalake-chatgpt-messages/_count | python3 -m json.tool
curl -s http://localhost:9200/datalake-voice-transcripts/_count | python3 -m json.tool

echo ""
echo "✓ Bulk indexing complete!"
