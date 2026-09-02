# -*- coding: utf-8 -*-
"""
tests/test_autopsia_tankio_20260902.py
======================================
Autopsia de la sesion Tank.io del 2026-09-02 (14:33 -> 16:57). Cinco fallos
del CLI, cada uno con su test que falla sin el fix:

1. `renderizar tankio.html` -> "no existe" x4: la tool resolvia la ruta
   relativa contra el cwd del proceso, no contra el workspace de la tarea
   (sus hermanas leer/escribir_archivo si usan _workspace()).
2. El 400 "request (65835 tokens) exceeds the available context size (65536)":
   los schemas de las 73 tools (~25 KB, ~6.400 tokens) viajan en cada
   peticion y ningun estimado los contaba.
3. El rescate NEGADO de un escribir_archivo cortado (el fichero en disco ya
   era mas grande) se anunciaba como "el arnes rescato y ESCRIBIO en disco":
   contradiccion que mandaba al modelo a repetir la escritura entera.
4. "las 3 variantes mencionadas anteriormente" / "Continúa con las mejoras
   pendientes" no casaban con las palabras de continuidad -> el CONTEXTO
   PREVIO no se inyectaba (y encima se guardaba recortado a 100 chars).
5. "Continua con las mejoras pendientes del juego de tanques, completando..."
   (40+ palabras) tras un turno de agente iba al CHAT, que no ejecuta nada:
   dos turnos seguidos sin respuesta.
"""
from __future__ import annotations

import json

import pytest

from cognia.agent import loop as loop_mod
from cognia.agent.chat_client import RespuestaChat, mensaje_assistant, mensaje_tool
from cognia.agent.tool_schemas import args_legacy, schemas_para


# ── 1. renderizar resuelve RELATIVO AL WORKSPACE ─────────────────────────────

def _backends():
    from cognia.agent import renderizador as R
    out = []
    if R.playwright_disponible():
        out.append("playwright")
    if R.navegador_sistema()[0]:
        out.append(R.navegador_sistema()[0])
    return out


def test_renderizar_resuelve_la_ruta_relativa_contra_el_workspace(tmp_path, monkeypatch):
    from cognia.agent import renderizador as R
    import cognia.agents.workers.dev_tools as dev_tools
    ws = tmp_path / "ws"
    otro = tmp_path / "otro_cwd"
    ws.mkdir()
    otro.mkdir()
    (ws / "tankio.html").write_text("<html><body>tank</body></html>", encoding="utf-8")
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(ws))
    monkeypatch.chdir(otro)                       # el cwd NO es el workspace
    uri, tec, _ = R.preparar_fuente("tankio.html", tmp_path)
    assert tec == "html" and uri == (ws / "tankio.html").resolve().as_uri()
    # una ruta relativa que si esta en el cwd (el dueno a mano) sigue valiendo
    (otro / "manual.html").write_text("<p>x</p>", encoding="utf-8")
    uri2, _, _ = R.preparar_fuente("manual.html", tmp_path)
    assert uri2 == (otro / "manual.html").resolve().as_uri()


def test_partir_args_acepta_clave_valor_con_espacio_y_con_pipe():
    """LA CAUSA REAL: armar_args produce 'tankio.html espera=2000' (espacio,
    no pipe) y partir_args solo entendia el pipe -> la 'fuente' era el string
    entero y la tool decia "no existe: tankio.html espera=2000"."""
    from cognia.agent.renderizador import partir_args
    from cognia.agent.tool_schemas import args_legacy
    assert partir_args("tankio.html espera=2000") == ("tankio.html", {"espera": "2000"})
    assert partir_args("a.html ancho=800 alto=600") == ("a.html", {"ancho": "800", "alto": "600"})
    assert partir_args("a.html | ancho=800 | alto=600") == ("a.html", {"ancho": "800", "alto": "600"})
    assert partir_args("a.html | ancho=800 salida=cap.png") == (
        "a.html", {"ancho": "800", "salida": "cap.png"})
    assert partir_args("mi pagina.html") == ("mi pagina.html", {})
    assert partir_args("http://127.0.0.1:8000/?ancho=3") == ("http://127.0.0.1:8000/?ancho=3", {})
    # el puente JSON -> string que usa el bucle nativo, de punta a punta
    s = args_legacy("renderizar", {"fuente": "tankio.html", "espera": 2000, "ancho": 900})
    assert partir_args(s) == ("tankio.html", {"espera": "2000", "ancho": "900"}), s


def test_renderizar_con_parametro_opcional_por_la_tool_ya_no_dice_no_existe(tmp_path, monkeypatch):
    from cognia.agent.tools import run_tool
    from cognia.agent.tool_schemas import args_legacy
    import cognia.agents.workers.dev_tools as dev_tools
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tankio.html").write_text("<html><body>tank</body></html>", encoding="utf-8")
    args = args_legacy("renderizar", {"fuente": "tankio.html", "espera": 50})
    out = run_tool("renderizar", args, {"_scratchpad": str(tmp_path / "scr")})
    assert "no existe" not in out, out
    if not _backends():
        pytest.skip("sin Playwright ni Edge/Chrome en esta maquina")
    assert "captura en" in out, out


def test_renderizar_por_la_tool_con_cwd_distinto_al_workspace(tmp_path, monkeypatch):
    """La reproduccion EXACTA del fallo del dueno, por la tool registrada."""
    from cognia.agent.tools import run_tool
    import cognia.agents.workers.dev_tools as dev_tools
    ws = tmp_path / "Tank.io"
    ws.mkdir()
    (ws / "tankio.html").write_text("<html><body>tank</body></html>", encoding="utf-8")
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(ws))
    monkeypatch.chdir(tmp_path)
    if not _backends():
        pytest.skip("sin Playwright ni Edge/Chrome en esta maquina")
    out = run_tool("renderizar", "tankio.html | espera=50", {"_scratchpad": str(tmp_path / "scr")})
    assert "no existe" not in out and "captura en" in out, out


def test_renderizar_inexistente_dice_donde_busco(tmp_path, monkeypatch):
    from cognia.agent import renderizador as R
    import cognia.agents.workers.dev_tools as dev_tools
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(ws))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError) as exc:
        R.preparar_fuente("nada.html", tmp_path)
    msg = str(exc.value)
    assert "no existe: nada.html" in msg and str(ws) in msg and str(tmp_path) in msg


def test_renderizar_salida_relativa_va_al_scratch_no_al_cwd(tmp_path, monkeypatch):
    from cognia.agent import renderizador as R
    import cognia.agents.workers.dev_tools as dev_tools
    ws, scr, otro = tmp_path / "ws", tmp_path / "scr", tmp_path / "otro"
    ws.mkdir()
    scr.mkdir()
    otro.mkdir()
    (ws / "p.html").write_text("<p>hola</p>", encoding="utf-8")
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(ws))
    monkeypatch.chdir(otro)
    if not _backends():
        pytest.skip("sin Playwright ni Edge/Chrome en esta maquina")
    r = R.renderizar("p.html", salida="cap.png", scratch=str(scr), espera_ms=50)
    assert r["png"] == str(scr / "cap.png") and (scr / "cap.png").exists()
    assert not (otro / "cap.png").exists()


# ── arnes minimo del bucle nativo (copiado de test_contexto_ventana_nunca_none) ──

class _TC:
    def __init__(self, i, nombre="leer_archivo", args=None):
        self.id = "c%d" % i
        self.nombre = nombre
        self.argumentos = args or {"path": "f%d.txt" % i}
        self.argumentos_rotos = False
        self.argumentos_crudos = ""


def _perfil(n_ctx):
    return {"nombre": "razonador_nativo", "modelo": "qwen.gguf",
            "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": n_ctx,
            "temperature": 0.7, "top_p": 0.8, "reasoning_effort": "",
            "max_tokens": 8192}


def _prompt_de(mensajes):
    return sum(len(str(m.get("content") or "")) + len(str(m.get("reasoning_content") or ""))
               + sum(len(str((tc.get("function") or {}).get("arguments") or ""))
                     for tc in (m.get("tool_calls") or []))
               for m in mensajes) // 4


def _correr(perfil, pasos_tool=12, razon_chars=12000, serie=None, avisos=None,
            completar_extra=None):
    est = {"i": 0}

    def completar(mensajes, tools=None, **kw):
        est["i"] += 1
        i = est["i"]
        p = _prompt_de(mensajes)
        if serie is not None:
            serie.append(p)
        if completar_extra is not None:
            r = completar_extra(i, mensajes, p)
            if r is not None:
                return r
        if i > pasos_tool:
            return RespuestaChat(texto="terminado", finish_reason="stop",
                                 usage={"prompt_tokens": p, "completion_tokens": 50})
        return RespuestaChat(texto="", reasoning_content="razono " * (razon_chars // 7),
                             finish_reason="tool_calls", tool_calls=[_TC(i)],
                             usage={"prompt_tokens": p, "completion_tokens": 3000})

    def _print(msg, *a, **k):
        if avisos is not None:
            avisos.append(str(msg))
    return loop_mod.bucle_nativo(
        "t", "sos el agente", completar, schemas_para(), args_legacy,
        mensaje_assistant, mensaje_tool, lambda n, a, c: "RESULTADO %s: OK" % n,
        {"_pasos_ilimitados": True}, perfil, ["TAREA: t"], [], _print, 40)


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.delenv("COGNIA_STREAM", raising=False)
    monkeypatch.delenv("COGNIA_COMPACT", raising=False)
    monkeypatch.delenv("COGNIA_PARED_S", raising=False)


# ── 2. los schemas pesan ──────────────────────────────────────────────────────

def test_tokens_prompt_suma_el_peso_de_los_schemas(monkeypatch):
    monkeypatch.setitem(loop_mod._PESO_FIJO, "schemas", 0)
    assert loop_mod._tokens_prompt([{"role": "user", "content": "x" * 400}]) == 100
    peso = loop_mod._peso_schemas(schemas_para())
    assert peso > 3000, peso                         # 73 tools no son gratis
    monkeypatch.setitem(loop_mod._PESO_FIJO, "schemas", peso)
    assert loop_mod._tokens_prompt([{"role": "user", "content": "x" * 400}]) == 100 + peso
    assert loop_mod._peso_schemas(None) == 0 and loop_mod._peso_schemas([]) == 0


def test_el_bucle_fija_el_peso_de_los_schemas_al_arrancar(monkeypatch):
    monkeypatch.setitem(loop_mod._PESO_FIJO, "schemas", 0)
    _correr(_perfil(65536), pasos_tool=1)
    assert loop_mod._PESO_FIJO["schemas"] > 3000


def test_sin_usage_del_server_el_estimado_cuenta_los_schemas(monkeypatch):
    """Stream sin chunk de usage (prompt_tokens=0): el estimado de fallback
    incluye los schemas, asi que la compactacion dispara ANTES y el prompt
    (chars/4 de mensajes) se queda a mas de `peso` tokens de la ventana."""
    monkeypatch.setitem(loop_mod._PESO_FIJO, "schemas", 0)
    serie, avisos = [], []

    def sin_usage(i, mensajes, p):
        if i > 30:
            return RespuestaChat(texto="terminado", finish_reason="stop", usage={})
        return RespuestaChat(texto="", reasoning_content="razono " * 1700,
                             finish_reason="tool_calls", tool_calls=[_TC(i)], usage={})
    r = _correr(_perfil(32768), pasos_tool=30, serie=serie, avisos=avisos,
                completar_extra=sin_usage)
    assert r["texto"] == "terminado"
    peso = loop_mod._PESO_FIJO["schemas"]
    assert peso > 3000
    assert max(serie) + peso < 32768, (max(serie), peso)


# ── 3. el rescate NEGADO no se anuncia como rescate ──────────────────────────

def test_rescate_negado_manda_a_editar_y_el_turno_sigue(tmp_path, monkeypatch):
    import cognia.agents.workers.dev_tools as dev_tools
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "tankio.html").write_text("<html>" + "x" * 30000 + "</html>", encoding="utf-8")
    # varias lineas: el rescate recorta en el ultimo salto de linea y con una
    # sola linea larga no habria nada "seguro" que rescatar (ni que negar)
    entero = json.dumps({"ruta": "tankio.html",
                         "contenido": "<html>\n" + ("y" * 80 + "\n") * 20})
    crudo = entero[: int(len(entero) * 0.8)]

    class _Parcial:
        nombre = "escribir_archivo"
        argumentos_crudos = crudo
        argumentos_rotos = True
        argumentos = {}
        id = "p1"

    def cortado(i, mensajes, p):
        if any("NO se escribio nada" in str(m.get("content") or "") for m in mensajes):
            return RespuestaChat(texto="terminado", finish_reason="stop",
                                 usage={"prompt_tokens": p, "completion_tokens": 5})
        r = RespuestaChat(texto="", finish_reason="", usage={},
                          error="HTTP 500: Failed to parse tool call arguments as JSON: "
                                "missing closing quote")
        r.tool_calls_parciales = [_Parcial()]
        return r
    avisos = []
    r = _correr(_perfil(65536), pasos_tool=3, avisos=avisos, completar_extra=cortado)
    assert r["texto"] == "terminado", (r, avisos[-5:])
    assert any("no rescato el parcial" in a for a in avisos), avisos
    assert not any("fichero(s) del turno cortado" in a for a in avisos), avisos
    assert (tmp_path / "tankio.html").stat().st_size > 30000     # intacto


# ── 4. continuidad con acentos y referencias al pedido anterior ──────────────

def test_prior_context_continuidad_con_acentos_y_referencias_al_pedido_anterior():
    from cognia.agent.loop import prior_context_relevant
    assert prior_context_relevant(
        "crea las 3 variantes del tanque mencionadas anteriormente al llegar al nivel 5",
        "Modifica el juego de tanques para que el menu de mejora...")
    assert prior_context_relevant(
        "Continúa con las mejoras pendientes del juego de tanques", "lo que sea")
    assert prior_context_relevant("Si sigamos con el juego de tanques", "lo que sea")
    assert prior_context_relevant(
        "haz lo que termino faltando, la barra de vida y las evoluciones", "x")
    # lo que era irrelevante sigue siendolo
    assert not prior_context_relevant(
        "Ejecuta el comando de shell: echo cognia_ok",
        "Crea origen.txt con el texto copiame. Despues copialo a destino.txt.")


# ── 5. continuacion LARGA tras el agente es accion ───────────────────────────

@pytest.mark.parametrize("text", [
    "continua con las mejoras Continúa con las mejoras pendientes del juego de "
    "tanques, completando la barra de vida, el sistema de evoluciones y la "
    "experiencia. Devuelve el codigo actualizado y funcional.",
    "Continúa con las mejoras pendientes del juego de tanques",
    "sigue con la tarea de antes y termina el HUD",
    "termina de crear el juego de ark",
    "completa el juego Tank.io integrando la barra de vida y las evoluciones",
])
def test_continuacion_larga_tras_agente_es_accion(text):
    from cognia.agent.intent import detect
    r = detect(text, turno_previo_agente=True)
    assert r.needs_agent and r.reason == "continuacion:agente", (text, r)


def test_continuacion_larga_exige_objeto_de_tarea_y_turno_de_agente():
    from cognia.agent.intent import detect
    # sin turno de agente detras esta regla no aplica (lo decide el enrutador)
    r = detect("Continúa con las mejoras pendientes del juego de tanques")
    assert r.reason != "continuacion:agente"
    # una pregunta no es una orden aunque arranque con el verbo
    assert not detect("sigue con el mismo fallo el boton de guardar?",
                      turno_previo_agente=True).needs_agent
    # el test viejo sigue en pie: 'sigue siendo raro...' es charla
    assert not detect("sigue siendo raro que el color del boton no combine con nada",
                      turno_previo_agente=True).needs_agent
