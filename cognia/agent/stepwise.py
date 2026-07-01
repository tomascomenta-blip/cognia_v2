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
