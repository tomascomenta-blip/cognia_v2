# -*- coding: utf-8 -*-
"""
tests/test_taller.py
====================
El TALLER (cognia/agent/taller_tools.py, 2026-09-10): Blender con referencias
de internet y Godot. Sin Blender ni Godot ni red: se prueba el parseo, la
generacion del bpy de referencias/render, la creacion del proyecto Godot, el
detector de errores de Godot, el registro de las tools y el opt-in. El e2e real
(Blender en la mesa, ddgs, Godot headless) va con COGNIA_E2E_TALLER=1.
"""
from __future__ import annotations

import json
import os

import pytest

from cognia.agent import taller_tools as TT


@pytest.fixture(autouse=True)
def _aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(TT, "CARPETA", tmp_path / "taller")
    monkeypatch.setattr(TT, "ARRANQUE", tmp_path / "taller" / "arranque_blender.py")
    monkeypatch.setattr(TT, "_ESTADO", {"blender": {"app_id": "", "pid": 0, "hwnd": 0, "fichero": "",
                                                    "conectado": False, "error": ""},
                                        "godot": {"app_id": "", "pid": 0, "proyecto": "", "error": ""}})


# ---- opt-in ----------------------------------------------------------------

def test_encendido_env_manda(monkeypatch):
    monkeypatch.setenv("COGNIA_TALLER", "0")
    assert TT.encendido() is False
    monkeypatch.setenv("COGNIA_TALLER", "1")
    assert TT.encendido() is True


def test_encendido_por_defecto_sin_env(monkeypatch, tmp_path):
    monkeypatch.delenv("COGNIA_TALLER", raising=False)
    monkeypatch.setattr(TT, "_cfg", lambda: {})
    assert TT.encendido() is True
    monkeypatch.setattr(TT, "_cfg", lambda: {"taller_tools": False})
    assert TT.encendido() is False


# ---- registro de tools ------------------------------------------------------

def test_tools_registradas_y_con_flag():
    from cognia.agent.tools import TOOLS, flag_de_optin
    esperadas = {"blender_abrir", "blender_referencias", "blender_codigo", "blender_escena", "blender_ver",
                 "blender_guardar", "blender_exportar", "blender_cerrar", "godot_proyecto", "godot_verificar",
                 "godot_correr", "godot_abrir", "godot_cerrar", "taller_estado"}
    assert esperadas <= set(TOOLS)
    for t in esperadas:
        assert flag_de_optin(t) == "COGNIA_TALLER", t


def test_familia_taller_en_familias():
    from cognia.harness import familias
    assert "taller" in familias.FAMILIAS
    assert familias.FAMILIAS["taller"]["flag"] == "COGNIA_TALLER"


def test_taller_estado_no_revienta_sin_nada(monkeypatch):
    monkeypatch.setattr(TT, "blender_exe", lambda: "")
    monkeypatch.setattr(TT, "godot_exe", lambda consola=False: "")
    monkeypatch.setattr(TT, "puerto_abierto", lambda *a, **k: False)
    txt = TT.texto_estado()
    assert "NO ENCONTRADO" in txt and "socket 9876 cerrado" in txt


# ---- Blender sin Blender ----------------------------------------------------

def test_blender_abrir_sin_exe_dice_como_instalar(monkeypatch):
    monkeypatch.setattr(TT, "blender_exe", lambda: "")
    monkeypatch.setattr(TT, "puerto_abierto", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="blender.exe"):
        TT.blender_abrir()


def test_bl_sin_puerto_pide_abrir(monkeypatch):
    monkeypatch.setattr(TT, "puerto_abierto", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="blender_abrir"):
        TT._bl("print(1)")


def test_bl_quita_prefijo_del_servidor(monkeypatch):
    class Cli:
        def llamar(self, h, a, timeout=None):
            assert h == "execute_blender_code" and "print" in a["code"]
            return "Code executed successfully: hola\n"
    monkeypatch.setattr(TT, "puerto_abierto", lambda *a, **k: True)
    monkeypatch.setattr(TT, "_mcp", lambda: Cli())
    assert TT._bl("print('hola')") == "hola"
    assert TT._ESTADO["blender"]["conectado"] is True


def test_bl_json_saca_el_ultimo_json(monkeypatch):
    monkeypatch.setattr(TT, "_bl", lambda c, timeout=120: 'ruido\n{"ok": true, "n": 2}\n')
    assert TT._bl_json("x") == {"ok": True, "n": 2}


def test_bl_error_del_servidor_lanza(monkeypatch):
    class Cli:
        def llamar(self, h, a, timeout=None):
            return "ERROR de la herramienta 'execute_blender_code': NameError"
    monkeypatch.setattr(TT, "puerto_abierto", lambda *a, **k: True)
    monkeypatch.setattr(TT, "_mcp", lambda: Cli())
    with pytest.raises(RuntimeError, match="NameError"):
        TT._bl("x")


def test_arranque_escribe_script_con_addon(tmp_path):
    p = TT._escribir_arranque()
    src = p.read_text(encoding="utf-8")
    assert "blender_addon.py" in src and "register()" in src and "9876" in src
    compile(src, str(p), "exec")          # es Python valido


def test_codigo_referencias_es_python_valido_y_lleva_las_rutas():
    imgs = [{"ruta": r"C:\refs\frente_1.png", "angulo": "frente"},
            {"ruta": r"C:\refs\lado_1.jpg", "angulo": "lado"}]
    src = TT.codigo_referencias(imgs, tam=3.5)
    compile(src, "refs", "exec")
    assert "frente_1.png" in src and "lado_1.jpg" in src and "Referencias" in src and "3.5" in src
    # las poses de los 4 angulos que se buscan estan definidas
    for ang in TT.ANGULOS:
        assert ang in TT._POSES


def test_codigo_render_es_python_valido():
    src = TT._CODIGO_RENDER % {"angulo": "frente", "ruta": r"C:\x\r.png", "motor": "workbench"}
    compile(src, "render", "exec")
    assert "BLENDER_WORKBENCH" in src and "CogniaCam" in src


def test_ver_viewport_mueve_la_imagen(monkeypatch, tmp_path):
    origen = tmp_path / "shot.png"
    origen.write_bytes(b"\x89PNG fake")

    class Cli:
        def llamar(self, h, a, timeout=None):
            assert h == "get_viewport_screenshot"
            return "[imagen image/png guardada en %s]" % origen
    monkeypatch.setattr(TT, "_mcp", lambda: Cli())
    r = TT.ver({"_scratchpad": str(tmp_path / "out")}, angulo="viewport")
    assert not origen.exists() and os.path.exists(r["ruta"]) and r["angulo"] == "viewport"


def test_exportar_rechaza_formato_raro(tmp_path):
    with pytest.raises(ValueError, match="no soportado"):
        TT.exportar(str(tmp_path / "x.xyz"))


def test_buscar_referencias_baja_y_apunta_fuentes(monkeypatch, tmp_path):
    # sin red: buscador y descarga doblados; se comprueba el flujo y fuentes.json
    monkeypatch.setattr(TT, "_buscar_imagenes", lambda q, n: [{"url": "http://x/%s.png" % q.replace(" ", "_"),
                                                                "titulo": q, "fuente": "t"}])

    def _bajar(url, destino, minimo_px=200):
        p = destino.with_suffix(".png")
        p.write_bytes(b"png")
        return p
    monkeypatch.setattr(TT, "_bajar_imagen", _bajar)
    r = TT.buscar_referencias("Pikachu", n_por_angulo=1, carpeta=tmp_path / "refs")
    assert len(r["imagenes"]) == 4 and not r["fallos"]
    assert {i["angulo"] for i in r["imagenes"]} == set(TT.ANGULOS)
    fuentes = json.loads((tmp_path / "refs" / "fuentes.json").read_text(encoding="utf-8"))
    assert fuentes["personaje"] == "Pikachu" and len(fuentes["imagenes"]) == 4


def test_buscar_referencias_reporta_angulo_sin_imagen(monkeypatch, tmp_path):
    monkeypatch.setattr(TT, "_buscar_imagenes", lambda q, n: [])
    r = TT.buscar_referencias("Nadie", n_por_angulo=1, angulos=("frente",), carpeta=tmp_path / "r")
    assert r["imagenes"] == [] and r["fallos"] and "frente" in r["fallos"][0]


# ---- Godot sin Godot --------------------------------------------------------

def test_crear_proyecto_2d_y_3d(tmp_path):
    r = TT.crear_proyecto(str(tmp_path / "j2d"), tipo="2d", nombre="Juego")
    assert (tmp_path / "j2d" / "project.godot").is_file()
    assert 'config/name="Juego"' in (tmp_path / "j2d" / "project.godot").read_text(encoding="utf-8")
    assert "Node2D" in (tmp_path / "j2d" / "main.tscn").read_text(encoding="utf-8")
    r3 = TT.crear_proyecto(str(tmp_path / "j3d"), tipo="3d")
    assert r3["tipo"] == "3d" and "Camera3D" in (tmp_path / "j3d" / "main.tscn").read_text(encoding="utf-8")
    # repetir no pisa nada
    r2 = TT.crear_proyecto(str(tmp_path / "j2d"))
    assert r2["existia"] is True


def test_nombre_pelado_va_al_workspace_al_crear(tmp_path):
    ctx = {"workspace": str(tmp_path)}
    r = TT.crear_proyecto("mi_juego", ctx=ctx)
    assert r["ruta"] == str(tmp_path / "mi_juego")
    # y al buscar, lo encuentra por el workspace
    assert TT._ruta_proyecto("mi_juego", ctx=ctx) == tmp_path / "mi_juego"


def test_nombre_pelado_sin_ctx_workspace_va_al_workspace_del_agente(tmp_path, monkeypatch):
    """Regresion del primer e2e con modelo (2026-09-10): el agente real NO pone
    ctx["workspace"]; el proyecto iba a ~/.cognia/taller y el modelo escribia
    main.gd en el workspace (dos mitades). Un nombre pelado sigue bases_relativas."""
    monkeypatch.setattr(TT.PC, "bases_relativas", lambda: [tmp_path / "ws"])
    (tmp_path / "ws").mkdir()
    r = TT.crear_proyecto("pong", ctx={})
    assert r["ruta"] == str(tmp_path / "ws" / "pong")
    assert TT._ruta_proyecto("pong", ctx=None) == tmp_path / "ws" / "pong"


def test_ruta_proyecto_sin_project_godot_avisa(tmp_path):
    with pytest.raises(ValueError, match="godot_proyecto"):
        TT._ruta_proyecto(str(tmp_path / "nada"))


def test_errores_de_godot_con_linea():
    salida = ("Godot Engine v4.7\nSCRIPT ERROR: Parse Error: Identifier \"x\" not declared in the current scope.\n"
              "   at: GDScript::reload (res://roto.gd:3)\nMain listo\nERROR: Failed to load script \"res://roto.gd\"\n")
    errs = TT._errores_de(salida)
    assert len(errs) == 2 and "res://roto.gd:3" in errs[0] and errs[1].startswith("ERROR")
    assert TT._errores_de("todo bien\nMain listo\n") == []


def test_verificar_usa_check_only_por_script(monkeypatch, tmp_path):
    TT.crear_proyecto(str(tmp_path / "p"))
    (tmp_path / "p" / "otro.gd").write_text("extends Node\n", encoding="utf-8")
    llamadas = []

    def _run(args, cwd, timeout):
        llamadas.append(args)
        if "--check-only" in args and "res://otro.gd" in args:
            return 1, "SCRIPT ERROR: Parse Error: boom\n   at: GDScript::reload (res://otro.gd:1)\n", 0.1, False
        return 0, "ok\n", 0.1, False
    monkeypatch.setattr(TT, "_godot_run", _run)
    r = TT.verificar(str(tmp_path / "p"))
    assert r["scripts"] == 2 and r["errores"] == 1
    assert r["por_script"]["res://main.gd"] == [] and "otro.gd:1" in r["por_script"]["res://otro.gd"][0]
    assert any("--quit-after" in a for a in llamadas)


def test_correr_headless_devuelve_salida_y_errores(monkeypatch, tmp_path):
    TT.crear_proyecto(str(tmp_path / "p"))
    monkeypatch.setattr(TT, "_godot_run", lambda args, cwd, timeout: (0, "Main listo\n", 1.2, False))
    r = TT.correr(str(tmp_path / "p"), segundos=2)
    assert r["modo"] == "headless" and r["exit"] == 0 and r["errores"] == [] and "Main listo" in r["salida"]


def test_run_tool_godot_proyecto_por_registry(tmp_path):
    from cognia.agent.tools import run_tool
    out = run_tool("godot_proyecto", "juego_x | tipo=2d | nombre=Equis", {"workspace": str(tmp_path)})
    assert out.startswith("RESULTADO godot_proyecto: creado") and (tmp_path / "juego_x" / "main.gd").is_file()


# ---- e2e real (opt-in) ------------------------------------------------------

@pytest.mark.skipif(os.environ.get("COGNIA_E2E_TALLER") != "1", reason="e2e real: COGNIA_E2E_TALLER=1")
def test_e2e_godot_real(tmp_path):
    TT.crear_proyecto(str(tmp_path / "real"), tipo="3d")
    r = TT.verificar(str(tmp_path / "real"))
    assert r["errores"] == 0, r
    r = TT.correr(str(tmp_path / "real"), segundos=2)
    assert "Main listo" in r["salida"] and not r["errores"], r


@pytest.mark.skipif(os.environ.get("COGNIA_E2E_TALLER") != "1", reason="e2e real: COGNIA_E2E_TALLER=1")
def test_e2e_blender_real(tmp_path, monkeypatch):
    monkeypatch.setattr(TT, "CARPETA", tmp_path / "taller")
    monkeypatch.setattr(TT, "ARRANQUE", tmp_path / "taller" / "arranque_blender.py")
    r = TT.blender_abrir(ctx={"workspace": str(tmp_path)})
    assert r["conectado"]
    try:
        assert "Blender" in TT._bl("import bpy; print('Blender', bpy.app.version_string)")
        v = TT.ver({"_scratchpad": str(tmp_path)}, angulo="frente")
        assert os.path.getsize(v["ruta"]) > 1000
        g = TT.guardar(str(tmp_path / "e2e.blend"))
        assert os.path.exists(g["ruta"])
    finally:
        TT.cerrar_blender(guardar_antes=False)
