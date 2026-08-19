# -*- coding: utf-8 -*-
"""Tests de cognia/hermes/parada_verificada.py (parada verificada al cerrar).

Unitarios y HERMETICOS: ni modelo ni red ni pytest anidado. El ledger se redirige con
COGNIA_EVIDENCIA_VERIFICACION a un tmp_path, asi la suite nunca escribe en ~/.cognia.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from cognia.hermes import parada_verificada as PV


@pytest.fixture(autouse=True)
def _ledger_aislado(tmp_path, monkeypatch):
    """Cada test corre con su propio ledger y con la compuerta en modo auto."""
    monkeypatch.setenv("COGNIA_EVIDENCIA_VERIFICACION",
                       str(tmp_path / "evidencia_verificacion.json"))
    monkeypatch.delenv("COGNIA_VERIFICAR_AL_CERRAR", raising=False)
    return tmp_path


def _proyecto(tmp_path: Path) -> Path:
    """Un proyecto minimo con pytest declarado: la deteccion tiene algo real que ver."""
    raiz = tmp_path / "proj"
    (raiz / "tests").mkdir(parents=True)
    (raiz / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (raiz / "modulo.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (raiz / "tests" / "test_modulo.py").write_text("def test_f():\n    pass\n", encoding="utf-8")
    return raiz


# -- Filtro de prosa ----------------------------------------------------------

def test_solo_prosa_no_pide_verificacion(tmp_path):
    """Un turno que solo toco README/LICENSE/notas no tiene NADA que verificar."""
    raiz = _proyecto(tmp_path)
    estado = {
        "ficheros_editados": [str(raiz / "README.md"), str(raiz / "LICENSE"),
                              str(raiz / "notas.txt"), str(raiz / "datos.json")],
        "workspace": str(raiz),
        "ts_primera_edicion": time.time(),
    }
    assert PV.decidir(estado) is None
    assert PV.decidir_detallado(estado)["motivo"] == "solo_prosa"


def test_filtro_de_prosa_distingue_json_de_configuracion():
    """package.json SI es codigo (un typo rompe el build); un dataset .json no."""
    assert PV.es_prosa("docs/guia.md") is True
    assert PV.es_prosa("LICENSE") is True
    assert PV.es_prosa("fixtures/datos.json") is True
    assert PV.es_prosa("package.json") is False
    assert PV.es_prosa("cognia/agent/tools.py") is False


def test_sin_ediciones_no_pide_nada():
    d = PV.decidir_detallado({"ficheros_editados": []})
    assert d["nudge"] is None and d["motivo"] == "sin_ediciones"


# -- El caso central: se edito codigo y no hay evidencia ----------------------

def test_pide_verificacion_si_edito_py_sin_evidencia(tmp_path):
    raiz = _proyecto(tmp_path)
    estado = {
        "ficheros_editados": [str(raiz / "modulo.py"), str(raiz / "README.md")],
        "workspace": str(raiz),
        "ts_primera_edicion": time.time(),
        "nudges_usados": 0,
    }
    d = PV.decidir_detallado(estado)
    assert d["nudge"] is not None
    assert d["motivo"] == "falta_verificacion"
    assert d["estado_evidencia"] == "sin_evidencia"
    # El nudge es SINTETICO: el cableado tiene que excluirlo del historial persistido.
    assert d["sintetico"] is True
    # La sugerencia es CONCRETA: nombra pytest y el test asociado al fichero editado.
    assert "pytest" in d["comando_sugerido"]
    assert "test_modulo.py" in d["comando_sugerido"]
    assert d["comando_sugerido"] in d["nudge"]
    # El README quedo fuera de la lista de ficheros a verificar.
    assert "README.md" not in d["nudge"]
    assert PV.decidir(estado) == d["nudge"]


def test_evidencia_rancia_sigue_pidiendo(tmp_path):
    """Evidencia ANTERIOR a la edicion probo el codigo VIEJO (regla stale de Hermes)."""
    raiz = _proyecto(tmp_path)
    PV.registrar_verificacion(str(raiz), "pytest -q", True, "3 passed")
    t_edicion = time.time() + 1.0          # la edicion ocurre DESPUES de la verificacion
    d = PV.decidir_detallado({
        "ficheros_editados": [str(raiz / "modulo.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": t_edicion,
    })
    assert d["estado_evidencia"] == "rancia"
    assert d["nudge"] is not None


def test_evidencia_fallida_sigue_pidiendo(tmp_path):
    raiz = _proyecto(tmp_path)
    t_edicion = time.time()
    PV.registrar_verificacion(str(raiz), "pytest -q", False, "1 failed, 2 passed")
    d = PV.decidir_detallado({
        "ficheros_editados": [str(raiz / "modulo.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": t_edicion,
    })
    assert d["estado_evidencia"] == "fallida"
    assert d["nudge"] is not None
    assert "1 failed" in d["nudge"]        # la salida real viaja en el nudge


def test_no_pide_si_hay_evidencia_fresca(tmp_path):
    raiz = _proyecto(tmp_path)
    t_edicion = time.time()
    PV.registrar_verificacion(str(raiz), "pytest -q tests/test_modulo.py", True, "3 passed")
    estado = {
        "ficheros_editados": [str(raiz / "modulo.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": t_edicion,
    }
    assert PV.decidir(estado) is None
    assert PV.decidir_detallado(estado)["motivo"] == "evidencia_fresca"


def test_evidencia_de_otro_workspace_no_sirve(tmp_path):
    """La evidencia es POR workspace: verificar otro repo no habilita cerrar este."""
    raiz = _proyecto(tmp_path)
    otro = tmp_path / "otro"
    otro.mkdir()
    t_edicion = time.time()
    PV.registrar_verificacion(str(otro), "pytest -q", True, "9 passed")
    d = PV.decidir_detallado({
        "ficheros_editados": [str(raiz / "modulo.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": t_edicion,
    })
    assert d["estado_evidencia"] == "sin_evidencia"
    assert d["nudge"] is not None


# -- Tope de nudges -----------------------------------------------------------

def test_corta_a_los_dos_nudges(tmp_path):
    """MAX_NUDGES=2: al tercer intento la compuerta deja salir aunque falte evidencia."""
    raiz = _proyecto(tmp_path)
    base = {
        "ficheros_editados": [str(raiz / "modulo.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": time.time(),
    }
    assert PV.MAX_NUDGES == 2
    assert PV.decidir(dict(base, nudges_usados=0)) is not None
    assert PV.decidir(dict(base, nudges_usados=1)) is not None
    assert PV.decidir(dict(base, nudges_usados=2)) is None
    assert PV.decidir_detallado(dict(base, nudges_usados=2))["motivo"] == "tope_nudges"
    assert PV.decidir(dict(base, nudges_usados=7)) is None


# -- Superficie ---------------------------------------------------------------

def test_superficie_de_mensajeria_apaga_la_compuerta(tmp_path, monkeypatch):
    raiz = _proyecto(tmp_path)
    base = {
        "ficheros_editados": [str(raiz / "modulo.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": time.time(),
    }
    assert PV.decidir(dict(base, superficie="cli")) is not None
    assert PV.decidir(dict(base, superficie="telegram")) is None
    assert PV.decidir_detallado(dict(base, superficie="discord"))["motivo"] == "superficie_silenciosa"
    # La env var manda sobre la superficie (misma precedencia que Hermes).
    monkeypatch.setenv("COGNIA_VERIFICAR_AL_CERRAR", "1")
    assert PV.decidir(dict(base, superficie="telegram")) is not None
    monkeypatch.setenv("COGNIA_VERIFICAR_AL_CERRAR", "0")
    assert PV.decidir(dict(base, superficie="cli")) is None


# -- Persistencia del ledger --------------------------------------------------

def test_el_ledger_sobrevive_a_un_reinicio(tmp_path, monkeypatch):
    """Escribir, "reiniciar" el proceso (recargar el modulo) y seguir leyendo lo mismo."""
    import importlib

    fichero = tmp_path / "ledger" / "evidencia_verificacion.json"
    monkeypatch.setenv("COGNIA_EVIDENCIA_VERIFICACION", str(fichero))
    raiz = _proyecto(tmp_path)

    t0 = time.time()
    PV.registrar_verificacion(str(raiz), "pytest -q tests/test_modulo.py", True, "3 passed")
    ev = PV.registrar_verificacion(str(raiz), "ruff check .", True, "All checks passed")
    assert ev["guardado"] is True
    assert fichero.is_file()

    # El fichero es JSON legible por cualquiera, no un formato opaco.
    dato = json.loads(fichero.read_text(encoding="utf-8"))
    assert dato["version"] == 1 and len(dato["eventos"]) == 2

    # "Reinicio": otro import del modulo, sin estado en RAM.
    fresco = importlib.reload(PV)
    est = fresco.estado_verificacion(str(raiz), desde_ts=t0)
    assert est["estado"] == "fresca"
    assert est["comando"] == "ruff check ."
    assert fresco.decidir({
        "ficheros_editados": [str(raiz / "modulo.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": t0,
    }) is None


def test_estado_verificacion_sin_evidencia(tmp_path):
    est = PV.estado_verificacion(str(tmp_path / "nada"), desde_ts=time.time())
    assert est["estado"] == "sin_evidencia" and est["evento"] is None


def test_ledger_corrupto_no_lanza(tmp_path, monkeypatch):
    """Un JSON roto degrada a "sin evidencia" (un nudge de mas), nunca revienta el turno."""
    fichero = tmp_path / "roto.json"
    fichero.write_text("{ esto no es json", encoding="utf-8")
    monkeypatch.setenv("COGNIA_EVIDENCIA_VERIFICACION", str(fichero))
    assert PV.estado_verificacion(str(tmp_path), desde_ts=0.0)["estado"] == "sin_evidencia"
    ev = PV.registrar_verificacion(str(tmp_path), "pytest", True, "1 passed")
    assert ev["guardado"] is True
    assert PV.estado_verificacion(str(tmp_path), desde_ts=0.0)["estado"] == "fresca"


# -- Evidencia inyectada por el caller ----------------------------------------

def test_evidencia_explicita_evita_el_disco(tmp_path, monkeypatch):
    """Si el caller ya calculo la evidencia, se usa esa (ni se mira el ledger)."""
    raiz = _proyecto(tmp_path)
    monkeypatch.setattr(PV, "estado_verificacion",
                        lambda *a, **k: pytest.fail("no debio consultar el ledger"))
    base = {"ficheros_editados": [str(raiz / "modulo.py")], "workspace": str(raiz),
            "ts_primera_edicion": 100.0}
    assert PV.decidir(dict(base, evidencia={"estado": "fresca"})) is None
    assert PV.decidir(dict(base, evidencia={"estado": "sin_evidencia"})) is not None
    # Tambien acepta la lista cruda de eventos.
    assert PV.decidir(dict(base, evidencia=[{"ts": 200.0, "exito": True, "comando": "pytest"}])) is None
    assert PV.decidir(dict(base, evidencia=[{"ts": 50.0, "exito": True, "comando": "pytest"}])) is not None


def test_comandos_verificacion_explicitos_ganan(tmp_path):
    raiz = _proyecto(tmp_path)
    d = PV.decidir_detallado({
        "ficheros_editados": [str(raiz / "modulo.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": time.time(),
        "comandos_verificacion": ["make verificar-todo"],
    })
    assert d["comando_sugerido"] == "make verificar-todo"
    assert "make verificar-todo" in d["nudge"]


# -- Deteccion del comando canonico -------------------------------------------

def test_comandos_canonicos_detecta_pytest_y_el_interprete(tmp_path):
    raiz = _proyecto(tmp_path)
    assert PV.comandos_canonicos(raiz) == ["python -m pytest"]
    # Con un venv en la raiz, la sugerencia nombra el interprete del proyecto.
    venv = raiz / "venv312" / "Scripts"
    venv.mkdir(parents=True)
    (venv / "python.exe").write_text("", encoding="utf-8")
    assert PV.comandos_canonicos(raiz) == ["venv312/Scripts/python.exe -m pytest"]


def test_comandos_canonicos_detecta_package_json_y_makefile(tmp_path):
    raiz = tmp_path / "js"
    raiz.mkdir()
    (raiz / "package.json").write_text(json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}),
                                       encoding="utf-8")
    (raiz / "Makefile").write_text("test:\n\techo hola\n", encoding="utf-8")
    cmds = PV.comandos_canonicos(raiz)
    assert "npm run test" in cmds and "npm run lint" in cmds and "make test" in cmds


def test_sin_test_asociado_pide_ESCRIBIRLO_y_no_la_suite_entera(tmp_path):
    """El eyeball sobre el repo real: sin test que cubra el .py, `pytest` pelado = 612
    ficheros de suite, o sea "verifica tu trabajo" con otro nombre. Se nombra el test que
    FALTA."""
    raiz = _proyecto(tmp_path)
    (raiz / "nuevo.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    d = PV.decidir_detallado({
        "ficheros_editados": [str(raiz / "nuevo.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": time.time(),
    })
    assert d["tests_a_crear"] == ["tests/test_nuevo.py"]
    assert d["comando_sugerido"].endswith("tests/test_nuevo.py -q")
    assert "NO existe ningun test" in d["nudge"]
    # y jamas el comando pelado (la suite entera)
    assert d["comando_sugerido"] != "python -m pytest"


def test_con_test_asociado_el_comando_es_dirigido(tmp_path):
    raiz = _proyecto(tmp_path)
    plan = PV.plan_verificacion([str(raiz / "modulo.py")], raiz)
    assert plan["tests_existentes"] == ["tests/test_modulo.py"]
    assert plan["tests_a_crear"] == []
    assert plan["comando"] == "python -m pytest tests/test_modulo.py -q"


def test_sin_comando_canonico_el_nudge_manda_verificacion_ad_hoc(tmp_path):
    raiz = tmp_path / "pelado"
    raiz.mkdir()
    (raiz / "cosa.py").write_text("x = 1\n", encoding="utf-8")
    d = PV.decidir_detallado({
        "ficheros_editados": [str(raiz / "cosa.py")],
        "workspace": str(raiz),
        "ts_primera_edicion": time.time(),
    })
    assert d["comando_sugerido"] == ""
    assert d["nudge"] is not None
    assert "ad-hoc" in d["nudge"]


# -- Rescate de la respuesta pendiente ----------------------------------------

def test_rescata_la_respuesta_si_el_presupuesto_se_agota_tras_el_nudge():
    r = PV.rescatar_respuesta_pendiente("La funcion ya esta lista.",
                                        respuesta_final=None,
                                        presupuesto_agotado=True,
                                        motivo_salida="desconocido")
    assert r["rescatada"] is True
    assert r["respuesta"] == "La funcion ya esta lista."


def test_no_rescata_si_hay_respuesta_nueva_o_falta_presupuesto_agotado():
    nueva = PV.rescatar_respuesta_pendiente("vieja", respuesta_final="nueva",
                                            presupuesto_agotado=True)
    assert nueva["rescatada"] is False and nueva["respuesta"] == "nueva"

    con_saldo = PV.rescatar_respuesta_pendiente("vieja", presupuesto_agotado=False)
    assert con_saldo["rescatada"] is False and con_saldo["respuesta"] is None


def test_no_rescata_en_salida_por_error_o_interrupcion():
    """La guarda de procedencia: un turno interrumpido o fallido NUNCA entra al rescate."""
    for kw in ({"interrumpido": True}, {"fallido": True}):
        r = PV.rescatar_respuesta_pendiente("vieja", presupuesto_agotado=True, **kw)
        assert r["rescatada"] is False and r["motivo"] == "salida_por_error"
    ajeno = PV.rescatar_respuesta_pendiente("vieja", presupuesto_agotado=True,
                                            motivo_salida="usuario_corto")
    assert ajeno["rescatada"] is False and ajeno["motivo"].startswith("motivo_ajeno")


def test_no_rescata_lo_vacio():
    r = PV.rescatar_respuesta_pendiente("   ", presupuesto_agotado=True)
    assert r["rescatada"] is False and r["motivo"] == "sin_pendiente"


# -- Ayudas del cableado ------------------------------------------------------

def test_ficheros_editados_de_traza():
    traza = [
        {"action": "leer_archivo", "args": "cognia/x.py", "ok": True},
        {"action": "escribir_archivo", "args": "cognia/x.py | print(1)", "ok": True},
        {"action": "editar_archivo", "args": "cognia/y.py | <<<<<<< SEARCH", "ok": True},
        {"action": "escribir_archivo", "args": "cognia/z.py | roto", "ok": False},
        {"action": "escribir_archivo", "args": "cognia/x.py | print(2)", "ok": True},
        "basura",
    ]
    assert PV.ficheros_editados_de_traza(traza) == ["cognia/x.py", "cognia/y.py"]
    assert PV.ficheros_editados_de_traza(None) == []


def test_es_comando_de_verificacion_y_veredicto_de_salida():
    assert PV.es_comando_de_verificacion("venv312/Scripts/python.exe -m pytest tests/ -q")
    assert PV.es_comando_de_verificacion("npm test")
    assert not PV.es_comando_de_verificacion("git status")
    assert PV.exito_de_verificacion("== 12 passed in 1.2s ==") is True
    assert PV.exito_de_verificacion("1 failed, 40 passed") is False
    assert PV.exito_de_verificacion("Traceback (most recent call last):") is False
    # Sin marca de exito el default es False: ausencia de examen no es aprobado.
    assert PV.exito_de_verificacion("") is False


def test_decidir_no_lanza_con_basura():
    """Camino caliente: la compuerta jamas rompe el turno, pase lo que pase."""
    for entrada in (None, "", 42, [], {"ficheros_editados": None},
                    {"ficheros_editados": ["x.py"], "nudges_usados": "dos"}):
        assert PV.decidir_detallado(entrada).get("nudge") in (None, PV.decidir(entrada))
