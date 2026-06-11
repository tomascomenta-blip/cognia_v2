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


# ---------------------------------------------------------------------------
# parse_search_replace / apply_edits — repair por EDICION (--repair-mode edit)
# ---------------------------------------------------------------------------

def _sr_block(old: str, new: str) -> str:
    return ("<<<<<<< SEARCH\n" + old + "\n=======\n" + new
            + "\n>>>>>>> REPLACE")


class TestParseSearchReplace:
    def test_single_block(self):
        from cognia_v3.eval.benchmark_code import parse_search_replace
        text = _sr_block("    if n % 2 == 1:", "    if n % 2 == 0:")
        assert parse_search_replace(text) == [
            ("    if n % 2 == 1:", "    if n % 2 == 0:")]

    def test_multiple_blocks_in_order(self):
        from cognia_v3.eval.benchmark_code import parse_search_replace
        text = (_sr_block("a = 1", "a = 2") + "\n\n"
                + _sr_block("b = 3", "b = 4"))
        assert parse_search_replace(text) == [
            ("a = 1", "a = 2"), ("b = 3", "b = 4")]

    def test_prose_around_blocks_ignored(self):
        from cognia_v3.eval.benchmark_code import parse_search_replace
        text = ("The bug is in the modulo check. Here is the fix:\n\n"
                + _sr_block("    return x - 1", "    return x + 1")
                + "\n\nThis fixes the off-by-one error.")
        assert parse_search_replace(text) == [
            ("    return x - 1", "    return x + 1")]

    def test_multiline_sections(self):
        from cognia_v3.eval.benchmark_code import parse_search_replace
        old = "    for i in items:\n        print(i)"
        new = "    for i in items:\n        yield i"
        assert parse_search_replace(_sr_block(old, new)) == [(old, new)]

    def test_no_blocks_returns_empty(self):
        from cognia_v3.eval.benchmark_code import parse_search_replace
        assert parse_search_replace("Here is the corrected function...") == []
        assert parse_search_replace("") == []

    def test_empty_replace_means_deletion(self):
        from cognia_v3.eval.benchmark_code import parse_search_replace
        text = "<<<<<<< SEARCH\n    debug_print(x)\n=======\n>>>>>>> REPLACE"
        assert parse_search_replace(text) == [("    debug_print(x)", "")]


class TestApplyEdits:
    CODE = ("def f(items):\n"
            "    total = 0\n"
            "    for i in items:\n"
            "        total += i\n"
            "    return total\n")

    def test_single_edit_applies(self):
        from cognia_v3.eval.benchmark_code import apply_edits
        out = apply_edits(self.CODE, [("        total += i",
                                       "        total += i * 2")])
        assert out is not None
        assert "total += i * 2" in out

    def test_search_not_found_returns_none(self):
        from cognia_v3.eval.benchmark_code import apply_edits
        assert apply_edits(self.CODE, [("        total -= i", "x")]) is None

    def test_ambiguous_search_returns_none(self):
        """SEARCH que aparece 2 veces: sin fuzzy ni eleccion arbitraria."""
        from cognia_v3.eval.benchmark_code import apply_edits
        code = "x = 1\ny = 2\nx = 1\n"
        assert apply_edits(code, [("x = 1", "x = 9")]) is None

    def test_empty_edit_list_returns_none(self):
        from cognia_v3.eval.benchmark_code import apply_edits
        assert apply_edits(self.CODE, []) is None

    def test_multiple_edits_apply_in_order(self):
        from cognia_v3.eval.benchmark_code import apply_edits
        out = apply_edits(self.CODE, [("    total = 0", "    total = 1"),
                                      ("    return total", "    return total - 1")])
        assert "total = 1" in out and "return total - 1" in out

    def test_edit_that_breaks_syntax_is_caught_by_ast(self):
        """El repair-edit valida con ast.parse: un edit roto NO se adopta."""
        import ast
        import pytest
        from cognia_v3.eval.benchmark_code import apply_edits
        out = apply_edits(self.CODE, [("    for i in items:",
                                       "    for i in items")])  # sin ':'
        assert out is not None  # el reemplazo exacto aplica...
        with pytest.raises(SyntaxError):
            ast.parse(out)      # ...pero el pipeline lo rechaza (syntax_after_edit)

    def test_full_pipeline_parse_then_apply(self):
        """Flujo completo respuesta-del-modelo -> edits -> codigo corregido."""
        from cognia_v3.eval.benchmark_code import apply_edits, parse_search_replace
        response = ("Sure! The loop accumulates wrong:\n"
                    + _sr_block("        total += i", "        total += abs(i)"))
        edits = parse_search_replace(response)
        out = apply_edits(self.CODE, edits)
        assert out == self.CODE.replace("total += i", "total += abs(i)")
