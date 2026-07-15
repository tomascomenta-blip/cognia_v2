# -*- coding: utf-8 -*-
"""Grafo de código nativo (fusión Graphify/CodeGraph dentro del KG).

Gap del inventario 2026-07-14: el KnowledgeGraph solo tenía tripletas de
conversación/documentos; no había representación navegable del CÓDIGO.
Este módulo indexa los paquetes del repo con ast (stdlib, cero deps) y
guarda el resultado EN EL MISMO knowledge_graph (source="code_graph"),
así /kg-camino, /kg-responder, get_neighbors, etc. funcionan sobre el
código gratis — un solo grafo, no dos sistemas (regla del mandato).

Predicados:
- modulo  --importa-->      modulo      (solo imports internos del repo)
- modulo  --define-->       mod.func / mod.Clase
- clase   --tiene_metodo--> metodo
- func    --llama_a-->      func        (best-effort: solo nombres que
                                         existen como definición indexada,
                                         para no meter ruido de builtins)

Reindexado idempotente: borra los triples previos con source="code_graph"
antes de escribir (el código cambia; el grafo debe reflejar el presente).
"""
import ast
import os
import time
from pathlib import Path

from storage.db_pool import db_connect_pooled as db_connect

PAQUETES_DEFAULT = ("cognia", "node", "coordinator", "storage", "shattering")
_SKIP_DIRS = {".git", "venv", "venv312", "__pycache__", ".pytest_cache",
              "node_modules", "web3d", "dist"}


def _modulo_de(path: Path, raiz: Path) -> str:
    """cognia/agent/tools.py -> cognia.agent.tools"""
    rel = path.relative_to(raiz).with_suffix("")
    partes = list(rel.parts)
    if partes[-1] == "__init__":
        partes = partes[:-1]
    return ".".join(partes)


def _archivos_py(raiz: Path, paquetes) -> list:
    out = []
    for paq in paquetes:
        base = raiz / paq
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for f in filenames:
                if f.endswith(".py"):
                    out.append(Path(dirpath) / f)
    return out


def _imports_de(tree, paquetes) -> set:
    """Módulos internos importados (prefijo en `paquetes`)."""
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                mods.add(a.name)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.add(n.module)
    return {m for m in mods if m.split(".")[0] in paquetes}


def _llamadas_en(fn_node) -> set:
    """Nombres llamados dentro de una función (Name o attr final)."""
    out = set()
    for n in ast.walk(fn_node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def indexar_codigo(raiz=None, kg=None, paquetes=PAQUETES_DEFAULT) -> dict:
    """Indexa el código del repo al KG. Devuelve métricas reales."""
    from cognia.knowledge.graph import KnowledgeGraph
    t0 = time.time()
    raiz = Path(raiz) if raiz else Path(__file__).resolve().parents[2]
    kg = kg or KnowledgeGraph()

    # pasada 1: parsear todo y juntar definiciones (para resolver llamadas)
    arboles = {}          # modulo -> (tree, path)
    defs_idx = {}         # nombre_simple -> fqn (última gana; best-effort)
    for path in _archivos_py(raiz, paquetes):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8",
                                            errors="replace"))
        except SyntaxError:
            continue
        mod = _modulo_de(path, raiz)
        arboles[mod] = tree
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
                defs_idx[n.name] = f"{mod}.{n.name}"

    # reindexado idempotente: fuera lo viejo de code_graph. La tabla la
    # crea el schema central en el primer add_triple: si aún no existe
    # (KG virgen, tests), no hay nada que borrar.
    import sqlite3
    conn = db_connect(kg.db)
    try:
        borrados = conn.execute(
            "DELETE FROM knowledge_graph WHERE source = 'code_graph'"
        ).rowcount
        conn.commit()
    except sqlite3.OperationalError:
        borrados = 0
    finally:
        conn.close()
    kg._dirty = True

    # pasada 2: triples
    n_triples = 0

    def _add(s, p, o):
        nonlocal n_triples
        kg.add_triple(s, p, o, weight=1.0, source="code_graph")
        n_triples += 1

    for mod, tree in arboles.items():
        for imp in _imports_de(tree, paquetes):
            if imp != mod:
                _add(mod, "importa", imp)
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fqn = f"{mod}.{n.name}"
                _add(mod, "define", fqn)
                for llamado in _llamadas_en(n):
                    destino = defs_idx.get(llamado)
                    if destino and destino != fqn:
                        _add(fqn, "llama_a", destino)
            elif isinstance(n, ast.ClassDef):
                fqn = f"{mod}.{n.name}"
                _add(mod, "define", fqn)
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef,
                                      ast.AsyncFunctionDef)):
                        _add(fqn, "tiene_metodo", m.name)

    return {"modulos": len(arboles), "triples": n_triples,
            "borrados_previos": borrados,
            "secs": round(time.time() - t0, 1)}


def _consulta(kg, campo_where: str, valor: str, campo_out: str) -> list:
    """SELECT dirigido sobre los triples de code_graph (get_facts matchea
    subject OR object y limita a 20 — acá la dirección importa)."""
    from cognia.knowledge.graph import KnowledgeGraph
    kg = kg or KnowledgeGraph()
    conn = db_connect(kg.db)
    try:
        rows = conn.execute(
            f"SELECT {campo_out} FROM knowledge_graph "
            f"WHERE predicate='importa' AND {campo_where}=? "
            f"AND source='code_graph'", (valor.lower(),)
        ).fetchall()
    finally:
        conn.close()
    return sorted({r[0] for r in rows})


def dependencias(modulo: str, kg=None) -> list:
    """Qué importa `modulo` (directo)."""
    return _consulta(kg, "subject", modulo, "object")


def quien_importa(modulo: str, kg=None) -> list:
    """Módulos que importan a `modulo` (grafo inverso)."""
    return _consulta(kg, "object", modulo, "subject")
