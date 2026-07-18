"""
tests/test_tasks_board.py
Tests para cognia/tasks_board.py — tablero de tareas con checkboxes.

Aislamiento: COGNIA_TASKS_FILE apunta a tmp_path (mismo patron que
tests/test_experts_registry.py con COGNIA_EXPERTS_DIR). El render se
prueba con sys.stdout monkeypatcheado para fijar el encoding.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia import tasks_board as tb  # noqa: E402

CHECK_EMPTY = "☐"   # BALLOT BOX
CHECK_DONE = "☑"    # BALLOT BOX WITH CHECK


@pytest.fixture(autouse=True)
def board_tmp(tmp_path, monkeypatch):
    """Aisla el tablero en tmp_path para cada test."""
    monkeypatch.setenv("COGNIA_TASKS_FILE", str(tmp_path / "tasks_board.json"))
    yield tmp_path


@pytest.fixture
def stdout_utf8(monkeypatch):
    """Consola que SI codifica los checkboxes unicode."""
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace(encoding="utf-8"))


class TestStore:
    def test_add_devuelve_id_y_persiste(self, board_tmp):
        tid = tb.add_task("comprar cafe")
        assert tid == 1
        assert tb.tasks_file().is_file()
        raw = json.loads(tb.tasks_file().read_text(encoding="utf-8"))
        assert raw["tasks"][0]["texto"] == "comprar cafe"
        assert raw["tasks"][0]["done"] is False
        assert raw["tasks"][0]["origen"] == "usuario"

    def test_add_complete_round_trip_persistente(self):
        """add + complete: una carga fresca desde disco ve done=True."""
        tid = tb.add_task("escribir tests")
        assert tb.complete_task(tid) is True
        tareas = tb.list_tasks()   # relee disco, sin cache
        assert len(tareas) == 1
        t = tareas[0]
        assert t["done"] is True
        assert t["id"] == tid
        assert t["origen"] == "usuario"
        assert t["created"]  # timestamp presente

    def test_uncomplete_round_trip(self):
        tid = tb.add_task("x")
        tb.complete_task(tid)
        assert tb.uncomplete_task(tid) is True
        assert tb.list_tasks()[0]["done"] is False

    def test_remove(self):
        tid = tb.add_task("borrable")
        assert tb.remove_task(tid) is True
        assert tb.list_tasks() == []

    def test_complete_id_desconocido_devuelve_false(self):
        assert tb.complete_task(999) is False
        assert tb.remove_task(999) is False
        assert tb.uncomplete_task(999) is False

    def test_add_texto_vacio_falla(self):
        with pytest.raises(ValueError, match="texto vacio"):
            tb.add_task("   ")

    def test_add_origen_invalido_falla(self):
        with pytest.raises(ValueError, match="origen invalido"):
            tb.add_task("x", origen="robot")

    def test_json_corrupto_degrada_a_vacio(self):
        tb.tasks_file().parent.mkdir(parents=True, exist_ok=True)
        tb.tasks_file().write_text("{esto no es json", encoding="utf-8")
        assert tb.list_tasks() == []
        # y se puede seguir agregando encima
        assert tb.add_task("recuperada") == 1

    def test_ids_no_se_reusan_tras_borrar(self):
        a = tb.add_task("a")
        tb.remove_task(a)
        b = tb.add_task("b")
        assert b != a
        assert b > a


class TestConcurrencia:
    def test_dos_adds_seguidos_ids_distintos(self):
        """Cada add relee next_id de disco: dos seguidos nunca chocan."""
        a = tb.add_task("primera")
        b = tb.add_task("segunda")
        assert a != b
        ids = [t["id"] for t in tb.list_tasks()]
        assert len(ids) == len(set(ids)) == 2


class TestRender:
    def test_checkbox_vacio_lleno_y_contador(self, stdout_utf8):
        tb.add_task("pendiente uno")
        tid = tb.add_task("ya hecha")
        tb.complete_task(tid)
        out = tb.render_board()
        assert f"{CHECK_EMPTY} #1 pendiente uno" in out
        assert f"{CHECK_DONE} #2 ya hecha" in out
        assert "1/2 completadas" in out

    def test_pendientes_arriba_completadas_abajo(self, stdout_utf8):
        primera = tb.add_task("terminada primero")
        tb.add_task("sigue pendiente")
        tb.complete_task(primera)
        out = tb.render_board()
        # aunque la completada se creo antes, va abajo
        assert out.index("sigue pendiente") < out.index("terminada primero")

    def test_fallback_ascii_cuando_encoding_no_soporta(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout",
                            types.SimpleNamespace(encoding="ascii"))
        tb.add_task("pendiente")
        tid = tb.add_task("hecha")
        tb.complete_task(tid)
        out = tb.render_board()
        assert "[ ] #1 pendiente" in out
        assert "[x] #2 hecha" in out
        assert CHECK_EMPTY not in out and CHECK_DONE not in out

    def test_stdout_sin_encoding_cae_a_ascii(self, monkeypatch):
        """stdout reemplazado (pipe raro) sin .encoding: no explota."""
        monkeypatch.setattr(sys, "stdout", types.SimpleNamespace())
        tb.add_task("x")
        assert "[ ]" in tb.render_board()

    def test_tablero_vacio(self):
        assert "No hay tareas" in tb.render_board()

    def test_render_lista_explicita_no_toca_disco(self, stdout_utf8):
        out = tb.render_board([{"id": 7, "texto": "inyectada", "done": False,
                                "origen": "usuario"}])
        assert "#7 inyectada" in out
        assert "0/1 completadas" in out
        assert not tb.tasks_file().exists()


class TestAgentAPI:
    def test_agent_plan_tasks_crea_n_como_agente(self, stdout_utf8):
        ids = tb.agent_plan_tasks(["leer archivo", "editar", "", "verificar"])
        assert len(ids) == 3            # el paso en blanco se salta
        assert len(set(ids)) == 3
        tareas = tb.list_tasks()
        assert all(t["origen"] == "agente" for t in tareas)
        assert all(t["done"] is False for t in tareas)
        # el tablero los muestra como cuadrados vacios marcados (agente)
        out = tb.render_board()
        assert out.count(CHECK_EMPTY) == 3
        assert "(agente)" in out

    def test_agent_mark_done_llena_el_cuadrado(self, stdout_utf8):
        ids = tb.agent_plan_tasks(["paso 1", "paso 2"])
        assert tb.agent_mark_done(ids[0]) is True
        out = tb.render_board()
        assert f"{CHECK_DONE} #{ids[0]} paso 1" in out
        assert f"{CHECK_EMPTY} #{ids[1]} paso 2" in out
        assert "1/2 completadas" in out

    def test_board_progress_hook_solo_tareas_agente(self, stdout_utf8):
        tb.add_task("tarea humana")
        ids = tb.agent_plan_tasks(["paso agente"])
        tb.agent_mark_done(ids[0])
        out = tb.board_progress_hook()
        assert "paso agente" in out
        assert "tarea humana" not in out
        assert "1/1 completadas" in out

    def test_board_progress_hook_vacio_sin_plan(self):
        tb.add_task("solo humana")
        assert tb.board_progress_hook() == ""
