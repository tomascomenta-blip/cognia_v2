"""
tests/test_benchmark_code.py
Tests for cognia_v3/eval/benchmark_code.py — sin modelo ni server real.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# GRAMMAR_PYTHON_BLOCK — la GBNF que restringe el output a un bloque python
# ---------------------------------------------------------------------------

class TestGrammarPythonBlock:
    def test_non_empty_and_has_root_rule(self):
        from cognia_v3.eval.benchmark_code import GRAMMAR_PYTHON_BLOCK
        assert GRAMMAR_PYTHON_BLOCK.strip()
        assert "root ::=" in GRAMMAR_PYTHON_BLOCK

    def test_forces_python_fence_literals(self):
        """La gramatica abre con ```python\\n y cierra con ``` (literales GBNF)."""
        from cognia_v3.eval.benchmark_code import GRAMMAR_PYTHON_BLOCK
        assert '"```python\\n"' in GRAMMAR_PYTHON_BLOCK
        assert '"```"' in GRAMMAR_PYTHON_BLOCK

    def test_extract_code_handles_grammar_shaped_output(self):
        """Un output con la forma que impone la gramatica se extrae limpio."""
        from cognia_v3.eval.benchmark_code import extract_code
        out = "```python\ndef suma(a, b):\n    return a + b\n```"
        assert extract_code(out) == "def suma(a, b):\n    return a + b"
        # Variante con el newline final opcional que permite la gramatica
        assert extract_code(out + "\n") == "def suma(a, b):\n    return a + b"
