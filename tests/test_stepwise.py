"""Regresión del CoT dirigido (cognia/agent/stepwise.py) contra la batería REAL del bench.

Falla sin el módulo y protege el contrato medido: los 16 items de razonamiento ACTIVAN el
empujón (donde CoT dio +50 pts) y los 4 de formato NO (donde CoT rompía compliance 0.75->0.25).

Correr: .\\venv312\\Scripts\\python.exe -m pytest tests/test_stepwise.py -q
"""
from cognia.agent.stepwise import augment_stepwise, needs_stepwise, wants_exact_format
from cognia_v3.eval.bench_reasoning import FORMAT_ITEMS, ITEMS


def test_items_razonamiento_activan():
    for iid, q, _ans in ITEMS:
        assert needs_stepwise(q), f"{iid} debería activar el empujón CoT"


def test_items_formato_no_activan():
    for fid, q, _kind, _exp in FORMAT_ITEMS:
        assert wants_exact_format(q), f"{fid} debería detectarse como pedido de formato"
        assert not needs_stepwise(q), f"{fid} NO debe activar CoT (rompe compliance, medido)"


def test_social_no_activa():
    for s in ("hola", "cómo estás?", "gracias!", "contame un chiste", "qué es un agujero negro?"):
        assert not needs_stepwise(s), s


def test_augment():
    assert augment_stepwise("hola") == "hola"
    q = ITEMS[0][1]
    out = augment_stepwise(q)
    assert out.startswith(q) and "paso a paso" in out


# ── Detectores CP1 (bon/tests_first/repair) contra la bateria real ──────

def test_tests_first_activa_en_todas_las_tasks_de_codigo():
    """Las 25 tasks embebidas del bench de codigo nombran una funcion
    explicita: el detector debe activar y extraer el entry point REAL."""
    from cognia.agent.stepwise import (bon_applies, extract_entry_point,
                                       tests_first_applies)
    from cognia_v3.eval.benchmark_code import TASKS
    for t in TASKS:
        assert tests_first_applies(t["prompt"]), t["id"]
        assert bon_applies(t["prompt"]), t["id"]
        assert extract_entry_point(t["prompt"]) == t["entry_point"], t["id"]


def test_tests_first_no_activa_fuera_de_codigo():
    from cognia.agent.stepwise import bon_applies, tests_first_applies
    for s in ("hola", "resume este texto en 3 lineas",
              "cuanto es 15% de 80?",
              "lista los archivos del directorio",
              # tarea de codigo SIN entry point explicito: sin oraculo, no paga
              "mejora el rendimiento del modulo de parsing"):
        assert not tests_first_applies(s), s
        assert not bon_applies(s), s


def test_tests_first_respeta_veto_de_formato():
    from cognia.agent.stepwise import tests_first_applies
    # pedido EXPLICITO de responder en JSON -> veta
    s = ("Write a Python function `f(x)` and reply ONLY with JSON in this "
         "exact format: {\"code\": ...}")
    assert not tests_first_applies(s)


def test_tests_first_no_veta_json_topico():
    """Una tarea de codigo que MENCIONA json como tema (no como formato de
    salida) SI debe activar — regresion de LONG3 del bench duro."""
    from cognia.agent.stepwise import bon_applies, tests_first_applies
    s = ("Write a Python function `parse_json(s)` that parses a JSON document "
         "into Python objects WITHOUT importing the json module.")
    assert tests_first_applies(s)
    assert bon_applies(s)


def test_repair_applies_solo_con_veredicto_externo():
    from cognia.agent.stepwise import repair_applies
    for et in ("syntax", "assert", "runtime", "timeout"):
        assert repair_applies(et), et
    for et in ("empty", "missing_func", ""):
        assert not repair_applies(et), et


def test_bon_applies_verbos_espanol():
    """Regresion: 'Escribe/Crea/Genera una funcion X' (imperativo español) debe
    activar bon_applies. El regex viejo (escrib[ií]) NO matcheaba 'Escribe'
    (terminado en e) -> BoN nunca disparaba en tareas en español (smoke live)."""
    from cognia.agent.stepwise import bon_applies, extract_entry_point
    activan = [
        "Escribe en primo.py una funcion es_primo(n) que devuelva True si n es primo",
        "Crea una funcion factorial(n) recursiva",
        "Genera la funcion suma(a, b)",
        "Programa la funcion ordenar(lista)",
    ]
    for t in activan:
        assert bon_applies(t), t
        assert extract_entry_point(t) is not None, t
    # sin funcion/entry point NO activa (aunque tenga el verbo)
    for t in ("escribe un poema sobre el mar", "crea una carpeta nueva"):
        assert not bon_applies(t), t


# ── classify_exec_error + build_exec_repair_hint (wire palanca #4) ────────

from cognia.agent.stepwise import build_exec_repair_hint, classify_exec_error


def test_classify_timeout():
    r = ("RESULTADO ejecutar ERROR: timeout tras 30s. "
         "Acota el comando (ruta/target mas especifico) y reintenta.")
    assert classify_exec_error("ejecutar", r) == "timeout"


def test_classify_syntax_py_validar():
    r = "RESULTADO py_validar foo.py: ERROR linea 3: invalid syntax"
    assert classify_exec_error("py_validar", r) == "syntax"


def test_classify_syntax_en_pytest():
    r = ("RESULTADO ejecutar (exit 2): E     SyntaxError: invalid syntax\n"
         "1 error in 0.12s")
    assert classify_exec_error("ejecutar", r) == "syntax"


def test_classify_assert_pytest_failed():
    r = ("RESULTADO ejecutar (exit 1): FAILED tests/test_x.py::test_a - "
         "AssertionError: assert 3 == 4\n1 failed, 2 passed in 0.30s")
    assert classify_exec_error("tests", r) == "assert"


def test_classify_runtime_traceback():
    r = ("RESULTADO ejecutar (exit 1): Traceback (most recent call last):\n"
         "  File \"foo.py\", line 2, in <module>\nNameError: name 'x' is not defined")
    assert classify_exec_error("ejecutar", r) == "runtime"


def test_classify_exit_no_cero_sin_traceback_es_runtime():
    r = "RESULTADO ejecutar (exit 1): comando fallo sin mas detalle"
    assert classify_exec_error("ejecutar", r) == "runtime"


def test_classify_exito_es_none():
    assert classify_exec_error("ejecutar", "RESULTADO ejecutar: 42") is None
    assert classify_exec_error("tests",
        "RESULTADO ejecutar: 3 passed in 0.5s") is None
    assert classify_exec_error("py_validar",
        "RESULTADO py_validar foo.py: sintaxis OK") is None


def test_classify_error_de_uso_es_none():
    # el aviso de uso de `tests` sin ruta no es un fallo de ejecucion
    r = ("RESULTADO tests ERROR: pasa una ruta ESPECIFICA (archivo o dir), "
         "p.ej. 'tests/test_foo.py'.")
    assert classify_exec_error("tests", r) is None


def test_classify_bloqueado_es_none():
    assert classify_exec_error("ejecutar",
        "RESULTADO ejecutar: BLOQUEADO por seguridad") is None


def test_classify_tool_no_ejecutora_es_none():
    # un grep que ENCUENTRA 'SyntaxError' en un archivo no es un error
    r = "RESULTADO buscar 'SyntaxError': foo.py:12: raise SyntaxError(...)"
    assert classify_exec_error("buscar", r) is None


def test_repair_hint_trae_el_error_real_y_la_instruccion():
    r = "RESULTADO ejecutar (exit 1): Traceback ...\nNameError: name 'x'"
    h = build_exec_repair_hint("runtime", r)
    assert "REPARACION (runtime)" in h
    assert "NameError: name 'x'" in h
    assert "escribir_archivo" in h and "generar_codigo" in h


def test_repair_hint_acota_la_cola():
    r = "X" * 5000
    h = build_exec_repair_hint("assert", r, max_chars=200)
    assert h.count("X") == 200


def test_clasificador_alimenta_repair_applies():
    # los 4 tipos que emite el clasificador son exactamente los reparables
    from cognia.agent.stepwise import repair_applies
    for t in ("timeout", "syntax", "assert", "runtime"):
        assert repair_applies(t)
