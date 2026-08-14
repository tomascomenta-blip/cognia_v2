"""
tests/test_subcomandos_cli.py
=============================
El chequeo que impide que la documentacion mienta sobre la CLI.

Historia real: `cognia doctor` estaba documentado en README.md (dos veces) y el
propio REPL mandaba ahi en sus dos mensajes de backend caido
("...revisa el backend con: cognia doctor", cli.py:9822 y :9847), pero el
dispatcher de cognia/__main__.py NO tenia la rama: el usuario que seguia la
instruccion recibia "Comando desconocido: 'doctor'". Un verbo documentado y no
cableado no lo caza ningun test de unidad de los modulos: solo lo caza cruzar
LO QUE SE PROMETE con LO QUE SE DESPACHA. Eso es lo que hace este fichero.

Reglas del parser (ver _verbos_de_texto): se cuenta como invocacion de comando
"cognia <verbo>" solo cuando aparece en posicion de comando -- entre backticks,
en un bloque de codigo, o al final de una frase tipo "instala con: cognia X" --
para no confundirse con prosa castellana ("cognia encadena sola las
continuaciones") ni con imports de Python ("from cognia import backend_activo").
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
README = RAIZ / "README.md"
CLI_PY = RAIZ / "cognia" / "cli.py"
MAIN_PY = RAIZ / "cognia" / "__main__.py"


# ── Extraccion de verbos prometidos ───────────────────────────────────────────

# "cognia <verbo>" seguido de fin de linea, backtick, opcion (--), comentario,
# comilla o marca de color: la forma en que se escriben los comandos de verdad.
_RE_VERBO = re.compile(
    r"""(?:^|[`"'(\s])cognia\s+([a-z][a-z0-9-]*)(?=\s*(?:$|`|--|<|\[/|\||\)|"|'|\#))""",
    re.M,
)
# Dentro de cadenas de Python el comando suele abrir la cadena: f"cognia flota
# arrancar". Ese caso lleva argumentos detras y no cae en el patron de arriba.
_RE_VERBO_APERTURA = re.compile(r"""["']cognia\s+([a-z][a-z0-9-]*)""")


def _verbos_de_texto(texto: str, apertura_de_cadena: bool = False) -> set[str]:
    verbos = set(_RE_VERBO.findall(texto))
    if apertura_de_cadena:
        verbos |= set(_RE_VERBO_APERTURA.findall(texto))
    return verbos


def _verbos_del_dispatcher() -> set[str]:
    """Los verbos que cognia/__main__.py despacha DE VERDAD.

    Se leen del fuente (ramas `cmd == "x"` y `cmd in ("x", "y")`) en vez de
    duplicar una lista a mano: una lista a mano se desincroniza y el test
    dejaria de valer justo cuando hace falta."""
    src = MAIN_PY.read_text(encoding="utf-8")
    verbos = set(re.findall(r"""cmd\s*==\s*["']([a-z0-9-]+)["']""", src))
    for grupo in re.findall(r"""cmd\s+in\s+\(([^)]*)\)""", src):
        verbos |= set(re.findall(r"""["']([a-z0-9-]+)["']""", grupo))
    return verbos


def _help_texto() -> str:
    from cognia.__main__ import _HELP
    return _HELP


# ── El chequeo: lo prometido esta cableado ────────────────────────────────────

def test_parser_de_verbos_no_confunde_prosa_ni_imports():
    """Guardia del propio parser: si empieza a tragar prosa, los otros tests
    se vuelven ruido y hay que enterarse aqui."""
    assert _verbos_de_texto("from cognia import backend_activo") == set()
    assert _verbos_de_texto("por defecto cognia encadena sola las continuaciones") == set()
    assert _verbos_de_texto("revisa el backend con: cognia doctor") == {"doctor"}
    assert _verbos_de_texto("cognia install-model --with-heavy-code   # opt-in") == {"install-model"}
    assert _verbos_de_texto("`cognia empezar` deja todo listo") == {"empezar"}
    assert _verbos_de_texto('f"cognia flota arrancar"', apertura_de_cadena=True) == {"flota"}


def test_verbos_del_readme_estan_en_el_dispatcher():
    """Si el README promete `cognia X`, `cognia X` tiene que correr.

    Falla si se revierte la rama 'doctor' del dispatcher (README.md:198, :325)."""
    prometidos = _verbos_de_texto(README.read_text(encoding="utf-8"))
    assert "doctor" in prometidos, "el README ya no documenta 'cognia doctor': revisa el parser"
    despachados = _verbos_del_dispatcher()
    faltan = sorted(prometidos - despachados)
    assert not faltan, (
        f"verbos documentados en README.md que el dispatcher NO despacha: {faltan}. "
        f"Cablearlos en cognia/__main__.py o borrarlos del README."
    )


def test_verbos_del_cli_estan_en_el_dispatcher():
    """Lo mismo para lo que el REPL le dice al usuario que escriba.

    Los mensajes de backend caido (cli.py) mandan a 'cognia doctor': ese
    consejo tiene que ser ejecutable."""
    prometidos = _verbos_de_texto(CLI_PY.read_text(encoding="utf-8"),
                                  apertura_de_cadena=True)
    assert "doctor" in prometidos, "cli.py ya no menciona 'cognia doctor': revisa el parser"
    despachados = _verbos_del_dispatcher()
    faltan = sorted(prometidos - despachados)
    assert not faltan, (
        f"verbos que cognia/cli.py le pide al usuario y el dispatcher NO despacha: {faltan}"
    )


def test_help_menciona_los_verbos_del_readme():
    """`cognia help` es la lista canonica: si el README lo promete, help lo lista."""
    prometidos = _verbos_de_texto(README.read_text(encoding="utf-8"))
    ayuda = _help_texto()
    faltan = sorted(v for v in prometidos if v not in ayuda)
    assert not faltan, f"verbos del README ausentes en _HELP: {faltan}"


def test_help_pone_empezar_primero_y_lista_doctor():
    """'empezar' es el camino unico: va antes que el resto de comandos."""
    ayuda = _help_texto()
    assert "empezar" in ayuda and "doctor" in ayuda
    cuerpo = ayuda.split("Comandos:", 1)[1]
    for otro in ("init", "install-model", "status", "flota"):
        assert cuerpo.index("empezar") < cuerpo.index(otro), (
            f"'empezar' deberia listarse antes que '{otro}'"
        )


# ── Despacho real (sin correr los chequeos lentos del doctor) ─────────────────

def _correr_main(argv: list[str], capsys) -> int:
    """Llama al dispatcher real con argv y devuelve el codigo de salida."""
    from cognia.__main__ import main
    argv_prev = sys.argv
    sys.argv = ["cognia", *argv]
    try:
        main()
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = argv_prev


def test_doctor_se_despacha_y_no_dice_comando_desconocido(monkeypatch, capsys):
    """El bug exacto: 'cognia doctor' respondia 'Comando desconocido'.

    El doctor de verdad mide velocidad de inferencia (minutos, backend vivo):
    aqui se sustituye SOLO su main() para verificar el cableado y que el codigo
    de salida del doctor es el que sale del proceso."""
    falso = types.ModuleType("cognia.doctor")
    llamadas = []
    falso.main = lambda: (llamadas.append(True), 1)[1]
    monkeypatch.setitem(sys.modules, "cognia.doctor", falso)

    codigo = _correr_main(["doctor"], capsys)
    salida = capsys.readouterr().out
    assert "Comando desconocido" not in salida, salida
    assert llamadas == [True], "no se llamo a cognia.doctor.main()"
    assert codigo == 1, "el codigo de salida del doctor tiene que propagarse"


def test_empezar_y_start_llaman_a_arranque_con_argv(monkeypatch, capsys):
    """Contrato fijo con cognia/arranque.py: main(argv: list[str]) -> int."""
    for verbo in ("empezar", "start"):
        recibidos = []
        falso = types.ModuleType("cognia.arranque")
        falso.main = lambda argv: (recibidos.append(argv), 0)[1]
        monkeypatch.setitem(sys.modules, "cognia.arranque", falso)

        codigo = _correr_main([verbo, "--sin-modelo"], capsys)
        salida = capsys.readouterr().out
        assert "Comando desconocido" not in salida, salida
        assert recibidos == [["--sin-modelo"]], f"{verbo}: argv no llego a arranque.main"
        assert codigo == 0


def test_empezar_sin_modulo_da_error_legible(monkeypatch, capsys):
    """Si cognia/arranque.py no esta en esta instalacion, el usuario ve QUE
    falta y que hacer -- no un ImportError crudo con traceback."""
    monkeypatch.setitem(sys.modules, "cognia.arranque", None)  # fuerza ImportError
    codigo = _correr_main(["empezar"], capsys)
    salida = capsys.readouterr().out
    assert codigo == 1
    assert "Comando desconocido" not in salida
    assert "no esta disponible" in salida, salida
    assert "install-model" in salida, salida


# ── bbrain no escribe en site-packages ────────────────────────────────────────

def test_bbrain_va_al_repo_si_hay_git(tmp_path):
    from cognia.__main__ import _ruta_bbrain
    (tmp_path / ".git").mkdir()
    assert _ruta_bbrain(tmp_path) == tmp_path / "bbrain.md"


def test_bbrain_va_a_cognia_home_si_esta_instalado(tmp_path, monkeypatch):
    """Instalado por pip la 'raiz' es site-packages: escribir ahi ensucia el
    entorno (y suele ser de solo lectura)."""
    import cognia.first_run as fr
    home = tmp_path / "home_cognia"
    monkeypatch.setattr(fr, "COGNIA_HOME", home)

    site_packages = tmp_path / "site-packages"   # sin .git
    site_packages.mkdir()
    from cognia.__main__ import _ruta_bbrain
    assert _ruta_bbrain(site_packages) == home / "bbrain.md"
