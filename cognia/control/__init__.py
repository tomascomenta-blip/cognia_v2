"""
cognia/control — manos de Cognia.

Control de navegador, escritorio y raton, segun planes/JARVIS_COGNIA.md 4.2.

  permisos.py    gate de seguridad: QUE se puede hacer sin preguntar y que no
  escritorio.py  UI Automation: ventanas, controles, foco, abrir apps
  raton.py       PyAutoGUI, ultimo recurso — pendiente

Se implemento primero el escritorio y no un control de navegador porque es mas
universalizable: UI Automation funciona sobre cualquier ventana (Chrome, Word,
VS Code, el Explorador) sin pedirle al dueño que cambie como arranca sus
programas, mientras que Playwright solo maneja navegadores y ademas el suyo
propio. Playwright/CDP queda para control fino dentro de una pagina.

permisos.py existe ANTES que cualquier capacidad de accion a proposito: Cognia
con mouse y teclado es Cognia capaz de borrar archivos, mandar mensajes y
comprar cosas. El plan lo pone como requisito del dia uno, no como un extra.
"""

from cognia.control.escritorio import Escritorio
from cognia.control.permisos import (ACCIONES, GestorPermisos, Accion,
                                     NIVEL_CONFIRMAR, NIVEL_LIBRE,
                                     NIVEL_PROHIBIDO, Veredicto,
                                     ventana_es_sensible)

__all__ = ["Accion", "Escritorio", "GestorPermisos", "Veredicto", "ACCIONES",
           "NIVEL_LIBRE", "NIVEL_CONFIRMAR", "NIVEL_PROHIBIDO",
           "ventana_es_sensible"]
