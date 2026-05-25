"""
tests/test_phase24.py — Phase 24: Workers deterministas + Synthesizer
"""

import os
import tempfile
from pathlib import Path

import pytest

from cognia.agents.workers.file_explorer import (
    explore, index_to_dict, ProjectIndex, FileSymbols, MAX_FILES, MAX_DEPTH
)
from cognia.agents.workers.research_worker import research
from cognia.agents.synthesizer import synthesize, _build_context, _deterministic_summary
from cognia.agents.planner import SubTask
from cognia.agents.tool_registry import get_tool_registry


# ── FileExplorer ──────────────────────────────────────────────────────────────

@pytest.fixture
def py_file(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(
        "import os\nimport sys\n\nclass Foo:\n    def bar(self):\n        pass\n\n"
        "def hello():\n    print('hi')\n"
    )
    return f


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "main.py").write_text("def main():\n    pass\n")
    (tmp_path / "utils.py").write_text("import os\nclass Helper:\n    pass\n")
    (tmp_path / "README.md").write_text("# Project\n")
    sub = tmp_path / "subpkg"
    sub.mkdir()
    (sub / "__init__.py").write_text("")
    (sub / "logic.py").write_text("def compute(x):\n    return x * 2\n")
    return tmp_path


class TestFileExplorer:
    def test_explore_single_file(self, py_file):
        idx = explore(str(py_file))
        assert isinstance(idx, ProjectIndex)
        assert idx.total_files == 1
        sym = list(idx.symbols.values())[0]
        assert "bar" in sym.functions
        assert "hello" in sym.functions
        assert "Foo" in sym.classes

    def test_explore_imports_detected(self, py_file):
        idx = explore(str(py_file))
        sym = list(idx.symbols.values())[0]
        assert "os" in sym.imports
        assert "sys" in sym.imports

    def test_explore_directory(self, project_dir):
        idx = explore(str(project_dir))
        assert idx.total_files >= 4
        assert idx.truncated is False
        py_paths = [f for f in idx.files if f.endswith(".py")]
        assert len(py_paths) >= 3

    def test_explore_nonexistent_path(self):
        idx = explore("/nonexistent/path/xyz")
        assert idx.total_files == 0
        assert idx.files == []

    def test_explore_syntax_error_file(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def foo(:\n    pass\n")
        idx = explore(str(bad))
        sym = list(idx.symbols.values())[0]
        assert sym.error is not None
        assert "SyntaxError" in sym.error

    def test_index_to_dict_is_json_safe(self, project_dir):
        import json
        idx = explore(str(project_dir))
        d = index_to_dict(idx)
        # Debe ser serializable a JSON
        serialized = json.dumps(d)
        assert len(serialized) > 0
        assert "total_files" in d
        assert "files" in d

    def test_ignores_pycache(self, project_dir):
        cache = project_dir / "__pycache__"
        cache.mkdir()
        (cache / "main.cpython-311.pyc").write_bytes(b"fake bytecode")
        idx = explore(str(project_dir))
        assert not any("__pycache__" in f for f in idx.files)

    def test_depth_limit(self, tmp_path):
        current = tmp_path
        for i in range(MAX_DEPTH + 2):
            current = current / f"level{i}"
            current.mkdir()
            (current / f"file{i}.py").write_text(f"# level {i}\n")
        idx = explore(str(tmp_path))
        max_depth_found = max(
            (len(Path(f).parts) for f in idx.files), default=0
        )
        assert max_depth_found <= MAX_DEPTH + 1  # +1 por el root

    def test_file_explorer_registered_in_registry(self):
        reg = get_tool_registry()
        assert "file_explorer" in reg.names()

    def test_file_explorer_tool_runs(self, project_dir):
        reg = get_tool_registry()
        result = reg.execute("file_explorer", path=str(project_dir))
        assert result.success is True
        assert result.output["total_files"] >= 4


# ── ResearchWorker ────────────────────────────────────────────────────────────

class TestResearchWorker:
    def test_returns_dict_with_required_keys(self):
        result = research("Python programming language")
        assert "source" in result
        assert "content" in result
        assert "found" in result

    def test_episodic_hit_used_first(self):
        class FakeEpisode:
            similarity = 0.90
            observation = "Python is a high-level language."
        class FakeVCache:
            def search(self, emb, top_k=1):
                return [FakeEpisode()]
        class FakeEpisodicMemory:
            pass

        # Mock cognia_embedding para que devuelva un vector
        import sys
        from unittest.mock import patch, MagicMock
        mock_emb = MagicMock(return_value=[0.1] * 384)
        with patch.dict(sys.modules, {"cognia.cognia_embedding": MagicMock(text_to_vector_fast=mock_emb)}):
            result = research(
                "Python language",
                episodic_memory=FakeEpisodicMemory(),
                vector_cache=FakeVCache(),
            )
        assert result["source"] == "episodic"
        assert "Python" in result["content"]

    def test_episodic_low_similarity_falls_through(self):
        class FakeEpisode:
            similarity = 0.30   # bajo umbral
            observation = "unrelated"
        class FakeVCache:
            def search(self, emb, top_k=1):
                return [FakeEpisode()]
        class FakeEpisodicMemory:
            pass

        import sys
        from unittest.mock import patch, MagicMock
        mock_emb = MagicMock(return_value=[0.1] * 384)
        with patch.dict(sys.modules, {"cognia.cognia_embedding": MagicMock(text_to_vector_fast=mock_emb)}):
            result = research(
                "Python language",
                episodic_memory=FakeEpisodicMemory(),
                vector_cache=FakeVCache(),
            )
        # Debe haber caído a wikipedia o llm, no episodic
        assert result["source"] != "episodic"

    def test_research_tool_registered(self):
        reg = get_tool_registry()
        assert "research" in reg.names()


# ── Synthesizer ───────────────────────────────────────────────────────────────

class TestSynthesizer:
    def _make_subtasks(self, task_id="t1"):
        return [
            SubTask(id=f"{task_id}_search",    description="Search: Python",  tool_required="search_wikipedia"),
            SubTask(id=f"{task_id}_synthesize", description="Synthesize",      tool_required="synthesize",
                    dependencies=[f"{task_id}_search"]),
        ]

    def test_deterministic_summary_no_orchestrator(self):
        subtasks = self._make_subtasks()
        results = {subtasks[0].id: {"content": "Python is a programming language."}}
        output = synthesize("What is Python?", subtasks, results, orchestrator=None)
        assert "Python" in output
        assert len(output) > 0

    def test_synthesize_skips_synthesize_subtask(self):
        subtasks = self._make_subtasks()
        results = {
            subtasks[0].id: {"content": "relevant info"},
            subtasks[1].id: {"content": "this should be skipped"},
        }
        output = _deterministic_summary("task", subtasks, results)
        # La subtarea 'synthesize' no debe aparecer en el output
        assert "this should be skipped" not in output

    def test_build_context_respects_budget(self):
        subtasks = self._make_subtasks()
        # Resultado muy largo
        results = {subtasks[0].id: {"content": "x" * 5000}}
        context = _build_context("task description", subtasks, results)
        # El contexto no debe exceder ~1500 chars (buffer generoso)
        assert len(context) < 2000

    def test_empty_results_returns_no_results_message(self):
        subtasks = self._make_subtasks()
        output = _deterministic_summary("my task", subtasks, {})
        assert "No results" in output or "my task" in output

    def test_synthesize_with_mock_orchestrator(self):
        from unittest.mock import MagicMock
        mock_orch = MagicMock()
        mock_orch.infer.return_value = MagicMock(text="Synthesized answer about Python.")

        subtasks = self._make_subtasks()
        results = {subtasks[0].id: {"content": "Python info"}}
        output = synthesize("What is Python?", subtasks, results, orchestrator=mock_orch)

        mock_orch.infer.assert_called_once()
        assert "Synthesized answer" in output

    def test_synthesize_falls_back_if_orchestrator_raises(self):
        from unittest.mock import MagicMock
        mock_orch = MagicMock()
        mock_orch.infer.side_effect = RuntimeError("LLM unavailable")

        subtasks = self._make_subtasks()
        results = {subtasks[0].id: {"content": "Python info"}}
        output = synthesize("What is Python?", subtasks, results, orchestrator=mock_orch)

        # Debe caer al deterministic summary sin lanzar excepción
        assert len(output) > 0
        assert "Python" in output


# ── Integración: Runtime con file_explorer ────────────────────────────────────

class TestRuntimeWithWorkers:
    def test_analyze_file_task_completes(self, tmp_path, tmp_db=None):
        import tempfile
        db = tempfile.mktemp(suffix=".db")
        py_file = tmp_path / "hello.py"
        py_file.write_text("def greet(name):\n    print(f'Hello {name}')\n")

        from cognia.agents.supervisor import CogniaAgentRuntime
        from cognia.agents.task_queue import DONE, FAILED, ABORTED
        runtime = CogniaAgentRuntime(db_path=db)
        tid = runtime.submit(f"analiza el archivo {py_file}")
        runtime.tick()
        record = runtime.status(tid)
        assert record.status in {DONE, FAILED, ABORTED}
        assert record.result is not None
        # Limpiar
        try:
            os.unlink(db)
        except OSError:
            pass
