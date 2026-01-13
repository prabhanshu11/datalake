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
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB for ChatGPT zips

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
        'chatgpt': 'chatgpt_conversations',
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


@app.route('/chatgpt')
def chatgpt_conversations():
    """Browse ChatGPT conversations."""
    db = get_db()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    total = db.execute('SELECT COUNT(*) FROM chatgpt_conversations').fetchone()[0]

    conversations = db.execute('''
        SELECT id, conversation_id, title, create_time, update_time,
               model_slug, message_count, is_starred, rating
        FROM chatgpt_conversations
        ORDER BY update_time DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset)).fetchall()

    # Get import stats
    imports = db.execute('''
        SELECT COUNT(*) as count, SUM(conversation_count) as total_convos,
               SUM(message_count) as total_msgs
        FROM chatgpt_imports
    ''').fetchone()

    return render_template('chatgpt_list.html',
                         conversations=conversations,
                         page=page,
                         total=total,
                         per_page=per_page,
                         imports=imports)


@app.route('/chatgpt/<conversation_id>')
def chatgpt_detail(conversation_id):
    """View a single ChatGPT conversation."""
    db = get_db()

    conversation = db.execute('''
        SELECT * FROM chatgpt_conversations WHERE conversation_id = ?
    ''', (conversation_id,)).fetchone()

    if not conversation:
        return "Conversation not found", 404

    messages = db.execute('''
        SELECT message_id, parent_id, role, content_type, content_text,
               create_time, model_slug, sequence_number
        FROM chatgpt_messages
        WHERE conversation_id = ?
        ORDER BY sequence_number
    ''', (conversation['id'],)).fetchall()

    return render_template('chatgpt_detail.html',
                         conversation=conversation,
                         messages=messages)


@app.route('/api/import/chatgpt', methods=['POST'])
def import_chatgpt():
    """Import ChatGPT conversations from uploaded zip file."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'File must be a zip'}), 400

    # Save uploaded file temporarily
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
        file.save(tmp.name)
        tmp_path = Path(tmp.name)

    # Import using parser
    import subprocess
    import socket
    device_name = socket.gethostname()

    db_path = Path(DB_PATH)
    data_dir = db_path.parent / 'data'

    result = subprocess.run([
        'python3',
        str(db_path.parent / 'parsers' / 'chatgpt_parser.py'),
        str(tmp_path),
        '--db', str(db_path),
        '--data-dir', str(data_dir),
        '--device', device_name
    ], capture_output=True, text=True)

    # Clean up temp file
    tmp_path.unlink()

    if result.returncode != 0:
        return jsonify({'error': result.stderr}), 500

    # Parse output for stats
    output = result.stdout
    import re
    new_match = re.search(r'New conversations: (\d+)', output)
    updated_match = re.search(r'Updated conversations: (\d+)', output)
    messages_match = re.search(r'Messages imported: (\d+)', output)

    return jsonify({
        'success': True,
        'conversations_new': int(new_match.group(1)) if new_match else 0,
        'conversations_updated': int(updated_match.group(1)) if updated_match else 0,
        'messages_imported': int(messages_match.group(1)) if messages_match else 0
    })


@app.route('/api/import/chatgpt/history')
def import_chatgpt_history():
    """List past ChatGPT imports."""
    db = get_db()

    imports = db.execute('''
        SELECT id, original_filename, conversation_count, message_count,
               imported_at, source_device
        FROM chatgpt_imports
        ORDER BY imported_at DESC
    ''').fetchall()

    return jsonify([dict(row) for row in imports])


# =============================================================================
# Memory Monitoring Routes
# =============================================================================

@app.route('/memory')
def memory_dashboard():
    """Memory monitoring dashboard with RAM charts."""
    db = get_db()

    # Get stats
    try:
        # Current stats from latest metrics
        latest = db.execute('''
            SELECT rss_mb, memory_rate_mb_min
            FROM memory_metrics
            ORDER BY timestamp_unix DESC
            LIMIT 1
        ''').fetchone()

        peak = db.execute('''
            SELECT MAX(rss_mb) as peak
            FROM memory_metrics
            WHERE date(timestamp) = date('now')
        ''').fetchone()

        avg_rate = db.execute('''
            SELECT AVG(memory_rate_mb_min) as avg_rate
            FROM memory_metrics
            WHERE date(timestamp) = date('now')
        ''').fetchone()

        active = db.execute('''
            SELECT COUNT(DISTINCT pid) as count
            FROM memory_metrics
            WHERE timestamp_unix > (strftime('%s', 'now') - 300)
        ''').fetchone()

        stats = {
            'current_rss_mb': latest['rss_mb'] if latest else 0,
            'peak_rss_mb': peak['peak'] if peak else 0,
            'avg_rate': avg_rate['avg_rate'] if avg_rate and avg_rate['avg_rate'] else 0,
            'active_sessions': active['count'] if active else 0,
        }
    except Exception:
        stats = {
            'current_rss_mb': 0,
            'peak_rss_mb': 0,
            'avg_rate': 0,
            'active_sessions': 0,
        }

    # Get sessions with latest metrics
    try:
        sessions = db.execute('''
            SELECT m.pid, m.session_id, m.rss_mb, m.memory_rate_mb_min as rate,
                   m.command, m.timestamp
            FROM memory_metrics m
            INNER JOIN (
                SELECT pid, MAX(timestamp_unix) as max_ts
                FROM memory_metrics
                WHERE timestamp_unix > (strftime('%s', 'now') - 3600)
                GROUP BY pid
            ) latest ON m.pid = latest.pid AND m.timestamp_unix = latest.max_ts
            ORDER BY m.rss_mb DESC
        ''').fetchall()
    except Exception:
        sessions = []

    # Get chart data
    try:
        metrics = db.execute('''
            SELECT pid, rss_mb, timestamp
            FROM memory_metrics
            WHERE date(timestamp) = date('now')
            ORDER BY timestamp_unix ASC
        ''').fetchall()

        # Group by PID for multiple lines
        pids = {}
        labels = []
        for m in metrics:
            pid = m['pid']
            if pid not in pids:
                pids[pid] = {'label': f'PID {pid}', 'data': []}
            pids[pid]['data'].append(m['rss_mb'])
            # Only add unique timestamps
            ts = m['timestamp'].split('T')[1][:5] if 'T' in m['timestamp'] else m['timestamp']
            if ts not in labels:
                labels.append(ts)

        # Create chart data structure
        colors = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
        datasets = []
        for i, (pid, data) in enumerate(pids.items()):
            color = colors[i % len(colors)]
            datasets.append({
                'label': data['label'],
                'data': data['data'],
                'borderColor': color,
                'backgroundColor': f'{color}20',
                'fill': False,
                'tension': 0.3
            })

        chart_data = {'labels': labels, 'datasets': datasets}

        # Rate data
        rate_metrics = db.execute('''
            SELECT memory_rate_mb_min as rate, timestamp
            FROM memory_metrics
            WHERE date(timestamp) = date('now') AND memory_rate_mb_min IS NOT NULL
            ORDER BY timestamp_unix ASC
        ''').fetchall()

        rate_labels = []
        rate_values = []
        for m in rate_metrics:
            ts = m['timestamp'].split('T')[1][:5] if 'T' in m['timestamp'] else m['timestamp']
            rate_labels.append(ts)
            rate_values.append(m['rate'] or 0)

        rate_data = {'labels': rate_labels, 'values': rate_values}

    except Exception:
        chart_data = {'labels': [], 'datasets': []}
        rate_data = {'labels': [], 'values': []}

    return render_template('memory.html',
                         stats=stats,
                         sessions=sessions,
                         chart_data=chart_data,
                         rate_data=rate_data,
                         last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@app.route('/memory/events')
def memory_events():
    """Memory events timeline."""
    db = get_db()
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('type', None)
    per_page = 50
    offset = (page - 1) * per_page

    # Get stats
    try:
        total_row = db.execute('SELECT COUNT(*) as c FROM memory_events').fetchone()
        warnings_row = db.execute(
            "SELECT COUNT(*) as c FROM memory_events WHERE severity = 'warning'"
        ).fetchone()
        critical_row = db.execute(
            "SELECT COUNT(*) as c FROM memory_events WHERE severity = 'critical'"
        ).fetchone()
        kills_row = db.execute(
            "SELECT COUNT(*) as c FROM memory_events WHERE event_type = 'process_kill' AND date(timestamp) = date('now')"
        ).fetchone()

        stats = {
            'total': total_row['c'] if total_row else 0,
            'warnings': warnings_row['c'] if warnings_row else 0,
            'critical': critical_row['c'] if critical_row else 0,
            'kills': kills_row['c'] if kills_row else 0,
        }
    except Exception:
        stats = {'total': 0, 'warnings': 0, 'critical': 0, 'kills': 0}

    # Get events
    try:
        query = '''
            SELECT event_type, pid, session_id, severity, message, details, timestamp
            FROM memory_events
        '''
        params = []

        if filter_type:
            query += ' WHERE event_type = ?'
            params.append(filter_type)

        query += ' ORDER BY timestamp_unix DESC LIMIT ? OFFSET ?'
        params.extend([per_page, offset])

        events = db.execute(query, params).fetchall()
        total = stats['total']
    except Exception:
        events = []
        total = 0

    return render_template('memory_events.html',
                         events=events,
                         stats=stats,
                         page=page,
                         per_page=per_page,
                         total=total,
                         filter_type=filter_type)


@app.route('/api/memory/chart-data')
def api_memory_chart_data():
    """API endpoint for memory chart data (for AJAX updates)."""
    db = get_db()

    try:
        metrics = db.execute('''
            SELECT pid, rss_mb, memory_rate_mb_min, timestamp
            FROM memory_metrics
            WHERE date(timestamp) = date('now')
            ORDER BY timestamp_unix ASC
        ''').fetchall()

        return jsonify([dict(row) for row in metrics])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory/sessions/<int:pid>/low-memory-mode', methods=['POST'])
def toggle_low_memory_mode(pid):
    """Toggle low-memory mode for a specific session."""
    from pathlib import Path

    data = request.get_json() or {}
    enabled = data.get('enabled', True)

    try:
        control_dir = Path('/var/log/claude-memory/low-memory-mode')
        control_dir.mkdir(parents=True, exist_ok=True)

        control_file = control_dir / str(pid)

        if enabled:
            control_file.write_text('1')
        else:
            if control_file.exists():
                control_file.unlink()

        return jsonify({'success': True, 'pid': pid, 'low_memory_mode': enabled})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
