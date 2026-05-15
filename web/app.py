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
import time
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, g, Response
from pathlib import Path
from flask import send_from_directory
from search.es_client import DatalakeSearch

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
LOCAL_FILES_DB = os.environ.get('FILES_DB',
    str(Path.home() / 'Programs' / 'takeout-parser' / 'local-index.db'))
DELETION_LOG_DB = os.environ.get('DELETION_LOG_DB',
    str(Path.home() / 'Programs' / 'utilities' / 'google-download' / 'deletion' / 'deletion_log.db'))


def get_db():
    """Get database connection for current request."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def get_files_db():
    """Get files database connection for current request."""
    if 'files_db' not in g:
        if not os.path.exists(LOCAL_FILES_DB):
            return None
        g.files_db = sqlite3.connect(LOCAL_FILES_DB)
        g.files_db.row_factory = sqlite3.Row
    return g.files_db


def log_action(action, scope, payload):
    """Append-only action log inside datalake.db (gets backed up via the standard sync).

    action: short verb ('photo_review_set', 'deletion_status_set', ...)
    scope:  e.g. 'photos:2018:03' or 'photos:file_id=1042'
    payload: dict; serialized as JSON
    """
    try:
        conn = get_db()  # datalake.db
        conn.execute("""
            CREATE TABLE IF NOT EXISTS action_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              action TEXT NOT NULL,
              scope TEXT,
              payload TEXT
            )
        """)
        conn.execute(
            "INSERT INTO action_log (action, scope, payload) VALUES (?, ?, ?)",
            (action, scope, json.dumps(payload, default=str))
        )
        conn.commit()
    except Exception as e:
        app.logger.warning(f"action_log write failed: {e}")


def get_deletion_db():
    """Get deletion-log database connection. Creates schema if missing."""
    if 'deletion_db' not in g:
        Path(DELETION_LOG_DB).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DELETION_LOG_DB)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deletion_log (
              year INTEGER NOT NULL,
              month INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              count_local INTEGER,
              count_google INTEGER,
              bytes_freed INTEGER,
              deleted_at TEXT,
              note TEXT,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (year, month)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS photo_review (
              file_id INTEGER PRIMARY KEY,
              status TEXT NOT NULL DEFAULT 'pending',
              note TEXT,
              reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        g.deletion_db = conn
    return g.deletion_db


@app.teardown_appcontext
def close_db(error):
    """Close database connections at end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()
    files_db = g.pop('files_db', None)
    if files_db is not None:
        files_db.close()
    deletion_db = g.pop('deletion_db', None)
    if deletion_db is not None:
        deletion_db.close()


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

    # Files stats from local files DB (all services)
    files_db = get_files_db()
    if files_db:
        try:
            files_row = files_db.execute(
                "SELECT COUNT(*) FROM files"
            ).fetchone()
            stats['total_files'] = files_row[0] if files_row else 0
        except Exception:
            stats['total_files'] = 0
    else:
        stats['total_files'] = 0

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

    # Build tool name lookups from tool_events table
    tool_events = db.execute('''
        SELECT message_uuid, result_message_uuid, tool_name, file_path
        FROM claude_tool_events
        WHERE session_id = ?
        ORDER BY sequence_number
    ''', (session['id'],)).fetchall()

    tools_by_msg = {}       # assistant msg → tool names (tool_use)
    tools_by_result = {}    # user msg → tool names (tool_result)
    for te in tool_events:
        name = te['tool_name']
        fp = te['file_path'] or ''
        label = name + (' ' + fp.split('/')[-1] if fp else '')
        tools_by_msg.setdefault(te['message_uuid'], []).append(label)
        if te['result_message_uuid']:
            tools_by_result.setdefault(te['result_message_uuid'], []).append(label)

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

        # Attach tool names for display
        m['tool_names'] = tools_by_msg.get(m['message_uuid'], []) or tools_by_result.get(m['message_uuid'], [])
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
    """Search across all content using Elasticsearch with SQLite FTS fallback."""
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'all')

    if not query:
        return render_template('search.html', results=None, query='', backend=None)

    # Initialize Elasticsearch
    es = DatalakeSearch()
    search_backend = None

    # Try Elasticsearch first
    if es.available:
        try:
            # Map search type to ES sources
            sources = []
            if search_type in ('all', 'messages'):
                sources.extend(['claude', 'chatgpt'])
            if search_type in ('all', 'transcripts'):
                sources.append('voice')

            es_results = es.search(query=query, sources=sources, limit=50)

            if es_results is not None:
                # Convert ES results to format expected by template
                results = {
                    'messages': es_results.get('claude', []),
                    'chatgpt': es_results.get('chatgpt', []),
                    'transcripts': es_results.get('voice', []),
                    'history': []  # Not using history search anymore
                }
                search_backend = 'elasticsearch'

                return render_template('search.html',
                                     results=results,
                                     query=query,
                                     backend=search_backend,
                                     search_type=search_type)
        except Exception as e:
            # Log error but continue to fallback
            print(f"Elasticsearch search error: {e}")

    # Fallback to SQLite FTS
    db = get_db()
    results = {'messages': [], 'history': [], 'chatgpt': [], 'transcripts': []}
    search_backend = 'sqlite'

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

        # Search ChatGPT messages
        results['chatgpt'] = db.execute('''
            SELECT cm.id, cm.content_text, cm.role, cm.create_time,
                   cc.conversation_id, cc.title
            FROM chatgpt_messages cm
            JOIN chatgpt_conversations cc ON cm.conversation_id = cc.id
            WHERE cm.id IN (
                SELECT rowid FROM chatgpt_messages_fts
                WHERE chatgpt_messages_fts MATCH ?
                LIMIT 50
            )
            ORDER BY cm.create_time DESC
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

    return render_template('search.html',
                         results=results,
                         query=query,
                         backend=search_backend,
                         search_type=search_type)


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


@app.route('/api/health')
def api_health():
    """API health check endpoint."""
    es = DatalakeSearch()

    health = {
        'database': 'ok',
        'elasticsearch': 'ok' if es.available else 'unavailable',
        'search_backend': 'elasticsearch' if es.available else 'sqlite'
    }

    return jsonify(health)


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
            WHERE date(timestamp) = date('now', 'localtime')
        ''').fetchone()

        avg_rate = db.execute('''
            SELECT AVG(memory_rate_mb_min) as avg_rate
            FROM memory_metrics
            WHERE date(timestamp) = date('now', 'localtime')
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
            WHERE date(timestamp) = date('now', 'localtime')
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
            WHERE date(timestamp) = date('now', 'localtime') AND memory_rate_mb_min IS NOT NULL
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
            "SELECT COUNT(*) as c FROM memory_events WHERE event_type = 'process_kill' AND date(timestamp) = date('now', 'localtime')"
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


@app.route('/api/memory/sessions')
def api_memory_sessions():
    """API endpoint for memory sessions list."""
    db = get_db()

    try:
        sessions = db.execute('''
            SELECT m.pid, m.session_id, m.rss_mb, m.memory_rate_mb_min as rate,
                   m.command, m.timestamp, m.source_device
            FROM memory_metrics m
            INNER JOIN (
                SELECT pid, MAX(timestamp_unix) as max_ts
                FROM memory_metrics
                WHERE timestamp_unix > (strftime('%s', 'now') - 3600)
                GROUP BY pid
            ) latest ON m.pid = latest.pid AND m.timestamp_unix = latest.max_ts
            ORDER BY m.rss_mb DESC
        ''').fetchall()

        return jsonify([dict(row) for row in sessions])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory/chart-data')
def api_memory_chart_data():
    """API endpoint for memory chart data (for AJAX updates)."""
    db = get_db()

    try:
        metrics = db.execute('''
            SELECT pid, rss_mb, memory_rate_mb_min, timestamp
            FROM memory_metrics
            WHERE date(timestamp) = date('now', 'localtime')
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


# =============================================================================
# HA Control Dashboard Routes
# =============================================================================

# Node configuration
NODES = {
    'laptop': {
        'name': 'Laptop (omarchy-1)',
        'ip': '100.103.8.87',
        'role': 'PRIMARY',
        'is_local': True,  # This is the laptop
    },
    'desktop': {
        'name': 'Desktop (omarchy)',
        'ip': '100.92.71.80',
        'role': 'REPLICA',
        'is_local': False,
    },
    'pi-nas': {
        'name': 'Pi 5 NAS (rpi5)',
        'ssh_alias': 'pi5',
        'role': 'NAS',
        'is_local': False,
    }
}

# Services to monitor
SERVICES = [
    {'name': 'datalake-api', 'description': 'REST API (port 8766)', 'type': 'docker'},
    {'name': 'datalake-web', 'description': 'Web UI (port 5050)', 'type': 'systemd-user'},
    {'name': 'claude-memory-monitor', 'description': 'Claude RAM monitor', 'type': 'systemd-user'},
    {'name': 'voice-gateway', 'description': 'Transcription (port 8765)', 'type': 'systemd-user'},
    {'name': 'hyprwhspr', 'description': 'Voice typing widget', 'type': 'systemd-user'},
]

# Pi NAS services (separate since they're on a different network)
PI_SERVICES = [
    {'name': 'smbd', 'description': 'Samba file sharing', 'type': 'systemd'},
    {'name': 'filebrowser', 'description': 'Web file browser (port 8080)', 'type': 'systemd'},
]

# Pi NAS database path
PI_FILES_DB = '/mnt/nas/prabhanshu-files/prabhanshu-files.db'


def check_node_reachable(host: str, timeout: int = 2, use_ssh: bool = False) -> bool:
    """Check if a node is reachable via ping or SSH."""
    import subprocess
    try:
        if use_ssh:
            result = subprocess.run(
                ['ssh', '-o', f'ConnectTimeout={timeout}', host, 'true'],
                capture_output=True, timeout=timeout + 3
            )
        else:
            result = subprocess.run(
                ['ping', '-c', '1', '-W', str(timeout), host],
                capture_output=True, timeout=timeout + 1
            )
        return result.returncode == 0
    except Exception:
        return False


def get_service_status_local(service_name: str, service_type: str) -> dict:
    """Get status of a local service."""
    import subprocess

    if service_type == 'docker':
        try:
            result = subprocess.run(
                ['docker', 'ps', '--filter', f'name={service_name}', '--format', '{{.Status}}'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                status_text = result.stdout.strip()
                if 'Up' in status_text:
                    return {'status': 'running', 'detail': status_text}
            return {'status': 'stopped', 'detail': 'Not running'}
        except Exception as e:
            return {'status': 'error', 'detail': str(e)}

    elif service_type == 'systemd-user':
        try:
            result = subprocess.run(
                ['systemctl', '--user', 'is-active', f'{service_name}.service'],
                capture_output=True, text=True, timeout=5
            )
            status = result.stdout.strip()
            if status == 'active':
                return {'status': 'running', 'detail': 'Active'}
            elif status == 'inactive':
                return {'status': 'stopped', 'detail': 'Inactive'}
            elif status == 'failed':
                return {'status': 'failed', 'detail': 'Failed'}
            else:
                return {'status': 'unknown', 'detail': status}
        except Exception as e:
            return {'status': 'error', 'detail': str(e)}

    return {'status': 'unknown', 'detail': 'Unknown service type'}


def get_service_status_remote(ip: str, service_name: str, service_type: str, timeout: int = 5) -> dict:
    """Get status of a remote service via SSH."""
    import subprocess

    # Determine SSH user based on IP (Pi uses 'pi', others use 'prabhanshu')
    ssh_user = 'pi' if '192.168.50' in ip else 'prabhanshu'

    if service_type == 'docker':
        cmd = f"docker ps --filter 'name={service_name}' --format '{{{{.Status}}}}'"
    elif service_type == 'systemd':
        # System-level systemd service (requires sudo or runs as system)
        cmd = f"systemctl is-active {service_name}.service"
    else:
        # User-level systemd service
        cmd = f"systemctl --user is-active {service_name}.service"

    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=3', '-o', 'StrictHostKeyChecking=no',
             f'{ssh_user}@{ip}', cmd],
            capture_output=True, text=True, timeout=timeout
        )

        if service_type == 'docker':
            if result.returncode == 0 and result.stdout.strip():
                status_text = result.stdout.strip()
                if 'Up' in status_text:
                    return {'status': 'running', 'detail': status_text}
            return {'status': 'stopped', 'detail': 'Not running'}
        else:
            status = result.stdout.strip()
            if status == 'active':
                return {'status': 'running', 'detail': 'Active'}
            elif status == 'inactive':
                return {'status': 'stopped', 'detail': 'Inactive'}
            elif status == 'failed':
                return {'status': 'failed', 'detail': 'Failed'}
            else:
                return {'status': 'unknown', 'detail': status or 'Unknown'}
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'detail': 'SSH timeout'}
    except Exception as e:
        return {'status': 'error', 'detail': str(e)}


def get_service_status_remote_ssh(ssh_alias: str, service_name: str, service_type: str, timeout: int = 5) -> dict:
    """Get status of a remote service via SSH alias."""
    import subprocess

    if service_type == 'docker':
        cmd = f"docker ps --filter 'name={service_name}' --format '{{{{.Status}}}}'"
    elif service_type == 'systemd':
        cmd = f"systemctl is-active {service_name}.service"
    else:
        cmd = f"systemctl --user is-active {service_name}.service"

    try:
        result = subprocess.run(
            ['ssh', '-o', f'ConnectTimeout={timeout}', ssh_alias, cmd],
            capture_output=True, text=True, timeout=timeout + 3
        )

        if service_type == 'docker':
            if result.returncode == 0 and result.stdout.strip():
                status_text = result.stdout.strip()
                if 'Up' in status_text:
                    return {'status': 'running', 'detail': status_text}
            return {'status': 'stopped', 'detail': 'Not running'}
        else:
            status = result.stdout.strip()
            if status == 'active':
                return {'status': 'running', 'detail': 'Active'}
            elif status == 'inactive':
                return {'status': 'stopped', 'detail': 'Inactive'}
            elif status == 'failed':
                return {'status': 'failed', 'detail': 'Failed'}
            else:
                return {'status': 'unknown', 'detail': status or 'Unknown'}
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'detail': 'SSH timeout'}
    except Exception as e:
        return {'status': 'error', 'detail': str(e)}


def get_system_resources_local() -> dict:
    """Get local system resources (CPU, RAM, Disk)."""
    import subprocess
    try:
        # CPU usage
        cpu_result = subprocess.run(
            ['bash', '-c', "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'"],
            capture_output=True, text=True, timeout=5
        )
        cpu = float(cpu_result.stdout.strip()) if cpu_result.stdout.strip() else 0

        # Memory usage
        mem_result = subprocess.run(
            ['bash', '-c', "free | grep Mem | awk '{print $3/$2 * 100}'"],
            capture_output=True, text=True, timeout=5
        )
        ram = float(mem_result.stdout.strip()) if mem_result.stdout.strip() else 0

        # Disk usage
        disk_result = subprocess.run(
            ['bash', '-c', "df -h / | tail -1 | awk '{print $5}' | tr -d '%'"],
            capture_output=True, text=True, timeout=5
        )
        disk = float(disk_result.stdout.strip()) if disk_result.stdout.strip() else 0

        return {'cpu': round(cpu, 1), 'ram': round(ram, 1), 'disk': round(disk, 1)}
    except Exception:
        return {'cpu': 0, 'ram': 0, 'disk': 0}


@app.route('/control')
def control_dashboard():
    """HA Control Dashboard - shows node and service status."""
    return render_template('control_dashboard.html',
                          nodes=NODES,
                          services=SERVICES,
                          last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@app.route('/api/control/nodes')
def api_control_nodes():
    """API endpoint for node status."""
    from datetime import datetime

    nodes_status = []
    for node_id, node in NODES.items():
        if node['is_local']:
            is_reachable = True
        elif 'ssh_alias' in node:
            is_reachable = check_node_reachable(node['ssh_alias'], use_ssh=True)
        else:
            is_reachable = check_node_reachable(node['ip'])

        if is_reachable:
            if node['is_local']:
                resources = get_system_resources_local()
            else:
                resources = {'cpu': 0, 'ram': 0, 'disk': 0}  # TODO: get remote resources
            status = 'online'
        else:
            resources = {'cpu': 0, 'ram': 0, 'disk': 0}
            status = 'offline'

        nodes_status.append({
            'id': node_id,
            'name': node['name'],
            'ip': node.get('ip', node.get('ssh_alias', '')),
            'role': node['role'],
            'status': status,
            'last_heartbeat': datetime.now().isoformat() if is_reachable else None,
            'resources': resources
        })

    return jsonify(nodes_status)


@app.route('/api/control/services')
def api_control_services():
    """API endpoint for service status across nodes."""
    services_status = []

    # Check laptop (local)
    laptop_reachable = True
    desktop_reachable = check_node_reachable(NODES['desktop']['ip'])

    for service in SERVICES:
        laptop_status = get_service_status_local(service['name'], service['type'])

        if desktop_reachable:
            desktop_status = get_service_status_remote(
                NODES['desktop']['ip'], service['name'], service['type']
            )
        else:
            desktop_status = {'status': 'offline', 'detail': 'Node offline'}

        services_status.append({
            'name': service['name'],
            'description': service['description'],
            'laptop': laptop_status,
            'desktop': desktop_status
        })

    return jsonify(services_status)


# =============================================================================
# Pi NAS Routes
# =============================================================================

@app.route('/api/pi-nas/status')
def api_pi_nas_status():
    """API endpoint for Pi NAS status."""
    import subprocess

    pi_ssh = NODES['pi-nas']['ssh_alias']
    is_reachable = check_node_reachable(pi_ssh, use_ssh=True)

    result = {
        'node': 'pi-nas',
        'ssh_alias': pi_ssh,
        'reachable': is_reachable,
        'services': [],
        'storage': {},
        'files_db': {}
    }

    if not is_reachable:
        result['error'] = 'Pi NAS not reachable via SSH (check pi5 SSH alias)'
        return jsonify(result)

    # Check Pi services
    for service in PI_SERVICES:
        try:
            status = get_service_status_remote_ssh(pi_ssh, service['name'], service['type'], timeout=10)
            result['services'].append({
                'name': service['name'],
                'description': service['description'],
                'status': status['status'],
                'detail': status['detail']
            })
        except Exception as e:
            result['services'].append({
                'name': service['name'],
                'description': service['description'],
                'status': 'error',
                'detail': str(e)
            })

    # Get storage info via SSH
    try:
        storage_cmd = "df -h /mnt/nas/* 2>/dev/null | tail -n +2 | awk '{print $1,$2,$3,$4,$5,$6}'"
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh, storage_cmd],
            capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 6:
                    mount = parts[5]
                    name = mount.split('/')[-1]
                    result['storage'][name] = {
                        'device': parts[0],
                        'size': parts[1],
                        'used': parts[2],
                        'avail': parts[3],
                        'use_pct': parts[4],
                        'mount': mount
                    }
    except Exception as e:
        result['storage_error'] = str(e)

    # Get prabhanshu-files database stats
    try:
        db_cmd = f"sqlite3 {PI_FILES_DB} \"SELECT source_service, COUNT(*) as count, SUM(size_bytes) as bytes FROM files GROUP BY source_service;\""
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh, db_cmd],
            capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0:
            stats = {}
            for line in proc.stdout.strip().split('\n'):
                parts = line.split('|')
                if len(parts) >= 3:
                    service = parts[0]
                    stats[service] = {
                        'count': int(parts[1]),
                        'bytes': int(parts[2]) if parts[2] else 0
                    }
            result['files_db'] = {
                'status': 'indexed',
                'by_service': stats,
                'total_files': sum(s['count'] for s in stats.values()),
                'total_bytes': sum(s['bytes'] for s in stats.values())
            }
        else:
            result['files_db'] = {'status': 'error', 'error': proc.stderr}
    except Exception as e:
        result['files_db'] = {'status': 'error', 'error': str(e)}

    return jsonify(result)


@app.route('/api/pi-nas/search')
def api_pi_nas_search():
    """Search files in prabhanshu-files database on Pi NAS."""
    import subprocess

    query = request.args.get('q', '')
    service = request.args.get('service', None)
    limit = request.args.get('limit', 50, type=int)

    pi_ssh = NODES['pi-nas']['ssh_alias']
    is_reachable = check_node_reachable(pi_ssh, use_ssh=True)

    if not is_reachable:
        return jsonify({'error': 'Pi NAS not reachable'}), 503

    if not query:
        return jsonify({'error': 'Query required'}), 400

    # Build SQL query
    sql = f"""
        SELECT f.path, f.filename, f.size_bytes, f.source_service, f.source_archive
        FROM files f
        WHERE f.id IN (
            SELECT rowid FROM files_fts WHERE files_fts MATCH '{query}'
        )
    """
    if service:
        sql += f" AND f.source_service = '{service}'"
    sql += f" LIMIT {limit};"

    try:
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh,
             f'sqlite3 -separator "|" {PI_FILES_DB} "{sql}"'],
            capture_output=True, text=True, timeout=30
        )

        results = []
        if proc.returncode == 0 and proc.stdout.strip():
            for line in proc.stdout.strip().split('\n'):
                parts = line.split('|')
                if len(parts) >= 5:
                    results.append({
                        'path': parts[0],
                        'filename': parts[1],
                        'size_bytes': int(parts[2]) if parts[2] else 0,
                        'service': parts[3],
                        'archive': parts[4]
                    })

        return jsonify({
            'query': query,
            'service': service,
            'count': len(results),
            'results': results
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Files Browser Routes (all Google Takeout services)
# =============================================================================

# Path prefix per service for folder navigation
SERVICE_PATH_PREFIXES = {
    'drive': 'Takeout/Drive/',
    'photos': 'Takeout/Google Photos/',
    'mail': 'Takeout/Mail/',
    'keep': 'Takeout/Keep/',
    'contacts': 'Takeout/Contacts/',
    'calendar': 'Takeout/Calendar/',
    'chrome': 'Takeout/Chrome/',
    'maps': 'Takeout/Maps/',
    'youtube': 'Takeout/YouTube and YouTube Music/',
    'hangouts': 'Takeout/Hangouts/',
    'fit': 'Takeout/Fit/',
    'tasks': 'Takeout/Tasks/',
    'profile': 'Takeout/Profile/',
}


def _get_path_prefix(service=None):
    """Get the path prefix for a given service (or generic Takeout/ for all)."""
    if service and service in SERVICE_PATH_PREFIXES:
        return SERVICE_PATH_PREFIXES[service]
    return 'Takeout/'


def _query_files_local(db, service=None, path=None, query=None, ext=None, page=1, per_page=50):
    """Query files from local files DB, optionally filtered by service."""
    params = []
    where_clauses = []

    if service:
        where_clauses.append("f.source_service = ?")
        params.append(service)

    if query:
        where_clauses.append(
            "f.id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?)"
        )
        params.append(query)

    if path:
        prefix = _get_path_prefix(service)
        where_clauses.append("f.path LIKE ?")
        params.append(f'{prefix}{path}/%')

    if ext:
        where_clauses.append("f.extension = ?")
        params.append(ext)

    where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'
    offset = (page - 1) * per_page

    total = db.execute(
        f'SELECT COUNT(*) FROM files f WHERE {where_sql}', params
    ).fetchone()[0]

    files = db.execute(f'''
        SELECT f.path, f.filename, f.extension, f.size_bytes,
               f.source_service, f.source_archive, f.created_at, f.modified_at
        FROM files f
        WHERE {where_sql}
        ORDER BY f.path
        LIMIT ? OFFSET ?
    ''', params + [per_page, offset]).fetchall()

    return files, total


def _query_files_pi_nas(service=None, path=None, query=None, ext=None, page=1, per_page=50):
    """Fallback: query files from Pi NAS via SSH."""
    import subprocess

    pi_ssh = NODES['pi-nas']['ssh_alias']
    if not check_node_reachable(pi_ssh, use_ssh=True):
        return [], 0

    params_parts = []
    if service:
        params_parts.append(f"source_service = '{service}'")
    if query:
        params_parts.append(
            f"id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH '{query}')"
        )
    if path:
        prefix = _get_path_prefix(service)
        params_parts.append(f"path LIKE '{prefix}{path}/%'")
    if ext:
        params_parts.append(f"extension = '{ext}'")

    where_sql = ' AND '.join(params_parts) if params_parts else '1=1'
    offset = (page - 1) * per_page

    # Get count
    count_sql = f"SELECT COUNT(*) FROM files WHERE {where_sql};"
    try:
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh,
             f'sqlite3 {PI_FILES_DB} "{count_sql}"'],
            capture_output=True, text=True, timeout=15
        )
        total = int(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else 0
    except Exception:
        return [], 0

    # Get files
    files_sql = f"""SELECT path, filename, extension, size_bytes, source_service, source_archive, created_at, modified_at
        FROM files WHERE {where_sql} ORDER BY path LIMIT {per_page} OFFSET {offset};"""
    try:
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh,
             f'sqlite3 -separator "|" {PI_FILES_DB} "{files_sql}"'],
            capture_output=True, text=True, timeout=30
        )
        files = []
        if proc.returncode == 0 and proc.stdout.strip():
            for line in proc.stdout.strip().split('\n'):
                parts = line.split('|')
                if len(parts) >= 8:
                    files.append({
                        'path': parts[0],
                        'filename': parts[1],
                        'extension': parts[2],
                        'size_bytes': int(parts[3]) if parts[3] else 0,
                        'source_service': parts[4],
                        'source_archive': parts[5],
                        'created_at': parts[6],
                        'modified_at': parts[7],
                    })
        return files, total
    except Exception:
        return [], 0


def _get_file_folders(db, service=None, parent_path=None):
    """Get immediate subfolders under a path, optionally filtered by service."""
    prefix = _get_path_prefix(service)
    if parent_path:
        prefix = f'{prefix}{parent_path}/'

    prefix_len = len(prefix)

    where_clauses = ["path LIKE ?", "INSTR(SUBSTR(path, ?), '/') > 0"]
    params = [f'{prefix}%', prefix_len + 1]

    if service:
        where_clauses.append("source_service = ?")
        params.append(service)

    where_sql = ' AND '.join(where_clauses)

    rows = db.execute(f'''
        SELECT DISTINCT SUBSTR(path, ?, INSTR(SUBSTR(path, ?), '/') - 1) as folder
        FROM files
        WHERE {where_sql}
        ORDER BY folder
    ''', [prefix_len + 1, prefix_len + 1] + params).fetchall()

    return [r['folder'] for r in rows if r['folder']]


def _get_file_stats(db, service=None):
    """Get file stats from local DB, optionally filtered by service."""
    if service:
        row = db.execute('''
            SELECT COUNT(*) as count, COALESCE(SUM(size_bytes), 0) as bytes,
                   COUNT(DISTINCT source_archive) as archives
            FROM files WHERE source_service = ?
        ''', (service,)).fetchone()
    else:
        row = db.execute('''
            SELECT COUNT(*) as count, COALESCE(SUM(size_bytes), 0) as bytes,
                   COUNT(DISTINCT source_archive) as archives
            FROM files
        ''').fetchone()
    return {
        'count': row['count'],
        'bytes': row['bytes'],
        'archives': row['archives'],
    }


def _get_file_extensions(db, service=None):
    """Get top file extensions, optionally filtered by service."""
    if service:
        rows = db.execute('''
            SELECT extension, COUNT(*) as count
            FROM files
            WHERE source_service = ? AND extension IS NOT NULL AND extension != ''
            GROUP BY extension
            ORDER BY count DESC
            LIMIT 20
        ''', (service,)).fetchall()
    else:
        rows = db.execute('''
            SELECT extension, COUNT(*) as count
            FROM files
            WHERE extension IS NOT NULL AND extension != ''
            GROUP BY extension
            ORDER BY count DESC
            LIMIT 20
        ''').fetchall()
    return [{'ext': r['extension'], 'count': r['count']} for r in rows]


def _get_service_stats(db):
    """Get per-service file count and bytes breakdown."""
    rows = db.execute('''
        SELECT source_service, COUNT(*) as count, COALESCE(SUM(size_bytes), 0) as bytes
        FROM files
        GROUP BY source_service
        ORDER BY count DESC
    ''').fetchall()
    return {r['source_service']: {'count': r['count'], 'bytes': r['bytes']} for r in rows}


def _format_size(size_bytes):
    """Format bytes into human-readable size."""
    if not size_bytes:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(size_bytes) < 1024:
            return f'{size_bytes:.1f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.1f} PB'


app.jinja_env.globals['format_size'] = _format_size


@app.route('/drive')
def drive_redirect():
    """Redirect /drive to /files?service=drive for backwards compatibility."""
    from flask import redirect, url_for
    args = request.args.to_dict()
    args['service'] = 'drive'
    return redirect(url_for('files_browser', **args))


@app.route('/files')
def files_browser():
    """File browser for all Google Takeout services."""
    service = request.args.get('service', '')
    path = request.args.get('path', '')
    query = request.args.get('q', '')
    ext = request.args.get('ext', '')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    db = get_files_db()
    use_pi_nas = False
    files = []
    total = 0
    folders = []
    stats = {'count': 0, 'bytes': 0, 'archives': 0}
    extensions = []
    service_stats = {}

    if db:
        file_count = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]

        if file_count > 0:
            files, total = _query_files_local(db, service or None, path or None, query or None, ext or None, page, per_page)
            folders = _get_file_folders(db, service or None, path or None)
            stats = _get_file_stats(db, service or None)
            extensions = _get_file_extensions(db, service or None)
            service_stats = _get_service_stats(db)
        else:
            use_pi_nas = True
    else:
        use_pi_nas = True

    if use_pi_nas:
        files, total = _query_files_pi_nas(service or None, path or None, query or None, ext or None, page, per_page)

    # Build breadcrumbs
    breadcrumbs = []
    if path:
        parts = path.split('/')
        for i, part in enumerate(parts):
            breadcrumbs.append({
                'name': part,
                'path': '/'.join(parts[:i + 1])
            })

    # Compute path prefix length for display (strip Takeout/Service/ from paths)
    prefix_len = len(_get_path_prefix(service or None))

    return render_template('files_browser.html',
                           files=files,
                           total=total,
                           folders=folders,
                           stats=stats,
                           extensions=extensions,
                           service_stats=service_stats,
                           breadcrumbs=breadcrumbs,
                           current_path=path,
                           current_service=service,
                           query=query,
                           ext_filter=ext,
                           page=page,
                           per_page=per_page,
                           use_pi_nas=use_pi_nas,
                           path_prefix_len=prefix_len)


@app.route('/api/files/folders')
def api_files_folders():
    """API: Get subfolders for a path, optionally filtered by service."""
    parent = request.args.get('path', '')
    service = request.args.get('service', '')
    db = get_files_db()
    if not db:
        return jsonify({'folders': [], 'error': 'No local files DB'}), 200

    folders = _get_file_folders(db, service or None, parent or None)
    return jsonify({'path': parent, 'service': service, 'folders': folders})


@app.route('/api/files/search')
def api_files_search():
    """API: FTS5 search across files, optionally filtered by service."""
    query = request.args.get('q', '')
    service = request.args.get('service', '')
    ext = request.args.get('ext', '')
    limit = request.args.get('limit', 50, type=int)

    if not query:
        return jsonify({'error': 'Query required'}), 400

    db = get_files_db()
    if not db:
        return jsonify({'error': 'No local files DB', 'results': []}), 200

    params = [query]
    extra_clauses = ''
    if service:
        extra_clauses += ' AND f.source_service = ?'
        params.append(service)
    if ext:
        extra_clauses += ' AND f.extension = ?'
        params.append(ext)

    results = db.execute(f'''
        SELECT f.path, f.filename, f.extension, f.size_bytes,
               f.source_service, f.source_archive
        FROM files f
        WHERE f.id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?)
          {extra_clauses}
        ORDER BY f.path
        LIMIT ?
    ''', params + [limit]).fetchall()

    return jsonify({
        'query': query,
        'service': service,
        'count': len(results),
        'results': [dict(r) for r in results]
    })


# =============================================================================
# Photo Browser Routes
# =============================================================================

# Media type classifications
PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
RAW_EXTENSIONS = {'.dng', '.raf', '.cr2', '.arw', '.nef', '.orf', '.rw2'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.3gp', '.m4v', '.mov', '.webm'}
METADATA_EXTENSIONS = {'.json'}


def _parse_date_from_filename(filename):
    """Extract (year, month) from filename. Handles:
       - IMG_20251207_174455917.jpg (compact YYYYMMDD)
       - Screenshot_2018-03-09-23-13-23.png (dashed YYYY-MM-DD)
    Returns (year_str, month_int) or (None, None) if unparseable."""
    import re
    # Try dashed form first (more specific)
    m = re.search(r'(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])', filename)
    if m:
        return m.group(1), int(m.group(2))
    # Compact form (IMG_YYYYMMDD…)
    m = re.search(r'(\d{4})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', filename)
    if m:
        return m.group(1), int(m.group(2))
    return None, None


def _photo_year_month(file):
    """Return (year_str, month_int) for a file dict.
    Prefers JSON sidecar taken_at (photos.taken_at column, ISO 8601);
    falls back to filename pattern. Returns (None, None) if neither works."""
    taken_at = file.get('taken_at')
    if taken_at and len(taken_at) >= 7:
        try:
            return taken_at[:4], int(taken_at[5:7])
        except (ValueError, TypeError):
            pass
    return _parse_date_from_filename(file.get('filename', ''))


def _parse_year_from_folder(path):
    """Extract year from folder like 'Photos from 2025'."""
    import re
    m = re.search(r'Photos from (\d{4})', path)
    if m:
        return m.group(1)
    return None


def _get_base_name(filename):
    """Strip extension to get base name for pairing.
    For JSON sidecars like 'IMG.jpg.supplemental-metadata.json', extract 'IMG.jpg'."""
    import re
    # Handle supplemental metadata JSON: strip .supplemental-metadata.json or truncated variants
    sidecar_match = re.match(r'^(.+?)\.(supplemental-metad(?:ata)?\.json|suppleme\.json|supplem\.json)$', filename, re.IGNORECASE)
    if sidecar_match:
        return sidecar_match.group(1)
    # Handle regular JSON sidecars that share the base name with media
    # e.g. Screenshot_2021-06-21-01-12-48-437_com.coindcx.json -> base is same as .png
    # For non-sidecar files, just strip extension
    name, ext = os.path.splitext(filename)
    return name


def _query_photos_pi_nas(year=None, month=None, view='photos', page=1, per_page=100):
    """Query photo files from Pi NAS, returns raw file list."""
    import subprocess

    pi_ssh = NODES['pi-nas']['ssh_alias']
    if not check_node_reachable(pi_ssh, use_ssh=True):
        return [], 0, False  # files, total, reachable

    where_parts = ["source_service = 'photos'"]

    # Filter by year via folder path
    if year:
        where_parts.append(f"path LIKE '%Photos from {year}%'")

    # Filter by extension based on view
    if view == 'photos':
        exts = "','".join(PHOTO_EXTENSIONS | RAW_EXTENSIONS | METADATA_EXTENSIONS)
        where_parts.append(f"extension IN ('{exts}')")
    elif view == 'videos':
        exts = "','".join(VIDEO_EXTENSIONS | METADATA_EXTENSIONS)
        where_parts.append(f"extension IN ('{exts}')")
    elif view == 'other':
        all_known = PHOTO_EXTENSIONS | RAW_EXTENSIONS | VIDEO_EXTENSIONS | METADATA_EXTENSIONS
        exts = "','".join(all_known)
        where_parts.append(f"extension NOT IN ('{exts}')")
        where_parts.append("filename != 'metadata.json'")

    where_sql = ' AND '.join(where_parts)

    # Get count first (without month filter - month is parsed from filename in Python)
    count_sql = f"SELECT COUNT(*) FROM files WHERE {where_sql};"
    try:
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh,
             f'sqlite3 {PI_FILES_DB} "{count_sql}"'],
            capture_output=True, text=True, timeout=15
        )
        total = int(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else 0
    except Exception:
        return [], 0, True

    # Get all files (we filter by month in Python since it's parsed from filename)
    # For month filtering we need all files in that year, then filter in Python
    files_sql = f"""SELECT path, filename, extension, size_bytes, source_archive, extracted, extracted_path
        FROM files WHERE {where_sql} ORDER BY filename;"""

    try:
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh,
             f'sqlite3 -separator "|" {PI_FILES_DB} "{files_sql}"'],
            capture_output=True, text=True, timeout=60
        )
        files = []
        if proc.returncode == 0 and proc.stdout.strip():
            for line in proc.stdout.strip().split('\n'):
                parts = line.split('|')
                if len(parts) >= 7:
                    files.append({
                        'path': parts[0],
                        'filename': parts[1],
                        'extension': parts[2],
                        'size_bytes': int(parts[3]) if parts[3] else 0,
                        'source_archive': parts[4],
                        'extracted': parts[5] == '1',
                        'extracted_path': parts[6] if parts[6] else None,
                    })
        return files, total, True
    except Exception:
        return [], 0, True


def _query_photos_local(db, year=None, month=None, view='photos'):
    """Query photo files from local DB, returns raw file list."""
    where_parts = ["source_service = 'photos'"]

    if year:
        where_parts.append(f"path LIKE '%Photos from {year}%'")

    if view == 'photos':
        exts = "','".join(PHOTO_EXTENSIONS | RAW_EXTENSIONS | METADATA_EXTENSIONS)
        where_parts.append(f"extension IN ('{exts}')")
    elif view == 'videos':
        exts = "','".join(VIDEO_EXTENSIONS | METADATA_EXTENSIONS)
        where_parts.append(f"extension IN ('{exts}')")
    elif view == 'other':
        all_known = PHOTO_EXTENSIONS | RAW_EXTENSIONS | VIDEO_EXTENSIONS | METADATA_EXTENSIONS
        exts = "','".join(all_known)
        where_parts.append(f"extension NOT IN ('{exts}')")
        where_parts.append("filename != 'metadata.json'")

    where_sql = ' AND '.join(where_parts)

    files = db.execute(f'''
        SELECT f.id, f.path, f.filename, f.extension, f.size_bytes, f.source_archive,
               f.extracted, f.extracted_path, p.taken_at
        FROM files f LEFT JOIN photos p ON p.file_id = f.id
        WHERE {where_sql}
        ORDER BY COALESCE(p.taken_at, f.filename)
    ''').fetchall()

    return [dict(f) for f in files]


def _pair_photo_files(files, month=None):
    """Group files into paired rows: {jpg, raw, json, video} by base name.
    Optionally filter by month (parsed from filename).
    Returns (paired_list, month_counts)."""
    import re
    from collections import defaultdict

    # Group by directory + base media name
    groups = defaultdict(lambda: {'jpg': None, 'raw': None, 'json': [], 'video': None})
    month_counter = defaultdict(int)  # month_num -> count of media files

    for f in files:
        fname = f['filename']
        ext = f['extension'].lower()
        fdir = os.path.dirname(f['path'])

        # Determine the base media name for grouping
        if ext == '.json':
            # JSON sidecar - find the media file it belongs to
            # Pattern: {media_filename}.supplemental-metadata.json (possibly truncated)
            sidecar_match = re.match(
                r'^(.+?\.\w+)\.suppleme',
                fname, re.IGNORECASE
            )
            if sidecar_match:
                media_name = sidecar_match.group(1)
                base = os.path.splitext(media_name)[0]
                key = (fdir, base)
                groups[key]['json'].append(f)
                continue
            # Non-sidecar JSON (e.g., metadata.json, shared_album_comments.json) - skip
            if fname in ('metadata.json', 'shared_album_comments.json', 'user-generated-memory-titles.json'):
                continue
            # Other JSON files that share base name with media
            base = os.path.splitext(fname)[0]
            key = (fdir, base)
            groups[key]['json'].append(f)
            continue

        base = os.path.splitext(fname)[0]
        key = (fdir, base)

        # Parse date for month counting (taken_at preferred, filename fallback)
        year_str, month_num = _photo_year_month(f)
        if month_num:
            month_counter[month_num] += 1

        if ext in PHOTO_EXTENSIONS:
            groups[key]['jpg'] = f
        elif ext in RAW_EXTENSIONS:
            groups[key]['raw'] = f
        elif ext in VIDEO_EXTENSIONS:
            groups[key]['video'] = f

    # Filter by month if specified
    def _sort_key(item):
        (fdir, base), group = item
        primary = group['jpg'] or group['raw'] or group['video']
        if primary:
            return primary['filename']
        return base

    paired = []
    for (fdir, base), group in sorted(groups.items(), key=_sort_key):
        # Get the primary file for date extraction
        primary = group['jpg'] or group['raw'] or group['video']
        if not primary:
            # Only JSON, no media file - skip
            continue

        if month:
            _, file_month = _photo_year_month(primary)
            if file_month != month:
                continue

        paired.append({
            'base_name': base,
            'jpg': group['jpg'],
            'raw': group['raw'],
            'json': group['json'],
            'video': group['video'],
        })

    return paired, dict(month_counter)


def _get_photo_years_pi_nas():
    """Get list of years with photo counts from Pi NAS."""
    import subprocess

    pi_ssh = NODES['pi-nas']['ssh_alias']
    sql = """SELECT DISTINCT
        CASE
            WHEN path LIKE '%Photos from%'
            THEN SUBSTR(path, INSTR(path, 'Photos from ') + 12, 4)
            ELSE 'unknown'
        END as year,
        COUNT(*) as cnt
        FROM files
        WHERE source_service = 'photos' AND extension NOT IN ('.json')
        GROUP BY year ORDER BY year;"""

    try:
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh,
             f'sqlite3 -separator "|" {PI_FILES_DB} "{sql}"'],
            capture_output=True, text=True, timeout=15
        )
        years = []
        if proc.returncode == 0 and proc.stdout.strip():
            for line in proc.stdout.strip().split('\n'):
                parts = line.split('|')
                if len(parts) >= 2 and parts[0] != 'unknown':
                    years.append({'year': parts[0], 'count': int(parts[1])})
        return years
    except Exception:
        return []


def _photo_month_counts(db, year):
    """Per-month FILE count for a year (raw, no dedup).

    Counts every file with source_service='photos' under 'Photos from <year>',
    bucketed by month from taken_at, falling back to filename date pattern.
    Includes photos, RAW, and videos. Edited copies (-edited.jpg) ARE counted —
    the grid dedupes them visually, but the count reflects files-on-disk."""
    if not db or not year:
        return {}
    all_exts = PHOTO_EXTENSIONS | RAW_EXTENSIONS | VIDEO_EXTENSIONS
    ext_list = "','".join(all_exts)
    rows = db.execute(f"""
        SELECT f.filename, p.taken_at
        FROM files f LEFT JOIN photos p ON p.file_id = f.id
        WHERE f.source_service='photos'
          AND lower(f.extension) IN ('{ext_list}')
          AND f.path LIKE ?
    """, (f'%Photos from {year}%',)).fetchall()

    counts = {}
    for r in rows:
        month = None
        if r['taken_at'] and len(r['taken_at']) >= 7:
            try:
                month = int(r['taken_at'][5:7])
            except ValueError:
                month = None
        if not month:
            _, m = _parse_date_from_filename(r['filename'])
            month = m
        if month:
            counts[month] = counts.get(month, 0) + 1
    return counts


def _get_photo_years_local(db):
    """Get list of years with photo counts from local DB."""
    rows = db.execute("""
        SELECT DISTINCT
            CASE
                WHEN path LIKE '%Photos from%'
                THEN SUBSTR(path, INSTR(path, 'Photos from ') + 12, 4)
                ELSE 'unknown'
            END as year,
            COUNT(*) as cnt
        FROM files
        WHERE source_service = 'photos' AND extension NOT IN ('.json')
        GROUP BY year ORDER BY year
    """).fetchall()
    return [{'year': r['year'], 'count': r['cnt']} for r in rows if r['year'] != 'unknown']


@app.route('/files/photos')
def photos_browser():
    """Dedicated photo browser with month filtering and JPG+RAW+JSON pairing."""
    year = request.args.get('year', '')
    month = request.args.get('month', 0, type=int)
    view = request.args.get('view', 'photos')  # photos, videos, other
    page = request.args.get('page', 1, type=int)
    per_page = 100

    # Local DB now contains all 5 photo archives (merged from Pi5 indexing).
    files = []
    years = []
    data_source = 'merged-local'
    pi_reachable = True  # legacy var kept truthy so the warning banner stays hidden

    db = get_files_db()
    if db:
        years = _get_photo_years_local(db)

    # Default to latest year
    if not year and years:
        year = years[-1]['year']

    if db:
        files = _query_photos_local(db, year=year, month=None, view=view)

    # Pair files and get month counts
    if view == 'photos':
        # NEW: unified count via _photo_month_counts (same source-of-truth as /api/photos/list).
        # Pair function still used to render the legacy table for old views, but for photos view
        # we don't need it — the grid fetches from /api/photos/list directly.
        month_counts = _photo_month_counts(db, year)
        paired_page = []  # grid renders client-side via API
        if month:
            total_paired = month_counts.get(int(month), 0)
        else:
            total_paired = sum(month_counts.values())
    elif view == 'videos':
        paired, month_counts = _pair_photo_files(files, month=month if month else None)
        # For videos tab, only show rows that have a video
        video_rows = [p for p in paired if p['video']]
        total_paired = len(video_rows)
        start = (page - 1) * per_page
        paired_page = video_rows[start:start + per_page]
    else:
        # 'other' view - no pairing, just list
        paired_page = [{'jpg': f, 'raw': None, 'json': [], 'video': None, 'base_name': f['filename']} for f in files]
        month_counts = {}
        total_paired = len(paired_page)
        start = (page - 1) * per_page
        paired_page = paired_page[start:start + per_page]

    # Count files per view for tab badges (local DB only)
    view_counts = {'photos': 0, 'videos': 0, 'other': 0}
    if db:
        for v, exts in [('photos', PHOTO_EXTENSIONS | RAW_EXTENSIONS), ('videos', VIDEO_EXTENSIONS)]:
            ext_list = "','".join(exts)
            row = db.execute(f"""
                SELECT COUNT(*) FROM files
                WHERE source_service='photos' AND path LIKE ? AND extension IN ('{ext_list}')
            """, (f'%Photos from {year}%',)).fetchone()
            view_counts[v] = row[0] if row else 0

    # Deletion-tracking state for the year (and current month detail)
    deletion_status_map = {}
    current_deletion = None
    try:
        ddb = get_deletion_db()
        if year:
            for r in ddb.execute(
                "SELECT month, status FROM deletion_log WHERE year = ?",
                (int(year),)
            ).fetchall():
                deletion_status_map[r['month']] = r['status']
        if year and month:
            row = ddb.execute(
                "SELECT * FROM deletion_log WHERE year = ? AND month = ?",
                (int(year), int(month))
            ).fetchone()
            if row:
                current_deletion = dict(row)
    except Exception as e:
        app.logger.warning(f"deletion_log query failed: {e}")

    return render_template('photos_browser.html',
                           paired=paired_page,
                           years=years,
                           current_year=year,
                           current_month=month,
                           current_view=view,
                           month_counts=month_counts,
                           view_counts=view_counts,
                           total=total_paired,
                           page=page,
                           per_page=per_page,
                           data_source=data_source,
                           pi_reachable=pi_reachable,
                           deletion_status_map=deletion_status_map,
                           current_deletion=current_deletion)


@app.route('/api/photos/review', methods=['GET'])
def photos_review_get():
    """Return {file_id: {status, note}} for a list of file_ids.
    Query: ?ids=1,2,3 (comma-separated)"""
    ids_str = request.args.get('ids', '')
    if not ids_str:
        return jsonify({})
    try:
        ids = [int(x) for x in ids_str.split(',') if x]
    except ValueError:
        return jsonify({'error': 'invalid ids'}), 400
    if not ids:
        return jsonify({})
    ddb = get_deletion_db()
    placeholders = ','.join('?' * len(ids))
    rows = ddb.execute(
        f"SELECT file_id, status, note, reviewed_at FROM photo_review WHERE file_id IN ({placeholders})",
        ids
    ).fetchall()
    return jsonify({str(r['file_id']): {'status': r['status'], 'note': r['note'], 'reviewed_at': r['reviewed_at']} for r in rows})


@app.route('/api/photos/review', methods=['POST'])
def photos_review_set():
    """Bulk upsert photo_review rows.
    Body: {file_ids: [int, ...], status: str, note: str (optional)}"""
    data = request.get_json() or {}
    file_ids = data.get('file_ids') or []
    status = data.get('status', 'reviewed')
    note = data.get('note')  # None means do not change existing note

    if not file_ids:
        return jsonify({'error': 'file_ids required'}), 400
    if status not in ('pending', 'reviewed', 'flagged', 'keep'):
        return jsonify({'error': 'invalid status'}), 400
    file_ids = [int(x) for x in file_ids]

    ddb = get_deletion_db()
    if note is None:
        # Don't overwrite note if not provided
        for fid in file_ids:
            ddb.execute("""
                INSERT INTO photo_review (file_id, status, reviewed_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(file_id) DO UPDATE SET
                    status = excluded.status,
                    reviewed_at = CURRENT_TIMESTAMP
            """, (fid, status))
    else:
        for fid in file_ids:
            ddb.execute("""
                INSERT INTO photo_review (file_id, status, note, reviewed_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(file_id) DO UPDATE SET
                    status = excluded.status,
                    note = excluded.note,
                    reviewed_at = CURRENT_TIMESTAMP
            """, (fid, status, note))
    ddb.commit()
    log_action('photo_review_set',
               f'photos:n={len(file_ids)}',
               {'file_ids': file_ids, 'status': status, 'note': note})
    return jsonify({'updated': len(file_ids), 'status': status})


@app.route('/api/photos/full/<int:file_id>')
def photo_full(file_id):
    """Stream full-size image straight from its zip archive (laptop-side only).
    For Pi5-side zips (9-001/002/003), returns 503 — uses thumb."""
    db = get_files_db()
    if not db:
        return "no DB", 503
    row = db.execute(
        "SELECT path, source_archive, extension FROM files WHERE id = ?", (file_id,)
    ).fetchone()
    if not row:
        return "not found", 404

    # Resolve archive to local path. Laptop has 9-004/005 in ~/Downloads/.
    local_zip = Path.home() / 'Downloads' / row['source_archive']
    if not local_zip.exists():
        return jsonify({'error': 'archive not on this host', 'archive': row['source_archive']}), 503

    import zipfile, mimetypes
    ext = (row['extension'] or '').lower()
    mime = mimetypes.guess_type(row['path'])[0] or 'application/octet-stream'
    if ext in ('.heic', '.heif'):
        mime = 'image/heic'  # browsers won't render but it's accurate

    def gen():
        with zipfile.ZipFile(local_zip) as z:
            with z.open(row['path']) as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk

    return Response(gen(), mimetype=mime,
                    headers={'Cache-Control': 'public, max-age=3600'})


@app.route('/api/photos/list')
def photos_list_api():
    """Paginated JSON list of photos for a (year, month).
    Used by the infinite-scroll grid in photos_browser.html.

    Query params:
        year (str, required), month (int, optional 1-12),
        offset (int, default 0), limit (int, default 200, max 500)
    Returns: {items: [{file_id, filename, taken_at, size_bytes,
                       source_archive, extracted, has_thumb, ext}], offset, limit}
    """
    year = request.args.get('year', '')
    month = request.args.get('month', 0, type=int)
    offset = max(0, request.args.get('offset', 0, type=int))
    limit = min(500, max(1, request.args.get('limit', 200, type=int)))
    order = request.args.get('order', 'asc').lower()
    if order not in ('asc', 'desc'):
        order = 'asc'

    if not year:
        return jsonify({'error': 'year required'}), 400

    db = get_files_db()
    if not db:
        return jsonify({'error': 'no files DB'}), 503

    photo_exts = "','".join(PHOTO_EXTENSIONS | RAW_EXTENSIONS | VIDEO_EXTENSIONS)

    where = ["f.source_service = 'photos'",
             f"lower(f.extension) IN ('{photo_exts}')",
             "f.path LIKE ?"]
    params = [f'%Photos from {year}%']

    if month:
        # Match by taken_at (ISO YYYY-MM-...) OR by filename containing
        # YYYYMMDD (IMG_*) OR YYYY-MM-DD (Screenshot_*)
        where.append(
            "(substr(p.taken_at, 6, 2) = ? OR "
            " (p.taken_at IS NULL AND "
            "  (f.filename GLOB ? OR f.filename GLOB ?)))"
        )
        params.append(f'{month:02d}')
        params.append(f'*{year}{month:02d}*')         # IMG_YYYYMMDD…
        params.append(f'*{year}-{month:02d}-*')       # Screenshot_YYYY-MM-DD…

    where_sql = ' AND '.join(where)
    # Sort key: taken_at if present, else reconstruct YYYY-MM-DD from IMG_YYYYMMDD,
    # else fall back to filename. Direction is parametrized.
    sort_dir = 'DESC' if order == 'desc' else 'ASC'
    sql = f"""
        SELECT f.id, f.filename, f.extension, f.size_bytes, f.source_archive,
               f.extracted, p.taken_at
        FROM files f LEFT JOIN photos p ON p.file_id = f.id
        WHERE {where_sql}
        ORDER BY COALESCE(
            p.taken_at,
            -- IMG_YYYYMMDD_*: pull YYYY-MM-DD out of compact date
            CASE WHEN f.filename GLOB '*_????????_*' THEN
                substr(f.filename, instr(f.filename, '_')+1, 4) || '-' ||
                substr(f.filename, instr(f.filename, '_')+5, 2) || '-' ||
                substr(f.filename, instr(f.filename, '_')+7, 2)
            -- Screenshot_YYYY-MM-DD-…: dashed form, take first 10 chars after first '_'
            WHEN f.filename GLOB '*_????-??-??-*' THEN
                substr(f.filename, instr(f.filename, '_')+1, 10)
            ELSE f.filename END
        ) {sort_dir}, f.id {sort_dir}
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    rows = db.execute(sql, params).fetchall()

    thumbs_dir = Path(app.static_folder) / 'thumbs'

    # Dedupe -edited siblings: if foo-edited.jpg and foo.jpg both exist in same archive,
    # hide the -edited one and attach its file_id to the original as edit_file_ids.
    import re
    raw_items = []
    edit_index = {}  # (archive, base, ext) -> edit row
    for r in rows:
        m = re.match(r'^(.+)-edited(\.[^.]+)$', r['filename'])
        if m:
            edit_index[(r['source_archive'], m.group(1), m.group(2).lower())] = r
        else:
            raw_items.append(r)

    items = []
    for r in raw_items:
        base, ext = (r['filename'].rsplit('.', 1) + [''])[:2]
        edit = edit_index.pop((r['source_archive'], base, '.' + ext.lower()), None)
        edit_ids = [edit['id']] if edit else []
        thumb_path = thumbs_dir / f"{r['id']}.jpg"
        items.append({
            'file_id': r['id'],
            'filename': r['filename'],
            'ext': (r['extension'] or '').lower(),
            'taken_at': r['taken_at'],
            'size_bytes': r['size_bytes'],
            'source_archive': (r['source_archive'] or '').replace('takeout-20260126T191854Z-', ''),
            'extracted': bool(r['extracted']),
            'has_thumb': thumb_path.exists(),
            'edit_file_ids': edit_ids,  # files merged into this tile (edits)
        })
    # Any orphan edits (no matching original in this page) become standalone tiles
    for (arch, base, ext), e in edit_index.items():
        thumb_path = thumbs_dir / f"{e['id']}.jpg"
        items.append({
            'file_id': e['id'],
            'filename': e['filename'],
            'ext': (e['extension'] or '').lower(),
            'taken_at': e['taken_at'],
            'size_bytes': e['size_bytes'],
            'source_archive': (e['source_archive'] or '').replace('takeout-20260126T191854Z-', ''),
            'extracted': bool(e['extracted']),
            'has_thumb': thumb_path.exists(),
            'edit_file_ids': [],
        })
    return jsonify({'items': items, 'offset': offset, 'limit': limit, 'returned': len(items)})


@app.route('/files/zips')
def zips_overview():
    """Per-archive overview: size, file counts by type, taken_at date range, services, extracted."""
    db = get_files_db()
    if not db:
        return "No files DB available", 503

    photo_exts = "','".join(PHOTO_EXTENSIONS | RAW_EXTENSIONS)
    video_exts = "','".join(VIDEO_EXTENSIONS)

    rows = db.execute(f"""
        SELECT
            a.filename,
            a.size_bytes,
            a.file_count,
            a.indexed_at,
            (SELECT COUNT(*) FROM files f WHERE f.source_archive = a.filename
                AND lower(f.extension) IN ('{photo_exts}')) AS photos,
            (SELECT COUNT(*) FROM files f WHERE f.source_archive = a.filename
                AND lower(f.extension) IN ('{video_exts}')) AS videos,
            (SELECT COUNT(*) FROM files f WHERE f.source_archive = a.filename
                AND lower(f.extension) NOT IN ('{photo_exts}','{video_exts}','.json')) AS other,
            (SELECT COUNT(*) FROM files f WHERE f.source_archive = a.filename AND f.extracted = 1) AS extracted,
            (SELECT MIN(p.taken_at) FROM photos p JOIN files f ON p.file_id = f.id
                WHERE f.source_archive = a.filename AND p.taken_at IS NOT NULL) AS date_min,
            (SELECT MAX(p.taken_at) FROM photos p JOIN files f ON p.file_id = f.id
                WHERE f.source_archive = a.filename AND p.taken_at IS NOT NULL) AS date_max
        FROM archives a
        ORDER BY a.filename
    """).fetchall()

    archives = []
    total_files = total_photos = total_bytes = 0
    for r in rows:
        # Top 5 years by file count for this archive
        ty = db.execute(f"""
            SELECT
                CASE WHEN path LIKE '%Photos from%'
                    THEN substr(path, instr(path, 'Photos from ') + 12, 4)
                    ELSE 'other' END AS year,
                COUNT(*) AS cnt
            FROM files
            WHERE source_archive = ? AND extension NOT IN ('.json')
            GROUP BY year ORDER BY cnt DESC LIMIT 5
        """, (r['filename'],)).fetchall()
        top_years = [(y['year'], y['cnt']) for y in ty]

        # Services in this archive
        svc = db.execute("""
            SELECT source_service, COUNT(*) AS cnt FROM files
            WHERE source_archive = ?
            GROUP BY source_service ORDER BY cnt DESC LIMIT 5
        """, (r['filename'],)).fetchall()
        services = [(s['source_service'] or 'unknown', s['cnt']) for s in svc]

        archives.append({
            'short_name': r['filename'].replace('takeout-20260126T191854Z-', '').replace('.zip', ''),
            'size_bytes': r['size_bytes'] or 0,
            'file_count': r['file_count'] or 0,
            'photos': r['photos'] or 0,
            'videos': r['videos'] or 0,
            'other': r['other'] or 0,
            'extracted': r['extracted'] or 0,
            'date_min': (r['date_min'] or '')[:10],
            'date_max': (r['date_max'] or '')[:10],
            'indexed_at': (r['indexed_at'] or '')[:10],
            'top_years': top_years,
            'services': services,
        })
        total_bytes += r['size_bytes'] or 0
        total_files += r['file_count'] or 0
        total_photos += r['photos'] or 0

    return render_template('zips_overview.html',
                           archives=archives,
                           total_archives=len(archives),
                           total_bytes=total_bytes,
                           total_files=total_files,
                           total_photos=total_photos)


@app.route('/api/deletion/status', methods=['GET'])
def deletion_status_get():
    """Read deletion log row for (year, month). Returns null if no row."""
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    if not year or not month:
        return jsonify({'error': 'year and month required'}), 400
    ddb = get_deletion_db()
    row = ddb.execute(
        "SELECT * FROM deletion_log WHERE year = ? AND month = ?",
        (year, month)
    ).fetchone()
    return jsonify(dict(row) if row else None)


@app.route('/api/deletion/status', methods=['POST'])
def deletion_status_set():
    """Upsert deletion log row."""
    data = request.get_json() or {}
    year = data.get('year')
    month = data.get('month')
    status = data.get('status', 'pending')
    if not year or not month:
        return jsonify({'error': 'year and month required'}), 400
    if status not in ('pending', 'reviewed', 'deleted', 'verified'):
        return jsonify({'error': 'invalid status'}), 400

    count_local = data.get('count_local')
    count_google = data.get('count_google')
    bytes_freed = data.get('bytes_freed')
    note = data.get('note', '')
    deleted_at = datetime.utcnow().isoformat() if status in ('deleted', 'verified') else None

    ddb = get_deletion_db()
    ddb.execute("""
        INSERT INTO deletion_log
            (year, month, status, count_local, count_google, bytes_freed, deleted_at, note, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(year, month) DO UPDATE SET
            status=excluded.status,
            count_local=COALESCE(excluded.count_local, deletion_log.count_local),
            count_google=COALESCE(excluded.count_google, deletion_log.count_google),
            bytes_freed=COALESCE(excluded.bytes_freed, deletion_log.bytes_freed),
            deleted_at=COALESCE(excluded.deleted_at, deletion_log.deleted_at),
            note=excluded.note,
            updated_at=CURRENT_TIMESTAMP
    """, (int(year), int(month), status, count_local, count_google, bytes_freed, deleted_at, note))
    ddb.commit()
    row = ddb.execute(
        "SELECT * FROM deletion_log WHERE year = ? AND month = ?",
        (int(year), int(month))
    ).fetchone()
    log_action('deletion_status_set',
               f'photos:{int(year)}:{int(month):02d}',
               {'status': status, 'count_local': count_local,
                'count_google': count_google, 'bytes_freed': bytes_freed,
                'note': note})
    return jsonify(dict(row))


@app.route('/api/files/extract', methods=['POST'])
def extract_file():
    """Extract a single file from a zip archive on Pi NAS."""
    import subprocess

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    file_path = data.get('path', '')
    archive = data.get('archive', '')

    if not file_path or not archive:
        return jsonify({'error': 'path and archive are required'}), 400

    # Sanitize inputs - prevent path traversal
    if '..' in file_path or '..' in archive:
        return jsonify({'error': 'Invalid path'}), 400

    pi_ssh = NODES['pi-nas']['ssh_alias']
    if not check_node_reachable(pi_ssh, use_ssh=True):
        return jsonify({'error': 'Pi NAS not reachable'}), 503

    archive_path = f'/mnt/nas/t7/takeout-archives/{archive}'
    extract_dir = '/mnt/nas/prabhanshu-files/extracted'

    # Use Python zipfile on Pi NAS to extract single file
    extract_cmd = f"""python3 -c "
import zipfile, os
z = zipfile.ZipFile('{archive_path}')
z.extract('{file_path}', '{extract_dir}')
print('OK')
" """

    try:
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh, extract_cmd],
            capture_output=True, text=True, timeout=120
        )

        if proc.returncode != 0:
            return jsonify({'error': f'Extraction failed: {proc.stderr}'}), 500

        extracted_path = f'{extract_dir}/{file_path}'

        # Update DB to mark as extracted
        update_sql = f"UPDATE files SET extracted=1, extracted_path='{extracted_path}' WHERE path='{file_path}' AND source_archive='{archive}';"
        subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', pi_ssh,
             f'sqlite3 {PI_FILES_DB} "{update_sql}"'],
            capture_output=True, text=True, timeout=15
        )

        return jsonify({
            'success': True,
            'extracted_path': extracted_path,
            'path': file_path,
            'archive': archive
        })

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Extraction timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ──────────────────────────────────────────────────────────────
# Conversation Explorer
# ──────────────────────────────────────────────────────────────

@app.route('/explorer')
@app.route('/explorer/<session_id>')
def explorer(session_id=None):
    """Conversation Explorer — visual tree view of Claude sessions."""
    return render_template('conversation_explorer.html',
                           initial_session_id=session_id)


@app.route('/api/sessions/active')
def api_sessions_active():
    """Return sessions modified in last 5 minutes + recent sessions for dropdown."""
    db = get_db()

    # Active sessions: check source_file modification time
    active = []
    recent_cutoff = (datetime.now() - timedelta(minutes=5)).isoformat()
    active_rows = db.execute('''
        SELECT id, session_id, summary, project_path, total_messages,
               source_device, started_at, ended_at
        FROM claude_sessions
        WHERE ended_at > ?
        ORDER BY ended_at DESC
        LIMIT 10
    ''', (recent_cutoff,)).fetchall()
    for row in active_rows:
        active.append({**dict(row), 'is_active': True})

    # Recent sessions (last 50, excluding already-shown active)
    active_ids = [r['id'] for r in active_rows]
    placeholders = ','.join('?' * len(active_ids)) if active_ids else '0'
    recent_rows = db.execute(f'''
        SELECT id, session_id, summary, project_path, total_messages,
               source_device, started_at, ended_at
        FROM claude_sessions
        WHERE id NOT IN ({placeholders})
        ORDER BY started_at DESC
        LIMIT 50
    ''', active_ids).fetchall()
    recent = [{**dict(row), 'is_active': False} for row in recent_rows]

    return jsonify({'active': active, 'recent': recent})


@app.route('/api/sessions/search')
def api_sessions_search():
    """Search sessions by message content using FTS5."""
    db = get_db()
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'results': []})

    # Sanitize query for FTS5: remove special characters that cause syntax errors
    safe_query = query.replace('-', ' ').replace('"', '').replace("'", '')
    # Use FTS5 to find matching sessions
    try:
        rows = db.execute('''
            SELECT DISTINCT s.id, s.session_id, s.summary, s.project_path,
                   s.total_messages, s.source_device, s.started_at, s.ended_at
            FROM claude_messages_fts fts
            JOIN claude_messages m ON m.id = fts.rowid
            JOIN claude_sessions s ON s.id = m.session_id
            WHERE claude_messages_fts MATCH ?
            ORDER BY s.started_at DESC
            LIMIT 20
        ''', (safe_query,)).fetchall()
    except Exception:
        # Fallback to LIKE search if FTS fails
        rows = db.execute('''
            SELECT DISTINCT s.id, s.session_id, s.summary, s.project_path,
                   s.total_messages, s.source_device, s.started_at, s.ended_at
            FROM claude_messages m
            JOIN claude_sessions s ON s.id = m.session_id
            WHERE m.content_text LIKE ?
            ORDER BY s.started_at DESC
            LIMIT 20
        ''', (f'%{query}%',)).fetchall()

    results = [{**dict(row), 'is_active': False} for row in rows]
    return jsonify({'results': results})


@app.route('/api/session/<int:session_id>/tree')
def api_session_tree(session_id):
    """Return full tree data for a session — nodes, tool events, compaction, subagents."""
    db = get_db()

    session = db.execute('''
        SELECT id, session_id, summary, project_path, total_messages,
               source_device, started_at, ended_at, duration_seconds,
               total_input_tokens, total_output_tokens
        FROM claude_sessions WHERE id = ?
    ''', (session_id,)).fetchone()

    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # All messages as flat list with parent links
    messages = db.execute('''
        SELECT message_uuid, parent_uuid, message_type, role, model,
               is_sidechain, cwd, content_text, content_thinking,
               content_tool_uses, content_tool_results,
               input_tokens, output_tokens, sequence_number, timestamp
        FROM claude_messages
        WHERE session_id = ?
        ORDER BY sequence_number
    ''', (session_id,)).fetchall()

    # Tool events for this session (load early so we can enrich empty nodes)
    tool_events = db.execute('''
        SELECT id, message_uuid, result_message_uuid, tool_use_id,
               tool_name, is_error, file_path, sequence_number, timestamp
        FROM claude_tool_events
        WHERE session_id = ?
        ORDER BY sequence_number
    ''', (session_id,)).fetchall()

    # Build tool name lookups for enriching empty content_preview
    tools_by_msg = {}       # assistant msg uuid → list of tool names
    tools_by_result = {}    # user (tool_result) msg uuid → list of tool names
    for te in tool_events:
        te_dict = dict(te)
        msg_uuid = te_dict['message_uuid']
        result_uuid = te_dict.get('result_message_uuid')
        name = te_dict['tool_name']
        fp = te_dict.get('file_path') or ''
        label = name + (' ' + fp.split('/')[-1] if fp else '')
        tools_by_msg.setdefault(msg_uuid, []).append(label)
        if result_uuid:
            tools_by_result.setdefault(result_uuid, []).append(label)

    nodes = []
    for msg in messages:
        m = dict(msg)
        # Truncate content for tree overview
        text = m.pop('content_text', '') or ''
        thinking = m.pop('content_thinking', '') or ''
        m['has_thinking'] = bool(thinking)
        m['tool_use_count'] = m.pop('content_tool_uses', 0) or 0
        m['tool_result_count'] = m.pop('content_tool_results', 0) or 0

        # Generate meaningful content_preview for tool-only messages
        if text:
            m['content_preview'] = text[:200] + ('...' if len(text) > 200 else '')
        elif m['tool_use_count'] > 0:
            tool_names = tools_by_msg.get(m['message_uuid'], [])
            if tool_names:
                m['content_preview'] = ', '.join(tool_names[:4])
                if len(tool_names) > 4:
                    m['content_preview'] += f' +{len(tool_names)-4} more'
            else:
                m['content_preview'] = f"{m['tool_use_count']} tool call{'s' if m['tool_use_count'] > 1 else ''}"
        elif m['tool_result_count'] > 0:
            tool_names = tools_by_result.get(m['message_uuid'], [])
            if tool_names:
                m['content_preview'] = '\u2190 ' + ', '.join(tool_names[:4])
                if len(tool_names) > 4:
                    m['content_preview'] += f' +{len(tool_names)-4} more'
            else:
                m['content_preview'] = f"{m['tool_result_count']} tool result{'s' if m['tool_result_count'] > 1 else ''}"
        elif thinking:
            m['content_preview'] = thinking[:120] + ('...' if len(thinking) > 120 else '')
        else:
            m['content_preview'] = ''
        nodes.append(m)

    # Compaction events
    compaction_events = db.execute('''
        SELECT id, leaf_uuid, summary_text, sequence_number, timestamp
        FROM claude_compaction_events
        WHERE session_id = ?
        ORDER BY sequence_number
    ''', (session_id,)).fetchall()

    # Subagents
    subagents = db.execute('''
        SELECT id, subagent_id, subagent_type, description,
               total_messages, started_at, ended_at
        FROM claude_subagents
        WHERE parent_session_id = ?
    ''', (session_id,)).fetchall()

    return jsonify({
        'session': dict(session),
        'nodes': nodes,
        'tool_events': [dict(te) for te in tool_events],
        'compaction_events': [dict(ce) for ce in compaction_events],
        'subagents': [dict(sa) for sa in subagents]
    })


@app.route('/api/session/<int:session_id>/node/<message_uuid>')
def api_session_node(session_id, message_uuid):
    """Return full detail for a single node — content, thinking, tool I/O."""
    db = get_db()

    msg = db.execute('''
        SELECT message_uuid, parent_uuid, message_type, role, model,
               content_text, content_thinking, content_tool_uses,
               content_tool_results, is_sidechain, cwd, git_branch,
               input_tokens, output_tokens, cache_read_tokens,
               stop_reason, timestamp, sequence_number
        FROM claude_messages
        WHERE session_id = ? AND message_uuid = ?
    ''', (session_id, message_uuid)).fetchone()

    if not msg:
        return jsonify({'error': 'Node not found'}), 404

    node = dict(msg)

    # Full tool events for this message
    tool_events = db.execute('''
        SELECT tool_use_id, tool_name, tool_input, tool_result,
               is_error, file_path, timestamp
        FROM claude_tool_events
        WHERE session_id = ? AND (message_uuid = ? OR result_message_uuid = ?)
        ORDER BY sequence_number
    ''', (session_id, message_uuid, message_uuid)).fetchall()
    node['tool_events'] = [dict(te) for te in tool_events]

    # File operations linked to tool events in this message
    tool_event_ids = [te['tool_use_id'] for te in tool_events]
    if tool_event_ids:
        placeholders = ','.join('?' * len(tool_event_ids))
        file_ops = db.execute(f'''
            SELECT operation, file_path, content_preview,
                   old_string, new_string, timestamp
            FROM claude_file_operations
            WHERE session_id = ? AND tool_event_id IN (
                SELECT id FROM claude_tool_events
                WHERE session_id = ? AND tool_use_id IN ({placeholders})
            )
            ORDER BY sequence_number
        ''', [session_id, session_id] + tool_event_ids).fetchall()
        node['file_operations'] = [dict(fo) for fo in file_ops]
    else:
        node['file_operations'] = []

    return jsonify(node)


@app.route('/api/session/<int:session_id>/stream')
def api_session_stream(session_id):
    """SSE stream — pushes new messages as they appear in DB."""
    last_seq = request.args.get('last_seq', 0, type=int)

    def generate():
        nonlocal last_seq
        # Send initial keepalive
        yield f"data: {json.dumps({'type': 'connected', 'last_seq': last_seq})}\n\n"

        while True:
            try:
                # New connection per poll — Flask's g doesn't work in generators
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row

                new_messages = conn.execute('''
                    SELECT message_uuid, parent_uuid, message_type, role,
                           is_sidechain, content_text, content_thinking,
                           content_tool_uses, content_tool_results,
                           input_tokens, output_tokens,
                           sequence_number, timestamp
                    FROM claude_messages
                    WHERE session_id = ? AND sequence_number > ?
                    ORDER BY sequence_number
                ''', (session_id, last_seq)).fetchall()

                if new_messages:
                    nodes = []
                    for msg in new_messages:
                        m = dict(msg)
                        text = m.pop('content_text', '') or ''
                        thinking = m.pop('content_thinking', '') or ''
                        m['content_preview'] = text[:200] + ('...' if len(text) > 200 else '')
                        m['has_thinking'] = bool(thinking)
                        m['tool_use_count'] = m.pop('content_tool_uses', 0) or 0
                        m['tool_result_count'] = m.pop('content_tool_results', 0) or 0
                        nodes.append(m)
                        last_seq = max(last_seq, m['sequence_number'] or 0)

                    # Also fetch new tool events
                    min_seq = min(n['sequence_number'] for n in nodes if n['sequence_number'])
                    tool_events = conn.execute('''
                        SELECT id, message_uuid, tool_use_id, tool_name,
                               is_error, file_path, sequence_number, timestamp
                        FROM claude_tool_events
                        WHERE session_id = ? AND sequence_number >= ?
                        ORDER BY sequence_number
                    ''', (session_id, min_seq)).fetchall()

                    yield f"data: {json.dumps({'type': 'new_nodes', 'nodes': nodes, 'tool_events': [dict(te) for te in tool_events]})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'last_seq': last_seq})}\n\n"

                conn.close()
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

            time.sleep(3)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
        }
    )


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
