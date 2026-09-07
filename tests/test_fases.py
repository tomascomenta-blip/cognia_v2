# -*- coding: utf-8 -*-
"""
tests/test_fases.py — la OBRA POR FASES (cognia/fases, 2026-09-07) sin modelo:
estado durable, Definicion de Hecho (JSON del modelo / automatica), git como
memoria de versiones con REVERT real, el juez (regresion, mejora, no tocar,
sin mejora neta), el verificador con tools reales sobre un producto web
sintetico, el pipeline entero con un ejecutor falso (una iteracion buena se
acepta y commitea; una que rompe la pagina se rechaza y se revierte), las
tools fases_* por run_tool y las puertas del CLI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cognia.fases import dod as D
from cognia.fases import estado as E
from cognia.fases import juez as J
from cognia.fases import pipeline as P
from cognia.fases import versiones as G

pytestmark = pytest.mark.skipif(not G.disponible(), reason="sin git en el PATH")


# ── estado ───────────────────────────────────────────────────────────────────

def test_estado_roundtrip_issues_versiones(tmp_path):
    est = E.nuevo(tmp_path, "un juego snake en canvas", P.IDS)
    assert E.existe(tmp_path) and est["fase_actual"] == "planificar"
    it = E.issue_agregar(est, "p1", "la serpiente atraviesa paredes", pasos="ir a la derecha 50 veces")
    assert it["id"] == "#001" and it["prioridad"] == "P1"
    E.issue_agregar(est, "zz", "titulo", )  # prioridad invalida -> P3
    assert E.conteo_issues(est) == {"P0": 0, "P1": 1, "P2": 0, "P3": 1, "P4": 0}
    assert E.issue_cerrar(est, "1", causa="bounds", fix="clamp")["estado"] == "cerrado"
    E.version_registrar(est, "abc123", "prototipo", 1, {"req_ok": 1, "req_total": 3}, "aceptar", ["primera"])
    E.version_registrar(est, "abc123", "completar", 1, {"req_ok": 0}, "rechazar", ["REGRESION"])
    E.estable_agregar(est, "motor.py", "pasa todo")
    E.guardar(est)
    est2 = E.cargar(tmp_path)
    assert est2["issues"][0]["estado"] == "cerrado" and E.ultima_aceptada(est2)["n"] == 1
    md = E.render_md(est2)
    assert "NO TOCAR" in md and "motor.py" in md and "#002" in md
    assert (E.dir_fases(tmp_path) / "ESTADO_PROYECTO.md").exists()


# ── DoD ──────────────────────────────────────────────────────────────────────

_JSON_DOD = """Aqui va el plan.
```json
{"tipo_producto": "web", "entrypoint": "index.html", "arquitectura": "un fichero",
 "funcionales": [{"texto": "muestra un saludo", "tipo": "guion", "args": "index.html | guion=assert texto contiene \\"Hola\\""},
                 "el boton suma",
                 {"texto": "el boton resta", "tipo": "guion", "args": "index.html | vars=window.n | guion=clic #r; assert window.n==-1"}],
 "visuales": [{"texto": "sin solapes", "tipo": "manual"}],
 "calidad": [{"texto": "sin errores de consola", "tipo": "probar", "args": "index.html", "espera": "sin errores de consola"}]}
```"""


def test_dod_parsea_el_json_del_modelo_y_la_automatica():
    d = D.parsear_json(_JSON_DOD)
    assert d is not None and d["_meta"]["entrypoint"] == "index.html"
    assert [i["id"] for i in d["funcionales"]] == ["F1", "F2", "F3"]
    assert d["funcionales"][1]["verif"]["tipo"] == "manual"
    assert D.resumen(d)["manuales"] == 2
    assert D.parsear_json("no hay json aqui {}") is None
    assert D.parsear_json('{"otra": 1}') is None
    auto = D.automatica("1. El jugador se mueve con flechas.\n2. Hay marcador.\n3. Game over al chocar.", "web", "index.html")
    assert len(auto["funcionales"]) >= 3 and auto["calidad"][0]["verif"]["args"] == "index.html"
    assert D.marcar(auto, "v1", True, "captura")["ok"] is True
    assert D.buscar(auto, "Z9") is None


# ── git como memoria de versiones ────────────────────────────────────────────

def test_versiones_snapshot_y_revert_real(tmp_path):
    ws = tmp_path
    (ws / "previo.txt").write_text("del dueno", encoding="utf-8")
    r = G.asegurar_repo(ws)
    assert r["ok"] and r["creado"] and ".cognia_fases/" in (ws / ".gitignore").read_text(encoding="utf-8")
    base = G.snapshot(ws, "fases: v0 base")
    assert base["ok"] and base["commit"]
    (ws / "app.py").write_text("print(1)\n", encoding="utf-8")
    v1 = G.snapshot(ws, "fases: v1")
    assert v1["ok"] and v1["commit"] != base["commit"]
    assert G.snapshot(ws, "nada")["sin_cambios"] is True
    # iteracion que rompe: modifica app.py, crea nuevo.py; y un untracked previo del dueno
    untracked_previos = G.untracked(ws)
    (ws / "app.py").write_text("print(1/0)\n", encoding="utf-8")
    (ws / "nuevo.py").write_text("x", encoding="utf-8")
    assert set(G.ficheros_cambiados(ws, v1["commit"])) == {"app.py", "nuevo.py"}
    rv = G.revertir(ws, v1["commit"], untracked_previos)
    assert rv["ok"] and rv["borrados"] == 1
    assert (ws / "app.py").read_text(encoding="utf-8") == "print(1)\n"
    assert not (ws / "nuevo.py").exists() and (ws / "previo.txt").exists()
    assert G.ficheros_cambiados(ws, v1["commit"]) == []


# ── juez ─────────────────────────────────────────────────────────────────────

def test_juez_decide_por_regresion_mejora_y_no_tocar():
    prev = {"req_ok": 3, "req_total": 5, "tests_ok": 4, "tests_total": 4, "consola_errores": 0, "tracebacks": 0, "req_fallan": 1}
    assert J.juzgar(prev, dict(prev), [], [], "completar")["decision"] == "sin_cambios"
    assert J.juzgar(None, dict(prev), ["a.py"], [], "prototipo")["decision"] == "aceptar"
    peor = dict(prev, req_ok=2, req_fallan=2)
    v = J.juzgar(prev, peor, ["a.py"], [], "completar")
    assert v["decision"] == "rechazar" and any("req_ok 3 -> 2" in m for m in v["motivos"])
    mejor = dict(prev, req_ok=4, req_fallan=0)
    assert J.juzgar(prev, mejor, ["a.py"], [], "completar")["decision"] == "aceptar"
    igual = dict(prev)
    v = J.juzgar(prev, igual, ["a.py"], [], "completar")
    assert v["decision"] == "rechazar" and "sin mejora neta" in v["motivos"][0]
    v = J.juzgar(prev, mejor, ["motor/fisica.py"], [{"que": "motor/"}], "completar")
    assert v["decision"] == "rechazar" and "NO TOCAR" in v["motivos"][0]
    assert J.juzgar(prev, mejor, ["motor/fisica.py"], [{"que": "motor/"}], "regresion")["decision"] == "aceptar"
    v = J.juzgar(prev, dict(prev, consola_errores=2), ["a.py"], [], "pulido")
    assert v["decision"] == "rechazar"
    assert J.juzgar(prev, igual, ["a.py"], [], "pulido", cerrados_en_iteracion=1)["decision"] == "aceptar"
    assert J.puntuacion(prev, {"P0": 1, "P1": 0, "P2": 0, "P3": 0, "P4": 0})["robustez"] == 60
    # regresion POR requisito aunque el conteo no cambie (F4 cae, F5 sube)
    p2 = dict(prev, ok_ids=["F1", "F2", "F4"])
    n2 = dict(prev, ok_ids=["F1", "F2", "F5"])
    v = J.juzgar(p2, n2, ["a.py"], [], "robustez", cerrados_en_iteracion=3)
    assert v["decision"] == "rechazar" and "F4" in v["motivos"][0]


# ── verificador con tools reales sobre un producto web ───────────────────────

PAGINA_OK = """<!doctype html><html><head><title>Saludo</title></head><body>
<h1 id="t">Hola mundo</h1><button id="b">+1</button><span id="n">0</span>
<script>window.n=0;document.getElementById('b').onclick=()=>{window.n++;document.getElementById('n').textContent=window.n;};</script>
</body></html>"""
PAGINA_ROTA = PAGINA_OK.replace("window.n=0;", "window.n=0;noExiste();")


def _navegador():
    from cognia.agent import renderizador as rz
    return rz.playwright_disponible()


def _dod_web():
    return D.normalizar({
        "funcionales": [{"texto": "muestra Hola", "tipo": "guion", "args": "index.html | guion=assert texto contiene \"Hola\""},
                        {"texto": "el boton suma", "tipo": "guion", "args": "index.html | vars=window.n | guion=clic #b; assert window.n==1"},
                        {"texto": "algo manual", "tipo": "manual"}],
        "visuales": [],
        "calidad": [{"texto": "sin errores de consola", "tipo": "probar", "args": "index.html", "espera": "sin errores de consola"}]})


@pytest.mark.skipif(not _navegador(), reason="sin Playwright")
def test_verificador_mide_una_pagina_buena_y_una_rota(tmp_path):
    from cognia.fases import verificador as V
    ws = tmp_path
    (ws / "index.html").write_text(PAGINA_OK, encoding="utf-8")
    est = E.nuevo(ws, "saludo", P.IDS)
    est["dod"] = _dod_web()
    est["tipo_producto"], est["entrypoint"] = "web", "index.html"
    m = V.verificar(est, ["index.html"], version_n=1)
    assert m["req_ok"] == 3 and m["req_fallan"] == 0 and m["req_sin"] == 1, m["detalle"]
    assert m["consola_errores"] == 0 and m["capturas"], m
    (ws / "index.html").write_text(PAGINA_ROTA, encoding="utf-8")
    m2 = V.verificar(est, ["index.html"], version_n=2)
    assert m2["req_fallan"] >= 1 and m2["consola_errores"] >= 1, m2["detalle"]


# ── pipeline entero con ejecutor falso ───────────────────────────────────────

class _Ejecutor:
    """Simula al agente: planifica con JSON, construye bien, luego rompe la pagina."""

    def __init__(self, ws):
        self.ws = Path(ws)
        self.llamadas = []

    def __call__(self, prompt, rol, allowed):
        self.llamadas.append((rol, allowed))
        if rol == "planificador":
            assert allowed and "escribir_archivo" not in allowed
            return _JSON_DOD
        if rol == "constructor" and "PROTOTIPO" in prompt:
            (self.ws / "index.html").write_text(PAGINA_OK, encoding="utf-8")
            return "HIPOTESIS: x\nCAMBIOS: index.html\nRESULTADO: renderiza"
        if rol == "constructor" and "COMPLETAR" in prompt:
            (self.ws / "index.html").write_text(PAGINA_ROTA, encoding="utf-8")
            (self.ws / "basura.txt").write_text("x", encoding="utf-8")
            return "rompi la pagina sin querer"
        return "nada"


@pytest.mark.skipif(not _navegador(), reason="sin Playwright")
def test_pipeline_acepta_la_buena_y_revierte_la_rota(tmp_path, monkeypatch):
    ws = tmp_path
    (ws / "README.md").write_text("del dueno", encoding="utf-8")
    ej = _Ejecutor(ws)
    lineas = []
    obra = P.Obra(ws, encargo="pagina con saludo y boton", ejecutor=ej, imprimir=lineas.append,
                  iteraciones=1, fases_ids=["planificar", "prototipo", "completar", "release"])
    inf = obra.correr()
    est = E.cargar(ws)
    assert est["tipo_producto"] == "web" and est["entrypoint"] == "index.html"
    assert D.total(est["dod"]) == 5
    decisiones = [v["decision"] for v in est["versiones"]]
    assert decisiones[0] == "aceptar", lineas
    assert "rechazar" in decisiones, lineas
    # el revert devolvio la pagina buena y borro la basura de la iteracion rota
    assert (ws / "index.html").read_text(encoding="utf-8") == PAGINA_OK
    assert not (ws / "basura.txt").exists() and (ws / "README.md").exists()
    # el prototipo no cubre "resta" (queda incompleto pero con version aceptada)
    assert est["fases"]["prototipo"]["estado"] == "incompleta"
    assert est["fases"]["completar"]["estado"] == "incompleta"
    assert any("fases: v1" in l for l in G.log_versiones(ws))
    assert "INFORME FINAL" in inf["texto"] and "NO LISTO" in inf["estado"]
    assert [r for r, _a in ej.llamadas] == ["planificador", "constructor", "constructor"]


def test_pipeline_sin_dod_del_modelo_usa_la_automatica_y_se_detiene_sin_producto(tmp_path):
    ej = lambda prompt, rol, allowed: "no se"      # noqa: E731
    lineas = []
    obra = P.Obra(tmp_path, encargo="script python que suma dos numeros por consola", ejecutor=ej,
                  imprimir=lineas.append, iteraciones=1, fases_ids=["planificar", "prototipo", "completar"])
    inf = obra.correr()
    est = E.cargar(tmp_path)
    assert est["tipo_producto"] == "python_cli" and D.total(est["dod"]) >= 3
    assert est["versiones"] == [] and "SIN PRODUCTO" in inf["estado"]
    assert any("no produjo ninguna version aceptada" in l for l in lineas)


def test_criterios_de_salida_no_dependen_de_opinion(tmp_path):
    est = E.nuevo(tmp_path, "x", P.IDS)
    est["dod"] = _dod_web()
    f = P.fase_por_id("completar")
    assert P.criterio_salida(f, est, {"tracebacks": 0})[0] is False
    for it in est["dod"]["funcionales"]:
        it["ok"] = True
    est["dod"]["calidad"][0]["ok"] = True
    assert P.criterio_salida(f, est, {"tracebacks": 0})[0] is True
    E.issue_agregar(est, "P1", "grave")
    assert P.criterio_salida(P.fase_por_id("robustez"), est, {"tracebacks": 0})[0] is False
    assert P.criterio_salida(P.fase_por_id("redteam"), est, {"tracebacks": 0})[0] is False
    assert P.adivinar_tipo("un juego en pygame") == "python_gui"
    assert P.adivinar_tipo("pagina web con canvas") == "web"


# ── tools fases_* por run_tool ───────────────────────────────────────────────

def test_tools_fases_escriben_en_el_estado(tmp_path, monkeypatch):
    from cognia.agent.tools import run_tool
    monkeypatch.setenv("COGNIA_FASES_WORKSPACE", str(tmp_path))
    assert "no hay una obra" in run_tool("fases_estado", "", {})
    est = E.nuevo(tmp_path, "juego", P.IDS)
    est["dod"] = _dod_web()
    E.guardar(est)
    out = run_tool("fases_issue", "agregar P2 | la pelota se pega | pasos=jugar 10s | esperado=rebota | actual=se queda", {})
    assert "#001 P2 registrado" in out
    assert "#001 P2" in run_tool("fases_issue", "lista", {})
    assert "cerrado" in run_tool("fases_issue", "cerrar #001 | causa=signo | fix=abs()", {})
    assert "sin issues" in run_tool("fases_issue", "lista", {})
    assert "registrada" in run_tool("fases_hipotesis", "el rebote falla por el signo | plan=1. cambiar signo | esperado=rebota", {})
    out = run_tool("fases_dod", "marcar F1 ok | evidencia=x", {})
    assert "ERROR" in out and "verificador" in out          # F1 es ejecutable
    assert "ERROR" in run_tool("fases_dod", "marcar F3 ok", {})   # sin evidencia no
    assert "F3 marcado OK" in run_tool("fases_dod", "marcar F3 ok | evidencia=captura v1", {})
    assert "NO TOCAR" in run_tool("fases_estable", "motor.js | motivo=pasa todo", {})
    est = E.cargar(tmp_path)
    assert est["hipotesis"]["texto"].startswith("el rebote") and est["estables"][0]["que"] == "motor.js"
    assert D.buscar(est["dod"], "F3")["ok"] is True
    out = run_tool("fases_dod", "definir " + _JSON_DOD, {})
    assert "guardada: 5 requisitos" in out


def test_puertas_del_cli():
    import cognia.cli as cli
    from cognia.harness import ayuda
    from cognia import cli_visibilidad as vis
    assert "/fases" in cli._CMD_DESCRIPTIONS and "/fases" in cli._CMD_DETAILS
    assert ayuda.clasificar("/fases", cli._CMD_DESCRIPTIONS["/fases"]) == "Horizonte largo (TX)"
    assert ayuda.desbordes(cli._CMD_DESCRIPTIONS, ayuda.TOPE_CATEGORIA) == []
    assert "/fases" in (vis.AVANZADO | vis.LABORATORIO)
    assert "fases_iteraciones" in cli._CONFIG_DEFAULTS
    from cognia.agent import catalogo_nodos as cn
    assert cn.categoria_de("fases_issue") == "horizonte"


def test_renderizador_no_pierde_la_comilla_final_del_guion():
    from cognia.agent import renderizador as rz
    _f, o = rz.partir_args("index.html | vars=window.a | guion=espera 100; assert typeof window.juego.tick==='function'")
    assert o["guion"].endswith("==='function'")
    _f, o = rz.partir_args('index.html | guion="tecla a"')
    assert o["guion"] == "tecla a"
