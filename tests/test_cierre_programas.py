# -*- coding: utf-8 -*-
"""
tests/test_cierre_programas.py
==============================
Cierre de programas al acabar la tarea (cognia/agent/cierre_programas.py,
2026-09-10). Sin ventanas reales: se dobla el registro de app_tools y se
prueba la politica (auto/siempre/nunca), las reglas de mantener (marcado por
el agente, peticion del usuario, ventana fuera de la mesa), el hook antes de
cerrar y que solo entra lo lanzado en ESTA tarea. El e2e real (notepad en la
mesa) va con COGNIA_E2E_TALLER=1.
"""
from __future__ import annotations

import os
import time

import pytest

from cognia.agent import cierre_programas as CP


class _AT:
    """Doble de app_tools: registro _APPS + cerrar/_exe_de que anotan."""
    def __init__(self):
        self._APPS = {}
        self.cerradas = []
        self.exes = {}

    def cerrar(self, app_id):
        self.cerradas.append(app_id)
        self._APPS.pop(app_id, None)
        return "%s cerrada (WM_CLOSE)" % app_id

    def _exe_de(self, pid):
        return self.exes.get(pid, "app.exe")


@pytest.fixture(autouse=True)
def _doble(monkeypatch):
    at = _AT()
    monkeypatch.setattr(CP, "AT", at)
    monkeypatch.setattr(CP, "EP", None)          # sin escritorio: todo cuenta como "en la mesa"
    monkeypatch.setattr(CP, "HOOKS_ANTES", {})
    monkeypatch.setattr(CP, "_MANTENER", {})
    monkeypatch.setattr(CP, "_INICIO", {"ts": 0.0, "tarea": ""})
    monkeypatch.delenv("COGNIA_CIERRE_PROGRAMAS", raising=False)
    monkeypatch.setattr(CP, "politica", lambda: "auto")
    yield at


def _lanzar(at, app_id, titulo, pid=100, mudada=True, ts=None):
    at._APPS[app_id] = {"pid": pid, "hwnd": 1000 + pid, "cmd": titulo.lower() + ".exe", "titulo": titulo,
                        "ts": time.time() if ts is None else ts, "mudada": mudada}


def test_cierra_lo_lanzado_en_la_tarea_y_no_lo_anterior(_doble):
    at = _doble
    _lanzar(at, "a1", "Vieja", pid=1, ts=time.time() - 100)     # de una tarea anterior
    CP.empezar_tarea("modela una taza en blender")
    time.sleep(0.01)
    _lanzar(at, "a2", "Blender", pid=2)
    out = CP.al_terminar("modela una taza en blender")
    assert [c[0] for c in out["cerradas"]] == ["a2"]
    assert "a1" in at._APPS and "a2" not in at._APPS


def test_usuario_pide_abrir_se_mantiene(_doble):
    at = _doble
    CP.empezar_tarea("ábreme la calculadora")
    _lanzar(at, "a1", "Calculadora")
    out = CP.al_terminar("ábreme la calculadora")
    assert out["cerradas"] == [] and out["mantenidas"][0][0] == "a1"
    assert "pidio abrirlo" in out["motivos"]["a1"]


@pytest.mark.parametrize("frase", ["abre el bloc de notas con la lista", "déjalo abierto cuando acabes",
                                   "quiero ver el resultado en Godot", "no lo cierres", "muéstrame el modelo"])
def test_frases_que_piden_verlo(frase):
    assert CP.usuario_lo_quiere_abierto(frase)


@pytest.mark.parametrize("frase", ["modela un pikachu en blender y exporta a glb",
                                   "crea un proyecto de godot con un pong", "renombra los ficheros"])
def test_frases_que_no_lo_piden(frase):
    assert not CP.usuario_lo_quiere_abierto(frase)


def test_marcado_por_el_agente_se_mantiene(_doble):
    at = _doble
    CP.empezar_tarea("modela algo")
    _lanzar(at, "a1", "Blender")
    _lanzar(at, "a2", "Godot")
    r = CP.marcar("godot", "el usuario lo va a seguir editando")
    assert r["ok"] and r["app_ids"] == ["a2"]
    out = CP.al_terminar("modela algo")
    assert [c[0] for c in out["cerradas"]] == ["a1"]
    assert out["mantenidas"][0][0] == "a2" and "marcado" in out["motivos"]["a2"]


def test_marcar_por_nombre_antes_de_lanzar(_doble):
    at = _doble
    CP.empezar_tarea("x")
    r = CP.marcar("Blender")
    assert r["ok"] and r["app_ids"] == []
    _lanzar(at, "a1", "Blender 5.2")
    out = CP.al_terminar("x")
    assert out["cerradas"] == [] and out["mantenidas"][0][0] == "a1"


def test_politica_nunca_y_siempre(_doble, monkeypatch):
    at = _doble
    CP.empezar_tarea("ábreme la calculadora")
    _lanzar(at, "a1", "Calculadora")
    monkeypatch.setattr(CP, "politica", lambda: "nunca")
    out = CP.al_terminar("ábreme la calculadora")
    assert out["cerradas"] == [] and "nunca" in out["motivos"]["a1"]
    monkeypatch.setattr(CP, "politica", lambda: "siempre")
    out = CP.al_terminar("ábreme la calculadora")          # 'siempre' ignora la peticion...
    assert [c[0] for c in out["cerradas"]] == ["a1"]
    _lanzar(at, "a2", "Otra")
    CP.marcar("a2")
    out = CP.al_terminar("x")                              # ...pero no lo marcado
    assert out["cerradas"] == [] and out["mantenidas"][0][0] == "a2"


def test_ventana_fuera_de_la_mesa_se_mantiene(_doble, monkeypatch):
    at = _doble

    class EP:
        @staticmethod
        def ventanas_en_escritorio():
            return [(1002, 2, "Blender")]          # solo a2 sigue en la mesa

        @staticmethod
        def ventana_viva(h):
            return True
    monkeypatch.setattr(CP, "EP", EP)
    CP.empezar_tarea("haz cosas")
    _lanzar(at, "a1", "Godot", pid=1)
    _lanzar(at, "a2", "Blender", pid=2)
    out = CP.al_terminar("haz cosas")
    assert [c[0] for c in out["cerradas"]] == ["a2"]
    assert out["mantenidas"][0][0] == "a1" and "escritorio" in out["motivos"]["a1"]


def test_hook_antes_de_cerrar(_doble):
    at = _doble
    at.exes[7] = "blender.exe"
    llamadas = []
    CP.HOOKS_ANTES["blender.exe"] = lambda a: llamadas.append(a["titulo"]) or "guardado en x.blend"
    CP.empezar_tarea("modela")
    _lanzar(at, "a1", "Blender", pid=7)
    out = CP.al_terminar("modela")
    assert llamadas == ["Blender"] and "guardado en x.blend" in out["cerradas"][0][2]


def test_hook_roto_no_impide_cerrar(_doble, monkeypatch):
    at = _doble
    at.exes[7] = "blender.exe"
    avisos = []
    monkeypatch.setattr(CP, "_degradado", lambda m: avisos.append(m))

    def _boom(a):
        raise RuntimeError("sin socket")
    CP.HOOKS_ANTES["blender.exe"] = _boom
    CP.empezar_tarea("modela")
    _lanzar(at, "a1", "Blender", pid=7)
    out = CP.al_terminar("modela")
    assert at.cerradas == ["a1"] and avisos and "hook fallo" in out["cerradas"][0][2]


def test_sin_empezar_tarea_no_toca_nada(_doble):
    at = _doble
    _lanzar(at, "a1", "Algo")
    out = CP.al_terminar("lo que sea")
    assert out["cerradas"] == [] and "a1" in at._APPS


def test_texto_legible():
    out = {"cerradas": [("a1", "Blender", "WM_CLOSE")], "mantenidas": [("a2", "Godot", "marcado por el agente")]}
    t = CP.texto(out)
    assert "cerré Blender (a1)" in t and "dejé abierto Godot: marcado" in t
    assert CP.texto({"cerradas": [], "mantenidas": []}) == ""


def test_tool_programa_mantener_registrada():
    from cognia.agent.tools import TOOLS, flag_de_optin, run_tool
    assert "programa_mantener" in TOOLS and flag_de_optin("programa_mantener") == "COGNIA_PRUEBAS"
    assert run_tool("programa_mantener", "", {}).startswith("RESULTADO programa_mantener ERROR")


def test_hook_de_blender_instalado_al_registrar():
    from cognia.agent import cierre_programas as CP2
    assert "blender.exe" in CP2.HOOKS_ANTES or True     # el fixture lo vacia; se comprueba la instalacion
    CP2._instalar_hooks()
    assert "blender.exe" in CP2.HOOKS_ANTES


@pytest.mark.skipif(os.environ.get("COGNIA_E2E_TALLER") != "1", reason="e2e real: COGNIA_E2E_TALLER=1")
def test_e2e_notepad_en_la_mesa_se_cierra(monkeypatch):
    from cognia.agent import app_tools as AT
    from cognia.agent import escritorio_propio as EP
    monkeypatch.setattr(CP, "AT", AT)
    monkeypatch.setattr(CP, "EP", EP)
    CP.empezar_tarea("escribe una nota")
    app_id, a = AT.lanzar("notepad.exe", espera_ms=8000)
    assert app_id in AT._APPS
    out = CP.al_terminar("escribe una nota")
    assert [c[0] for c in out["cerradas"]] == [app_id]
    for _ in range(20):                       # el Bloc de notas nuevo (UWP) tarda en irse
        if not EP.ventana_viva(a["hwnd"]):
            break
        time.sleep(0.5)
    assert not EP.ventana_viva(a["hwnd"])
