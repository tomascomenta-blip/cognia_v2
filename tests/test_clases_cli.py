# -*- coding: utf-8 -*-
"""
tests/test_clases_cli.py
========================
LA PUERTA del cuaderno de clase en el REPL: los subcomandos nuevos de
`/grabar-clase` (cognia/cli.py) y los dos cableados sin los cuales las piezas
de cognia/clases son inertes.

QUE SE PRUEBA AQUI Y QUE NO. Aqui NO se vuelve a probar cognia/clases (eso ya
lo hacen tests/test_clases_*.py contra los modulos): se prueba que el CLI los
ALCANZA. Las tres cosas que ningun test del modulo puede ver:

  1. `servidor_vivo.fijar_pagina(vista_viva.render)` -- el gancho existe y la
     pagina existe, pero hasta esta entrega NADIE los unia y `GET /` servia el
     placeholder del transporte.
  2. La familia doc_* solo se ANUNCIA al abrir el cuaderno (COGNIA_DOC_TOOLS).
     El flag no lo ponia ningun comando: siete tools registradas e invisibles.
  3. Que las lineas de resultado SOBREVIVAN al modo sencillo. `_print_line`
     tira la linea ENTERA si lleva '[detail]', y el modo sencillo es el
     default: dos comandos nuevos salieron MUDOS en el tecleado por eso.

TODO va a un directorio temporal (COGNIA_CLASES_DIR, cli._CONFIG_PATH): nada
toca el cuaderno real del duenio. Ningun import pesado a nivel de modulo
(matplotlib, PIL, soundcard): el CI de ubuntu instala solo requirements.txt.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import tomllib
import warnings
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


_ENV_TOCADAS = ("COGNIA_CLASES_REFINADO", "COGNIA_DOC_TOOLS",
                "COGNIA_DOC_MATERIA", "COGNIA_REMOTO")


@pytest.fixture
def cli_clases(tmp_path, monkeypatch):
    """El CLI con su config y su cuaderno en tmp, y `_print_line` capturado.

    LA ENV SE RESTAURA A MANO. El codigo bajo prueba escribe en os.environ por
    su cuenta (`familias.activar` pone el flag, `_clases_sembrar_env` siembra
    el del refinado) y eso monkeypatch NO lo revierte: un COGNIA_DOC_TOOLS=1
    que sobrevive a este fichero le cambia el catalogo a los tests que corran
    despues, que es un banco contaminado y se diagnostica fatal.
    """
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(tmp_path / "clases"))
    previas = {k: os.environ.get(k) for k in _ENV_TOCADAS}
    for k in _ENV_TOCADAS:
        os.environ.pop(k, None)
    import cognia.cli as cli
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / "cognia_config.json")
    lineas: list = []
    monkeypatch.setattr(cli, "_print_line", lambda t: lineas.append(str(t)))
    monkeypatch.setattr(cli, "_show_response",
                        lambda t, *a, **k: lineas.append("RESP: " + str(t)))
    degradados: list = []
    monkeypatch.setattr(cli, "_aviso_degradado",
                        lambda via, detalle="", backend=None:
                        degradados.append((via, str(detalle))))
    cli._CLASES_CIERRE.update({"jornada": "", "hilo": None, "jv": None,
                               "t0": 0.0, "t_captura": 0.0, "t_fin": 0.0,
                               "resumen": None, "error": "", "inline": False})
    cli._CLASES_CIERRE_AVISOS.clear()
    yield cli, lineas, degradados
    cli._CLASES_CIERRE.update({"jornada": "", "hilo": None, "jv": None,
                               "t0": 0.0, "t_captura": 0.0, "t_fin": 0.0,
                               "resumen": None, "error": "", "inline": False})
    cli._CLASES_CIERRE_AVISOS.clear()
    for k, v in previas.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _texto(lineas) -> str:
    return "\n".join(lineas)


# ── La PUERTA (tilde 1 del checklist de CLAUDE.md) ──────────────────────────

def test_la_ficha_del_comando_existe_y_nombra_los_subcomandos_nuevos():
    """`/grabar-clase ayuda` imprimia CADENA VACIA: la clave no estaba en
    _CMD_DETAILS y `.get(..., "")` se lo tragaba sin decir nada."""
    import cognia.cli as cli
    ficha = cli._CMD_DETAILS.get("/grabar-clase", "")
    assert ficha, "sin entrada en _CMD_DETAILS, '/grabar-clase ayuda' no dice nada"
    for palabra in ("vivo", "widget", "forzar", "pegar", "pdf", "imagen-buscar",
                    "refinar", "doc estado", "formula"):
        assert palabra in ficha, palabra


def test_la_descripcion_de_ayuda_lista_los_subcomandos_nuevos():
    """_CMD_DESCRIPTIONS es lo que alimenta /ayuda y el autocompletado: un
    subcomando que no sale ahi, para el duenio no existe."""
    import cognia.cli as cli
    desc = cli._CMD_DESCRIPTIONS["/grabar-clase"]
    for palabra in ("vivo", "widget", "pausar", "mutear", "forzar", "pegar",
                    "pdf", "formula", "grafico", "imagen-buscar",
                    "imagen-usar", "refinar", "doc estado"):
        assert palabra in desc, palabra


def test_todos_los_subcomandos_del_contrato_estan_registrados():
    """El punto de extension: un dict, no un if-chain enterrado."""
    import cognia.cli as cli
    for nombre in ("widget", "vivo", "pausar", "reanudar", "mutear",
                   "desmutear", "forzar", "refinar", "formula", "grafico",
                   "imagen-buscar", "imagen-usar", "pegar", "pdf", "doc"):
        assert nombre in cli._CLASES_SUBCOMANDOS, nombre
        assert callable(cli._CLASES_SUBCOMANDOS[nombre])


def test_el_despacho_del_registro_gana_al_if_chain(cli_clases, monkeypatch):
    """`/grabar-clase pdf` tiene que llegar a su manejador y no morir en el
    'subcomando desconocido' del final."""
    cli, lineas, _ = cli_clases
    visto = []
    monkeypatch.setitem(cli._CLASES_SUBCOMANDOS, "pdf",
                        lambda resto, ai=None: visto.append(resto))
    cli._slash_grabar_clase("pdf mi/ruta.html")
    assert visto == ["mi/ruta.html"]
    assert "desconocido" not in _texto(lineas)


# ── EXPANDIBLE (tilde 2): config persistida, default sensato, on/off ────────

def test_las_claves_de_config_tienen_default_sensato():
    import cognia.cli as cli
    d = cli._CONFIG_DEFAULTS
    assert d["clases_refinado"] == "on"
    assert d["clases_doc_tools"] == "on"
    assert d["clases_vivo_app"] == "on"
    assert int(d["clases_imagenes"]) > 0


def test_la_config_viaja_a_la_env_que_leen_los_modulos(cli_clases):
    """clases_refinado -> COGNIA_CLASES_REFINADO. Sin esta siembra la clave
    seria una config que no decide nada (el fallo que ya se pago con
    bots_max_hops)."""
    cli, _, _ = cli_clases
    cli._save_config({**cli._CONFIG_DEFAULTS, "clases_refinado": "off"})
    cli._clases_sembrar_env()
    assert os.environ["COGNIA_CLASES_REFINADO"] == "0"


def test_una_env_puesta_a_mano_gana_a_la_config(cli_clases, monkeypatch):
    """Quien exporta la variable antes de arrancar dice algo mas concreto que
    la config de ayer."""
    cli, _, _ = cli_clases
    monkeypatch.setenv("COGNIA_CLASES_REFINADO", "1")
    cli._save_config({**cli._CONFIG_DEFAULTS, "clases_refinado": "off"})
    cli._clases_sembrar_env()
    assert os.environ["COGNIA_CLASES_REFINADO"] == "1"


def test_refinar_on_off_persiste_y_siembra(cli_clases):
    cli, _, _ = cli_clases
    cli._clases_refinar("off")
    assert cli._load_config()["clases_refinado"] == "off"
    assert os.environ["COGNIA_CLASES_REFINADO"] == "0"
    cli._clases_refinar("on")
    assert cli._load_config()["clases_refinado"] == "on"
    assert os.environ["COGNIA_CLASES_REFINADO"] == "1"


def test_un_si_no_invalido_en_la_config_se_dice_y_no_se_traga(cli_clases):
    cli, _, degradados = cli_clases
    assert cli._clases_encendido({"clases_doc_tools": "quiza"},
                                 "clases_doc_tools") is True
    assert any(v == "clases.config" for v, _ in degradados)


# ── NO CALLA (tilde 3): nada de vacios silenciosos ──────────────────────────

def test_el_ok_y_su_detalle_van_en_lineas_distintas(cli_clases):
    """`_print_line` tira la linea ENTERA si lleva '[detail]' y el modo
    sencillo es el DEFAULT: un '[ok]...[/ok] [detail]...[/detail]' en una
    sola llamada desaparecia con el detalle y el comando no contestaba nada.
    Cazado tecleando '/grabar-clase formula ...'."""
    from cognia.simple_mode import should_show_detail
    cli, lineas, _ = cli_clases
    cli._clases_ok("salio bien", "la letra pequenia")
    assert len(lineas) == 2
    assert "[detail]" not in lineas[0]
    assert should_show_detail(lineas[0]), "el resultado se pierde en sencillo"


def test_la_lista_de_imagenes_sobrevive_al_modo_sencillo(cli_clases,
                                                         monkeypatch):
    """Las lineas de resultado de imagen-buscar llevaban '[detail]' y el
    comando salia MUDO en modo sencillo (cazado tecleando 'imagen-buscar
    celula animal': salida vacia)."""
    from cognia import busqueda_imagenes as bi
    from cognia.simple_mode import should_show_detail
    cli, lineas, _ = cli_clases
    falso = [{"titulo": "Celula", "url_imagen": "https://x/a.png",
              "url_pagina": "https://x/a", "autor": "Alguien",
              "licencia": "CC0", "licencia_url": "", "ancho": 800,
              "alto": 600, "fuente": "commons",
              "atribucion": "Celula - Alguien - CC0 - https://x/a",
              "atribucion_completa": True}]
    monkeypatch.setattr(bi, "buscar_con_avisos",
                        lambda *a, **k: (falso, []))
    cli._clases_imagen_buscar("celula")
    visibles = [ln for ln in lineas if should_show_detail(ln)]
    assert any("Celula" in ln for ln in visibles), "el titulo no se ve"
    assert any("CC0" in ln for ln in visibles), "la licencia no se ve"


def test_imagen_usar_sin_busqueda_previa_lo_dice(cli_clases):
    cli, lineas, _ = cli_clases
    cli._CLASES_BUSQUEDA["resultados"] = []
    cli._clases_imagen_usar("2")
    assert "imagen-buscar" in _texto(lineas)


def test_el_estado_del_refinado_no_revienta_con_el_backend_real(cli_clases):
    """`refinado.estado()['backend']` es una CADENA (llm_local.describir()),
    no un dict. El render lo trataba como dict y el comando moria con
    AttributeError: se cazo TECLEANDOLO, la suite no lo veia."""
    cli, lineas, _ = cli_clases
    cli._clases_refinar("estado")
    assert "backend" in _texto(lineas)


def test_forzar_sin_lock_lo_dice_en_vez_de_callarse(cli_clases):
    cli, lineas, _ = cli_clases
    cli._clases_forzar("")
    assert "lock" in _texto(lineas).lower()


# ── CABLEADO 1: la pagina del cuaderno en vivo ──────────────────────────────

def test_vivo_une_el_transporte_con_la_pagina(cli_clases, monkeypatch):
    """EL CABLE QUE FALTABA. `servidor_vivo.fijar_pagina` es un gancho a
    proposito (el transporte tiene que arrancar aunque la pagina reviente),
    pero nadie lo llamaba nunca y `GET /` servia el placeholder."""
    from cognia.clases import servidor_vivo as sv
    from cognia.clases import vista_viva as vv
    cli, lineas, _ = cli_clases
    puestas = []
    monkeypatch.setattr(sv, "fijar_pagina", lambda render: puestas.append(render))
    monkeypatch.setattr(sv, "arrancar",
                        lambda **k: {"url": "http://127.0.0.1:1/?t=x",
                                     "base": "http://127.0.0.1:1", "puerto": 1,
                                     "token": "x", "nuevo": True,
                                     "handshake": ""})
    monkeypatch.setattr(cli, "_abrir_en_navegador", lambda: False)
    cli._clases_vivo("")
    assert puestas == [vv.render], "el cuaderno no queda inyectado en el servidor"
    assert "http://127.0.0.1:1/?t=x" in _texto(lineas), "no dice la URL"


def test_la_pagina_inyectada_no_es_el_placeholder():
    """El gancho y la pagina encajan de verdad: `render(ctx)` devuelve el
    cuaderno, no el placeholder del transporte."""
    from cognia.clases import vista_viva as vv
    html = vv.render({"base": "http://127.0.0.1:1", "token": "x", "puerto": 1,
                      "eventos": "/eventos?t=x", "estado": "/estado?t=x",
                      "adj": "/adj"})
    assert "placeholder del transporte" not in html
    assert 'id="doc"' in html and "@media print" in html


# ── CABLEADO 2: la familia doc_* se anuncia al abrir el cuaderno ────────────

def test_abrir_el_cuaderno_anuncia_las_tools_del_documento(cli_clases):
    """Siete tools registradas y ningun comando que ponga su flag = siete
    tools que para el duenio no existen."""
    cli, _, _ = cli_clases
    res = cli._clases_encender_doc_tools("Biologia")
    assert res.get("ok"), res
    assert os.environ.get("COGNIA_DOC_TOOLS") == "1"
    assert os.environ.get("COGNIA_DOC_MATERIA") == "Biologia"
    from cognia.agent.tools import TOOLS
    assert [t for t in TOOLS if t.startswith("doc_")]


def test_la_config_puede_apagar_el_anuncio_de_las_tools(cli_clases):
    """El techo del catalogo esta MEDIDO (46 tools bajan el camino feliz de
    4,25/5 a 2,5/5): tiene que haber un off."""
    cli, _, _ = cli_clases
    cli._save_config({**cli._CONFIG_DEFAULTS, "clases_doc_tools": "off"})
    res = cli._clases_encender_doc_tools("Biologia")
    assert res.get("ok") is False
    assert "clases_doc_tools" in res.get("detalle", "")


def test_la_familia_documento_esta_en_el_catalogo_de_familias():
    """El reconocimiento por prefijo y el flag opt-in, como las demas."""
    from cognia.harness import familias
    fam = familias.FAMILIAS["documento"]
    assert fam["flag"] == "COGNIA_DOC_TOOLS"
    assert fam["prefijo"] == "doc_"


def test_no_se_toma_por_materia_el_sin_clasificar(cli_clases, monkeypatch):
    """'(sin clasificar aun)' NO es una materia: tomarla por buena crearia en
    el cuaderno del duenio un documento con ese nombre."""
    from cognia.clases import jornada as jor
    cli, _, _ = cli_clases
    monkeypatch.setattr(jor, "estado",
                        lambda: {"grabando": True,
                                 "materia": "(sin clasificar aun)"})
    assert cli._clases_materia_actual() == ""
    monkeypatch.setattr(jor, "estado",
                        lambda: {"grabando": False, "materia": "Fisica"})
    assert cli._clases_materia_actual() == "", \
        "la materia de una jornada CERRADA escribiria en el documento de ayer"


# ── El parser de `grafico` ──────────────────────────────────────────────────

@pytest.mark.parametrize("texto, ys, etiquetas", [
    ("sin(x)*x", None, None),
    ("x**2", None, None),
    ("3,5,8", [3.0, 5.0, 8.0], None),
    ("lunes=3, martes=5", [3.0, 5.0], ["lunes", "martes"]),
    ("3", None, None),                      # un solo numero: es una expresion
    ("a,b,c", None, None),                  # ni numeros ni pares: expresion
])
def test_grafico_deduce_datos_o_expresion(texto, ys, etiquetas):
    """Traducir UNA linea tecleada a los argumentos de mates.graficar es lo
    que hace que 'sin(x)*x' funcione sin que nadie escriba 'tipo='."""
    import cognia.cli as cli
    assert cli._clases_numeros(texto) == (ys, etiquetas)


# ── EMPAQUETADO: lo que se pierde EN SILENCIO al instalar el wheel ─────────

def test_el_svg_del_cerebrito_viaja_al_wheel():
    """package-data no incluye NADA que no se declare. Sin esta entrada el
    cuaderno instalado sale sin icono y degrada por 'clases.vista_viva.
    cerebro' solo en la version instalada, que es indiagnosticable."""
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    patrones = datos["tool"]["setuptools"]["package-data"]["cognia.clases"]
    assert any(p.endswith("*.svg") for p in patrones), patrones
    assert (RAIZ / "cognia" / "clases" / "assets" / "cerebro.svg").exists()


def test_el_extra_clases_trae_lo_que_dibuja_formulas_y_graficas():
    """`mates` necesita matplotlib y sympy; sin declararlos, `pip install
    cognia-ai[clases]` deja formula y grafico muertos con un pip install en
    el mensaje que nadie puso en el paquete."""
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    extra = " ".join(datos["project"]["optional-dependencies"]["clases"])
    for paquete in ("soundcard", "faster-whisper", "matplotlib", "sympy"):
        assert paquete in extra, paquete


def test_requirements_no_carga_al_ci_con_lo_pesado_de_clases():
    """requirements.txt es lo UNICO que instala el CI de ubuntu: soundcard
    (WASAPI) y faster-whisper no pintan nada ahi, y los tests de mates ya se
    saltan solos con importorskip."""
    req = (RAIZ / "requirements.txt").read_text(encoding="utf-8").lower()
    for paquete in ("soundcard", "faster-whisper", "matplotlib", "sympy"):
        assert paquete not in req, paquete


# ── EL CIERRE EN DOS FASES: 'parar' no puede secuestrar el REPL ─────────────
# El verificador midio 'parar' cuatro veces sobre jornadas de 35-90 s: 3 de 4
# NO devolvieron el prompt (>300 s, >420 s, >165 s) y hubo que matar el
# proceso. La causa es de DISENO: la deteccion definitiva de materias y los
# apuntes hablan con el modelo local dentro del turno. Lo que se prueba aqui
# es el contrato nuevo -- lo urgente (dejar de grabar) pasa en el turno, lo
# caro se va a un hilo, y el duenio puede consultarlo y no pierde nada.


class _GrabadorFalso:
    """El grabador de la jornada, con lo unico que el CLI le mira: `viva`.

    Existe separado de la jornada porque la FRONTERA de la fase urgente pasa
    justo por aqui: `jv.grabador.viva` (ya no entra audio) es lo que devuelve
    el prompt, y `jv.viva` (grabador O transcripcion) es lo que tarda."""

    def __init__(self):
        self.viva = True


class _JornadaFalsa:
    """Una jornada viva de mentira con lo unico que el CLI le mira: `nombre`,
    `grabador` y `viva`. No se puede usar la de verdad: abrir el loopback
    WASAPI en un test no es posible y `parar()` real llamaria al modelo."""

    def __init__(self, nombre: str = "2026-08-31"):
        self.nombre = nombre
        self.grabador = _GrabadorFalso()
        self.viva = True


@pytest.fixture
def cierre(cli_clases, monkeypatch):
    """`jornada.viva/parar` de mentira + el carril de fondo FORZADO.

`_clases_hay_carril()` es False en pytest (ni PromptSession ni consola),
    y ahi el cierre corre INLINE a proposito: en un pipe o en el CI, un hilo
    daemon moriria con el proceso antes de generar los apuntes. Para probar el
    carril de fondo hay que decir explicitamente que si lo hay.
    """
    cli, lineas, degradados = cli_clases
    from cognia.clases import cuaderno as cua
    from cognia.clases import jornada as jor
    jv = _JornadaFalsa()
    suelta = threading.Event()
    visto = {"paradas": 0}

    def _parar_falso():
        visto["paradas"] += 1
        jv.grabador.viva = False   # fase 1: ya no entra audio, y esta en disco
        jv.viva = False
        suelta.wait(20)            # fase 2: lo caro (aqui, gobernado)
        return {"jornada": jv.nombre, "segundos": 95.0, "avisos": []}

    monkeypatch.setattr(jor, "viva", lambda: jv if jv.viva else None)
    monkeypatch.setattr(jor, "parar", _parar_falso)
    monkeypatch.setattr(cua, "sesiones_de", lambda nombre: [])
    monkeypatch.setattr(cli, "_clases_hay_carril", lambda: True)
    yield cli, lineas, jv, suelta, visto
    suelta.set()
    hilo = cli._CLASES_CIERRE.get("hilo")
    if hilo is not None:
        hilo.join(timeout=10)


def test_parar_devuelve_el_prompt_sin_esperar_a_los_apuntes(cierre):
    """LA REGRESION DE GRAVE 1. Con el cierre entero dentro del turno, esto
    tarda lo que tarde el modelo (minutos); con las dos fases, vuelve en
    cuanto la grabacion esta a salvo en disco."""
    cli, lineas, jv, suelta, visto = cierre
    t0 = time.time()
    cli._slash_grabar_clase("parar")
    tardanza = time.time() - t0
    assert tardanza < 5.0, f"el prompt tardo {tardanza:.1f} s en volver"
    assert visto["paradas"] == 1, "no se llego a parar la grabacion"
    assert cli._clases_cierre_vivo(), "el trabajo caro no quedo en el hilo"
    from cognia.simple_mode import should_show_detail
    visibles = [ln for ln in lineas if should_show_detail(ln)]
    assert any("ya no entra audio" in ln and "en disco" in ln
               for ln in visibles), "no dice que la clase ya esta guardada"
    assert any("cierre" in ln for ln in visibles), \
        "no dice como consultar el trabajo que sigue"


def test_el_cierre_se_consulta_y_anuncia_su_final_entre_turnos(cierre):
    """La puerta del trabajo que ya no ocurre delante del duenio: en que fase
    esta y si su clase esta guardada. Y el final NO se imprime desde el hilo
    (pisaria el prompt): se drena entre turnos."""
    cli, lineas, jv, suelta, visto = cierre
    cli._slash_grabar_clase("parar")
    lineas.clear()
    cli._slash_grabar_clase("cierre")
    texto = _texto(lineas)
    assert "apuntes" in texto and "fase" in texto
    assert "YA esta guardada" in texto

    lineas.clear()
    suelta.set()
    cli._CLASES_CIERRE["hilo"].join(timeout=10)
    assert not cli._clases_cierre_vivo()
    assert not lineas, "el hilo imprimio por su cuenta y pisaria el prompt"
    cli._clases_cierre_drenar()
    texto = _texto(lineas)
    assert "cerrada del todo" in texto
    assert "1 min" in texto, texto        # los 95 s del resumen


def test_ctrl_c_corta_la_espera_y_NO_el_cierre(cierre, monkeypatch):
    """Ctrl-C mientras se espera a que cierre la captura devuelve el prompt,
    pero el hilo sigue: matarlo a media escritura es lo unico que podria
    corromper el cuaderno."""
    cli, lineas, jv, suelta, visto = cierre
    # que la fase 1 NO termine sola: asi el Ctrl-C cae dentro de la espera
    from cognia.clases import jornada as jor

    def _parar_lento():
        visto["paradas"] += 1
        suelta.wait(20)
        jv.grabador.viva = False
        jv.viva = False
        return {"jornada": jv.nombre, "segundos": 10.0, "avisos": []}

    monkeypatch.setattr(jor, "parar", _parar_lento)

    def _sleep_que_interrumpe(_s):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", _sleep_que_interrumpe)
    cli._slash_grabar_clase("parar")      # no puede propagar el KeyboardInterrupt
    assert cli._clases_cierre_vivo(), "el Ctrl-C mato el cierre"
    assert "Ctrl-C" in _texto(lineas)
    suelta.set()
    cli._CLASES_CIERRE["hilo"].join(timeout=10)
    assert cli._CLASES_CIERRE_AVISOS, "el cierre no dejo su parte"


def test_sin_carril_de_fondo_el_cierre_se_hace_EN_EL_TURNO(cli_clases,
                                                           monkeypatch):
    """En un pipe, en el CI o con COGNIA_SIN_FONDO=1 no hay prompt que
    proteger y un hilo daemon seria una TRAMPA: el proceso terminaria antes
    que el y los apuntes no se generarian nunca."""
    cli, lineas, _ = cli_clases
    from cognia.clases import cuaderno as cua
    from cognia.clases import jornada as jor
    jv = _JornadaFalsa()

    def _parar_falso():
        jv.grabador.viva = False
        jv.viva = False
        return {"jornada": jv.nombre, "segundos": 60.0, "avisos": []}

    monkeypatch.setattr(jor, "viva", lambda: jv if jv.viva else None)
    monkeypatch.setattr(jor, "parar", _parar_falso)
    monkeypatch.setattr(cua, "sesiones_de", lambda nombre: [])
    monkeypatch.setattr(cli, "_clases_hay_carril", lambda: False)
    cli._slash_grabar_clase("parar")
    assert not cli._clases_cierre_vivo()
    assert "cerrada del todo" in _texto(lineas), "el parte final no salio"


def test_un_fallo_del_cierre_no_muere_mudo(cierre, monkeypatch):
    """Si `parar()` revienta en el hilo, el duenio se entera y se le dice que
    lo grabado NO se perdio."""
    cli, lineas, jv, suelta, visto = cierre
    from cognia.clases import jornada as jor

    def _parar_roto():
        jv.grabador.viva = False
        jv.viva = False
        raise RuntimeError("el disco dijo que no")

    monkeypatch.setattr(jor, "parar", _parar_roto)
    cli._slash_grabar_clase("parar")
    # sin lineas.clear(): un `parar()` que revienta enseguida puede haber
    # terminado ANTES de que la espera devuelva, y ahi el propio 'parar' ya
    # drena el parte. Se junta lo de los dos caminos.
    hilo = cli._CLASES_CIERRE.get("hilo")
    if hilo is not None:
        hilo.join(timeout=10)
    cli._clases_cierre_drenar()
    texto = _texto(lineas)
    assert "fallo" in texto and "apuntes" in texto
    assert cli._clases_cierre_fase() == "fallo"


def test_iniciar_con_un_cierre_vivo_lo_dice_en_vez_de_chocar(cierre):
    """El lock de grabacion no se suelta hasta que acaban los apuntes
    (jornada.py lo suelta al final de parar()): sin este aviso, 'iniciar'
    fallaria con un 'ya hay una grabacion' que no explica nada."""
    cli, lineas, jv, suelta, visto = cierre
    cli._slash_grabar_clase("parar")
    lineas.clear()
    cli._slash_grabar_clase("iniciar")
    texto = _texto(lineas)
    assert "cerrando" in texto and "cierre" in texto


def test_el_estado_dice_que_el_cierre_sigue_en_marcha(cierre, monkeypatch):
    """'ultima jornada cerrada' no es 'los apuntes ya estan'."""
    cli, lineas, jv, suelta, visto = cierre
    from cognia.clases import jornada as jor
    cli._slash_grabar_clase("parar")
    # con un cierre vivo el cuaderno NUNCA esta vacio (la jornada ya se
    # escribio): se le da el estado que tendria en disco.
    monkeypatch.setattr(jor, "estado", lambda: {
        "grabando": False, "jornada": jv.nombre, "estado": "cerrada",
        "materia": "", "pausada": False, "muteada": False, "segundos": 95.0,
        "trozos": 3, "transcritos": 3, "silencios": 0, "descartados": 0,
        "sesiones": 1, "materias": ["Fisica"], "aviso": "", "avisos": [],
        "lock": {}, "otro_proceso": False})
    lineas.clear()
    cli._slash_grabar_clase("")
    assert "cierre de" in _texto(lineas)


def test_parar_esta_en_el_registro_y_no_duplicado_en_el_if_chain():
    """El punto de extension manda: dos implementaciones del mismo subcomando
    es peor que ninguna."""
    import cognia.cli as cli
    for alias in ("parar", "fin", "stop", "off"):
        assert cli._CLASES_SUBCOMANDOS[alias] is cli._clases_parar
    assert cli._CLASES_SUBCOMANDOS["cierre"] is cli._clases_cierre
    fuente = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    assert 'if cmd in ("parar", "fin", "stop", "off"):' not in fuente


# ── GRAVE 2: los subcomandos que salian MUDOS en el modo por defecto ───────

def test_iniciar_dice_que_graba_en_modo_sencillo(cli_clases, monkeypatch):
    """LA REGRESION DE GRAVE 2. `_print_line` tira la linea ENTERA si lleva
    '[detail]', y 'iniciar' imprimia "[ok]grabando la jornada X[/ok]
    [detail](...)[/detail]" de una sola vez: el duenio tecleaba 'iniciar' y le
    volvia el prompt PELADO."""
    from cognia.simple_mode import should_show_detail
    cli, lineas, _ = cli_clases
    from cognia.clases import jornada as jor
    jv = _JornadaFalsa("2026-08-31-2")
    monkeypatch.setattr(jor, "arrancar",
                        lambda **k: (jv, "audio del sistema (loopback)"))
    monkeypatch.setattr(jor, "viva", lambda: None)
    cli._slash_grabar_clase("iniciar")
    visibles = [ln for ln in lineas if should_show_detail(ln)]
    assert any("grabando" in ln for ln in visibles), "no dice que graba"
    assert any(jv.nombre in ln for ln in visibles), "no dice que jornada"
    assert any("parar" in ln for ln in visibles), "no dice como se cierra"


def test_olvidar_plan_lista_las_acciones_en_modo_sencillo(cli_clases,
                                                          monkeypatch):
    """Mismo bug que 'iniciar': la fila llevaba su detalle pegado y el modo
    sencillo se llevaba la fila entera, asi que 'olvidar plan' no listaba
    NADA."""
    from cognia.simple_mode import should_show_detail
    from cognia.clases import olvido as ol
    cli, lineas, _ = cli_clases
    monkeypatch.setattr(ol, "plan", lambda: [
        {"accion": "borrar audio", "objetivo": "2026-08-01/audio",
         "bytes": 2048000, "por_que": "mas de 30 dias"}])
    cli._slash_grabar_clase("olvidar plan")
    visibles = [ln for ln in lineas if should_show_detail(ln)]
    assert any("2026-08-01/audio" in ln for ln in visibles), \
        "el plan de olvido sale mudo en el modo por defecto"


def test_ningun_subcomando_de_clases_habla_SOLO_por_detail():
    """La trampa, cazada en el CODIGO: un `_print_line` que mezcla el
    resultado con '[detail]' en la MISMA cadena desaparece entero en modo
    sencillo. Se prohibe en el bloque de /grabar-clase."""
    import re
    fuente = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    ini = fuente.index("# CUADERNO DE CLASE: los subcomandos NUEVOS")
    fin = fuente.index("def _slash_compilar")
    bloque = fuente[ini:fin]
    malas = []
    for m in re.finditer(r'_print_line\((?:\s*f?"[^"]*"\s*)+\)', bloque):
        t = m.group()
        if "[detail]" in t and any(k in t for k in ("[ok]", "[warn_cl]",
                                                    "[err_cl]", "[info_dim]",
                                                    "[mod]")):
            malas.append(" ".join(t.split())[:90])
    assert not malas, malas


def test_la_ayuda_lista_lo_que_se_teclea_al_empezar_el_curso():
    """'marcar', 'materias <a,b,c>' y 'audio <ruta>' existen desde el
    principio y no salian en la linea de Uso de /ayuda; 'cierre' es nuevo."""
    import cognia.cli as cli
    desc = cli._CMD_DESCRIPTIONS["/grabar-clase"]
    for palabra in ("marcar", "materias <a,b,c>", "audio <ruta>", "cierre"):
        assert palabra in desc, palabra


# ── MEDIO 4: la basura del modelo no llega a la cara del duenio ────────────

def test_la_respuesta_ilegible_del_modelo_se_resume_y_no_se_escupe():
    """Literal, al parar una jornada: "clases/materias: respuesta del modelo
    fuera de la lista (禚 瑜` 瑜` ... 瑜4月:Spo)". Se resume, se dice que paso
    y se conserva la cola, que es donde el modulo dice que hizo en su lugar."""
    import cognia.cli as cli
    crudo = ("clases/materias: respuesta del modelo fuera de la lista "
             "(\u79da \u745c` \u745c` \u745c4\u6708:Spo); queda el nombre "
             "deterministico")
    visto = cli._resumir_para_pantalla(crudo)
    assert "\u745c" not in visto and "\u79da" not in visto
    assert "ilegible" in visto
    assert "queda el nombre deterministico" in visto, \
        "se perdio lo que se hizo en su lugar"
    assert "fuera de la lista" in visto


def test_un_motivo_normal_no_se_toca():
    """El saneado no puede volverse un filtro que muerde lo legible."""
    import cognia.cli as cli
    crudo = ("no pude copiar C:/temp/pizarra.png: FileNotFoundError "
             "[WinError 2] El sistema no puede encontrar el archivo — "
             "revisa la ruta")
    assert cli._resumir_para_pantalla(crudo) == crudo


def test_el_texto_entero_queda_en_el_log(caplog):
    """Resumir en pantalla NO es perder: el motivo completo se registra."""
    import cognia.cli as cli
    crudo = "materias: fuera de la lista (\u79da \u745c \u745c4\u6708:Spo)"
    with caplog.at_level(logging.WARNING, logger="cognia.cli"):
        visto = cli._detalle_presentable("clases.materias", crudo)
    assert "ilegible" in visto
    assert any("\u745c" in r.getMessage() for r in caplog.records), \
        "el texto entero no llego al log"


def test_los_logs_que_se_pintan_pasan_por_el_saneado():
    """La linea que le llego a la cara al duenio era un log.warning de
    cognia/clases/materias.py, no un _aviso_degradado: se sanea envolviendo
    el formatter de los handlers de PANTALLA (el de fichero, jamas)."""
    import cognia.cli as cli
    logger = logging.getLogger("cognia")
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    previos = [(h, h.formatter) for h in logger.handlers]
    try:
        assert cli._sanear_consola_de_logs() >= 1
        assert isinstance(handler.formatter, cli._FormatoSinRuidoDelModelo)
        # idempotente: llamarlo dos veces no apila envoltorios
        cli._sanear_consola_de_logs()
        assert not isinstance(handler.formatter.base,
                              cli._FormatoSinRuidoDelModelo)
        registro = logging.LogRecord("cognia.clases.materias", logging.WARNING,
                                     __file__, 1,
                                     "fuera de la lista (\u79da \u745c "
                                     "\u745c4\u6708)", (), None)
        pintado = handler.formatter.format(registro)
        assert "\u745c" not in pintado and "ilegible" in pintado
    finally:
        logger.removeHandler(handler)
        for h, f in previos:            # el logger real, como estaba
            h.setFormatter(f)


def test_el_saneado_no_toca_el_handler_de_fichero(tmp_path):
    """El log de fichero es donde se diagnostica: ahi va el texto ENTERO."""
    import cognia.cli as cli
    logger = logging.getLogger("cognia")
    fh = logging.FileHandler(tmp_path / "cognia.log", encoding="utf-8")
    formato = logging.Formatter("%(message)s")
    fh.setFormatter(formato)
    logger.addHandler(fh)
    try:
        cli._sanear_consola_de_logs()
        assert fh.formatter is formato
    finally:
        logger.removeHandler(fh)
        fh.close()


# ── MEDIO 3: el arranque no puede decir "sin backend" con el server vivo ───

def test_un_backend_ocupado_no_se_pinta_como_ausente(monkeypatch):
    """El arranque decia "sin backend en http://127.0.0.1:8080" con
    llama-server sirviendo ahi (/health -> ok). La causa raiz esta FUERA de
    cli.py: backend_activo.props() acaba en `except Exception: datos = {}` y
    estado() traduce ese {} a "NO HAY BACKEND", con lo que "no hay nadie",
    "esta cargando", "tardo mas de 3 s" y "fallo la llamada" se pintan
    iguales. Aqui se deja de AFIRMAR lo que no se sabe."""
    import cognia.cli as cli
    monkeypatch.setattr(cli, "_backend_vivo_sin_props", lambda url: True)
    linea = cli._linea_sin_backend("sin backend en X — arranca: cognia flota",
                                   "http://127.0.0.1:8080")
    assert "VIVO" in linea and "/health" in linea
    assert "sin backend" not in linea
    monkeypatch.setattr(cli, "_backend_vivo_sin_props", lambda url: False)
    assert cli._linea_sin_backend("sin backend en X", "http://127.0.0.1:8080") \
        == "sin backend en X"


def test_la_sonda_del_arranque_distingue_ocupado_de_ausente(monkeypatch):
    """Un 503 ('cargando el modelo') es un servidor VIVO; que no haya nadie
    escuchando es lo unico que es 'sin backend'."""
    import urllib.error
    import cognia.cli as cli
    import urllib.request as urlreq

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urlreq, "urlopen", lambda *a, **k: _Resp())
    assert cli._backend_vivo_sin_props("http://127.0.0.1:8080") is True

    def _503(*a, **k):
        raise urllib.error.HTTPError("u", 503, "loading", None, None)

    monkeypatch.setattr(urlreq, "urlopen", _503)
    assert cli._backend_vivo_sin_props("http://127.0.0.1:8080") is True

    def _nadie(*a, **k):
        raise urllib.error.URLError("conexion rechazada")

    monkeypatch.setattr(urlreq, "urlopen", _nadie)
    assert cli._backend_vivo_sin_props("http://127.0.0.1:8080") is False


# ── BAJO 6: el ruido de las librerias, callado POR NOMBRE ──────────────────

def test_el_ruido_de_las_librerias_se_calla_por_nombre_y_solo_ese(monkeypatch):
    """soundcard suelta 'data discontinuity in recording' cada pocos segundos
    durante toda la clase. Se filtra ESE mensaje; cualquier otro aviso de la
    misma libreria (y de las demas) tiene que seguir saliendo -- un filtro
    global cambia un ruido por una ceguera."""
    import cognia.cli as cli
    monkeypatch.delenv("CT2_VERBOSE", raising=False)
    with warnings.catch_warnings(record=True) as vistos:
        warnings.resetwarnings()
        warnings.simplefilter("always")
        cli._silenciar_ruido_de_librerias()
        warnings.warn("data discontinuity in recording", RuntimeWarning)
        warnings.warn("el dispositivo de audio cambio", RuntimeWarning)
    mensajes = [str(w.message) for w in vistos]
    assert "data discontinuity in recording" not in mensajes
    assert "el dispositivo de audio cambio" in mensajes, \
        "se silenciaron avisos que si importan"
    assert os.environ.get("CT2_VERBOSE") == "-1"


def test_una_variable_puesta_a_mano_gana_al_silenciador(monkeypatch):
    """Quien exporta CT2_VERBOSE antes de arrancar esta diciendo algo mas
    concreto que nuestro default (misma regla que el resto de la config)."""
    import cognia.cli as cli
    monkeypatch.setenv("CT2_VERBOSE", "2")
    cli._silenciar_ruido_de_librerias()
    assert os.environ["CT2_VERBOSE"] == "2"


def test_el_silenciado_sobrevive_al_import_de_soundcard(cli_clases,
                                                        monkeypatch):
    """EL BUG QUE ENSENIO LA GRABACION REAL. soundcard hace
    `warnings.simplefilter('always', SoundcardRuntimeWarning)` al importarse
    (mediafoundation.py:26) y ese filtro se mete DELANTE del nuestro; como el
    import ocurre dentro de 'iniciar', el silenciado del arranque quedaba
    pisado y en 40 s de grabacion real salieron dos trazas. 'iniciar' vuelve a
    afirmarlo."""
    cli, lineas, _ = cli_clases
    from cognia.clases import jornada as jor
    jv = _JornadaFalsa("2026-08-31-3")

    class _RuidoDeAudio(RuntimeWarning):
        pass

    def _arrancar_que_importa_soundcard(**k):
        # exactamente lo que hace soundcard al importarse
        warnings.simplefilter("always", _RuidoDeAudio)
        return jv, "audio del sistema (loopback)"

    monkeypatch.setattr(jor, "arrancar", _arrancar_que_importa_soundcard)
    monkeypatch.setattr(jor, "viva", lambda: None)
    with warnings.catch_warnings(record=True) as vistos:
        warnings.resetwarnings()
        warnings.simplefilter("always")
        cli._silenciar_ruido_de_librerias()        # el del arranque del REPL
        cli._slash_grabar_clase("iniciar")         # aqui entra soundcard
        warnings.warn("data discontinuity in recording", _RuidoDeAudio)
    assert not [w for w in vistos
                if "data discontinuity" in str(w.message)],         "el filtro de soundcard se metio delante y la traza vuelve a salir"


def test_la_fase_urgente_NO_espera_a_la_transcripcion(cierre, monkeypatch):
    """LA FRONTERA, MEDIDA. Con la fase 1 esperando tambien a que se vaciara
    la transcripcion (`jv.viva`), una jornada real de 40 s devolvia el prompt
    a los 30,01 s: whisper carga su modelo y transcribe los trozos pendientes.
    El prompt vuelve cuando para EL AUDIO; el texto va detras."""
    cli, lineas, jv, suelta, visto = cierre
    from cognia.clases import jornada as jor

    def _parar_con_transcripcion_lenta():
        jv.grabador.viva = False      # el audio, cortado y en disco
        suelta.wait(20)               # la transcripcion, todavia vaciandose
        jv.viva = False
        return {"jornada": jv.nombre, "segundos": 40.0, "avisos": []}

    monkeypatch.setattr(jor, "parar", _parar_con_transcripcion_lenta)
    t0 = time.time()
    cli._slash_grabar_clase("parar")
    tardanza = time.time() - t0
    assert tardanza < 2.0, f"espero a la transcripcion: {tardanza:.1f} s"
    assert jv.viva, "el test no esta probando lo que dice"
    assert "transcrib" in cli._clases_cierre_fase()
    from cognia.simple_mode import should_show_detail
    visibles = [ln for ln in lineas if should_show_detail(ln)]
    assert any("ya no entra audio" in ln for ln in visibles), visibles


def test_sin_consola_NO_se_usa_el_carril_de_fondo(monkeypatch):
    """LO QUE ENSENIO EL TECLEADO POR PIPE. Con la entrada redirigida,
    prompt_toolkit SI crea la PromptSession en esta maquina, asi que
    `_sin_carril()` decia que habia carril: el cierre se fue al hilo, el guion
    llego a '/salir' y el proceso salio con el hilo daemon a medias. Un guion
    no tiene a quien devolverle el prompt."""
    import cognia.cli as cli

    class _StdinDePipe:
        def isatty(self):
            return False

    class _StdinDeConsola:
        def isatty(self):
            return True

    monkeypatch.setattr(cli, "_sin_carril", lambda: False)
    monkeypatch.setattr(cli.sys, "stdin", _StdinDePipe())
    assert cli._clases_hay_carril() is False
    monkeypatch.setattr(cli.sys, "stdin", _StdinDeConsola())
    assert cli._clases_hay_carril() is True
    monkeypatch.setattr(cli, "_sin_carril", lambda: True)
    assert cli._clases_hay_carril() is False, "COGNIA_SIN_FONDO tiene que ganar"


def test_al_salir_se_ESPERA_al_cierre_que_sigue_en_el_hilo(cierre):
    """El hilo es daemon: si el proceso termina, muere en el acto y la jornada
    se queda sin apuntes. Al salir del REPL se espera (con tope y cortable) y
    se dice."""
    cli, lineas, jv, suelta, visto = cierre
    cli._slash_grabar_clase("parar")
    assert cli._clases_cierre_vivo()
    lineas.clear()

    def _soltar():
        time.sleep(0.3)
        suelta.set()

    threading.Thread(target=_soltar, daemon=True).start()
    cli._clases_esperar_cierre_al_salir(tope_s=20.0)
    assert not cli._clases_cierre_vivo(), "salio sin esperar al cierre"
    texto = _texto(lineas)
    assert "cerrando la jornada" in texto, "se va en silencio"
    assert "cerrada del todo" in texto, "no da el parte final antes de irse"


def test_al_salir_con_el_cierre_atascado_se_dice_y_no_se_secuestra(cierre):
    """El tope existe: nadie se queda preso de su portatil por unos apuntes.
    Pero irse sin decirlo seria el vacio silencioso de siempre."""
    cli, lineas, jv, suelta, visto = cierre
    _, _, degradados = None, None, None
    cli._slash_grabar_clase("parar")
    lineas.clear()
    cli._clases_esperar_cierre_al_salir(tope_s=0.4)
    assert cli._clases_cierre_vivo(), "no deberia haber terminado"
    assert "apuntes" in _texto(lineas)


def test_el_repl_pasa_por_la_espera_del_cierre_al_salir():
    """El cableado: la espera cuelga del UNICO punto por el que se sale del
    REPL (un try/finally alrededor de _repl_sesion), no de la rama de
    '/salir' -- por ahi tambien se sale con Ctrl-D, con Ctrl-C y por
    excepcion."""
    import inspect
    import cognia.cli as cli
    fuente = inspect.getsource(cli.repl)
    assert "_clases_esperar_cierre_al_salir()" in fuente
    assert "finally" in fuente
