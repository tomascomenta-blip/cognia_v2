"""
Regresión de las trayectorias EXPERTAS de tool-use (cognia_v3/training/tooluse/gen_expert.py).

Cada secuencia scripted en tasks.py:EXPERT_STEPS debe, al EJECUTARSE contra las
tools reales del deploy, dejar el workspace en un estado que pase la postcondición
(task['verify']) de esa tarea. Si alguien rompe una secuencia, un verificador, o el
formato de una tool, estos tests fallan antes de que el dato malo llegue al fine-tune.

También verifica que ningún par SFT filtre rutas absolutas de la máquina que genera
(sys.executable / venv), que fue un bug real: py_write_run guardaba la ruta del
python del venv en el completion (2026-07-01).
"""
import json
import sys

import pytest

from cognia_v3.training.tooluse.gen_expert import run_expert, build_tools_doc_full
from cognia_v3.training.tooluse.tasks import (
    EXPERT_STEPS, TASKS, expert_tasks, by_id,
)

TOOLS_DOC = build_tools_doc_full()


def test_expert_steps_reference_real_tasks():
    """Toda clave de EXPERT_STEPS debe corresponder a una tarea de TASKS."""
    ids = {t["id"] for t in TASKS}
    missing = [k for k in EXPERT_STEPS if k not in ids]
    assert not missing, f"EXPERT_STEPS con ids inexistentes: {missing}"


def test_expert_tasks_nonempty():
    assert expert_tasks(), "expert_tasks() no debe estar vacío"


@pytest.mark.parametrize("task", expert_tasks(), ids=lambda t: t["id"])
def test_expert_trajectory_passes_verify(task):
    r = run_expert(task, TOOLS_DOC)
    assert r["ok"], f"la trayectoria experta de {task['id']} NO pasa su verify"
    assert r["pairs"], f"{task['id']} no produjo pares"
    # Cierre limpio: el último paso enseña a PARAR con 'responder'.
    assert r["pairs"][-1]["tool"] == "responder"
    # Formato del deploy: toda completion arranca con la línea ACCION.
    for p in r["pairs"]:
        assert p["completion"].startswith("ACCION: "), p["completion"][:60]


@pytest.mark.parametrize("task", expert_tasks(), ids=lambda t: t["id"])
def test_expert_no_abs_path_leak(task):
    r = run_expert(task, TOOLS_DOC)
    blob = json.dumps(r["pairs"], ensure_ascii=False)
    for leak in (sys.executable, "venv312", "python.exe"):
        assert leak not in blob, f"{task['id']} filtra ruta absoluta: {leak!r}"


def test_kg_expert_is_isolated():
    """La tarea de KG debe agregar y recuperar el hecho SIN tocar la DB del usuario
    (usa un KnowledgeGraph sobre DB temporal). El transcript de kg_buscar prueba que
    el hecho quedó en el grafo aislado."""
    task = by_id("kg_agregar_buscar")
    r = run_expert(task, TOOLS_DOC)
    assert r["ok"]
    tools = [p["tool"] for p in r["pairs"]]
    assert "kg_agregar" in tools and "kg_buscar" in tools
