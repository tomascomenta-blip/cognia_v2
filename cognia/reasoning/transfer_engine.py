"""
cognia/reasoning/transfer_engine.py
===================================
Motor de transferencia de conocimiento (pieza 3 de la mision creativa). Dado un
dominio/problema FUENTE (A) y uno OBJETIVO (B), NO busca coincidencias
superficiales: extrae el PRINCIPIO abstracto y general que hace funcionar a la
fuente y lo APLICA de forma concreta al objetivo.

El backend vivo se toca SOLO via creative_generate (creative_llm.py). Patron de
parseo robusto + REINTENTO heredado de abstraction_engine / analogy_engine: si la
1a llamada en server frio vuelve sin las 2 partes, se reintenta una vez; si tras
el reintento siguen faltando, None (honesto: no se logro la transferencia, no se
inventa).

Reusa los helpers de robustez de analogy_engine (_LINEA_RE, _strip_accents,
_canon_clave NO: las claves son propias) para casar claves en mayus/minus,
con/sin acentos, y para foldear un ':' interno del valor como continuacion.
"""

from typing import Optional

from .creative_llm import creative_generate
# Reusamos la regex de linea "CLAVE: valor" y el quita-acentos de analogy_engine
# (mismo formato de bloque); las claves canonicas de ESTA pieza son propias.
from .analogy_engine import _LINEA_RE, _strip_accents


# Mapea cada clave de bloque (con/sin acento, mayus/minus) a su nombre canonico.
_CLAVES = {
    "principio":  "principio",
    "aplicacion": "aplicacion",
}


def _canon_clave(raw_name: str) -> Optional[str]:
    """Normaliza el nombre de una clave de bloque a su forma canonica, o None.

    Propia de esta pieza (claves PRINCIPIO/APLICACION); usa el _strip_accents
    compartido para casar 'aplicacion'/'aplicación' sin depender de unicodedata.
    """
    key = _strip_accents(raw_name).strip().lower()
    return _CLAVES.get(key)


def _parse_transfer(text: str) -> dict:
    """Parsea una respuesta estructurada con dos claves:

        PRINCIPIO: <el principio abstracto y general que hace funcionar a la fuente>
        APLICACION: <como aplicar ese principio al objetivo, concreto>

    Robusto a: claves en mayus/minus, con/sin acentos, separador ':'; lineas de
    continuacion que pertenecen al valor abierto (un ':' interno NO rompe el
    bloque: si la "clave" de esa linea no es una de las nuestras, se foldea como
    continuacion del valor abierto, igual que _parse_abstraction).

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


def _build_prompt(source: str, target: str) -> str:
    """Arma el prompt que pide las 2 partes en el formato exacto."""
    bloque_fmt = (
        "PRINCIPIO: <el principio abstracto y general que hace funcionar a la fuente>\n"
        "APLICACION: <como aplicar ese principio al objetivo, de forma concreta>"
    )
    return (
        f"FUENTE: {source.strip()}\n"
        f"OBJETIVO: {target.strip()}\n\n"
        "No busques coincidencias superficiales: busca el PRINCIPIO fundamental "
        "que comparten. (1) Extrae de la FUENTE el principio abstracto y general "
        "que la hace funcionar (despoja los detalles del dominio, queda el "
        "mecanismo de fondo). (2) APLICA ese principio al OBJETIVO de forma "
        "concreta. Se concreto, no genericies.\n"
        "Responde SOLO en este formato exacto, una clave por linea:\n"
        f"{bloque_fmt}\n"
    )


def transfer_principle(orchestrator, source: str, target: str) -> Optional[dict]:
    """Transfiere el principio que hace funcionar a la FUENTE hacia el OBJETIVO via
    el LLM vivo.

    - Sin orchestrator o source/target vacios -> None (sin tocar el backend).
    - 1 llamada (temp 0.6, max_tokens 500) que pide PRINCIPIO (el principio
      abstracto de la fuente, no detalles superficiales) y APLICACION (ese
      principio aplicado al objetivo) en el formato exacto.
    - Parsea con _parse_transfer; si falta alguna de las 2 claves REINTENTA una
      vez (rescata el edge de server frio, mismo documentado en
      abstraction_engine.solve_by_abstraction). Si tras el reintento NO estan las
      2, devuelve None (honesto: no se logro la transferencia).
    - Acotado para el i3 (~8 tok/s): 1 llamada (2 con el reintento). No mas.

    Devuelve {"principio","aplicacion"}.
    """
    if orchestrator is None or not source or not source.strip() \
            or not target or not target.strip():
        return None

    prompt = _build_prompt(source, target)
    raw = creative_generate(orchestrator, prompt, temperature=0.6, max_tokens=500)
    partes = _parse_transfer(raw or "")
    # Reintento si falta alguna clave: la 1a generacion en server frio a veces
    # vuelve vacia/incompleta (mismo edge documentado en abstraction_engine).
    if len(partes) < 2:
        raw = creative_generate(orchestrator, prompt, temperature=0.6, max_tokens=500)
        retry = _parse_transfer(raw or "")
        # Conserva lo ya parseado y completa con lo nuevo (no piso valores buenos).
        for k, v in retry.items():
            partes.setdefault(k, v)

    # Solo se considera exito la transferencia COMPLETA (las 2 partes); si no, None.
    if not all(partes.get(k) for k in ("principio", "aplicacion")):
        return None

    return {
        "principio":  partes["principio"],
        "aplicacion": partes["aplicacion"],
    }
