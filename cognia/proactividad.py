"""
proactividad.py — el rol de automatizacion: pensar en el usuario, no solo
en el encargo.

Pedido del dueno (2026-07-20): "cuando le pides algo a una IA, se limita a lo
que le pides; no piensa en el usuario. La idea es que el sistema vaya
anadiendo cosas el mismo". Este modulo es ese rol, montado sobre el modelo
residente (la decision fue roles sobre qwen2.5-coder-14b, no entrenar
especialistas: BDraft ya dejo un KILL pre-registrado de esa via, y en 16GB no
caben mas modelos junto al 14B).

REGLA DE ORO, aprendida hoy con un bug real: la proactividad PROPONE, nunca
ejecuta sin permiso. Esta misma manana el pipeline entrego una pagina HTML que
nadie habia pedido — con confianza y hasta puntuada — por decidir el solo.
Anadir cosas sin consentimiento no es proactividad: es desobediencia con
buena intencion. Por eso esto devuelve SUGERENCIAS y el usuario decide.

El contrato prompt-parser es explicito a proposito: el prompt le pide al
modelo exactamente el formato que el parser espera ("- " por linea, "NADA" si
no hay nada). La primera version no lo hacia y el parseo casaba por suerte.

Autoria: escrito por Cognia via G4 (generar -> revisar -> integrar). El
centinela corrigio en revision el contrato prompt-parser (v1 no daba reglas
de formato al modelo) y dos restos del parseo (NADA con puntuacion, numeracion
sin comprobar el digito).
"""

from __future__ import annotations

import logging
from typing import List

from .llm_local import disponible, generar

logger = logging.getLogger(__name__)

# Menos de esto es ruido ("- si", "- ok"); mas es una parrafada, no una
# sugerencia accionable.
_MIN_CHARS = 15
_MAX_CHARS = 200


def proponer_extras(tarea: str, respuesta: str,
                    max_propuestas: int = 3) -> List[str]:
    """
    Hasta max_propuestas sugerencias concretas de que anadir o hacer despues.

    Lista vacia si no hay nada que valga la pena, si no hay LLM o si algo
    falla. NUNCA lanza: la proactividad es un extra, no puede romper la
    respuesta que el usuario si pidio.
    """
    try:
        if not disponible():
            return []

        prompt = (
            f"Task: {tarea[:300]}\n"
            f"Response: {respuesta[:800]}\n"
            f"Propose up to {max_propuestas} concrete NEXT additions the "
            f"user did not ask for but would likely appreciate. Think about "
            f"what is missing: tests? error handling? documentation? a usage "
            f"example? persistence? an edge case?\n"
            f"Rules: one proposal per line, each starting with '- '. Be "
            f"concrete and actionable. Do NOT repeat anything already done "
            f"in the response. If nothing worthwhile remains, answer "
            f"exactly: NADA"
        )

        respuesta_llm = generar(prompt, temperature=0.4, max_tokens=250)
        if not respuesta_llm:
            return []

        limpia = respuesta_llm.strip()
        # startswith y no ==: el modelo remata con "NADA." o "NADA\n" a veces.
        if limpia.upper().startswith("NADA"):
            return []

        propuestas = []
        for linea in limpia.splitlines():
            linea = linea.strip()
            if linea.startswith(("- ", "* ")):
                propuesta = linea.lstrip("-* ").strip()
            elif len(linea) > 2 and linea[0].isdigit() and linea[1] == ".":
                propuesta = linea[2:].strip()
            else:
                continue
            if _MIN_CHARS <= len(propuesta) <= _MAX_CHARS:
                propuestas.append(propuesta)

        return propuestas[:max_propuestas]

    except Exception as e:
        logger.warning("Proactividad: me la salto: %s", e)
        return []
