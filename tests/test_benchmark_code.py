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


# ---------------------------------------------------------------------------
# FEWSHOT_EXEMPLARS / build_prompt(fewshot=N) — flag --fewshot
# ---------------------------------------------------------------------------

class TestFewshot:
    TASK_PROMPT = "Write a Python function `dummy(x)` that returns x."

    def test_fewshot_zero_prompt_byte_identical(self):
        """Con N=0 el prompt es BYTE-identico al comportamiento previo."""
        from cognia_v3.eval.benchmark_code import build_fewshot_prefix, build_prompt
        assert build_fewshot_prefix(0) == ""
        assert build_prompt(self.TASK_PROMPT, fewshot=0) == build_prompt(self.TASK_PROMPT)
        # Reconstruccion del template previo (sin few-shot) a mano:
        from node.inference_pipeline import _apply_qwen_template
        from cognia_v3.eval.benchmark_code import SYSTEM_PROMPT
        expected = _apply_qwen_template(self.TASK_PROMPT, system=SYSTEM_PROMPT)
        assert build_prompt(self.TASK_PROMPT, fewshot=0) == expected

    def test_fewshot_two_contains_exemplars_and_real_task_last(self):
        """Con N=2 el prompt trae ambos ejemplos y el enunciado real al final."""
        from cognia_v3.eval.benchmark_code import FEWSHOT_EXEMPLARS, build_prompt
        prompt = build_prompt(self.TASK_PROMPT, fewshot=2)
        assert "Ejemplos resueltos:" in prompt
        assert prompt.count("[Problema]") == 2
        assert prompt.count("[Solucion]") == 2
        for problem, solution in FEWSHOT_EXEMPLARS:
            assert problem in prompt
            assert solution in prompt
        # El enunciado real va DESPUES de todos los ejemplos
        real_pos = prompt.index("Ahora resuelve:\n\n" + self.TASK_PROMPT)
        for problem, _ in FEWSHOT_EXEMPLARS:
            assert prompt.index(problem) < real_pos

    def test_exemplar_solutions_compile(self):
        """Cada solucion de FEWSHOT_EXEMPLARS es codigo Python valido."""
        import ast
        from cognia_v3.eval.benchmark_code import FEWSHOT_EXEMPLARS
        assert len(FEWSHOT_EXEMPLARS) == 2
        for _, solution in FEWSHOT_EXEMPLARS:
            ast.parse(solution)
