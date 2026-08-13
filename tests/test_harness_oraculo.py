# -*- coding: utf-8 -*-
"""
Regresion de cognia/harness/oraculo.py (modelo por rol + consulta explicita).

Todo es REAL, nada de mocks. El transporte es el punto de inyeccion del modulo,
asi que se le enchufan transportes de VERDAD:
  - camino feliz: un SUBPROCESO real (sys.executable) que imprime el plan; el
    prompt viaja por argv y vuelve texto por stdout.
  - transporte caido: un urlopen REAL contra un puerto que se acaba de cerrar
    (ConnectionRefused de verdad, no una excepcion inventada).
  - transporte colgado: un time.sleep real contra un timeout chico.
El conteo de llamadas se mide por evidencia observable (un contador que el
propio transporte incrementa), igual que el anti-bucle de test_harness_verificacion.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from cognia.harness.oraculo import (
    MAX_CONSULTAS, MAX_CONTEXTO_CHARS, NOMBRE_TOOL, PARAMS_TOOL, ROLES,
    TIMEOUT_DEF,
    armar_consulta, consultar, elegir_rol, error_exacto, estado, hay_fallo,
    nuevo_registro, reiniciar, spec_tool, texto_resultado,
)

TRACEBACK_REAL = """Traceback (most recent call last):
  File "cognia/indice.py", line 42, in buscar
    return self._tabla[clave]
KeyError: 'ruta'
"""


# ── transportes REALES ──────────────────────────────────────────────────

def _transporte_subproceso(llamadas):
    """Transporte de verdad: lanza un proceso Python que devuelve un plan. La
    lista `llamadas` acumula (rol, timeout, len(prompt)) — la evidencia."""
    def transporte(prompt, rol, timeout):
        llamadas.append((rol, timeout, len(prompt)))
        salida = subprocess.run(
            [sys.executable, "-c",
             "import sys; print('PLAN para', sys.argv[1]); "
             "print('1. medir antes de tocar'); print('2. escribir el test')",
             rol],
            capture_output=True, text=True, timeout=60)
        return salida.stdout
    return transporte


def _puerto_cerrado() -> int:
    """Un puerto que SEGURO no escucha: se abre, se lee el numero y se cierra."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


def _transporte_caido(puerto: int):
    """Transporte que habla HTTP contra un puerto cerrado: URLError REAL."""
    def transporte(prompt, rol, timeout):
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/v1/chat",
                                    timeout=timeout) as r:
            return r.read().decode()
    return transporte


def _transporte_colgado(segundos: float):
    def transporte(prompt, rol, timeout):
        time.sleep(segundos)
        return "tarde pero llegue"
    return transporte


def _transporte_vacio(prompt, rol, timeout):
    """El fallo tipico de este repo: vivo, sin excepcion, y no dice nada."""
    return "   \n  "


# ── tabla de roles ──────────────────────────────────────────────────────

def test_roles_declaran_los_cuatro_y_su_criterio():
    assert set(ROLES) == {"pensar", "codigo", "revisar", "rapido"}
    for rol, spec in ROLES.items():
        for campo in ("para", "criterio", "prefiere", "combo_flota",
                      "rol_summoner", "pide", "max_palabras"):
            assert spec.get(campo), f"{rol} sin {campo}"


# ── elegir_rol: cada regla de la cascada ────────────────────────────────

def test_elegir_rol_evidencia_dura_gana_al_lexico():
    # R1: el traceback lo escribio la maquina; manda sobre "diseno" en la pregunta.
    assert elegir_rol("el diseno del indice no me cierra",
                      contexto=TRACEBACK_REAL) == "codigo"


def test_elegir_rol_lexico_de_error():
    assert elegir_rol("el test de sumar falla y no se por que") == "codigo"
    assert elegir_rol("no compila el modulo") == "codigo"


def test_elegir_rol_diseno_y_revision():
    assert elegir_rol("que arquitectura conviene para el cache?") == "pensar"
    assert elegir_rol("estoy atascado con el enfoque") == "pensar"
    assert elegir_rol("revisa este parche antes de que lo suba") == "revisar"
    assert elegir_rol("esta bien resuelto asi?") == "revisar"


def test_elegir_rol_default_rapido_y_acentos():
    assert elegir_rol("como se llama el flag de pytest para ver stdout") == "rapido"
    # Sin tildes o con tildes es la misma pista lexica.
    assert elegir_rol("cual es el mejor DISEÑO?") == "pensar"


def test_hay_fallo_y_error_exacto():
    assert hay_fallo(TRACEBACK_REAL)
    assert not hay_fallo("todo verde, 12 passed")
    assert error_exacto(TRACEBACK_REAL) == "KeyError: 'ruta'"
    # Se queda con el ULTIMO error, que es el vigente.
    assert error_exacto("ValueError: viejo\nTypeError: nuevo") == "TypeError: nuevo"
    assert error_exacto("no hay nada roto aca") == ""


def test_cero_failed_es_una_tanda_verde():
    """Regresion: '\\d+ failed' pescaba tambien el '0 failed' de un log LIMPIO,
    y entonces cualquier pregunta con un resumen verde pegado caia en 'codigo'."""
    assert not hay_fallo("=== 12 passed, 0 failed in 3.21s ===")
    assert not hay_fallo("0 failed")
    assert hay_fallo("=== 11 passed, 1 failed in 3.21s ===")
    assert hay_fallo("=== 10 failed in 3.21s ===")
    assert elegir_rol("revisa este diseno", "12 passed, 0 failed") == "revisar"


def test_error_exacto_pesca_los_formatos_de_verificacion_py():
    """Los tres formatos que emite de verdad cognia/harness/verificacion.py."""
    assert error_exacto("ERROR: timeout tras 60s corriendo los tests")
    assert error_exacto("ERROR linea 12: falta parentesis")
    # La rama JSON agrega la columna; se escapaba del regex y volvia "".
    assert error_exacto("ERROR linea 12 col 3: Expecting ','") == \
        "ERROR linea 12 col 3: Expecting ','"
    # Y las lineas de pytest.
    assert error_exacto("E       assert 1 == 2") == "E assert 1 == 2"
    assert error_exacto("FAILED tests/test_x.py::test_y - KeyError: 'a'").startswith(
        "FAILED tests/test_x.py")


def test_no_lanza_con_entradas_no_textuales():
    """El contrato es 'NUNCA lanza': un integrador que pasa un no-str no puede
    llevarse el turno del lazo por un TypeError de unicodedata."""
    assert elegir_rol(123) == "rapido"
    assert hay_fallo(None) is False
    assert error_exacto(None) == ""
    assert "PREGUNTA: 123" in armar_consulta(123, contexto=None)
    r = consultar(42, transporte=_transporte_vacio, registro=nuevo_registro())
    assert r["ok"] is False and "VACIA" in r["error"]


# ── armar_consulta ──────────────────────────────────────────────────────

def test_armar_consulta_lleva_intento_error_y_que_devolver():
    prompt = armar_consulta("por que revienta al leer la ruta?",
                            contexto="intente con dict.get y con try/except\n"
                                     + TRACEBACK_REAL,
                            rol="codigo")
    assert "LO QUE YA SE INTENTO:" in prompt
    assert "intente con dict.get" in prompt
    assert "ERROR EXACTO:" in prompt
    assert "KeyError: 'ruta'" in prompt          # extraido y puesto aparte
    assert "QUE TENES QUE DEVOLVER:" in prompt
    assert ROLES["codigo"]["pide"].split("(")[0].strip()[:20] in prompt
    assert "NO devuelvas el fichero entero" in prompt


def test_armar_consulta_sin_contexto_lo_dice():
    prompt = armar_consulta("por donde arranco?", contexto="")
    assert "(nada todavia: es el primer intento)" in prompt
    assert "ERROR EXACTO" not in prompt


def test_armar_consulta_recorta_por_el_medio():
    ctx = "CABEZA-" + ("x" * 20000) + "-COLA KeyError: 'ruta'"
    prompt = armar_consulta("que hago?", contexto=ctx, rol="pensar")
    assert "CABEZA-" in prompt                    # sobrevive el principio
    assert "-COLA KeyError: 'ruta'" in prompt     # y el final (donde esta el error)
    assert "recortado el medio" in prompt
    assert "x" * 5000 not in prompt               # el medio se fue
    assert len(prompt) < MAX_CONTEXTO_CHARS + 2500


def test_armar_consulta_tope_cero_no_manda_el_log_entero():
    """Regresion: `tope <= 0` significaba 'no recortes' y max_contexto=0 mandaba
    los 9000 chars enteros — el reves exacto de lo que pide quien pone 0."""
    ctx = "X" * 9000
    prompt = armar_consulta("que hago?", contexto=ctx, rol="pensar",
                            max_contexto=0)
    assert "X" * 100 not in prompt
    assert len(prompt) < 2000
    # Y no miente diciendo que no se intento nada: dice que se OMITIO.
    assert "contexto omitido" in prompt
    assert "(nada todavia" not in prompt


def test_armar_consulta_rol_invalido_cae_en_la_cascada():
    prompt = armar_consulta("revisa el diseno", contexto="", rol="inexistente")
    assert "rol 'revisar'" in prompt


# ── consultar: camino feliz con un subproceso REAL ──────────────────────

def test_consultar_camino_feliz_transporte_real():
    reg = nuevo_registro()
    llamadas = []
    r = consultar("me conviene indice invertido o fuerza bruta?",
                  contexto="probe fuerza bruta y tarda 8s",
                  transporte=_transporte_subproceso(llamadas),
                  registro=reg, timeout=60)
    assert r["ok"] is True
    assert r["error"] == ""
    assert "PLAN para pensar" in r["respuesta"]
    assert r["rol"] == "pensar"
    assert r["segundos"] >= 0
    assert r["restantes"] == MAX_CONSULTAS - 1
    assert len(llamadas) == 1
    assert llamadas[0][0] == "pensar" and llamadas[0][1] == 60
    assert "RESULTADO consultar_oraculo [rol=pensar" in texto_resultado(r)


def test_consultar_respeta_el_rol_forzado():
    reg = nuevo_registro()
    llamadas = []
    r = consultar("una duda corta", transporte=_transporte_subproceso(llamadas),
                  rol="revisar", registro=reg)
    assert r["rol"] == "revisar" and llamadas[0][0] == "revisar"


# ── degradacion honesta: los cinco fallos, con el error REAL ────────────

def test_consultar_sin_transporte_no_gasta_presupuesto():
    reg = nuevo_registro()
    r = consultar("que hago?", transporte=None, registro=reg)
    assert r["ok"] is False and r["respuesta"] == ""
    assert "no hay transporte" in r["error"]
    assert estado(reg)["consultas"] == 0
    assert "SEGUI SIN ORACULO" in texto_resultado(r)


def test_consultar_transporte_caido_devuelve_el_error_real():
    reg = nuevo_registro()
    r = consultar("por que no responde?", transporte=_transporte_caido(_puerto_cerrado()),
                  registro=reg, timeout=5)
    assert r["ok"] is False and r["respuesta"] == ""
    assert "URLError" in r["error"]               # el tipo REAL de la excepcion
    assert estado(reg)["consultas"] == 1          # el intento se cuenta


def test_consultar_transporte_colgado_no_bloquea_al_agente():
    reg = nuevo_registro()
    t0 = time.time()
    r = consultar("me responde alguien?", transporte=_transporte_colgado(30),
                  registro=reg, timeout=0.5)
    tardo = time.time() - t0
    assert r["ok"] is False and r["respuesta"] == ""
    assert "no respondio" in r["error"]
    assert tardo < 10, f"el agente quedo bloqueado {tardo:.1f}s"


def test_consultar_respuesta_vacia_es_fallo_declarado():
    reg = nuevo_registro()
    r = consultar("decime algo", transporte=_transporte_vacio, registro=reg)
    assert r["ok"] is False
    assert "VACIA" in r["error"]


def test_consultar_timeout_no_numerico_no_revienta():
    """Regresion: timeout=None ('sin limite') reventaba con TypeError DESPUES de
    arrancar el hilo y con la consulta ya contada; el turno se perdia entero."""
    reg = nuevo_registro()
    llamadas = []
    r = consultar("me responde alguien?", transporte=_transporte_subproceso(llamadas),
                  registro=reg, timeout=None)
    assert r["ok"] is True, r["error"]
    # Al transporte le llega el timeout YA saneado: si el watchdog espera 180s y
    # el transporte cree que no tiene limite, son dos presupuestos distintos.
    assert llamadas[0][1] == TIMEOUT_DEF
    # Y el watchdog sigue siendo un tope real con un timeout de texto.
    t0 = time.time()
    r2 = consultar("otra distinta", transporte=_transporte_colgado(30),
                   registro=nuevo_registro(), timeout="0.5")
    assert r2["ok"] is False and "no respondio" in r2["error"]
    assert time.time() - t0 < 10


def test_consultar_transporte_que_devuelve_json_crudo():
    """El fallo del INTEGRADOR, no del oraculo: devolver el dict de la respuesta
    en vez del texto. Antes era un AttributeError que salia del modulo."""
    reg = nuevo_registro()
    r = consultar("y ahora?", transporte=lambda p, rol, to: {"choices": [{"text": "hola"}]},
                  registro=reg)
    assert r["ok"] is False and r["respuesta"] == ""
    assert "dict" in r["error"] and "no texto" in r["error"]
    assert "SEGUI SIN ORACULO" in texto_resultado(r)


def test_estado_respeta_el_max_consultas_que_se_uso():
    """Regresion: estado() hardcodeaba MAX_CONSULTAS y le decia 'restantes 2' a
    un integrador que corria con tope 1 y ya no tenia presupuesto."""
    reg = nuevo_registro()
    llamadas = []
    r = consultar("unica pregunta", transporte=_transporte_subproceso(llamadas),
                  registro=reg, max_consultas=1)
    assert r["ok"] is True and r["restantes"] == 0
    assert estado(reg, max_consultas=1)["restantes"] == 0
    r2 = consultar("otra mas", transporte=_transporte_subproceso(llamadas),
                   registro=reg, max_consultas=1)
    assert r2["ok"] is False and "tope de consultas" in r2["error"]


def test_consultar_pregunta_vacia():
    reg = nuevo_registro()
    llamadas = []
    r = consultar("   ", transporte=_transporte_subproceso(llamadas), registro=reg)
    assert r["ok"] is False and "pregunta vacia" in r["error"]
    assert llamadas == []


# ── anti-abuso: tope por tarea y de-duplicacion ─────────────────────────

def test_tope_de_consultas_por_tarea():
    reg = nuevo_registro()
    llamadas = []
    transporte = _transporte_subproceso(llamadas)
    for i in range(MAX_CONSULTAS):
        r = consultar(f"pregunta distinta numero {i}", transporte=transporte,
                      registro=reg)
        assert r["ok"] is True, r["error"]
    assert len(llamadas) == MAX_CONSULTAS
    r = consultar("una mas, la cuarta", transporte=transporte, registro=reg)
    assert r["ok"] is False
    assert "tope de consultas" in r["error"]
    assert len(llamadas) == MAX_CONSULTAS         # NO se llamo al transporte
    assert estado(reg)["restantes"] == 0
    # reiniciar() = tarea nueva: vuelve el presupuesto.
    reiniciar(reg)
    assert estado(reg)["restantes"] == MAX_CONSULTAS
    r = consultar("una mas, la cuarta", transporte=transporte, registro=reg)
    assert r["ok"] is True and len(llamadas) == MAX_CONSULTAS + 1


def test_dedup_por_pregunta_normalizada():
    reg = nuevo_registro()
    llamadas = []
    transporte = _transporte_subproceso(llamadas)
    r1 = consultar("Como encaro el cache?", transporte=transporte, registro=reg)
    assert r1["ok"] is True and r1["cacheada"] is False
    # Misma pregunta con otra puntuacion/mayusculas/espacios: NO se repregunta.
    r2 = consultar("  ¿COMO  encaro el cache?  ", transporte=transporte, registro=reg)
    assert r2["ok"] is True
    assert r2["cacheada"] is True
    assert len(llamadas) == 1                     # el transporte no se toco
    assert "CACHEADA" in r2["respuesta"]          # y lo DICE
    assert "PLAN para pensar" in r2["respuesta"]  # con la respuesta de antes
    assert estado(reg)["consultas"] == 1          # no gasto presupuesto
    assert "CACHE" in texto_resultado(r2)


def test_los_fallos_no_se_cachean():
    reg = nuevo_registro()
    llamadas = []
    r1 = consultar("pregunta que fallara", transporte=_transporte_vacio, registro=reg)
    assert r1["ok"] is False
    r2 = consultar("pregunta que fallara",
                   transporte=_transporte_subproceso(llamadas), registro=reg)
    assert r2["ok"] is True and r2["cacheada"] is False
    assert len(llamadas) == 1


def test_registro_global_por_defecto_y_reiniciar():
    reiniciar()
    llamadas = []
    r = consultar("algo global", transporte=_transporte_subproceso(llamadas))
    assert r["ok"] is True
    assert estado()["consultas"] == 1
    reiniciar()
    assert estado()["consultas"] == 0 and estado()["cacheadas"] == 0


# ── registro como herramienta (listo, NO registrado) ────────────────────

def test_spec_tool_tiene_la_forma_del_catalogo():
    spec = spec_tool()
    assert spec["nombre"] == NOMBRE_TOOL == "consultar_oraculo"
    assert spec["danger"] is False
    assert len(spec["descripcion"]) > 100
    nombres = [p["nombre"] for p in spec["params"]]
    assert nombres == ["pregunta", "contexto", "rol"]
    for p in spec["params"]:
        assert set(p) >= {"nombre", "tipo", "requerido", "descripcion"}
    assert spec["params"][0]["requerido"] is True
    # copia defensiva: mutar lo devuelto no corrompe la constante del modulo
    spec["params"][0]["descripcion"] = "roto"
    assert PARAMS_TOOL[0]["descripcion"] != "roto"


def test_no_se_metio_en_el_catalogo_por_defecto(monkeypatch):
    """El A/B de 2026-07-25 (46 tools: 4.25/5 -> 2.5/5) manda: la herramienta
    no puede ENGORDAR el catalogo que ve el modelo sin su propia medicion.

    Al cablearla (2026-08-12) se registro con el mecanismo opt-in del repo:
    esta en el registry (asi `run_tool` responde "DESHABILITADA - activala con
    COGNIA_ORACULO=1" en vez de "no existe", que es lo que hace concluir que
    Cognia no sabe hacerlo), pero sin el flag NO se anuncia. Lo que este test
    protege es eso: el catalogo por defecto sigue igual de chico.
    """
    from cognia.agent.tools import CORE_TOOLS, TOOLS, flag_de_optin
    from cognia.simple_mode import visible_tools
    assert NOMBRE_TOOL not in CORE_TOOLS
    assert flag_de_optin(NOMBRE_TOOL) == "COGNIA_ORACULO", (
        "sin flag opt-in la tool entraria al catalogo de cada tarea")
    monkeypatch.delenv("COGNIA_ORACULO", raising=False)
    assert NOMBRE_TOOL not in visible_tools(set(TOOLS), override="sencillo")
    monkeypatch.setenv("COGNIA_ORACULO", "1")
    assert NOMBRE_TOOL in visible_tools(set(TOOLS), override="sencillo"), (
        "con el flag encendido la capacidad tiene que estar disponible")


if __name__ == "__main__":                        # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
