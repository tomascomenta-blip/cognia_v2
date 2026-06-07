"""
Tests for cognia/search/web_search.py
No real network calls — urllib.request.urlopen is fully mocked.
"""
import io
import json
import time
import unittest
from unittest.mock import MagicMock, patch

from cognia.search.web_search import WebSearch


_SAMPLE_DDG_RESPONSE = {
    "Heading": "Python programming language",
    "AbstractText": "Python is a high-level, general-purpose programming language.",
    "AbstractSource": "Wikipedia",
    "Answer": "",
    "RelatedTopics": [
        {"Text": "CPython — the reference implementation of Python"},
        {"Text": "PyPy — a fast Python interpreter"},
        {"Text": "Jython — Python on the JVM"},
    ],
}


def _make_urlopen_mock(payload: dict):
    """Return a context-manager mock that yields a fake HTTP response."""
    raw = json.dumps(payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestWebSearchSearch(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_search_returns_expected_keys(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_mock(_SAMPLE_DDG_RESPONSE)
        ws = WebSearch()
        result = ws.search("python")
        expected_keys = {"query", "abstract", "abstract_source", "related_topics", "answer", "cached", "error"}
        self.assertEqual(set(result.keys()), expected_keys)

    @patch("urllib.request.urlopen")
    def test_search_parses_abstract_and_source(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_mock(_SAMPLE_DDG_RESPONSE)
        ws = WebSearch()
        result = ws.search("python")
        self.assertIn("Python", result["abstract"])
        self.assertEqual(result["abstract_source"], "Wikipedia")
        self.assertIsNone(result["error"])
        self.assertFalse(result["cached"])

    @patch("urllib.request.urlopen")
    def test_search_respects_max_results(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_mock(_SAMPLE_DDG_RESPONSE)
        ws = WebSearch()
        result = ws.search("python", max_results=2)
        self.assertLessEqual(len(result["related_topics"]), 2)

    @patch("urllib.request.urlopen")
    def test_cache_hit_returns_cached_true(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_mock(_SAMPLE_DDG_RESPONSE)
        ws = WebSearch()
        first = ws.search("python")
        self.assertFalse(first["cached"])
        # Second call should hit cache — urlopen called only once
        second = ws.search("python")
        self.assertTrue(second["cached"])
        mock_urlopen.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_cache_hit_case_insensitive(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_mock(_SAMPLE_DDG_RESPONSE)
        ws = WebSearch()
        ws.search("Python")
        result = ws.search("PYTHON")
        self.assertTrue(result["cached"])
        mock_urlopen.assert_called_once()


class TestWebSearchParseResponse(unittest.TestCase):
    def test_parse_empty_data_does_not_raise(self):
        ws = WebSearch()
        result = ws._parse_response({}, max_results=5)
        self.assertEqual(result["abstract"], "")
        self.assertEqual(result["related_topics"], [])
        self.assertIsNone(result["error"])

    def test_parse_skips_topics_without_text(self):
        ws = WebSearch()
        data = {
            "Heading": "Test",
            "AbstractText": "",
            "AbstractSource": "",
            "Answer": "",
            "RelatedTopics": [
                {"Text": ""},        # should be skipped
                {},                  # should be skipped
                {"Text": "Valid topic"},
            ],
        }
        result = ws._parse_response(data, max_results=5)
        self.assertEqual(result["related_topics"], ["Valid topic"])

    def test_parse_truncates_long_abstract(self):
        ws = WebSearch()
        data = {"AbstractText": "x" * 600, "AbstractSource": "", "Answer": "", "Heading": "", "RelatedTopics": []}
        result = ws._parse_response(data, max_results=5)
        self.assertLessEqual(len(result["abstract"]), 500)

    def test_parse_truncates_long_answer(self):
        ws = WebSearch()
        data = {"AbstractText": "", "AbstractSource": "", "Answer": "a" * 300, "Heading": "", "RelatedTopics": []}
        result = ws._parse_response(data, max_results=5)
        self.assertLessEqual(len(result["answer"]), 200)


class TestWebSearchErrorHandling(unittest.TestCase):
    @patch("urllib.request.urlopen", side_effect=TimeoutError("timed out"))
    def test_timeout_returns_error_not_none(self, mock_urlopen):
        ws = WebSearch()
        result = ws.search("something")
        self.assertIsNotNone(result["error"])
        self.assertIn("timed out", result["error"])
        self.assertEqual(result["abstract"], "")

    @patch("urllib.request.urlopen", side_effect=Exception("connection refused"))
    def test_generic_exception_returns_graceful_error(self, mock_urlopen):
        ws = WebSearch()
        result = ws.search("something")
        self.assertIsNotNone(result["error"])
        self.assertFalse(result["cached"])

    @patch("urllib.request.urlopen", side_effect=Exception("x" * 300))
    def test_error_truncated_to_200_chars(self, mock_urlopen):
        ws = WebSearch()
        result = ws.search("something")
        self.assertLessEqual(len(result["error"]), 200)


class TestWebSearchClearCache(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_clear_cache_removes_entries(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_mock(_SAMPLE_DDG_RESPONSE)
        ws = WebSearch()
        ws.search("python")
        self.assertEqual(len(ws._cache), 1)
        ws.clear_cache()
        self.assertEqual(len(ws._cache), 0)

    @patch("urllib.request.urlopen")
    def test_after_clear_cache_fetches_again(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_mock(_SAMPLE_DDG_RESPONSE)
        ws = WebSearch()
        ws.search("python")
        ws.clear_cache()
        result = ws.search("python")
        self.assertFalse(result["cached"])
        self.assertEqual(mock_urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
