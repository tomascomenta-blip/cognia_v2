"""
cognia/reasoning/repetition_detector.py
========================================
Detector de repeticion (pieza 6 de la mision creativa). Identifica cuando la IA
repite patrones aprendidos (mismas estrategias/respuestas) y, cuando ocurre,
fuerza la generacion de enfoques FUNDAMENTALMENTE DISTINTOS.

Es DETERMINISTICO y SIN embeddings (no hay sentence-transformers instalado):
mide similitud LEXICA (Jaccard sobre tokens normalizados). Esto es suficiente
para detectar casi-duplicados de texto generado (mismas palabras clave) sin
depender de un modelo de embeddings ni de la red.

El backend vivo se toca SOLO via creative_generate (creative_llm.py), en
force_alternatives. El resto (similarity/diversity/find_repeats) no llama al LLM.
"""

from typing import Optional

from .creative_llm import creative_generate


# Tabla de quita-acentos compartida con analogy_engine._strip_accents: casa
# 'energia'/'energía' y 'solucion'/'solución' para que la similitud no se rompa
# por una tilde.
_ACCENTS = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")

# Stopwords ES cortas: palabras de funcion que no aportan a la "estrategia" de
# una idea (inflan el Jaccard de forma artificial). Lista deliberadamente corta.
_STOPWORDS = {
    "de", "la", "el", "los", "las", "un", "una", "que", "en", "con", "por",
    "para", "del", "al", "se", "su", "sus", "lo", "es", "y", "o", "a",
}

# Umbral de casi-duplicado por defecto: a partir de aca dos ideas se consideran
# "la misma" (mismos tokens significativos). 0.6 = comparten >=60% del vocabulario
# util tras descartar union.
_THRESHOLD = 0.6


def _tokens(s: str) -> set:
    """Normaliza un texto a un set de tokens significativos.

    lower + quita acentos + split por todo lo no-alfanumerico; descarta tokens
    de menos de 3 chars y las stopwords. Set (no lista) porque el Jaccard solo
    mira presencia, no frecuencia.
    """
    s = (s or "").translate(_ACCENTS).lower()
    out = set()
    buff = []
    for ch in s:
        if ch.isalnum():
            buff.append(ch)
        else:
            if buff:
                tok = "".join(buff)
                buff = []
                if len(tok) >= 3 and tok not in _STOPWORDS:
                    out.add(tok)
    if buff:
        tok = "".join(buff)
        if len(tok) >= 3 and tok not in _STOPWORDS:
            out.add(tok)
    return out


def similarity(a: str, b: str) -> float:
    """Jaccard lexico entre dos textos: |interseccion| / |union| de sus tokens.

    1.0 = mismos tokens significativos; 0.0 = sin tokens en comun (o ambos
    vacios). Deterministico.
    """
    ta = _tokens(a)
    tb = _tokens(b)
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


def diversity(ideas: list) -> float:
    """Que tan variado es un conjunto de ideas: 1 - promedio de similitud de
    TODOS los pares (i<j). 1.0 si hay 0 o 1 idea (nada que comparar).

    Cerca de 1.0 = todas distintas; cerca de 0.0 = casi todas iguales.
    """
    n = len(ideas)
    if n < 2:
        return 1.0
    total = 0.0
    pares = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += similarity(ideas[i], ideas[j])
            pares += 1
    return 1.0 - (total / pares)


def find_repeats(ideas: list, threshold: float = _THRESHOLD) -> list:
    """Pares (i, j, sim) con i<j cuya similitud >= threshold: casi-duplicados.

    Lista vacia si nada repite. Util para mostrarle al usuario QUE ideas son
    redundantes, no solo el score agregado.
    """
    out = []
    n = len(ideas)
    for i in range(n):
        for j in range(i + 1, n):
            sim = similarity(ideas[i], ideas[j])
            if sim >= threshold:
                out.append((i, j, sim))
    return out


def force_alternatives(orchestrator, problem: str, existing: list,
                       n: int = 3, threshold: float = _THRESHOLD) -> list:
    """Pide al LLM N enfoques FUNDAMENTALMENTE DISTINTOS de los `existing`.

    Le pasa la lista existing como angulos YA CUBIERTOS para que los evite, y
    devuelve SOLO las hipotesis genuinamente nuevas: las que tienen
    similarity < threshold contra TODAS las existing (si una se parece a
    cualquiera de las ya presentes, se descarta). Alta temperatura para empujar
    la divergencia.

    [] si orchestrator es None, problem vacio, o no salio nada nuevo.
    """
    if orchestrator is None or not problem or not problem.strip():
        return []
    existing = [e for e in (existing or []) if e and e.strip()]

    # Import tardio: _parse_numbered vive en hypothesis y este modulo se importa
    # desde alli (evita el ciclo de import al cargar el paquete).
    from .hypothesis import _parse_numbered

    n = max(1, int(n))
    evita = "\n".join(f"- {e}" for e in existing) if existing else "(ninguno)"
    prompt = (
        f"Problema: {problem.strip()}\n\n"
        "Evita estos angulos YA cubiertos (no los repitas ni los reformules):\n"
        f"{evita}\n\n"
        f"Propon EXACTAMENTE {n} hipotesis FUNDAMENTALMENTE DISTINTAS de las de "
        "arriba: otros mecanismos, otras causas, otras estrategias. Nada de "
        "variaciones de lo ya cubierto. Se conciso y concreto.\n"
        "Responde SOLO con la lista numerada, una por linea, en este formato "
        "exacto:\n1. ...\n2. ...\n"
    )
    raw = creative_generate(orchestrator, prompt, temperature=0.97, max_tokens=420)
    candidatas = _parse_numbered(raw, n) if raw else []

    nuevas = []
    for cand in candidatas:
        # Genuinamente nueva = no se parece a NINGUNA existente ni a las nuevas
        # ya aceptadas (evita meter dos alternativas casi-iguales entre si).
        if all(similarity(cand, e) < threshold for e in existing) and \
           all(similarity(cand, nv) < threshold for nv in nuevas):
            nuevas.append(cand)
    return nuevas
