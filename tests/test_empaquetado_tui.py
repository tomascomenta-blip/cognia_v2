"""
tests/test_empaquetado_tui.py
=============================
Empaquetado de la TUI. Tres bugs REALES que cubre esta suite:

1. `tui = ["textual>=0.60.0"]` mentia. El codigo usa textual.theme.Theme,
   App.register_theme y App.get_theme_variable_defaults, que nacen en 0.86.0.
   Medido en un venv limpio: con textual 0.85.2 la app muere en
   "No module named 'textual.theme'"; con 0.86.0 monta (52 widgets, tema
   'cognia' activo) y sigue montando hasta 8.2.8.
2. El aviso de cognia/tui/__main__.py era CODIGO MUERTO. `python -m cognia.tui`
   importa primero el paquete, y el `__init__.py` hacia `from .app import
   CogniaTUI`: el ModuleNotFoundError de textual saltaba antes de que
   __main__.py corriera una linea. Se arreglo con __getattr__ perezoso.
3. El .tcss es lo unico no-.py sin lo cual la TUI instalada NO arranca
   (CSS_PATH). Se declara por package-data Y por MANIFEST.in.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PYPROJECT = RAIZ / "pyproject.toml"
MANIFEST = RAIZ / "MANIFEST.in"


def _cfg() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _dep(deps: list[str], nombre: str) -> str | None:
    for d in deps:
        if d.split(">=")[0].split("[")[0].split("==")[0].strip().lower() == nombre:
            return d
    return None


# --- 1. textual es dependencia DURA con el piso medido -----------------------

def test_textual_es_dependencia_dura():
    duras = _cfg()["project"]["dependencies"]
    assert _dep(duras, "textual") is not None, (
        "textual dejo de ser extra en 4.8.x: tiene que estar en las deps duras"
    )


def test_piso_de_textual_es_el_medido_no_060():
    spec = _dep(_cfg()["project"]["dependencies"], "textual")
    assert spec is not None
    assert ">=0.86.0" in spec, (
        f"piso equivocado ({spec}): el sistema de temas que usa cognia/tui/theme.py "
        "no existe antes de textual 0.86.0"
    )


def test_el_piso_declarado_y_el_del_mensaje_no_se_desincronizan():
    """El aviso de __main__.py imprime el minimo: si difiere del pyproject,
    el usuario lee una version y pip exige otra."""
    from cognia.tui.__main__ import TEXTUAL_MINIMO
    spec = _dep(_cfg()["project"]["dependencies"], "textual")
    assert f">={TEXTUAL_MINIMO}" in spec, f"pyproject dice {spec} y el aviso {TEXTUAL_MINIMO}"


def test_textual_no_se_repite_en_el_extra_all():
    """Repetirlo creaba una SEGUNDA restriccion que se desincronizaba: `all`
    tenia >=0.60.0 mientras el codigo exigia >=0.86.0."""
    todo = _cfg()["project"]["optional-dependencies"]["all"]
    assert _dep(todo, "textual") is None


# --- 2. el extra `tui` sobrevive vacio ---------------------------------------

def test_extra_tui_sigue_existiendo_y_esta_vacio():
    """`pip install cognia-ai[tui]` esta en el README, en docs/INSTALL.md y en
    scripts de usuarios. Borrar el extra no rompe (pip solo avisa "does not
    provide the extra"), pero un alias vacio cuesta una linea y no ensucia."""
    extras = _cfg()["project"]["optional-dependencies"]
    assert "tui" in extras, "el extra 'tui' se mantiene como alias vacio"
    assert extras["tui"] == [], "no debe volver a declarar textual (ya es dura)"


# --- 3. los datos no-.py de cognia/tui/ estan DECLARADOS ---------------------

def test_tcss_declarado_en_package_data():
    pd = _cfg()["tool"]["setuptools"]["package-data"]
    assert "*.tcss" in pd.get("cognia.tui", [])
    assert "*.tcss" in pd.get("cognia.tui.widgets", [])


def test_tcss_declarado_en_manifest_in():
    texto = MANIFEST.read_text(encoding="utf-8")
    assert "recursive-include cognia/tui *.tcss" in texto


def test_todo_archivo_no_py_de_tui_esta_cubierto_por_un_patron():
    """Guardia contra el dato nuevo que viaja 'por suerte': si manana aparece un
    .json o un .svg en cognia/tui/, este test obliga a declararlo."""
    pd = _cfg()["tool"]["setuptools"]["package-data"]
    patrones = set(pd.get("cognia.tui", [])) | set(pd.get("cognia.tui.widgets", []))
    sufijos_cubiertos = {p.lstrip("*") for p in patrones}
    huerfanos = []
    for f in (RAIZ / "cognia" / "tui").rglob("*"):
        if not f.is_file() or f.suffix in (".py", ".pyc") or "__pycache__" in f.parts:
            continue
        if f.suffix == ".md":
            continue  # documentacion de desarrollo, no la necesita el runtime
        if f.suffix not in sufijos_cubiertos:
            huerfanos.append(str(f.relative_to(RAIZ)))
    assert not huerfanos, f"datos de cognia/tui/ sin patron en package-data: {huerfanos}"


def test_los_tcss_viven_al_lado_del_modulo_instalado():
    """CSS_PATH es relativo al modulo: el archivo tiene que estar en el paquete."""
    import cognia.tui
    base = Path(cognia.tui.__file__).parent
    for nombre in ("app.tcss", "agentes.tcss"):
        assert (base / nombre).is_file(), f"falta {nombre} junto al modulo"


# --- 4. el paquete importa SIN textual y el aviso es ALCANZABLE --------------

_BLOQUEO = r"""
import sys
class _SinTextual:
    def find_spec(self, name, path=None, target=None):
        if name == "textual" or name.startswith("textual."):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None
sys.meta_path.insert(0, _SinTextual())
for m in [m for m in sys.modules if m == "textual" or m.startswith("textual.")]:
    del sys.modules[m]
"""


def _correr_sin_textual(codigo: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _BLOQUEO + codigo],
        capture_output=True, text=True, cwd=str(RAIZ), timeout=180,
    )


def test_importar_el_paquete_tui_no_exige_textual():
    r = _correr_sin_textual("import cognia.tui; print('IMPORT_OK')")
    assert "IMPORT_OK" in r.stdout, (r.stdout[-2000:], r.stderr[-2000:])


def test_cogniatui_sigue_accesible_desde_el_paquete():
    """El __getattr__ perezoso no puede romper `from cognia.tui import CogniaTUI`."""
    from cognia.tui import CogniaTUI
    assert CogniaTUI.__name__ == "CogniaTUI"
    assert "CogniaTUI" in dir(__import__("cognia.tui", fromlist=["x"]))


def test_sin_textual_el_usuario_lee_el_motivo_y_no_un_traceback():
    r = _correr_sin_textual(
        "from cognia.tui.__main__ import main\n"
        "try:\n"
        "    main()\n"
        "except SystemExit as e:\n"
        "    print('SALIDA', e.code)\n"
    )
    salida = r.stdout
    assert "no pudo cargar 'textual'" in salida, (salida[-2000:], r.stderr[-2000:])
    assert "0.86.0" in salida
    assert "SALIDA 1" in salida
    assert "Traceback" not in r.stderr
    # El extra ya no existe como via de instalacion: no puede seguir sugiriendolo.
    assert "cognia-ai[tui]" not in salida


def test_el_subcomando_cognia_tui_llega_al_mismo_aviso():
    """`cognia tui` importaba cognia.tui.__main__, y eso disparaba el import del
    paquete: el traceback crudo salia en cognia/__main__.py, no el aviso."""
    r = _correr_sin_textual(
        "import sys; sys.argv = ['cognia', 'tui']\n"
        "from cognia.__main__ import main\n"
        "try:\n"
        "    main()\n"
        "except SystemExit as e:\n"
        "    print('SALIDA', e.code)\n"
    )
    assert "no pudo cargar 'textual'" in r.stdout, (r.stdout[-2000:], r.stderr[-2000:])
