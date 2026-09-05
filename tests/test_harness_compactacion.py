# -*- coding: utf-8 -*-
"""
Regresion (2026-08-23, F4): la compactacion del contexto era mordiscos de
truncado — `loop._recortar_mensajes` trunca contents viejos a 200 chars DE A 3
POR PASADA, y cada pasada muta el principio del contexto e invalida la KV
cache del server (medido en el repo: ~24x por ciclo).

Estos tests fijan el contrato de `cognia/harness/compactacion.py` (numeros de
deepseek-harness): al superar el umbral, UNA pasada deja
[system intacto, objetivo intacto, UN resumen estructurado, cola intacta].

  (a) system y user del objetivo INTACTOS
  (b) la cola reciente INTACTA (cero mordiscos de 200 chars en este modo)
  (c) el resumen lista las tools descartadas con su referencia de spill (F3)
  (d) el modo 'truncado' sigue byte-identico al de hoy (fallback intocado)
  (e) idempotencia: compactar dos veces no duplica resumenes (se FUNDEN)

Sin el modulo, el fichero entero falla en el import. Sin mocks: se compacta
una lista de mensajes real, como la que arma bucle_nativo.
"""

from __future__ import annotations

import copy

import pytest

from cognia.agent.loop import _compactar_por_resumen, _recortar_mensajes
from cognia.harness import compactacion as comp


@pytest.fixture(autouse=True)
def knobs_limpios(monkeypatch, tmp_path):
    """Ningun test hereda knobs del entorno ni telemetria de otro test. El
    almacen del offload va a tmp: compactar() vuelca el historial crudo a
    disco (2026-08-24) y sin esto los tests escribirian en el ~/.cognia real."""
    for var in ("COGNIA_COMPACT", "COGNIA_COMPACT_UMBRAL",
                "COGNIA_COMPACT_RETENCION", "COGNIA_COMPACT_CAP"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COGNIA_OFFLOAD_DIR", str(tmp_path / "offload"))
    comp._ULTIMA.clear()
    comp._ULTIMO_ERROR.clear()


# La referencia de spill EXACTA que deja harness/offloading (F3) en el content
# de un turno tool cuando la salida se fue a disco.
_SPILL = ("[SALIDA GRANDE de leer_archivo: 1200 lineas, 45.0 KB. NO esta "
          "entera aca: faltan 1180 lineas (43.0 KB). NO se perdio nada: esta "
          "guardada.]\ncabeza\n"
          "[COMPLETO en res:3f2a1b (1200 lineas, 45000 bytes exactos) -> "
          "fichero: C:\\tmp\\off\\res-3f2a1b.txt. Para ver mas usa la "
          "herramienta recuperar, NO repitas la llamada original:]\n"
          "  recuperar res:3f2a1b lineas 16-75   (rango de lineas, 1-1200)")


def _historial(n_pares: int = 6, chars_tool: int = 3000) -> list:
    """Un historial como el que arma bucle_nativo: system + user objetivo +
    pares (assistant con tool_call -> tool) + assistant final chico."""
    msgs = [
        {"role": "system", "content": "SYSTEM: reglas del agente"},
        {"role": "user", "content": "OBJETIVO: arregla el bug de la fecha"},
    ]
    for i in range(n_pares):
        msgs.append({
            "role": "assistant", "content": "",
            "reasoning_content": ("pienso el paso %d " % i) * 40,
            "tool_calls": [{"type": "function", "id": "c%d" % i,
                            "function": {"name": "leer_archivo",
                                         "arguments": '{"ruta": "f%d.py"}' % i}}],
        })
        msgs.append({"role": "tool", "tool_call_id": "c%d" % i,
                     "content": ("linea de f%d\n" % i) * (chars_tool // 12)})
    msgs.append({"role": "assistant", "content": "sigo con lo siguiente"})
    return msgs


# ── el modo resumen ──────────────────────────────────────────────────────────

def test_bajo_el_umbral_no_toca_nada():
    msgs = _historial()
    antes = copy.deepcopy(msgs)
    info = comp.compactar(msgs, n_ctx=65536, prompt_tokens=100)
    assert not info["aplicada"]
    assert msgs == antes


def test_system_y_objetivo_intactos_y_cola_intacta():
    msgs = _historial(n_pares=8)
    antes = copy.deepcopy(msgs)
    info = comp.compactar(msgs, n_ctx=10000, prompt_tokens=9000)
    assert info["aplicada"] and info["liberados"] > 0
    # (a) cabeza protegida byte a byte
    assert msgs[0] == antes[0]
    assert msgs[1] == antes[1]
    # UN solo resumen, pegado al objetivo
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"].startswith(comp._MARCA)
    # (b) la cola es un SUFIJO exacto del historial original: cero mordiscos
    cola = msgs[3:]
    assert cola == antes[len(antes) - len(cola):]
    # el estimado de tokens baja de verdad
    assert info["tokens_despues"] < info["tokens_antes"]


def test_resumen_lista_tools_descartadas_con_su_spill():
    msgs = _historial(n_pares=6)
    # el segundo tool viejo llevaba su salida spilleada por F3
    msgs[5]["content"] = _SPILL
    info = comp.compactar(msgs, n_ctx=10000, prompt_tokens=9000)
    assert info["aplicada"]
    resumen = msgs[2]["content"]
    # (c) nombre + veredicto + handle + RUTA del spill: lo descartado se puede
    # recuperar sin re-ejecutar nada
    assert "leer_archivo" in resumen
    assert "-> OK" in resumen
    assert "res:3f2a1b" in resumen
    assert "res-3f2a1b.txt" in resumen


def test_resumen_incluye_el_canal_de_estado():
    from cognia.estado import canal
    estado = canal.EstadoVerificado(objetivo="arreglar la fecha")
    canal.anotar_restriccion(estado, "NUNCA tocar produccion en Railway")
    msgs = _historial(n_pares=6)
    info = comp.compactar(msgs, n_ctx=10000, prompt_tokens=9000, estado=estado)
    assert info["aplicada"]
    resumen = msgs[2]["content"]
    assert "[ESTADO VERIFICADO]" in resumen
    assert "NUNCA tocar produccion en Railway" in resumen


def test_la_cola_nunca_arranca_en_un_tool_huerfano():
    # Un assistant con 3 tool_calls paralelas y 3 tools grandes: el corte por
    # presupuesto caeria en mitad del grupo; el contrato es retroceder hasta
    # incluir al assistant que las pidio (huerfano = template roto).
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "OBJETIVO"},
        {"role": "assistant", "content": "", "reasoning_content": "x" * 2000,
         "tool_calls": [{"type": "function", "id": "v",
                         "function": {"name": "listar", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "v", "content": "y" * 2000},
        {"role": "assistant", "content": "",
         "tool_calls": [{"type": "function", "id": "p%d" % i,
                         "function": {"name": "leer_archivo",
                                      "arguments": '{"ruta": "g%d.py"}' % i}}
                        for i in range(3)]},
    ]
    for i in range(3):
        msgs.append({"role": "tool", "tool_call_id": "p%d" % i,
                     "content": "z" * 1500})
    info = comp.compactar(msgs, n_ctx=2000, prompt_tokens=1900,
                          retencion=0.4)
    assert info["aplicada"]
    tras_resumen = msgs[3]
    assert tras_resumen["role"] != "tool"
    # el grupo quedo entero: el assistant de las 3 llamadas + sus 3 tools
    assert tras_resumen.get("tool_calls")
    assert [m["role"] for m in msgs[4:]] == ["tool", "tool", "tool"]


def test_idempotente_compactar_dos_veces_funde_el_resumen():
    msgs = _historial(n_pares=6)
    msgs[5]["content"] = _SPILL
    info1 = comp.compactar(msgs, n_ctx=10000, prompt_tokens=9000)
    assert info1["aplicada"]
    # la tarea siguio: mas pares de tool nuevos encima del resumen
    for i in range(10, 16):
        msgs.insert(-1, {
            "role": "assistant", "content": "",
            "tool_calls": [{"type": "function", "id": "c%d" % i,
                            "function": {"name": "ejecutar",
                                         "arguments": '{"cmd": "pytest -q %d"}' % i}}]})
        msgs.insert(-1, {"role": "tool", "tool_call_id": "c%d" % i,
                         "content": "salida %d\n" % i * 200})
    info2 = comp.compactar(msgs, n_ctx=10000, prompt_tokens=9000)
    assert info2["aplicada"]
    # (e) UN solo resumen en todo el historial: el previo se fundio
    marcas = [m for m in msgs
              if str(m.get("content") or "").startswith(comp._MARCA)]
    assert len(marcas) == 1
    # y lo que el resumen viejo sabia (el spill) sobrevive en el nuevo
    assert "res:3f2a1b" in marcas[0]["content"]
    assert "res-3f2a1b.txt" in marcas[0]["content"]


def test_cap_recorta_lineas_viejas_y_lo_dice():
    msgs = _historial(n_pares=30, chars_tool=1200)
    info = comp.compactar(msgs, n_ctx=10000, prompt_tokens=9000, cap=900)
    assert info["aplicada"]
    resumen = msgs[2]["content"]
    assert len(resumen) <= 900 + 200   # cap + margen del aviso
    assert "omitidas por cap" in resumen


# ── el fallback truncado ─────────────────────────────────────────────────────

def _truncado_esperado(msgs: list) -> list:
    """El comportamiento de HOY de _recortar_mensajes, congelado literal:
    content de tools y reasoning de assistants viejos a 200 chars, de a 3."""
    esperado = copy.deepcopy(msgs)
    ultimo_assistant = max(i for i, m in enumerate(esperado)
                           if m.get("role") == "assistant")
    recortados = 0
    for i, m in enumerate(esperado):
        if m.get("role") == "tool" and len(m.get("content") or "") > 400:
            m["content"] = (m["content"][:200]
                            + "\n[... recortado por presupuesto de contexto ...]")
            recortados += 1
        elif (m.get("role") == "assistant" and i != ultimo_assistant
                and len(m.get("reasoning_content") or "") > 400):
            m["reasoning_content"] = (
                m["reasoning_content"][:200]
                + "\n[... razonamiento recortado por presupuesto de contexto ...]")
            recortados += 1
        if recortados >= 3:
            break
    return esperado


def test_modo_truncado_sigue_byte_identico_al_de_hoy():
    # (d) el fallback no cambio NADA: misma mutacion, mismos literales, mismo
    # tope de 3 por pasada.
    msgs = _historial(n_pares=5)
    esperado = _truncado_esperado(msgs)
    liberados = _recortar_mensajes(msgs, 10000, 9000)
    assert liberados > 0
    assert msgs == esperado


def test_env_truncado_fuerza_el_modo_viejo(monkeypatch):
    monkeypatch.setenv("COGNIA_COMPACT", "truncado")
    msgs = _historial(n_pares=5)
    antes = copy.deepcopy(msgs)
    salida = []
    r = _compactar_por_resumen(msgs, 10000, 9000, None, salida.append)
    # None = "usa el truncado"; y el resumen no toco el historial
    assert r is None
    assert msgs == antes
    assert not any(str(m.get("content") or "").startswith(comp._MARCA)
                   for m in msgs)


def test_fallo_del_resumen_degrada_al_truncado_sin_mutar(monkeypatch):
    # Un `estado` roto (sin .get) revienta canal.render: compactar lanza SIN
    # haber tocado la lista y el bucle cae al truncado en ese turno.
    msgs = _historial(n_pares=5)
    antes = copy.deepcopy(msgs)
    salida = []
    r = _compactar_por_resumen(msgs, 10000, 9000, object(), salida.append)
    assert r is None
    assert msgs == antes
    # y el fallo quedo registrado para la puerta /compactar
    assert comp._ULTIMO_ERROR.get("motivo")


def test_telemetria_de_la_puerta():
    msgs = _historial(n_pares=8)
    comp.compactar(msgs, n_ctx=10000, prompt_tokens=9000)
    est = comp.estado_puerta()
    assert est["modo"] == "resumen"
    assert est["ultima"]["modo"] == "resumen"
    assert est["ultima"]["tokens_antes"] == 9000
    assert est["ultima"]["tokens_despues"] < 9000
    # el modo viejo tambien anota (lo llama el bucle tras sus mordiscos)
    comp.anotar_truncado(4000, 9000, 10000)
    assert comp.estado_puerta()["ultima"]["modo"] == "truncado"


# ── el disparo bajo streaming (est sin prompt_tokens) ────────────────────────

def test_bucle_compacta_aunque_el_stream_no_traiga_prompt_tokens(monkeypatch):
    """Regresion (cazada TECLEANDO en el REPL, 2026-08-23): bajo streaming el
    usage estimado por timings/frames viene SIN prompt_tokens, el presupuesto
    de contexto contaba solo lo apendeado en el turno y la compactacion no
    disparaba nunca. Con el fallback (historial entero a chars/4) el bucle
    compacta de verdad: aparece el mensaje-resumen en el historial."""
    # Este test fija el camino VIEJO (resumen por compactacion.compactar). Con la
    # memoria larga encendida (default desde 2026-09-04) el bucle reconstruye el
    # contexto antes de que ese camino dispare: se apaga aqui a proposito.
    monkeypatch.setenv("COGNIA_MEMORIA_LARGA", "0")
    from cognia.agent import loop as loop_mod
    from cognia.agent.chat_client import (RespuestaChat, ToolCall,
                                          mensaje_assistant, mensaje_tool)
    from cognia.agent.tool_schemas import args_legacy

    grande = "linea util del fichero\n" * 500     # ~11.5 KB por lectura

    def _run_tool(name, args, ctx):
        return "RESULTADO leer_archivo: " + grande

    def _tc(i):
        return ToolCall(id="t%d" % i, nombre="leer_archivo",
                        argumentos={"path": "f%d.py" % i},
                        argumentos_crudos='{"path": "f%d.py"}' % i)

    # usage SIN prompt_tokens en todos los turnos (el sintoma del stream)
    rs = [RespuestaChat(texto="", finish_reason="tool_calls",
                        usage={"completion_tokens": 5}, tool_calls=[_tc(i)])
          for i in range(3)]
    rs.append(RespuestaChat(texto="Listo.", finish_reason="stop",
                            usage={"completion_tokens": 5}))
    it = iter(rs)
    mensajes_vistos = []

    def _completar(mensajes, tools=None, **kw):
        mensajes_vistos.append(copy.deepcopy(mensajes))
        return next(it)

    schemas = [{"type": "function",
                "function": {"name": "leer_archivo", "parameters": {}}}]
    # n_ctx 8000, no 4000: con 4000 el primer turno no tenia zona vieja (la
    # unica lectura era el ultimo mensaje, siempre retenido), el fallback
    # truncado la mordia a 248 chars y la zona vieja del segundo turno eran
    # 385 chars — menos que el resumen con secciones + ruta del volcado
    # (2026-08-24), que por diseno NO se aplica si no libera. Con 8000 la
    # compactacion dispara al tercer turno sobre ~23 KB de zona vieja real.
    perfil = {"nombre": "razonador_nativo", "modelo": "m.gguf",
              "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": 8000,
              "temperature": 1.0, "top_p": 1.0, "max_tokens": 4096}
    out = loop_mod.bucle_nativo(
        "resume los ficheros", "sos el agente", _completar, schemas,
        args_legacy, mensaje_assistant, mensaje_tool, _run_tool, {},
        perfil, ["TAREA: resume"], [], lambda *a, **k: None, 8)
    assert out["ok"]
    # el ULTIMO prompt enviado ya viajo compactado: un solo resumen, con el
    # system y el objetivo intactos delante
    final = mensajes_vistos[-1]
    marcas = [m for m in final
              if str(m.get("content") or "").startswith(comp._MARCA)]
    assert len(marcas) == 1
    assert final[0]["role"] == "system"
    assert final[1]["content"].startswith("TAREA: resume")


# ── Regresion 2026-08-23 (revision adversarial): el resumen decia OK a rojos ──

def test_linea_tool_no_declara_ok_una_ejecucion_fallida():
    """El veredicto de _linea_tool solo miraba \bERROR\b en la linea 1:
    un 'RESULTADO ejecutar (exit 1): FFF' salia '-> OK' y, tras compactar, el
    modelo planificaba el resto de la tarea creyendo que la suite roja paso
    (el bug P0-1 reintroducido en la capa del resumen)."""
    assert "-> FALLO" in comp._linea_tool(
        "ejecutar", "pytest -q", "RESULTADO ejecutar (exit 1): FFF 3 failed")
    assert "-> FALLO" in comp._linea_tool(
        "ejecutar", "python x.py", "RESULTADO ejecutar ERROR: revento")
    # exit 0 sigue siendo OK, y un contenido sano tambien.
    assert "-> OK" in comp._linea_tool(
        "ejecutar", "ls", "RESULTADO ejecutar (exit 0): 643")


def test_linea_tool_ve_el_fallo_a_traves_del_spill_de_f3(tmp_path, monkeypatch):
    """Para una salida spilleada la linea 1 es '[SALIDA GRANDE...': el
    marcador ERROR que ahora propaga la cabecera del offload tiene que llegar
    al veredicto del resumen."""
    from cognia.harness import offloading as off
    monkeypatch.setenv("COGNIA_OFFLOAD_DIR", str(tmp_path / "offload"))
    fallo = ("RESULTADO ejecutar ERROR (exit 1): Traceback...\n"
             + "\n".join(f"  traza {i}" for i in range(300)))
    spilleado = off.formatear_observacion(fallo, "ejecutar", "python x.py")
    assert spilleado.startswith("[SALIDA GRANDE")
    linea = comp._linea_tool("ejecutar", "python x.py", spilleado)
    assert "-> FALLO" in linea
    assert "spill res:" in linea


def test_bucle_trunca_cuando_el_resumen_no_libera_nada():
    """Regresion (revision adversarial 2026-08-23): en el presupuesto
    proactivo, compactar() devolviendo 0 con aplicada=False ('nada viejo que
    fundir': la retencion conserva el ultimo mensaje y el anti-huerfanos
    arrastra a su assistant) se trataba como ATENDIDO y el bucle se saltaba
    _recortar_mensajes — el prompt viajaba por encima de n_ctx y el server
    hacia context-shift en silencio (fallo clase A3). Con el fix, 0 cae al
    truncado igual que None (el camino de retry ya lo hacia con su `or 0`)."""
    from cognia.agent import loop as loop_mod
    from cognia.agent.chat_client import (RespuestaChat, ToolCall,
                                          mensaje_assistant, mensaje_tool)
    from cognia.agent.tool_schemas import args_legacy

    # UNA sola tool con salida gigante: todo lo "viejo" queda dentro de la
    # retencion y compactar() no tiene nada que fundir, pero est >> 0.8*n_ctx.
    gigante = "x" * 96000

    def _run_tool(name, args, ctx):
        return "RESULTADO leer_archivo: " + gigante

    tc = ToolCall(id="t1", nombre="leer_archivo",
                  argumentos={"path": "f.py"},
                  argumentos_crudos='{"path": "f.py"}')
    rs = iter([
        RespuestaChat(texto="", finish_reason="tool_calls",
                      usage={"completion_tokens": 5}, tool_calls=[tc]),
        RespuestaChat(texto="Listo.", finish_reason="stop",
                      usage={"completion_tokens": 5}),
    ])
    mensajes_vistos = []

    def _completar(mensajes, tools=None, **kw):
        mensajes_vistos.append(copy.deepcopy(mensajes))
        return next(rs)

    schemas = [{"type": "function",
                "function": {"name": "leer_archivo", "parameters": {}}}]
    perfil = {"nombre": "razonador_nativo", "modelo": "m.gguf",
              "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": 16384,
              "temperature": 1.0, "top_p": 1.0, "max_tokens": 4096}
    out = loop_mod.bucle_nativo(
        "lee f.py", "sos el agente", _completar, schemas,
        args_legacy, mensaje_assistant, mensaje_tool, _run_tool, {},
        perfil, ["TAREA: lee"], [], lambda *a, **k: None, 8)
    assert out["ok"]
    final = mensajes_vistos[-1]
    # sin resumen (no habia nada que fundir)...
    assert not any(str(m.get("content") or "").startswith(comp._MARCA)
                   for m in final)
    # ...pero el turno tool YA NO viaja gigante: lo recorto el fallback.
    tools_en_prompt = [m for m in final if m.get("role") == "tool"]
    assert tools_en_prompt, "el historial perdio el turno tool"
    assert all("recortado por presupuesto de contexto" in m["content"]
               for m in tools_en_prompt)
    assert all(len(m["content"]) < 1000 for m in tools_en_prompt)
