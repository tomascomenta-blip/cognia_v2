# -*- coding: utf-8 -*-
"""/estilo textual + aplicacion en caliente (paso P4 del sistema de estilos
por elemento, 2026-08-24). Cubre: la puerta slash (sin shadowing), cada
subcomando por funcion, deshacer (.bak), animacion on/off persistida y su
origen en /config-resuelta, el aviso E8 para los elementos no enganchados,
el arranque con fichero roto (ruidoso, sigue con el default), el hot reload
E6 (el toolbar solo MARCA; la reconstruccion va en el bucle) y la conexion
del motor de glow al registro.

Nada de esto toca el HOME: estilo.json, presets y la config van a tmp_path.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("rich")

import cognia.cli as cli
from cognia.ux import aspecto as A
from cognia.ux import glow as G

_CLI_SRC = Path(inspect.getfile(cli)).read_text(encoding="utf-8")


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """estilo.json, presets del dueno y config del CLI en tmp_path; salida y
    degradados capturados; la Console se restaura al salir."""
    monkeypatch.setattr(A, "RUTA_ESTILO", tmp_path / "estilo.json")
    monkeypatch.setattr(A, "DIR_PRESETS", tmp_path / "estilos")
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / "cfg.json")
    for k in ("COGNIA_THEME", "COGNIA_REMOTO", "COGNIA_ASCII", "COGNIA_ANIMACION", "NO_COLOR"):
        monkeypatch.delenv(k, raising=False)
    salida, avisos = [], []
    monkeypatch.setattr(cli, "_print_line", lambda t: salida.append(str(t)))
    monkeypatch.setattr(cli, "_aviso_degradado", lambda via, det="": avisos.append((via, det)))
    monkeypatch.setattr(cli, "_theme_idx", 0)
    monkeypatch.setattr(cli, "_persist_setting", lambda k, v: None)
    consola_previa = cli._console
    A.cargar()
    yield SimpleNamespace(salida=salida, avisos=avisos, tmp=tmp_path,
                          texto=lambda: "\n".join(salida))
    A.reset()
    try:
        A.cargar()          # el tmp puede haber quedado ROTO a proposito
    except A.EstiloInvalido:
        A.reset()
    cli._console = consola_previa
    try:
        from cognia.ux import renderer as _R
        if _R._renderer is not None:
            _R.activar(console=consola_previa)
    except Exception:
        pass


def _ok_cl_hex() -> str:
    """El color del token ok_cl en la Console VIVA del CLI (lo que pinta)."""
    return cli._console.get_style("ok_cl").color.get_truecolor().hex


# ---------------------------------------------------------------------------
# Puerta slash: existe una sola vez y no tapa ni la tapan
# ---------------------------------------------------------------------------

def test_estilo_no_esta_tapado_ni_tapa():
    assert _CLI_SRC.count('raw == "/estilo"') == 1
    assert _CLI_SRC.count('raw.startswith("/estilo ")') == 2  # el elif y su slice
    assert 'startswith("/estilo")' not in _CLI_SRC, "un startswith sin espacio taparia /estilo_info"
    assert _CLI_SRC.count("def _slash_estilo(") == 1
    assert "/estilo" in cli._CMD_DESCRIPTIONS and "/estilo" in cli._CMD_DETAILS
    assert cli._CMD_DESCRIPTIONS.get("/estilo_info"), "/estilo_info sigue existiendo"
    # el elif de /estilo va DESPUES del de /color (donde el diseno lo pone) y
    # ANTES del == "/estilo_info" no importa: son comparaciones exactas
    assert _CLI_SRC.index('raw == "/color"') < _CLI_SRC.index('raw == "/estilo"')


def test_sin_argumentos_sin_tty_degrada_a_la_ayuda_y_no_abre_application(entorno):
    """P11: `/estilo` a secas abre el editor SOLO con tty real; bajo pytest
    (sin tty) abrir_editor devuelve no_abrible y el CLI degrada a la ayuda
    textual avisando por _aviso_degradado (nada mudo)."""
    cli._slash_estilo("")
    t = entorno.texto()
    assert "editor no disponible" in t
    # _print_line recibe markup: el [grupo] del uso viaja escapado (\[grupo])
    # para que rich no se lo coma como tag
    assert r"lista \[grupo]" in t, "el [grupo] de la ayuda tiene que ir escapado"
    assert any(via == "estilo.editor" for via, _ in entorno.avisos)
    # E12: el editor nunca se abre desde un binding de teclado, solo desde el
    # bucle del REPL via _estilo_editor
    assert "_estilo_editor" not in "".join(
        l for l in _CLI_SRC.splitlines() if "@_kb.add" in l or "kb.add(" in l)
    fuente = inspect.getsource(cli._slash_estilo)
    assert "Application" not in fuente


def test_config_default_estilo_animacion_on():
    assert cli._CONFIG_DEFAULTS["estilo_animacion"] == "on"


# ---------------------------------------------------------------------------
# lista / ver
# ---------------------------------------------------------------------------

def test_lista_completa_y_por_grupo(entorno):
    cli._slash_estilo("lista")
    t = entorno.texto()
    for id in A.REGISTRO:
        assert id in t
    # banner.* (P7) y spinner.* (P8) ya estan enganchados: no anuncian paso;
    # los de P6 (agentes.*, diff.*...) si
    assert "(P6)" in t, "los no enganchados dicen su paso"
    assert "(P7)" not in t and "(P8)" not in t, "banner y spinner ya se aplican"
    assert "(P5)" not in t, "P5 ya engancho prompt/barra/menu"
    entorno.salida.clear()
    cli._slash_estilo("lista sistema")
    t = entorno.texto()
    assert "sistema.ok" in t and "prompt.etiqueta" not in t
    entorno.salida.clear()
    cli._slash_estilo("lista nada")
    assert "grupo desconocido" in entorno.texto()


def test_ver_muestra_valor_resuelto_y_origen(entorno):
    cli._slash_estilo("ver sistema.ok")
    t = entorno.texto()
    assert "#3fb950" in t and "(default)" in t and "enganchado si" in t
    cli._slash_estilo("sistema.ok color #ff00ff")
    entorno.salida.clear()
    cli._slash_estilo("ver sistema.ok")
    t = entorno.texto()
    assert "#ff00ff" in t and "(estilo.json)" in t
    entorno.salida.clear()
    cli._slash_estilo("ver")
    t = entorno.texto()
    assert "sistema.ok" in t and "#ff00ff" in t and "animacion global: on" in t


# ---------------------------------------------------------------------------
# <id> <prop> <valor> y style string: validar -> guardar -> aplicar
# ---------------------------------------------------------------------------

def test_set_guarda_con_bak_y_recolorea_la_console_en_caliente(entorno):
    antes = _ok_cl_hex()
    assert antes != "#ff00ff"
    cli._slash_estilo("sistema.ok color #ff00ff")
    assert A.RUTA_ESTILO.exists()
    doc = json.loads(A.RUTA_ESTILO.read_text(encoding="utf-8"))
    assert doc["elementos"]["sistema.ok"]["color"] == "#ff00ff"
    assert _ok_cl_hex() == "#ff00ff", "el Theme vivo tiene que retener ok_cl"
    assert "(guardado)" in entorno.texto()
    assert entorno.avisos == []
    # segundo cambio: el .bak es el estado anterior
    cli._slash_estilo("sistema.ok negrita on")
    bak = json.loads((entorno.tmp / "estilo.json.bak").read_text(encoding="utf-8"))
    assert "negrita" not in bak["elementos"]["sistema.ok"]


def test_set_en_elemento_no_enganchado_guarda_y_avisa_E8(entorno):
    # banner.* ya esta enganchado (P7); el ejemplo de elemento pendiente es
    # la vista F2 de agentes (P6)
    cli._slash_estilo("agentes.texto color #ff00ff")
    t = entorno.texto()
    assert "(guardado)" in t
    assert "se aplica cuando su elemento este enganchado (paso P6)" in t
    assert A.estilo_de("agentes.texto").color == "#ff00ff"
    assert json.loads(A.RUTA_ESTILO.read_text(encoding="utf-8"))["elementos"]["agentes.texto"]["color"] == "#ff00ff"


def test_set_en_el_prompt_ya_no_avisa_ni_por_la_animacion(entorno):
    """P5: prompt.etiqueta esta enganchado: el texto se ve en el prompt
    siguiente (sin aviso E8); P9: la animacion tampoco avisa (pulso cableado).
    barra.estado no va con el pulso: sigue diciendo P9 hasta que alguien lo cablee."""
    cli._slash_estilo("prompt.etiqueta texto jarvis")
    t = entorno.texto()
    assert "(guardado)" in t and "se aplica cuando" not in t
    assert A.texto("prompt.etiqueta") == "jarvis"
    assert [x for x, _ in cli._mensaje_prompt()] == ["class:marco", "class:cognia", "class:flecha"]
    assert list(cli._mensaje_prompt())[1][1] == " jarvis"
    entorno.salida.clear()
    cli._slash_estilo("prompt.etiqueta animacion.activa on")
    assert "(guardado)" in entorno.texto() and "paso P9" not in entorno.texto()
    assert A.paso_pendiente("prompt.etiqueta", "animacion.activa") == ""
    entorno.salida.clear()
    cli._slash_estilo("barra.estado animacion.activa on")
    assert "paso P9" in entorno.texto(), "la barra no va con el pulso todavia"


def test_set_de_glifo_en_enganchado_por_token_avisa_pero_el_color_no(entorno):
    cli._slash_estilo("tool.ok color #ff00ff")
    assert "se aplica cuando" not in entorno.texto()
    entorno.salida.clear()
    cli._slash_estilo("tool.ok glifo x")
    # P6: el glifo de tool.ok ya se ve (render_tools.glifo_estado y renderer._glifo)
    assert "se aplica cuando" not in entorno.texto()
    assert A.glifo("tool.ok") == "x"


def test_style_string_entre_comillas(entorno):
    cli._slash_estilo('sistema.ok "bold fg:#ff00ff"')
    est = A.estilo_de("sistema.ok")
    assert est.negrita is True and est.color == "#ff00ff"
    assert _ok_cl_hex() == "#ff00ff"
    assert "(guardado)" in entorno.texto()


def test_valor_con_espacios_entre_comillas(entorno):
    cli._slash_estilo('prompt.etiqueta texto "hola gato"')
    assert A.texto("prompt.etiqueta") == "hola gato"


def test_errores_son_ruidosos_y_no_escriben(entorno):
    cli._slash_estilo("sistema.okk color red")
    cli._slash_estilo("sistema.ok colr red")
    cli._slash_estilo("sistema.ok color rojo-no")
    cli._slash_estilo("sistema.ok color")
    vias = [v for v, _ in entorno.avisos]
    detalles = "\n".join(d for _, d in entorno.avisos)
    assert vias.count("estilo") == 3
    assert "ids parecidos: sistema.ok" in detalles
    assert "propiedad desconocida" in detalles and "parecidos: color" in detalles
    assert "color invalido 'rojo-no'" in detalles
    assert "falta el valor" in entorno.texto()
    assert not A.RUTA_ESTILO.exists(), "con error no se guarda nada"
    assert not A.tiene_override("sistema.ok")


def test_subcomando_desconocido_sugiere(entorno):
    cli._slash_estilo("listar")
    t = entorno.texto()
    assert "no entiendo 'listar'" in t and "lista" in t


# ---------------------------------------------------------------------------
# deshacer / reset
# ---------------------------------------------------------------------------

def test_deshacer_alterna_con_el_bak(entorno):
    cli._slash_estilo("deshacer")
    assert "nada que deshacer" in entorno.texto()
    cli._slash_estilo("sistema.ok color #ff00ff")
    cli._slash_estilo("sistema.ok color #00ff00")
    assert _ok_cl_hex() == "#00ff00"
    entorno.salida.clear()
    cli._slash_estilo("deshacer")
    assert A.estilo_de("sistema.ok").color == "#ff00ff"
    assert _ok_cl_hex() == "#ff00ff", "deshacer tambien aplica en caliente"
    assert "restaurado" in entorno.texto()
    cli._slash_estilo("deshacer")
    assert A.estilo_de("sistema.ok").color == "#00ff00"


def test_reset_id_y_todo(entorno, monkeypatch):
    from cognia.ux import selector
    monkeypatch.setattr(selector, "hay_tty", lambda: False)  # sin confirmacion por pipe
    cli._slash_estilo("sistema.ok color #ff00ff")
    cli._slash_estilo("prompt.etiqueta texto jarvis")
    cli._slash_estilo("reset sistema.ok")
    assert not A.tiene_override("sistema.ok") and A.tiene_override("prompt.etiqueta")
    assert _ok_cl_hex() == "#3fb950"
    cli._slash_estilo("reset todo")
    assert not any(A.tiene_override(i) for i in A.REGISTRO)
    assert json.loads(A.RUTA_ESTILO.read_text(encoding="utf-8"))["elementos"] == {}


def test_reset_todo_cancelado_con_tty_no_toca_nada(entorno, monkeypatch):
    from cognia.ux import selector
    monkeypatch.setattr(selector, "hay_tty", lambda: True)
    monkeypatch.setattr(selector, "confirmar", lambda *a, **k: False)
    cli._slash_estilo("sistema.ok color #ff00ff")
    cli._slash_estilo("reset")
    assert A.tiene_override("sistema.ok") and "cancelado" in entorno.texto()


# ---------------------------------------------------------------------------
# animacion on|off: config persistida y origen correcto en /config-resuelta
# ---------------------------------------------------------------------------

def test_animacion_on_off_persiste_y_config_resuelta_no_miente(entorno, monkeypatch):
    from cognia.harness import config_resuelta as CR
    assert "estilo_animacion" in CR.ENV_QUE_PISAN
    ruta = cli._CONFIG_PATH
    res = CR.config_resuelta(defaults=cli._CONFIG_DEFAULTS, ruta_fichero=ruta, entorno={})
    assert res["estilo_animacion"] == {"valor": "on", "origen": "default", "default": "on"}
    assert A.animacion_global()[0] is True

    cli._slash_estilo("animacion off")
    assert cli._load_config()["estilo_animacion"] == "off"
    assert "off (guardado)" in entorno.texto()
    assert A.animacion_global() == (False, "config estilo_animacion=off")
    res = CR.config_resuelta(defaults=cli._CONFIG_DEFAULTS, ruta_fichero=ruta, entorno={})
    assert res["estilo_animacion"]["origen"] == "fichero"
    assert res["estilo_animacion"]["valor"] == "off"
    # la env gana y se reporta como env, nunca como siembra
    res = CR.config_resuelta(defaults=cli._CONFIG_DEFAULTS, ruta_fichero=ruta,
                             entorno={"COGNIA_ANIMACION": "1"})
    assert res["estilo_animacion"]["origen"] == "env:COGNIA_ANIMACION"

    entorno.salida.clear()
    cli._slash_estilo("animacion estado")
    t = entorno.texto()
    assert "animacion de estilos: off (config" in t and "esta terminal" in t

    cli._slash_estilo("animacion on")
    assert cli._load_config()["estilo_animacion"] == "on"
    entorno.salida.clear()
    cli._slash_estilo("animacion estado")
    assert "on (default" in entorno.texto()
    monkeypatch.setenv("COGNIA_ANIMACION", "0")
    entorno.salida.clear()
    cli._slash_estilo("animacion on")
    assert "GANA a la config" in entorno.texto()
    cli._slash_estilo("animacion quizas")
    assert "Uso: /estilo animacion" in entorno.texto()


# ---------------------------------------------------------------------------
# presets: guardar / cargar / presets / exportar
# ---------------------------------------------------------------------------

def test_cargar_preset_del_paquete_y_avisa_lo_pendiente(entorno):
    cli._slash_estilo("cargar neon")
    t = entorno.texto()
    assert "'neon' cargado" in t
    # P5: prompt.* ya se ve; del neon solo queda pendiente la animacion del
    # prompt (P9) y el banner/spinner de sus pasos
    assert "prompt.* (P5)" not in t
    assert "prompt.etiqueta.animacion" not in t, "P9: la animacion del prompt ya se ve"
    assert "(P7)" not in t and "(P8)" not in t, "banner y spinner ya se aplican"
    assert A.tiene_override("prompt.etiqueta")
    assert json.loads(A.RUTA_ESTILO.read_text(encoding="utf-8"))["nombre"] == "neon"
    assert entorno.avisos == []


def test_cargar_preset_desconocido_es_ruidoso(entorno):
    cli._slash_estilo("cargar neonn")
    assert any("preset no cargado" in d and "neon" in d for _, d in entorno.avisos)
    assert not A.RUTA_ESTILO.exists()


def test_cargar_sin_argumento_por_pipe_lista_y_dice_el_uso(entorno, monkeypatch):
    from cognia.ux import selector
    monkeypatch.setattr(selector, "hay_tty", lambda: False)
    cli._slash_estilo("cargar")
    t = entorno.texto()
    assert "Presets" in t and "neon" in t and "Uso: /estilo cargar" in t


def test_guardar_preset_del_dueno_y_presets_lo_lista(entorno):
    cli._slash_estilo("sistema.ok color #ff00ff")
    cli._slash_estilo("guardar mio")
    ruta = entorno.tmp / "estilos" / "mio.json"
    assert ruta.exists()
    assert json.loads(ruta.read_text(encoding="utf-8"))["elementos"]["sistema.ok"]["color"] == "#ff00ff"
    entorno.salida.clear()
    cli._slash_estilo("presets")
    t = entorno.texto()
    assert "mio" in t and "dueno" in t and "clasico" in t and "paquete" in t
    cli._slash_estilo("reset sistema.ok")
    assert _ok_cl_hex() != "#ff00ff"
    cli._slash_estilo("cargar mio")
    assert _ok_cl_hex() == "#ff00ff"
    cli._slash_estilo("guardar nombre malo")
    assert any("preset no guardado" in d for _, d in entorno.avisos)
    cli._slash_estilo("guardar")
    assert "Uso: /estilo guardar" in entorno.texto()


def test_exportar_escribe_el_estado_completo(entorno):
    cli._slash_estilo("sistema.ok color #ff00ff")
    destino = entorno.tmp / "exp.json"
    cli._slash_estilo(f"exportar {destino}")
    doc = json.loads(destino.read_text(encoding="utf-8"))
    assert set(doc["elementos"]) == set(A.REGISTRO)
    assert doc["elementos"]["sistema.ok"]["color"] == "#ff00ff"
    assert "exportado" in entorno.texto()
    cli._slash_estilo("exportar")
    assert "Uso: /estilo exportar" in entorno.texto()


# ---------------------------------------------------------------------------
# /tema comparte _aplicar_tema_en_caliente y sigue funcionando
# ---------------------------------------------------------------------------

def test_tema_sigue_funcionando_y_retiene_el_override(entorno):
    from rich.theme import Theme
    cli._slash_estilo("sistema.ok color #ff00ff")
    cli._slash_tema("claro")
    assert cli._THEME_ORDER[cli._theme_idx] == "claro"
    assert _ok_cl_hex() == "#ff00ff", "/tema claro conserva el override de /estilo"
    # y sin override, el Theme es el de paleta tal cual (byte-identico)
    cli._slash_estilo("reset sistema.ok")
    from cognia.ux import paleta
    assert A.tema_rich("claro") == paleta.tema_cli("claro")
    assert _ok_cl_hex() == Theme(paleta.tema_cli("claro")).styles["ok_cl"].color.get_truecolor().hex
    fuente = inspect.getsource(cli._slash_tema)
    assert "_aplicar_tema_en_caliente()" in fuente and "Console(" not in fuente


# ---------------------------------------------------------------------------
# arranque: fichero roto avisa y se sigue con el default; motor conectado
# ---------------------------------------------------------------------------

def test_arranque_con_fichero_roto_avisa_y_arranca_con_default(entorno):
    A.RUTA_ESTILO.write_text("{no es json", encoding="utf-8")
    consola = cli._console
    cli._aplicar_config_estilo()
    assert any(v == "estilo" and "aspecto por defecto" in d for v, d in entorno.avisos)
    assert not any(A.tiene_override(i) for i in A.REGISTRO)
    assert cli._console is consola, "sin fichero valido no se reconstruye nada"
    assert A.tema_rich("oscuro") == __import__("cognia.ux.paleta", fromlist=["x"]).tema_cli("oscuro")


def test_arranque_con_fichero_invalido_nombra_el_error(entorno):
    A.RUTA_ESTILO.write_text(json.dumps({"version": 1, "elementos": {
        "prompt.etiquta": {"texto": "x"}}}), encoding="utf-8")
    cli._aplicar_config_estilo()
    assert any("prompt.etiquta" in d and "prompt.etiqueta" in d for _, d in entorno.avisos)


def test_arranque_conecta_el_motor_y_aplica_el_fichero(entorno):
    A.RUTA_ESTILO.write_text(json.dumps({"version": 1, "global": {"fps": 20}, "elementos": {
        "sistema.ok": {"color": "#ff00ff"}}}), encoding="utf-8")
    cli._aplicar_config_estilo()
    assert G.RESOLVER is A.estilo_glow and G.VERSION is A.version
    assert G.VARIANTE is A.variante_activa and G.LEER_CONFIG is cli._load_config
    assert G.FPS == 20
    assert _ok_cl_hex() == "#ff00ff", "con overrides la Console se reconstruye antes del banner"
    assert entorno.avisos == []
    # el motor pinta sistema.ok con el hex nuevo y el resto con su token
    assert str(G.estilo_rich("sistema.ok")) == "#ff00ff"
    assert G.estilo_rich("sistema.detalle") == "detail"


# ---------------------------------------------------------------------------
# E6: hot reload por mtime: el toolbar solo marca; el bucle reconstruye
# ---------------------------------------------------------------------------

def test_hot_reload_el_toolbar_solo_marca_y_el_bucle_aplica(entorno):
    cli._slash_estilo("sistema.ok color #ff00ff")
    consola = cli._console
    doc = json.loads(A.RUTA_ESTILO.read_text(encoding="utf-8"))
    doc["elementos"]["sistema.ok"]["color"] = "#00ff00"
    A.RUTA_ESTILO.write_text(json.dumps(doc), encoding="utf-8")
    m = A._estado["mtime"] + 10 ** 9
    os.utime(A.RUTA_ESTILO, ns=(m, m))
    toolbar = cli._pie_prompt(None)
    frag = toolbar()
    assert A.recarga_pendiente() is True
    assert cli._console is consola, "el toolbar NO reconstruye la Console (reentrante)"
    assert _ok_cl_hex() == "#ff00ff"
    assert list(frag)[0][0] == "class:marco"
    cli._aplicar_recarga_estilo()
    assert cli._console is not consola
    assert _ok_cl_hex() == "#00ff00"
    assert "recargado" in entorno.texto()
    assert A.recarga_pendiente() is False
    # sin cambio: no-op silencioso
    entorno.salida.clear()
    toolbar()
    cli._aplicar_recarga_estilo()
    assert entorno.salida == []


def test_hot_reload_con_fichero_roto_avisa_y_conserva_lo_anterior(entorno):
    cli._slash_estilo("sistema.ok color #ff00ff")
    A.RUTA_ESTILO.write_text("{roto", encoding="utf-8")
    m = A._estado["mtime"] + 10 ** 9
    os.utime(A.RUTA_ESTILO, ns=(m, m))
    cli._pie_prompt(None)()
    cli._aplicar_recarga_estilo()
    assert any("sigo con el estilo anterior" in d for _, d in entorno.avisos)
    assert A.estilo_de("sistema.ok").color == "#ff00ff"
    # no se reintenta en cada vuelta hasta que el mtime cambie
    entorno.avisos.clear()
    cli._pie_prompt(None)()
    cli._aplicar_recarga_estilo()
    assert entorno.avisos == []


def test_el_toolbar_no_deja_rastro_sin_fichero(entorno):
    """REGLA UNO: sin estilo.json el pie del prompt es el de siempre (el golden
    de tests/test_ux_aspecto.py lo fija en bytes; aqui, la forma)."""
    frag = list(cli._pie_prompt(lambda: "barra")())
    assert frag == [("class:marco", cli._REGLA * cli._ancho_marco()),
                    ("class:estado", "\nbarra")]
    assert A.recarga_pendiente() is False


def test_ver_de_un_elemento_con_glow_y_animacion_no_tumba_el_repl(entorno):
    """REGRESION (cazada tecleando en P5): '/estilo ver prompt.etiqueta'
    moria con AttributeError ('EstiloResuelto' no tiene 'glow') y se llevaba
    el REPL entero; P4 solo lo habia probado con sistema.ok (sin GLOW)."""
    for id in ("prompt.etiqueta", "prompt.marco", "barra.estado", "banner.arte", "spinner.pensar"):
        entorno.salida.clear()
        cli._slash_estilo(f"ver {id}")
        t = entorno.texto()
        assert id in t and "glow" in t and "animacion" in t, (id, t)
    assert entorno.avisos == []


def test_set_en_respuesta_markdown_y_codigo_ya_no_avisa_P6(entorno):
    """P6: los sub-estados del markdown los aplica tema_rich en caliente y
    respuesta.codigo es el tema pygments del markdown vivo: sin aviso E8."""
    cli._slash_estilo("respuesta.markdown estados.h2.color #ffaa00")
    t = entorno.texto()
    assert "(guardado)" in t and "se aplica cuando" not in t
    assert cli._console.get_style("markdown.h2").color.get_truecolor().hex == "#ffaa00"
    entorno.salida.clear()
    cli._slash_estilo("respuesta.codigo texto dracula")
    t = entorno.texto()
    assert "(guardado)" in t and "se aplica cuando" not in t
    from cognia.ux import markdown_vivo
    assert markdown_vivo.config()[1] == "dracula"


# ---------------------------------------------------------------------------
# P9 / E6: el hot reload de estilo.json llega al PROMPT en el turno siguiente
# ---------------------------------------------------------------------------

def test_hot_reload_editar_el_fichero_a_mano_cambia_el_prompt_al_siguiente_turno(entorno):
    """Edicion EXTERNA (otro proceso, un editor): el toolbar del prompt vivo
    solo ve el mtime; el bucle del REPL aplica con el prompt ya devuelto y el
    prompt siguiente ya dice el texto nuevo (sin reiniciar)."""
    cli._slash_estilo("prompt.etiqueta texto jarvis")
    assert list(cli._mensaje_prompt())[1][1] == " jarvis"
    doc = json.loads(A.RUTA_ESTILO.read_text(encoding="utf-8"))
    doc["elementos"]["prompt.etiqueta"]["texto"] = "friday"
    doc["elementos"]["prompt.etiqueta"]["animacion"] = {"activa": True}
    A.RUTA_ESTILO.write_text(json.dumps(doc), encoding="utf-8")
    m = A._estado["mtime"] + 10 ** 9
    os.utime(A.RUTA_ESTILO, ns=(m, m))
    # el prompt vivo se redibuja (tecla): SOLO marca
    cli._pie_prompt(None)()
    assert A.recarga_pendiente() is True
    assert list(cli._mensaje_prompt())[1][1] == " jarvis", "dentro del render no se aplica"
    # session.prompt() devolvio: el bucle aplica antes de despachar la linea
    cli._aplicar_recarga_estilo()
    assert A.recarga_pendiente() is False
    assert A.texto("prompt.etiqueta") == "friday"
    assert list(cli._mensaje_prompt())[1][1] == " friday"
    assert A.estilo_de("prompt.etiqueta").animacion.activa is True
    assert "recargado" in entorno.texto()
    # el fichero editado no puede sobrevivir al test: el teardown de `entorno`
    # recarga desde tmp y "friday" se colaba en test_marco_prompt (medido)
    A.RUTA_ESTILO.unlink()
    A.reset()


def test_hot_reload_el_bucle_del_repl_aplica_tras_get_input_y_antes_de_despachar():
    """E6 en el fuente: el toolbar no reconstruye nada; repl() llama
    _aplicar_recarga_estilo() justo despues de _get_input() y antes del
    dispatch de la linea."""
    pie = inspect.getsource(cli._pie_prompt)
    assert "recargar_si_cambio()" in pie
    assert "_aplicar_tema_en_caliente" not in pie and "aplicar_recarga" not in pie.replace(
        "_aplicar_recarga_estilo) con el prompt devuelto", "")
    repl = inspect.getsource(cli.repl)
    i = repl.index("raw = _strip_input_bom(_get_input())")
    j = repl.index("_aplicar_recarga_estilo()")
    assert i < j
    # entre los dos solo hay el manejo de EOF/Ctrl-C: ningun dispatch
    assert "_dispatch" not in repl[i:j] and "_run(" not in repl[i:j]
