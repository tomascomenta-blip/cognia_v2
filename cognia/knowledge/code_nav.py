# -*- coding: utf-8 -*-
"""Navegación de código tipo LSP sin language server (find-def / find-refs).

Motivación (2026-07-21, mandato OSS): OpenCode/SCIP/Aider coinciden en que darle
al modelo "go-to-definition / find-references / call-hierarchy" sobre el código
es más barato y fiable que hacerle leer ficheros a ciegas. Cognia ya tiene el
grafo (`code_graph.py`) pero (a) se consulta por vecindad genérica y (b) esas
consultas leen la BD (source='code_graph'), que si no se ha indexado devuelve
VACÍO en silencio — justo el modo de fallo documentado del repo ("Cognia degrada
en silencio"). Este módulo responde las mismas preguntas construyendo el índice
DIRECTAMENTE del AST (stdlib, sin BD, determinista), así nunca miente por estado
de BD desactualizado.

Complementa a `repo_map` (repo_map = dónde mirar globalmente; code_nav = la
vecindad local de un símbolo/módulo). Caché por firma de mtime como repo_map.
"""
from __future__ import annotations

import ast
from pathlib import Path

from cognia.knowledge.code_graph import (
    PAQUETES_DEFAULT,
    _archivos_py,
    _imports_de,
    _modulo_de,
)
from cognia.knowledge.repo_map import _firma

# (raiz, paquetes, firma) -> Indice
_CACHE: dict = {}


class Indice:
    """Índice de navegación construido del AST. Todo dict, cero BD."""

    __slots__ = ("defs", "imports", "importado_por", "sym_def", "sym_ref")

    def __init__(self):
        self.defs: dict = {}            # modulo -> [símbolos top-level]
        self.imports: dict = {}         # modulo -> set(módulos internos importados)
        self.importado_por: dict = {}   # modulo -> set(módulos que lo importan)
        self.sym_def: dict = {}         # símbolo -> set(módulos que lo definen)
        self.sym_ref: dict = {}         # símbolo -> set(módulos que lo referencian)


def _refs_de(tree) -> set:
    """Nombres referenciados en el módulo (Name.id + Attribute.attr)."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _construir(raiz: Path, paquetes) -> Indice:
    archivos = _archivos_py(raiz, paquetes)
    clave = (str(raiz), tuple(paquetes), _firma(archivos))
    hit = _CACHE.get(clave)
    if hit is not None:
        return hit

    idx = Indice()
    for path in archivos:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        mod = _modulo_de(path, raiz)
        syms = [n.name for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef))]
        idx.defs[mod] = syms
        idx.imports[mod] = {m for m in _imports_de(tree, paquetes) if m != mod}
        for s in syms:
            idx.sym_def.setdefault(s, set()).add(mod)
        for s in _refs_de(tree):
            idx.sym_ref.setdefault(s, set()).add(mod)

    for mod, imps in idx.imports.items():
        for imp in imps:
            if imp in idx.defs:
                idx.importado_por.setdefault(imp, set()).add(mod)

    for k in [k for k in _CACHE if k[0] == clave[0] and k[1] == clave[1]]:
        del _CACHE[k]
    _CACHE[clave] = idx
    return idx


def vecindad(objetivo: str, raiz=None, paquetes=PAQUETES_DEFAULT,
             max_items: int = 20) -> dict:
    """Vecindad de un módulo o símbolo en el grafo de código.

    Si `objetivo` es un módulo indexado (p.ej. 'cognia.agent.tools'): devuelve
    qué importa, quién lo importa y qué define. Si es un símbolo (una función o
    clase): devuelve dónde se define y qué módulos lo referencian.
    Retorna dict con {tipo, objetivo, ...listas...}."""
    idx = _construir(Path(raiz) if raiz else Path(__file__).resolve().parents[2],
                     paquetes)
    obj = objetivo.strip()

    if obj in idx.defs:  # es un módulo
        return {
            "tipo": "modulo",
            "objetivo": obj,
            "define": sorted(idx.defs.get(obj, []))[:max_items],
            "importa": sorted(m for m in idx.imports.get(obj, set())
                              if m in idx.defs)[:max_items],
            "importado_por": sorted(idx.importado_por.get(obj, set()))[:max_items],
        }

    # es (o se trata como) un símbolo
    definido_en = sorted(idx.sym_def.get(obj, set()))
    referenciado_en = sorted(m for m in idx.sym_ref.get(obj, set())
                             if m not in definido_en)
    return {
        "tipo": "simbolo",
        "objetivo": obj,
        "definido_en": definido_en[:max_items],
        "referenciado_en": referenciado_en[:max_items],
        "n_referencias": len(referenciado_en),
        "encontrado": bool(definido_en or referenciado_en),
    }


def formatear(v: dict) -> str:
    """Render compacto de la vecindad para inyectar al modelo."""
    if v["tipo"] == "modulo":
        out = [f"modulo {v['objetivo']}:"]
        if v["define"]:
            out.append("  define: " + ", ".join(v["define"]))
        if v["importa"]:
            out.append("  importa: " + ", ".join(v["importa"]))
        if v["importado_por"]:
            out.append("  importado_por: " + ", ".join(v["importado_por"]))
        return "\n".join(out)
    # símbolo
    if not v["encontrado"]:
        return f"simbolo '{v['objetivo']}': no encontrado en el codigo indexado"
    out = [f"simbolo {v['objetivo']}:"]
    if v["definido_en"]:
        out.append("  definido_en: " + ", ".join(v["definido_en"]))
    if v["referenciado_en"]:
        out.append(f"  referenciado_en ({v['n_referencias']}): "
                   + ", ".join(v["referenciado_en"]))
    return "\n".join(out)
