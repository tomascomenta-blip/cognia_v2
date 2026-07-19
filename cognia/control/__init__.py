"""
cognia/control — manos de Cognia.

Control de navegador, escritorio y raton, segun planes/JARVIS_COGNIA.md 4.2.

  permisos.py    gate de seguridad: QUE se puede hacer sin preguntar y que no
  navegador.py   capa 1 (Playwright)      — pendiente
  escritorio.py  capa 2 (UI Automation)   — pendiente
  raton.py       capa 3 (PyAutoGUI)       — pendiente

permisos.py existe ANTES que cualquier capacidad de accion a proposito: Cognia
con mouse y teclado es Cognia capaz de borrar archivos, mandar mensajes y
comprar cosas. El plan lo pone como requisito del dia uno, no como un extra.
"""

from cognia.control.permisos import (ACCIONES, GestorPermisos, Accion,
                                     NIVEL_CONFIRMAR, NIVEL_LIBRE,
                                     NIVEL_PROHIBIDO, Veredicto,
                                     ventana_es_sensible)

__all__ = ["Accion", "GestorPermisos", "Veredicto", "ACCIONES",
           "NIVEL_LIBRE", "NIVEL_CONFIRMAR", "NIVEL_PROHIBIDO",
           "ventana_es_sensible"]
