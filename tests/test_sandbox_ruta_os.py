"""
test_sandbox_ruta_os.py — Seleccion de ruta de contencion en run_in_sandbox.

Desde 2026-08-01 run_in_sandbox prefiere la contencion DURA (os_sandbox,
Windows AppContainer) cuando esta disponible, y cae al guard in-process solo
como fallback. Antes run_in_appcontainer era una huerfana: el aislamiento real
existia (WS_WRITE=OK, REPO_WRITE=BLOCKED, NET=BLOCKED, medido en el spike
G0-SO) pero NINGUN llamador de produccion lo usaba — todo el codigo generado
corria detras del guard que el equipo rojo rompio con 11 escapes.

Aqui se prueba la LOGICA de seleccion con os_sandbox mockeado (sin crear
perfiles de AppContainer reales; eso lo cubre test_os_sandbox.py):
  - disponible  -> se ejecuta via run_in_appcontainer y NO se toca el guard
  - no disponible / excepcion / exit -4 (ni arranco) -> fallback al guard
  - COGNIA_SANDBOX_GUARD=1 -> guard forzado sin consultar os_sandbox
  - el scan AST corta ANTES de elegir ruta (defensa en profundidad comun)
  - "tests en rojo" degrada el exito tambien en la ruta AppContainer
"""

import pytest

from cognia.program_creator import os_sandbox
from cognia.program_creator.sandbox_runner import ExecutionResult, run_in_sandbox


def _resultado_container(**kw):
    base = dict(success=True, execution_output="DESDE_APPCONTAINER",
                execution_errors="", exit_code=0, timed_out=False)
    base.update(kw)
    return ExecutionResult(**base)


@pytest.fixture(autouse=True)
def _sin_guard_forzado(monkeypatch):
    # El env del proceso de tests puede traer el opt-out puesto (otros tests lo
    # usan): aqui se limpia para medir la seleccion real.
    monkeypatch.delenv("COGNIA_SANDBOX_GUARD", raising=False)


class TestSeleccionDeRuta:
    def test_disponible_usa_appcontainer_y_no_el_guard(self, monkeypatch):
        llamadas = {}

        def _falso_container(code, extra_files=None, timeout_sec=15):
            llamadas["code"] = code
            return _resultado_container()

        monkeypatch.setattr(os_sandbox, "is_available", lambda: True)
        monkeypatch.setattr(os_sandbox, "run_in_appcontainer", _falso_container)
        # Si el guard llegara a ejecutarse, subprocess.run explotaria aqui.
        import cognia.program_creator.sandbox_runner as sr
        monkeypatch.setattr(sr.subprocess, "run",
                            lambda *a, **k: pytest.fail("el guard NO debia correr"))

        r = run_in_sandbox("print('hola')")
        assert r.execution_output == "DESDE_APPCONTAINER"
        assert r.success is True
        assert llamadas["code"] == "print('hola')"

    def test_no_disponible_cae_al_guard(self, monkeypatch):
        monkeypatch.setattr(os_sandbox, "is_available", lambda: False)
        monkeypatch.setattr(
            os_sandbox, "run_in_appcontainer",
            lambda *a, **k: pytest.fail("no debia llamarse sin disponibilidad"))
        r = run_in_sandbox("print('GUARD_OK')")
        assert r.success is True, r.execution_errors
        assert "GUARD_OK" in r.execution_output

    def test_excepcion_del_container_cae_al_guard(self, monkeypatch):
        monkeypatch.setattr(os_sandbox, "is_available", lambda: True)

        def _explota(*a, **k):
            raise os_sandbox.OsSandboxError("perfil roto")

        monkeypatch.setattr(os_sandbox, "run_in_appcontainer", _explota)
        r = run_in_sandbox("print('GUARD_OK')")
        assert r.success is True, r.execution_errors
        assert "GUARD_OK" in r.execution_output

    def test_exit_menos4_ni_arranco_cae_al_guard(self, monkeypatch):
        # -4 = CreateProcess fallo: el programa no llego a correr, el fallback
        # no puede repetir efectos a medias.
        monkeypatch.setattr(os_sandbox, "is_available", lambda: True)
        monkeypatch.setattr(
            os_sandbox, "run_in_appcontainer",
            lambda *a, **k: _resultado_container(
                success=False, execution_output="",
                execution_errors="[appcontainer] CreateProcess fallo",
                exit_code=-4))
        r = run_in_sandbox("print('GUARD_OK')")
        assert r.success is True, r.execution_errors
        assert "GUARD_OK" in r.execution_output

    def test_opt_out_por_env_fuerza_el_guard(self, monkeypatch):
        monkeypatch.setenv("COGNIA_SANDBOX_GUARD", "1")
        monkeypatch.setattr(
            os_sandbox, "is_available",
            lambda: pytest.fail("con el opt-out ni se consulta os_sandbox"))
        r = run_in_sandbox("print('GUARD_OK')")
        assert r.success is True, r.execution_errors
        assert "GUARD_OK" in r.execution_output


class TestPoliticaComun:
    def test_scan_ast_corta_antes_de_elegir_ruta(self, monkeypatch):
        monkeypatch.setattr(os_sandbox, "is_available", lambda: True)
        monkeypatch.setattr(
            os_sandbox, "run_in_appcontainer",
            lambda *a, **k: pytest.fail("un import prohibido no debe ejecutarse"))
        r = run_in_sandbox("import socket\nprint('OK')")
        assert r.success is False
        assert r.exit_code == -2
        assert "socket" in r.execution_errors

    def test_tests_en_rojo_degradan_tambien_en_appcontainer(self, monkeypatch):
        monkeypatch.setattr(os_sandbox, "is_available", lambda: True)
        monkeypatch.setattr(
            os_sandbox, "run_in_appcontainer",
            lambda *a, **k: _resultado_container(
                execution_output="Ran 0 tests in 0.000s\nOK"))
        r = run_in_sandbox("print('con tests fantasma')")
        assert r.success is False
        assert "Tests en rojo" in r.execution_errors
