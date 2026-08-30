# -*- coding: utf-8 -*-
"""
tests/test_cli_flujoteca_editor.py
=================================
El CABLEADO en cognia/cli.py de las tres puertas nuevas de la obra del
2026-08-29: `/flujoteca editor`, `/flujoteca importar`, `/biblioteca` y
`/avanzado`. Los MODULOS que hay debajo tienen sus propios tests
(tests/test_flujoteca_editor.py, tests/test_biblioteca_view.py,
tests/test_cli_visibilidad.py); aca se prueba lo que solo existe en el CLI.

Lo que se fija:
  1. un flujo llamado literalmente "editor de textos" NO se come el subcomando
     `editor` -- y sigue siendo alcanzable (riesgo #18 del plan:
     `_flujoteca_partir_nombre` elige el nombre real MAS LARGO que sea prefijo
     de lo tecleado);
  2. `abrir` sigue yendo al VISOR de solo lectura y `editor` al editor;
  3. la URL del editor lleva el TOKEN dentro: se imprime SIN el cuando la
     pestana ya se abrio, y ENTERA solo si no se pudo abrir (si no, el dueno
     no puede entrar);
  4. `importar` valida en Python ANTES de escribir: un flujo con ciclo no deja
     nada en disco;
  5. `/biblioteca` genera y abre, y `/biblioteca abrir <id>` abre el producto;
  6. `/avanzado` cambia el nivel, invalida los caches y NO desactiva nada.

La flujoteca va a tmp_path con una fixture AUTOUSE.
"""

import json

import pytest

import cognia.cli as cli
from cognia.agent import flujoteca as ft


UN_NODO = [{"id": "leer", "tool": "leer_archivo", "args": "notas.md",
            "wires": []}]


@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    monkeypatch.delenv("COGNIA_REMOTO", raising=False)
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / ".cognia_config.json")
    return tmp_path


def _crear(nombre):
    ft.guardar({"nombre": nombre, "nodos": UN_NODO}, nombre=nombre,
               nota="test")


def _espiar_apertura(monkeypatch):
    vistos = []
    monkeypatch.setattr(cli, "_abrir_editor_flujo",
                        lambda nombre, *, forzar_visor=False:
                        vistos.append((nombre, forzar_visor)) or
                        {"ok": True, "que": "editor", "ruta": "http://127.0.0.1:1",
                         "url": "http://127.0.0.1:1/?t=T", "abierto": True,
                         "motivo": ""})
    return vistos


# ---------------------------------------------------------------------------
# 1-2. El subcomando gana, y el flujo sigue siendo alcanzable
# ---------------------------------------------------------------------------

def test_un_flujo_llamado_editor_de_textos_no_se_come_el_subcomando(monkeypatch):
    """`_flujoteca_partir_nombre` coge el nombre real MAS LARGO que sea prefijo
    de lo tecleado. Con un flujo llamado "editor de textos", `/flujoteca
    editor de textos` tiene que abrir ESE flujo, no uno llamado "de textos"
    (que no existe) ni tratar "editor" como parte del nombre en las demas
    ramas."""
    _crear("editor de textos")
    _crear("otro")
    vistos = _espiar_apertura(monkeypatch)

    cli._slash_flujoteca("editor de textos")

    assert vistos == [("editor de textos", False)], vistos


def test_el_subcomando_editor_gana_sobre_un_flujo_que_si_existe(monkeypatch):
    """Y al reves: si "de textos" SI es un flujo, `editor` es el subcomando y
    el nombre es "de textos". El subcomando se comprueba primero."""
    _crear("de textos")
    vistos = _espiar_apertura(monkeypatch)

    cli._slash_flujoteca("editor de textos")

    assert vistos == [("de textos", False)]


def test_editor_sin_nombre_abre_el_mas_reciente(monkeypatch):
    _crear("viejo")
    _crear("nuevo")
    vistos = _espiar_apertura(monkeypatch)

    cli._slash_flujoteca("editor")

    assert len(vistos) == 1
    assert vistos[0][0] in [f["nombre"] for f in ft.listar()]


def test_editor_sin_flujos_lo_dice_y_no_abre_nada(monkeypatch, capsys):
    vistos = _espiar_apertura(monkeypatch)
    cli._slash_flujoteca("editor")
    assert vistos == []
    assert "no hay ningun flujo" in capsys.readouterr().out


def test_abrir_sigue_yendo_al_visor_de_solo_lectura(monkeypatch):
    """El visor file:// es lo que funciona en remoto, en CI y sin display: no
    se cambia por el editor."""
    _crear("informe")
    vistos = _espiar_apertura(monkeypatch)
    cli._slash_flujoteca("abrir informe")
    assert vistos == [("informe", True)]


def test_partir_nombre_no_inventa_un_flujo_con_el_subcomando(monkeypatch):
    """"editar editor ..." sin ningun flujo llamado "editor" no puede resolver
    a un flujo fantasma."""
    _crear("informe")
    assert cli._flujoteca_partir_nombre("editor de textos") == ("", "")
    assert cli._flujoteca_partir_nombre("informe anade un paso") == \
        ("informe", "anade un paso")


# ---------------------------------------------------------------------------
# 3. El token no se pinta cuando no hace falta
# ---------------------------------------------------------------------------

def test_la_url_con_token_no_se_imprime_si_el_navegador_abrio(capsys):
    cli._flujoteca_pintar_apertura("informe", {
        "ok": True, "que": "editor", "ruta": "http://127.0.0.1:5555",
        "url": "http://127.0.0.1:5555/?t=SECRETO-DEL-TOKEN",
        "abierto": True, "motivo": ""})
    salida = capsys.readouterr().out
    assert "SECRETO-DEL-TOKEN" not in salida
    assert "127.0.0.1:5555" in salida


def test_la_url_entera_si_sale_cuando_el_navegador_no_abrio(capsys):
    """Ocultarla aqui dejaria al dueno sin poder entrar: el riesgo cambia de
    'se filtra' a 'no sirve para nada'."""
    cli._flujoteca_pintar_apertura("informe", {
        "ok": True, "que": "editor", "ruta": "http://127.0.0.1:5555",
        "url": "http://127.0.0.1:5555/?t=SECRETO-DEL-TOKEN",
        "abierto": False, "motivo": "el navegador no se pudo abrir"})
    salida = capsys.readouterr().out
    assert "SECRETO-DEL-TOKEN" in salida


def test_un_fallo_al_abrir_se_dice_y_no_lanza(capsys):
    cli._flujoteca_pintar_apertura("informe", {
        "ok": False, "que": "editor", "ruta": "", "url": "",
        "abierto": False, "motivo": "OSError: sin display"})
    assert "sin display" in capsys.readouterr().out


def test_el_visor_dice_como_encender_el_editor(capsys):
    """Con memorias_abrir_navegador=false, '/flujoteca editor' entrega el
    visor de solo lectura. Eso es correcto (el editor necesita una ventana)
    pero NO puede pasar en silencio: seria indistinguible de que el editor no
    existe."""
    cli._flujoteca_pintar_apertura("informe", {
        "ok": True, "que": "visor", "ruta": "C:/x/lienzo.html", "url": "",
        "abierto": False,
        "motivo": "no se abre ventana (memorias_abrir_navegador / COGNIA_REMOTO)"})
    salida = capsys.readouterr().out
    assert "solo lectura" in salida
    assert "memorias_abrir_navegador=true" in salida


def test_abrir_editor_flujo_cae_al_visor_sin_navegador(monkeypatch):
    """La politica esta en UN sitio: con memorias_abrir_navegador=false no se
    levanta ningun servidor, se escribe el fichero y se dice la ruta."""
    _crear("informe")
    cli._save_config({**cli._CONFIG_DEFAULTS, "memorias_abrir_navegador": False})

    def _no(*a, **k):
        raise AssertionError("no deberia levantarse el editor")

    monkeypatch.setattr("cognia.agent.flujoteca_editor.abrir", _no)
    monkeypatch.setattr("cognia.agent.flujoteca_view.export",
                        lambda nombre, open_browser=True: "C:/x/lienzo.html")

    res = cli._abrir_editor_flujo("informe")

    assert res["que"] == "visor" and res["abierto"] is False


# ---------------------------------------------------------------------------
# 4. importar valida antes de escribir
# ---------------------------------------------------------------------------

def test_importar_guarda_un_flujo_valido(capsys):
    cli._slash_flujoteca("importar " + json.dumps(
        {"nombre": "traido", "nodos": UN_NODO}))
    assert [f["nombre"] for f in ft.listar()] == ["traido"]
    assert "importado" in capsys.readouterr().out


def test_importar_con_ciclo_no_escribe_nada(capsys):
    ciclo = {"nombre": "malo", "nodos": [
        {"id": "a", "tool": "leer_archivo", "args": "", "wires": ["b"]},
        {"id": "b", "tool": "leer_archivo", "args": "", "wires": ["a"]}]}
    cli._slash_flujoteca("importar " + json.dumps(ciclo))
    assert ft.listar() == []
    assert "no se importo NADA" in capsys.readouterr().out


def test_importar_basura_no_lanza(capsys):
    cli._slash_flujoteca("importar {esto no es json")
    assert ft.listar() == []
    assert "no es JSON valido" in capsys.readouterr().out


def test_importar_desde_un_fichero(tmp_path, capsys):
    p = tmp_path / "flujo.json"
    p.write_text(json.dumps({"nombre": "de fichero", "nodos": UN_NODO}),
                 encoding="utf-8")
    cli._slash_flujoteca(f"importar {p}")
    assert [f["nombre"] for f in ft.listar()] == ["de fichero"]


# ---------------------------------------------------------------------------
# 5. /biblioteca
# ---------------------------------------------------------------------------

def test_biblioteca_sin_argumento_genera_y_abre(monkeypatch, capsys):
    from cognia.program_creator import biblioteca_view as bv
    vistos = []
    monkeypatch.setattr(bv, "export",
                        lambda path=None, *, open_browser=True, base=None:
                        vistos.append(open_browser) or "C:/x/biblioteca.html")
    monkeypatch.setattr(bv, "build_biblioteca_data",
                        lambda base=None: {"total": 3, "items": [],
                                           "lenguajes": [], "fantasmas": 0,
                                           "en_index": 3, "categorias": []})
    cli._slash_biblioteca("")
    assert vistos == [True]
    assert "biblioteca.html" in capsys.readouterr().out


def test_biblioteca_bajo_remoto_no_abre_ventana(monkeypatch, capsys):
    from cognia.program_creator import biblioteca_view as bv
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    vistos = []
    monkeypatch.setattr(bv, "export",
                        lambda path=None, *, open_browser=True, base=None:
                        vistos.append(open_browser) or "C:/x/biblioteca.html")
    monkeypatch.setattr(bv, "build_biblioteca_data",
                        lambda base=None: {"total": 0, "items": [],
                                           "lenguajes": [], "fantasmas": 0,
                                           "en_index": 0, "categorias": []})
    cli._slash_biblioteca("")
    assert vistos == [False]
    assert "biblioteca.html" in capsys.readouterr().out    # la ruta SI sale


def test_biblioteca_abrir_resuelve_y_abre_el_producto(monkeypatch, capsys):
    from cognia.program_creator import biblioteca_view as bv
    item = {"id": "mi_web", "title": "Mi web", "lenguaje": "html",
            "entrypoint": "C:/x/index.html", "directorio": "C:/x"}
    monkeypatch.setattr(bv, "resolver_detalle",
                        lambda ref, base=None: {"item": item, "motivo": "",
                                                "candidatos": []})
    abiertos = []
    monkeypatch.setattr(bv, "abrir_producto",
                        lambda it, *, open_browser=True:
                        abiertos.append((it["id"], open_browser)) or
                        {"ok": True, "que": "html", "ruta": it["entrypoint"],
                         "abierto": True, "motivo": ""})
    cli._slash_biblioteca("abrir mi_web")
    assert abiertos == [("mi_web", True)]
    assert "index.html" in capsys.readouterr().out


def test_biblioteca_abrir_ambiguo_ensena_los_candidatos(monkeypatch, capsys):
    """'no existe' y 'es ambiguo' piden acciones distintas del dueno."""
    from cognia.program_creator import biblioteca_view as bv
    monkeypatch.setattr(bv, "resolver_detalle",
                        lambda ref, base=None: {
                            "item": None, "motivo": "el prefijo 'di_' es ambiguo",
                            "candidatos": ["di_hola_1", "di_hola_2"]})
    cli._slash_biblioteca("abrir di_")
    salida = capsys.readouterr().out
    assert "ambiguo" in salida and "di_hola_2" in salida


def test_biblioteca_ver_sigue_existiendo(monkeypatch, capsys):
    monkeypatch.setattr("cognia.program_creator.storage.load_program_code",
                        lambda pid: "print('hola')")
    cli._slash_biblioteca("ver mi_programa")
    assert "print('hola')" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 6. /avanzado
# ---------------------------------------------------------------------------

def test_avanzado_revela_y_off_vuelve_al_nucleo(monkeypatch, capsys):
    from cognia import cli_visibilidad as vis
    from cognia import user_prefs
    monkeypatch.setenv("COGNIA_UI_MODE", "sencillo")
    # `set_nivel_cmds` PERSISTE de verdad (~/.cognia/config.env) y escribe
    # os.environ a mano. Sin estas dos lineas, un test le cambia la config al
    # dueno: se corta la escritura a disco y se da de alta la clave con
    # `setenv` ANTES para que el teardown de monkeypatch la borre.
    monkeypatch.setenv(vis.K_CMD_NIVEL, "nucleo")
    monkeypatch.setattr(user_prefs, "save_pref", lambda k, v: None)
    monkeypatch.setattr("cognia.simple_mode.is_simple", lambda override=None: True)
    vis.invalidar_cache()

    cli._slash_avanzado("off")
    capsys.readouterr()
    nucleo = len(cli._cmds_visibles())
    assert nucleo < len(cli._CMD_DESCRIPTIONS)

    cli._slash_avanzado("")
    assert len(cli._cmds_visibles()) == len(cli._CMD_DESCRIPTIONS)
    assert "catalogo completo" in capsys.readouterr().out

    cli._slash_avanzado("off")
    assert len(cli._cmds_visibles()) == nucleo
    vis.invalidar_cache()


def test_ocultar_no_es_desactivar(monkeypatch):
    """Un comando fuera del nucleo tiene que SEGUIR despachandose, y el CLI
    tiene que seguir sugiriendolo cuando el dueno se equivoca al teclearlo."""
    import inspect
    from cognia import cli_visibilidad as vis
    from cognia.harness import ayuda

    fuente = inspect.getsource(cli)
    ocultos = [c for c in cli._CMD_DESCRIPTIONS if c not in vis.NUCLEO]
    assert ocultos
    for cmd in ("/grafo", "/autoprueba", "/tx"):
        assert cmd in ocultos
        assert (f'raw == "{cmd}"' in fuente
                or f'raw.startswith("{cmd} ' in fuente), cmd
    # mensaje_desconocido recibe el catalogo COMPLETO: '/gaf' -> '/grafo'
    assert "mensaje_desconocido(_CMD_DESCRIPTIONS" in fuente
    assert "/grafo" in ayuda.mensaje_desconocido(cli._CMD_DESCRIPTIONS, "/gaf")


def test_comandos_dice_cuantos_oculta(monkeypatch, capsys):
    from cognia import cli_visibilidad as vis
    monkeypatch.setattr(vis, "es_avanzado", lambda override=None: False)
    cli._slash_comandos("")
    salida = capsys.readouterr().out
    assert str(len(cli._CMD_DESCRIPTIONS)) in salida
    assert "Categorias principales:" in salida
    assert "/avanzado los revela" in salida


def test_ayuda_todo_ignora_el_filtro():
    """'/ayuda todo' es la valvula de escape: siempre lista el catalogo
    entero, o la promesa 'ocultar no es desactivar' no seria comprobable."""
    import inspect
    fuente = inspect.getsource(cli)
    assert "_ah.todo(_CMD_DESCRIPTIONS, _ancho)" in fuente
    assert "_ah.portada(_cat_ayuda, _ancho)" in fuente
