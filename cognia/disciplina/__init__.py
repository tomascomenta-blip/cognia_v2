"""
cognia/disciplina/ — mecanismos contra la espiral de parches.

El problema, dicho por el dueño: "cuando a una IA le pides que corrija algo, se
va llenando de ruido, se va haciendo mas tonta y solo quedan parches por encima
que a la larga dejan de funcionar".

No es una impresion, esta medido:

  - Laban et al., "LLMs Get Lost In Multi-Turn Conversation" (arXiv:2505.06120,
    >200.000 conversaciones): caida media del 39% en multi-turno. La aptitud
    solo baja 16%, la NO-FIABILIDAD sube 112%. Mecanismo nombrado: los modelos
    "dependen en exceso de intentos de respuesta previos (incorrectos)".
  - Huang et al., ICLR 2024 (arXiv:2310.01798): auto-corregirse SIN verificador
    externo EMPEORA el resultado. Con feedback oraculo mejora.

De ahi la regla que gobierna todo este paquete:

    UN BUCLE DE REPARACION SIN VERIFICADOR EXTERNO DETERMINISTA NO SE ARREGLA
    CON MAS INTENTOS. SE CORTA.

Y de ahi tambien lo que este paquete NO hace: pedirle al modelo que "respire
hondo y revise su trabajo". Esa es la tecnica mas popular del sector y la
evidencia esta en contra. El respiro profundo se implementa como CORTE
ESTRUCTURAL, no como prompt.
"""

from .reparacion import (
    Disyuntor,
    HuellaSintoma,
    Intento,
    huella_de_texto,
    normalizar,
    MAX_INTENTOS,
    HUELLA_REPETIDA_CORTA,
    MISMO_ERROR_CONSECUTIVO,
)

__all__ = [
    "Disyuntor",
    "HuellaSintoma",
    "Intento",
    "huella_de_texto",
    "normalizar",
    "MAX_INTENTOS",
    "HUELLA_REPETIDA_CORTA",
    "MISMO_ERROR_CONSECUTIVO",
]
