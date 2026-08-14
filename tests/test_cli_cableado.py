# -*- coding: utf-8 -*-
"""Regresion de C2-cli (2026-08-13): lo que estaba ESCRITO pero sin cablear.

Cinco modulos del arnes ya existian, testeados, y el CLI no los llamaba. El
sintoma comun es el peor de este repo: una capacidad que parece existir y no
hace nada, indistinguible de una rota.

1. `harness/ayuda.mensaje_desconocido` no tenia UN SOLO llamador: '/ayudda'
   contestaba "Comando desconocido" y te mandaba a leer 244 comandos.
2. '/ayuda todo' salia de HELP_TEXT, una copia A MANO de 288 lineas a la que le
   faltaban 45 de los 244 comandos (/deshacer, /permisos, /workflow, /rlm,
   /flota entre ellos). Dos fuentes -> la de mano se queda vieja sola.
3. Las @-menciones estaban condicionadas a `not raw.startswith('/')`, o sea
   eran INVISIBLES para /hacer: el autocompletado de rutas del REPL te invita a
   escribir '/hacer arregla @cognia/cli.py' y eso mandaba el literal, sin una
   sola linea del fichero.
4. Ctrl-C durante el streaming MATABA el proceso: KeyboardInterrupt hereda de
   BaseException, el 'except Exception' del stream no lo ve y el unico
   'except (EOFError, KeyboardInterrupt)' solo rodea a _get_input().
   Medido antes del fix: rc 3221225786 (STATUS_CONTROL_C_EXIT) y traceback.
5. Tres 'except Exception: pass' en capacidades VISIBLES (barra de estado,
   menciones, ayuda) hacian que "no lo cablearon" y "se rompio" se vieran igual.

Los tests de subproceso usan el REPL por stdin, que degrada a input() sin
consola (cli.py). No necesitan backend: /ayuda y los desconocidos no infieren.
"""
import ast
import io
import os
import subprocess
import sys

import pytest

import cognia.cli as cli

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__)))
FUENTE = io.open(cli.__file__, encoding="utf-8").read()


def _repl(linea, timeout=180):
    """Una linea por stdin al REPL real y su salida completa."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-m", "cognia"],
                       input=(linea + "\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       cwd=RAIZ, env=env, timeout=timeout)
    return p.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# 1. Comando desconocido -> sugerencias
# ---------------------------------------------------------------------------

def test_desconocido_sugiere_el_parecido():
    """'/ayudda' tiene que proponer /ayuda, no mandar a leer el catalogo."""
    salida = _repl("/ayudda")
    assert "Comando desconocido: /ayudda" in salida
    assert "No existe el comando" in salida, salida[-600:]
    assert "/ayuda" in salida.split("No existe el comando")[1][:200]


def test_desconocido_no_revienta_con_markup_en_la_linea():
    """El texto tecleado se imprime con markup=False: un '[' suelto reventaria
    el parser de rich y se llevaria el REPL por delante."""
    salida = _repl("/no-existe[bold]")
    assert "No existe el comando" in salida
    assert "Traceback" not in salida


# ---------------------------------------------------------------------------
# 2. /ayuda todo desde la UNICA fuente
# ---------------------------------------------------------------------------

def test_ayuda_todo_lista_los_comandos_que_faltaban():
    """Los 5 nombrados en la auditoria; en HELP_TEXT no estaba ninguno."""
    salida = _repl("/ayuda todo")
    for cmd in ("/workflow", "/deshacer", "/permisos", "/rlm", "/flota"):
        assert cmd in salida, f"{cmd} sigue ausente de /ayuda todo"


def test_ayuda_todo_cubre_practicamente_todo_el_catalogo():
    """Contra el HELP_TEXT de mano faltaban 45 de 244. Ahora sale del dict."""
    salida = _repl("/ayuda todo")
    faltan = [c for c in cli._CMD_DESCRIPTIONS if c not in salida]
    assert len(faltan) <= 5, f"{len(faltan)} comandos ausentes: {faltan[:20]}"


def test_help_text_es_solo_emergencia():
    """HELP_TEXT ya no es un catalogo: es el cartel de cuando ayuda.py falla.
    Si vuelve a crecer, el catalogo esta duplicado otra vez."""
    lineas = [l for l in cli.HELP_TEXT.splitlines() if l.strip()]
    assert len(lineas) <= 20, f"HELP_TEXT volvio a crecer: {len(lineas)} lineas"
    assert "EMERGENCIA" in cli.HELP_TEXT


# ---------------------------------------------------------------------------
# 3. @-menciones tambien en los comandos que mandan su argumento al modelo
# ---------------------------------------------------------------------------

def test_particion_texto_libre_expande_todo():
    assert cli._partir_para_menciones("mira @a.py") == ("", "mira @a.py")


def test_particion_slash_de_la_lista_blanca_expande_solo_el_argumento():
    for cmd in cli._SLASH_CON_MENCIONES:
        pref, cuerpo = cli._partir_para_menciones(f"{cmd} arregla @a.py")
        assert pref == cmd + " ", cmd
        assert cuerpo == "arregla @a.py", cmd


def test_particion_ignora_los_slash_de_fuera_de_la_lista():
    """En los otros ~238 comandos el '@' es del argumento (un email), no una
    mencion: expandirlo seria adivinar."""
    assert cli._partir_para_menciones("/recordar escribile a x@y.com") == ("", "")
    assert cli._partir_para_menciones("/memoria") == ("", "")


def test_particion_sin_arroba_o_sin_argumento_no_hace_nada():
    assert cli._partir_para_menciones("/hacer arregla el bug") == ("", "")
    assert cli._partir_para_menciones("/hacer") == ("", "")
    assert cli._partir_para_menciones("") == ("", "")


def test_hacer_con_mencion_lleva_el_CONTENIDO(tmp_path):
    """El bug real: '/hacer arregla @f.py' mandaba el literal SIN contenido.
    Se reproduce la composicion exacta del REPL (partir -> expandir -> pegar)."""
    from cognia.harness.menciones import expandir
    (tmp_path / "objetivo.py").write_text("MARCA_UNICA_DEL_TEST = 1\n",
                                          encoding="utf-8")
    linea = "/hacer arregla el bug de @objetivo.py"

    pref, cuerpo = cli._partir_para_menciones(linea)
    assert cuerpo, "la mencion sigue siendo invisible para /hacer"
    exp, adjuntos, _avisos = expandir(cuerpo, str(tmp_path))
    raw = pref + exp

    # el dispatch tiene que seguir viendo su cabecera intacta
    assert raw.startswith("/hacer ")
    # y el modelo, el contenido del fichero
    assert "MARCA_UNICA_DEL_TEST" in raw
    assert [a["ruta"] for a in adjuntos] == ["objetivo.py"]


def test_la_condicion_vieja_de_menciones_no_volvio():
    """`'@' in raw and not raw.startswith('/')` es exactamente el guard que
    hacia invisibles las menciones en los comandos."""
    assert "'@' in raw and not raw.startswith" not in FUENTE
    assert '"@" in raw and not raw.startswith' not in FUENTE


# ---------------------------------------------------------------------------
# 4. Ctrl-C corta el turno, no el REPL
# ---------------------------------------------------------------------------

def _tries_del_modulo():
    return [n for n in ast.walk(ast.parse(FUENTE)) if isinstance(n, ast.Try)]


def _captura_keyboardinterrupt(try_node):
    for h in try_node.handlers:
        nombres = []
        if isinstance(h.type, ast.Name):
            nombres = [h.type.id]
        elif isinstance(h.type, ast.Tuple):
            nombres = [e.id for e in h.type.elts if isinstance(e, ast.Name)]
        if "KeyboardInterrupt" in nombres or "BaseException" in nombres:
            return True
    return False


def _try_cuyo_handler_marca(marca):
    """El try que se identifica por la marca de su _aviso_degradado (los
    'except Exception as _se' hay varios en el modulo; la marca es unica)."""
    for t in _tries_del_modulo():
        for h in t.handlers:
            if marca in ast.dump(ast.Module(body=h.body, type_ignores=[])):
                return t
    return None


@pytest.mark.parametrize("marca", ["cli.fast_path.stream", "cli.articulado.excepcion"])
def test_el_turno_captura_keyboardinterrupt(marca):
    """Los dos caminos donde el turno se va segundos sin devolver el prompt.
    Sin este handler, Ctrl-C mata el proceso: medido en HEAD antes del fix,
    rc 3221225786 (STATUS_CONTROL_C_EXIT) con traceback en socket.recv_into."""
    t = _try_cuyo_handler_marca(marca)
    assert t is not None, f"no se encontro el try de {marca}"
    assert _captura_keyboardinterrupt(t), (
        f"el try de {marca} (linea {t.lineno}) no captura KeyboardInterrupt")


def test_el_handler_de_ctrlc_no_usa_corchetes_en_el_texto():
    """rich se come '[interrumpido]' como etiqueta de markup y el aviso salia
    decapitado (cazado en la corrida real de verificacion)."""
    literales = [n.value for n in ast.walk(ast.parse(FUENTE))
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in literales if "[interrumpido]" in s]
    assert FUENTE.count("Ctrl-C: turno cortado") == 2   # fast-path + articulado


# ---------------------------------------------------------------------------
# 5. Los 'except Exception: pass' de capacidades visibles ahora gritan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("via", ["cli.barra_estado", "cli.menciones", "cli.ayuda"])
def test_los_sitios_mudos_avisan(via):
    assert f'"{via}"' in FUENTE, f"{via} sigue tragandose el error en silencio"


# ---------------------------------------------------------------------------
# 6. Ordenes sugeridas que existan en la instalacion pip
# ---------------------------------------------------------------------------

def test_no_sugiere_scripts_que_no_viajan_en_el_wheel():
    """'python scripts/servir_*.py' no existe para quien instalo por pip; el
    subcomando (cognia/__main__.py:_cmd_flota) si."""
    assert "python scripts/servir_flota.py" not in FUENTE
    assert "python scripts/servir_modelo.py" not in FUENTE
    assert "python -m cognia flota arrancar pensar" in FUENTE
