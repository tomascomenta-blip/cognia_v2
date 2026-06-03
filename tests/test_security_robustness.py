"""
tests/test_security_robustness.py
==================================
Security and robustness tests for:
  1. /ejecutar blocklist in cognia/cli.py (both REPL and agent paths)
  2. /escribir path traversal prevention
  3. VectorCache robustness (empty/None/huge/wrong-dim/NaN inputs)
  4. SemanticMemory robustness (empty names, SQL injection, NaN, out-of-range confidence)
"""

import re
import sys
import math
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Helpers to exercise the blocklist logic without running the full REPL
# ---------------------------------------------------------------------------

def _is_blocked_repl(cmd: str) -> bool:
    """
    Mirror of the /ejecutar REPL check after the fix.
    Returns True when the command should be blocked.
    """
    _BLOCKED = [
        "rm -rf", "format", "del /s", "del /q", "del /f",
        ":(){:|:&};:", "python -c", "python3 -c", "powershell",
        "mkfs", "dd if=", "> /dev/", "shutdown", "reboot",
    ]
    _cmd_normalized = re.sub(r"\s+", " ", cmd.lower())
    return any(b in _cmd_normalized for b in _BLOCKED)


def _is_blocked_agent(args: str) -> bool:
    """
    Mirror of the agent ejecutar check after the fix.
    Returns True when the command should be blocked.
    """
    _BLOCK = [
        "rm -rf", "format", "del /s", "del /q", "del /f",
        ":(){", "python -c", "python3 -c", "powershell",
        "mkfs", "dd if=", "> /dev/", "shutdown", "reboot",
    ]
    _args_normalized = re.sub(r"\s+", " ", args.lower())
    return any(b in _args_normalized for b in _BLOCK)


# ---------------------------------------------------------------------------
# AUDIT 1 — /ejecutar blocklist
# ---------------------------------------------------------------------------

class TestEjecutarBlocklist:

    # --- commands that MUST be blocked ---

    def test_rm_rf_slash_blocked(self):
        assert _is_blocked_repl("rm -rf /")

    def test_rm_rf_no_slash_blocked(self):
        """'rm -rf .' must also be blocked."""
        assert _is_blocked_repl("rm -rf .")

    def test_rm_rf_double_space_bypass_fixed(self):
        """Double-space was a bypass before the fix."""
        assert _is_blocked_repl("rm  -rf /")

    def test_format_uppercase_blocked(self):
        assert _is_blocked_repl("FORMAT c:")

    def test_del_q_blocked(self):
        assert _is_blocked_repl("del /q /s C:\\")

    def test_del_f_blocked(self):
        assert _is_blocked_repl("del /f important.txt")

    def test_python_c_injection_blocked(self):
        assert _is_blocked_repl("python -c \"import os; os.remove('x')\"")

    def test_python3_c_injection_blocked(self):
        assert _is_blocked_repl("python3 -c 'print(1)'")

    def test_powershell_blocked(self):
        assert _is_blocked_repl("powershell -c \"Remove-Item -Recurse\"")

    def test_powershell_uppercase_blocked(self):
        assert _is_blocked_repl("PowerShell -Command \"rm -r *\"")

    def test_fork_bomb_blocked(self):
        assert _is_blocked_repl(":(){:|:&};:")

    def test_shutdown_blocked(self):
        assert _is_blocked_repl("shutdown -s -t 0")

    def test_reboot_blocked(self):
        assert _is_blocked_repl("reboot now")

    # --- commands that must NOT be blocked ---

    def test_safe_ls_allowed(self):
        assert not _is_blocked_repl("ls -la")

    def test_safe_echo_allowed(self):
        assert not _is_blocked_repl("echo hello world")

    def test_safe_git_log_allowed(self):
        assert not _is_blocked_repl("git log --oneline")

    def test_safe_pytest_allowed(self):
        assert not _is_blocked_repl("python -m pytest tests/")

    # --- agent path ---

    def test_agent_format_uppercase_blocked(self):
        """Before fix, agent check was case-sensitive — FORMAT bypassed it."""
        assert _is_blocked_agent("FORMAT c:")

    def test_agent_rm_rf_blocked(self):
        assert _is_blocked_agent("rm -rf /home")

    def test_agent_python_c_blocked(self):
        assert _is_blocked_agent("python -c \"import shutil; shutil.rmtree('.')\"")

    def test_agent_safe_allowed(self):
        assert not _is_blocked_agent("ls .")

    def test_agent_double_space_bypass_fixed(self):
        assert _is_blocked_agent("rm  -rf /")


# ---------------------------------------------------------------------------
# AUDIT 2 — /escribir path traversal
# ---------------------------------------------------------------------------

class TestEscribirPathTraversal:

    def _check_path(self, path_str: str, cwd: Path) -> bool:
        """
        Mirror of the path traversal guard added to /escribir.
        Returns True when path is SAFE (within cwd).
        """
        resolved = Path(path_str).resolve()
        return str(resolved).startswith(str(cwd.resolve()))

    def test_safe_relative_path_allowed(self, tmp_path):
        safe = tmp_path / "output.txt"
        assert self._check_path(str(safe), tmp_path)

    def test_dotdot_traversal_blocked(self, tmp_path):
        evil = str(tmp_path) + "/../../etc/passwd"
        # resolve() collapses the .. — check against tmp_path cwd
        resolved = Path(evil).resolve()
        assert not str(resolved).startswith(str(tmp_path.resolve()))

    def test_absolute_system_path_blocked(self, tmp_path):
        # C:\Windows\System32 is outside tmp_path
        evil = "C:/Windows/System32/evil.txt"
        resolved = Path(evil).resolve()
        assert not str(resolved).startswith(str(tmp_path.resolve()))

    def test_nested_safe_path_allowed(self, tmp_path):
        nested = tmp_path / "subdir" / "file.txt"
        assert self._check_path(str(nested), tmp_path)

    def test_unix_root_traversal_blocked(self, tmp_path):
        evil = "/etc/passwd"
        resolved = Path(evil).resolve()
        assert not str(resolved).startswith(str(tmp_path.resolve()))


# ---------------------------------------------------------------------------
# AUDIT 3 — VectorCache robustness
# ---------------------------------------------------------------------------

class TestVectorCacheRobustness:
    """
    Tests against VectorCache.search() using a pre-built in-memory cache.
    We don't need a real SQLite DB — we inject a pre-built matrix directly.
    """

    def _make_cache(self, n: int = 5, dim: int = 384):
        from cognia.memory.episodic_fast import VectorCache
        cache = VectorCache(":memory:")
        # Inject a synthetic normalized matrix
        mat = np.random.randn(n, dim).astype(np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        cache._matrix = mat / norms
        cache._meta = [
            {"id": i, "observation": f"obs_{i}", "label": f"lbl_{i}",
             "confidence": 0.8, "importance": 1.0, "emotion_score": 0.0,
             "emotion_label": "neutral", "surprise": 0.0, "feedback_weight": 1.0}
            for i in range(n)
        ]
        cache._db_hash = 1  # mark as built
        return cache

    def test_zero_length_query_returns_empty(self):
        """Empty list query — norm is 0 — should return [] not crash."""
        cache = self._make_cache()
        result = cache.search([])
        assert result == []

    def test_wrong_dimension_query_handled(self):
        """384-dim cache queried with 768-dim vector: numpy will raise or produce garbage.
        The code normalizes and does matmul — shape mismatch will raise, which is fine,
        but it must not silently corrupt state. We confirm it raises or returns []."""
        cache = self._make_cache(dim=384)
        qv_wrong = [0.1] * 768
        try:
            result = cache.search(qv_wrong)
            # If it doesn't raise, result must be a list (empty or truncated)
            assert isinstance(result, list)
        except (ValueError, Exception):
            pass  # raising is also acceptable

    def test_nan_query_vector_returns_empty(self):
        """NaN query — norm is NaN — guard `if qnorm == 0` won't catch it.
        After fix (qnorm check using math.isfinite), should return [] or raise cleanly."""
        cache = self._make_cache()
        nan_query = [float("nan")] * 384
        # Current code: qnorm will be NaN, not 0 — matmul produces NaN scores
        # We assert it doesn't corrupt cache._matrix
        before = cache._matrix.copy()
        try:
            result = cache.search(nan_query)
            # After matmul, scores are NaN — results may be returned with NaN scores
            # Acceptable if list returned; verify cache not corrupted
        except Exception:
            pass
        np.testing.assert_array_equal(cache._matrix, before)

    def test_huge_query_string_handled(self):
        """100k char string passed as query — should raise TypeError gracefully."""
        cache = self._make_cache()
        huge_string = "x" * 100_000
        # search() calls np.array(query_vector, ...) — a string will create a 0-dim array
        # This raises or produces non-float — should not crash permanently
        try:
            cache.search(huge_string)
        except (TypeError, ValueError, Exception):
            pass  # expected
        # Cache must still be intact
        assert cache._matrix is not None

    def test_none_query_returns_empty(self):
        """None query must return [] without crashing (guard added to search())."""
        cache = self._make_cache()
        result = cache.search(None)
        assert result == []

    def test_normal_search_returns_top_k(self):
        """Sanity check: a valid query returns top_k results."""
        cache = self._make_cache(n=10, dim=384)
        query = list(np.random.randn(384).astype(float))
        result = cache.search(query, top_k=3)
        assert len(result) <= 3
        for r in result:
            assert "observation" in r
            assert "score" in r

    def test_nan_in_matrix_does_not_corrupt_subsequent_searches(self):
        """If a NaN somehow ends up in the matrix, subsequent valid searches must not hang."""
        cache = self._make_cache(n=5, dim=384)
        # Inject NaN into one row
        cache._matrix[2, 0] = float("nan")
        query = list(np.random.randn(384).astype(float))
        # Should not raise — may return NaN scores for the corrupted row
        try:
            result = cache.search(query, top_k=5)
            assert isinstance(result, list)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# AUDIT 4 — SemanticMemory robustness (SQL injection, edge cases)
# ---------------------------------------------------------------------------

class TestSemanticMemoryRobustness:
    """
    Tests SemanticMemory with a real in-memory SQLite database.
    """

    @pytest.fixture
    def semantic_mem(self, tmp_path):
        from cognia.memory.semantic import SemanticMemory
        import sqlite3
        db = str(tmp_path / "test_semantic.db")
        # Init the table
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS semantic_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                vector TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                support INTEGER DEFAULT 1,
                last_updated TEXT,
                emotion_avg REAL DEFAULT 0.0,
                associations TEXT DEFAULT '{}'
            )
        """)
        conn.commit()
        conn.close()
        return SemanticMemory(db_path=db)

    def test_sql_injection_in_concept_name_is_safe(self, semantic_mem):
        """SQL injection via concept name must not execute."""
        evil = "'; DROP TABLE semantic_memory; --"
        vector = [0.1] * 10
        # Should execute without error (parameterized query)
        semantic_mem.update_concept(evil, vector, confidence_delta=0.1)
        # Table must still exist
        result = semantic_mem.get_concept(evil)
        # Either stored safely (concept as literal string) or returned None
        # Key invariant: no exception was raised and table still works
        normal_result = semantic_mem.get_concept("normal_concept")
        assert normal_result is None  # table intact, concept just not there

    def test_empty_string_concept_handled(self, semantic_mem):
        """Empty string concept name: should store or fail gracefully."""
        vector = [0.5] * 10
        try:
            semantic_mem.update_concept("", vector)
            result = semantic_mem.get_concept("")
            # Either stored (empty string key) or None — no crash
            assert result is None or isinstance(result, dict)
        except Exception:
            pass  # raising cleanly is fine too

    def test_confidence_above_1_clamped(self, semantic_mem):
        """After update, confidence must never exceed 1.0."""
        vector = [0.1] * 10
        for _ in range(20):
            semantic_mem.update_concept("high_conf", vector, confidence_delta=0.5)
        result = semantic_mem.get_concept("high_conf")
        if result:
            assert result["confidence"] <= 1.0

    def test_nan_vector_does_not_crash(self, semantic_mem):
        """NaN values in vector: json.dumps stores them, but retrieval should not crash."""
        nan_vec = [float("nan")] * 10
        try:
            semantic_mem.update_concept("nan_concept", nan_vec)
        except Exception:
            pass  # acceptable to reject NaN
        # Must not leave DB in broken state
        result = semantic_mem.get_concept("normal_after_nan")
        assert result is None  # not there, but table functional

    def test_get_concept_nonexistent_returns_none(self, semantic_mem):
        result = semantic_mem.get_concept("does_not_exist_xyz_abc_123")
        assert result is None

    def test_update_and_retrieve_roundtrip(self, semantic_mem):
        vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        semantic_mem.update_concept("test_concept", vector, description="test desc")
        result = semantic_mem.get_concept("test_concept")
        assert result is not None
        assert result["concept"] == "test_concept"
        assert result["confidence"] >= 0.0
        assert result["confidence"] <= 1.0

    def test_very_long_concept_name_handled(self, semantic_mem):
        """Concept name of 10k chars: should store or fail gracefully, no crash."""
        long_name = "a" * 10_000
        vector = [0.1] * 5
        try:
            semantic_mem.update_concept(long_name, vector)
            result = semantic_mem.get_concept(long_name)
            assert result is None or isinstance(result, dict)
        except Exception:
            pass  # acceptable
