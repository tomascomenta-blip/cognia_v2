"""
mapa_proyecto.py — Saber donde esta cada cosa sin leer los ficheros enteros.

POR QUE EXISTE: con n_ctx=8192, mandarle a Cognia el codigo completo de un
directorio para que responda "donde esta la funcion que puntua programas" gasta
la ventana entera en texto que casi todo sobra. Un mapa de clases y funciones
con su linea contesta lo mismo en dos ordenes de magnitud menos.

La idea sale de la investigacion que hizo Cognia sola el 2026-07-20 sobre
agentes de coding: `tirth8205/code-review-graph` (21k estrellas) construye "un
mapa persistente del codebase para que las herramientas de IA lean solo lo que
importa". El recorrido con `ast` lo escribio la propia Cognia
(`generated_programs/python_project_map_with_ast`, 2 tests en verde, reparado
por el lazo G1 al primer intento).

Lo que se le anadio al integrarlo, todo por casos reales de este repo:
  - recursivo, que su version solo miraba el primer nivel
  - saltar venv/, __pycache__ y demas, o el mapa se llena de dependencias
  - no morir con un fichero que no parsea (los hay generados y a medias)
  - metodos con su clase, que es como se buscan de verdad
  - async def, que su visitor se saltaba

Sin dependencias externas: solo stdlib.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

# Directorios que nunca aportan: son dependencias o basura de build.
_IGNORAR = {
    ".git", "__pycache__", "node_modules", "build", "dist", ".pytest_cache",
    ".mypy_cache", "generated_programs", "generated_games", ".playwright-mcp",
}


def _saltar(parte: str) -> bool:
    return parte in _IGNORAR or parte.startswith(("venv", ".venv"))


@dataclass
class Simbolo:
    nombre: str
    linea:  int
    clase:  str = ""      # la clase que lo contiene, si es un metodo

    def etiqueta(self) -> str:
        return f"{self.clase}.{self.nombre}" if self.clase else self.nombre


@dataclass
class FicheroMapeado:
    ruta:      str
    clases:    List[Simbolo] = field(default_factory=list)
    funciones: List[Simbolo] = field(default_factory=list)
    importa:   List[str]     = field(default_factory=list)
    error:     str = ""

    @property
    def vacio(self) -> bool:
        return not self.clases and not self.funciones and not self.importa


class _Recorrido(ast.NodeVisitor):
    """Junta clases y funciones sabiendo cual es metodo de cual."""

    def __init__(self):
        self.clases:    List[Simbolo] = []
        self.funciones: List[Simbolo] = []
        self.importa:   List[str]     = []
        self._clase_actual = ""

    # Los imports contestan la pregunta que el mapa de clases no puede: "si
    # cambio esto, que se rompe".
    #
    # Se guarda el modulo COMPLETO, no la raiz. Guardando solo la raiz,
    # `from cognia.compresion_salidas import comprimir` quedaba como "cognia" y
    # la pregunta "quien usa compresion_salidas" respondia "nadie" teniendo dos
    # ficheros que lo importaban. Medido el 2026-07-20 con el comando ya
    # montado, que es cuando se vio.
    def visit_Import(self, node):
        for alias in node.names:
            self.importa.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.importa.append(node.module)
        elif node.level:
            self.importa.append("." * node.level)   # from . import x
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.clases.append(Simbolo(node.name, node.lineno))
        anterior, self._clase_actual = self._clase_actual, node.name
        self.generic_visit(node)
        self._clase_actual = anterior

    def _funcion(self, node):
        self.funciones.append(
            Simbolo(node.name, node.lineno, self._clase_actual))
        self.generic_visit(node)

    # async def tambien cuenta: el visitor original se lo saltaba.
    visit_FunctionDef      = _funcion
    visit_AsyncFunctionDef = _funcion


def mapear_fichero(ruta: Path) -> FicheroMapeado:
    """Mapea un .py. Un fichero que no parsea se anota, no revienta."""
    fm = FicheroMapeado(ruta=str(ruta))
    try:
        arbol = ast.parse(ruta.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError) as exc:
        fm.error = f"{type(exc).__name__}: {exc}"
        return fm

    r = _Recorrido()
    r.visit(arbol)
    fm.clases, fm.funciones = r.clases, r.funciones
    fm.importa = sorted(set(r.importa))
    return fm


def mapear(directorio, recursivo: bool = True) -> Dict[str, FicheroMapeado]:
    """Mapea los .py de un directorio. Devuelve {ruta relativa: FicheroMapeado}."""
    base = Path(directorio)
    if not base.is_dir():
        return {}

    patron  = "**/*.py" if recursivo else "*.py"
    salida: Dict[str, FicheroMapeado] = {}

    for py in sorted(base.glob(patron)):
        if any(_saltar(p) for p in py.relative_to(base).parts):
            continue
        salida[py.relative_to(base).as_posix()] = mapear_fichero(py)

    return salida


def resumen(mapa: Dict[str, FicheroMapeado], max_por_fichero: int = 12) -> str:
    """Formato compacto, pensado para caber en un prompt."""
    if not mapa:
        return "Sin ficheros Python."

    lineas = []
    for ruta, fm in mapa.items():
        if fm.error:
            lineas.append(f"{ruta}: [no parsea] {fm.error[:60]}")
            continue
        if fm.vacio:
            continue

        partes = []
        if fm.clases:
            partes.append("clases: " + ", ".join(
                f"{c.nombre}:{c.linea}" for c in fm.clases[:max_por_fichero]))
        sueltas = [f for f in fm.funciones if not f.clase]
        if sueltas:
            partes.append("funciones: " + ", ".join(
                f"{f.nombre}:{f.linea}" for f in sueltas[:max_por_fichero]))

        lineas.append(f"{ruta} — " + " | ".join(partes))

    return "\n".join(lineas) if lineas else "Sin simbolos."


def dependencias(mapa: Dict[str, FicheroMapeado],
                 solo_internos: bool = True) -> Dict[str, List[str]]:
    """
    Que fichero depende de que modulo.

    Con `solo_internos`, se queda con los modulos que son ficheros del propio
    mapa: es lo que contesta "si toco esto, que se rompe". Las dependencias
    externas (json, ast, urllib) son ruido para esa pregunta.
    """
    propios = {Path(r).stem for r in mapa}
    salida: Dict[str, List[str]] = {}

    for ruta, fm in mapa.items():
        # Se compara por el ultimo segmento: `cognia.compresion_salidas` es el
        # fichero `compresion_salidas.py` del mapa.
        mods = [m for m in fm.importa
                if not solo_internos or m.split(".")[-1] in propios]
        if mods:
            salida[ruta] = sorted(set(mods))
    return salida


def quien_usa(mapa: Dict[str, FicheroMapeado], modulo: str) -> List[str]:
    """
    Ficheros que importan `modulo`. El grafo al reves, que es como se pregunta
    de verdad: "voy a cambiar compresion_salidas, a quien afecta".

    Casa tanto `compresion_salidas` como `cognia.compresion_salidas`: al
    usuario no se le puede exigir que sepa con que ruta lo importo cada uno.
    """
    m = modulo.replace(".py", "").replace("/", ".").split(".")[-1]
    return sorted(ruta for ruta, fm in mapa.items()
                  if any(imp.split(".")[-1] == m for imp in fm.importa))


def buscar(mapa: Dict[str, FicheroMapeado], termino: str) -> List[str]:
    """Donde esta definido algo. Devuelve 'ruta:linea  etiqueta'."""
    t = termino.lower()
    hits = []
    for ruta, fm in mapa.items():
        for s in fm.clases + fm.funciones:
            if t in s.nombre.lower():
                hits.append(f"{ruta}:{s.linea}  {s.etiqueta()}")
    return hits
