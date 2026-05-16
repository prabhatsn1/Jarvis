"""Tests for jarvis.actions.memory module."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import jarvis.actions.memory as mem_actions


class TestRecallTopicAction(unittest.TestCase):

    def test_recall_topic_returns_results(self):
        mock_sm = MagicMock()
        mock_sm.query.return_value = [
            {"text": "Team standup every Monday at 10am", "metadata": {}, "distance": 0.3},
        ]
        mem_actions._semantic_memory = mock_sm

        result = mem_actions.recall_topic("meetings")
        self.assertIn("standup", result)
        mock_sm.query.assert_called_once_with("meetings", n_results=3)

    def test_recall_topic_no_memory(self):
        mem_actions._semantic_memory = None
        result = mem_actions.recall_topic("meetings")
        self.assertIn("not enabled", result)

    def tearDown(self):
        mem_actions._semantic_memory = None


class TestStoreUserFactAction(unittest.TestCase):

    def test_store_user_fact_calls_store(self):
        mock_sm = MagicMock()
        mem_actions._semantic_memory = mock_sm

        result = mem_actions.store_user_fact("I work out at 7am")
        self.assertIn("remember", result.lower())
        mock_sm.store_fact.assert_called_once()
        args, kwargs = mock_sm.store_fact.call_args
        self.assertEqual(args[0], "I work out at 7am")
        self.assertEqual(args[1]["source"], "user_fact")

    def tearDown(self):
        mem_actions._semantic_memory = None


if __name__ == "__main__":
    unittest.main()
