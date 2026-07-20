"""
cognia/reasoning/abstraction_engine.py
=======================================
Motor de abstraccion (pieza 7 de la mision creativa). Ante un problema concreto
piensa en PRINCIPIOS, no en ejemplos: (1) extrae su FORMA ABSTRACTA (despoja los
detalles del dominio, queda la estructura general), (2) resuelve esa forma
abstracta, (3) TRADUCE la solucion abstracta de vuelta al problema concreto
original.

El backend vivo se toca SOLO via creative_generate (creative_llm.py). Patron de
parseo robusto + REINTENTO heredado de analogy_engine / idea_eval: si la 1a
llamada en server frio vuelve sin las 3 partes, se reintenta una vez; si tras el
reintento siguen faltando, None (honesto: no se logro el ciclo completo, no se
inventa).
"""

import re
from typing import Optional

from .creative_llm import creative_generate


# Mapea cada clave de bloque (con/sin acento, mayus/minus) a su nombre canonico.
_CLAVES = {
    "forma abstracta":    "forma_abstracta",
    "solucion abstracta": "solucion_abstracta",
    "solucion concreta":  "solucion_concreta",
}

# Una linea "CLAVE: valor". La clave se captura cruda (letras y espacios, para
# "forma abstracta"/"solucion concreta") y se normaliza despues contra _CLAVES.
# El separador es ':'; el valor es el resto de la linea. Un ':' interno cae en el
# valor (la regex es no-greedy en la clave pero el valor toma todo el resto).
_LINEA_RE = re.compile(
    r"^\s*([A-Za-zÀ-ſ ]+?)\s*:\s*(.+?)\s*$",
    re.UNICODE,
)


def _strip_accents(s: str) -> str:
    """Quita acentos basicos para casar 'solucion'/'solución' sin depender de unicodedata."""
    table = str.maketrans("áéíóúÁÉÍÓÚ",
                          "aeiouAEIOU")
    return s.translate(table)


def _canon_clave(raw_name: str) -> Optional[str]:
    """Normaliza el nombre de una clave de bloque a su forma canonica, o None."""
    key = _strip_accents(raw_name).strip().lower()
    return _CLAVES.get(key)


def _parse_abstraction(text: str) -> dict:
    """Parsea una respuesta estructurada con tres claves:

        FORMA ABSTRACTA: <el problema despojado a su estructura general>
        SOLUCION ABSTRACTA: <como se resuelve esa forma general>
        SOLUCION CONCRETA: <esa solucion traducida de vuelta al problema original>

    Robusto a: claves en mayus/minus, con/sin acentos, separador ':'; lineas de
    continuacion que pertenecen al valor abierto (un ':' interno NO rompe el
    bloque: si la "clave" de esa linea no es una de las nuestras, se foldea como
    continuacion del valor abierto, igual que _parse_analogies).

    Devuelve dict SOLO con las claves que parseo (las faltantes no aparecen);
    valores .strip()eados. Si una clave aparece repetida gana la primera.
    """
    out = {}
    last_key = None  # ultima clave canonica abierta, para foldear continuaciones

    for line in (text or "").splitlines():
        stripped = line.strip()

        m = _LINEA_RE.match(line)
        if m:
            clave = _canon_clave(m.group(1))
            if clave is not None:
                # Primera aparicion gana; un valor ya abierto no se pisa.
                if clave not in out:
                    out[clave] = m.group(2).strip()
                    last_key = clave
                else:
                    last_key = clave
                continue
            # Linea "algo: ..." que NO es una de nuestras claves: tratala como
            # continuacion del valor abierto (p.ej. un valor con un ':' dentro).
        if not stripped:
            continue
        if last_key is not None:
            out[last_key] = (out[last_key] + " " + stripped).strip()
        # Si no hay clave abierta todavia (preambulo del modelo), se ignora.

    return out


def _build_prompt(problem: str) -> str:
    """Arma el prompt que pide las 3 partes en el formato exacto."""
    bloque_fmt = (
        "FORMA ABSTRACTA: <el problema despojado a su estructura general>\n"
        "SOLUCION ABSTRACTA: <como se resuelve esa forma general>\n"
        "SOLUCION CONCRETA: <esa solucion traducida de vuelta al problema original>"
    )
    return (
        f"Problema: {problem.strip()}\n\n"
        "Pensa en PRINCIPIOS, no en ejemplos. (1) Extrae la FORMA ABSTRACTA del "
        "problema: despoja los detalles del dominio y queda con su estructura "
        "general. (2) Resuelve esa FORMA ABSTRACTA (SOLUCION ABSTRACTA). (3) "
        "TRADUCE esa solucion abstracta de vuelta al problema concreto original "
        "(SOLUCION CONCRETA). Se concreto, no genericies.\n"
        "Responde SOLO en este formato exacto, una clave por linea:\n"
        f"{bloque_fmt}\n"
    )


def solve_by_abstraction(orchestrator, problem: str) -> Optional[dict]:
    """Resuelve un problema por abstraccion via el LLM vivo.

    - Sin orchestrator o problem vacio -> None (sin tocar el backend).
    - 1 llamada (temp 0.6, max_tokens 600) que pide FORMA ABSTRACTA / SOLUCION
      ABSTRACTA / SOLUCION CONCRETA en el formato exacto.
    - Parsea con _parse_abstraction; si falta alguna de las 3 claves REINTENTA
      una vez (rescata el edge de server frio, mismo documentado en
      analogy_engine.find_analogies). Si tras el reintento NO estan las 3,
      devuelve None (honesto: no se logro el ciclo completo).
    - Acotado para el i3 (~8 tok/s): 1 llamada (2 con el reintento). No mas.

    Devuelve {"forma_abstracta","solucion_abstracta","solucion_concreta"}.
    """
    if orchestrator is None or not problem or not problem.strip():
        return None

    prompt = _build_prompt(problem)
    raw = creative_generate(orchestrator, prompt, temperature=0.6, max_tokens=600)
    partes = _parse_abstraction(raw or "")
    # Reintento si falta alguna clave: la 1a generacion en server frio a veces
    # vuelve vacia/incompleta (mismo edge documentado en analogy_engine).
    if len(partes) < 3:
        raw = creative_generate(orchestrator, prompt, temperature=0.6, max_tokens=600)
        retry = _parse_abstraction(raw or "")
        # Conserva lo ya parseado y completa con lo nuevo (no piso valores buenos).
        for k, v in retry.items():
            partes.setdefault(k, v)

    # Solo se considera exito el CICLO COMPLETO (las 3 partes); si no, None.
    if not all(partes.get(k) for k in
               ("forma_abstracta", "solucion_abstracta", "solucion_concreta")):
        return None

    return {
        "forma_abstracta":    partes["forma_abstracta"],
        "solucion_abstracta": partes["solucion_abstracta"],
        "solucion_concreta":  partes["solucion_concreta"],
    }
