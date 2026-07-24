# -*- coding: utf-8 -*-
"""Imports que solo resuelven desde la raiz del repo: rompen la instalacion.

Deuda cazada el 2026-07-24 en un venv limpio con cognia-ai 4.3.0 instalado desde
PyPI. Dos casos, ambos del mismo patron y ambos SILENCIOSOS:

  - cognia/voz/jarvis.py hacia `from respuestas_articuladas import ...`. El modulo
    se empaqueta como cognia_v3.interfaces.respuestas_articuladas, asi que Jarvis
    moria con ModuleNotFoundError al construir el cerebro.
  - cognia/cli.py hacia `from vectors import text_to_vector` sin caer primero a
    `cognia.vectors`. Estaba dentro de un try/except Exception que se lo tragaba:
    el turno de conversacion NUNCA se registraba y las preguntas de seguimiento
    tras un /hacer dejaban de funcionar sin aviso.

La regla que se protege: dentro del paquete se importa por la RUTA DEL PAQUETE;
el nombre suelto de la raiz solo vale como fallback.
"""
import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# nombres de modulos que existen sueltos en la raiz del repo pero NO como
# paquete de primer nivel en una instalacion (o que viven en otro paquete)
SOLO_EN_LA_RAIZ = {"respuestas_articuladas", "vectors"}


def _imports_de_primer_nivel(archivo: pathlib.Path):
    """(linea, modulo) de cada import absoluto del archivo."""
    try:
        arbol = ast.parse(archivo.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield n.lineno, a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            yield n.lineno, n.module.split(".")[0]


def _tiene_fallback(archivo: pathlib.Path, linea: int) -> bool:
    """True si el import esta en la rama `except` de un try (es un fallback)."""
    lineas = archivo.read_text(encoding="utf-8", errors="replace").splitlines()
    # se mira hacia arriba: si lo primero que aparece con menor indentacion es un
    # `except`, el import es la rama de respaldo y esta bien.
    idx = linea - 1
    if idx >= len(lineas):
        return False
    sangria = len(lineas[idx]) - len(lineas[idx].lstrip())
    for j in range(idx - 1, max(-1, idx - 6), -1):
        s = lineas[j]
        if not s.strip():
            continue
        if len(s) - len(s.lstrip()) < sangria and s.lstrip().startswith("except"):
            return True
    return False


def test_ningun_import_depende_de_correr_desde_la_raiz():
    ofensores = []
    for paquete in ("cognia", "node", "shattering"):
        for f in (RAIZ / paquete).rglob("*.py"):
            for linea, mod in _imports_de_primer_nivel(f):
                if mod in SOLO_EN_LA_RAIZ and not _tiene_fallback(f, linea):
                    ofensores.append(f"{f.relative_to(RAIZ)}:{linea} -> '{mod}'")
    assert not ofensores, (
        "estos imports solo resuelven con el cwd en la raiz del repo; en una "
        "instalacion desde PyPI fallan (y si estan dentro de un try/except "
        "amplio, fallan EN SILENCIO):\n  " + "\n  ".join(ofensores))


def test_jarvis_importa_por_la_ruta_del_paquete():
    src = (RAIZ / "cognia" / "voz" / "jarvis.py").read_text(encoding="utf-8")
    assert "cognia_v3.interfaces.respuestas_articuladas" in src
