"""
tests/test_user_prefs.py
========================
Personalization preferences (cognia/user_prefs.py): the explicit, user-set
name/language/style that the onboarding wizard and `cognia modo` persist and
that get folded into the system prompt at chat time.

Key invariant: with nothing configured, personalize_prompt is a NO-OP, so a
fresh user's canonical identity prompt is never altered.
"""

from __future__ import annotations

import os

from cognia import user_prefs as up
from shattering.model_constants import COGNIA_SYSTEM_PROMPT


def test_suffix_empty_is_blank():
    assert up.personalization_suffix({}) == ""
    assert up.personalization_suffix({up.K_USER_NAME: "", up.K_LANG: "", up.K_STYLE: ""}) == ""


def test_suffix_includes_name_lang_style():
    s = up.personalization_suffix({
        up.K_USER_NAME: "Tomas", up.K_LANG: "espanol", up.K_STYLE: "breve",
    })
    assert "Tomas" in s
    assert "espanol" in s.lower()
    assert "breves" in s.lower()
    # ASCII-safe for the CP1252 CLI
    s.encode("ascii")


def test_suffix_partial_only_name():
    s = up.personalization_suffix({up.K_USER_NAME: "Ana"})
    assert "Ana" in s
    assert "idioma" not in s.lower()  # no language line when unset


def test_personalize_prompt_noop_when_empty():
    # The canonical identity prompt must survive untouched for a fresh user.
    assert up.personalize_prompt(COGNIA_SYSTEM_PROMPT, {}) == COGNIA_SYSTEM_PROMPT


def test_personalize_prompt_appends():
    out = up.personalize_prompt("BASE", {up.K_USER_NAME: "Leo"})
    assert out.startswith("BASE")
    assert "Leo" in out


def test_save_load_roundtrip(tmp_path, monkeypatch):
    from cognia import first_run
    cfg = tmp_path / "config.env"
    monkeypatch.setattr(first_run, "COGNIA_HOME", tmp_path)
    monkeypatch.setattr(first_run, "CONFIG_FILE", cfg)
    touched = []
    try:
        up.save_pref(up.K_USER_NAME, "Tomas"); touched.append(up.K_USER_NAME)
        up.save_pref(up.K_RUN_MODE, "local");  touched.append(up.K_RUN_MODE)
        up.save_pref(up.K_STYLE, "tecnica");   touched.append(up.K_STYLE)
        prefs = up.load_prefs()
        assert prefs[up.K_USER_NAME] == "Tomas"
        assert prefs[up.K_RUN_MODE] == "local"
        assert prefs[up.K_STYLE] == "tecnica"
    finally:
        # set_config_value also writes os.environ; keep the suite clean.
        for k in touched:
            os.environ.pop(k, None)


def test_cli_exposes_modo_command():
    import inspect
    from cognia import __main__ as m
    assert hasattr(m, "_cmd_modo")
    src = inspect.getsource(m.main)
    assert '"modo"' in src or "'modo'" in src


# ---------------------------------------------------------------------------
# ANTICUERPO: ninguna clave persistente se queda fuera de load_prefs()
# ---------------------------------------------------------------------------
#
# EL BUG QUE ESTO IMPIDE (vivo hasta 2026-08-29, reproducido antes del fix):
# `load_prefs()` FILTRA las claves de ~/.cognia/config.env por una tupla
# escrita a mano. Una clave que no este en esa tupla se escribe bien en el
# fichero y NO SE RELEE: la preferencia funciona en la sesion y se olvida al
# reiniciar, sin excepcion, sin aviso y sin nada que mirar en un log.
#
#     >>> first_run.set_config_value("COGNIA_UI_MODE", "avanzado")
#     >>> user_prefs.load_prefs()
#     {}                     # <- el fichero SI lo tiene
#
# Le paso a COGNIA_UI_MODE (`/modo avanzado`), que sobrevivia solo de rebote
# porque `first_run.apply_config()` rellena os.environ y `simple_mode` tiene
# fallback por env; y le habria vuelto a pasar a COGNIA_CMD_NIVEL
# (`/avanzado`). Una leccion en prosa no impide nada: esto es el chequeo que
# corre. Si manana alguien declara `K_LO_QUE_SEA = "COGNIA_LO_QUE_SEA"` y no
# la da de alta, este test falla ANTES de que el dueno pierda la preferencia.

import ast
import pathlib

_RAIZ_COGNIA = pathlib.Path(__file__).resolve().parents[1] / "cognia"


def _claves_persistentes_declaradas(raiz) -> dict:
    """{clave: [modulo, ...]} de todo `K_* = "COGNIA_..."` a nivel de modulo.

    Se lee con AST y no importando: importar el paquete entero para censar
    constantes arrastra backends, sockets y modelos. El AST solo mira el
    fuente y no puede colgarse.
    """
    encontradas: dict = {}
    for py in sorted(pathlib.Path(raiz).rglob("*.py")):
        try:
            arbol = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo in arbol.body:            # SOLO nivel de modulo
            if not isinstance(nodo, ast.Assign):
                continue
            valor = nodo.value
            if not (isinstance(valor, ast.Constant)
                    and isinstance(valor.value, str)
                    and valor.value.startswith("COGNIA_")):
                continue
            for destino in nodo.targets:
                if isinstance(destino, ast.Name) and destino.id.startswith("K_"):
                    encontradas.setdefault(valor.value, []).append(py.name)
    return encontradas


def test_el_censo_de_claves_encuentra_las_conocidas():
    """Contrafactual 1: el censo no devuelve vacio por un rglob roto."""
    claves = _claves_persistentes_declaradas(_RAIZ_COGNIA)
    assert up.K_USER_NAME in claves
    assert "COGNIA_UI_MODE" in claves, "simple_mode.K_UI_MODE deberia salir"
    assert "COGNIA_CMD_NIVEL" in claves, "cli_visibilidad.K_CMD_NIVEL deberia salir"


def test_el_censo_caza_una_clave_nueva(tmp_path):
    """Contrafactual 2: una clave recien declarada aparece de verdad."""
    (tmp_path / "modulo_falso.py").write_text(
        'K_INVENTADA = "COGNIA_INVENTADA_PARA_EL_TEST"\n', encoding="utf-8")
    claves = _claves_persistentes_declaradas(tmp_path)
    assert "COGNIA_INVENTADA_PARA_EL_TEST" in claves


def test_toda_clave_persistente_declarada_esta_dada_de_alta(monkeypatch):
    """EL ANTICUERPO. Cada `K_* = "COGNIA_..."` del paquete tiene que estar en
    PERSISTED_KEYS *y* salir de verdad por load_prefs()."""
    from cognia import first_run

    claves = _claves_persistentes_declaradas(_RAIZ_COGNIA)
    faltan = sorted(k for k in claves if k not in up.PERSISTED_KEYS)
    assert not faltan, (
        "estas claves se persisten en ~/.cognia/config.env y load_prefs() NO "
        "las devuelve: la preferencia se olvidara al reiniciar SIN ERROR. "
        "Darlas de alta en cognia/user_prefs.py::PERSISTED_KEYS.\n  "
        + "\n  ".join(f"{k}  (declarada en {', '.join(claves[k])})"
                      for k in faltan))

    # no basta la tupla: load_prefs tiene que DEVOLVER cada una leyendola del
    # disco (el modo en que el bug se manifestaba era un {} silencioso).
    falso = {k: "valor-de-prueba" for k in claves}
    monkeypatch.setattr(first_run, "_load_config", lambda: falso, raising=True)
    devueltas = up.load_prefs()
    mudas = sorted(k for k in claves if devueltas.get(k) != "valor-de-prueba")
    assert not mudas, f"load_prefs() se traga estas claves del disco: {mudas}"


def test_las_constantes_duplicadas_coinciden():
    """user_prefs duplica los literales de simple_mode y cli_visibilidad (el
    import directo seria un ciclo). Esto ata las copias."""
    from cognia import simple_mode, cli_visibilidad
    assert up.K_UI_MODE == simple_mode.K_UI_MODE
    assert up.K_CMD_NIVEL == cli_visibilidad.K_CMD_NIVEL


def test_ui_mode_y_cmd_nivel_sobreviven_al_reinicio(tmp_path, monkeypatch):
    """REGRESION del bug: escribir en config.env y releer SIN os.environ.

    Es la simulacion honesta de un reinicio en el que apply_config() no ha
    corrido todavia (o en el que la env var no esta): antes del fix las dos
    claves salian de load_prefs() como si nunca se hubieran guardado.
    """
    from cognia import first_run
    cfg = tmp_path / "config.env"
    monkeypatch.setattr(first_run, "COGNIA_HOME", tmp_path)
    monkeypatch.setattr(first_run, "CONFIG_FILE", cfg)
    monkeypatch.setattr(first_run, "ENV_FILE_INSTALADOR", tmp_path / "no-existe.env")

    try:
        up.save_pref(up.K_UI_MODE, "avanzado")
        up.save_pref(up.K_CMD_NIVEL, "todo")
        # el "reinicio": la sesion viva no aporta nada, solo manda el fichero.
        # (No con monkeypatch.delenv: registraria el valor recien puesto por
        # save_pref y lo RESTAURARIA en el teardown, ensuciando la suite.)
        os.environ.pop(up.K_UI_MODE, None)
        os.environ.pop(up.K_CMD_NIVEL, None)

        prefs = up.load_prefs()
        assert prefs.get(up.K_UI_MODE) == "avanzado"
        assert prefs.get(up.K_CMD_NIVEL) == "todo"
    finally:
        os.environ.pop(up.K_UI_MODE, None)
        os.environ.pop(up.K_CMD_NIVEL, None)
