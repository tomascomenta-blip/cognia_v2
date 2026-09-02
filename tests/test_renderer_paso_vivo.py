# -*- coding: utf-8 -*-
"""
tests/test_renderer_paso_vivo.py
================================
Pedido del dueno (2026-09-02): "eliminar el ruido de las tareas, mostrar
todas las lineas que el agente escribe y la cantidad de tokens en vivo, como
en el chat".

Lo que fija cada test (cada uno falla sin su fix):

- PasoInicio abre la fase de generacion del agente (antes la pantalla estaba
  muda entre el prompt y la primera tool) y resetea el contador POR PASO.
- TextoAgente pinta la prosa del agente ENTERA en streaming y PasoIntencion
  no la repite en una linea cortada.
- TokensVivos.tokens (contados, uno por delta) llegan a la linea viva sin '~'.
- El footer de TareaFin se DIFIERE: lo pinta quien muestra la respuesta,
  debajo de ella, con los extras del cierre ('objetivo 1/1'). Bajo remoto
  sigue saliendo en el acto (contrato del movil).
- El bloque colapsado no repite 'OK (51 chars)' bajo '51 chars escritos'.
"""
from __future__ import annotations

import io
import time

import pytest

from cognia.ux import events
from cognia.ux.renderer import Renderer


def _consola(width=80):
    from rich.console import Console
    from rich.theme import Theme
    buf = io.StringIO()
    tema = Theme({"ok_cl": "green", "err_cl": "red", "footer": "dim",
                  "warn_cl": "yellow", "info_dim": "dim", "respuesta": "default",
                  "intencion": "italic", "escrito": "green", "borrado": "red",
                  "tool_verbo": "cyan", "tool_obj": "bold", "spinner": "green",
                  "pensar": "green"})
    return Console(file=buf, theme=tema, highlight=False, width=width,
                   force_terminal=False), buf


@pytest.fixture(autouse=True)
def _local(monkeypatch):
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setenv("COGNIA_SPINNER", "0")      # sin terminal: nada anima
    monkeypatch.setenv("COGNIA_RENDER_COLAPSO", "0")
    yield
    # Los tests que corren bucle_nativo anotan uso en contexto_vivo, y ese
    # estado de proceso cambia el footer del chat ('ctx N% libre') que el
    # golden footer_cli de test_ux_aspecto compara byte a byte. Se limpia.
    try:
        from cognia.harness import contexto_vivo
        contexto_vivo.reiniciar()
    except Exception:
        pass


# -- PasoInicio ---------------------------------------------------------------

def test_paso_inicio_sin_terminal_no_imprime_y_resetea_el_contador(capsys):
    r = Renderer(console=None)
    r(events.TareaInicio(tarea="t"))
    r(events.TokensVivos(chars=400, tokens=100, fase="razonando"))
    assert r._chars_stream == 400 and r._tokens_stream == 100
    r(events.PasoInicio(paso=2))
    assert r._chars_stream == 0 and r._tokens_stream == 0
    assert r._status is None
    assert capsys.readouterr().out == ""


# -- TextoAgente / PasoIntencion ---------------------------------------------

def test_la_prosa_del_agente_se_pinta_entera_y_la_intencion_no_se_repite(capsys):
    r = Renderer(console=None)
    r(events.TareaInicio(tarea="t"))
    r(events.PasoInicio(paso=1))
    r(events.TextoAgente(texto="Voy a crear el fichero saludo.py ", paso=1))
    r(events.TextoAgente(texto="y despues lo ejecuto para comprobarlo.", paso=1))
    r(events.PasoIntencion(paso=1, intencion="Voy a crear el fichero saludo.py"))
    r(events.ToolInicio(tool="escribir_archivo", args="saludo.py", paso=1))
    out = capsys.readouterr().out
    assert "Voy a crear el fichero saludo.py y despues lo ejecuto para comprobarlo." in out
    assert out.count("Voy a crear el fichero") == 1, out
    assert "∴" not in out          # la linea ∴ de intencion no sale


def test_la_intencion_sale_cuando_el_paso_no_trajo_prosa(capsys):
    r = Renderer(console=None)
    r(events.TareaInicio(tarea="t"))
    r(events.PasoInicio(paso=1))
    r(events.PasoIntencion(paso=1, intencion="Leo motor.py para ver la firma"))
    out = capsys.readouterr().out
    assert "∴ Leo motor.py para ver la firma" in out


def test_la_prosa_final_se_recuerda_para_no_repetirla():
    from cognia.ux import renderer as rnd
    r = Renderer(console=None)
    rnd._renderer = r
    try:
        r(events.TareaInicio(tarea="t"))
        r(events.PasoInicio(paso=1))
        r(events.TextoAgente(texto="La suma es ", paso=1))
        r(events.TextoAgente(texto="5.", paso=1))
        r(events.TareaFin(ok=True, resumen="La suma es 5.", pasos=1,
                          tokens_predichos=10, duracion_s=0.2))
        assert rnd.prosa_final_pintada() == "La suma es 5."
        r(events.TareaInicio(tarea="otra"))
        assert rnd.prosa_final_pintada() == ""
    finally:
        rnd._renderer = None


def test_bajo_remoto_la_prosa_no_se_pinta(monkeypatch, capsys):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    r = Renderer(console=None)
    r(events.TareaInicio(tarea="t"))
    r(events.PasoInicio(paso=1))
    r(events.TextoAgente(texto="hola", paso=1))
    r(events.PasoIntencion(paso=1, intencion="hola"))
    out = capsys.readouterr().out
    assert "hola" not in out.replace("∴ hola", "")   # solo la intencion
    assert r._chars_stream == 4                            # pero SI cuenta


# -- tokens contados en la linea viva ------------------------------------------

def test_tokens_contados_salen_sin_tilde_y_la_estimacion_con_ella():
    from cognia.ux import spinner_vivo as sv
    t0 = 1000.0
    con = sv.linea_estado(None, t0, t0 + 5, chars=400, ancho=100, tokens=123)
    assert "123 tok" in con and "~" not in con
    est = sv.linea_estado(None, t0, t0 + 5, chars=400, ancho=100)
    assert "~100 tok" in est


def test_el_renderer_acumula_los_tokens_contados_por_paso():
    r = Renderer(console=None)
    r(events.TareaInicio(tarea="t"))
    r(events.PasoInicio(paso=1))
    r(events.TokensVivos(chars=40, tokens=10, fase="razonando"))
    r(events.TokensVivos(chars=80, tokens=20, fase="escribiendo"))
    assert r._tokens_stream == 30 and r._chars_stream == 120
    assert r._fase_stream == "escribiendo"


# -- footer diferido ------------------------------------------------------------

def test_el_footer_se_difiere_y_sale_al_reclamarlo_con_los_extras():
    from cognia.ux import renderer as rnd
    console, buf = _consola()
    r = Renderer(console=console)
    rnd._renderer = r
    try:
        r(events.TareaInicio(tarea="t"))
        r(events.TareaFin(ok=True, resumen="listo", pasos=2,
                          tokens_predichos=100, duracion_s=5.0))
        assert "5.0s" not in buf.getvalue()          # todavia no
        rnd.anotar_footer("objetivo 1/1")
        assert rnd.pintar_footer_pendiente() is True
        salida = buf.getvalue()
        assert "5.0s" in salida and "100 tokens" in salida and "2 pasos" in salida
        assert "objetivo 1/1" in salida
        assert rnd.pintar_footer_pendiente() is False   # ya reclamado
    finally:
        rnd._renderer = None


def test_un_footer_no_reclamado_se_descarta_en_la_tarea_siguiente():
    console, buf = _consola()
    r = Renderer(console=console)
    r(events.TareaInicio(tarea="t"))
    r(events.TareaFin(ok=True, resumen="x", pasos=1,
                      tokens_predichos=10, duracion_s=3.0))
    r(events.TareaInicio(tarea="otra"))
    assert r.pintar_footer_pendiente() is False
    assert "3.0s" not in buf.getvalue()


def test_bajo_remoto_el_footer_sale_en_el_acto(monkeypatch, capsys):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    r = Renderer(console=None)
    r(events.TareaInicio(tarea="t"))
    r(events.TareaFin(ok=True, resumen="x", pasos=2,
                      tokens_predichos=100, duracion_s=5.0))
    out = capsys.readouterr().out
    assert "5.0s" in out and "100 tokens" in out
    assert r.pintar_footer_pendiente() is False


# -- Progreso -------------------------------------------------------------------

def test_progreso_sin_terminal_es_una_linea_tenue(capsys):
    r = Renderer(console=None)
    r(events.Progreso(texto="revision profunda: arrancando index.html"))
    assert "revision profunda: arrancando index.html" in capsys.readouterr().out


# -- bloque colapsado sin la fila redundante -------------------------------------

def test_el_bloque_colapsado_no_repite_lo_que_el_resumen_ya_dijo():
    from cognia.harness import render_tools as rt
    lineas, _ = rt.bloque_colapsado(
        "escribir_archivo", "suma.py|def suma(a, b):\n    return a + b\n",
        True, "RESULTADO escribir_archivo suma.py: OK (51 chars)",
        max_lineas=3, ancho=100)
    texto = "\n".join(lineas)
    assert "51 chars escritos" in texto
    assert "OK (51 chars)" not in texto
    assert "+1 linea" not in texto           # lo deduplicado no cuenta como oculto


# -- entrega compacta -------------------------------------------------------------

def test_la_entrega_con_varios_ficheros_sigue_siendo_multilinea(tmp_path):
    from cognia.harness import entrega as E
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("x = 1\n", encoding="utf-8")
    b.write_text("y = 2\n", encoding="utf-8")
    txt = E.bloque(E.informe([str(a), str(b)]))
    assert txt.startswith(E.MARCA + " — lo que quedo en disco:")
    assert "a.py" in txt and "b.py" in txt
    assert "no dice que hagan" not in txt


def test_una_linea_ajena_cierra_antes_la_prosa_abierta(capsys):
    """print_fn del bucle imprime por fuera del bus: la prosa en streaming se
    vacia ANTES, o el aviso sale encima del texto (captura real 2026-09-02)."""
    from cognia.ux import renderer as rnd
    r = Renderer(console=None)
    rnd._renderer = r
    try:
        r(events.TareaInicio(tarea="t"))
        r(events.PasoInicio(paso=1))
        r(events.TextoAgente(texto="listar .", paso=1))
        rnd.cerrar_flujo_abierto()
        print("AVISO ajeno")
        out = capsys.readouterr().out
        assert out.index("listar .") < out.index("AVISO ajeno")
    finally:
        rnd._renderer = None


def test_objetivo_incumplido_vuelve_el_footer_en_fallo():
    from cognia.ux import renderer as rnd
    console, buf = _consola()
    r = Renderer(console=console)
    rnd._renderer = r
    try:
        r(events.TareaInicio(tarea="t"))
        r(events.TareaFin(ok=True, resumen="x", pasos=1,
                          tokens_predichos=10, duracion_s=3.0))
        rnd.anotar_footer("objetivo 0/1", ok=False)
        assert rnd.pintar_footer_pendiente() is True
        salida = buf.getvalue()
        assert "✗" in salida and "objetivo 0/1" in salida and "✓" not in salida
    finally:
        rnd._renderer = None


def test_con_pensar_ver_el_razonamiento_del_agente_sale_entero_y_sin_repetir(monkeypatch, capsys):
    """/pensar ver en modo agente: el bucle emite RazonamientoTick por
    fragmento y el renderer lo streamea como prosa; PasoIntencion no lo
    resume otra vez, y los chars no se cuentan dos veces (los cuenta el pulso)."""
    monkeypatch.setenv("COGNIA_PENSAR", "ver")
    r = Renderer(console=None)
    r(events.TareaInicio(tarea="t"))
    r(events.PasoInicio(paso=1))
    r(events.RazonamientoTick(chars=10, fragmento="Primero leo "))
    r(events.RazonamientoTick(chars=10, fragmento="motor.py y luego edito."))
    r(events.TokensVivos(chars=35, tokens=8, fase="razonando"))
    r(events.PasoIntencion(paso=1, intencion="Primero leo motor.py y luego edito."))
    r(events.ToolInicio(tool="leer_archivo", args="motor.py", paso=1))
    out = capsys.readouterr().out
    assert "Primero leo motor.py y luego edito." in out
    assert out.count("Primero leo") == 1, out
    assert r._chars_stream == 35            # solo el pulso; el tick no suma


def test_el_bucle_emite_el_razonamiento_solo_con_pensar_ver(monkeypatch):
    from cognia.agent import loop as loop_mod
    from cognia.agent.chat_client import RespuestaChat, mensaje_assistant, mensaje_tool
    from cognia.agent.tool_schemas import args_legacy, schemas_para
    monkeypatch.delenv("COGNIA_STREAM", raising=False)

    def _correr():
        vistos = []
        events.suscribir(vistos.append)
        try:
            def _completar(mensajes, tools=None, **kw):
                kw["on_reasoning"]("pienso ")
                kw["on_token"]("listo")
                return RespuestaChat(texto="listo", finish_reason="stop")
            loop_mod.bucle_nativo(
                "t", "sos el agente", _completar, schemas_para(), args_legacy,
                mensaje_assistant, mensaje_tool, lambda n, a, c: "RESULTADO",
                {}, {"nombre": "x", "modelo": "m", "url": "http://127.0.0.1:9",
                     "tools": "nativo", "n_ctx": 16384, "temperature": 0.7,
                     "top_p": 0.8, "reasoning_effort": "", "max_tokens": 4096},
                ["TAREA: t"], [], lambda *a, **k: None, 2)
        finally:
            events.desuscribir(vistos.append)
        return [type(e).__name__ for e in vistos]

    monkeypatch.delenv("COGNIA_PENSAR", raising=False)
    assert "RazonamientoTick" not in _correr()
    monkeypatch.setenv("COGNIA_PENSAR", "ver")
    assert "RazonamientoTick" in _correr()
