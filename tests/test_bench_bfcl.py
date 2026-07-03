"""
tests/test_bench_bfcl.py
Tests para cognia_v3/eval/bfcl_ast_checker.py y bench_bfcl_slice.py --
sin red ni modelo, con fixtures inline (no dependen de los JSON descargados
en data/bfcl/, salvo los 2 tests de la clase TestHarnessSlice al final que
leen la slice congelada ya materializada en el repo).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# parse_model_response -- texto crudo del modelo -> llamadas parseadas
# ---------------------------------------------------------------------------

class TestParseModelResponse:
    def test_single_call(self):
        from cognia_v3.eval.bfcl_ast_checker import parse_model_response
        calls, err = parse_model_response("f(a=1)")
        assert err is None
        assert calls == [{"f": {"a": 1}}]

    def test_multiple_calls_semicolon_separated(self):
        from cognia_v3.eval.bfcl_ast_checker import parse_model_response
        calls, err = parse_model_response("f(a=1); g(b=2, c='x')")
        assert err is None
        assert calls == [{"f": {"a": 1}}, {"g": {"b": 2, "c": "x"}}]

    def test_prose_around_calls_ignored(self):
        from cognia_v3.eval.bfcl_ast_checker import parse_model_response
        text = "Sure, here is the call: f(a=1) -- that should do it."
        calls, err = parse_model_response(text)
        assert err is None
        assert calls == [{"f": {"a": 1}}]

    def test_code_fence_stripped(self):
        from cognia_v3.eval.bfcl_ast_checker import parse_model_response
        calls, err = parse_model_response("```python\nf(a=1)\n```")
        assert err is None
        assert calls == [{"f": {"a": 1}}]

    def test_dotted_function_name(self):
        from cognia_v3.eval.bfcl_ast_checker import parse_model_response
        calls, err = parse_model_response("math.hypot(x=3, y=4)")
        assert err is None
        assert calls == [{"math.hypot": {"x": 3, "y": 4}}]

    def test_empty_response(self):
        from cognia_v3.eval.bfcl_ast_checker import parse_model_response
        assert parse_model_response("") == ([], "empty")
        assert parse_model_response("   ") == ([], "empty")

    def test_garbage_returns_no_calls_parsed(self):
        from cognia_v3.eval.bfcl_ast_checker import parse_model_response
        calls, err = parse_model_response("I cannot help with that request.")
        assert calls == []
        assert err == "no_calls_parsed"

    def test_negative_number_argument(self):
        from cognia_v3.eval.bfcl_ast_checker import parse_model_response
        calls, err = parse_model_response("f(a=-5)")
        assert err is None
        assert calls == [{"f": {"a": -5}}]

    def test_list_and_dict_arguments(self):
        from cognia_v3.eval.bfcl_ast_checker import parse_model_response
        calls, err = parse_model_response("f(items=[1, 2, 3], opts={'k': 'v'})")
        assert err is None
        assert calls == [{"f": {"items": [1, 2, 3], "opts": {"k": "v"}}}]


# ---------------------------------------------------------------------------
# check_response -- el oraculo completo (parse + ast_checker), categoria
# "simple": 1 sola funcion disponible, 1 sola llamada esperada.
# ---------------------------------------------------------------------------

TRIANGLE_FUNCTIONS = [{
    "name": "calculate_triangle_area",
    "description": "Calculate the area of a triangle given its base and height.",
    "parameters": {
        "type": "dict",
        "properties": {
            "base": {"type": "integer", "description": "The base of the triangle."},
            "height": {"type": "integer", "description": "The height of the triangle."},
            "unit": {"type": "string", "description": "Unit of measure (optional)."},
        },
        "required": ["base", "height"],
    },
}]
TRIANGLE_GROUND_TRUTH = [{
    "calculate_triangle_area": {"base": [10], "height": [5], "unit": ["units", ""]}
}]


class TestCheckResponseSimple:
    """Los 3 casos negativos pedidos por la tarea (nombre malo, param
    requerido faltante, valor no aceptado) + el caso positivo de control."""

    def test_positive_case_passes(self):
        from cognia_v3.eval.bfcl_ast_checker import check_response
        passed, error_type, _ = check_response(
            "simple", TRIANGLE_FUNCTIONS, TRIANGLE_GROUND_TRUTH,
            "calculate_triangle_area(base=10, height=5)")
        assert passed
        assert error_type == ""

    def test_optional_param_may_be_supplied_and_still_pass(self):
        from cognia_v3.eval.bfcl_ast_checker import check_response
        passed, _, _ = check_response(
            "simple", TRIANGLE_FUNCTIONS, TRIANGLE_GROUND_TRUTH,
            "calculate_triangle_area(base=10, height=5, unit='units')")
        assert passed

    def test_wrong_function_name_fails(self):
        from cognia_v3.eval.bfcl_ast_checker import check_response
        passed, error_type, _ = check_response(
            "simple", TRIANGLE_FUNCTIONS, TRIANGLE_GROUND_TRUTH,
            "bad_calculate_triangle_area(base=10, height=5)")
        assert not passed
        assert error_type == "simple_function_checker:wrong_func_name"

    def test_missing_required_param_fails(self):
        from cognia_v3.eval.bfcl_ast_checker import check_response
        passed, error_type, _ = check_response(
            "simple", TRIANGLE_FUNCTIONS, TRIANGLE_GROUND_TRUTH,
            "calculate_triangle_area(height=5)")
        assert not passed
        assert error_type == "simple_function_checker:missing_required"

    def test_bad_value_fails(self):
        from cognia_v3.eval.bfcl_ast_checker import check_response
        passed, error_type, _ = check_response(
            "simple", TRIANGLE_FUNCTIONS, TRIANGLE_GROUND_TRUTH,
            "calculate_triangle_area(base=99, height=5)")
        assert not passed
        assert error_type == "value_error:others"

    def test_empty_response_fails(self):
        from cognia_v3.eval.bfcl_ast_checker import check_response
        passed, error_type, _ = check_response(
            "simple", TRIANGLE_FUNCTIONS, TRIANGLE_GROUND_TRUTH, "")
        assert not passed
        assert error_type == "empty"

    def test_dot_mangled_function_name_tolerated(self):
        """El modelo puede reproducir 'math.hypot' con '_' en vez de '.'
        (mangling) -- ver simplificacion #2 del docstring del checker."""
        from cognia_v3.eval.bfcl_ast_checker import check_response
        functions = [{
            "name": "math.hypot",
            "parameters": {
                "type": "dict",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"],
            },
        }]
        ground_truth = [{"math.hypot": {"x": [3], "y": [4]}}]
        passed, _, _ = check_response("simple", functions, ground_truth,
                                      "math_hypot(x=3, y=4)")
        assert passed


# ---------------------------------------------------------------------------
# check_response -- categorias "parallel" y "multiple"
# ---------------------------------------------------------------------------

class TestCheckResponseParallelAndMultiple:
    def test_parallel_matches_any_order(self):
        """parallel: N llamadas a la MISMA funcion, orden NO importa."""
        from cognia_v3.eval.bfcl_ast_checker import check_response
        functions = [{
            "name": "f",
            "parameters": {"type": "dict", "properties": {"a": {"type": "integer"}},
                          "required": ["a"]},
        }]
        ground_truth = [{"f": {"a": [1]}}, {"f": {"a": [2]}}]
        # respuesta en orden INVERTIDO al ground truth: debe seguir pasando
        passed, _, _ = check_response("parallel", functions, ground_truth,
                                      "f(a=2); f(a=1)")
        assert passed

    def test_parallel_wrong_count_fails(self):
        from cognia_v3.eval.bfcl_ast_checker import check_response
        functions = [{
            "name": "f",
            "parameters": {"type": "dict", "properties": {"a": {"type": "integer"}},
                          "required": ["a"]},
        }]
        ground_truth = [{"f": {"a": [1]}}, {"f": {"a": [2]}}]
        passed, error_type, _ = check_response("parallel", functions, ground_truth, "f(a=1)")
        assert not passed
        assert "wrong_count" in error_type

    def test_multiple_picks_the_right_function_among_choices(self):
        """multiple: varias funciones DISPONIBLES, el modelo debe elegir la
        correcta (no la primera de la lista)."""
        from cognia_v3.eval.bfcl_ast_checker import check_response
        functions = [
            {"name": "f1", "parameters": {"type": "dict",
                                          "properties": {"a": {"type": "integer"}},
                                          "required": ["a"]}},
            {"name": "f2", "parameters": {"type": "dict",
                                          "properties": {"b": {"type": "integer"}},
                                          "required": ["b"]}},
        ]
        ground_truth = [{"f2": {"b": [5]}}]
        passed, _, _ = check_response("multiple", functions, ground_truth, "f2(b=5)")
        assert passed
        # eligiendo la funcion incorrecta (f1 en vez de f2 pedido) -> FAIL
        passed_wrong, error_type, _ = check_response(
            "multiple", functions, ground_truth, "f1(a=5)")
        assert not passed_wrong


# ---------------------------------------------------------------------------
# bench_bfcl_slice: la slice congelada ya materializada en el repo (datos
# locales descargados, sin red) -- verifica forma y determinismo del archivo.
# ---------------------------------------------------------------------------

class TestHarnessSlice:
    def test_slice_is_200_items_40_per_category(self):
        from cognia_v3.eval.bench_bfcl_slice import build_slice, CATEGORIES, PER_CATEGORY
        slice_items = build_slice()
        assert len(slice_items) == len(CATEGORIES) * PER_CATEGORY
        counts = {}
        for entry in slice_items:
            counts[entry["category"]] = counts.get(entry["category"], 0) + 1
        assert counts == {cat: PER_CATEGORY for cat in CATEGORIES}

    def test_slice_ids_are_unique(self):
        from cognia_v3.eval.bench_bfcl_slice import build_slice
        slice_items = build_slice()
        ids = [entry["id"] for entry in slice_items]
        assert len(ids) == len(set(ids))


# ── Brazo v1 (fewshot + validate/repair) — CP1 eje-1, sin modelo ni red ──

def test_validate_calls_v1():
    from cognia_v3.eval.bench_bfcl_slice import validate_calls, available_names
    from cognia_v3.eval.bfcl_ast_checker import parse_model_response
    funcs = [{"name": "get_weather",
              "parameters": {"type": "object",
                             "properties": {"city": {"type": "string"}}}}]
    # llamada valida -> None
    calls, err = parse_model_response('get_weather(city="Paris")')
    assert validate_calls(calls, err, funcs) is None
    # nombre inexistente -> error accionable
    calls, err = parse_model_response('get_wether(city="Paris")')
    assert validate_calls(calls, err, funcs) is not None
    # nada parseable -> error
    calls, err = parse_model_response("solo prosa sin llamadas")
    assert validate_calls(calls, err, funcs) is not None
    # mangling . -> _ tolerado
    assert "math_hypot" in available_names([{"name": "math.hypot"}])


def test_fewshot_prefix_cero_leakage():
    """El prompt con fewshot=0 no lleva ejemplos (baseline byte-identico);
    fewshot>0 los agrega. Los ejemplos NO son de la slice."""
    from cognia_v3.eval.bench_bfcl_slice import (
        FEWSHOT_EXEMPLARS_BFCL, build_fewshot_prefix_bfcl, build_prompt)
    assert build_fewshot_prefix_bfcl(0) == ""
    assert "get_weather" in build_fewshot_prefix_bfcl(2)
    funcs = [{"name": "f", "parameters": {}}]
    assert "Examples" not in build_prompt(funcs, "q", fewshot=0)
    assert "Examples" in build_prompt(funcs, "q", fewshot=2)
    # los exemplars usan funciones inventadas, no de BFCL
    joined = " ".join(e[2] for e in FEWSHOT_EXEMPLARS_BFCL)
    assert "get_weather" in joined and "add_numbers" in joined
