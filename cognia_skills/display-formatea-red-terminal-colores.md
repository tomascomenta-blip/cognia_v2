---
name: display-formatea-red-terminal-colores
description: Crea display.py que formatea la red en terminal con colores ANSI según el estado del nodo.
auto_generated: true
verified: oraculo duro via 'generar_codigo': RESULTADO generar_codigo display.py: OK (mejor de 1 candidatos unicos, rank=test (args: display.py | def display_ne
version: 0.1.0
---

## Cuando usar
Tareas como: Crea display.py que formatea la red en terminal con colores ANSI según el estado del nodo.

## Procedimiento verificado
1. ACCION: generar_codigo display.py | def display_network(nodes, size):     ANSI_COLORS = {         'active': '\033[0;36m',         'decaying': '
2. ACCION: escribir_archivo display.py |  ```python def format_network(nodes):     colors = {         'active': '\033[0;36m',         'decaying': '\
3. ACCION: escribir_archivo display.py | import sys  def format_network(n):     if n < 5:         size = 5     else:         size = n     for y in r
4. ACCION: ejecutar python display.py
5. ACCION: escribir_archivo display.py | '''def formatear_red(nodos):     # Implementación de la función para formatear la red en terminal con color
6. ACCION: ejecutar python display.py
7. ACCION: escribir_archivo display.py | import sys import os  def formatear_red():     if os.path.exists('red.txt'):         with open('red.txt', '

## Verificacion
Cerrar SIEMPRE corriendo los tests (tool `tests`) y confirmar 'N passed'.
