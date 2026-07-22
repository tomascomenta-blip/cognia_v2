# -*- coding: utf-8 -*-
"""Repo-map: selector de contexto por PageRank personalizado (idea de Aider).

Motivación (2026-07-21, mandato OSS): `code_graph.py` ya construye el grafo del
código (imports/defines/llama_a) pero solo se consultaba por VECINDAD. Aider
(`aider/repomap.py`) demostró que lo valioso de un grafo de código para un LLM
es usarlo como SELECTOR DE CONTEXTO: correr PageRank con un vector de
personalización sesgado hacia lo que la tarea menciona, y renderizar bajo un
presupuesto de tokens los símbolos más relevantes. Para un modelo cuantizado con
ventana chica eso es exactamente lo que hace falta: contexto denso y pertinente,
no un volcado del repo.

Diseño (respeta las restricciones del repo):
- Reutiliza el MISMO extractor AST de `code_graph.py` (cero deps nuevas; evoluciona,
  no duplica — regla del mandato). `networkx` ya está en `pyproject.toml`.
- NO toca la BD: es un cálculo puro sobre el árbol de ficheros, determinista y
  barato (PageRank sobre ~500 nodos/miles de aristas = milisegundos).
- Caché en proceso por firma barata (nº de ficheros + max mtime): no reparsea el
  repo en cada llamada del agente (optimización pedida: evitar trabajo redundante).
- Granularidad de módulo (el punto fuerte del grafo actual): nodo = módulo,
  arista = importador -> importado, de modo que PageRank premia a los módulos
  núcleo (muy importados) y la personalización acerca el foco a la consulta.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from cognia.knowledge.code_graph import (
    PAQUETES_DEFAULT,
    _archivos_py,
    _imports_de,
    _modulo_de,
)

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Palabras que no aportan señal como "término mencionado" (ES+EN, cortas comunes).
_STOP = {
    "de", "la", "el", "que", "los", "las", "un", "una", "uno", "por", "con",
    "para", "sin", "del", "al", "en", "es", "se", "su", "lo", "como", "mas",
    "the", "and", "for", "with", "this", "that", "from", "into", "not", "you",
    "code", "codigo", "archivo", "modulo", "funcion", "clase", "repo",
}

# caché en proceso: (raiz, paquetes, firma) -> (defs, imports)
_CACHE: dict = {}


def _firma(archivos: list) -> tuple:
    """Firma barata del árbol: (nº ficheros, mtime máximo). Cambia si se edita
    o se agrega/borra un .py, así la caché se invalida sola sin escanear hashes."""
    mx = 0.0
    for p in archivos:
        try:
            mx = max(mx, p.stat().st_mtime)
        except OSError:
            pass
    return (len(archivos), round(mx, 3))


def _defs_de(tree) -> list:
    """Símbolos definidos a nivel de módulo (funciones y clases top-level)."""
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(n.name)
    return out


def _construir(raiz: Path, paquetes) -> tuple:
    """Parsea el repo UNA vez -> (defs_por_modulo, imports_internos_por_modulo).

    Cacheado por firma de mtime: llamadas repetidas del agente no repiten el
    parseo salvo que el código cambie."""
    archivos = _archivos_py(raiz, paquetes)
    clave = (str(raiz), tuple(paquetes), _firma(archivos))
    hit = _CACHE.get(clave)
    if hit is not None:
        return hit

    defs: dict = {}      # modulo -> [símbolos]
    imports: dict = {}   # modulo -> set(módulos internos importados)
    for path in archivos:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        mod = _modulo_de(path, raiz)
        defs[mod] = _defs_de(tree)
        imports[mod] = {m for m in _imports_de(tree, paquetes) if m != mod}

    resultado = (defs, imports)
    # La caché es pequeña (una entrada por firma); limpiar entradas viejas de la
    # misma raíz/paquetes para no acumular tras muchas ediciones.
    for k in [k for k in _CACHE if k[0] == clave[0] and k[1] == clave[1]]:
        del _CACHE[k]
    _CACHE[clave] = resultado
    return resultado


def _norm_mentioned(mentioned) -> set:
    """Normaliza términos de la tarea a un set de tokens minúsculos con señal."""
    if not mentioned:
        return set()
    if isinstance(mentioned, str):
        toks = _WORD.findall(mentioned)
    else:
        toks = []
        for m in mentioned:
            toks.extend(_WORD.findall(str(m)))
    return {t.lower() for t in toks if len(t) >= 3 and t.lower() not in _STOP}


def _pagerank(defs: dict, imports: dict, terms: set) -> dict:
    """PageRank sobre el grafo de módulos, con personalización hacia `terms`.

    Aristas: importador -> importado (solo módulos indexados), de modo que la
    masa fluye hacia los módulos núcleo. La personalización siembra probabilidad
    inicial en los módulos cuyo nombre o símbolos casan con la consulta ->
    ranking relativo a la tarea (no un ranking global fijo)."""
    import networkx as nx

    G = nx.DiGraph()
    G.add_nodes_from(defs)
    for mod, imps in imports.items():
        for imp in imps:
            if imp in defs and imp != mod:
                # Peso acumulado: varios import del mismo par refuerzan la arista.
                if G.has_edge(mod, imp):
                    G[mod][imp]["weight"] += 1.0
                else:
                    G.add_edge(mod, imp, weight=1.0)

    pers = None
    if terms:
        seed = {}
        for mod, syms in defs.items():
            hay = any(t in mod.lower() for t in terms) or any(
                t in s.lower() for s in syms for t in terms)
            if hay:
                seed[mod] = 1.0
        tot = sum(seed.values())
        if tot > 0:
            pers = {n: seed.get(n, 0.0) / tot for n in G.nodes}

    if G.number_of_nodes() == 0:
        return {}
    try:
        return nx.pagerank(G, personalization=pers, weight="weight")
    except Exception:
        # Fallback ultra-defensivo: si PageRank no converge, rankea por grado de
        # entrada (nº de importadores), que es la señal dominante que aproxima.
        indeg = dict(G.in_degree())
        tot = sum(indeg.values()) or 1
        return {n: indeg.get(n, 0) / tot for n in G.nodes}


def repo_map(mentioned=None, raiz=None, paquetes=PAQUETES_DEFAULT,
             max_modulos: int = 12, max_symbols: int = 6,
             max_chars: int = 1800) -> dict:
    """Devuelve un mapa rankeado del código relevante a `mentioned`.

    Parámetros:
      mentioned: str o iterable con la tarea/consulta (sesga el ranking). None =
                 ranking estructural global (módulos núcleo primero).
      max_chars: presupuesto de tamaño del texto (aprox. tokens) — se cortan los
                 módulos de menor rank que no quepan (como el --map-tokens de Aider).

    Retorna dict: {texto, modulos (list en orden), n_modulos, ranks}."""
    raiz = Path(raiz) if raiz else Path(__file__).resolve().parents[2]
    defs, imports = _construir(raiz, paquetes)
    if not defs:
        return {"texto": "", "modulos": [], "n_modulos": 0, "ranks": {}}

    terms = _norm_mentioned(mentioned)
    ranks = _pagerank(defs, imports, terms)

    # nº de importadores por módulo (para anotar "quién lo usa" en la salida).
    importado_por: dict = {}
    for imps in imports.values():
        for imp in imps:
            if imp in defs:
                importado_por[imp] = importado_por.get(imp, 0) + 1

    # Desempate estable: rank desc, luego nº de importadores desc, luego nombre.
    orden = sorted(defs, key=lambda m: (-ranks.get(m, 0.0),
                                        -importado_por.get(m, 0), m))

    lineas = []
    usados = []
    for mod in orden[:max_modulos]:
        syms = list(defs.get(mod) or [])
        if terms:
            # Los símbolos que casan la consulta van primero.
            syms.sort(key=lambda s: (not any(t in s.lower() for t in terms), s))
        vis = ", ".join(syms[:max_symbols]) if syms else "(sin defs top-level)"
        n_imp = importado_por.get(mod, 0)
        linea = f"{mod}  [usado_por={n_imp}]\n    {vis}"
        proyectado = sum(len(x) + 1 for x in lineas) + len(linea)
        if lineas and proyectado > max_chars:
            break
        lineas.append(linea)
        usados.append(mod)

    return {"texto": "\n".join(lineas), "modulos": usados,
            "n_modulos": len(defs), "ranks": ranks}
