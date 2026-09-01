# -*- coding: utf-8 -*-
"""Banco de tareas LARGAS para el harness de Cognia.

Vive FUERA del paquete `cognia/` a proposito: el harness no puede importarlo,
asi que ninguna mejora del harness puede reconocer una tarea del banco.
"""
__all__ = ["esquema", "motor", "runner", "evaluador", "informe"]
