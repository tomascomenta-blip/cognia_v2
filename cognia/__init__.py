# Antes de nada: stdout UTF-8. Si no, cualquier print con emoji mata el
# proceso en Windows cuando la salida esta redirigida (ver cognia/consola.py).
from .consola import forzar_utf8

forzar_utf8()

# `Cognia` se importa PEREZOSAMENTE (PEP 562, 2026-08-25). Medido con
# -X importtime en la maquina del dueno: `import cognia` costaba 220 ms de los
# que 215 eran `.cognia` (la clase arrastra memoria, grafo, mesh, prometheus,
# razonadores...). El REPL la instancia UNA vez en cli.repl(); `cognia --help`,
# `cognia doctor`, los scripts y la mitad de la suite solo necesitan
# `__version__`, `consola` o un submodulo. Con el atributo perezoso `import
# cognia` baja a unos ms y `import cognia.cli` pierde los 215 ms enteros.
# Contrato que se conserva: `cognia.Cognia`, `from cognia import Cognia`,
# `hasattr(cognia, "Cognia")` y `mock.patch("cognia.Cognia")` siguen
# funcionando (todos pasan por __getattr__ y devuelven LA MISMA clase que
# cognia.cognia.Cognia); solo cambia CUANDO se paga el import: al primer
# acceso, no al importar el paquete. Test: tests/test_pulido_arranque.py.
_PEREZOSOS = {"Cognia": ".cognia"}


def __getattr__(nombre: str):
    if nombre == "__version__":
        return _version_cacheada()
    if nombre in _PEREZOSOS:
        from importlib import import_module
        modulo = import_module(_PEREZOSOS[nombre], __name__)
        valor = getattr(modulo, nombre)
        # Cachear en el namespace del paquete: los accesos siguientes no
        # vuelven a pasar por aqui (y mock.patch puede pisarlo y restaurarlo).
        globals()[nombre] = valor
        return valor
    if nombre == "cognia":
        # `import cognia; cognia.cognia.X` sin haber importado el submodulo:
        # antes funcionaba porque `from .cognia import ...` lo colgaba del
        # paquete al arrancar. Se conserva.
        from importlib import import_module
        return import_module(".cognia", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")


def __dir__():
    return sorted(set(globals()) | set(_PEREZOSOS) | {"__version__"})


def _detectar_version() -> str:
    # Instalado por pip: la metadata del wheel es la verdad. En un checkout
    # del repo (venv312 sin cognia-ai instalado) la metadata no existe, asi
    # que se lee pyproject.toml; "dev" solo si tampoco hay repo alrededor.
    try:
        from importlib.metadata import version
        return version("cognia-ai")
    except Exception:
        pass
    try:
        import os
        import re
        pp = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "pyproject.toml")
        with open(pp, "r", encoding="utf-8") as fh:
            m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "dev"


# `__version__` tambien es perezoso (2026-08-25): _detectar_version() tira de
# importlib.metadata, que cuesta 35,6 ms de los 45 que quedaban en `import
# cognia` (medido con -X importtime tras hacer perezosa la clase). El banner
# lo pide al arrancar el REPL (ahi se paga igual), pero `cognia --help`, los
# tests y cualquier `import cognia.cli` que no abre el REPL ya no. Se calcula
# UNA vez y se cachea en el namespace del paquete (ver __getattr__).
_VERSION_CACHE = None


def _version_cacheada() -> str:
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        _VERSION_CACHE = _detectar_version()
        globals()["__version__"] = _VERSION_CACHE
    return _VERSION_CACHE
