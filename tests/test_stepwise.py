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
