# -*- coding: utf-8 -*-
"""Visión / percepción de pantalla de Cognia (JARVIS §4.3).

`percepcion` compone captura (mss) + detección de cambios (dHash) + árbol UIA +
gate de ventana sensible en un servicio real-time read-only (modo sombra). El VLM
(ver la imagen con un modelo) llega aparte; el árbol UIA ya da percepción
determinista sin VRAM.
"""
from .percepcion import Percepcion, ServicioPercepcion, describir  # noqa: F401
from .agente_pantalla import (  # noqa: F401
    AgentePantalla,
    Registro,
    politica_por_control,
)
