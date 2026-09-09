# -*- coding: utf-8 -*-
"""
tests/test_mesa.py
==================
El SEGUNDO PUESTO / MESA (cognia/agent/mesa.py + mesa_tools.py, 2026-09-08).
Sin escritorio real: se doblan las funciones de escritorio_propio y se prueba
la logica del puntero virtual (clamp, ventana bajo el punto, clic por UIA vs
mensajes), invocar por etiqueta, teclado, el parseo del atajo, el estado
persistente y el registro de las 8 tools. El e2e real (lanzar tkinter en la
mesa, teclear, componer, pantallita) va con COGNIA_E2E_MESA=1.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from cognia.agent import mesa as M
from cognia.agent import escritorio_propio as EP

# Funciones REALES de escritorio_propio capturadas ANTES de que la fixture las
# doble: el e2e (COGNIA_E2E_MESA=1) las restaura para usar el escritorio de verdad.
_EP_REAL = {n: getattr(EP, n) for n in
            ("ventanas_en_escritorio", "ventanas_visibles", "ventana_viva", "titulo_ventana", "rect_ventana")}
_PANTALLA_TAM_REAL = M.pantalla_tam


@pytest.fixture(autouse=True)
def _estado_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "_ESTADO", tmp_path / "mesa_estado.json")
    monkeypatch.setattr(M, "_PUNTERO", {"x": None, "y": None})
    monkeypatch.setattr(M, "_ACTIVA", {"hwnd": 0})
    monkeypatch.setattr(M, "pantalla_tam", lambda: (1000, 800, 0, 0))
    # sin ventanas por defecto
    monkeypatch.setattr(EP, "ventanas_en_escritorio", lambda: [])
    monkeypatch.setattr(EP, "ventanas_visibles", lambda: [])
    monkeypatch.setattr(EP, "ventana_viva", lambda h: True)
    monkeypatch.setattr(EP, "titulo_ventana", lambda h: "T%d" % h)
    yield


def _con_ventanas(monkeypatch, ventanas):
    """ventanas: [(hwnd, (x,y,w,h))] en orden z (frente->fondo)."""
    rects = {h: r for h, r in ventanas}
    monkeypatch.setattr(EP, "ventanas_en_escritorio", lambda: [(h, 0, "T%d" % h) for h, _ in ventanas])
    monkeypatch.setattr(EP, "ventanas_visibles", lambda: [(h, 0, "T%d" % h) for h, _ in ventanas])
    monkeypatch.setattr(EP, "rect_ventana", lambda h: rects[h])
    return rects


# ── puntero: clamp y persistencia ────────────────────────────────────────────

def test_mover_clampa_y_persiste(monkeypatch):
    r = M.mover(5000, -30, animar=False)
    assert r == {"x": 999, "y": 0}
    est = json.loads(M._ESTADO.read_text(encoding="utf-8"))
    assert est["puntero"] == {"x": 999, "y": 0}


def test_puntero_por_defecto_centro(monkeypatch):
    assert M.puntero() == (500, 400)


# ── ventana bajo el punto: la mas al frente ──────────────────────────────────

def test_ventana_en_punto_toma_la_de_encima(monkeypatch):
    # dos ventanas solapadas; la primera en z (frente) gana
    _con_ventanas(monkeypatch, [(11, (0, 0, 200, 200)), (22, (0, 0, 300, 300))])
    assert M.ventana_en_punto(50, 50) == 11
    # punto solo dentro de la de atras
    assert M.ventana_en_punto(250, 250) == 22
    # fuera de todas
    assert M.ventana_en_punto(900, 900) == 0


# ── clic: UIA Invoke si hay patron, si no cae a mensajes ─────────────────────

def test_clic_usa_uia_invoke(monkeypatch):
    _con_ventanas(monkeypatch, [(11, (0, 0, 400, 400))])
    llamado = {"n": 0}

    class _Ctrl:
        Name = "Aceptar"
        ControlTypeName = "ButtonControl"
    monkeypatch.setattr(M, "_uia_en_punto", lambda h, x, y: (_Ctrl(), (lambda: llamado.__setitem__("n", llamado["n"] + 1)), "UIA.Invoke"))
    r = M.clic(100, 100)
    assert r["metodo"] == "UIA.Invoke"
    assert r["control"] == "Aceptar"
    assert llamado["n"] == 1


def test_clic_cae_a_mensajes_sin_uia(monkeypatch):
    _con_ventanas(monkeypatch, [(11, (10, 10, 400, 400))])
    monkeypatch.setattr(M, "_uia_en_punto", lambda h, x, y: (None, None, ""))
    monkeypatch.setattr(EP, "rect_cliente", lambda h: (10, 10, 380, 380))
    vistos = {}
    monkeypatch.setattr(EP, "clic", lambda h, x, y, boton="izquierdo", doble=False: vistos.update(h=h, x=x, y=y) or {"control": "Edit"})
    r = M.clic(100, 120)
    assert r["metodo"] == "mensaje"
    assert vistos == {"h": 11, "x": 90, "y": 110}   # coords cliente (pantalla - origen)


def test_clic_sin_ventana_da_error(monkeypatch):
    r = M.clic(500, 500)
    assert "error" in r and "ninguna ventana" in r["error"]


# ── invocar por etiqueta ─────────────────────────────────────────────────────

def test_invocar_busca_y_clica(monkeypatch):
    _con_ventanas(monkeypatch, [(11, (0, 0, 400, 400))])
    monkeypatch.setattr(EP, "buscar_control", lambda h, t: (30, 40, "Button", "Guardar como"))
    monkeypatch.setattr(EP, "rect_cliente", lambda h: (5, 5, 390, 390))
    monkeypatch.setattr(M, "_uia_en_punto", lambda h, x, y: (None, None, ""))
    monkeypatch.setattr(EP, "clic", lambda h, x, y, boton="izquierdo", doble=False: {"control": "Button"})
    r = M.invocar("Guardar")
    assert r["ok"] and r["encontrado"] == "Guardar como"


def test_invocar_sin_ventana(monkeypatch):
    r = M.invocar("Aceptar")
    # parentesis a proposito: sin ellos `A and B or C` pasaba con ok=True
    assert r["ok"] is False and ("vac" in r["error"].lower() or "no hay" in r["error"].lower())


def test_invocar_reintenta_cuando_el_arbol_uia_vuelve_vacio(monkeypatch):
    # la Calculadora devuelve el arbol vacio unos ms tras cada Invoke
    _con_ventanas(monkeypatch, [(11, (0, 0, 400, 400))])
    monkeypatch.setattr(M, "INVOCAR_ESPERA_S", 0.0)
    monkeypatch.setattr(M, "INVOCAR_ASIENTO_S", 0.0)
    intentos = {"n": 0}

    def buscar(h, t):
        intentos["n"] += 1
        return None if intentos["n"] < 3 else (30, 40, "Button", "Seis")
    monkeypatch.setattr(EP, "buscar_control", buscar)
    monkeypatch.setattr(EP, "rect_cliente", lambda h: (0, 0, 400, 400))
    monkeypatch.setattr(M, "clic", lambda x, y, boton="izquierdo", doble=False, hwnd=0: {"x": x, "y": y, "metodo": "UIA.Invoke"})
    r = M.invocar("Seis")
    assert r["ok"] and r["encontrado"] == "Seis" and intentos["n"] == 3


def test_mejor_ventana_elige_la_corewindow_con_controles(monkeypatch):
    # UWP: el marco (11) tiene 1 nodo; la CoreWindow (22), mismo titulo, tiene 5
    monkeypatch.setattr(EP, "ventanas_en_escritorio", lambda: [(11, 100, "Calculadora"), (22, 200, "Calculadora"), (33, 300, "Otra")])
    monkeypatch.setattr(EP, "titulo_ventana", lambda h: {11: "Calculadora", 22: "Calculadora", 33: "Otra"}[h])
    monkeypatch.setattr(EP, "pid_de", lambda h: h * 10)
    monkeypatch.setattr(EP, "arbol_uia", lambda h, profundidad=6, maximo=40: [0] if h == 11 else [0, 1, 2, 3, 4])
    despertadas = []
    from cognia.agent import plm
    monkeypatch.setattr(plm, "mantener_despierta", lambda pid: despertadas.append(pid) or {"ok": True, "paquete": "Calc_1.0"})
    r = M.mejor_ventana(11, segundos=1.0)
    assert r["ok"] and r["hwnd"] == 22 and r["nodos"] == 5 and r["paquete"] == "Calc_1.0"
    assert sorted(despertadas) == [110, 220]          # solo las del mismo titulo


def test_invocar_salta_al_hermano_con_controles(monkeypatch):
    _con_ventanas(monkeypatch, [(11, (0, 0, 400, 400)), (22, (0, 0, 400, 400))])
    monkeypatch.setattr(M, "INVOCAR_ESPERA_S", 0.0)
    monkeypatch.setattr(M, "INVOCAR_ASIENTO_S", 0.0)
    monkeypatch.setattr(EP, "buscar_control", lambda h, t: (30, 40, "Button", "Siete") if h == 22 else None)
    monkeypatch.setattr(M, "mejor_ventana", lambda h, segundos=2.0: {"ok": True, "hwnd": 22, "nodos": 5, "paquete": ""})
    monkeypatch.setattr(EP, "rect_cliente", lambda h: (0, 0, 400, 400))
    monkeypatch.setattr(M, "clic", lambda x, y, boton="izquierdo", doble=False, hwnd=0: {"x": x, "y": y, "metodo": "UIA.Invoke", "hwnd": hwnd})
    M.fijar_activa(11)
    r = M.invocar("Siete")
    assert r["ok"] and r["hwnd"] == 22 and M.activa() == 22


def test_arbol_estable_reintenta(monkeypatch):
    monkeypatch.setattr(M, "INVOCAR_ESPERA_S", 0.0)
    vueltas = {"n": 0}

    def arbol(h, profundidad=8, maximo=200):
        vueltas["n"] += 1
        return [(0, "Window", "Calc", (0, 0, 1, 1), "")] if vueltas["n"] < 2 else \
               [(0, "Window", "Calc", (0, 0, 1, 1), ""), (1, "Text", "La pantalla muestra 42", (0, 0, 1, 1), "")]
    monkeypatch.setattr(EP, "arbol_uia", arbol)
    a = M.arbol_estable(11)
    assert len(a) == 2 and vueltas["n"] == 2


def test_invocar_no_dice_ok_si_el_clic_fallo(monkeypatch):
    _con_ventanas(monkeypatch, [(11, (0, 0, 400, 400))])
    monkeypatch.setattr(EP, "buscar_control", lambda h, t: (30, 40, "Button", "Guardar"))
    monkeypatch.setattr(EP, "rect_cliente", lambda h: (5, 5, 390, 390))
    monkeypatch.setattr(M, "clic", lambda x, y, boton="izquierdo", doble=False, hwnd=0: {"x": x, "y": y, "error": "boom"})
    r = M.invocar("Guardar")
    assert r["ok"] is False and r["error"] == "boom"


def test_clic_con_hwnd_explicito_no_se_va_a_la_de_encima(monkeypatch):
    # la 11 tapa a la 22; invocar pide clicar en la 22 (la activa)
    _con_ventanas(monkeypatch, [(11, (0, 0, 200, 200)), (22, (0, 0, 300, 300))])
    monkeypatch.setattr(M, "_uia_en_punto", lambda h, x, y: (None, None, ""))
    monkeypatch.setattr(EP, "rect_cliente", lambda h: (0, 0, 300, 300))
    vistos = []
    monkeypatch.setattr(EP, "clic", lambda h, x, y, boton="izquierdo", doble=False: vistos.append(h) or {"control": "x"})
    M.clic(50, 50, hwnd=22)
    assert vistos == [22]
    # un hwnd que NO es de la mesa se ignora y se resuelve por el punto
    M.clic(50, 50, hwnd=999)
    assert vistos == [22, 11]


def test_puntero_se_lee_del_json_en_otro_proceso(monkeypatch):
    # la pantallita es otro proceso: su _PUNTERO esta a None y debe leer el JSON
    M._ESTADO.write_text(json.dumps({"puntero": {"x": 123, "y": 456}}), encoding="utf-8")
    assert M.puntero() == (123, 456)
    M.mover(10, 20, animar=False)
    assert M.puntero() == (10, 20)


def test_partir_args_con_clave_al_inicio():
    from cognia.agent import pruebas_comun as PC
    # tools.armar_args produce ' tecla=intro' cuando la tool no lleva posicional
    assert PC.partir_args(" tecla=intro", ("tecla", "atajo", "veces")) == ("", {"tecla": "intro"})
    assert PC.partir_args("hola mundo", ("tecla",)) == ("hola mundo", {})
    assert PC.partir_args("texto | tecla=intro", ("tecla",)) == ("texto", {"tecla": "intro"})


def _tools_registradas():
    from cognia.agent import mesa_tools as MT
    fns = {}

    def tool(name, usage, desc="", params=None, danger=False, timeout_s=60):
        def deco(fn):
            fns[name] = fn
            return fn
        return deco
    MT.register(tool)
    return fns


def test_mesa_teclear_tecla_intro_no_escribe_literal(monkeypatch):
    fns = _tools_registradas()
    llamadas = []
    monkeypatch.setattr(M, "tecla", lambda nombre, veces=1: llamadas.append(("tecla", nombre, veces)) or {"ok": True, "hwnd": 1, "pulsaciones": veces})
    monkeypatch.setattr(M, "escribir", lambda texto: llamadas.append(("escribir", texto)) or {"ok": True, "hwnd": 1, "chars": len(texto)})
    out = fns["mesa_teclear"](" tecla=intro", {})
    assert llamadas == [("tecla", "intro", 1)], out
    # un texto normal con '=' de claves AJENAS no se parte
    llamadas.clear()
    fns["mesa_teclear"]("titulo=Informe fps=30", {})
    assert llamadas == [("escribir", "titulo=Informe fps=30")]


def test_mesa_ventanas_activar_rechaza_ventanas_del_dueno(monkeypatch):
    fns = _tools_registradas()
    _con_ventanas(monkeypatch, [(11, (0, 0, 100, 100))])
    out = fns["mesa_ventanas"]("activar 999", {})
    assert out.startswith("ERROR") and "mesa" in out
    assert "activa ahora hwnd 11" in fns["mesa_ventanas"]("activar 11", {})


# ── teclado y atajo ──────────────────────────────────────────────────────────

def test_escribir_requiere_activa(monkeypatch):
    assert M.escribir("hola")["ok"] is False


def test_atajo_parsea_modificadores(monkeypatch):
    _con_ventanas(monkeypatch, [(11, (0, 0, 400, 400))])
    posts = []
    monkeypatch.setattr(EP, "hwnd_con_foco", lambda h: h)
    monkeypatch.setattr(EP, "vk_de", lambda n: ({"ctrl": 0x11, "control": 0x11, "mayus": 0x10, "alt": 0x12, "s": 0x53}.get(n, 0), ""))
    monkeypatch.setattr(EP, "_post", lambda h, m, w, l: posts.append((m, w)))
    r = M.atajo("ctrl+s")
    assert r["ok"] is True
    # KEYDOWN Ctrl, KEYDOWN s, KEYUP s, KEYUP Ctrl — y NUNCA un WM_CHAR (0x0102):
    # con WM_CHAR la app escribia una "s" literal (revision adversarial 2026-09-08)
    assert posts == [(0x0100, 0x11), (0x0100, 0x53), (0x0101, 0x53), (0x0101, 0x11)]
    assert r["aviso"]  # avisa del limite de los modificadores por mensajes


# ── estado ───────────────────────────────────────────────────────────────────

def test_estado_forma(monkeypatch):
    monkeypatch.setattr(EP, "disponible", lambda: (True, ""))
    monkeypatch.setattr(EP, "config", lambda: {"nombre": "Cognia"})
    monkeypatch.setattr(EP, "activo", lambda: True)
    e = M.estado()
    assert e["disponible"] and e["escritorio"] == "Cognia"
    assert set(("puntero", "ventanas", "activa", "pantalla_abierta")).issubset(e)


# ── las 8 tools se registran ─────────────────────────────────────────────────

def test_registra_ocho_tools():
    from cognia.agent import mesa_tools as MT
    nombres = []

    def tool(name, usage, desc="", params=None, danger=False, timeout_s=60):
        def deco(fn):
            nombres.append(name)
            return fn
        return deco
    MT.register(tool)
    assert nombres == ["mesa_lanzar", "mesa_ver", "mesa_raton", "mesa_invocar",
                       "mesa_teclear", "mesa_ventanas", "mesa_pantalla", "mesa_estado"]


# ── e2e real opcional ────────────────────────────────────────────────────────

@pytest.mark.skipif(os.environ.get("COGNIA_E2E_MESA") != "1", reason="pon COGNIA_E2E_MESA=1 para el e2e real")
def test_e2e_mesa_real(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("solo Windows")
    # restaurar las funciones REALES del escritorio (la fixture autouse las dobla)
    for n, f in _EP_REAL.items():
        monkeypatch.setattr(EP, n, f)
    monkeypatch.setattr(M, "pantalla_tam", _PANTALLA_TAM_REAL)
    from cognia.agent import app_tools as AT
    app = tmp_path / "tkapp.py"
    app.write_text(
        "import tkinter as tk\n"
        "r=tk.Tk(); r.title('MESA_E2E'); r.geometry('500x260+160+160')\n"
        "e=tk.Entry(r,font=('Consolas',22)); e.pack(pady=20,fill='x'); e.focus_force()\n"
        "r.mainloop()\n", encoding="utf-8")
    app_id, a = AT.lanzar('python "%s"' % app, titulo="MESA_E2E", espera_ms=9000)
    try:
        M.fijar_activa(a["hwnd"])
        assert M.escribir("mesa e2e ok")["ok"]
        out = tmp_path / "mesa.png"
        r = M.componer(str(out), escala=1.0)
        assert r["ventanas"] >= 1 and out.exists()
    finally:
        EP.matar_arbol(a["pid"])
