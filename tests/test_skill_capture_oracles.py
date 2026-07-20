"""
Regresion del registro pluggable de reconocedores de oraculo duro
(cognia/agent/skill_capture.py, TAREA 1 de la corrida-agente skills).

hard_oracle_evidence() ya no reconoce un solo formato (pytest 'N passed');
ahora prueba una lista de reconocedores (action, result_head) -> bool.
Fija: (a) el v1 original sigue andando igual (regresion), (b) el formato
REAL de generar_codigo/BoN (candidates.py via tools.py:_generar_codigo:
'tests visibles X/Y'), (c) el formato REAL de contracts.py:attribute_failure
('todos los contratos pasan'), y (d) que el conjunto no matchea evidencia
falsa (ERROR, vacio, 'failed', parcial).
"""
import cognia.agent.skill_capture as SC


# ── (a) v1 original: tool 'tests' con 'N passed' sin 'failed' ──────────

def test_recognizer_pytest_verde():
    assert SC._recognize_pytest_verde("tests", "RESULTADO ejecutar: 5 passed in 0.1s")
    assert not SC._recognize_pytest_verde("tests", "3 passed, 1 failed")
    assert not SC._recognize_pytest_verde("otra_accion", "5 passed")


def test_hard_oracle_evidence_pytest_regresion():
    trace = [{"action": "tests", "ok": True, "args": "t.py",
              "result_head": "RESULTADO ejecutar: 5 passed in 0.1s"}]
    ev = SC.hard_oracle_evidence(trace)
    assert ev and "tests" in ev


# ── (b) formato REAL de generar_codigo (BoN, candidates.py) ────────────
# _generar_codigo (tools.py) emite:
#   "RESULTADO generar_codigo <path>: OK (mejor de N candidatos unicos,
#    rank=<mode>, tests visibles X/Y, Z chars)"

def test_recognizer_bon_tests_visibles_todos_pasan():
    head = ("RESULTADO generar_codigo doble.py: OK (mejor de 5 candidatos "
            "unicos, rank=tests, tests visibles 4/4, 120 chars)")
    assert SC._recognize_bon_tests_visibles("generar_codigo", head)


def test_recognizer_bon_rechaza_parcial_y_greedy_fallback():
    # parcial: 3 de 4 asserts -- no es 'verde total'
    parcial = ("RESULTADO generar_codigo x.py: OK (mejor de 3 candidatos "
               "unicos, rank=tests, tests visibles 3/4, 90 chars)")
    assert not SC._recognize_bon_tests_visibles("generar_codigo", parcial)
    # greedy_fallback: 0/0 -- no hubo asserts que ejecutar, no es oraculo
    sin_asserts = ("RESULTADO generar_codigo x.py: OK (mejor de 2 candidatos "
                   "unicos, rank=greedy_fallback, tests visibles 0/0, 50 chars)")
    assert not SC._recognize_bon_tests_visibles("generar_codigo", sin_asserts)


def test_hard_oracle_evidence_bon_captura():
    trace = [{"action": "generar_codigo", "ok": True, "args": "doble.py | doble(n)",
              "result_head": ("RESULTADO generar_codigo doble.py: OK (mejor de 5 "
                              "candidatos unicos, rank=tests, tests visibles 4/4, "
                              "120 chars)")}]
    ev = SC.hard_oracle_evidence(trace)
    assert ev and "generar_codigo" in ev


# ── (c) formato REAL de contracts.py:attribute_failure ─────────────────
# attribute_failure devuelve {"stage": None, "reason": "todos los
# contratos pasan", "contract": None} cuando los 3 contratos pasan.

def test_recognizer_contratos_pasan():
    assert SC._recognize_contratos_pasan(
        "contratos", "RESULTADO contratos: todos los contratos pasan")
    assert not SC._recognize_contratos_pasan(
        "contratos", "RESULTADO contratos ERROR: tests fallan (assert): ...")
    assert not SC._recognize_contratos_pasan("otra_accion",
                                             "todos los contratos pasan")


def test_hard_oracle_evidence_contratos_captura():
    trace = [{"action": "contratos", "ok": True, "args": "pipeline",
              "result_head": "RESULTADO contratos: todos los contratos pasan"}]
    ev = SC.hard_oracle_evidence(trace)
    assert ev and "contratos" in ev


# ── (d) el conjunto no acepta evidencia sin sustancia ───────────────────

def test_hard_oracle_evidence_rechaza_sin_evidencia():
    casos = [
        {"action": "tests", "ok": True, "args": "x", "result_head": "ERROR"},
        {"action": "tests", "ok": True, "args": "x", "result_head": ""},
        {"action": "tests", "ok": True, "args": "x", "result_head": "3 failed"},
        {"action": "generar_codigo", "ok": True, "args": "x",
         "result_head": "RESULTADO generar_codigo ERROR: no se genero funcion"},
        {"action": "contratos", "ok": True, "args": "x",
         "result_head": "RESULTADO contratos ERROR: design no cubre entidad"},
    ]
    for caso in casos:
        assert SC.hard_oracle_evidence([caso]) == "", caso


def test_hard_oracle_evidence_ignora_pasos_no_ok():
    # ok=False: aunque el texto tenga el formato correcto, no cuenta.
    trace = [{"action": "generar_codigo", "ok": False, "args": "x",
              "result_head": ("RESULTADO generar_codigo x.py: OK (mejor de 2 "
                              "candidatos unicos, rank=tests, tests visibles "
                              "4/4, 50 chars)")}]
    assert SC.hard_oracle_evidence(trace) == ""


# ── registro pluggable: extensible sin tocar hard_oracle_evidence ──────

def test_register_oracle_recognizer_extiende_el_registro(monkeypatch):
    # aislar el registro global para no contaminar otros tests del modulo
    monkeypatch.setattr(SC, "_ORACLE_RECOGNIZERS", list(SC._ORACLE_RECOGNIZERS))

    def _mi_reconocedor(action, result_head):
        return action == "mi_tool_custom" and "MI-OK" in result_head

    SC.register_oracle_recognizer(_mi_reconocedor)
    trace = [{"action": "mi_tool_custom", "ok": True, "args": "x",
              "result_head": "MI-OK: paso"}]
    assert SC.hard_oracle_evidence(trace) != ""


def test_registro_mantiene_el_original_primero():
    assert SC._ORACLE_RECOGNIZERS[0] is SC._recognize_pytest_verde


# ── integracion: maybe_capture_skill via los formatos nuevos ───────────

def test_maybe_capture_skill_via_bon(monkeypatch, tmp_path):
    from cognia.agent import skills
    monkeypatch.setattr(skills, "AUTO_SKILL_DIR", tmp_path / "cs")
    monkeypatch.setattr(skills, "SKILL_DIRS", [tmp_path / "cs"])
    trace = [
        {"action": "leer_archivo", "ok": True, "args": "m.py", "result_head": "..."},
        {"action": "escribir_archivo", "ok": True, "args": "m.py | code", "result_head": "OK"},
        {"action": "py_validar", "ok": True, "args": "m.py", "result_head": "OK"},
        {"action": "generar_codigo", "ok": True, "args": "doble.py | doble(n)",
         "result_head": ("RESULTADO generar_codigo doble.py: OK (mejor de 5 "
                         "candidatos unicos, rank=tests, tests visibles 4/4, "
                         "120 chars)")},
    ]
    res = SC.maybe_capture_skill("implementar funcion doble con BoN", trace)
    assert res["captured"], res
    assert (tmp_path / "cs" / f"{res['name']}.md").exists()
