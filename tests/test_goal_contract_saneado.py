"""
Tests del saneo harmony en derive_criteria_from_task (goal_contract.py).

Causa raiz A6 (obra 2026-08-09): la letra de la tarea contaminada con tokens
de canal harmony (<|channel|>..., <|end|>) o bloques <think> hacia derivar
criterios basura. El saneo corre SIEMPRE (sin flag); estos tests fijan que
(a) los tokens no derivan criterios y (b) una tarea limpia produce LOS MISMOS
criterios que antes del fix (no-regresion).
"""

from cognia.agents.goal_contract import derive_criteria_from_task


def test_tokens_harmony_no_derivan_criterios():
    contaminada = "<|channel|>analysis crear x.py<|end|><|start|>assistant"
    specs = derive_criteria_from_task(contaminada)
    # El unico criterio legitimo es x.py; nada con '<' o '|' en la ruta.
    assert all("|" not in s.get("path", "") and "<" not in s.get("path", "")
               for s in specs)
    paths = [s.get("path") for s in specs if s["kind"] == "file_exists"]
    assert paths == ["x.py"]


def test_bloques_think_se_limpian():
    specs = derive_criteria_from_task("<think>quiza tests</think> crea hola.py")
    assert [s.get("path") for s in specs] == ["hola.py"]
    # 'tests' vivia solo dentro del <think>: no debe armar pytest.
    assert all(s["kind"] == "file_exists" for s in specs)


def test_contenido_del_think_no_deriva_criterios():
    # Repro de la revision 2026-08-09: borrar solo las ETIQUETAS dejaba el
    # veneno adentro — el pytest sobre tests/test_foo.py salia del
    # razonamiento, no de la tarea, y congelado bloqueaba el horizonte.
    specs = derive_criteria_from_task(
        "<think>habria que correr pytest sobre tests/test_foo.py</think> "
        "crea foo.py")
    assert [s.get("path") for s in specs] == ["foo.py"]
    assert all(s["kind"] == "file_exists" for s in specs)


def test_think_huerfano_se_limpia_como_etiqueta():
    # Bloque truncado (sin cierre): las etiquetas sueltas se limpian y el
    # contenido queda — mejor derivar de mas que perder la letra entera.
    specs = derive_criteria_from_task("</think> crea solo.py")
    assert [s.get("path") for s in specs] == ["solo.py"]


def test_tarea_limpia_no_regresion():
    tarea = "crea datos.csv y analiza.py con tests en tests/test_analiza.py"
    specs = derive_criteria_from_task(tarea)
    kinds = {s.get("path", s.get("command", "")): s["kind"] for s in specs}
    assert kinds["datos.csv"] == "file_exists"
    assert kinds["analiza.py"] == "file_exists"
    assert any(s["kind"] == "command_succeeds"
               and "tests/test_analiza.py" in s["command"] for s in specs)


def test_task_none_o_vacia_degrada_a_lista_vacia():
    assert derive_criteria_from_task("") == []
    assert derive_criteria_from_task(None) == []
