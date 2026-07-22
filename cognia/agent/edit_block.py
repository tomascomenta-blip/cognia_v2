# -*- coding: utf-8 -*-
"""Edición SEARCH/REPLACE con matching en cascada (idea de Aider `EditBlockCoder`).

Motivación (2026-07-21, mandato OSS): el agente solo tenía `escribir_archivo`
(sobrescribe el fichero entero). Para un modelo cuantizado pequeño eso es frágil
y caro: reescribir 200 líneas para cambiar 3 gasta tokens y arrastra el resto del
fichero a la deriva (el 3B "acorta" lo que no repite -> pérdida de datos, ya
cazado en e2e). La edición quirúrgica por bloque es lo que usan Aider/OpenHands.

Formato (un bloque, o varios seguidos):

    <<<<<<< SEARCH
    código original exacto a encontrar
    =======
    código de reemplazo
    >>>>>>> REPLACE

`apply_edits` intenta, por bloque, dos estrategias en orden creciente de holgura
(como el `do_replace` de Aider):
  1. EXACTO: match literal de subcadena (reemplaza la 1ª ocurrencia).
  2. SANGRÍA: match ignorando la indentación uniforme del bloque y re-aplicando
     la indentación real del fichero al reemplazo. Cubre el fallo típico del
     modelo pequeño: acierta el código pero estropea el sangrado.
Si nada casa, lanza `EditError` cuyo texto NOMBRA el SEARCH fallido y muestra las
líneas reales más parecidas (difflib) — el error ES el siguiente prompt, un lazo
de auto-corrección barato sin coste de arquitectura.

Puro stdlib (re, difflib). Determinista. No toca disco: opera sobre strings.
"""
from __future__ import annotations

import difflib
import re

# Marcadores tolerantes: permiten longitud variable de <, =, > y espacios.
_RE_BLOQUE = re.compile(
    r"<{5,}\s*SEARCH\s*\n(.*?)\n?={5,}\s*\n(.*?)\n?>{5,}\s*REPLACE",
    re.DOTALL,
)


class EditError(Exception):
    """Fallo de aplicación de un bloque; su mensaje está pensado para el modelo."""


def parse_bloques(texto: str) -> list:
    """Extrae [(search, replace), ...] del texto. Lista vacía si no hay bloques."""
    return [(m.group(1), m.group(2)) for m in _RE_BLOQUE.finditer(texto)]


def _lead(s: str) -> str:
    return s[: len(s) - len(s.lstrip())]


def _match_exacto(content: str, search: str, replace: str):
    if search and search in content:
        return content.replace(search, replace, 1)
    return None


def _match_sangria(content: str, search: str, replace: str):
    """Match ignorando la indentación uniforme; re-indenta el reemplazo con la
    sangría real del fichero (delta constante). Preserva la indentación relativa
    dentro del bloque."""
    s_lines = search.splitlines()
    if not any(l.strip() for l in s_lines):
        return None
    c_lines = content.splitlines(keepends=True)
    n = len(s_lines)
    if n == 0 or n > len(c_lines):
        return None
    s_strip = [l.strip() for l in s_lines]
    fnb = next(i for i, l in enumerate(s_lines) if l.strip())  # 1ª línea no vacía
    s_lead = len(_lead(s_lines[fnb]))

    for i in range(0, len(c_lines) - n + 1):
        window = [w.rstrip("\n") for w in c_lines[i:i + n]]
        if [w.strip() for w in window] != s_strip:
            continue
        delta = len(_lead(window[fnb])) - s_lead  # sangría a aplicar al replace
        r_lines = replace.splitlines()
        nuevas = []
        for rl in r_lines:
            if not rl.strip():
                nuevas.append("")
            elif delta >= 0:
                nuevas.append(" " * delta + rl)
            else:
                nuevas.append(rl[min(-delta, len(_lead(rl))):])
        # Preserva el salto de línea final del bloque original.
        block_had_nl = c_lines[i + n - 1].endswith("\n")
        nuevo_bloque = "\n".join(nuevas)
        if block_had_nl:
            nuevo_bloque += "\n"
        return "".join(c_lines[:i]) + nuevo_bloque + "".join(c_lines[i + n:])
    return None


def _pista_cercana(content: str, search: str) -> str:
    """Líneas reales más parecidas al SEARCH, para guiar el reenvío del modelo."""
    c_lines = [l.strip() for l in content.splitlines() if l.strip()]
    s_first = next((l.strip() for l in search.splitlines() if l.strip()), "")
    if not s_first or not c_lines:
        return ""
    cerca = difflib.get_close_matches(s_first, c_lines, n=3, cutoff=0.5)
    if not cerca:
        return ""
    return " | lineas parecidas en el fichero: " + " ; ".join(repr(c) for c in cerca)


def apply_edit(content: str, search: str, replace: str) -> tuple:
    """Aplica UN bloque. Devuelve (nuevo_contenido, estrategia). Lanza EditError."""
    if not search.strip():
        raise EditError("SEARCH vacio: para crear un fichero usa escribir_archivo")
    r = _match_exacto(content, search, replace)
    if r is not None:
        return r, "exacto"
    r = _match_sangria(content, search, replace)
    if r is not None:
        return r, "sangria"
    s0 = search.splitlines()[0].strip() if search.splitlines() else search.strip()
    raise EditError(f"no se encontro el bloque SEARCH (empieza por: {s0!r})"
                    + _pista_cercana(content, search))


def apply_edits(content: str, bloques: list) -> tuple:
    """Aplica varios bloques en orden sobre una copia. Todo o nada: si uno falla,
    lanza EditError y NO deja cambios a medias. Devuelve (nuevo, [estrategias])."""
    if not bloques:
        raise EditError("no hay bloques SEARCH/REPLACE (usa <<<<<<< SEARCH / "
                        "======= / >>>>>>> REPLACE)")
    actual = content
    estrategias = []
    for idx, (search, replace) in enumerate(bloques, 1):
        try:
            actual, como = apply_edit(actual, search, replace)
        except EditError as e:
            raise EditError(f"bloque {idx}/{len(bloques)}: {e}")
        estrategias.append(como)
    return actual, estrategias
