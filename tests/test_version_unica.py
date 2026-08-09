"""
WP6 (2026-08-09): habia TRES versiones visibles distintas — pyproject.toml
4.5.0, installer/cognia_setup.iss 4.3.1 y el launcher saludando "Cognia
v3.2". La canonica es pyproject.toml; el .iss no puede leer TOML asi que se
mantiene a mano Y este test grita si diverge; el launcher dejo de hardcodear
y pregunta `cognia --version` en runtime.
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _version_pyproject() -> str:
    texto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', texto, re.M)
    assert m, "pyproject.toml sin campo version"
    return m.group(1)


def test_setup_iss_lleva_la_version_de_pyproject():
    texto = (RAIZ / "installer" / "cognia_setup.iss").read_text(encoding="utf-8")
    m = re.search(r'#define\s+AppVersion\s+"([^"]+)"', texto)
    assert m, "cognia_setup.iss sin #define AppVersion"
    assert m.group(1) == _version_pyproject(), (
        f"el instalador dice {m.group(1)} y pyproject.toml "
        f"{_version_pyproject()}: actualiza AppVersion en cognia_setup.iss")


def test_launcher_no_hardcodea_version():
    texto = (RAIZ / "installer" / "cognia_launcher.ps1").read_text(encoding="utf-8")
    # "Cognia v3.2" vivio aqui dos releases: cualquier vN.N literal vuelve a
    # ser una segunda verdad que nadie actualiza.
    assert not re.search(r"Cognia v\d", texto), (
        "el launcher hardcodea una version; debe preguntarla con "
        "`cognia --version`")
    assert "--version" in texto, "el launcher debe obtener la version en runtime"


def test_el_paquete_reporta_la_version_de_pyproject():
    # En el checkout (sin cognia-ai instalado en el venv del repo, o instalado
    # editable desde este mismo arbol) __version__ debe coincidir con
    # pyproject; si aqui divergen es que la metadata instalada esta rancia.
    import cognia
    from importlib.metadata import PackageNotFoundError, version
    try:
        instalada = version("cognia-ai")
    except PackageNotFoundError:
        instalada = None
    if instalada is None:
        assert cognia.__version__ == _version_pyproject()
    else:
        assert cognia.__version__ == instalada
