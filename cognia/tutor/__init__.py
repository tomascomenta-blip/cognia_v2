# -*- coding: utf-8 -*-
"""cognia.tutor — modo tutor de Cognia (estilo DeepTutor, con Cognia como
modelo tutor y el centinela anti-inyeccion delante del material web)."""

from cognia.tutor.motor import (
    Leccion,
    estudiar_tema,
    evaluar_respuesta,
    responder_duda,
)

__all__ = ["Leccion", "estudiar_tema", "responder_duda", "evaluar_respuesta"]
