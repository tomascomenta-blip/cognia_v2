"""Oráculo determinista de las suites held-out COGNIA 3B (P0-ii).

Semántica normativa en SPEC_SUITES.md. Un ítem PASA si TODAS las restricciones
presentes en su `oracle` se cumplen sobre la respuesta foldeada. Binario por
ítem (McNemar necesita binario). Sin LLM-juez (regla de la Parte 3 §3.3).
"""
import json
import re
import unicodedata


def fold(t: str) -> str:
    """lowercase + sin acentos (mismo patrón que train_qlora_kaggle.py)."""
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower())
                   if not unicodedata.combining(c))


_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def ultimo_numero(t: str):
    """Último número de la respuesta (acepta coma decimal española)."""
    hits = _NUM_RE.findall(t.replace("−", "-"))
    if not hits:
        return None
    return float(hits[-1].replace(",", "."))


def ultima_opcion(respuesta: str, opciones):
    """De una lista de opciones, la que aparece ULTIMA en la respuesta (None
    si ninguna aparece). Espejo de ultimo_numero para respuestas de eleccion:
    con CoT el razonamiento menciona TODAS las opciones y must_any/not_any
    falsean; la respuesta final viene al final. Match con borde de palabra
    ('Ada' NO matchea dentro de 'ubicada')."""
    r = fold(respuesta)
    mejor, pos = None, -1
    for op in opciones:
        rx = re.compile(r"(?<![a-z0-9])" + re.escape(fold(op)) + r"(?![a-z0-9])")
        ultimo = None
        for m in rx.finditer(r):
            ultimo = m.start()
        if ultimo is not None and ultimo > pos:
            mejor, pos = op, ultimo
    return mejor


def oracle_pass(respuesta: str, oracle: dict) -> bool:
    r = fold(respuesta)
    ultimo_de = oracle.get("ultimo_de")
    if ultimo_de and ultima_opcion(respuesta, ultimo_de["opciones"]) != ultimo_de["gana"]:
        return False
    must_all = oracle.get("must_all") or []
    if any(fold(k) not in r for k in must_all):
        return False
    must_any = oracle.get("must_any") or []
    if must_any and not any(fold(k) in r for k in must_any):
        return False
    not_any = oracle.get("not_any") or []
    if any(fold(k) in r for k in not_any):
        return False
    number = oracle.get("number")
    if number is not None:
        n = ultimo_numero(respuesta)
        if n is None or abs(n - float(number)) > 1e-6:
            return False
    return True


# Heurística de idioma para el criterio (b) de G5 (sin dependencia externa;
# suficiente para distinguir es/en/otro en respuestas de >=8 palabras).
_ES_STOP = {"el", "la", "los", "las", "de", "que", "y", "en", "un", "una",
            "es", "por", "con", "para", "del", "se", "no", "su", "al", "como",
            "más", "pero", "este", "esta", "son", "hay", "muy"}
_EN_STOP = {"the", "of", "and", "to", "in", "is", "that", "it", "for", "on",
            "with", "as", "are", "this", "was", "be", "by", "an", "not", "or"}


def es_espanol(respuesta: str) -> bool:
    """¿La respuesta está en español? Para respuestas LARGAS (>=8 palabras)
    exige dominancia de stopwords es (semántica original, confiable ahí).
    Para CORTAS solo VETA evidencia de inglés: 'Feliz', '7' o 'uno, dos,
    tres' son español/neutro válido — exigirles stopwords era un falso
    negativo del instrumento (diagnóstico G5 2026-07-10: 6/13 'fallos' eran
    respuestas correctas cortas; el oráculo de contenido ya discrimina)."""
    palabras = re.findall(r"[a-záéíóúñü]+", respuesta.lower())
    if not palabras:
        return True  # solo dígitos/símbolos: neutro (el oracle valida contenido)
    es = sum(1 for p in palabras if p in _ES_STOP)
    en = sum(1 for p in palabras if p in _EN_STOP)
    if len(palabras) >= 8:
        return es > en
    return es >= en  # corta: veta solo si el inglés DOMINA


# ── oráculo G2A (tool-use formato ACCION): primera línea ACCION del output ──
_ACCION_RE = re.compile(r"ACCI[OÓ]N:\s*(\w+)", re.IGNORECASE)


def accion_first(respuesta: str):
    """(tool, bloque) de la PRIMERA ACCION emitida; bloque = texto desde esa
    ACCION hasta la siguiente ACCION o el final (los args, incl. multilínea).
    (None, '') si no hay ninguna ACCION parseable."""
    m = _ACCION_RE.search(respuesta)
    if not m:
        return None, ""
    m2 = _ACCION_RE.search(respuesta, m.end())
    bloque = respuesta[m.end():m2.start()] if m2 else respuesta[m.end():]
    return m.group(1), bloque


def accion_pass(respuesta: str, oracle: dict) -> bool:
    """PASA si la primera ACCION usa una tool esperada y (si hay args_regex)
    los args del bloque matchean (p.ej. el archivo correcto)."""
    tool, bloque = accion_first(respuesta)
    if tool is None or tool not in (oracle.get("accion_tools") or []):
        return False
    rx = oracle.get("args_regex")
    if rx and not re.search(rx, bloque, re.IGNORECASE):
        return False
    return True


CLAVES_VALIDAS = {"must_all", "must_any", "not_any", "number", "ultimo_de"}
CLAVES_G2A = {"accion_tools", "args_regex"}
GATES = {"G1", "G2R", "G3", "G5", "G2A"}


def carga_suite(path: str) -> list:
    """Carga y VALIDA una suite JSONL. Lanza ValueError ante cualquier defecto."""
    items, ids = [], set()
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                raise ValueError(f"{path}:{lineno}: línea vacía")
            it = json.loads(line)
            for campo in ("id", "gate", "dominio", "idioma", "shots", "prompt",
                          "oracle", "max_new_tokens"):
                if campo not in it:
                    raise ValueError(f"{path}:{lineno}: falta campo {campo!r}")
            if it["id"] in ids:
                raise ValueError(f"{path}:{lineno}: id duplicado {it['id']}")
            ids.add(it["id"])
            if it["gate"] not in GATES:
                raise ValueError(f"{path}:{lineno}: gate inválido {it['gate']}")
            if it["idioma"] not in ("es", "en"):
                raise ValueError(f"{path}:{lineno}: idioma inválido")
            if it["shots"] not in (0, 3):
                raise ValueError(f"{path}:{lineno}: shots inválido")
            if it["gate"] == "G2A":
                extra = set(it["oracle"]) - CLAVES_G2A
                if extra:
                    raise ValueError(f"{path}:{lineno}: claves de oracle inválidas {extra}")
                if not it["oracle"].get("accion_tools"):
                    raise ValueError(f"{path}:{lineno}: G2A sin accion_tools")
            else:
                extra = set(it["oracle"]) - CLAVES_VALIDAS
                if extra:
                    raise ValueError(f"{path}:{lineno}: claves de oracle inválidas {extra}")
                restricciones = [k for k in CLAVES_VALIDAS
                                 if it["oracle"].get(k) not in (None, [], "")]
                if not restricciones:
                    raise ValueError(f"{path}:{lineno}: oracle sin restricciones")
            if not it["prompt"].strip():
                raise ValueError(f"{path}:{lineno}: prompt vacío")
            items.append(it)
    return items
