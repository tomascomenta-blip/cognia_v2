---
title: Oficina — jefe/directores/trabajadores (:8766)
type: entity
tags: [oficina, dashboard, jerarquia, trabajadores, 3d]
updated: 2026-07-16
---

# Oficina

→ [[index]]

## Que es

`cognia/oficina/` — orquestacion jerarquica sobre la maquinaria real:
el JEFE descompone la meta en directivas (orch.infer, el mismo
orquestador del CLI); cada DIRECTOR descompone su directiva en subtareas
con rol (investigador | implementador); cada TRABAJADOR ejecuta con
`cli._run_agent_task` (el agent loop ReAct real, tools acotadas por rol).

## Honestidad del motor (3.9.1)

Un trabajador que devuelve error o vacio se marca FALLIDA (no "hecha");
una meta donde todos los trabajadores fallaron cierra FALLIDA. Sin modelo
cargable no hay planificacion ni trabajo: se registra el fallo (nada de
resultados simulados).

## Control externo real

El hook de print del agent loop se llama en cada paso; detener/pausar
desde el dashboard lanza Detenida/Pausada y corta el trabajo a mitad de
ejecucion.

## Puertos y despliegue

Dashboard en **:8766** (movido de 8765 en 3.9.1: el 8765 es del backend
del desktop — colision cuando conviven). El build Vite de la oficina 3D
(`cognia/oficina/web3d/dist`) viaja en el wheel; `python -m cognia.oficina`
aplica `apply_config()` como todos los entry points.

## Links

- [[entities/agente]]
- [[entities/cognia_desktop_api]]
- [[concepts/install_model]]
