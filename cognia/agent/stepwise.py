"""CoT DIRIGIDO por turno — la única mejora de razonamiento que sobrevivió el bench e2e.

Medido en cognia_v3/eval/bench_reasoning.py (2026-07-01, 3B Q4_K_M deployado, 16 items
verificables + 4 de formato):
  - direct 0.3125  ->  CoT POR TURNO 0.8125 (+50 pts, temp=0).
  - self-consistency k=3 a temp 0.7: 0.6875 a 3x costo -> DESCARTADA (peor que CoT greedy).
  - CoT en el SYSTEM prompt: 0.3125 (= baseline) -> DESCARTADO (el 3B no se auto-dispara).
  - El CoT por turno ROMPE el formato estricto (compliance 0.75 -> 0.25) -> el empujón NO se
    aplica cuando el usuario pide un formato exacto de salida.

Por eso: detector barato (regex) que agrega la instrucción de pensar paso a paso SOLO cuando la
pregunta pide cálculo/razonamiento cuantitativo Y NO pide formato exacto. Cero LLM, cero costo.
"""
import re

# pedidos de formato exacto: acá el CoT DAÑA (medido) -> nunca aumentar
_FORMAT_RX = re.compile(
    r"(únicamente|unicamente|solamente|\bsolo con\b|exactamente|\bjson\b|"
    r"sin ning[uú]n otro texto|una sola palabra|\bformato\b|\bxml\b|\byaml\b)",
    re.IGNORECASE)

# señales de pregunta cuantitativa/razonamiento multi-paso
_REASON_RX = re.compile(
    r"(cu[aá]nt|calcul|qu[eé] n[uú]mero|cu[aá]l es el n[uú]mero|por ciento|"
    r"\bpromedio\b|\bporcentaje\b|en qu[eé] d[ií]a|qu[eé] d[ií]a|a qu[eé] hora|"
    r"\bdescuento\b|\bdoble\b|\btriple\b|\bmitad\b)",
    re.IGNORECASE)

STEP_TAG = ("\n\nPensá paso a paso: mostrá el razonamiento en pasos numerados y recién "
            "al final dá la respuesta.")


def wants_exact_format(text: str) -> bool:
    return bool(_FORMAT_RX.search(text))


def needs_stepwise(text: str) -> bool:
    """True si conviene el empujón CoT: pregunta cuantitativa SIN pedido de formato exacto."""
    if wants_exact_format(text):
        return False
    if _REASON_RX.search(text):
        return True
    # fallback: pregunta con al menos dos números (relación cuantitativa implícita)
    return "?" in text and len(re.findall(r"\d+", text)) >= 2


def augment_stepwise(text: str) -> str:
    """Texto del turno de usuario que va al LLM (el historial guarda el original)."""
    return text + STEP_TAG if needs_stepwise(text) else text


# ── Detectores CP1 (06_AGENTE_PLAN §2 #5): cada palanca cara corre SOLO ──
# donde aplica. Mismo patron que needs_stepwise: regex, cero LLM.

# nombre de funcion pedido explicitamente. Patrones ESTRICTOS (backticks o
# parentesis obligatorios): "function so that..." NO debe extraer 'so' —
# mejor None (la palanca no activa) que un entry point inventado que
# envenena los tests visibles.
_ENTRY_RX = [
    re.compile(r"`(\w+)\s*\("),                                        # `foo(...)`
    re.compile(r"(?:function|funci[oó]n|method|m[eé]todo|class|clase)\s+`(\w+)`",
               re.IGNORECASE),                                         # function `foo`
    re.compile(r"(?:function|funci[oó]n|method|m[eé]todo)\s+(\w+)\s*\(",
               re.IGNORECASE),                                         # function foo(
    re.compile(r"\bdef\s+(\w+)\s*\("),                                 # def foo(
    re.compile(r"(?:name|nombre|llamada|named|called)\s+`(\w+)`",
               re.IGNORECASE),                                         # name `foo`
]

_CODE_TASK_RX = re.compile(
    r"(write|escrib[ií]|implement|fix|arregl[aá]|corrig[eí]|debug)\w*\b.*?"
    r"(function|funci[oó]n|class|clase|method|m[eé]todo|c[oó]digo|code)|"
    r"\bdef\s+\w+\s*\(",
    re.IGNORECASE | re.DOTALL)


def extract_entry_point(task: str):
    """Nombre de la funcion/clase objetivo si la tarea lo pide explicito,
    None si no. Es el prerequisito de test-first y BoN: sin entry point no
    hay asserts ejecutables que sirvan de oraculo."""
    for rx in _ENTRY_RX:
        m = rx.search(task or "")
        if m and m.group(1).lower() not in ("python", "return", "def"):
            return m.group(1)
    return None


def tests_first_applies(task: str) -> bool:
    """True si conviene generar el test ANTES del codigo (palanca #2):
    tarea de codigo con entry point explicito y sin pedido de formato
    exacto (mismo veto medido que el CoT)."""
    if wants_exact_format(task):
        return False
    return bool(_CODE_TASK_RX.search(task or "")) and \
        extract_entry_point(task) is not None


def bon_applies(task: str) -> bool:
    """True si conviene Best-of-N (palanca #1). Misma señal que test-first
    porque el juez de BoN SON los tests visibles: sin oraculo ejecutable,
    BoN degrada a 'elegir a ojo' (prohibido, P8/CYCLE 12)."""
    return tests_first_applies(task)


def repair_applies(err_type: str) -> bool:
    """True si el ciclo repair paga (palanca #4): hay veredicto EXTERNO real
    (traceback/assert/timeout de ejecucion). 'empty' y 'missing_func' no
    son reparables con feedback (no hay nada que trazar) -> regenerar."""
    return err_type in ("syntax", "assert", "runtime", "timeout")
