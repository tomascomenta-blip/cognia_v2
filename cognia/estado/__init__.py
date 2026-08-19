# -*- coding: utf-8 -*-
"""Canal de ESTADO del turno: contabilidad verificable, separada de la prosa.

Existe porque la compactacion se diseno como un problema de RESUMEN y no de
CONTABILIDAD: al resumir se destruye justo el registro verificable (seguimiento
de artefactos 2,19-2,45 sobre 5,0, identico en las tres implementaciones grandes
sobre 36.611 mensajes de produccion). Lo que vive aqui son acumuladores que NO
se resumen: se serializan enteros en el envelope del turno.

Este __init__ se deja a proposito vacio de re-exports: cada modulo se importa por
su ruta completa (`from cognia.estado.presupuesto_progreso import Progreso`) para
que anadir un modulo hermano no obligue a tocar este fichero.
"""
