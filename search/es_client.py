#!/usr/bin/env python3
"""Elasticsearch client for datalake search."""

from elasticsearch import Elasticsearch
from typing import List, Dict, Any, Optional
import os
import logging

logger = logging.getLogger(__name__)


class DatalakeSearch:
    """Elasticsearch client for datalake search with fallback support."""

    def __init__(self, es_url: str = None):
        """Initialize Elasticsearch client.

        Args:
            es_url: Elasticsearch URL (defaults to http://localhost:9200 or ELASTICSEARCH_URL env var)
        """
        if es_url is None:
            es_url = os.environ.get('ELASTICSEARCH_URL', 'http://localhost:9200')

        self.es_url = es_url
        self.es = None
        self.available = False

        try:
            self.es = Elasticsearch([es_url])
            self.available = self.es.ping()
            if self.available:
                logger.info(f"Elasticsearch connected at {es_url}")
            else:
                logger.warning(f"Elasticsearch not responding at {es_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Elasticsearch: {e}")
            self.available = False

    def create_indices(self):
        """Create all datalake indices if they don't exist."""
        if not self.available:
            logger.error("Cannot create indices: Elasticsearch not available")
            return False

        indices = {
            'datalake-claude-messages': {
                'mappings': {
                    'properties': {
                        'message_uuid': {'type': 'keyword'},
                        'session_id': {'type': 'keyword'},
                        'message_type': {'type': 'keyword'},
                        'role': {'type': 'keyword'},
                        'content_text': {'type': 'text', 'analyzer': 'english'},
                        'content_thinking': {'type': 'text', 'analyzer': 'english'},
                        'model': {'type': 'keyword'},
                        'timestamp': {'type': 'date'},
                        'project_path': {'type': 'keyword'},
                        'source_device': {'type': 'keyword'}
                    }
                }
            },
            'datalake-chatgpt-messages': {
                'mappings': {
                    'properties': {
                        'message_id': {'type': 'keyword'},
                        'conversation_id': {'type': 'keyword'},
                        'role': {'type': 'keyword'},
                        'content_text': {'type': 'text', 'analyzer': 'english'},
                        'model_slug': {'type': 'keyword'},
                        'create_time': {'type': 'date'},
                        'conversation_title': {'type': 'text'}
                    }
                }
            },
            'datalake-voice-transcripts': {
                'mappings': {
                    'properties': {
                        'id': {'type': 'keyword'},
                        'content': {'type': 'text', 'analyzer': 'english'},
                        'filename': {'type': 'keyword'},
                        'created_at': {'type': 'date'},
                        'word_count': {'type': 'integer'}
                    }
                }
            }
        }

        for index_name, index_body in indices.items():
            try:
                if not self.es.indices.exists(index=index_name):
                    self.es.indices.create(index=index_name, body=index_body)
                    logger.info(f"Created index: {index_name}")
                else:
                    logger.info(f"Index already exists: {index_name}")
            except Exception as e:
                logger.error(f"Failed to create index {index_name}: {e}")
                return False

        return True

    def index_claude_message(self, message: Dict[str, Any]):
        """Index a single Claude message.

        Args:
            message: Dictionary containing message data from database
        """
        if not self.available:
            return False

        try:
            doc = {
                'message_uuid': message.get('message_uuid'),
                'session_id': message.get('session_id'),
                'message_type': message.get('message_type'),
                'role': message.get('role'),
                'content_text': message.get('content_text', ''),
                'content_thinking': message.get('content_thinking', ''),
                'model': message.get('model'),
                'timestamp': message.get('timestamp'),
                'project_path': message.get('project_path'),
                'source_device': message.get('source_device')
            }

            self.es.index(
                index='datalake-claude-messages',
                id=message.get('message_uuid'),
                document=doc
            )
            return True
        except Exception as e:
            logger.error(f"Failed to index Claude message: {e}")
            return False

    def index_chatgpt_message(self, message: Dict[str, Any]):
        """Index a single ChatGPT message.

        Args:
            message: Dictionary containing message data from database
        """
        if not self.available:
            return False

        try:
            doc = {
                'message_id': message.get('message_id'),
                'conversation_id': message.get('conversation_id'),
                'role': message.get('role'),
                'content_text': message.get('content_text', ''),
                'model_slug': message.get('model_slug'),
                'create_time': message.get('create_time'),
                'conversation_title': message.get('conversation_title')
            }

            self.es.index(
                index='datalake-chatgpt-messages',
                id=message.get('message_id'),
                document=doc
            )
            return True
        except Exception as e:
            logger.error(f"Failed to index ChatGPT message: {e}")
            return False

    def index_voice_transcript(self, transcript: Dict[str, Any]):
        """Index a single voice transcript.

        Args:
            transcript: Dictionary containing transcript data from database
        """
        if not self.available:
            return False

        try:
            doc = {
                'id': transcript.get('id'),
                'content': transcript.get('content', ''),
                'filename': transcript.get('filename'),
                'created_at': transcript.get('created_at'),
                'word_count': transcript.get('word_count')
            }

            self.es.index(
                index='datalake-voice-transcripts',
                id=transcript.get('id'),
                document=doc
            )
            return True
        except Exception as e:
            logger.error(f"Failed to index voice transcript: {e}")
            return False

    def search(self,
               query: str,
               sources: List[str] = None,
               filters: Dict[str, Any] = None,
               limit: int = 50) -> Dict:
        """Search across datalake indices.

        Args:
            query: Search query string
            sources: List of sources to search ['claude', 'chatgpt', 'voice']
            filters: Additional filters (date range, device, model, etc.)
            limit: Max results per source

        Returns:
            Dict with results grouped by source:
            {
                'claude': [...],
                'chatgpt': [...],
                'voice': [...],
                'total': int
            }
        """
        if not self.available:
            return None

        if sources is None:
            sources = ['claude', 'chatgpt', 'voice']

        results = {
            'claude': [],
            'chatgpt': [],
            'voice': [],
            'total': 0
        }

        # Build search query
        search_body = {
            'query': {
                'multi_match': {
                    'query': query,
                    'fields': ['content_text', 'content_thinking', 'content', 'conversation_title'],
                    'type': 'best_fields',
                    'fuzziness': 'AUTO'
                }
            },
            'size': limit,
            'sort': [
                {'_score': {'order': 'desc'}},
                {'timestamp': {'order': 'desc', 'missing': '_last'}},
                {'create_time': {'order': 'desc', 'missing': '_last'}},
                {'created_at': {'order': 'desc', 'missing': '_last'}}
            ],
            'highlight': {
                'fields': {
                    'content_text': {},
                    'content_thinking': {},
                    'content': {},
                    'conversation_title': {}
                },
                'pre_tags': ['<mark>'],
                'post_tags': ['</mark>']
            }
        }

        # Add filters if provided
        if filters:
            # TODO: Implement filter logic for date ranges, devices, models
            pass

        # Search Claude messages
        if 'claude' in sources:
            try:
                response = self.es.search(index='datalake-claude-messages', body=search_body)
                for hit in response['hits']['hits']:
                    result = hit['_source']
                    result['_score'] = hit['_score']
                    if 'highlight' in hit:
                        result['_highlight'] = hit['highlight']
                    results['claude'].append(result)
                    results['total'] += 1
            except Exception as e:
                logger.error(f"Failed to search Claude messages: {e}")

        # Search ChatGPT messages
        if 'chatgpt' in sources:
            try:
                response = self.es.search(index='datalake-chatgpt-messages', body=search_body)
                for hit in response['hits']['hits']:
                    result = hit['_source']
                    result['_score'] = hit['_score']
                    if 'highlight' in hit:
                        result['_highlight'] = hit['highlight']
                    results['chatgpt'].append(result)
                    results['total'] += 1
            except Exception as e:
                logger.error(f"Failed to search ChatGPT messages: {e}")

        # Search voice transcripts
        if 'voice' in sources:
            try:
                response = self.es.search(index='datalake-voice-transcripts', body=search_body)
                for hit in response['hits']['hits']:
                    result = hit['_source']
                    result['_score'] = hit['_score']
                    if 'highlight' in hit:
                        result['_highlight'] = hit['highlight']
                    results['voice'].append(result)
                    results['total'] += 1
            except Exception as e:
                logger.error(f"Failed to search voice transcripts: {e}")

        return results
