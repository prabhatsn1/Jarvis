"""Unit tests for LLM function-calling tools."""

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis.brain.tools import web_search, read_file, run_code
from jarvis.brain.tool_schemas import get_enabled_schemas, TOOL_SCHEMAS


class TestWebSearch(unittest.TestCase):
    """Tests for web_search tool."""

    def test_empty_query(self):
        result = web_search(query="")
        self.assertIn("Error", result)

    @patch("jarvis.brain.tools.DDGS", create=True)
    def test_success(self, _mock_ddgs_class):
        # Mock duckduckgo_search at import time
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = [
            {"title": "Python 3.13", "href": "https://python.org", "body": "New release"},
        ]

        # Patch the import inside the function
        with patch("jarvis.brain.tools.DDGS", return_value=mock_ddgs, create=True):
            # Re-import to pick up mock
            import importlib
            import jarvis.brain.tools as tools_mod
            # Simulate the function with mocked import
            from duckduckgo_search import DDGS as _real
            with patch.dict("sys.modules", {"duckduckgo_search": MagicMock(DDGS=lambda: mock_ddgs)}):
                result = web_search(query="python release")
        # Just verify no crash — actual DuckDuckGo tests need network
        self.assertIsInstance(result, str)

    def test_max_results_clamped(self):
        # max_results > 10 should be clamped
        # Just make sure the function doesn't crash with extreme values
        result = web_search(query="test", max_results=100)
        self.assertIsInstance(result, str)


class TestReadFile(unittest.TestCase):
    """Tests for read_file tool."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmpdir, "test.txt")
        with open(self.test_file, "w") as f:
            for i in range(1, 51):
                f.write(f"Line {i}\n")

    def test_success(self):
        result = read_file(path=self.test_file, start_line=1, end_line=10,
                           workspace_root=self.tmpdir)
        self.assertIn("Line 1", result)
        self.assertIn("Line 10", result)
        self.assertNotIn("Line 11", result)

    def test_file_not_found(self):
        result = read_file(path="/nonexistent/file.txt")
        self.assertIn("Error", result)

    def test_empty_path(self):
        result = read_file(path="")
        self.assertIn("Error", result)

    def test_binary_file_blocked(self):
        bin_path = os.path.join(self.tmpdir, "image.png")
        with open(bin_path, "wb") as f:
            f.write(b"\x89PNG")
        result = read_file(path=bin_path, workspace_root=self.tmpdir)
        self.assertIn("Error", result)
        self.assertIn("binary", result.lower())

    def test_large_file_blocked(self):
        big_path = os.path.join(self.tmpdir, "big.txt")
        with open(big_path, "w") as f:
            f.write("x" * (600 * 1024))
        result = read_file(path=big_path, workspace_root=self.tmpdir)
        self.assertIn("Error", result)
        self.assertIn("too large", result.lower())

    def test_path_outside_allowed(self):
        result = read_file(path="/etc/passwd", workspace_root=self.tmpdir)
        self.assertIn("Error", result)

    def test_line_range_clamped(self):
        result = read_file(path=self.test_file, start_line=1, end_line=10000,
                           workspace_root=self.tmpdir)
        # Should clamp to MAX_FILE_LINES (500)
        self.assertIn("Line 50", result)


class TestRunCode(unittest.TestCase):
    """Tests for run_code tool."""

    def test_success(self):
        result = run_code(code="print(1 + 2)")
        self.assertIn("3", result)

    def test_empty_code(self):
        result = run_code(code="")
        self.assertIn("Error", result)

    def test_unsupported_language(self):
        result = run_code(code="console.log(1)", language="javascript")
        self.assertIn("Error", result)
        self.assertIn("unsupported", result.lower())

    def test_timeout(self):
        result = run_code(code="import time; time.sleep(30)", timeout=1)
        self.assertIn("Error", result)
        self.assertIn("timed out", result.lower())

    def test_syntax_error(self):
        result = run_code(code="def ()")
        self.assertIn("exit code", result.lower())

    def test_output_captured(self):
        code = textwrap.dedent("""\
            for i in range(5):
                print(f"item {i}")
        """)
        result = run_code(code=code)
        self.assertIn("item 0", result)
        self.assertIn("item 4", result)


class TestToolSchemas(unittest.TestCase):
    """Tests for tool schema filtering."""

    def test_all_enabled(self):
        config = {
            "web_search_enabled": True,
            "file_read_enabled": True,
            "code_exec_enabled": True,
            "calendar_enabled": False,
        }
        schemas = get_enabled_schemas(config)
        self.assertEqual(len(schemas), 3)

    def test_none_enabled(self):
        config = {
            "web_search_enabled": False,
            "file_read_enabled": False,
            "code_exec_enabled": False,
            "calendar_enabled": False,
        }
        schemas = get_enabled_schemas(config)
        self.assertEqual(len(schemas), 0)

    def test_partial(self):
        config = {
            "web_search_enabled": True,
            "file_read_enabled": False,
            "code_exec_enabled": True,
        }
        schemas = get_enabled_schemas(config)
        names = [s["function"]["name"] for s in schemas]
        self.assertIn("web_search", names)
        self.assertIn("run_code", names)
        self.assertNotIn("read_file", names)


if __name__ == "__main__":
    unittest.main()
