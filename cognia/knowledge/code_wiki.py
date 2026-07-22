# -*- coding: utf-8 -*-
"""Wiki Markdown del código desde el grafo (idea de deepwiki-open).

Motivación (2026-07-22, mandato OSS): deepwiki-open muestra el PRODUCTO de salida
que le faltaba a nuestro grafo de código — una página navegable por módulo con
diagramas. Este generador es determinista y CPU puro (sin LLM para lo
estructural): toma el índice AST de `code_nav` (ya verificado) y emite, por
módulo, qué define, qué importa, quién lo importa, y un snippet **Mermaid** de
dependencias (texto plano, sin render pesado). La prosa de resumen por módulo
queda opcional para el modelo; lo estructural no lo necesita.

Completa la suite de inteligencia de código: repo_map (ubicar) + code_grafo
(navegar) + code_wiki (documentar). Cero deps nuevas.
"""
from __future__ import annotations

import re
from pathlib import Path

from cognia.knowledge.code_graph import PAQUETES_DEFAULT
from cognia.knowledge.code_nav import _construir

_ID = re.compile(r"[^0-9A-Za-z_]")


def _nid(mod: str) -> str:
    """id de nodo Mermaid seguro (sin puntos ni guiones)."""
    return "n_" + _ID.sub("_", mod)


def mermaid_deps(mod: str, idx, max_lado: int = 6) -> str:
    """Diagrama Mermaid de la vecindad inmediata de `mod` (importadores → mod →
    importados). Acotado a `max_lado` por lado para que quepa y sea legible."""
    importa = sorted(m for m in idx.imports.get(mod, set()) if m in idx.defs)[:max_lado]
    importado_por = sorted(idx.importado_por.get(mod, set()))[:max_lado]
    lineas = ["```mermaid", "graph LR", f'  {_nid(mod)}["{mod}"]']
    for imp in importa:
        lineas.append(f'  {_nid(mod)} --> {_nid(imp)}["{imp}"]')
    for imp in importado_por:
        lineas.append(f'  {_nid(imp)}["{imp}"] --> {_nid(mod)}')
    lineas.append("```")
    return "\n".join(lineas)


def pagina_modulo(mod: str, idx) -> str:
    """Página Markdown de un módulo."""
    define = sorted(idx.defs.get(mod, []))
    importa = sorted(m for m in idx.imports.get(mod, set()) if m in idx.defs)
    importado_por = sorted(idx.importado_por.get(mod, set()))
    out = [f"# `{mod}`", ""]
    out.append("**Define:** " + (", ".join(f"`{s}`" for s in define)
                                 if define else "_(sin defs top-level)_"))
    out.append("")
    out.append("**Importa (interno):** " + (", ".join(f"`{m}`" for m in importa)
                                            if importa else "_(nada interno)_"))
    out.append("")
    out.append(f"**Importado por ({len(importado_por)}):** "
               + (", ".join(f"`{m}`" for m in importado_por)
                  if importado_por else "_(nadie)_"))
    out.append("")
    out.append(mermaid_deps(mod, idx))
    out.append("")
    return "\n".join(out)


def generar_wiki(raiz=None, paquetes=PAQUETES_DEFAULT, destino=None) -> dict:
    """Genera el wiki completo. Si `destino` se pasa, escribe una página .md por
    módulo + un index.md; siempre devuelve {n_modulos, index, paginas:{mod:md}}.

    Escritura idempotente: sobrescribe. El índice ordena por nº de importadores
    (los módulos núcleo primero), útil como mapa de arranque del repo."""
    idx = _construir(Path(raiz) if raiz else Path(__file__).resolve().parents[2],
                     paquetes)
    orden = sorted(idx.defs, key=lambda m: (-len(idx.importado_por.get(m, set())), m))
    paginas = {mod: pagina_modulo(mod, idx) for mod in orden}

    lineas_idx = ["# Wiki del código de Cognia", "",
                  f"{len(orden)} módulos (ordenados por nº de importadores).", ""]
    for mod in orden:
        n = len(idx.importado_por.get(mod, set()))
        lineas_idx.append(f"- `{mod}` — usado por {n}")
    index = "\n".join(lineas_idx)

    if destino:
        dest = Path(destino)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "index.md").write_text(index, encoding="utf-8")
        for mod, md in paginas.items():
            (dest / (mod.replace(".", "_") + ".md")).write_text(md, encoding="utf-8")

    return {"n_modulos": len(orden), "index": index, "paginas": paginas}
