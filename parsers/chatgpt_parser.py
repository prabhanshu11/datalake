#!/usr/bin/env python3
"""
ChatGPT Conversation Parser for Datalake

Parses ChatGPT export (conversations.json) and imports into SQLite database.
Handles tree traversal, duplicate detection, and raw zip archival.

Usage:
    python3 chatgpt_parser.py /path/to/conversations.zip
    python3 chatgpt_parser.py --import /path/to/conversations.zip --db datalake.db
"""

import json
import sys
import argparse
import sqlite3
import hashlib
import zipfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


def parse_message_tree(mapping: Dict[str, Any], node_id: str, visited: set = None) -> List[Dict[str, Any]]:
    """
    Traverse the message tree and extract messages in order.

    Args:
        mapping: The mapping dictionary from conversation
        node_id: Current node ID to process
        visited: Set of visited node IDs to avoid cycles

    Returns:
        List of messages in conversation order
    """
    if visited is None:
        visited = set()

    if node_id in visited or node_id not in mapping:
        return []

    visited.add(node_id)
    node = mapping[node_id]
    messages = []

    # Add current message if it exists
    if node.get('message') is not None:
        msg = node['message']
        # Skip system messages that are visually hidden
        metadata = msg.get('metadata', {})
        if not metadata.get('is_visually_hidden_from_conversation', False):
            # Add parent_id for threading
            msg['_parent_id'] = node.get('parent')
            messages.append(msg)

    # Process all children
    for child_id in node.get('children', []):
        messages.extend(parse_message_tree(mapping, child_id, visited))

    return messages


def extract_text_content(message: Dict[str, Any]) -> Tuple[str, str]:
    """
    Extract text content from a message.

    Returns:
        Tuple of (content_text, content_type)
    """
    content = message.get('content', {})
    content_type = content.get('content_type', 'text')

    # Handle different content types
    if content_type == 'text':
        parts = content.get('parts', [])
        text = ''.join(str(part) for part in parts if part)
        return text, content_type

    elif content_type == 'code':
        text = content.get('text', '')
        return f"```\n{text}\n```", content_type

    elif content_type == 'execution_output':
        text = content.get('text', '')
        return f"[Execution Output]\n{text}", content_type

    elif content_type == 'multimodal_text':
        parts = content.get('parts', [])
        result = []
        for part in parts:
            if isinstance(part, str):
                result.append(part)
            elif isinstance(part, dict):
                if part.get('content_type') == 'image_asset_pointer':
                    result.append('[Image]')
                elif 'text' in part:
                    result.append(part['text'])
        return ''.join(result), content_type

    # Fallback
    text = str(content.get('parts', [''])[0] if content.get('parts') else '')
    return text, content_type


def hash_file(path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def store_raw_zip(zip_path: Path, data_dir: Path) -> Path:
    """
    Store raw zip file in datalake imports directory.

    Returns:
        Path where zip was stored
    """
    imports_dir = data_dir / 'imports' / 'chatgpt'
    imports_dir.mkdir(parents=True, exist_ok=True)

    zip_hash = hash_file(zip_path)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    stored_name = f"{zip_hash[:8]}_{zip_path.stem}_{timestamp}.zip"
    stored_path = imports_dir / stored_name

    shutil.copy2(zip_path, stored_path)
    return stored_path


class ChatGPTImporter:
    """Import ChatGPT conversations into datalake."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def import_from_zip(self, zip_path: Path, data_dir: Path, source_device: str) -> Dict[str, int]:
        """
        Import ChatGPT conversations from export zip.

        Returns:
            Dictionary with stats: {conversations_new, conversations_updated, messages_imported}
        """
        # Calculate zip hash for duplicate detection
        zip_hash = hash_file(zip_path)

        # Check if already imported
        existing = self.conn.execute(
            "SELECT id, conversation_count FROM chatgpt_imports WHERE zip_hash = ?",
            (zip_hash,)
        ).fetchone()

        if existing:
            print(f"⚠ Zip file already imported (import ID {existing['id']}, {existing['conversation_count']} conversations)")
            return {'conversations_new': 0, 'conversations_updated': 0, 'messages_imported': 0}

        # Extract conversations.json from zip
        with zipfile.ZipFile(zip_path, 'r') as zf:
            try:
                conversations_data = zf.read('conversations.json')
            except KeyError:
                print("Error: conversations.json not found in zip file")
                return {'conversations_new': 0, 'conversations_updated': 0, 'messages_imported': 0}

        conversations = json.loads(conversations_data)

        # Store raw zip
        stored_zip_path = store_raw_zip(zip_path, data_dir)

        # Create import record
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO chatgpt_imports (zip_hash, original_filename, zip_path, conversation_count, source_device)
            VALUES (?, ?, ?, ?, ?)
        """, (zip_hash, zip_path.name, str(stored_zip_path), len(conversations), source_device))
        import_id = cursor.lastrowid

        stats = {
            'conversations_new': 0,
            'conversations_updated': 0,
            'messages_imported': 0
        }

        # Process each conversation
        for conv in conversations:
            conv_stats = self._import_conversation(conv, import_id, source_device)
            if conv_stats['is_new']:
                stats['conversations_new'] += 1
            else:
                stats['conversations_updated'] += 1
            stats['messages_imported'] += conv_stats['messages_imported']

        # Update import record with message count
        cursor.execute("""
            UPDATE chatgpt_imports SET message_count = ? WHERE id = ?
        """, (stats['messages_imported'], import_id))

        self.conn.commit()
        return stats

    def _import_conversation(self, conv: Dict[str, Any], import_id: int, source_device: str) -> Dict:
        """Import a single conversation."""
        conversation_id = conv['id']
        create_time = conv.get('create_time')
        update_time = conv.get('update_time')

        # Check if conversation exists
        existing = self.conn.execute(
            "SELECT id, update_time FROM chatgpt_conversations WHERE conversation_id = ?",
            (conversation_id,)
        ).fetchone()

        is_new = existing is None

        if existing:
            # Check if this version is newer
            if update_time and existing['update_time'] and update_time <= existing['update_time']:
                # Skip - older or same version
                return {'is_new': False, 'messages_imported': 0}

            # Update conversation
            db_conv_id = existing['id']
            self.conn.execute("""
                UPDATE chatgpt_conversations
                SET title = ?, update_time = ?, model_slug = ?,
                    is_archived = ?, is_starred = ?, import_id = ?
                WHERE id = ?
            """, (
                conv.get('title'),
                update_time,
                conv.get('default_model_slug'),
                conv.get('is_archived', 0),
                conv.get('is_starred', 0),
                import_id,
                db_conv_id
            ))

            # Delete old messages
            self.conn.execute("DELETE FROM chatgpt_messages WHERE conversation_id = ?", (db_conv_id,))
        else:
            # Insert new conversation
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO chatgpt_conversations
                (conversation_id, title, create_time, update_time, model_slug,
                 is_archived, is_starred, import_id, source_device)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                conversation_id,
                conv.get('title'),
                create_time,
                update_time,
                conv.get('default_model_slug'),
                conv.get('is_archived', 0),
                conv.get('is_starred', 0),
                import_id,
                source_device
            ))
            db_conv_id = cursor.lastrowid

        # Parse and insert messages
        mapping = conv.get('mapping', {})
        if not mapping:
            return {'is_new': is_new, 'messages_imported': 0}

        # Find root node
        root_id = list(mapping.keys())[0]
        messages = parse_message_tree(mapping, root_id)

        message_count = 0
        for seq, msg in enumerate(messages):
            content_text, content_type = extract_text_content(msg)

            self.conn.execute("""
                INSERT INTO chatgpt_messages
                (conversation_id, message_id, parent_id, role, content_type,
                 content_text, create_time, model_slug, sequence_number)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                db_conv_id,
                msg.get('id'),
                msg.get('_parent_id'),
                msg.get('author', {}).get('role', 'unknown'),
                content_type,
                content_text,
                msg.get('create_time'),
                msg.get('metadata', {}).get('model_slug'),
                seq
            ))
            message_count += 1

        # Update message count
        self.conn.execute("""
            UPDATE chatgpt_conversations SET message_count = ? WHERE id = ?
        """, (message_count, db_conv_id))

        return {'is_new': is_new, 'messages_imported': message_count}

    def close(self):
        """Close database connection."""
        self.conn.close()


def main():
    parser = argparse.ArgumentParser(description='Import ChatGPT conversations into datalake')
    parser.add_argument('zip_file', help='ChatGPT export zip file')
    parser.add_argument('--db', default='datalake.db', help='Database path')
    parser.add_argument('--data-dir', default='data', help='Data directory for raw zips')
    parser.add_argument('--device', default='desktop', help='Source device name')

    args = parser.parse_args()

    zip_path = Path(args.zip_file)
    if not zip_path.exists():
        print(f"Error: {zip_path} not found")
        sys.exit(1)

    data_dir = Path(args.data_dir)

    print(f"Importing ChatGPT conversations from {zip_path.name}...")

    importer = ChatGPTImporter(args.db)
    try:
        stats = importer.import_from_zip(zip_path, data_dir, args.device)

        print(f"\n✓ Import complete!")
        print(f"  New conversations: {stats['conversations_new']}")
        print(f"  Updated conversations: {stats['conversations_updated']}")
        print(f"  Messages imported: {stats['messages_imported']}")
    finally:
        importer.close()


if __name__ == '__main__':
    main()
