# -*- coding: utf-8 -*-
"""Saneo determinista de respuestas del agente (E-INT #31, 2026-07-08).

El experto LoRA a temp=0 a veces degenera la COLA del cierre `responder`
repitiendo un token basura ("Listo, tarea completada. fitte fitte fitte...")
— visto en la batería e2e del producto instalado. La tarea cierra bien
(postcondición OK) pero el texto que VE el usuario queda sucio.

Regla quirúrgica: cortar SOLO una cola de la misma palabra repetida >=3
veces al final (más un fragmento suelto de esa palabra si el sampling cortó
a mitad, y puntuación colgante). Nada de LLM, nada de heurísticas difusas:
una repetición >=3 de la MISMA palabra terminando la respuesta nunca es
contenido legítimo del cierre de una tarea.
"""
from __future__ import annotations

import re

# cola: palabra (2-24 chars) repetida >=3 veces (con espacios/puntuación
# blanda entre medio) + opcional fragmento-prefijo de la misma palabra
_TAIL_RUN_RX = re.compile(
    r"\s+(\S{2,24}?)(?:[\s,.;:]+\1\b){2,}[\s,.;:]*(\S{0,23})?\s*$",
    re.UNICODE)


def trim_degenerate_tail(text: str) -> str:
    """Corta la cola degenerada; si no hay, devuelve el texto igual."""
    if not text:
        return text
    out = text
    for _ in range(3):   # por si quedan capas (raro)
        m = _TAIL_RUN_RX.search(out)
        if not m:
            break
        frag = m.group(2) or ""
        # el fragmento final solo se come si es prefijo de la palabra repetida
        if frag and not m.group(1).startswith(frag):
            break
        out = out[:m.start()].rstrip()
    return out if out.strip() else text
