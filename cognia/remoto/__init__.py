"""
cognia/remoto — control remoto movil de Cognia, estilo Telegram.

Pedido del dueno (2026-07-20): manejar Cognia desde el celular — proyectos
(carpetas donde se abrio el CLI), sesiones con sus tareas y acciones, las
output images, esfuerzo/velocidad/modo, monitores, formularios, el
pensamiento interno, la oficina y los grafos en paneles desplegables, TODOS
los comandos con sugerencias, y mensajes desde el movil al computador.

LA DECISION DE ARQUITECTURA que lo hace posible sin reimplementar nada: cada
sesion es un REPL REAL de Cognia corriendo como subproceso en el PC, con cwd
en la carpeta del proyecto. El telefono manda lineas por WebSocket y recibe
el stream de salida. Cobertura de comandos: TOTAL por construccion — es el
mismo REPL que la terminal, incluidos /hacer, /crear, /esfuerzo, /oficina y
cualquier comando futuro sin tocar la app.

    python -m cognia.remoto            # sirve en 0.0.0.0:8777
    # en el celular:  http://<IP-del-PC>:8777
"""

from .servidor import crear_app, main  # noqa: F401
