# -*- coding: utf-8 -*-
"""Regresion del paquete WP2 (obra "nivel SOTA", 2026-08-09): tools del agente.

- leer_archivo: offset/limit (default 2000 lineas), aviso de continuacion con
  el offset siguiente, y EXENTO de aci_trim (el doble truncado 4000->1650
  hacia que el modelo editara con SEARCH/REPLACE texto que jamas vio —
  evidencia baseline 2026-08-09).
- ejecutar: conserva cabeza+COLA (el traceback vive al final) y acepta
  '| timeout=N'.
- editar_archivo: devuelve mini-diff del cambio aplicado; SEARCH ambiguo es
  error accionable.
- borrar_archivo: nueva, confinada al workspace.
- catalogo core (~12) + mensaje uniforme DESHABILITADA para familias opt-in
  sin disparar record_wanted_tool.
- catalogo_schemas/armar_args: registry consumible para tool-calling nativo.

Cada test falla sin su fix (verificados contra el codigo previo).
"""
import os

import pytest

import cognia.agents.workers.dev_tools as dev_tools
from cognia.agent import tools as T


def _ctx(**over):
    c = {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}
    c.update(over)
    return c


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


# ── leer_archivo: offset/limit + sin doble truncado ────────────────────────

def test_leer_archivo_default_2000_lineas(workspace):
    f = workspace / "muchas.txt"
    f.write_text("\n".join(f"linea {i}" for i in range(1, 2501)), encoding="utf-8")
    out = T.run_tool("leer_archivo", str(f), _ctx())
    assert "linea 1\n" in out and "linea 2000" in out
    assert "linea 2001" not in out
    # aviso de continuacion estilo OpenCode: dice el offset con el que seguir
    assert "TRUNCADO" in out and "offset=2001" in out and "2500" in out


def test_leer_archivo_offset_y_limit(workspace):
    f = workspace / "m.txt"
    f.write_text("\n".join(f"linea {i}" for i in range(1, 101)), encoding="utf-8")
    out = T.run_tool("leer_archivo", f"{f} offset=50 limit=3", _ctx())
    assert "linea 50" in out and "linea 52" in out
    assert "linea 49" not in out and "linea 53\n" not in out
    assert "offset=53" in out          # el puntero apunta a la siguiente


def test_leer_archivo_acepta_forma_con_pipe(workspace):
    # run_tool directo (sin auto_fix) puede recibir 'path | offset=N'
    f = workspace / "p.txt"
    f.write_text("\n".join(f"l{i}" for i in range(1, 11)), encoding="utf-8")
    out = T.run_tool("leer_archivo", f"{f} | offset=9", _ctx())
    assert "l9" in out and "l8\n" not in out


def test_leer_archivo_offset_fuera_de_rango(workspace):
    f = workspace / "x.txt"
    f.write_text("una\n", encoding="utf-8")
    out = T.run_tool("leer_archivo", f"{f} offset=99", _ctx())
    assert "ERROR" in out and "1 lineas" in out


def test_leer_archivo_no_pasa_por_aci_trim(workspace, monkeypatch):
    # EL fix del doble truncado: un archivo de 3000 chars entraba entero por
    # leer_archivo (cap 4000) y aci_trim lo recortaba a ~1650 con un hueco en
    # el medio — el modelo editaba texto que no vio. Ahora leer_archivo esta
    # en ACI_EXENTAS y el contenido llega INTEGRO al loop.
    f = workspace / "grande.py"
    contenido = "\n".join(f"def funcion_{i}(): pass" for i in range(150))
    f.write_text(contenido, encoding="utf-8")            # ~3.5k chars
    out = T.run_tool("leer_archivo", str(f), _ctx())
    assert "chars omitidos" not in out                   # sin marca de aci_trim
    assert "def funcion_0" in out and "def funcion_149" in out


def test_leer_archivo_linea_kilometrica_se_corta(workspace):
    f = workspace / "mini.json"
    f.write_text("x" * 5000, encoding="utf-8")           # 1 linea de 5000
    out = T.run_tool("leer_archivo", str(f), _ctx())
    assert "linea cortada" in out and "TRUNCADO" in out and "5000" in out


def test_leer_archivo_vacio(workspace):
    f = workspace / "v.txt"
    f.write_text("", encoding="utf-8")
    assert "archivo vacio" in T.run_tool("leer_archivo", str(f), _ctx())


# ── ejecutar: cabeza+cola + timeout parametrizable ─────────────────────────

def test_head_cola_conserva_el_final():
    out = "INICIO " + ("relleno " * 500) + "Traceback: el error real"
    r = T._head_cola(out)
    assert r.startswith("INICIO")
    assert r.endswith("Traceback: el error real")
    assert "chars omitidos" in r


def test_shell_conserva_la_cola(monkeypatch):
    # output largo con el "traceback" al final: antes out[:1500] perdia el
    # final; ahora _shell conserva cabeza+cola (el subprocess se mockea para no
    # depender del shell de la maquina; el sentinel real corre igual).
    #
    # EL MOCK ERA EL DE ANTES Y ESTABA MUERTO (arreglado 2026-08-25): pisaba
    # T.subprocess.run, pero _shell dejo de usar run() el 2026-08-24 y llama a
    # _correr_proceso (Popen + matar_arbol). O sea que este test corria `echo x`
    # DE VERDAD y comparaba su "x" contra "Traceback final real" — fallaba, y
    # con el mock puesto habria fallado igual porque no interceptaba nada. Es
    # el caso "el test que pasa (o falla) por el motivo equivocado".
    class _R:
        returncode = 0
        stdout = ("INICIO " + ("relleno " * 500) + "Traceback final real").encode()
        stderr = b""

    monkeypatch.setattr(T, "_correr_proceso", lambda *a, **k: _R())
    out = T._shell("echo x", _ctx())
    assert out.endswith("Traceback final real")
    assert "chars omitidos" in out
    # exit 0: ni una palabra de la pista de shell equivocado (2026-08-25).
    assert "NOTA:" not in out


def test_ejecutar_timeout_parametrizable(monkeypatch):
    capturado = {}

    # cwd es parametro de _shell desde 2026-08-18 (ejecutar lo pasa siempre):
    # el doble sin el reventaba con TypeError y run_tool se lo tragaba, dejando
    # el test en KeyError en vez de en el assert que le importa.
    def fake_shell(cmd, ctx, timeout=30, cwd=""):
        capturado["cmd"], capturado["timeout"] = cmd, timeout
        capturado["cwd"] = cwd
        return "RESULTADO ejecutar: ok"

    monkeypatch.setattr(T, "_shell", fake_shell)
    T.run_tool("ejecutar", "echo hola | timeout=120", _ctx())
    assert capturado["timeout"] == 120
    assert capturado["cmd"] == "echo hola"      # el sufijo no viaja al shell
    # sin sufijo: default 30, y un pipe legitimo NO se confunde con timeout
    T.run_tool("ejecutar", "echo a | findstr a", _ctx())
    assert capturado["timeout"] == 30
    assert capturado["cmd"] == "echo a | findstr a"
    # techo de 600s
    T.run_tool("ejecutar", "echo x | timeout=9999", _ctx())
    assert capturado["timeout"] == 600


# ── editar_archivo: diff de vuelta + unicidad ──────────────────────────────

def test_editar_archivo_devuelve_mini_diff(workspace):
    f = workspace / "code.py"
    f.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    bloque = "<<<<<<< SEARCH\nb = 2\n=======\nb = 99\n>>>>>>> REPLACE"
    out = T.run_tool("editar_archivo", f"{f} | {bloque}", _ctx())
    assert "OK" in out
    assert "-b = 2" in out and "+b = 99" in out      # el modelo VE que cambio


def test_editar_archivo_search_ambiguo_pide_ampliar(workspace):
    f = workspace / "dup.py"
    f.write_text("x = 1\ny = 2\nx = 1\n", encoding="utf-8")
    bloque = "<<<<<<< SEARCH\nx = 1\n=======\nx = 9\n>>>>>>> REPLACE"
    out = T.run_tool("editar_archivo", f"{f} | {bloque}", _ctx())
    assert "ERROR" in out and "amplia el SEARCH" in out
    # y el archivo quedo INTACTO
    assert f.read_text(encoding="utf-8") == "x = 1\ny = 2\nx = 1\n"


# ── borrar_archivo ─────────────────────────────────────────────────────────

def test_borrar_archivo_borra_en_workspace(workspace):
    f = workspace / "temporal.txt"
    f.write_text("x", encoding="utf-8")
    out = T.run_tool("borrar_archivo", "temporal.txt", _ctx())
    assert "OK" in out and not f.exists()


def test_borrar_archivo_fuera_rechazado(workspace, tmp_path_factory):
    fuera = tmp_path_factory.mktemp("fuera") / "no.txt"
    fuera.write_text("x", encoding="utf-8")
    out = T.run_tool("borrar_archivo", str(fuera), _ctx())
    assert "ERROR" in out and fuera.exists()


def test_borrar_archivo_inexistente_y_directorio(workspace):
    assert "no existe" in T.run_tool("borrar_archivo", "nada.txt", _ctx())
    (workspace / "carpeta").mkdir()
    out = T.run_tool("borrar_archivo", "carpeta", _ctx())
    assert "ERROR" in out and (workspace / "carpeta").exists()


# ── catalogo core + DESHABILITADA uniforme ─────────────────────────────────

def test_visible_tools_default_es_el_core(monkeypatch):
    from cognia.simple_mode import visible_tools
    for flag in ("COGNIA_LCD", "COGNIA_SCREEN", "COGNIA_BROWSER",
                 "COGNIA_IMG_TOOLS", "COGNIA_REPO_REVERSE"):
        monkeypatch.delenv(flag, raising=False)
    vis = visible_tools(set(T.TOOLS), override="sencillo")
    assert vis <= T.CORE_TOOLS               # nada fuera del core sin flag
    assert "leer_archivo" in vis and "editar_archivo" in vis
    # el registry entero sigue INVOCABLE aunque no se anuncie
    assert "git_estado" in T.TOOLS


def test_escena_apagada_dice_como_habilitarla(monkeypatch):
    """Mensaje uniforme para TODA familia opt-in (antes solo pantalla_*):
    'DESHABILITADA — activala con X=1', sin record_wanted_tool."""
    monkeypatch.delenv("COGNIA_LCD", raising=False)
    llamadas = []
    import cognia.agent.background_research as br
    monkeypatch.setattr(br, "record_wanted_tool",
                        lambda name, hint="": llamadas.append(name))
    # escena_zzz no registrada (y si tools_lcd ya se importo en esta suite,
    # una inexistente de la familia sigue probando el gate)
    out = T.run_tool("escena_zzz_inexistente", "", _ctx())
    assert "DESHABILITADA" in out and "COGNIA_LCD=1" in out
    assert "no existe" not in out
    assert llamadas == []                    # NO se pide sintetizar duplicados


def test_familias_optin_cubiertas():
    assert T.flag_de_optin("pantalla_captura") == "COGNIA_SCREEN"
    assert T.flag_de_optin("escena_crear") == "COGNIA_LCD"
    assert T.flag_de_optin("render_aprox") == "COGNIA_LCD"
    assert T.flag_de_optin("atribuir_fallo") == "COGNIA_LCD"
    assert T.flag_de_optin("imagen_generar") == "COGNIA_IMG_TOOLS"
    assert T.flag_de_optin("web_buscar") == "COGNIA_BROWSER"
    assert T.flag_de_optin("repo_a_prompt") == "COGNIA_REPO_REVERSE"
    assert T.flag_de_optin("leer_archivo") == ""


def test_tool_desconocida_sin_familia_sigue_diciendo_no_existe(monkeypatch):
    monkeypatch.setattr("cognia.agent.background_research.record_wanted_tool",
                        lambda name, hint="": None)
    out = T.run_tool("tool_totalmente_inventada", "", _ctx())
    assert "no existe" in out


# ── docs para schemas (WP1) ────────────────────────────────────────────────

def test_catalogo_schemas_trae_params_tipados():
    cat = {c["nombre"]: c for c in T.catalogo_schemas()}
    lee = cat["leer_archivo"]
    assert lee["descripcion"].startswith("Lee un archivo")
    nombres = [p["nombre"] for p in lee["params"]]
    assert nombres == ["path", "offset", "limit"]
    assert lee["params"][0]["requerido"] is True
    assert lee["params"][1]["tipo"] == "integer"
    # una tool sin params declarados cae al doc de una linea (no rompe)
    assert cat["fecha"]["params"] == []
    assert cat["fecha"]["descripcion"]


def test_catalogo_schemas_respeta_allowed():
    cat = T.catalogo_schemas(allowed={"leer_archivo"})
    assert [c["nombre"] for c in cat] == ["leer_archivo"]


def test_armar_args_posicionales_y_claves():
    assert T.armar_args("escribir_archivo",
                        {"path": "a.txt", "contenido": "hola"}) == "a.txt | hola"
    assert T.armar_args("leer_archivo",
                        {"path": "a.py", "offset": 10, "limit": 5}) == \
        "a.py offset=10 limit=5"                 # sin pipe: auto_fix lo comeria
    assert T.armar_args("ejecutar",
                        {"comando": "pytest -q", "timeout": 90}) == \
        "pytest -q | timeout=90"                 # su parser exige el pipe
    assert T.armar_args("leer_archivo", {"path": "a.py"}) == "a.py"


def test_armar_args_roundtrip_con_leer(workspace):
    # el string que arma armar_args es EXACTAMENTE lo que la tool parsea
    f = workspace / "r.txt"
    f.write_text("\n".join(f"l{i}" for i in range(1, 21)), encoding="utf-8")
    args = T.armar_args("leer_archivo", {"path": str(f), "offset": 18})
    out = T.run_tool("leer_archivo", args, _ctx())
    assert "l18" in out and "l17\n" not in out
