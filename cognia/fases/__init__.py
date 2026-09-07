# -*- coding: utf-8 -*-
"""
cognia/fases — construir un PRODUCTO por fases con puertas de salida (2026-09-07).

Pedido del dueno: "que construya por fases: el modelo construye, otro proceso
intenta romperlo, las pruebas reales deciden si funciona, un juez compara la
version nueva contra la mejor anterior y nunca se acepta un cambio que no
demuestre mejora neta".

Piezas (cada una es un modulo plano, sin framework):

  estado.py       el PROJECT STATE durable en <workspace>/.cognia_fases/
                  (fase actual, Definicion de Hecho, issues P0-P4, versiones,
                  sistemas estables / no tocar) + su render para el modelo.
  dod.py          la Definicion de Hecho: requisitos funcionales, visuales y
                  de calidad, cada uno con una VERIFICACION ejecutable
                  (tests, ejecutar, probar, guion, app) o manual.
  verificador.py  corre la DoD con las tools reales (probar, renderizar,
                  app_probar, tests...) y mide: requisitos OK, tests, errores de
                  consola, tracebacks, capturas por version, visual (VLM si hay).
  juez.py         compara la version nueva contra la ultima ACEPTADA:
                  aceptar / rechazar / sin cambios, con motivos.
  versiones.py    git como memoria de versiones: snapshot por iteracion
                  aceptada y REVERT real cuando el juez rechaza.
  pipeline.py     las fases (planificar, prototipo, completar, robustez, visual,
                  pulido, optimizacion, red team, regresion, release), sus
                  prompts por rol y el bucle analizar -> implementar -> probar
                  -> juzgar -> aceptar/revertir.
  tools_fases.py  las tools con las que el agente escribe en el estado
                  (fases_estado, fases_dod, fases_issue, fases_hipotesis,
                  fases_estable).

Puertas: `/fases` en el REPL y `cognia fases "<encargo>"` fuera de el.
"""
