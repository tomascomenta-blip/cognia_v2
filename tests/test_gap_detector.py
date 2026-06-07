"""
tests/test_gap_detector.py -- Phase 60: KnowledgeGapDetector unit tests
"""

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, call

from storage.db_pool import close_pool


def _make_detector(tmp_path, curiosity_engine=None):
    from cognia.knowledge.gap_detector import KnowledgeGapDetector
    return KnowledgeGapDetector(tmp_path, curiosity_engine=curiosity_engine)


class TestMaybeRecordGapBelowThreshold(unittest.TestCase):
    """maybe_record_gap with score < threshold records gap and returns True."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name

    def tearDown(self):
        close_pool(self.db)
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_low_score_returns_true(self):
        det = _make_detector(self.db)
        result = det.maybe_record_gap("why is Python slow", "idk", 0.3)
        self.assertTrue(result)

    def test_gap_appears_in_get_gaps(self):
        det = _make_detector(self.db)
        det.maybe_record_gap("why is Python slow", "idk", 0.3)
        gaps = det.get_gaps()
        self.assertEqual(len(gaps), 1)

    def test_score_stored_correctly(self):
        det = _make_detector(self.db)
        det.maybe_record_gap("why is Python slow", "idk", 0.25)
        gaps = det.get_gaps()
        self.assertAlmostEqual(gaps[0]["quality_score"], 0.25, places=5)

    def test_timestamp_is_recent_float(self):
        det = _make_detector(self.db)
        before = time.time()
        det.maybe_record_gap("why is Python slow", "idk", 0.1)
        after = time.time()
        gaps = det.get_gaps()
        self.assertGreaterEqual(gaps[0]["timestamp"], before)
        self.assertLessEqual(gaps[0]["timestamp"], after)


class TestMaybeRecordGapAboveThreshold(unittest.TestCase):
    """maybe_record_gap with score >= threshold returns False, nothing stored."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name

    def tearDown(self):
        close_pool(self.db)
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_high_score_returns_false(self):
        det = _make_detector(self.db)
        result = det.maybe_record_gap("what is Python", "Python is a language", 0.5)
        self.assertFalse(result)

    def test_exact_threshold_returns_false(self):
        det = _make_detector(self.db)
        result = det.maybe_record_gap("what is Python", "Python is a language", 0.4)
        self.assertFalse(result)

    def test_nothing_recorded_when_high_score(self):
        det = _make_detector(self.db)
        det.maybe_record_gap("what is Python", "Python is a language", 0.7)
        self.assertEqual(len(det.get_gaps()), 0)


class TestDeduplication(unittest.TestCase):
    """Same topic recorded twice same day — second returns False."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name

    def tearDown(self):
        close_pool(self.db)
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_same_topic_second_call_returns_false(self):
        det = _make_detector(self.db)
        r1 = det.maybe_record_gap("why is Python slow", "idk", 0.2)
        r2 = det.maybe_record_gap("why is Python slow", "idk", 0.1)
        self.assertTrue(r1)
        self.assertFalse(r2)

    def test_only_one_gap_in_db_after_duplicate(self):
        det = _make_detector(self.db)
        det.maybe_record_gap("why is Python slow", "idk", 0.2)
        det.maybe_record_gap("why is Python slow", "idk", 0.1)
        self.assertEqual(len(det.get_gaps()), 1)


class TestDailyCap(unittest.TestCase):
    """After MAX_GAPS_PER_DAY gaps, new ones are rejected."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name

    def tearDown(self):
        close_pool(self.db)
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_cap_at_max_per_day(self):
        from cognia.knowledge.gap_detector import KnowledgeGapDetector
        det = _make_detector(self.db)
        cap = KnowledgeGapDetector.MAX_GAPS_PER_DAY
        # Record up to the cap with unique topics
        for i in range(cap):
            det.maybe_record_gap(f"topic number {i} unique concept", "bad", 0.1)
        # One more should be rejected
        result = det.maybe_record_gap("brand new extra topic here", "bad", 0.1)
        self.assertFalse(result)
        self.assertEqual(len(det.get_gaps()), cap)


class TestExtractTopic(unittest.TestCase):
    """_extract_topic heuristic tests."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name

    def tearDown(self):
        close_pool(self.db)
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_removes_question_words(self):
        det = _make_detector(self.db)
        # "why", "is" are question words, "Python", "slow" remain
        topic = det._extract_topic("why is Python slow")
        self.assertNotIn("why", topic)
        self.assertNotIn("is", topic)

    def test_removes_stop_words(self):
        det = _make_detector(self.db)
        topic = det._extract_topic("what is a decorator")
        words = topic.split()
        self.assertNotIn("a", words)
        self.assertNotIn("what", words)
        self.assertIn("decorator", words)

    def test_empty_query_fallback(self):
        det = _make_detector(self.db)
        # All words filtered — falls back to query[:30]
        topic = det._extract_topic("why is the")
        self.assertIsInstance(topic, str)
        self.assertGreater(len(topic), 0)

    def test_topic_stored_as_extracted_not_raw_query(self):
        det = _make_detector(self.db)
        raw_query = "why is Python slow today"
        det.maybe_record_gap(raw_query, "not sure", 0.1)
        gaps = det.get_gaps()
        self.assertNotEqual(gaps[0]["topic"], raw_query)

    def test_takes_first_three_remaining_words(self):
        det = _make_detector(self.db)
        # "how" filtered, rest: alpha beta gamma delta
        topic = det._extract_topic("how alpha beta gamma delta")
        parts = topic.split()
        self.assertLessEqual(len(parts), 3)


class TestMarkResolved(unittest.TestCase):
    """mark_resolved sets resolved=1."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name

    def tearDown(self):
        close_pool(self.db)
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_mark_resolved_sets_flag(self):
        det = _make_detector(self.db)
        det.maybe_record_gap("why is Python slow", "idk", 0.2)
        topic = det.get_gaps()[0]["topic"]
        det.mark_resolved(topic)
        gaps = det.get_gaps()
        self.assertTrue(gaps[0]["resolved"])

    def test_get_gaps_includes_resolved(self):
        det = _make_detector(self.db)
        det.maybe_record_gap("why is Python slow", "idk", 0.2)
        topic = det.get_gaps()[0]["topic"]
        det.mark_resolved(topic)
        gaps = det.get_gaps()
        self.assertEqual(len(gaps), 1)
        self.assertTrue(gaps[0]["resolved"])


class TestCuriosityEngineIntegration(unittest.TestCase):
    """Curiosity engine enqueue called when gap recorded."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name

    def tearDown(self):
        close_pool(self.db)
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_enqueue_called_on_gap(self):
        mock_ce = MagicMock()
        det = _make_detector(self.db, curiosity_engine=mock_ce)
        det.maybe_record_gap("why is Python slow", "idk", 0.1)
        mock_ce.enqueue.assert_called_once()

    def test_enqueue_not_called_above_threshold(self):
        mock_ce = MagicMock()
        det = _make_detector(self.db, curiosity_engine=mock_ce)
        det.maybe_record_gap("what is Python", "Python is a language", 0.8)
        mock_ce.enqueue.assert_not_called()

    def test_curiosity_engine_none_no_crash(self):
        det = _make_detector(self.db, curiosity_engine=None)
        result = det.maybe_record_gap("why is Python slow", "idk", 0.1)
        self.assertTrue(result)

    def test_enqueue_receives_question_string(self):
        mock_ce = MagicMock()
        det = _make_detector(self.db, curiosity_engine=mock_ce)
        det.maybe_record_gap("why is Python slow", "idk", 0.1)
        args = mock_ce.enqueue.call_args
        questions_list = args[0][0]
        self.assertIsInstance(questions_list, list)
        self.assertGreater(len(questions_list), 0)
        self.assertIn("python", questions_list[0].lower())


class TestGetGapsFields(unittest.TestCase):
    """get_gaps returns correct fields."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name

    def tearDown(self):
        close_pool(self.db)
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_gap_dict_has_required_fields(self):
        det = _make_detector(self.db)
        det.maybe_record_gap("why is Python slow", "idk", 0.15)
        gaps = det.get_gaps()
        self.assertEqual(len(gaps), 1)
        g = gaps[0]
        for field in ("topic", "question", "quality_score", "timestamp", "resolved"):
            self.assertIn(field, g)

    def test_question_contains_topic(self):
        det = _make_detector(self.db)
        det.maybe_record_gap("why is Python slow", "idk", 0.15)
        gaps = det.get_gaps()
        topic = gaps[0]["topic"]
        question = gaps[0]["question"]
        self.assertIn(topic, question)


if __name__ == "__main__":
    unittest.main()
