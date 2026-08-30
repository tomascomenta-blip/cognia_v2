# -*- coding: utf-8 -*-
"""
tests/test_harness_veredicto_tool.py
====================================
Regresion del juicio visual 2026-08-24: una lectura SANA se pintaba como
FALLO (vineta roja, resumen rojo, ' ERROR' en la cabecera del offload) porque
la primera linea del fichero leido contenia la palabra ERROR
('2026-08-24T10:00:00 ERROR [cache] ...'). Cinco sitios decidian el veredicto
con `\\bERROR\\b` sobre la cabeza del texto; ahora todos pasan por
harness/veredicto_tool.es_fallo, que para las tools de CONTENIDO solo mira el
prefijo 'RESULTADO <tool> <obj>'.

Cada test falla sin el fix. Sin mocks: se usa run_tool REAL sobre un fichero
real, el offload real y el render real.
"""
from __future__ import annotations

import re

import pytest

from cognia.harness import veredicto_tool as vt

LOG_SANO = ("RESULTADO leer_archivo grande.log: 2026-08-24T10:00:00 ERROR "
            "[cache] evento 0 detalle=6468\n2026-08-24T10:00:01 INFO [db] ok\n")


# -- la regla -----------------------------------------------------------------

@pytest.mark.parametrize("texto, tool, esperado", [
    # El caso del juez: contenido con ERROR en su linea 1 -> sano.
    (LOG_SANO, "leer_archivo", False),
    ("RESULTADO leer_archivo x.log: ERROR x", "leer_archivo", False),
    # El fallo REAL de leer_archivo lleva ERROR antes del ':' del contenido.
    ("RESULTADO leer_archivo x.log ERROR: offset=99 fuera de rango", "leer_archivo", True),
    ("RESULTADO leer_archivo ERROR: no existe", "leer_archivo", True),
    # Busquedas: el patron entrecomillado es un dato, el 'ERROR: uso' un fallo.
    ("RESULTADO buscar 'ERROR': a.py:3 | b.py:9", "buscar", False),
    ("RESULTADO buscar ERROR: uso: buscar <patron>", "buscar", True),
    ("RESULTADO listar .: ERROR_LOG.txt | main.py", "listar", False),
    # Ejecucion y validadores: regla laxa de siempre.
    ("RESULTADO ejecutar (exit 1): Traceback (most recent call last):", "ejecutar", True),
    # Con exit en el prefijo, el exit decide: la salida de un grep de ERROR
    # es contenido (re-tecleo 2026-08-24: exit 0 salia en rojo + E8).
    ("RESULTADO ejecutar (exit 0):      56 ERROR [db]", "ejecutar", False),
    ("RESULTADO ejecutar (exit 0): ERROR: nada grave", "ejecutar", False),
    ("RESULTADO ejecutar ERROR (exit 1): Traceback", "ejecutar", True),
    ("RESULTADO ejecutar ERROR: comando vacio", "ejecutar", True),
    ("RESULTADO ejecutar: BLOQUEADO por Sentinel (rm -rf)", "ejecutar", False),
    ("RESULTADO ejecutar (exit 0): todo bien", "ejecutar", False),
    ("RESULTADO py_validar x.py: ERROR linea 3: invalid syntax", "py_validar", True),
    ("RESULTADO escribir_archivo x.py: OK (39 chars)", "escribir_archivo", False),
    ("RESULTADO escribir_archivo ERROR: ruta fuera del workspace", "escribir_archivo", True),
    # Offload: la cabecera propaga (o no) el marcador.
    ("[SALIDA GRANDE de ejecutar ERROR: 300 lineas, 12 KB. ...]", "ejecutar", True),
    ("[SALIDA GRANDE de leer_archivo: 431 lineas, 22.4 KB. ...]", "leer_archivo", False),
    ("", "leer_archivo", False),
])
def test_es_fallo_distingue_el_marcador_del_contenido(texto, tool, esperado):
    assert vt.es_fallo(texto, tool) is esperado
    assert vt.es_exito(texto, tool) is (not esperado)


def test_sin_tool_se_lee_del_prefijo():
    assert vt.tool_de(LOG_SANO) == "leer_archivo"
    assert vt.tool_de("[SALIDA GRANDE de ejecutar ERROR: ...") == "ejecutar"
    assert vt.tool_de("texto suelto") == ""
    assert vt.es_fallo(LOG_SANO) is False                     # leido del prefijo
    assert vt.es_fallo("RESULTADO ejecutar (exit 2): boom") is True
    # Sin prefijo ni tool: regla laxa (compatibilidad).
    assert vt.es_fallo("ERROR: sin prefijo") is True
    assert vt.es_fallo("todo bien") is False


# -- run_tool REAL: el ok estructurado ---------------------------------------

def test_run_tool_leer_archivo_con_ERROR_en_la_linea_1_es_exito(tmp_path, monkeypatch):
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia.agent import tools as T
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    f = tmp_path / "grande.log"
    f.write_text("2026-08-24T10:00:00 ERROR [cache] evento 0\nINFO ok\n",
                 encoding="utf-8")
    ctx = {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}
    out = T.run_tool("leer_archivo", str(f), ctx)
    assert out.startswith("RESULTADO leer_archivo")
    assert ctx["_ultimo_ok"] is True, out[:160]
    # Y un fallo REAL de la misma tool sigue siendo fallo.
    out2 = T.run_tool("leer_archivo", str(tmp_path / "no_existe.log"), ctx)
    assert ctx["_ultimo_ok"] is False, out2[:160]


# -- offload: la cabecera no inventa el fallo ---------------------------------

def test_offload_no_marca_ERROR_en_la_cabecera_de_una_lectura_sana(tmp_path, monkeypatch):
    from cognia.harness import offloading as off
    monkeypatch.setenv("COGNIA_OFFLOAD_DIR", str(tmp_path / "offload"))
    monkeypatch.setenv("COGNIA_TOOL_RESULT_MAX", "2000")
    # Lo que se mide es la CABECERA de un spill, no el reparto de umbral por
    # tool del 2026-08-30: con LECTURA=1 el umbral de lectura colapsa al
    # general y estas 300 lineas vuelven a spillear como siempre.
    monkeypatch.setenv("COGNIA_TOOL_RESULT_MAX_LECTURA", "1")
    cuerpo = "\n".join(f"2026-08-24T10:00:{i:02d} ERROR [cache] evento {i}"
                       for i in range(300))
    salida = off.formatear_observacion("RESULTADO leer_archivo grande.log: " + cuerpo,
                                       "leer_archivo", "grande.log")
    assert salida.startswith("[SALIDA GRANDE de leer_archivo:"), salida[:120]
    assert not re.search(r"\bERROR\b", salida.split("\n", 1)[0])
    # Y la ejecucion fallida SI lo propaga (contrato de la revision 2026-08-23).
    fallo = "RESULTADO ejecutar (exit 1): boom\n" + cuerpo
    assert re.search(r"\bERROR\b",
                     off.formatear_observacion(fallo, "ejecutar", "x").split("\n", 1)[0])


# -- render: el ok del evento manda sobre el olor del texto -------------------

def test_bloque_colapsado_pinta_verde_una_lectura_sana_con_ERROR(monkeypatch):
    monkeypatch.setenv("COGNIA_ASCII", "0")
    from cognia.harness import render_tools as rt
    lineas, estilos = rt.bloque_colapsado("leer_archivo", "grande.log", ok=True,
                                          resultado=LOG_SANO, max_lineas=1)
    assert estilos[0] == rt.ESTILOS_ESTADO["ok"], (lineas, estilos)
    assert estilos[1] == rt.ESTILO_RESULTADO
    assert lineas[1].strip().endswith("2 lineas"), lineas
    assert rt.es_error(LOG_SANO, "leer_archivo") is False
    assert rt.resumir_resultado("leer_archivo", LOG_SANO) == "2 lineas"
    # ok=False del evento manda aunque el texto no huela a error.
    lineas2, estilos2 = rt.bloque_colapsado("ejecutar", "x", ok=False,
                                            resultado="RESULTADO ejecutar (exit 0): raro")
    assert estilos2[0] == rt.ESTILOS_ESTADO["error"]
    assert estilos2[1] == rt.ESTILOS_ESTADO["error"]


def test_error_accionable_no_se_activa_con_una_lectura_sana():
    from cognia.agent.loop import error_accionable_de_ejecucion
    assert error_accionable_de_ejecucion(["ACCION leer_archivo", LOG_SANO]) == ""
    assert "exit 1" in error_accionable_de_ejecucion(
        ["RESULTADO ejecutar (exit 1): Traceback"])
