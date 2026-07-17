---
title: Agente — loop ReAct /hacer con formato ACCION
type: entity
tags: [agente, hacer, react, accion, tools, pasos]
updated: 2026-07-16
---

# Agente (/hacer)

→ [[index]]

## Que es

El loop ReAct de produccion: `/hacer <tarea>` ejecuta un ciclo
pensar→ACCION→observar con las tools reales de `cognia/agent/tools.py`
(escribir/leer/copiar archivos, generar_codigo, buscar, ejecutar, KG,
escenas LCD, delegar_subtarea por rol, etc.). El modelo emite lineas
`ACCION: <tool> <args>` — formato texto plano, NO JSON (medido: el 3B
sostiene ACCION y rompe JSON).

## Presupuesto dinamico de pasos

`cognia/agent/loop.py` — el presupuesto de pasos se decide por tarea
(no 12 fijos), con techo duro. El perfil hibrido lo multiplica por
`pasos_factor` (0.5 en esfuerzo bajo, 1.5 en maximo) y acota
`delegacion_max` (profundidad de sub-agentes).

## Robustez medida contra el 3B

- `first_action_block()`: el 3B emite VARIAS lineas ACCION por respuesta;
  se recorta al primer bloque (antes ejecutaba una accion corrupta).
- Corte por no-progreso + max_tokens acotado en busqueda (fix del cuelgue
  3.8.4) — sin repeat_penalty alto (la regresion 3.8.4→3.8.5: 1.3
  empujaba al 3B a basura, /hacer 0/5).
- Experto LoRA `accion` activo durante toda la tarea de agente
  ([[entities/fleet_registry]]).

## Verificacion

Gate pre-release: `scripts/e2e_happy_path.py` (5 tareas /hacer con
postcondicion, modelo real) — el pytest NO ejecuta el agente con modelo
real, por eso el e2e es obligatorio antes de cada release.

## Links

- [[entities/hybrid_router]]
- [[concepts/colonia]]
- [[entities/oficina]]
