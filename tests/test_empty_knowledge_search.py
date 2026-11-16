from unittest.mock import Mock

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from rag.retriever import VECTOR_SIZE, ensure_collection, search


def test_fresh_install_returns_no_matches_then_searches_uploaded_knowledge():
    client = QdrantClient(':memory:')
    try:
        vector = [1.0] + [0.0] * (VECTOR_SIZE - 1)
        assert search(vector, client) == []
        ensure_collection(client)
        client.upsert('knowledge_base', [PointStruct(
            id=1, vector=vector, payload={'text': 'uploaded answer'},
        )])
        assert search(vector, client)[0].payload['text'] == 'uploaded answer'
        # Switching to a new empty archive must not search another archive.
        assert search(vector, client, collection_name='new_archive') == []
    finally:
        client.close()


def test_storage_failure_is_not_hidden_as_empty_knowledge():
    client = Mock()
    client.collection_exists.side_effect = RuntimeError('storage unavailable')
    with pytest.raises(RuntimeError, match='storage unavailable'):
        search([0.0] * VECTOR_SIZE, client)
