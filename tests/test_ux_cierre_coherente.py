# -*- coding: utf-8 -*-
"""
tests/test_ux_cierre_coherente.py
=================================
Regresion del juicio visual 2026-08-24 sobre el CIERRE del turno:

1. Contradiccion: footer '✓ 5.6s · 216 tokens · 2 pasos' y tres lineas
   despues 'No se pudo completar: la ultima operacion fallo' en prosa, con el
   traceback aplastado y sin '<string>'/'<module>' (el Markdown se los comia).
   El objetivo ERA ver fallar el comando y el modelo ya lo habia contado.
2. Tres mensajes para un hecho: 'Agente sin progreso (3 tools seguidas
   fallaron): cierre honesto.' + la linea del logger
   'cognia.hermes.presupuesto_turno: Turno terminado ...' en amarillo +
   '(interrumpida: ...)'. Ahora: UNA linea en el footer
   ('✗ 37.7s · 1213 tokens · 5 pasos · parado: 3 tools seguidas fallaron'),
   el logger baja a INFO y los logs enrutados a la interfaz nunca traen el
   nombre del modulo Python.

Cada test falla sin su fix.
"""
from __future__ import annotations

import io
import logging
import re

import pytest

from cognia.agent import loop as L
from cognia.ux import events
from cognia.ux.renderer import Renderer


# -- 1) la respuesta ya reporta el fallo -> sin E8 y sin ✓ ------------------

@pytest.mark.parametrize("texto", [
    "El comando termino con codigo de salida 1 y el error esperado de Python",
    "Se lanzo un ModuleNotFoundError: No module named 'x'",
    "Traceback (most recent call last): ...",
    "python -c fallo con exit 1",
    "No se pudo importar el modulo",
    "La operación falló porque el fichero no existe",
])
def test_ya_reporta_fallo_reconoce_la_parafrasis_del_modelo(texto):
    assert L.ya_reporta_fallo(texto) is True


@pytest.mark.parametrize("texto", [
    "Listo. Cree cuadrados.py y lo ejecute; la salida fue 1 4 9 16",
    "Termine la tarea.",
    "",
])
def test_ya_reporta_fallo_no_ve_fallos_donde_no_hay(texto):
    assert L.ya_reporta_fallo(texto) is False


def test_anexo_fallo_final_va_como_bloque_fenced_y_conserva_el_traceback():
    err = ('ejecutar (exit 1): Traceback (most recent call last):\n'
           '  File "<string>", line 1, in <module>\n'
           "ModuleNotFoundError: No module named 'x'")
    salida = L.anexo_fallo_final("Listo.", err)
    assert salida.startswith("Listo.\n\nNo se pudo completar")
    assert "```text\n" in salida and salida.rstrip().endswith("```")
    # Renderizado por rich.Markdown, '<string>' y '<module>' sobreviven
    # (como prosa el Markdown los tomaba por HTML y los borraba).
    from rich.console import Console
    from rich.markdown import Markdown
    buf = io.StringIO()
    Console(file=buf, width=100, force_terminal=False).print(Markdown(salida))
    pintado = buf.getvalue()
    assert '"<string>"' in pintado and "<module>" in pintado, pintado


def test_motivo_de_cierre_traduce_el_envelope():
    assert L.motivo_de_cierre({"razon": "bucle_detectado",
                               "detalle": "3 tools seguidas fallaron"}) == (
        "parado: 3 tools seguidas fallaron")
    assert L.motivo_de_cierre({"razon": "presupuesto_agotado",
                               "detalle": "techo 12"}) == "presupuesto agotado: techo 12"
    assert L.motivo_de_cierre({"razon": "interrumpido"}) == "interrumpido"
    assert L.motivo_de_cierre({"razon": "respuesta_texto", "detalle": "x"}) == ""
    assert L.motivo_de_cierre({}) == ""
    assert L.motivo_de_cierre(None) == ""


# -- 2) el footer funde el motivo; remoto sigue plano -------------------------

def _consola():
    from rich.console import Console
    from rich.theme import Theme
    buf = io.StringIO()
    tema = Theme({"ok_cl": "green", "err_cl": "red", "footer": "dim grey50",
                  "warn_cl": "yellow", "info_dim": "dim", "respuesta": "default"})
    return Console(file=buf, theme=tema, highlight=False, width=200,
                   force_terminal=False), buf


def test_footer_local_lleva_el_motivo_del_cierre(monkeypatch):
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    con, buf = _consola()
    r = Renderer(console=con)
    r(events.TareaFin(ok=False, resumen="", pasos=5, tokens_predichos=1213,
                      duracion_s=37.7, motivo="parado: 3 tools seguidas fallaron"))
    r.pintar_footer_pendiente()        # diferido (2026-09-02): debajo de la respuesta
    assert ("✗ 37.7s · 1213 tokens · 5 pasos · parado: 3 tools seguidas "
            "fallaron") in buf.getvalue()


def test_footer_remoto_no_rompe_el_dedup_con_el_motivo(monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    con, buf = _consola()
    r = Renderer(console=con)
    r(events.TareaFin(ok=False, resumen="", pasos=5, tokens_predichos=1213,
                      duracion_s=37.7, motivo="parado: 3 tools seguidas fallaron"))
    from cognia.remoto.sesiones import _RE_FOOTER_RENDERER
    linea = buf.getvalue().strip()
    assert _RE_FOOTER_RENDERER.match(linea), linea


def test_el_evento_sin_motivo_pinta_el_footer_de_siempre():
    con, buf = _consola()
    r = Renderer(console=con)
    r(events.TareaFin(ok=True, pasos=3, tokens_predichos=87, duracion_s=3.2))
    r.pintar_footer_pendiente()
    assert buf.getvalue().strip() == "✓ 3.2s · 87 tokens · 3 pasos"


# -- 3) los logs enrutados no traen el nombre del modulo ---------------------

def test_los_logs_enrutados_a_la_interfaz_no_traen_el_nombre_del_modulo():
    from cognia import logger_config as lc
    if lc._CONSOLE_HANDLER is None:
        pytest.skip("sin handler de consola en este proceso")
    vistos = []
    nivel_previo = lc._CONSOLE_HANDLER.level
    lc.enrutar_consola_a(lambda nivel, texto: vistos.append((nivel, texto)))
    try:
        logging.getLogger("cognia.hermes.presupuesto_turno").warning(
            "Turno terminado [bucle_nativo]: razon=bucle_detectado")
    finally:
        lc.restaurar_enrutado()
        lc._CONSOLE_HANDLER.setLevel(nivel_previo)
    textos = [t for _, t in vistos]
    assert textos, "el enrutado no recibio nada"
    assert not any(re.search(r"cognia\.[a-z_.]+: ", t) for t in textos), textos
    assert any(t.startswith("Turno terminado") for t in textos), textos
    # Los loggers ajenos conservan su nombre: ahi si informa de donde viene.
    # (Se prueba el formateador directo: el root de logger_config filtra lo
    # que no es cognia.* antes de que llegue al enrutado.)
    rec = logging.LogRecord("urllib3.connectionpool", logging.WARNING, __file__,
                            1, "Retrying (1/3)", None, None)
    assert lc._FormatoInterfaz().format(rec) == "urllib3.connectionpool: Retrying (1/3)"
    rec2 = logging.LogRecord("cognia.agent.loop", logging.WARNING, __file__,
                             1, "sin progreso", None, None)
    assert lc._FormatoInterfaz().format(rec2) == "sin progreso"


def test_el_bucle_detectado_ya_no_es_WARNING(caplog):
    from cognia.hermes.presupuesto_turno import (
        PresupuestoTurno, RazonSalida, RAZON_BUCLE_DETECTADO)
    pres = PresupuestoTurno(4)
    pres.consume()
    salida = RazonSalida(pres, etiqueta="bucle_nativo")
    salida.sellar(RAZON_BUCLE_DETECTADO, "3 tools seguidas fallaron")
    with caplog.at_level(logging.INFO, logger="cognia.hermes.presupuesto_turno"):
        env = salida.cerrar([{"role": "assistant", "content": "(interrumpida)"}])
    assert env["razon"] == RAZON_BUCLE_DETECTADO
    assert env["detalle"] == "3 tools seguidas fallaron"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("bucle_detectado" in r.getMessage() for r in caplog.records)
