"""
cognia/reasoning/creative_llm.py
================================
Punto unico por el que los modulos creativos hablan con el LLM vivo
(ShatteringOrchestrator compartido). Temperatura alta por defecto.
"""

from typing import Optional


def creative_generate(orchestrator, prompt: str, *,
                      temperature: float = 0.9,
                      max_tokens: int = 320) -> Optional[str]:
    """Genera texto creativo via el orchestrator compartido; None si falla o es muy corto."""
    try:
        res = orchestrator.infer(prompt, max_tokens=max_tokens, temperature=temperature)
        text = res.text if hasattr(res, "text") else str(res)
        text = (text or "").strip()
        return text if len(text) >= 15 else None
    except Exception:
        # Boundary con backend externo: cualquier fallo de inferencia -> None.
        return None
