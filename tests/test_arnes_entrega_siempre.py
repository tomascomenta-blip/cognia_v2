# -*- coding: utf-8 -*-
"""
tests/test_arnes_entrega_siempre.py
===================================
LA TRAZA DEL 2026-08-31: tres tareas seguidas sobre el mismo juego HTML, media
hora cada una, y el dueno no se llevo NADA de las tres.

    ✗ 819.0s · 15 pasos · sin progreso verificado: meseta_de_coste
      (cerrada sin progreso verificado: meseta_de_coste)
      Salida de la ejecución: extraido 19630 chars SINTAXIS_OK

    ✗ 422.4s · 10 pasos · sin progreso verificado: sin_arranque
      Salida de la ejecución: OK

En disco habia un index.html de 32 KB cortado a mitad de una clase (sin
`</script>`, sin `</html>`, con 50 ids de botones y UN solo addEventListener), y
en dos de las tres tareas no se escribio ni un byte. Ninguna de las dos cosas
se dijo, y el HTML roto ademas contaba como avance verificado.

Este fichero fija los tres arreglos de punta a punta, con `completar` guionado
(sin modelo, patron de test_arnes_ampliacion_pasos.py):

 1. un HTML truncado NO es un avance verificado;
 2. el turno cierra SIEMPRE con el bloque ENTREGA, tambien cuando el cierre es
    por estancamiento (que es por donde salieron las tres tareas);
 3. el vigilante de razonamiento inyecta su recordatorio cuando el modelo
    piensa mucho y no deja un avance detras.
"""
from __future__ import annotations

import json

import pytest

from cognia.agent import loop as loop_mod
from cognia.agent.chat_client import (RespuestaChat, ToolCall,
                                      mensaje_assistant, mensaje_tool)
from cognia.agent.tool_schemas import args_legacy, schemas_para
from cognia.estado.presupuesto_progreso import _validar_fichero
from cognia.harness import entrega as E

HTML_CORTADO = ("<!DOCTYPE html>\n<html><body>\n"
                "<button id='btnNew'>NEW GAME</button>\n<script>\n"
                "class Renderer {\n  draw(){\n    this.gl.clear();\n")
HTML_ENTERO = ("<!DOCTYPE html>\n<html><body>\n"
               "<button id='btnNew'>NEW GAME</button>\n<script>\n"
               "document.getElementById('btnNew').onclick = () => 1;\n"
               "</script>\n</body></html>\n")


@pytest.fixture(autouse=True)
def _aislado(monkeypatch, tmp_path):
    for var in ("COGNIA_TRAZAS", "COGNIA_TRACE", "COGNIA_COMPACT",
                "COGNIA_ESPECULAR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COGNIA_ESTADO", "1")       # el gobernador de progreso
    monkeypatch.setenv("COGNIA_REVISION", "0")     # la revision EJECUTA cosas
    monkeypatch.setenv("COGNIA_ENTREGA", "1")
    monkeypatch.setenv("COGNIA_RAZONAMIENTO", "1")
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path))


def _perfil():
    return {"nombre": "razonador_nativo", "modelo": "x.gguf",
            "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": 16384,
            "temperature": 1.0, "top_p": 1.0, "max_tokens": 4096}


def _resp_tools(*calls):
    return RespuestaChat(
        texto="", finish_reason="tool_calls",
        usage={"completion_tokens": 20, "prompt_tokens": 100},
        tool_calls=[ToolCall(id=i, nombre=n, argumentos=a,
                             argumentos_crudos=json.dumps(a))
                    for i, n, a in calls])


def _resp_pensando(chars=9000):
    """Un paso que se va ENTERO en razonar y aun asi llama a una tool inutil."""
    return RespuestaChat(
        texto="", finish_reason="tool_calls",
        usage={"completion_tokens": 900, "prompt_tokens": 100},
        reasoning_content="reconsidero el enfoque del renderizador otra vez " * (chars // 46),
        tool_calls=[ToolCall(id="p", nombre="listar", argumentos={"path": "."},
                             argumentos_crudos='{"path": "."}')])


def _resp_fin(texto="Listo."):
    return RespuestaChat(texto=texto, finish_reason="stop",
                         usage={"completion_tokens": 5, "prompt_tokens": 200})


def _correr(respuestas, run_tool, max_turns=6, tarea="construi el juego"):
    it = iter(respuestas)

    def _completar(mensajes, tools=None, **kw):
        return next(it, _resp_fin())

    avisos = []
    out = loop_mod.bucle_nativo(
        tarea, "sos el agente", _completar, schemas_para(),
        args_legacy, mensaje_assistant, mensaje_tool, run_tool, {},
        _perfil(), [f"TAREA: {tarea}"], [],
        lambda m, *a, **k: avisos.append(str(m)), max_turns)
    return out, avisos


# ══════════════════════════════════════════════════════════════════════
# 1. Un HTML truncado no es un avance verificado
# ══════════════════════════════════════════════════════════════════════

def test_el_html_cortado_ya_no_cuenta_como_fichero_valido(tmp_path):
    roto = tmp_path / "index.html"
    roto.write_text(HTML_CORTADO, encoding="utf-8")
    ok, motivo = _validar_fichero(str(roto))
    assert ok is False
    assert "INCOMPLETO" in motivo

    sano = tmp_path / "bueno.html"
    sano.write_text(HTML_ENTERO, encoding="utf-8")
    assert _validar_fichero(str(sano))[0] is True


# ══════════════════════════════════════════════════════════════════════
# 2. La ENTREGA sale en TODOS los cierres
# ══════════════════════════════════════════════════════════════════════

def test_el_cierre_por_estancamiento_entrega_el_estado_del_fichero(tmp_path):
    """El cierre exacto de la traza: el gobernador corta por falta de avance.

    Antes: '(cerrada sin progreso verificado: sin_arranque)' y nada mas.
    Ahora: eso MAS el inventario de lo que quedo en disco, con el HTML marcado
    ROTO y la linea en la que se corta.
    """
    destino = tmp_path / "index.html"

    def _run_tool(name, args, ctx):
        destino.write_text(HTML_CORTADO, encoding="utf-8")
        return f"RESULTADO {name} {destino}: OK"

    calls = [(f"t{i}", "escribir_archivo",
              {"path": str(destino), "contenido": HTML_CORTADO + "// %d" % i})
             for i in range(8)]
    out, _ = _correr([_resp_tools(c) for c in calls], _run_tool, max_turns=8)
    texto = out["texto"]
    assert "sin progreso verificado" in texto or "presupuesto" in texto
    assert E.MARCA in texto
    assert "ROTO index.html" in texto
    assert "se corta en la linea" in texto
    assert "INCOMPLETOS" in texto


def test_una_tarea_que_no_escribio_nada_lo_dice(tmp_path):
    """Las dos ultimas tareas de la traza. El cierre util es "no escribi nada",
    no el stdout de la ultima tool."""
    def _run_tool(name, args, ctx):
        return f"RESULTADO {name}: OK"

    calls = [(f"t{i}", "listar", {"path": "."}) for i in range(6)]
    out, _ = _correr([_resp_tools(c) for c in calls], _run_tool, max_turns=6)
    assert E.MARCA in out["texto"]
    assert "ningun fichero escrito" in out["texto"]


def test_un_cierre_SANO_con_ficheros_tambien_lleva_la_entrega(tmp_path):
    destino = tmp_path / "ok.html"

    def _run_tool(name, args, ctx):
        destino.write_text(HTML_ENTERO, encoding="utf-8")
        return f"RESULTADO {name} {destino}: OK"

    out, _ = _correr(
        [_resp_tools(("t1", "escribir_archivo",
                      {"path": str(destino), "contenido": HTML_ENTERO})),
         _resp_fin("Hecho.")], _run_tool, max_turns=6)
    assert out["ok"] is True
    assert "OK  ok.html" in out["texto"]


def test_una_respuesta_en_PROSA_sin_ficheros_no_lleva_inventario():
    """Una pregunta contestada no necesita "no escribi nada": seria ruido."""
    out, _ = _correr([_resp_fin("Son las tres.")],
                     lambda n, a, c: "RESULTADO ok", max_turns=4,
                     tarea="que hora es")
    assert E.MARCA not in out["texto"]


def test_la_entrega_se_puede_apagar(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_ENTREGA", "0")
    def _run_tool(name, args, ctx):
        return f"RESULTADO {name}: OK"
    calls = [(f"t{i}", "listar", {"path": "."}) for i in range(6)]
    out, _ = _correr([_resp_tools(c) for c in calls], _run_tool, max_turns=6)
    assert E.MARCA not in out["texto"]


# ══════════════════════════════════════════════════════════════════════
# 3. El recordatorio de razonamiento en bucle
# ══════════════════════════════════════════════════════════════════════

def test_pensar_mucho_sin_avanzar_dispara_el_recordatorio(tmp_path):
    def _run_tool(name, args, ctx):
        return f"RESULTADO {name}: OK (nada cambio)"

    out, avisos = _correr([_resp_pensando() for _ in range(6)],
                          _run_tool, max_turns=6)
    unidos = "\n".join(avisos)
    assert "razonamiento en bucle" in unidos
    assert "racha 1" in unidos and "racha 2" in unidos   # el nudge escala
    # (el aviso EN VIVO por hitos solo existe con streaming, que este arnes no
    #  usa: su unidad esta en test_harness_entrega_y_razonamiento.py)


def test_la_racha_dura_apaga_el_pensamiento_extendido(tmp_path, monkeypatch):
    """La unica intervencion con medicion detras: con el pensamiento apagado
    este modelo emite el fichero con la quinta parte del presupuesto."""
    monkeypatch.delenv("COGNIA_THINKING", raising=False)
    it = iter([_resp_pensando() for _ in range(6)])

    def _completar(mensajes, tools=None, **kw):
        return next(it, _resp_fin())

    perfil = _perfil()
    perfil["kwargs_plantilla"] = {"enable_thinking": True}
    avisos = []
    loop_mod.bucle_nativo(
        "construi el juego", "sos el agente", _completar, schemas_para(),
        args_legacy, mensaje_assistant, mensaje_tool,
        lambda n, a, c: f"RESULTADO {n}: OK (nada cambio)", {},
        perfil, ["TAREA: construi el juego"], [],
        lambda m, *a, **k: avisos.append(str(m)), 6)
    assert "apago el pensamiento extendido" in "\n".join(avisos)


def test_apagado_por_entorno_no_dispara_nada(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_RAZONAMIENTO", "0")

    def _run_tool(name, args, ctx):
        return f"RESULTADO {name}: OK (nada cambio)"

    _, avisos = _correr([_resp_pensando() for _ in range(6)],
                        _run_tool, max_turns=6)
    assert "razonamiento en bucle" not in "\n".join(avisos)


# ══════════════════════════════════════════════════════════════════════
# 4. Tokens EN VIVO en modo agente (pedido del dueno 2026-08-31)
# ══════════════════════════════════════════════════════════════════════

def test_el_bucle_emite_TokensVivos_de_los_tres_canales(monkeypatch):
    """El `~N tok` de la linea viva se alimentaba solo de TokenTexto y
    RazonamientoTick — eventos de PINTAR que el agente no emite — asi que en
    /hacer el spinner decia los segundos y nada mas. Ahora el bucle emite el
    pulso de contabilidad desde los tres canales del stream, incluido el de
    los ARGUMENTOS del tool call, que es el unico latido de un paso que esta
    escribiendo un fichero.
    """
    from cognia.ux import events as ev

    vistos = []
    monkeypatch.setattr(ev, "emitir",
                        lambda e: vistos.append(e) if type(e).__name__ == "TokensVivos" else None)

    def _completar(mensajes, tools=None, **kw):
        # El bucle pasa sus callbacks de stream por kwargs: se los llama como
        # los llamaria el SSE de chat_client.
        kw["on_reasoning"]("pienso un poco ")
        kw["on_tool_frag"]('{"path": "a.html", "contenido": "<html>')
        kw["on_token"]("texto final")
        return _resp_fin("Listo.")

    loop_mod.bucle_nativo(
        "haz algo", "sos el agente", _completar, schemas_para(),
        args_legacy, mensaje_assistant, mensaje_tool,
        lambda n, a, c: "RESULTADO ok", {}, _perfil(),
        ["TAREA: haz algo"], [], lambda m, *a, **k: None, 3)

    assert vistos, "el bucle no emitio ningun TokensVivos"
    fases = {e.fase for e in vistos}
    assert fases & {"razonando", "escribiendo", "respondiendo"}
    assert sum(e.chars for e in vistos) > 0


def test_el_renderer_cuenta_TokensVivos_sin_pintar_nada():
    from cognia.ux import events as ev
    from cognia.ux import renderer as rnd

    r = rnd.Renderer.__new__(rnd.Renderer)
    r._chars_stream = 0
    r._status = None
    r._ticker = None
    r._on_tokens_vivos(ev.TokensVivos(chars=120, fase="escribiendo"))
    r._on_tokens_vivos(ev.TokensVivos(chars=80, fase="razonando"))
    assert r._chars_stream == 200
    # basura: no suma y no revienta
    r._on_tokens_vivos(ev.TokensVivos(chars=None, fase=""))
    assert r._chars_stream == 200
