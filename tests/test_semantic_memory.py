"""Tests for SemanticMemory (ChromaDB-backed vector store)."""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis.memory.semantic import SemanticMemory


class TestSemanticMemory(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = {"vector_db_path": self.tmpdir}
        self.sm = SemanticMemory(self.config, llm=None)

    def tearDown(self):
        self.sm.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_store_and_query(self):
        self.sm.store_fact(
            "Team standup is every Monday at 10am",
            {"source": "user_fact"},
        )
        self.sm.store_fact(
            "I usually go for a run on Wednesday mornings",
            {"source": "user_fact"},
        )
        results = self.sm.query("weekly meetings schedule", n_results=2)
        self.assertTrue(len(results) > 0)
        self.assertLess(results[0]["distance"], 0.6)

    def test_deduplication(self):
        self.sm.store_fact("I drink coffee every morning", {"source": "user_fact"})
        self.sm.store_fact("I drink coffee every morning", {"source": "user_fact"})
        count = self.sm._collection.count()
        self.assertEqual(count, 1)

    def test_summarize_empty_log(self):
        # Should not raise even with LLM disabled
        self.sm.summarize_and_store_session([])

    def test_forget_topic(self):
        self.sm.store_fact(
            "My project deadline is next Friday",
            {"source": "user_fact"},
        )
        # Verify it's there
        results = self.sm.query("project deadline", n_results=1)
        self.assertTrue(len(results) > 0)

        # Delete and verify gone
        self.sm.delete_by_topic("project deadline")
        results = self.sm.query("project deadline", n_results=1)
        self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
