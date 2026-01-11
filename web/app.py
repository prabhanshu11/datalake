#!/usr/bin/env python3
"""
Datalake Web UI

Simple Flask-based web interface for browsing and searching:
- Claude Code conversations
- Voice typing sessions
- Full-text search across all content
"""

import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, g
from pathlib import Path
from flask import send_from_directory

app = Flask(__name__)

# Audio directories to search for files
AUDIO_DIRS = [
    Path.home() / 'Programs' / 'recordings',
    Path.home() / 'Programs' / 'omarchy-voice-typing' / 'recordings',
]

# Configuration
DB_PATH = os.environ.get('DATALAKE_DB',
    str(Path.home() / 'Programs' / 'datalake' / 'datalake.db'))


def get_db():
    """Get database connection for current request."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    """Close database connection at end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.route('/audio/<path:filename>')
def serve_audio(filename):
    """Serve audio files from recording directories."""
    for audio_dir in AUDIO_DIRS:
        file_path = audio_dir / filename
        if file_path.exists():
            return send_from_directory(audio_dir, filename)
    return "Audio not found", 404


@app.route('/')
def index():
    """Home page with overview stats."""
    db = get_db()

    stats = {
        'sessions': db.execute('SELECT COUNT(*) FROM claude_sessions').fetchone()[0],
        'messages': db.execute('SELECT COUNT(*) FROM claude_messages').fetchone()[0],
        'history': db.execute('SELECT COUNT(*) FROM claude_history').fetchone()[0],
        'voice_sessions': db.execute('SELECT COUNT(*) FROM voice_sessions').fetchone()[0],
        'audio_files': db.execute('SELECT COUNT(*) FROM audio').fetchone()[0],
        'transcripts': db.execute('SELECT COUNT(*) FROM transcripts').fetchone()[0],
    }

    # Recent sessions
    recent = db.execute('''
        SELECT session_id, summary, project_path, total_messages,
               total_input_tokens + total_output_tokens as total_tokens,
               source_device, started_at, rating
        FROM claude_sessions
        ORDER BY started_at DESC
        LIMIT 10
    ''').fetchall()

    return render_template('index.html', stats=stats, recent=recent)


@app.route('/sessions')
def sessions():
    """Browse all Claude sessions."""
    db = get_db()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    total = db.execute('SELECT COUNT(*) FROM claude_sessions').fetchone()[0]

    sessions = db.execute('''
        SELECT session_id, summary, project_path, total_messages,
               total_input_tokens + total_output_tokens as total_tokens,
               source_device, started_at, duration_seconds, rating
        FROM claude_sessions
        ORDER BY started_at DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset)).fetchall()

    return render_template('sessions.html',
                         sessions=sessions,
                         page=page,
                         total=total,
                         per_page=per_page)


@app.route('/session/<session_id>')
def session_detail(session_id):
    """View a single session with all messages."""
    db = get_db()

    session = db.execute('''
        SELECT * FROM claude_sessions WHERE session_id = ?
    ''', (session_id,)).fetchone()

    if not session:
        return "Session not found", 404

    messages_raw = db.execute('''
        SELECT message_uuid, message_type, role, model,
               content_text, content_thinking, content_images,
               content_tool_uses, input_tokens, output_tokens,
               timestamp, sequence_number
        FROM claude_messages
        WHERE session_id = ?
        ORDER BY sequence_number
    ''', (session['id'],)).fetchall()

    # Convert to dicts and handle tool_uses (stored as count in DB)
    messages = []
    for msg in messages_raw:
        m = dict(msg)
        tool_uses = m.get('content_tool_uses')
        # content_tool_uses is stored as a count (int), not JSON
        # Keep as int for template to check > 0
        if isinstance(tool_uses, str):
            try:
                m['content_tool_uses'] = json.loads(tool_uses)
            except json.JSONDecodeError:
                m['content_tool_uses'] = 0
        elif tool_uses is None:
            m['content_tool_uses'] = 0
        # If it's already an int, leave it as-is
        messages.append(m)

    return render_template('session_detail.html',
                         session=session,
                         messages=messages)


@app.route('/voice')
def voice_sessions():
    """Browse voice typing sessions."""
    db = get_db()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    total = db.execute('SELECT COUNT(*) FROM voice_sessions').fetchone()[0]

    sessions = db.execute('''
        SELECT vs.id, vs.session_uuid, vs.success, vs.rating, vs.created_at,
               a.filename as audio_filename, a.duration_seconds,
               t.content as transcript, t.word_count
        FROM voice_sessions vs
        LEFT JOIN audio a ON vs.audio_id = a.id
        LEFT JOIN transcripts t ON vs.transcript_id = t.id
        ORDER BY vs.created_at DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset)).fetchall()

    return render_template('voice.html',
                         sessions=sessions,
                         page=page,
                         total=total,
                         per_page=per_page)


@app.route('/search')
def search():
    """Search across all content."""
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'all')

    if not query:
        return render_template('search.html', results=None, query='')

    db = get_db()
    results = {'messages': [], 'history': [], 'transcripts': []}

    if search_type in ('all', 'messages'):
        # Search Claude messages
        results['messages'] = db.execute('''
            SELECT cm.id, cm.content_text, cm.message_type, cm.timestamp,
                   cs.session_id, cs.summary
            FROM claude_messages cm
            JOIN claude_sessions cs ON cm.session_id = cs.id
            WHERE cm.id IN (
                SELECT rowid FROM claude_messages_fts
                WHERE claude_messages_fts MATCH ?
                LIMIT 50
            )
            ORDER BY cm.timestamp DESC
        ''', (query,)).fetchall()

    if search_type in ('all', 'history'):
        # Search history
        results['history'] = db.execute('''
            SELECT id, display, session_id, timestamp
            FROM claude_history
            WHERE id IN (
                SELECT rowid FROM claude_history_fts
                WHERE claude_history_fts MATCH ?
                LIMIT 50
            )
            ORDER BY timestamp_unix DESC
        ''', (query,)).fetchall()

    if search_type in ('all', 'transcripts'):
        # Search transcripts
        results['transcripts'] = db.execute('''
            SELECT t.id, t.content, t.filename, t.created_at, t.word_count
            FROM transcripts t
            WHERE t.id IN (
                SELECT rowid FROM transcripts_fts
                WHERE transcripts_fts MATCH ?
                LIMIT 50
            )
            ORDER BY t.created_at DESC
        ''', (query,)).fetchall()

    return render_template('search.html', results=results, query=query)


@app.route('/api/rate/<item_type>/<int:item_id>', methods=['POST'])
def rate_item(item_type, item_id):
    """API to rate an item (session, message, voice session)."""
    data = request.get_json()
    rating = data.get('rating')
    notes = data.get('notes', '')

    if not rating or not (1 <= rating <= 10):
        return jsonify({'error': 'Rating must be 1-10'}), 400

    db = get_db()

    table_map = {
        'session': 'claude_sessions',
        'message': 'claude_messages',
        'voice': 'voice_sessions',
    }

    if item_type not in table_map:
        return jsonify({'error': 'Invalid item type'}), 400

    db.execute(f'''
        UPDATE {table_map[item_type]}
        SET rating = ?, rating_notes = ?
        WHERE id = ?
    ''', (rating, notes, item_id))
    db.commit()

    return jsonify({'success': True})


@app.route('/api/feedback/<int:voice_id>', methods=['POST'])
def voice_feedback(voice_id):
    """API to provide corrected transcript for voice session."""
    data = request.get_json()
    corrected = data.get('corrected_transcript', '')

    db = get_db()
    db.execute('''
        UPDATE voice_sessions
        SET corrected_transcript = ?
        WHERE id = ?
    ''', (corrected, voice_id))
    db.commit()

    return jsonify({'success': True})


@app.route('/api/stats')
def api_stats():
    """API endpoint for stats."""
    db = get_db()

    # Token usage by day
    usage = db.execute('''
        SELECT date(started_at) as date,
               SUM(total_input_tokens) as input_tokens,
               SUM(total_output_tokens) as output_tokens,
               COUNT(*) as sessions
        FROM claude_sessions
        GROUP BY date(started_at)
        ORDER BY date DESC
        LIMIT 30
    ''').fetchall()

    return jsonify({
        'daily_usage': [dict(row) for row in usage]
    })


def main():
    """Run the web server."""
    import argparse

    parser = argparse.ArgumentParser(description='Datalake Web UI')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', '-p', type=int, default=5000, help='Port')
    parser.add_argument('--debug', '-d', action='store_true', help='Debug mode')
    parser.add_argument('--db', help='Database path')

    args = parser.parse_args()

    if args.db:
        global DB_PATH
        DB_PATH = args.db

    print(f"Starting Datalake Web UI")
    print(f"Database: {DB_PATH}")
    print(f"URL: http://{args.host}:{args.port}")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
