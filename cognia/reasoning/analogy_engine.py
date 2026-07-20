"""
cognia/reasoning/analogy_engine.py
==================================
Motor de analogias transversales (pieza 2 de la mision creativa). Ante un
problema, lo traduce a OTROS DOMINIOS (biologia, fisica, economia, ecologia,
ingenieria, sistemas sociales, etc.), mira como ESE dominio resuelve el problema
analogo y ADAPTA esa solucion de vuelta al problema original.

Ejemplo guia: "el contexto se satura" -> analogia "ciudad congestionada" -> el
dominio del trafico resuelve con semaforos/rutas prioritarias/distribucion ->
adaptar eso a la gestion de memoria/contexto.

El backend vivo se toca SOLO via creative_generate (creative_llm.py). Patron de
parseo robusto + REINTENTO heredado de hypothesis.generate_many / idea_eval:
si la 1a llamada en server frio vuelve vacia/sin bloques, se reintenta una vez;
si sigue 0 utiles, [] (honesto, no se inventa).

NOTA: NO reusar el AnalogyEngine viejo de cognia_v3 (Levenshtein lexico, zombie).
Esto es fresco sobre el LLM vivo.
"""

import re
from typing import Optional

from .creative_llm import creative_generate


# Dominios curados (ASCII puro) desde donde traer analogias. find_analogies
# elige k de aca de forma DETERMINISTICA (ver mas abajo) para que sea testeable.
DOMINIOS = [
    "biologia",
    "evolucion",
    "ecologia",
    "fisica",
    "quimica",
    "economia",
    "psicologia",
    "sistemas sociales",
    "logistica",
    "ingenieria",
    "videojuegos",
    "vida cotidiana",
]


# Mapea cada clave de bloque (con/sin acento, mayus/minus) a su nombre canonico.
_CLAVES = {
    "dominio":    "dominio",
    "analogia":   "analogia",
    "solucion":   "solucion",
    "adaptacion": "adaptacion",
}

# Una linea "CLAVE: valor". La clave se captura cruda (letras, con acentos y
# espacios para "sistemas sociales") y se normaliza despues contra _CLAVES.
# El separador es ':'; el valor es el resto de la linea.
_LINEA_RE = re.compile(
    r"^\s*([A-Za-zÀ-ſ ]+?)\s*:\s*(.+?)\s*$",
    re.UNICODE,
)


def _strip_accents(s: str) -> str:
    """Quita acentos basicos para casar 'analogia'/'analogía' y 'solucion'/'solución'."""
    table = str.maketrans("áéíóúÁÉÍÓÚ",
                          "aeiouAEIOU")
    return s.translate(table)


def _canon_clave(raw_name: str) -> Optional[str]:
    """Normaliza el nombre de una clave de bloque a su forma canonica, o None."""
    key = _strip_accents(raw_name).strip().lower()
    return _CLAVES.get(key)


def _flush_bloque(acc: dict) -> Optional[dict]:
    """Cierra un bloque acumulado: lo devuelve solo si tiene analogia Y adaptacion
    no vacias (un bloque sin la vuelta al problema original no sirve)."""
    if not acc:
        return None
    analogia   = (acc.get("analogia") or "").strip()
    adaptacion = (acc.get("adaptacion") or "").strip()
    if not analogia or not adaptacion:
        return None
    return {
        "dominio":    (acc.get("dominio") or "").strip(),
        "analogia":   analogia,
        "solucion":   (acc.get("solucion") or "").strip(),
        "adaptacion": adaptacion,
    }


def _parse_analogies(text: str, expected_domains: list) -> list:
    """Parsea una respuesta estructurada en bloques (uno por dominio):

        DOMINIO: biologia
        ANALOGIA: <situacion equivalente en ese dominio>
        SOLUCION: <como ese dominio lo resuelve>
        ADAPTACION: <como aplicar eso al problema original>
        ---

    Robusto a: claves en mayus/minus, con/sin acentos, separador ':'; bloques
    separados por lineas con "---" o por la aparicion de una nueva clave DOMINIO.
    Tolera que el modelo devuelva menos bloques de los pedidos.

    Devuelve lista de {dominio, analogia, solucion, adaptacion} SOLO con bloques
    que tengan al menos analogia Y adaptacion no vacias. Si un bloque no trae
    DOMINIO explicito, se le asigna por posicion el dominio esperado correspondiente
    (expected_domains[i]); si tampoco hay, queda con dominio "".
    """
    out = []
    acc = {}
    last_key = None  # ultima clave abierta, para foldear lineas de continuacion

    def _cerrar():
        nonlocal acc, last_key
        bloque = _flush_bloque(acc)
        if bloque is not None:
            out.append(bloque)
        acc = {}
        last_key = None

    for line in (text or "").splitlines():
        stripped = line.strip()
        # Separador explicito de bloque.
        if stripped and set(stripped) <= {"-"} and len(stripped) >= 3:
            _cerrar()
            continue

        m = _LINEA_RE.match(line)
        if m:
            clave = _canon_clave(m.group(1))
            if clave is not None:
                # Nueva clave DOMINIO arranca un bloque nuevo aunque no haya "---".
                if clave == "dominio" and acc:
                    _cerrar()
                acc[clave] = m.group(2).strip()
                last_key = clave
                continue
            # Linea "algo: ..." que NO es una de nuestras claves: tratala como
            # continuacion del valor abierto (p.ej. una analogia con un ':' dentro).
        if not stripped:
            continue
        if last_key is not None:
            acc[last_key] = (acc[last_key] + " " + stripped).strip()
        # Si no hay clave abierta todavia (preambulo del modelo), se ignora.

    _cerrar()

    # Asigna dominio por posicion a los bloques que no lo trajeron explicito.
    for i, bloque in enumerate(out):
        if not bloque["dominio"] and i < len(expected_domains):
            bloque["dominio"] = expected_domains[i]
    return out


def _pick_domains(problem: str, k: int) -> list:
    """Elige k dominios DIVERSOS de DOMINIOS de forma DETERMINISTICA (sin random,
    para que el test sea reproducible). Rota el punto de arranque por el hash del
    problema asi distintos problemas tocan distintos dominios, pero el mismo
    problema siempre da el mismo set."""
    n = len(DOMINIOS)
    # hash() de Python esta saleado por proceso; usamos una suma de ords estable.
    seed = sum(ord(c) for c in problem) % n
    return [DOMINIOS[(seed + i) % n] for i in range(k)]


def _build_prompt(problem: str, domains: list, esencia: Optional[str]) -> str:
    """Arma el prompt que pide UN bloque por dominio en el formato exacto."""
    nombres = ", ".join(domains)
    ctx = f"Esencia del problema: {esencia.strip()}\n" if esencia and esencia.strip() else ""
    bloques_fmt = (
        "DOMINIO: <nombre del dominio>\n"
        "ANALOGIA: <situacion equivalente del problema en ese dominio>\n"
        "SOLUCION: <como ese dominio resuelve esa situacion>\n"
        "ADAPTACION: <como aplicar esa solucion de vuelta al problema original>\n"
        "---"
    )
    return (
        f"Problema: {problem.strip()}\n"
        f"{ctx}\n"
        f"Traduci este problema a CADA uno de estos dominios: {nombres}.\n"
        "Para cada dominio: (1) describe la ANALOGIA (la situacion equivalente del "
        "problema en ese dominio), (2) la SOLUCION (como ese dominio resuelve esa "
        "situacion) y (3) la ADAPTACION (como aplicar esa solucion de vuelta al "
        "problema original). Se concreto, no genericies.\n"
        f"Responde SOLO con un bloque por dominio en este formato exacto, separados "
        f"por una linea '---':\n{bloques_fmt}\n"
    )


def essence(orchestrator, problem: str) -> Optional[str]:
    """Extrae la 'esencia abstracta' del problema en una frase corta para enriquecer
    el prompt de analogias. Una sola llamada corta; None si falla o problem vacio.
    Se usa dentro de find_analogies manteniendo 1-2 llamadas LLM totales (acotado
    para el i3 ~8 tok/s)."""
    if orchestrator is None or not problem or not problem.strip():
        return None
    prompt = (
        f"Problema: {problem.strip()}\n\n"
        "Resume la ESENCIA ABSTRACTA de este problema en UNA sola frase corta "
        "(el mecanismo o tension de fondo, sin jerga del dominio original). "
        "Responde solo con la frase, sin preambulo.\n"
    )
    raw = creative_generate(orchestrator, prompt, temperature=0.5, max_tokens=80)
    if not raw:
        return None
    # Una frase: cortamos en la primera linea util.
    frase = raw.strip().splitlines()[0].strip()
    return frase or None


def find_analogies(orchestrator, problem: str, k: int = 3) -> list:
    """Genera k analogias transversales para un problema via el LLM vivo.

    - Sin orchestrator o problem vacio -> [].
    - Clamp k a [2, 6]. Elige k dominios diversos de DOMINIOS (deterministico,
      rotado por el problema; ver _pick_domains).
    - 1 llamada corta opcional para la esencia + 1 llamada (temp 0.8, 700 tokens)
      que pide un bloque ANALOGIA/SOLUCION/ADAPTACION por dominio.
    - Parsea con _parse_analogies; si 0 bloques utiles, REINTENTA una vez; si sigue
      0, devuelve [] (honesto). Tope: 2 llamadas de analogias (1-2 incl. esencia
      se mantiene acotado: esencia + 1a; el reintento reemplaza, no suma esencia).

    Devuelve lista de dicts {dominio, analogia, solucion, adaptacion}.
    """
    if orchestrator is None or not problem or not problem.strip():
        return []

    k = max(2, min(6, int(k)))
    problem = problem.strip()
    domains = _pick_domains(problem, k)

    # Esencia (acotado): enriquece el prompt; si falla, seguimos sin ella.
    esencia = essence(orchestrator, problem)

    prompt = _build_prompt(problem, domains, esencia)
    raw = creative_generate(orchestrator, prompt, temperature=0.8, max_tokens=700)
    bloques = _parse_analogies(raw or "", domains)
    # La 1a llamada de generacion en server frio devuelve a veces vacio/sin
    # bloques (mismo edge documentado en hypothesis.generate_many): un reintento
    # lo rescata. Sin esto el usuario ve [] cuando el backend SI estaba vivo.
    if not bloques:
        raw = creative_generate(orchestrator, prompt, temperature=0.8, max_tokens=700)
        bloques = _parse_analogies(raw or "", domains)

    return bloques
