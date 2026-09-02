# -*- coding: utf-8 -*-
"""
tests/test_pasos_ilimitados_scratch_render.py
=============================================
Pedido del dueno (2026-09-02), tres piezas:

1. PASOS ILIMITADOS: con ctx['_pasos_ilimitados'] el bucle nativo NO cierra
   por presupuesto, techo, gobernador, guardia de bucle ni racha de fallos;
   cierra cuando el MODELO responde sin tool calls. Sin el flag, el
   comportamiento de siempre (contrafactual).
2. SCRATCHPAD por tarea: se abre dentro del workspace, se borra al cerrar
   (salvo conservar), lo escrito ahi no cuenta como entrega, y el primer user
   lleva la nota que le dice al modelo donde probar.
3. RENDERIZAR: captura aislada con Playwright y con Edge/Chrome headless;
   errores de consola reportados; fuentes .md/.js/.svg envueltas; fichero
   inexistente = error accionable, nunca vacio.

Cada test falla sin su fix.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cognia.agent import loop as loop_mod
from cognia.agent.chat_client import RespuestaChat, mensaje_assistant, mensaje_tool
from cognia.agent.tool_schemas import args_legacy, schemas_para


# ── andamio del bucle ─────────────────────────────────────────────────────────

class _TC:
    def __init__(self, nombre, argumentos, i):
        self.id = "c%d" % i
        self.nombre = nombre
        self.argumentos = argumentos
        self.argumentos_rotos = False
        self.argumentos_crudos = ""


def _perfil():
    return {"nombre": "razonador_nativo", "modelo": "qwen.gguf",
            "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": 16384,
            "temperature": 0.7, "top_p": 0.8, "reasoning_effort": "",
            "max_tokens": 4096}


def _correr(completar_fn, ctx, max_turns=3, run_tool=None, avisos=None):
    def _print(msg, *a, **k):
        if avisos is not None:
            avisos.append(str(msg))
    return loop_mod.bucle_nativo(
        "crea hola.txt", "sos el agente", completar_fn, schemas_para(),
        args_legacy, mensaje_assistant, mensaje_tool,
        run_tool or (lambda n, a, c: "RESULTADO %s: OK" % n),
        ctx, _perfil(), ["TAREA: crea hola.txt"], [], _print, max_turns)


def _modelo_que_tarda(n_pasos):
    """Un `completar` que lee un fichero DISTINTO en cada paso durante n_pasos
    y luego cierra con texto: simula un trabajo largo y legitimo. (leer_archivo
    y no listar: los args de listar se serializan siempre como '.', y eso es
    la misma llamada repetida para el guardia de bucle.)"""
    estado = {"i": 0}

    def _completar(mensajes, tools=None, **kw):
        estado["i"] += 1
        if estado["i"] <= n_pasos:
            return RespuestaChat(texto="", finish_reason="tool_calls",
                                 tool_calls=[_TC("leer_archivo", {"path": "d%d.txt" % estado["i"]},
                                                 estado["i"])])
        return RespuestaChat(texto="terminado", finish_reason="stop")
    return _completar, estado


@pytest.fixture(autouse=True)
def _sin_reloj(monkeypatch):
    monkeypatch.delenv("COGNIA_PARED_S", raising=False)
    monkeypatch.delenv("COGNIA_STREAM", raising=False)
    monkeypatch.setenv("COGNIA_HERMES", os.environ.get("COGNIA_HERMES", "1"))


# ── 1. pasos ilimitados ────────────────────────────────────────────────────────

def test_sin_el_flag_el_presupuesto_sigue_cortando():
    completar, estado = _modelo_que_tarda(30)
    r = _correr(completar, {}, max_turns=3)
    assert r["texto"] != "terminado"
    assert estado["i"] < 30


def test_con_pasos_ilimitados_el_bucle_llega_hasta_que_el_modelo_cierra():
    completar, estado = _modelo_que_tarda(30)
    r = _correr(completar, {"_pasos_ilimitados": True}, max_turns=3)
    assert r["texto"] == "terminado", r
    assert r["ok"] is True
    assert r["pasos"] >= 30


def test_con_pasos_ilimitados_la_racha_de_fallos_avisa_pero_no_corta():
    """Doce tools fallidas seguidas: sin el flag corta (racha doble); con el
    flag manda el ALTO y sigue hasta que el modelo cierra."""
    completar, estado = _modelo_que_tarda(12)
    avisos = []
    r = _correr(completar, {"_pasos_ilimitados": True}, max_turns=3,
                run_tool=lambda n, a, c: "ERROR: no existe", avisos=avisos)
    assert r["texto"] == "terminado", r
    assert any("seguidas fallaron" in a for a in avisos)
    avisos2 = []
    r2 = _correr(_modelo_que_tarda(12)[0], {}, max_turns=3,
                 run_tool=lambda n, a, c: "ERROR: no existe", avisos=avisos2)
    assert r2["texto"] != "terminado"


def test_con_pasos_ilimitados_repetir_la_misma_tool_avisa_pero_no_corta():
    estado = {"i": 0}

    def _completar(mensajes, tools=None, **kw):
        estado["i"] += 1
        if estado["i"] <= 7:      # 7 veces el MISMO par tool+args (5 bloqueos)
            return RespuestaChat(texto="", finish_reason="tool_calls",
                                 tool_calls=[_TC("listar", {"path": "x"}, estado["i"])])
        return RespuestaChat(texto="terminado", finish_reason="stop")
    avisos = []
    r = _correr(_completar, {"_pasos_ilimitados": True}, max_turns=3, avisos=avisos)
    assert r["texto"] == "terminado", r
    assert any("sigo (pasos ilimitados)" in a for a in avisos), avisos


def test_con_pasos_ilimitados_el_ciclo_degenerado_si_cierra():
    """Medido 2026-09-02: 60 apendices seguidos sobre c.txt con el aviso del
    guardia ignorado cada vez. Seis bloqueos SEGUIDOS ignorados cierran con
    motivo claro; eso no es 'el modelo piensa que termino', es girar."""
    estado = {"i": 0}

    def _completar(mensajes, tools=None, **kw):
        estado["i"] += 1
        if estado["i"] <= 40:
            return RespuestaChat(texto="", finish_reason="tool_calls",
                                 tool_calls=[_TC("listar", {"path": "x"}, estado["i"])])
        return RespuestaChat(texto="terminado", finish_reason="stop")
    avisos = []
    r = _correr(_completar, {"_pasos_ilimitados": True}, max_turns=3, avisos=avisos)
    assert r["texto"] != "terminado"
    assert estado["i"] < 40 and estado["i"] >= 8
    assert any("ciclo degenerado" in a for a in avisos), avisos


# ── 2. scratchpad ──────────────────────────────────────────────────────────────

def test_scratchpad_se_abre_dentro_del_workspace_y_se_borra_al_cerrar(tmp_path, monkeypatch):
    from cognia.agent import scratchpad as S
    monkeypatch.delenv("COGNIA_SCRATCHPAD_CONSERVAR", raising=False)
    ruta = S.abrir(raiz=tmp_path)
    assert ruta.is_dir() and ruta.parent.name == S.NOMBRE_DIR
    assert tmp_path in ruta.parents
    (ruta / "test_tmp.py").write_text("assert True\n", encoding="utf-8")
    assert S.es_del_scratch(ruta / "test_tmp.py", ruta)
    assert not S.es_del_scratch(tmp_path / "entrega.py", ruta)
    assert S.cerrar(ruta) is True
    assert not ruta.exists()
    assert not (tmp_path / S.NOMBRE_DIR).exists()      # la carpeta madre vacia tambien


def test_scratchpad_conservar_no_borra(tmp_path, monkeypatch):
    from cognia.agent import scratchpad as S
    monkeypatch.setenv("COGNIA_SCRATCHPAD_CONSERVAR", "1")
    ruta = S.abrir(raiz=tmp_path)
    assert S.cerrar(ruta) is False
    assert ruta.exists()


def test_scratchpad_nunca_borra_fuera_de_su_carpeta(tmp_path):
    from cognia.agent import scratchpad as S
    ajena = tmp_path / "proyecto"
    ajena.mkdir()
    (ajena / "a.txt").write_text("x", encoding="utf-8")
    assert S.cerrar(ajena, conservar_=False) is False
    assert (ajena / "a.txt").exists()


def test_la_nota_del_scratchpad_dice_donde_probar_y_que_se_borra(tmp_path, monkeypatch):
    from cognia.agent import scratchpad as S
    monkeypatch.setattr(S, "raiz_workspace", lambda: tmp_path)
    ruta = S.abrir(raiz=tmp_path)
    try:
        nota = S.nota_para_el_modelo(ruta)
        assert "SCRATCHPAD" in nota and S.NOMBRE_DIR in nota
        assert "BORRA" in nota and "entregables" in nota.lower()
    finally:
        S.cerrar(ruta, conservar_=False)


def test_lo_escrito_en_el_scratch_no_entra_en_la_entrega(tmp_path, monkeypatch):
    """El bucle anexa la ENTREGA con lo escrito; lo del scratchpad no es
    producto y no puede salir como 'no existe en disco' tras borrarse."""
    from cognia.agent import scratchpad as S
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COGNIA_ENTREGA", "1")
    scr = S.abrir(raiz=tmp_path)
    estado = {"i": 0}

    def _completar(mensajes, tools=None, **kw):
        estado["i"] += 1
        if estado["i"] == 1:
            return RespuestaChat(texto="", finish_reason="tool_calls", tool_calls=[
                _TC("escribir_archivo", {"path": str(scr / "test_x.py"), "contenido": "assert 1\n"}, 1),
                _TC("escribir_archivo", {"path": "entrega.py", "contenido": "print(1)\n"}, 2)])
        return RespuestaChat(texto="listo", finish_reason="stop")

    def _run_tool(n, a, c):
        from cognia.agent.tools import run_tool
        return run_tool(n, a, c)
    r = _correr(_completar, {"_scratchpad": str(scr), "_pasos_ilimitados": True},
                max_turns=4, run_tool=_run_tool)
    S.cerrar(scr, conservar_=False)
    assert "entrega.py" in r["texto"]
    assert "test_x.py" not in r["texto"], r["texto"]


# ── 3. renderizar ─────────────────────────────────────────────────────────────

PAGINA = ("<!doctype html><html><head><title>Prueba</title></head><body>"
          "<h1>Hola render</h1><canvas id='c' width='200' height='100'></canvas>"
          "<script>const x=document.getElementById('c').getContext('2d');"
          "x.fillStyle='red';x.fillRect(10,10,80,50);noExiste();</script></body></html>")


def _backends():
    from cognia.agent import renderizador as R
    out = []
    if R.playwright_disponible():
        out.append("playwright")
    if R.navegador_sistema()[0]:
        out.append(R.navegador_sistema()[0])
    return out


@pytest.mark.parametrize("backend", _backends() or ["ninguno"])
def test_renderizar_captura_y_reporta_el_error_de_js(tmp_path, backend):
    from cognia.agent import renderizador as R
    if backend == "ninguno":
        pytest.skip("sin Playwright ni Edge/Chrome en esta maquina")
    p = tmp_path / "p.html"
    p.write_text(PAGINA, encoding="utf-8")
    r = R.renderizar(str(p), salida=str(tmp_path / "cap.png"), backend=backend,
                     espera_ms=300)
    assert Path(r["png"]).is_file() and Path(r["png"]).stat().st_size > 500
    assert any("noExiste" in e for e in r["errores"]), r
    txt = R.texto_resultado(r)
    assert "captura en" in txt and "error(es) de JS" in txt
    if backend == "playwright":
        assert "Hola render" in txt and "canvas 200x100" in txt


def test_renderizar_envuelve_md_js_y_svg(tmp_path):
    from cognia.agent import renderizador as R
    for nombre, cuerpo, tec in (("n.md", "# Titulo\n\n- uno\n", "markdown"),
                                ("j.js", "document.body.innerHTML+='<b>js</b>'", "js"),
                                ("s.svg", "<svg xmlns='http://www.w3.org/2000/svg' width='50' height='50'><rect width='50' height='50' fill='blue'/></svg>", "svg")):
        f = tmp_path / nombre
        f.write_text(cuerpo, encoding="utf-8")
        uri, tecnologia, _ = R.preparar_fuente(str(f), tmp_path)
        assert tecnologia == tec
        assert uri.startswith("file:")


def test_renderizar_fuente_inexistente_es_error_accionable(tmp_path):
    from cognia.agent import renderizador as R
    with pytest.raises(ValueError) as exc:
        R.renderizar(str(tmp_path / "nada.html"))
    assert "no existe" in str(exc.value)
    from cognia.agent.tools import run_tool
    out = run_tool("renderizar", str(tmp_path / "nada.html"), {})
    assert out.startswith("RESULTADO renderizar ERROR") and "no existe" in out


def test_renderizar_esta_en_el_catalogo_core_y_parte_sus_args():
    from cognia.agent.tools import CORE_TOOLS, TOOLS
    from cognia.agent import renderizador as R
    assert "renderizar" in CORE_TOOLS and "renderizar" in TOOLS
    fuente, o = R.partir_args("index.html | ancho=800 | espera=2000 | salida=x.png")
    assert fuente == "index.html"
    assert o == {"ancho": "800", "espera": "2000", "salida": "x.png"}


# ── puertas del CLI ─────────────────────────────────────────────────────────────

def test_las_puertas_nuevas_estan_en_el_catalogo_y_clasificadas():
    from cognia import cli_visibilidad as v
    from cognia import cli
    for cmd in ("/pasos", "/scratchpad", "/renderizar"):
        assert cmd in cli._CMD_DESCRIPTIONS
        assert cmd in (v.NUCLEO | v.AVANZADO | v.LABORATORIO)
    assert "/pasos" in v.NUCLEO and "/scratchpad" in v.NUCLEO


def test_pasos_ilimitados_es_el_default_y_la_env_manda(monkeypatch):
    from cognia import cli
    monkeypatch.delenv("COGNIA_PASOS_ILIMITADOS", raising=False)
    monkeypatch.setattr(cli, "_load_config", lambda: {})
    assert cli._pasos_ilimitados() is True
    monkeypatch.setattr(cli, "_load_config", lambda: {"pasos_ilimitados": "off"})
    assert cli._pasos_ilimitados() is False
    monkeypatch.setenv("COGNIA_PASOS_ILIMITADOS", "1")
    assert cli._pasos_ilimitados() is True


def test_la_guia_de_una_skill_capturada_no_lleva_el_protocolo_de_texto():
    from cognia.agent.skills import neutralizar_acciones
    g = ("Skill candidata 'x': hacer cosas\n8. ACCION: leer_archivo kanban.js\n"
         "9. ACCION: ejecutar node --check app.js && echo OK\nACCION: listar\nprosa normal")
    out = neutralizar_acciones(g)
    assert "ACCION:" not in out
    assert "8. usar la tool leer_archivo con: kanban.js" in out
    assert "usar la tool ejecutar con: node --check app.js && echo OK" in out
    assert "usar la tool listar" in out and "prosa normal" in out
    assert neutralizar_acciones("") == "" and neutralizar_acciones("sin nada") == "sin nada"


def test_renderizar_acepta_file_uri_y_no_fotografia_la_pagina_de_error(tmp_path):
    from cognia.agent import renderizador as R
    p = tmp_path / "p.html"
    p.write_text("<!doctype html><title>T</title><p>hola</p>", encoding="utf-8")
    uri, tec, _ = R.preparar_fuente(p.resolve().as_uri(), tmp_path)   # file:///C:/...
    assert tec == "html" and uri == p.resolve().as_uri()
    if not (R.playwright_disponible() or R.navegador_sistema()[0]):
        pytest.skip("sin navegador")
    with pytest.raises(ValueError) as exc:
        R.renderizar("http://127.0.0.1:1/nada", salida=str(tmp_path / "x.png"), espera_ms=100)
    assert "no se pudo conectar" in str(exc.value) and "ejecutar_fondo" in str(exc.value)
    assert not (tmp_path / "x.png").exists()
